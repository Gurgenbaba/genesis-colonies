#!/usr/bin/env python3
from pathlib import Path

path = Path("game/shop.py")
src = path.read_text(encoding="utf-8")
old = '''    if ev_reason == "duplicate":
        # Still return current order if known.
        order = None
        if order_id:
            order = get_order(int(order_id), conn=conn)
        elif provider_session_id:
            order = find_order_by_session(provider, provider_session_id, conn=conn)
        return True, "duplicate", order

    order = None
    if order_id:
        order = get_order(int(order_id), conn=conn)
    if order is None and provider_session_id:
        order = find_order_by_session(provider, str(provider_session_id), conn=conn)
    if order is None:
        return False, "order_not_found", None

    ok_paid, paid_reason, order = mark_paid(
        int(order["id"]),
        conn=conn,
        provider_payment_id=provider_payment_id,
        now=now,
    )
    if not ok_paid and paid_reason not in ("already_paid",):
        return False, paid_reason, order

    return fulfill_order(int(order["id"]), conn=conn, now=now)
'''
new = '''    duplicate_event = ev_reason == "duplicate"

    order = None
    if order_id:
        order = get_order(int(order_id), conn=conn)
    if order is None and provider_session_id:
        order = find_order_by_session(provider, str(provider_session_id), conn=conn)
    if order is None:
        # Preserve idempotent acknowledgement for an already-seen event whose
        # order can no longer be resolved; new events must still fail loudly.
        if duplicate_event:
            return True, "duplicate", None
        return False, "order_not_found", None

    if duplicate_event:
        status = str(order.get("status") or "").strip().lower()
        if status == STATUS_FULFILLED:
            return True, "duplicate", order
        # A previous paid-event pass may have persisted the event and then
        # failed during reward granting. Those states are safe to resume:
        # mark_paid() is idempotent and _grant_product_once() protects rewards
        # from double credit on a partial prior fulfillment.
        if status not in (STATUS_PENDING, STATUS_PAID, STATUS_FAILED):
            return True, "duplicate", order

    ok_paid, paid_reason, order = mark_paid(
        int(order["id"]),
        conn=conn,
        provider_payment_id=provider_payment_id,
        now=now,
    )
    if not ok_paid and paid_reason not in ("already_paid",):
        return False, paid_reason, order

    return fulfill_order(int(order["id"]), conn=conn, now=now)
'''
if old not in src:
    raise SystemExit("target process_paid_event block not found")
path.write_text(src.replace(old, new, 1), encoding="utf-8")
