from __future__ import annotations

import json
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from .db import table_exists
from .shop import STATUS_PAID, fulfill_order, get_order


def repair_verified_paid_order(
    order_id: int,
    *,
    conn,
    expected_player_id: Optional[int] = None,
    reason: str,
    metadata: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """One-time operator recovery for a paid order with missing rewards.

    This path is deliberately explicit and is intended only after an operator
    independently verifies that payment was received and rewards are absent.
    The shared repair ledger keeps the compensation idempotent.
    """
    if not table_exists(conn, "shop_fulfillment_repairs"):
        return False, "repair_schema_unavailable", None

    order = get_order(int(order_id), conn=conn)
    if not order:
        return False, "order_not_found", None

    pid = int(order["player_id"])
    if expected_player_id is not None and pid != int(expected_player_id):
        return False, "player_mismatch", order

    existing = conn.execute(
        "SELECT order_id FROM shop_fulfillment_repairs WHERE order_id = ? LIMIT 1;",
        (int(order_id),),
    ).fetchone()
    if existing:
        return True, "already_repaired", order

    if str(order.get("status") or "") != STATUS_PAID:
        return False, "not_marked_paid", order
    if not order.get("paid_at"):
        return False, "paid_timestamp_missing", order

    why = str(reason or "").strip()
    if not why:
        return False, "repair_reason_required", order

    ts = float(now if now is not None else time.time())
    ok, fulfill_reason, repaired = fulfill_order(int(order_id), conn=conn, now=ts)
    if not ok:
        return False, fulfill_reason, repaired

    conn.execute(
        """
        INSERT INTO shop_fulfillment_repairs (
            order_id, player_id, original_status, reason, metadata_json, repaired_at
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (
            int(order_id),
            pid,
            STATUS_PAID,
            why,
            json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
            ts,
        ),
    )

    out = get_order(int(order_id), conn=conn)
    if out is not None:
        out["repair_reason"] = why
        out["repair_fulfill_reason"] = fulfill_reason
        out["granted"] = (repaired or {}).get("granted")
    return True, "repaired", out
