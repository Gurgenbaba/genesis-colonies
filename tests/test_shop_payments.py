"""
EPIC-23 — Shop / Payment contracts.

Run: python -m pytest tests/test_shop_payments.py -v
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

from game.battle_pass import ensure_default_season, unlock_premium
from game.db import db
from game.inventory import inventory_amount
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.shop import (
    ALLOWED_KINDS,
    CATALOG_VERSION,
    DEFAULT_CATALOG,
    IMPULSE_TRIO_SKUS,
    SHOP_SKU_UI_BADGES,
    SKU_GENESIS_ACCELERATOR,
    SKU_HYPERDRIVE_PROTOCOL,
    SKU_SEASON_PASS,
    SKU_TITAN_SLOT_PLUS,
    create_pending_order,
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
    assert CATALOG_VERSION >= 7
    products = list_catalog(conn=conn)
    assert products
    skus = {p["sku"] for p in products}
    assert SKU_SEASON_PASS in skus
    assert SKU_GENESIS_ACCELERATOR in skus
    assert SKU_HYPERDRIVE_PROTOCOL in skus
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
    assert by_sku[SKU_GENESIS_ACCELERATOR]["price_cents"] == 499
    assert by_sku[SKU_HYPERDRIVE_PROTOCOL]["price_cents"] == 699
    assert by_sku["commander_supply_pack"]["price_cents"] == 999
    conn.close()


def test_impulse_trio_catalog_and_ui_badges(shop_db):
    """Goldilocks ladder: Starter decoy → Accelerator BEST VALUE → Hyperdrive anchor."""
    by_sku = {e["sku"]: e for e in DEFAULT_CATALOG}
    assert IMPULSE_TRIO_SKUS == (
        "booster_pack_starter",
        SKU_GENESIS_ACCELERATOR,
        SKU_HYPERDRIVE_PROTOCOL,
    )
    assert by_sku[SKU_GENESIS_ACCELERATOR]["sort_order"] == 52
    assert by_sku[SKU_HYPERDRIVE_PROTOCOL]["sort_order"] == 58
    assert SHOP_SKU_UI_BADGES[SKU_GENESIS_ACCELERATOR] == ("new", "best_value")
    assert SHOP_SKU_UI_BADGES[SKU_HYPERDRIVE_PROTOCOL] == ("new", "crazy")

    accel = by_sku[SKU_GENESIS_ACCELERATOR]
    assert int(accel["payload"]["timekeeper_sec"]) >= 48 * 3600
    accel_items = {
        str(i["item_key"]): int(i["amount"]) for i in accel["payload"]["items"]
    }
    assert accel_items.get("booster_build_24h", 0) >= 8
    assert accel_items.get("booster_research_24h", 0) >= 8
    assert accel_items.get("booster_build_6h", 0) + accel_items.get(
        "booster_research_6h", 0
    ) >= 12
    assert accel_items.get("container_epic", 0) >= 2
    assert accel_items.get("container_mythic", 0) >= 1

    hyper = by_sku[SKU_HYPERDRIVE_PROTOCOL]
    assert int(hyper["payload"]["timekeeper_sec"]) >= 72 * 3600
    hyper_items = {
        str(i["item_key"]): int(i["amount"]) for i in hyper["payload"]["items"]
    }
    assert hyper_items.get("booster_build_24h", 0) >= 10
    assert hyper_items.get("container_ancient_relic", 0) >= 1
    assert hyper_items.get("container_mythic", 0) >= 2

    conn = db()
    client = serialize_catalog_for_client(conn=conn)
    by_client = {p["sku"]: p for p in client["products"]}
    assert "best_value" in by_client[SKU_GENESIS_ACCELERATOR]["display"]["ui_badges"]
    assert "crazy" in by_client[SKU_HYPERDRIVE_PROTOCOL]["display"]["ui_badges"]
    assert "new" in by_client[SKU_GENESIS_ACCELERATOR]["display"]["ui_badges"]
    conn.close()


def test_impulse_trio_template_contract():
    """Shop template must render Commander Favorites trio and exclude them from flat grid."""
    from pathlib import Path

    tpl = (Path(__file__).resolve().parents[1] / "templates" / "shop.html").read_text(
        encoding="utf-8"
    )
    assert 'data-shop-impulse-trio' in tpl
    assert "shop_impulse_title" in tpl
    assert "genesis_accelerator_pack" in tpl
    assert "hyperdrive_protocol_pack" in tpl
    assert "shop-card--best-value" in tpl or "best_value" in tpl
    assert "rejectattr('sku', 'equalto', 'genesis_accelerator_pack')" in tpl
    assert "rejectattr('sku', 'equalto', 'hyperdrive_protocol_pack')" in tpl
    assert "rejectattr('sku', 'equalto', 'booster_pack_starter')" in tpl


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

    # Impulse packs must beat free-month domain skip and Starter density.
    for sku in (SKU_GENESIS_ACCELERATOR, SKU_HYPERDRIVE_PROTOCOL):
        items = {
            str(i["item_key"]): int(i["amount"])
            for i in by_sku[sku]["payload"]["items"]
        }
        build_h = (
            items.get("booster_build_24h", 0) * 24
            + items.get("booster_build_6h", 0) * 6
        )
        research_h = (
            items.get("booster_research_24h", 0) * 24
            + items.get("booster_research_6h", 0) * 6
        )
        assert build_h > FREE_LOGIN_MONTH_BUILD_SKIP_H
        assert research_h > FREE_LOGIN_MONTH_BUILD_SKIP_H
        assert build_h >= build_skip_h
        assert research_h >= research_skip_h

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
        legal_ack=True,
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
        legal_ack=True,
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
        legal_ack=True,
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
        legal_ack=True,
    )
    assert ok, reason
    oid = int(created["order_id"])
    bal1 = get_balance(uid, conn=conn)
    ok2, reason2, out2 = fulfill_order(oid, conn=conn)
    assert ok2 is True
    assert reason2 == "already_fulfilled"
    assert get_balance(uid, conn=conn) == bal1
    conn.close()


def test_build_shop_return_payload_enriched(shop_db):
    from game.shop import (
        SKU_BOOSTER_STARTER,
        build_shop_return_payload,
        ensure_catalog_seeded,
        fulfill_order,
        get_order,
        mark_paid,
    )

    uid = _player()
    conn = db()
    ensure_catalog_seeded(conn)
    empty = build_shop_return_payload(None, conn=conn)
    assert empty["ok"] is False
    assert empty["status_key"] == "unknown"
    assert empty["headline_key"] == "shop_return_unknown_title"

    ok, reason, created = create_pending_order(
        uid, SKU_BOOSTER_STARTER, "test", conn=conn
    )
    assert ok, reason
    oid = int(created["order"]["id"])
    mark_paid(oid, conn=conn, provider_payment_id="pay_return_test")
    ok_f, reason_f, _ = fulfill_order(oid, conn=conn)
    assert ok_f, reason_f
    order = get_order(oid, conn=conn)
    receipt = build_shop_return_payload(order, conn=conn)
    assert receipt["ok"] is True
    assert receipt["status_key"] == "fulfilled"
    assert receipt["headline_key"] == "shop_return_fulfilled_title"
    assert receipt["order_id"] == oid
    assert receipt["amount_label"]
    assert len(receipt["lines"]) >= 1
    line = receipt["lines"][0]
    assert line["sku"] == SKU_BOOSTER_STARTER
    assert line["title_key"] == "shop_sku_booster_starter"
    assert line["qty"] == 1
    assert line.get("image")
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
        legal_ack=True,
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
        legal_ack=True,
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
        legal_ack=True,
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
        legal_ack=True,
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
        legal_ack=True,
    )
    assert ok, reason
    assert get_balance(uid, conn=conn) >= before_cmd + 48 * 3600
    assert inventory_amount(uid, "container_ancient_relic", conn=conn) >= 2
    assert inventory_amount(uid, "container_mythic", conn=conn) >= 5  # 2 from rare pack + 3

    before_accel = get_balance(uid, conn=conn)
    ok, reason, _ = start_checkout(
        uid,
        SKU_GENESIS_ACCELERATOR,
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
        legal_ack=True,
    )
    assert ok, reason
    assert get_balance(uid, conn=conn) >= before_accel + 48 * 3600
    assert inventory_amount(uid, "booster_build_24h", conn=conn) >= 6 + 8
    assert inventory_amount(uid, "container_epic", conn=conn) >= 4 + 2

    before_hyper = get_balance(uid, conn=conn)
    ok, reason, _ = start_checkout(
        uid,
        SKU_HYPERDRIVE_PROTOCOL,
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
        legal_ack=True,
    )
    assert ok, reason
    assert get_balance(uid, conn=conn) >= before_hyper + 72 * 3600
    assert inventory_amount(uid, "container_ancient_relic", conn=conn) >= 2 + 1
    assert inventory_amount(uid, "booster_research_24h", conn=conn) >= 6 + 8 + 10
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


def test_http_checkout_drops_invalid_promo_and_continues(shop_db, monkeypatch):
    """Stale promo in the request must not block PayPal/test checkout."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess["shop_promo_code"] = {
            "code": "DEADCODE",
            "expires_at": time.time() + 3600,
        }

    checkout = client.post(
        "/api/shop/checkout",
        json={
            "sku": "tk_pack_s",
            "provider": "test",
            "legal_ack": True,
            "promo_code": "DEADCODE",
        },
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["fulfilled"] is True
    assert data.get("promo_dropped") == "promo_not_found"
    with client.session_transaction() as sess:
        assert "shop_promo_code" not in sess


def test_shop_legal_ack_is_above_buy_buttons():
    """Checkout acknowledgements must appear before product PayPal CTAs."""
    tpl = (
        Path(__file__).resolve().parent.parent / "templates" / "shop.html"
    ).read_text(encoding="utf-8")
    include_at = tpl.index('{% include "partials/legal_ack.html" %}')
    catalog_at = tpl.index("shop-catalog-body")
    assert include_at < catalog_at
    assert tpl.count('{% include "partials/legal_ack.html" %}') == 1
    assert "shop-policy-panel--checkout" in tpl


def test_http_shop_and_checkout_auth(shop_db, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()

    # Unauthenticated checkout
    res = client.post(
        "/api/shop/checkout",
        json={"sku": "tk_pack_s", "provider": "test", "legal_ack": True},
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
        json={"sku": "tk_pack_s", "provider": "test", "legal_ack": True},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["fulfilled"] is True


def test_http_checkout_skips_game_state_for_external_redirect(shop_db, monkeypatch):
    """PayPal redirect must not depend on heavy _build_game_state_payload."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "0")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test_client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")

    import game.payment_providers as pp
    from app import app

    def fake_paypal_create(**kwargs):
        return True, "ok", {
            "session_id": "PAYPAL_ORDER_TEST",
            "checkout_url": "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL_ORDER_TEST",
        }

    monkeypatch.setattr(pp, "paypal_create_checkout_order", fake_paypal_create)
    monkeypatch.setattr(pp, "paypal_configured", lambda: True)

    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("game_state_must_not_run_for_redirect")

    monkeypatch.setattr("app._build_game_state_payload", boom)

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    checkout = client.post(
        "/api/shop/checkout",
        json={"sku": "tk_pack_s", "provider": "paypal", "legal_ack": True},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["checkout_url"]
    assert data.get("state") == {}
    assert calls["n"] == 0


def test_shop_checkout_client_surfaces_paypal_and_promo_errors():
    """Shop buy path must map provider/promo failures instead of a blind generic toast."""
    src = (
        Path(__file__).resolve().parent.parent / "static" / "main.js"
    ).read_text(encoding="utf-8")
    assert "function _shopCheckoutFailMessage(" in src
    assert "function _shopHandleCheckoutResponse(" in src
    buy = src.split("function bindShopBuyOnce()")[1].split("function initShop()")[0]
    assert "_shopHandleCheckoutResponse" in buy
    assert "shop_paypal_unavailable" in src
    assert "shop_host_mismatch" in src
    assert "shop_invalid_return_url" in src
    assert "shop_promo_blocked_checkout" in src
    assert "canonical_shop_url" in src
    # External checkout must redirect before any HUD apply on empty state:{}.
    handler = src.split("function _shopHandleCheckoutResponse(")[1].split(
        "function _shopActivePromoCode("
    )[0]
    assert "window.location.assign" in handler
    assert "_shopMaybeApplyCheckoutState" in handler
    assert handler.index("checkout_url") < handler.index("_shopMaybeApplyCheckoutState")
    assert "public_host_mismatch" in handler
    assert "canonical_shop_url" in handler
    maybe = src.split("function _shopMaybeApplyCheckoutState(")[1].split(
        "function _shopHandleCheckoutResponse("
    )[0]
    assert "res.checkout_url" in maybe or "checkout_url" in maybe
    assert "server_time" in maybe


def test_live_paypal_accepts_www_apex_alias(shop_db, monkeypatch):
    """www and apex of PUBLIC_BASE_URL must both be allowed for live PayPal."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "0")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test_client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("PAYPAL_MODE", "live")
    # Test client host is localhost — PUBLIC_BASE_URL with www. must still match.
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.localhost")

    import game.payment_providers as pp
    from app import app

    monkeypatch.setattr(
        pp,
        "paypal_create_checkout_order",
        lambda **kwargs: (
            True,
            "ok",
            {
                "session_id": "PAYPAL_ORDER_TEST",
                "checkout_url": "https://www.paypal.com/checkoutnow?token=PAYPAL_ORDER_TEST",
            },
        ),
    )
    monkeypatch.setattr(pp, "paypal_configured", lambda: True)
    monkeypatch.setattr("app._build_game_state_payload", lambda **_k: ({}, None))

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    checkout = client.post(
        "/api/shop/checkout",
        json={"sku": "tk_pack_s", "provider": "paypal", "legal_ack": True},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["checkout_url"]


def test_live_paypal_rejects_foreign_host(shop_db, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "0")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test_client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("PAYPAL_MODE", "live")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.genesis-colonies.de")

    import game.payment_providers as pp
    from app import app

    monkeypatch.setattr(pp, "paypal_configured", lambda: True)

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    checkout = client.post(
        "/api/shop/checkout",
        json={"sku": "tk_pack_s", "provider": "paypal", "legal_ack": True},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 400
    data = checkout.get_json()
    assert data["ok"] is False
    assert data["reason"] == "public_host_mismatch"
    assert data.get("canonical_shop_url") == "https://www.genesis-colonies.de/shop"


def test_sandbox_paypal_allows_foreign_host_despite_prod_public_url(shop_db, monkeypatch):
    """Local sandbox must not hit public_host_mismatch (Instant-Buy baseline)."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "0")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test_client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.genesis-colonies.de")

    import game.payment_providers as pp
    from app import app

    captured = {}

    def _create(**kwargs):
        captured["success_url"] = kwargs.get("success_url")
        captured["cancel_url"] = kwargs.get("cancel_url")
        return (
            True,
            "ok",
            {
                "session_id": "PAYPAL_SB_TEST",
                "checkout_url": "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL_SB_TEST",
            },
        )

    monkeypatch.setattr(pp, "paypal_create_checkout_order", _create)
    monkeypatch.setattr(pp, "paypal_configured", lambda: True)
    monkeypatch.setattr("app._build_game_state_payload", lambda **_k: ({}, None))

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    checkout = client.post(
        "/api/shop/checkout",
        json={"sku": "tk_pack_s", "provider": "paypal", "legal_ack": True},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["checkout_url"]
    # Return URLs must stay on the request host (not prod PUBLIC_BASE_URL).
    assert "genesis-colonies.de" not in str(captured.get("success_url") or "")
    assert "/shop/return" in str(captured.get("success_url") or "")


def test_instant_buy_impulse_sku_same_checkout_shape(shop_db, monkeypatch):
    """Impulse Trio uses the same Instant-Buy checkout contract as classic SKUs."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "0")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test_client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")

    import game.payment_providers as pp
    from app import app

    monkeypatch.setattr(
        pp,
        "paypal_create_checkout_order",
        lambda **kwargs: (
            True,
            "ok",
            {
                "session_id": "PAYPAL_IMPULSE",
                "checkout_url": "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL_IMPULSE",
            },
        ),
    )
    monkeypatch.setattr(pp, "paypal_configured", lambda: True)
    monkeypatch.setattr("app._build_game_state_payload", lambda **_k: ({}, None))

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    checkout = client.post(
        "/api/shop/checkout",
        json={
            "sku": "genesis_accelerator_pack",
            "provider": "paypal",
            "legal_ack": True,
        },
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["checkout_url"]
    assert data.get("state") == {}
    assert data.get("fulfilled") is False


def test_resolve_shop_checkout_base_url_local_vs_live(monkeypatch):
    from game.config import resolve_shop_checkout_base_url

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.genesis-colonies.de")
    local = resolve_shop_checkout_base_url(
        request_url_root="http://127.0.0.1:5000/",
        paypal_live=False,
    )
    assert local == "http://127.0.0.1:5000"
    live = resolve_shop_checkout_base_url(
        request_url_root="http://127.0.0.1:5000/",
        paypal_live=True,
    )
    assert live == "https://www.genesis-colonies.de"


def test_session_cookie_domain_explicit_only(monkeypatch):
    from game.config import session_cookie_domain

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.genesis-colonies.de")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("GC_SESSION_COOKIE_DOMAIN", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_DOMAIN", raising=False)
    assert session_cookie_domain() is None
    monkeypatch.setenv("GC_SESSION_COOKIE_DOMAIN", ".genesis-colonies.de")
    assert session_cookie_domain() == ".genesis-colonies.de"


def test_paypal_cart_checkout_keeps_session_cart_until_paid(shop_db, monkeypatch):
    """Cart must survive PayPal redirect start (empty_cart regression)."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "0")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test_client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("PAYPAL_MODE", "sandbox")

    import game.payment_providers as pp
    from app import app

    monkeypatch.setattr(
        pp,
        "paypal_create_checkout_order",
        lambda **kwargs: (
            True,
            "ok",
            {
                "session_id": "PAYPAL_CART_KEEP",
                "checkout_url": "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL_CART_KEEP",
            },
        ),
    )
    monkeypatch.setattr(pp, "paypal_configured", lambda: True)
    monkeypatch.setattr("app._build_game_state_payload", lambda **_k: ({}, None))

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    add = client.post(
        "/api/shop/cart/add",
        json={"sku": "tk_pack_s", "qty": 1},
        headers={"Content-Type": "application/json"},
    )
    assert add.status_code == 200
    checkout = client.post(
        "/api/shop/checkout",
        json={"from_cart": True, "provider": "paypal", "legal_ack": True},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    assert checkout.get_json()["checkout_url"]
    cart = client.get("/api/shop/cart")
    assert cart.status_code == 200
    assert cart.get_json()["cart"]["item_count"] >= 1


def test_cart_checkout_accepts_client_lines_when_session_empty(shop_db, monkeypatch):
    """UI cart snapshot can recover checkout if session cart was lost."""
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
        sess.pop("shop_cart", None)

    checkout = client.post(
        "/api/shop/checkout",
        json={
            "from_cart": True,
            "provider": "test",
            "legal_ack": True,
            "lines": [{"sku": "tk_pack_s", "qty": 1}],
        },
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["fulfilled"] is True


def test_multi_sku_cart_order_and_fulfill(shop_db):
    """One order can hold multiple SKUs; one promo discounts the sum once."""
    from game.db import begin_write_transaction, commit
    from game.shop import create_pending_order, fulfill_order, get_order, mark_paid
    from game.shop_promos import create_campaign_code
    from game.timekeeper import get_balance

    uid = _player()
    conn = db()
    begin_write_transaction(conn)
    ok, reason, promo = create_campaign_code(
        conn=conn, code="CART10", discount_bps=1000, max_redemptions=None
    )
    assert ok, reason
    ok, reason, created = create_pending_order(
        uid,
        "",
        "test",
        conn=conn,
        promo_code="CART10",
        lines=[
            {"sku": "tk_pack_s", "qty": 2},
            {"sku": "tk_pack_m", "qty": 1},
        ],
    )
    assert ok, reason
    order = created["order"]
    assert order["sku"] == "tk_pack_s"
    items = order.get("items") or []
    assert len(items) == 2
    list_cents = 99 * 2 + 299
    assert int(order["list_amount_cents"]) == list_cents
    assert int(order["discount_cents"]) == list_cents // 10
    assert int(order["amount_cents"]) == list_cents - list_cents // 10
    mark_paid(int(order["id"]), conn=conn, provider_payment_id="pay_cart_1")
    ok_f, reason_f, fulfilled = fulfill_order(int(order["id"]), conn=conn)
    assert ok_f, reason_f
    bal = get_balance(uid, conn=conn)
    # 2×6h + 1×24h
    assert int(bal) >= (2 * 6 + 24) * 3600
    again = get_order(int(order["id"]), conn=conn)
    assert again["status"] == "fulfilled"
    commit(conn)
    conn.close()


def test_http_cart_add_and_checkout(shop_db, monkeypatch):
    monkeypatch.setenv("SHOP_ENABLED", "1")
    monkeypatch.setenv("SHOP_TEST_PROVIDER", "1")
    from app import app

    app.config["TESTING"] = True
    client = app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    add = client.post(
        "/api/shop/cart/add",
        json={"sku": "tk_pack_s", "qty": 1},
        headers={"Content-Type": "application/json"},
    )
    assert add.status_code == 200, add.get_data(as_text=True)
    assert add.get_json()["cart"]["item_count"] >= 1

    add2 = client.post(
        "/api/shop/cart/add",
        json={"sku": "tk_pack_m", "qty": 1},
        headers={"Content-Type": "application/json"},
    )
    assert add2.status_code == 200
    assert len(add2.get_json()["cart"]["items"]) == 2

    checkout = client.post(
        "/api/shop/checkout",
        json={"from_cart": True, "provider": "test", "legal_ack": True},
        headers={"Content-Type": "application/json"},
    )
    assert checkout.status_code == 200, checkout.get_data(as_text=True)
    data = checkout.get_json()
    assert data["ok"] is True
    assert data["fulfilled"] is True

    cart = client.get("/api/shop/cart")
    assert cart.status_code == 200
    assert cart.get_json()["cart"]["item_count"] == 0


def test_shop_cart_ui_contract():
    tpl = (
        Path(__file__).resolve().parent.parent / "templates" / "shop.html"
    ).read_text(encoding="utf-8")
    assert "data-shop-cart-add" in tpl
    assert "data-shop-cart-panel" in tpl
    assert "data-shop-cart-checkout" in tpl
    assert "data-shop-cart-discount-row" in tpl
    assert "data-shop-card-cart-qty" in tpl
    js = (
        Path(__file__).resolve().parent.parent / "static" / "main.js"
    ).read_text(encoding="utf-8")
    assert "_shopRefreshCart" in js
    assert "_shopRestoreSessionCart" in js
    assert 'from_cart: true' in js
    refresh = js.split("async function _shopRefreshCart()")[1].split(
        "async function _shopRestoreSessionCart"
    )[0]
    assert "prevItems" in refresh
    assert "_shopRestoreSessionCart" in refresh
    assert "prevItems.length > 0" in refresh
    assert "/api/shop/cart/add" in js
    assert "discount_cents" in js
    assert "shop_cart_discount" in js
    assert "_shopSyncCardCartQtys" in js
    assert "shop_cart_card_qty" in js
    cart_checkout = js.split("closest(\"[data-shop-cart-checkout]\")")[1].split(
        "closest(\"[data-shop-buy]\")"
    )[0]
    assert "lines" in cart_checkout
    assert "empty_cart" in cart_checkout
    assert "from_cart: true" in cart_checkout


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
    skus = {p["sku"] for p in state["products"]}
    from game.shop import SHOP_SKU_IMAGES

    assert skus == set(SHOP_SKU_IMAGES.keys())
    for p in state["products"]:
        assert p.get("image") == SHOP_SKU_IMAGES[p["sku"]]
    signal = next(p for p in state["products"] if p["sku"] == "name_style_signal")
    assert signal["display"]["preview_style"] == "signal"
    assert signal["display"]["unlocks"] == [{"kind": "name_style", "key": "signal"}]
    pack = next(p for p in state["products"] if p["sku"] == "identity_pack_signal")
    assert len(pack["display"]["unlocks"]) == 3
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


def test_shop_products_kind_schema_rebuild(shop_db):
    """Old CHECK without cosmetic_unlock is rebuilt before catalog seed."""
    from game.shop import (
        _shop_products_allows_cosmetic_unlock,
        ensure_catalog_seeded,
        ensure_shop_products_kind_schema,
    )

    conn = db()
    # Force legacy CHECK (pre-115).
    conn.execute("DROP TABLE IF EXISTS shop_products;")
    conn.execute(
        """
        CREATE TABLE shop_products (
            sku TEXT NOT NULL PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('entitlement', 'timekeeper', 'inventory_bundle')),
            title_key TEXT NOT NULL DEFAULT '',
            hint_key TEXT NOT NULL DEFAULT '',
            price_cents INTEGER NOT NULL CHECK (price_cents > 0),
            currency TEXT NOT NULL DEFAULT 'eur',
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            payload_json TEXT NOT NULL DEFAULT '{}',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()
    assert _shop_products_allows_cosmetic_unlock(conn) is False
    assert ensure_shop_products_kind_schema(conn) is True
    assert _shop_products_allows_cosmetic_unlock(conn) is True
    n = ensure_catalog_seeded(conn)
    assert n >= 8
    row = conn.execute(
        "SELECT kind FROM shop_products WHERE sku = 'name_style_signal' LIMIT 1;"
    ).fetchone()
    assert row and str(row["kind"]) == "cosmetic_unlock"
    conn.commit()
    conn.close()


def test_admin_unlock_still_works(shop_db):
    uid = _player()
    conn = db()
    ok, reason, _ = unlock_premium(uid, conn=conn, source="admin:test")
    assert ok, reason
    conn.commit()
    conn.close()


def test_fulfill_name_style_cosmetic(shop_db):
    from game.playercard import (
        get_equipped_name_style,
        player_has_name_style,
        player_has_title_flair,
        save_own_card,
    )
    from game import playercard as pc_mod

    uid = _player()
    conn = db()
    assert player_has_name_style(uid, "signal", conn=conn) is False
    ok, reason, out = start_checkout(
        uid,
        "name_style_signal",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
        legal_ack=True,
    )
    assert ok, reason
    assert player_has_name_style(uid, "signal", conn=conn) is True
    assert out and (out.get("fulfilled") is True or (out.get("order") or {}).get("status") == "fulfilled")

    # Already owned → checkout rejected
    ok2, reason2, _ = start_checkout(
        uid,
        "name_style_signal",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
        legal_ack=True,
    )
    assert ok2 is False
    assert reason2 == "already_owned"

    ok3, reason3, out3 = start_checkout(
        uid,
        "identity_pack_signal",
        "test",
        conn=conn,
        success_url="http://localhost/shop/return",
        cancel_url="http://localhost/shop?cancelled=1",
        legal_ack=True,
    )
    assert ok3, reason3
    assert player_has_name_style(uid, "etched", conn=conn) is True
    assert player_has_title_flair(uid, "etched", conn=conn) is True
    conn.commit()
    conn.close()

    pc_mod._LAST_SAVE_TS.pop(uid, None)
    ok_save, reason_save, _ = save_own_card(
        uid,
        {"theme": "cyan", "aura_key": "none", "title_flair": "etched", "name_style": "signal"},
    )
    assert ok_save is True, reason_save
    assert get_equipped_name_style(uid) == "signal"


def test_name_style_locked_without_unlock(shop_db):
    from game.playercard import save_own_card
    from game import playercard as pc_mod

    uid = _player()
    pc_mod._LAST_SAVE_TS.pop(uid, None)
    ok, reason, _ = save_own_card(
        uid,
        {"theme": "cyan", "aura_key": "none", "title_flair": "none", "name_style": "void"},
    )
    assert ok is False
    assert reason == "playercard_name_style_locked"


def test_titan_slot_plus_fulfill_and_cap(shop_db):
    from game.db import begin_write_transaction, commit
    from game.world_boss_companions import (
        MAX_COMPANION_CAPACITY,
        get_companion_capacity,
    )

    uid = _player()
    conn = db()
    begin_write_transaction(conn)
    try:
        products = list_catalog(conn=conn)
        assert any(p["sku"] == SKU_TITAN_SLOT_PLUS for p in products)
        assert CATALOG_VERSION >= 6

        assert get_companion_capacity(uid, conn=conn) == 1
        ok, reason, meta = create_pending_order(
            uid, SKU_TITAN_SLOT_PLUS, "test", conn=conn
        )
        assert ok, reason
        oid = int(meta["order"]["id"])
        mark_paid(oid, conn=conn)
        ok_f, reason_f, order = fulfill_order(oid, conn=conn)
        assert ok_f, reason_f
        assert get_companion_capacity(uid, conn=conn) == 2
        assert (order or {}).get("status") == "fulfilled"

        # Buy until max
        while get_companion_capacity(uid, conn=conn) < MAX_COMPANION_CAPACITY:
            ok2, reason2, meta2 = create_pending_order(
                uid, SKU_TITAN_SLOT_PLUS, "test", conn=conn
            )
            assert ok2, reason2
            oid2 = int(meta2["order"]["id"])
            mark_paid(oid2, conn=conn)
            ok_f2, reason_f2, _ = fulfill_order(oid2, conn=conn)
            assert ok_f2, reason_f2

        assert get_companion_capacity(uid, conn=conn) == MAX_COMPANION_CAPACITY
        ok3, reason3, _ = create_pending_order(
            uid, SKU_TITAN_SLOT_PLUS, "test", conn=conn
        )
        assert ok3 is False
        assert reason3 == "already_owned"

        cat = serialize_catalog_for_client(conn=conn, player_id=uid)
        titan = next(p for p in cat["products"] if p["sku"] == SKU_TITAN_SLOT_PLUS)
        assert titan["owned"] is True
        commit(conn)
    finally:
        conn.close()
