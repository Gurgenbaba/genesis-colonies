"""P0 reproduction for paid PayPal orders not granting rewards on Production PostgreSQL.

Runs only when GC_DB_BACKEND=postgres. The workflow provides a fresh PostgreSQL 16 DB.
No PayPal network call is needed: this starts at the trusted paid-event boundary and
proves the same fulfillment path used by the PayPal webhook/browser return.
"""

from __future__ import annotations

import os
import uuid

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("GC_DB_BACKEND", "").strip().lower() != "postgres",
    reason="PostgreSQL-only production regression",
)


@pytest.fixture(scope="module", autouse=True)
def _close_postgres_pool_after_module():
    yield
    from game.db_pg import close_pool

    close_pool()


def _make_player() -> int:
    from game.models import create_user, ensure_player_and_homeworld

    username = f"Nova{uuid.uuid4().hex[:10]}"
    ok, reason, user = create_user(username, "test-pass-123")
    assert ok, reason
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def _pending_timekeeper_order(uid: int, *, conn, tag: str):
    from game.shop import attach_provider_session, create_pending_order, ensure_catalog_seeded

    ensure_catalog_seeded(conn)
    ok, reason, created = create_pending_order(
        uid,
        "tk_pack_s",
        "paypal",
        conn=conn,
        metadata={"test": tag},
    )
    assert ok, reason
    assert created and created.get("order")
    order_id = int(created["order"]["id"])
    paypal_order = f"PAYPAL-PG-{tag}-{order_id}"
    attach_provider_session(order_id, paypal_order, conn=conn)
    return order_id, paypal_order


def test_paid_paypal_timekeeper_s_fulfills_on_postgres():
    from game.db import begin_write_transaction, commit, db, rollback
    from game.shop import STATUS_FULFILLED, get_order, process_paid_event
    from game.timekeeper import get_balance

    uid = _make_player()
    conn = db()
    try:
        begin_write_transaction(conn)
        order_id, paypal_order = _pending_timekeeper_order(uid, conn=conn, tag="gc43")
        before = get_balance(uid, conn=conn)

        paid_ok, paid_reason, paid_order = process_paid_event(
            provider="paypal",
            event_id=f"PAYMENT.CAPTURE.COMPLETED:gc43:{order_id}",
            order_id=order_id,
            provider_session_id=paypal_order,
            provider_payment_id=f"CAPTURE-PG-{order_id}",
            conn=conn,
            payload={"source": "postgres_p0_regression"},
        )
        assert paid_ok, paid_reason
        assert paid_order is not None
        assert str(paid_order.get("status")) == STATUS_FULFILLED
        assert get_balance(uid, conn=conn) - before == 6 * 3600
        stored = get_order(order_id, conn=conn)
        assert stored is not None
        assert stored["status"] == STATUS_FULFILLED
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def test_optional_promo_sql_failure_cannot_rollback_paid_reward(monkeypatch):
    """Creator accounting failure must not poison the paid reward transaction."""
    from game import shop_promos
    from game.db import begin_write_transaction, commit, db, rollback
    from game.shop import STATUS_FULFILLED, get_order, process_paid_event
    from game.timekeeper import get_balance

    uid = _make_player()
    conn = db()
    try:
        begin_write_transaction(conn)
        order_id, paypal_order = _pending_timekeeper_order(uid, conn=conn, tag="promo-fail")
        before = get_balance(uid, conn=conn)

        def _broken_release(*, conn, now=None, creator_id=None):
            conn.execute("SELECT * FROM gc_missing_creator_commission_table;")
            return 0

        monkeypatch.setattr(shop_promos, "release_held_commissions", _broken_release)

        paid_ok, paid_reason, paid_order = process_paid_event(
            provider="paypal",
            event_id=f"PAYMENT.CAPTURE.COMPLETED:promo-fail:{order_id}",
            order_id=order_id,
            provider_session_id=paypal_order,
            provider_payment_id=f"CAPTURE-PROMO-FAIL-{order_id}",
            conn=conn,
            payload={"source": "postgres_optional_promo_failure"},
        )
        assert paid_ok, paid_reason
        assert paid_order is not None
        assert str(paid_order.get("status")) == STATUS_FULFILLED
        assert get_balance(uid, conn=conn) - before == 6 * 3600
        assert get_order(order_id, conn=conn)["status"] == STATUS_FULFILLED
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def test_failed_order_is_not_presented_as_pending():
    """A failed grant must never be rendered as an innocent 'payment pending'."""
    from game.db import begin_write_transaction, db, rollback
    from game.shop import build_shop_return_payload, ensure_catalog_seeded

    fake = {
        "id": 43,
        "player_id": 1,
        "sku": "tk_pack_s",
        "provider": "paypal",
        "amount_cents": 99,
        "currency": "eur",
        "status": "failed",
        "fulfill_reason": "grant_failed",
        "items": [
            {
                "sku": "tk_pack_s",
                "qty": 1,
                "unit_cents": 99,
                "list_cents": 99,
                "kind": "timekeeper",
                "currency": "eur",
                "title_key": "shop_sku_tk_s",
            }
        ],
    }

    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_catalog_seeded(conn)
        payload = build_shop_return_payload(fake, conn=conn)
        assert payload["status"] == "failed"
        assert payload["status_key"] == "failed"
    finally:
        rollback(conn)
        conn.close()
