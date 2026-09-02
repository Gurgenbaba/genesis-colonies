"""P0 production regressions for paid-shop fulfillment and operator recovery."""

from __future__ import annotations

import uuid

import pytest

from game.db import db
from game.inventory import inventory_amount
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.shop import (
    SKU_HYPERDRIVE_PROTOCOL,
    create_pending_order,
    fulfill_order,
    get_order,
    mark_paid,
    repair_fulfilled_order,
)
from game.timekeeper import get_balance


@pytest.fixture
def hardening_db(tmp_path, monkeypatch):
    db_path = tmp_path / "shop_hardening.db"
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


def _player() -> int:
    conn = db()
    try:
        ok, err, user = create_user(
            f"shop_harden_{uuid.uuid4().hex[:10]}", "test-pass-123"
        )
        assert ok, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="ShopHardening", conn=conn)
        conn.commit()
        return uid
    finally:
        conn.close()


def _hyperdrive_x2(uid: int, conn):
    ok, reason, created = create_pending_order(
        uid,
        SKU_HYPERDRIVE_PROTOCOL,
        "test",
        conn=conn,
        lines=[{"sku": SKU_HYPERDRIVE_PROTOCOL, "qty": 2}],
    )
    assert ok, reason
    assert created and created.get("order")
    return int(created["order"]["id"])


def test_multi_unit_failure_rolls_back_prior_unit_grants(hardening_db, monkeypatch):
    import game.shop as shop

    uid = _player()
    conn = db()
    try:
        order_id = _hyperdrive_x2(uid, conn)
        ok, reason, _ = mark_paid(order_id, conn=conn, provider_payment_id="TEST-CAP")
        assert ok, reason
        conn.commit()

        tk_before = get_balance(uid, conn=conn)
        inv_before = inventory_amount(uid, "booster_build_24h", conn=conn)
        original = shop._grant_product_once
        calls = {"n": 0}

        def flaky_grant(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return original(**kwargs)
            return False, "simulated_second_unit_failure", {}

        monkeypatch.setattr(shop, "_grant_product_once", flaky_grant)
        ok, reason, failed = fulfill_order(order_id, conn=conn)
        assert not ok
        assert reason == "simulated_second_unit_failure"
        assert failed and failed["status"] == "failed"
        conn.commit()

        assert get_balance(uid, conn=conn) == tk_before
        assert inventory_amount(uid, "booster_build_24h", conn=conn) == inv_before
    finally:
        conn.close()


def test_repair_falsely_fulfilled_order_grants_once_and_is_audited(hardening_db):
    uid = _player()
    conn = db()
    try:
        order_id = _hyperdrive_x2(uid, conn)
        # Reproduce the unsafe manual SQL from the Production incident: status
        # changed without ever executing Genesis' reward grant pipeline.
        conn.execute(
            """
            UPDATE shop_orders
            SET status = 'fulfilled', paid_at = 1000, fulfilled_at = 1000,
                fulfill_reason = 'manual_fulfillment'
            WHERE id = ?;
            """,
            (order_id,),
        )
        conn.commit()

        tk_before = get_balance(uid, conn=conn)
        inv_before = inventory_amount(uid, "booster_build_24h", conn=conn)

        ok, reason, repaired = repair_fulfilled_order(
            order_id,
            conn=conn,
            expected_player_id=uid,
            reason="confirmed payment; manual fulfilled flag skipped rewards",
            metadata={"incident": "mando-pattern"},
            now=2000,
        )
        assert ok and reason == "repaired"
        assert repaired and repaired["status"] == "fulfilled"
        conn.commit()

        # Hyperdrive x2 = 144h Timekeeper + 20 build-24h boosters.
        assert get_balance(uid, conn=conn) - tk_before == 2 * 72 * 3600
        assert inventory_amount(uid, "booster_build_24h", conn=conn) - inv_before == 20
        row = conn.execute(
            "SELECT reason FROM shop_fulfillment_repairs WHERE order_id = ?;",
            (order_id,),
        ).fetchone()
        assert row is not None

        tk_once = get_balance(uid, conn=conn)
        inv_once = inventory_amount(uid, "booster_build_24h", conn=conn)
        ok2, reason2, _ = repair_fulfilled_order(
            order_id,
            conn=conn,
            expected_player_id=uid,
            reason="must not run twice",
            now=3000,
        )
        assert ok2 and reason2 == "already_repaired"
        conn.commit()
        assert get_balance(uid, conn=conn) == tk_once
        assert inventory_amount(uid, "booster_build_24h", conn=conn) == inv_once
    finally:
        conn.close()


def test_repair_refuses_wrong_player(hardening_db):
    uid = _player()
    conn = db()
    try:
        order_id = _hyperdrive_x2(uid, conn)
        conn.execute("UPDATE shop_orders SET status = 'fulfilled' WHERE id = ?;", (order_id,))
        conn.commit()
        ok, reason, _ = repair_fulfilled_order(
            order_id,
            conn=conn,
            expected_player_id=uid + 999,
            reason="should fail",
        )
        assert not ok and reason == "player_mismatch"
    finally:
        conn.close()
