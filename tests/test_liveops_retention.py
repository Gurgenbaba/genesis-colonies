"""
EPIC-22 — Login rewards + Battle Pass contracts.

Run: python -m pytest tests/test_liveops_retention.py -v
"""

from __future__ import annotations

import time
import uuid

import pytest

from game.activity_xp import (
    SOURCE_BUILDING_FINISH,
    grant_activity_xp,
)
from game.battle_pass import (
    OP_BUILD,
    PASSIVE_DRIP_DAILY_CAP,
    REWARD_CATALOG_VERSION,
    _default_level_rewards,
    apply_op_progress,
    claim_battle_pass_reward,
    claim_op,
    credit_activity_drip_xp,
    credit_xp,
    ensure_default_season,
    get_active_season,
    schema_ready as bp_ready,
    serialize_for_client as bp_serialize,
    unlock_premium,
)
from game.db import db
from game.inventory import inventory_amount
from game.login_rewards import (
    LOGIN_CYCLE_DAYS,
    LOGIN_REWARD_CATALOG,
    catalog_day,
    claim_login_reward,
    day_bucket,
    ensure_progress,
    schema_ready as lr_ready,
    serialize_for_client as lr_serialize,
)
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.repository import get_context_planet
from game.timekeeper import get_balance


@pytest.fixture
def liveops_db(tmp_path, monkeypatch):
    db_path = tmp_path / "liveops.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player():
    conn = db()
    ok, err, user = create_user(f"lo_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="LiveOpsTester", conn=conn)
    conn.commit()
    conn.close()
    return uid


def test_login_catalog_complete(liveops_db):
    assert len(LOGIN_REWARD_CATALOG) == LOGIN_CYCLE_DAYS
    for i in range(1, 31):
        entry = catalog_day(i)
        assert entry is not None
        assert int(entry["day"]) == i
        assert entry["items"] or entry["timekeeper_sec"] > 0


def test_login_claim_day1_grants_items_and_tk(liveops_db):
    uid = _player()
    conn = db()
    assert lr_ready(conn)
    ok, reason, result = claim_login_reward(uid, conn=conn)
    assert ok, reason
    assert result["day"] == 1
    conn.commit()
    assert inventory_amount(uid, "container_basic", conn=conn) >= 1
    assert get_balance(uid, conn=conn) >= 300
    state = lr_serialize(uid, conn=conn, include_calendar=True)
    assert state["available"] is False
    assert state["reason"] == "already_claimed_today"
    assert state["current_day"] == 1
    conn.close()


def test_login_streak_resets_on_missed_day(liveops_db):
    uid = _player()
    conn = db()
    t0 = 1_700_000_000.0
    ok, reason, _ = claim_login_reward(uid, conn=conn, now=t0)
    assert ok, reason
    # Next UTC day → day 2
    t1 = t0 + 86400
    ok, reason, result = claim_login_reward(uid, conn=conn, now=t1)
    assert ok, reason
    assert result["day"] == 2
    # Skip a day → reset, claim is day 1 again
    t3 = t1 + 2 * 86400
    progress = ensure_progress(uid, conn=conn, now=t3)
    assert int(progress["current_day"]) == 0
    ok, reason, result = claim_login_reward(uid, conn=conn, now=t3)
    assert ok, reason
    assert result["day"] == 1
    conn.commit()
    conn.close()


def test_login_cannot_double_claim_same_day(liveops_db):
    uid = _player()
    conn = db()
    t0 = time.time()
    ok, _, _ = claim_login_reward(uid, conn=conn, now=t0)
    assert ok
    ok2, reason, _ = claim_login_reward(uid, conn=conn, now=t0 + 10)
    assert not ok2
    assert reason == "already_claimed_today"
    conn.close()


def test_battle_pass_xp_and_free_claim(liveops_db):
    uid = _player()
    conn = db()
    assert bp_ready(conn)
    season = get_active_season(conn)
    assert season is not None
    credited = credit_xp(uid, int(season["xp_per_level"]), conn=conn)
    assert credited["granted"] is True
    assert credited["level"] >= 1
    ok, reason, result = claim_battle_pass_reward(uid, 1, "free", conn=conn)
    assert ok, reason
    assert result["track"] == "free"
    ok2, reason2, _ = claim_battle_pass_reward(uid, 1, "free", conn=conn)
    assert not ok2
    assert reason2 == "already_claimed"
    conn.commit()
    conn.close()


def test_battle_pass_premium_gate_and_unlock(liveops_db):
    uid = _player()
    conn = db()
    season = get_active_season(conn)
    credit_xp(uid, int(season["xp_per_level"]) * 2, conn=conn)
    ok, reason, _ = claim_battle_pass_reward(uid, 1, "premium", conn=conn)
    assert not ok
    assert reason == "premium_required"
    uok, ureason, _ = unlock_premium(uid, conn=conn, source="test")
    assert uok, ureason
    ok2, reason2, result = claim_battle_pass_reward(uid, 1, "premium", conn=conn)
    assert ok2, reason2
    assert result["track"] == "premium"
    state = bp_serialize(uid, conn=conn, include_tracks=True)
    assert state["premium_unlocked"] is True
    assert state["claimable_count"] >= 1  # level 2 free still open
    conn.commit()
    conn.close()


def test_battle_pass_premium_catalog_cracks(liveops_db):
    """Premium must dwarf Free so paying feels inevitable (catalog v3+)."""
    assert REWARD_CATALOG_VERSION >= 3
    free1, prem1 = _default_level_rewards(1)
    assert int(prem1["timekeeper_sec"]) >= 3600
    assert sum(int(i["amount"]) for i in prem1["items"]) >= 5
    assert int(free1.get("timekeeper_sec") or 0) < int(prem1["timekeeper_sec"])

    free10, prem10 = _default_level_rewards(10)
    prem10_keys = {i["item_key"] for i in prem10["items"]}
    assert "container_epic" in prem10_keys or "container_relic" in prem10_keys
    assert int(prem10["timekeeper_sec"]) >= 6 * 3600
    assert sum(int(i["amount"]) for i in prem10["items"]) > sum(
        int(i["amount"]) for i in free10["items"]
    )

    _, prem50 = _default_level_rewards(50)
    prem50_keys = {i["item_key"] for i in prem50["items"]}
    assert "container_void_artifact" in prem50_keys
    assert "container_mythic" in prem50_keys
    void_amt = next(i["amount"] for i in prem50["items"] if i["item_key"] == "container_void_artifact")
    assert int(void_amt) >= 2
    assert int(prem50["timekeeper_sec"]) >= 48 * 3600

    conn = db()
    sid = ensure_default_season(conn)
    assert sid is not None
    # Stale weak L50 → ensure reseeds on next ensure call
    conn.execute(
        """
        UPDATE battle_pass_levels
        SET premium_reward_json = ?
        WHERE season_id = ? AND level = 50;
        """,
        ('{"items":[{"item_key":"booster_build_5m","amount":1}],"timekeeper_sec":0}', sid),
    )
    ensure_default_season(conn)
    row = conn.execute(
        "SELECT premium_reward_json FROM battle_pass_levels WHERE season_id = ? AND level = 50;",
        (sid,),
    ).fetchone()
    assert "container_void_artifact" in str(row["premium_reward_json"])
    conn.commit()
    conn.close()


def test_activity_xp_hooks_battle_pass(liveops_db):
    uid = _player()
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    assert planet
    before = bp_serialize(uid, conn=conn)
    grant_activity_xp(
        uid,
        int(planet["id"]),
        SOURCE_BUILDING_FINISH,
        conn=conn,
        idempotency_key=f"test-bp-{uuid.uuid4().hex}",
    )
    after = bp_serialize(uid, conn=conn)
    assert int(after["xp"]) >= int(before.get("xp") or 0) + 1
    ops = after.get("ops") or {}
    daily = {row["op_key"]: row for row in (ops.get("daily") or [])}
    assert OP_BUILD in daily
    assert int(daily[OP_BUILD]["progress"]) >= 1
    conn.commit()
    conn.close()


def test_battle_pass_op_key_lists_are_iterable_keys(liveops_db):
    """Regression: single-string WEEKLY_OP_KEYS would iterate chars ('o') and 500 /premium."""
    from game.battle_pass import DAILY_OP_KEYS, OPS_CATALOG, WEEKLY_OP_KEYS

    assert isinstance(DAILY_OP_KEYS, list)
    assert isinstance(WEEKLY_OP_KEYS, list)
    for key in list(DAILY_OP_KEYS) + list(WEEKLY_OP_KEYS):
        assert len(key) > 1
        assert key in OPS_CATALOG


def test_battle_pass_ops_claim_and_no_double(liveops_db):
    uid = _player()
    conn = db()
    apply_op_progress(uid, SOURCE_BUILDING_FINISH, conn=conn)
    state = bp_serialize(uid, conn=conn)
    build = next(o for o in state["ops"]["daily"] if o["op_key"] == OP_BUILD)
    assert build["claimable"] is True
    before_xp = int(state["xp"])
    ok, reason, result = claim_op(uid, OP_BUILD, conn=conn)
    assert ok, reason
    assert int(result["xp_reward"]) == 30
    assert int(result["xp"]) == before_xp + 30
    ok2, reason2, _ = claim_op(uid, OP_BUILD, conn=conn)
    assert not ok2
    assert reason2 == "already_claimed"
    conn.commit()
    conn.close()


def test_battle_pass_passive_drip_soft_cap(liveops_db):
    uid = _player()
    conn = db()
    first = credit_activity_drip_xp(uid, PASSIVE_DRIP_DAILY_CAP, conn=conn)
    assert first["granted"] is True
    assert int(first["amount"]) == PASSIVE_DRIP_DAILY_CAP
    second = credit_activity_drip_xp(uid, 10, conn=conn)
    assert second["granted"] is False
    assert second["reason"] == "daily_drip_cap"
    assert int(second["amount"]) == 0
    state = bp_serialize(uid, conn=conn)
    assert int(state["ops"]["drip_today"]) == PASSIVE_DRIP_DAILY_CAP
    assert int(state["xp"]) == PASSIVE_DRIP_DAILY_CAP
    conn.commit()
    conn.close()


def test_day_bucket_stable():
    assert day_bucket(86400 * 10) == 10
    assert day_bucket(86400 * 10 + 86399) == 10


def test_login_and_battle_pass_http_claim(liveops_db):
    import importlib

    import app as app_mod
    from game.models import ensure_player_and_homeworld

    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    ok, err, user = create_user(f"http_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    ensure_player_and_homeworld(uid, player_name="HttpOps", conn=conn)
    conn.commit()
    conn.close()

    with client.session_transaction() as sess:
        sess["user_id"] = uid

    # Jinja must use day['items'] / free['items'] — bare .items is dict.items().
    lr_page = client.get("/login-rewards")
    assert lr_page.status_code == 200
    assert "login-rewards-page" in lr_page.get_data(as_text=True)
    prem_page = client.get("/premium")
    assert prem_page.status_code == 200
    prem_html = prem_page.get_data(as_text=True)
    assert "battle-pass-page" in prem_html or "premium-page" in prem_html
    assert "battle-pass-ops-panel" in prem_html
    assert "data-bp-claim-op" in prem_html or "bp_ops" in prem_html or "Season Ops" in prem_html

    lr = client.post(
        "/api/login-rewards/claim",
        json={"request_id": f"lr-{uuid.uuid4().hex}"},
        content_type="application/json",
    )
    assert lr.status_code == 200
    body = lr.get_json()
    assert body["ok"] is True
    assert body["day"] == 1
    assert "state" in body
    assert body["state"].get("login_rewards", {}).get("available") is False

    # Earn BP XP then claim free L1
    conn = db()
    season = get_active_season(conn)
    credit_xp(uid, int(season["xp_per_level"]), conn=conn)
    conn.commit()
    conn.close()

    bp = client.post(
        "/api/battle-pass/claim",
        json={"level": 1, "track": "free", "request_id": f"bp-{uuid.uuid4().hex}"},
        content_type="application/json",
    )
    assert bp.status_code == 200
    bp_body = bp.get_json()
    assert bp_body["ok"] is True
    assert bp_body["track"] == "free"
    assert "battle_pass" in bp_body

    # Complete build op via gameplay hook, then claim-op API
    conn = db()
    apply_op_progress(uid, SOURCE_BUILDING_FINISH, conn=conn)
    conn.commit()
    conn.close()
    op = client.post(
        "/api/battle-pass/claim-op",
        json={"op_key": OP_BUILD, "request_id": f"bp-op-{uuid.uuid4().hex}"},
        content_type="application/json",
    )
    assert op.status_code == 200
    op_body = op.get_json()
    assert op_body["ok"] is True
    assert op_body["op_key"] == OP_BUILD
    assert int(op_body["xp_reward"]) == 30
    assert "battle_pass" in op_body
    assert "state" in op_body
