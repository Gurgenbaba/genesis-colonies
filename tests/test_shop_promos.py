"""Creator promo codes — pricing, bridge, ledger hold."""

from __future__ import annotations

import time
import uuid

import pytest

from game.db import db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.referrals import apply_referral_code, ensure_referral_code
from game.shop import create_pending_order, fulfill_order, get_order, start_checkout
from game.shop_promos import (
    ack_partner_terms,
    create_creator,
    create_promo_code,
    create_payout_batch,
    creator_overview,
    get_promo_by_code,
    list_ledger,
    price_breakdown,
    release_held_commissions,
    resolve_referrer_player_id,
    schema_ready,
)


@pytest.fixture
def promo_db(tmp_path, monkeypatch):
    db_path = tmp_path / "promo.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    monkeypatch.setenv("CREATOR_COMMISSION_HOLD_SEC", "0")
    monkeypatch.setenv("CREATOR_MIN_PAYOUT_CENTS", "1")
    monkeypatch.setenv("CREATOR_MIN_BUYER_SCORE", "0")
    monkeypatch.setenv("CREATOR_BUYER_ACTIVE_WINDOW_SEC", "0")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _user(prefix: str) -> int:
    conn = db()
    ok, err, user = create_user(f"{prefix}_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name=prefix.title(), conn=conn)
    conn.commit()
    conn.close()
    return uid


def test_price_breakdown_defaults():
    br = price_breakdown(1000, 1000, 1000)
    assert br["paid_cents"] == 900
    assert br["discount_cents"] == 100
    assert br["commission_cents"] == 100


def test_promo_checkout_and_ledger(promo_db):
    creator_uid = _user("creator")
    buyer_uid = _user("buyer")
    conn = db()
    assert schema_ready(conn)
    ok, reason, creator = create_creator(
        conn=conn, display_name="StreamX", player_id=creator_uid
    )
    assert ok, reason
    ok, reason, promo = create_promo_code(
        conn=conn, creator_id=int(creator["id"]), code="STREAMX"
    )
    assert ok, reason
    assert get_promo_by_code("streamx", conn=conn)["code"] == "STREAMX"
    assert resolve_referrer_player_id("STREAMX", conn=conn) == creator_uid

    ok, reason, result = start_checkout(
        buyer_uid,
        "tk_pack_s",
        "test",
        conn=conn,
        success_url="http://localhost/ok",
        cancel_url="http://localhost/cancel",
        legal_ack=True,
        promo_code="STREAMX",
    )
    assert ok, reason
    order = result["order"]
    assert int(order["amount_cents"]) == 90  # 99 - floor(99*0.1) = 90
    assert int(order["list_amount_cents"]) == 99
    assert int(order["commission_cents"]) == 9
    assert int(order["discount_cents"]) == 9
    assert order["status"] == "fulfilled"
    rows = list_ledger(int(creator["id"]), conn=conn)
    assert len(rows) == 1
    assert rows[0]["status"] == "available"
    conn.commit()
    conn.close()


def test_promo_self_use_blocked(promo_db):
    creator_uid = _user("selfc")
    conn = db()
    ok, _, creator = create_creator(conn=conn, display_name="Self", player_id=creator_uid)
    assert ok
    ok, _, _ = create_promo_code(conn=conn, creator_id=int(creator["id"]), code="SELFCODE")
    assert ok
    ok, reason, _ = create_pending_order(
        creator_uid, "tk_pack_s", "test", conn=conn, promo_code="SELFCODE"
    )
    assert not ok
    assert reason == "promo_self_not_allowed"
    conn.close()


def test_referral_bridge_with_promo_code(promo_db):
    creator_uid = _user("refc")
    recruit_uid = _user("recr")
    conn = db()
    ok, _, creator = create_creator(conn=conn, display_name="Ref", player_id=creator_uid)
    assert ok
    ok, _, promo = create_promo_code(
        conn=conn, creator_id=int(creator["id"]), code="REFBRIDGE"
    )
    assert ok
    ensure_referral_code(creator_uid, conn=conn)
    ok, reason = apply_referral_code(recruit_uid, "REFBRIDGE", "1.2.3.4", conn=conn)
    assert ok, reason
    conn.commit()
    conn.close()


def test_hold_then_release_and_payout(promo_db, monkeypatch):
    monkeypatch.setenv("CREATOR_COMMISSION_HOLD_SEC", str(7 * 24 * 3600))
    monkeypatch.setenv("CREATOR_MIN_BUYER_SCORE", "50")
    monkeypatch.setenv("CREATOR_BUYER_ACTIVE_WINDOW_SEC", str(7 * 24 * 3600))
    creator_uid = _user("holdc")
    buyer_uid = _user("holdb")
    conn = db()
    # Make buyer brand new so hold applies
    now = time.time()
    conn.execute(
        "UPDATE users SET registered_at = ? WHERE id = ?;",
        (now, buyer_uid),
    )
    conn.execute(
        "UPDATE players SET last_seen = ? WHERE id = ?;",
        (now, buyer_uid),
    )
    ok, _, creator = create_creator(conn=conn, display_name="Hold", player_id=creator_uid)
    ok, _, _ = create_promo_code(conn=conn, creator_id=int(creator["id"]), code="HOLDME")
    ok, reason, created = create_pending_order(
        buyer_uid, "tk_pack_s", "test", conn=conn, promo_code="HOLDME"
    )
    assert ok, reason
    order = created["order"]
    from game.shop import mark_paid

    mark_paid(int(order["id"]), conn=conn, provider_payment_id="t1")
    fok, freason, fulfilled = fulfill_order(int(order["id"]), conn=conn)
    assert fok, freason
    rows = list_ledger(int(creator["id"]), conn=conn)
    assert rows[0]["status"] == "held"
    # Age buyer + score + recent activity
    conn.execute(
        "UPDATE users SET registered_at = ? WHERE id = ?;",
        (now - 8 * 24 * 3600, buyer_uid),
    )
    conn.execute(
        "UPDATE players SET last_seen = ? WHERE id = ?;",
        (now, buyer_uid),
    )
    conn.execute(
        """
        INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
        VALUES (?, 200, 0, 0, ?)
        ON CONFLICT(player_id) DO UPDATE SET score_total = excluded.score_total;
        """,
        (buyer_uid, now),
    )
    released = release_held_commissions(conn=conn)
    assert released >= 1
    rows = list_ledger(int(creator["id"]), conn=conn)
    assert rows[0]["status"] == "available"
    ok, reason, batch = create_payout_batch(
        conn=conn,
        creator_id=int(creator["id"]),
        ledger_ids=[int(rows[0]["id"])],
        marked_by=1,
    )
    assert ok, reason
    assert batch["total_cents"] > 0
    conn.commit()
    conn.close()


def test_performance_stats_and_ban_blocks_release(promo_db, monkeypatch):
    from game.shop_promos import buyer_qualifies_for_commission, creator_performance_stats

    monkeypatch.setenv("CREATOR_COMMISSION_HOLD_SEC", "0")
    monkeypatch.setenv("CREATOR_MIN_BUYER_SCORE", "0")
    monkeypatch.setenv("CREATOR_BUYER_ACTIVE_WINDOW_SEC", "0")
    creator_uid = _user("perfc")
    recruit_uid = _user("perfr")
    conn = db()
    ok, _, creator = create_creator(conn=conn, display_name="Perf", player_id=creator_uid)
    create_promo_code(conn=conn, creator_id=int(creator["id"]), code="PERFCODE")
    apply_referral_code(recruit_uid, "PERFCODE", "9.9.9.9", conn=conn)
    now = time.time()
    conn.execute("UPDATE players SET last_seen = ? WHERE id = ?;", (now, recruit_uid))
    perf = creator_performance_stats(int(creator["id"]), conn=conn)
    assert perf["registrations"] >= 1
    assert perf["active_7d"] >= 1
    assert perf["code"] == "PERFCODE"
    # Ban blocks qualification
    conn.execute(
        "UPDATE players SET banned_until = ? WHERE id = ?;",
        (now + 86400, recruit_uid),
    )
    ok_q, reason_q = buyer_qualifies_for_commission(recruit_uid, conn=conn, now=now)
    assert not ok_q
    assert reason_q == "buyer_banned"
    conn.commit()
    conn.close()


def test_creator_overview_terms(promo_db):
    uid = _user("dash")
    conn = db()
    ok, _, creator = create_creator(conn=conn, display_name="Dash", player_id=uid)
    assert ok
    create_promo_code(conn=conn, creator_id=int(creator["id"]), code="DASHCODE")
    ok, reason, overview = creator_overview(uid, conn=conn)
    assert ok, reason
    assert overview["terms_required"] is True
    ack_partner_terms(uid, conn=conn)
    ok, reason, overview = creator_overview(uid, conn=conn)
    assert ok
    assert overview["terms_required"] is False
    conn.commit()
    conn.close()
