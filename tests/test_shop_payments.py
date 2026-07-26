"""
EPIC-23 — Shop / Payment contracts.

Run: python -m pytest tests/test_shop_payments.py -v
"""

from __future__ import annotations

import json
import uuid

import pytest

from game.battle_pass import ensure_default_season, unlock_premium
from game.db import db
from game.inventory import inventory_amount
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.shop import (
    ALLOWED_KINDS,
    CATALOG_VERSION,
    DEFAULT_CATALOG,
    SKU_SEASON_PASS,
    fulfill_order,
    get_order,
    is_shop_enabled,
    list_catalog,
    mark_paid,
    process_paid_event,
    schema_ready,
    serialize_catalog_for_client,
    start_checkout,
)
from game.timekeeper import get_balance

# Free-Baseline anchors (GC-2313) — Paid must beat these.
FREE_LOGIN_MONTH_TK_SEC = int(2.6 * 3600)  # ~2.6h flexible TK / login month
FREE_LOGIN_MONTH_BUILD_SKIP_H = 140  # ~domain build skip hours / active free month


@pytest.fixture
def shop_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shop.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player():
    conn = db()
    ok, err, user = create_user(f"shop_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="ShopTester", conn=conn)
    ensure_default_season(conn)
    conn.commit()
    conn.close()
    return uid


def test_catalog_kinds_policy_only(shop_db):
    conn = db()
    assert schema_ready(conn)
    assert CATALOG_VERSION >= 3
    products = list_catalog(conn=conn)
    assert products
    skus = {p["sku"] for p in products}
    assert SKU_SEASON_PASS in skus
    for p in products:
        assert p["kind"] in ALLOWED_KINDS
        assert "ship_" not in p["sku"]
        assert int(p["price_cents"]) <= 999
        payload = p["payload"]
        for item in payload.get("items") or []:
            key = str(item.get("item_key") or "")
            assert not key.startswith(("ship_", "defense_"))
            assert key not in ("metal", "crystal", "fuel_cells")
    # Default catalog matches seed
    assert {e["sku"] for e in DEFAULT_CATALOG} <= skus
    by_sku = {e["sku"]: e for e in DEFAULT_CATALOG}
    assert by_sku[SKU_SEASON_PASS]["price_cents"] == 499
    assert by_sku["commander_supply_pack"]["price_cents"] == 999
    conn.close()


def test_catalog_v3_beats_free_baseline(shop_db):
    """Paid yields must beat Free-Baseline anchors (TK scarcity, booster density)."""
    by_sku = {e["sku"]: e for e in DEFAULT_CATALOG}

    tk_s = int(by_sku["tk_pack_s"]["payload"]["timekeeper_sec"])
    tk_m = int(by_sku["tk_pack_m"]["payload"]["timekeeper_sec"])
    tk_l = int(by_sku["tk_pack_l"]["payload"]["timekeeper_sec"])
    assert tk_s >= 6 * 3600
    assert tk_s > FREE_LOGIN_MONTH_TK_SEC
    assert tk_m >= 24 * 3600
    assert tk_l >= 72 * 3600

    booster_items = {
        str(i["item_key"]): int(i["amount"])
        for i in by_sku["booster_pack_starter"]["payload"]["items"]
    }
    build_skip_h = (
        booster_items.get("booster_build_24h", 0) * 24
        + booster_items.get("booster_build_6h", 0) * 6
    )
    research_skip_h = (
        booster_items.get("booster_research_24h", 0) * 24
        + booster_items.get("booster_research_6h", 0) * 6
    )
    # Catalog v3 target: ≥ ~176 h/domain and must beat one free login-month (~140 h).
    assert build_skip_h >= 176
    assert research_skip_h >= 176
    assert build_skip_h > FREE_LOGIN_MONTH_BUILD_SKIP_H
    assert research_skip_h > FREE_LOGIN_MONTH_BUILD_SKIP_H

    cont = {
        str(i["item_key"]): int(i["amount"])
        for i in by_sku["container_pack_rare"]["payload"]["items"]
    }
    assert cont.get("container_rare", 0) >= 8
    assert cont.get("container_epic", 0) >= 4
    assert cont.get("container_mythic", 0) >= 2
    assert cont.get("container_relic", 0) >= 1

    cmd = by_sku["commander_supply_pack"]
    assert int(cmd["payload"]["timekeeper_sec"]) >= 48 * 3600
    cmd_items = {
        str(i["item_key"]): int(i["amount"]) for i in cmd["payload"]["items"]
    }
    assert cmd_items.get("container_mythic", 0) >= 3
    assert cmd_items.get("container_ancient_relic", 0) >= 2
    assert cmd_items.get("booster_build_24h", 0) >= 6


def test_shop_disabled_blocks_checkout(shop_db, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "0")
    assert is_shop_enabled() is False
    uid = _player()
    conn = db()
    ok, reason, result = start_checkout(
        uid,
        "tk_pack_s",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok is False
    assert reason == "shop_disabled"
    assert result is None
    conn.close()


def test_fulfill_season_pass_sets_entitlement(shop_db):
    uid = _player()
    conn = db()
    ok, reason, result = start_checkout(
        uid,
        SKU_SEASON_PASS,
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok, reason
    assert result["fulfilled"] is True
    order = result["order"]
    assert order["status"] == "fulfilled"
    conn.commit()

    from game.battle_pass import serialize_for_client

    bp = serialize_for_client(uid, conn=conn, include_tracks=False)
    assert bp.get("premium_unlocked") is True

    # Second purchase rejected at checkout
    ok2, reason2, _ = start_checkout(
        uid,
        SKU_SEASON_PASS,
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok2 is False
    assert reason2 == "already_owned"
    conn.close()


def test_fulfill_order_idempotent(shop_db):
    uid = _player()
    conn = db()
    ok, reason, created = start_checkout(
        uid,
        "tk_pack_s",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok, reason
    oid = int(created["order_id"])
    bal1 = get_balance(uid, conn=conn)
    ok2, reason2, out2 = fulfill_order(oid, conn=conn)
    assert ok2 is True
    assert reason2 == "already_fulfilled"
    assert get_balance(uid, conn=conn) == bal1
    conn.close()


def test_fulfill_tk_and_inventory_packs(shop_db):
    uid = _player()
    conn = db()
    before_tk = get_balance(uid, conn=conn)
    ok, reason, _ = start_checkout(
        uid,
        "tk_pack_s",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok, reason
    assert get_balance(uid, conn=conn) >= before_tk + 6 * 3600

    before_m = get_balance(uid, conn=conn)
    ok, reason, _ = start_checkout(
        uid,
        "tk_pack_m",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok, reason
    assert get_balance(uid, conn=conn) >= before_m + 24 * 3600

    before_rare = inventory_amount(uid, "container_rare", conn=conn)
    ok, reason, _ = start_checkout(
        uid,
        "container_pack_rare",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok, reason
    assert inventory_amount(uid, "container_rare", conn=conn) >= before_rare + 8
    assert inventory_amount(uid, "container_epic", conn=conn) >= 4
    assert inventory_amount(uid, "container_mythic", conn=conn) >= 2
    assert inventory_amount(uid, "container_relic", conn=conn) >= 1

    ok, reason, _ = start_checkout(
        uid,
        "booster_pack_starter",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok, reason
    assert inventory_amount(uid, "booster_build_6h", conn=conn) >= 8
    assert inventory_amount(uid, "booster_build_24h", conn=conn) >= 6
    assert inventory_amount(uid, "booster_research_24h", conn=conn) >= 6

    before_cmd = get_balance(uid, conn=conn)
    ok, reason, _ = start_checkout(
        uid,
        "commander_supply_pack",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
    )
    assert ok, reason
    assert get_balance(uid, conn=conn) >= before_cmd + 48 * 3600
    assert inventory_amount(uid, "container_ancient_relic", conn=conn) >= 2
    assert inventory_amount(uid, "container_mythic", conn=conn) >= 5  # 2 from rare pack + 3
    conn.commit()
    conn.close()


def test_process_paid_event_duplicate(shop_db):
    uid = _player()
    conn = db()
    from game.shop import create_pending_order, attach_provider_session

    ok, reason, created = create_pending_order(uid, "tk_pack_s", "stripe", conn=conn)
    assert ok, reason
    oid = int(created["order"]["id"])
    attach_provider_session(oid, "cs_test_1", conn=conn)

    ok1, r1, order1 = process_paid_event(
        provider="stripe",
        event_id="evt_1",
        order_id=oid,
        provider_session_id="cs_test_1",
        provider_payment_id="pi_1",
        conn=conn,
        payload={"type": "checkout.session.completed"},
    )
    assert ok1, r1
    assert order1["status"] == "fulfilled"

    ok2, r2, order2 = process_paid_event(
        provider="stripe",
        event_id="evt_1",
        order_id=oid,
        provider_session_id="cs_test_1",
        provider_payment_id="pi_1",
        conn=conn,
        payload={"type": "checkout.session.completed"},
    )
    assert ok2 is True
    assert r2 == "duplicate"
    assert order2["status"] == "fulfilled"
    conn.close()


def test_http_shop_and_checkout_auth(shop_db, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()

    # Unauthenticated checkout
    res = client.post(
        "/api/shop/checkout",
        json={"sku": "tk_pack_s", "provider": "test"},
    )
    assert res.status_code in (401, 302)

    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    page = client.get("/shop")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "shop-page" in body
    assert "Imperium" in body or "shop" in body.lower()

    cat = client.get("/api/shop/catalog")
    assert cat.status_code == 200
    payload = cat.get_json()
    assert payload["ok"] is True
    assert payload["shop"]["enabled"] is True
    assert any(p["sku"] == SKU_SEASON_PASS for p in payload["shop"]["products"])

    checkout = client.post(
        "/api/shop/checkout",
        json={"sku": "tk_pack_s", "provider": "test"},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["fulfilled"] is True


def test_stripe_webhook_rejects_bad_signature(shop_db, monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()
    res = client.post(
        "/api/webhooks/stripe",
        data=b'{"id":"evt_x"}',
        headers={"Stripe-Signature": "t=1,v1=deadbeef", "Content-Type": "application/json"},
    )
    assert res.status_code == 400
    assert res.get_json()["reason"] in ("invalid_signature", "stripe_sdk_missing", "webhook_unconfigured")


def test_stripe_webhook_fulfill_via_mock(shop_db, monkeypatch):
    uid = _player()
    conn = db()
    from game.shop import attach_provider_session, create_pending_order

    ok, reason, created = create_pending_order(uid, SKU_SEASON_PASS, "stripe", conn=conn)
    assert ok, reason
    oid = int(created["order"]["id"])
    attach_provider_session(oid, "cs_live_1", conn=conn)
    conn.commit()
    conn.close()

    event = {
        "id": "evt_mock_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_live_1",
                "client_reference_id": str(oid),
                "payment_intent": "pi_mock_1",
                "metadata": {"order_id": str(oid), "player_id": str(uid), "sku": SKU_SEASON_PASS},
            }
        },
    }

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(
        "game.payment_providers.stripe_verify_and_parse_event",
        lambda payload, sig: (True, "ok", event),
    )

    from app import app

    app.config["TESTING"] = True
    client = app.test_client()
    res = client.post(
        "/api/webhooks/stripe",
        data=json.dumps(event).encode("utf-8"),
        headers={"Stripe-Signature": "t=1,v1=mock", "Content-Type": "application/json"},
    )
    assert res.status_code == 200
    assert res.get_json()["ok"] is True

    conn = db()
    order = get_order(oid, conn=conn)
    assert order["status"] == "fulfilled"
    from game.battle_pass import serialize_for_client

    bp = serialize_for_client(uid, conn=conn, include_tracks=False)
    assert bp.get("premium_unlocked") is True
    conn.close()


def test_serialize_hides_payload(shop_db):
    uid = _player()
    conn = db()
    state = serialize_catalog_for_client(conn=conn, player_id=uid)
    assert "payload" not in state["products"][0]
    assert "display" in state["products"][0]
    conn.close()


def test_recover_paypal_return_creates_and_fulfills(shop_db, monkeypatch):
    """Orphaned PayPal COMPLETED order → grant for logged-in player (local→prod fix)."""
    from game.shop import recover_paypal_return_for_player
    from game import payment_providers as pp

    uid = _player()
    paypal_oid = "PAYPAL_ORPHAN_TK_S"

    def fake_fetch(_oid):
        return True, "ok", {
            "id": paypal_oid,
            "status": "COMPLETED",
            "purchase_units": [
                {
                    "description": "tk_pack_s",
                    "amount": {"currency_code": "EUR", "value": "0.99"},
                    "payments": {
                        "captures": [
                            {
                                "id": "CAP_ORPHAN_1",
                                "status": "COMPLETED",
                                "amount": {"currency_code": "EUR", "value": "0.99"},
                            }
                        ]
                    },
                }
            ],
        }

    monkeypatch.setattr(pp, "paypal_fetch_order", fake_fetch)

    conn = db()
    before = get_balance(uid, conn=conn)
    ok, reason, order = recover_paypal_return_for_player(uid, paypal_oid, conn=conn)
    assert ok, reason
    assert order and order["status"] == "fulfilled"
    assert order["sku"] == "tk_pack_s"
    assert order["provider_session_id"] == paypal_oid
    after = get_balance(uid, conn=conn)
    assert after > before
    # Idempotent
    ok2, reason2, order2 = recover_paypal_return_for_player(uid, paypal_oid, conn=conn)
    assert ok2, reason2
    assert reason2 in ("already_fulfilled", "duplicate")
    assert get_balance(uid, conn=conn) == after
    conn.commit()
    conn.close()


def test_admin_unlock_still_works(shop_db):
    uid = _player()
    conn = db()
    ok, reason, _ = unlock_premium(uid, conn=conn, source="admin:test")
    assert ok, reason
    conn.commit()
    conn.close()
