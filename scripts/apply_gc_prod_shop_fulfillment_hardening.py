#!/usr/bin/env python3
from pathlib import Path

p = Path("game/shop.py")
src = p.read_text(encoding="utf-8")


def repl(old: str, new: str) -> None:
    global src
    if old not in src:
        raise SystemExit(f"shop target not found: {old[:140]!r}")
    src = src.replace(old, new, 1)


# Fulfillment must be all-or-nothing even when a later unit grant returns false.
repl(
'''    granted_all: List[Dict[str, Any]] = []\n    grant_reason = "ok"\n    any_ok_grant = False\n''',
'''    # P0: make multi-unit / multi-line grants atomic inside the caller transaction.\n    # A later unit failure must never leave earlier inventory/timekeeper grants\n    # committed while the order is marked failed and retried.\n    savepoint = f"shop_fulfill_{int(order_id)}"\n    conn.execute(f"SAVEPOINT {savepoint};")\n\n    def _rollback_fulfillment_savepoint() -> None:\n        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint};")\n        conn.execute(f"RELEASE SAVEPOINT {savepoint};")\n\n    def _release_fulfillment_savepoint() -> None:\n        conn.execute(f"RELEASE SAVEPOINT {savepoint};")\n\n    granted_all: List[Dict[str, Any]] = []\n    grant_reason = "ok"\n    any_ok_grant = False\n''')

repl(
'''        if not product:\n            conn.execute(\n                """\n                UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;\n                """,\n                (STATUS_FAILED, "unknown_sku", int(order_id)),\n            )\n            return False, "unknown_sku", get_order(int(order_id), conn=conn)\n''',
'''        if not product:\n            _rollback_fulfillment_savepoint()\n            conn.execute(\n                """\n                UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;\n                """,\n                (STATUS_FAILED, "unknown_sku", int(order_id)),\n            )\n            return False, "unknown_sku", get_order(int(order_id), conn=conn)\n''')

repl(
'''            if not ok_g:\n                conn.execute(\n                    """\n                    UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;\n                    """,\n                    (STATUS_FAILED, str(reason_g), int(order_id)),\n                )\n                return False, reason_g, get_order(int(order_id), conn=conn)\n''',
'''            if not ok_g:\n                _rollback_fulfillment_savepoint()\n                conn.execute(\n                    """\n                    UPDATE shop_orders SET status = ?, fulfill_reason = ? WHERE id = ?;\n                    """,\n                    (STATUS_FAILED, str(reason_g), int(order_id)),\n                )\n                return False, reason_g, get_order(int(order_id), conn=conn)\n''')

repl(
'''        except Exception:\n            pass\n    return True, grant_reason, out\n\n\ndef record_payment_event(\n''',
'''        except Exception:\n            pass\n    _release_fulfillment_savepoint()\n    return True, grant_reason, out\n\n\ndef repair_fulfilled_order(\n    order_id: int,\n    *,\n    conn,\n    expected_player_id: Optional[int] = None,\n    reason: str,\n    metadata: Optional[Mapping[str, Any]] = None,\n    now: Optional[float] = None,\n) -> Tuple[bool, str, Optional[Dict[str, Any]]]:\n    """Explicit one-time recovery for an order falsely marked fulfilled.\n\n    This is intentionally *not* automatic. Operators must independently verify\n    that payment was received and rewards are missing. The repair ledger has a\n    unique order_id, preventing a second compensation pass.\n    """\n    if not table_exists(conn, "shop_fulfillment_repairs"):\n        return False, "repair_schema_unavailable", None\n    order = get_order(int(order_id), conn=conn)\n    if not order:\n        return False, "order_not_found", None\n    pid = int(order["player_id"])\n    if expected_player_id is not None and pid != int(expected_player_id):\n        return False, "player_mismatch", order\n    if str(order.get("status") or "") != STATUS_FULFILLED:\n        return False, "not_marked_fulfilled", order\n    existing = conn.execute(\n        "SELECT order_id FROM shop_fulfillment_repairs WHERE order_id = ? LIMIT 1;",\n        (int(order_id),),\n    ).fetchone()\n    if existing:\n        return True, "already_repaired", order\n\n    why = str(reason or "").strip()\n    if not why:\n        return False, "repair_reason_required", order\n    ts = float(now if now is not None else time.time())\n    original_status = str(order.get("status") or "")\n\n    # Re-enter the real grant pipeline. Merely changing status never grants items.\n    conn.execute(\n        """\n        UPDATE shop_orders\n        SET status = ?, fulfilled_at = NULL, fulfill_reason = ?\n        WHERE id = ?;\n        """,\n        (STATUS_PAID, "repair_regrant_pending", int(order_id)),\n    )\n    ok, fulfill_reason, repaired = fulfill_order(int(order_id), conn=conn, now=ts)\n    if not ok:\n        return False, fulfill_reason, repaired\n\n    conn.execute(\n        """\n        INSERT INTO shop_fulfillment_repairs (\n            order_id, player_id, original_status, reason, metadata_json, repaired_at\n        ) VALUES (?, ?, ?, ?, ?, ?);\n        """,\n        (\n            int(order_id),\n            pid,\n            original_status,\n            why,\n            _json_dumps(dict(metadata or {})),\n            ts,\n        ),\n    )\n    out = get_order(int(order_id), conn=conn)\n    if out is not None:\n        out["repair_reason"] = why\n        out["repair_fulfill_reason"] = fulfill_reason\n        out["granted"] = (repaired or {}).get("granted")\n    return True, "repaired", out\n\n\ndef record_payment_event(\n''')

# Correct the retry comment: atomicity, not grant function idempotence, is the safety contract.
repl(
'''        # A previous paid-event pass may have persisted the event and then\n        # failed during reward granting. Those states are safe to resume:\n        # mark_paid() is idempotent and _grant_product_once() protects rewards\n        # from double credit on a partial prior fulfillment.\n''',
'''        # A previous paid-event pass may have persisted the event and then\n        # failed during reward granting. Those states are safe to resume:\n        # mark_paid() is idempotent and fulfill_order() rolls back its grant\n        # savepoint on any explicit unit failure, so retries cannot duplicate\n        # a partially committed multi-unit grant.\n''')

p.write_text(src, encoding="utf-8")
print("Applied production shop fulfillment hardening")
