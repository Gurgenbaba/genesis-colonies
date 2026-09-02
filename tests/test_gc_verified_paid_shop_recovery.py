from __future__ import annotations

import uuid

import pytest

from game.db import db
from game.inventory import inventory_amount
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.shop import SKU_HYPERDRIVE_PROTOCOL, create_pending_order, get_order, mark_paid
from game.shop_recovery import repair_verified_paid_order
from game.timekeeper import get_balance


@pytest.fixture
def recovery_db(tmp_path, monkeypatch):
    db_path = tmp_path / "verified_paid_recovery.db"
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
            f"verified_paid_{uuid.uuid4().hex[:10]}", "test-pass-123"
        )
        assert ok, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="VerifiedPaid", conn=conn)
        conn.commit()
        return uid
    finally:
        conn.close()


def _paid_hyperdrive_x2(uid: int, conn) -> int:
    ok, reason, created = create_pending_order(
        uid,
        SKU_HYPERDRIVE_PROTOCOL,
        "paypal",
        conn=conn,
        lines=[{"sku": SKU_HYPERDRIVE_PROTOCOL, "qty": 2}],
    )
    assert ok, reason
    order_id = int(created["order"]["id"])
    ok, reason, _ = mark_paid(
        order_id,
        conn=conn,
        provider_payment_id="LEGACY-VERIFIED-PAYMENT",
        now=1000,
    )
    assert ok, reason
    conn.commit()
    return order_id


def test_verified_paid_repair_grants_once_and_records_ledger(recovery_db):
    uid = _player()
    conn = db()
    try:
        order_id = _paid_hyperdrive_x2(uid, conn)
        tk_before = get_balance(uid, conn=conn)
        inv_before = inventory_amount(uid, "booster_build_24h", conn=conn)

        ok, reason, repaired = repair_verified_paid_order(
            order_id,
            conn=conn,
            expected_player_id=uid,
            reason="operator verified payment and missing rewards",
            metadata={"incident": "legacy-paypal-404"},
            now=2000,
        )
        assert ok and reason == "repaired"
        assert repaired and repaired["status"] == "fulfilled"
        conn.commit()

        assert get_balance(uid, conn=conn) - tk_before == 2 * 72 * 3600
        assert inventory_amount(uid, "booster_build_24h", conn=conn) - inv_before == 20
        ledger = conn.execute(
            "SELECT original_status, reason FROM shop_fulfillment_repairs WHERE order_id = ?;",
            (order_id,),
        ).fetchone()
        assert ledger is not None
        assert ledger["original_status"] == "paid"

        tk_once = get_balance(uid, conn=conn)
        inv_once = inventory_amount(uid, "booster_build_24h", conn=conn)
        ok2, reason2, _ = repair_verified_paid_order(
            order_id,
            conn=conn,
            expected_player_id=uid,
            reason="must remain idempotent",
            now=3000,
        )
        assert ok2 and reason2 == "already_repaired"
        conn.commit()
        assert get_balance(uid, conn=conn) == tk_once
        assert inventory_amount(uid, "booster_build_24h", conn=conn) == inv_once
    finally:
        conn.close()


def test_verified_paid_repair_refuses_pending_order(recovery_db):
    uid = _player()
    conn = db()
    try:
        ok, reason, created = create_pending_order(
            uid,
            SKU_HYPERDRIVE_PROTOCOL,
            "paypal",
            conn=conn,
        )
        assert ok, reason
        order_id = int(created["order"]["id"])
        conn.commit()

        ok, reason, _ = repair_verified_paid_order(
            order_id,
            conn=conn,
            expected_player_id=uid,
            reason="must fail",
        )
        assert not ok and reason == "not_marked_paid"
    finally:
        conn.close()


def test_verified_paid_repair_refuses_wrong_player(recovery_db):
    uid = _player()
    conn = db()
    try:
        order_id = _paid_hyperdrive_x2(uid, conn)
        ok, reason, _ = repair_verified_paid_order(
            order_id,
            conn=conn,
            expected_player_id=uid + 999,
            reason="must fail",
        )
        assert not ok and reason == "player_mismatch"
    finally:
        conn.close()
