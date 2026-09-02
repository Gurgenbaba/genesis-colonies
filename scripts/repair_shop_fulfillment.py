#!/usr/bin/env python3
"""Repair an order that was manually marked fulfilled without running grants.

Safety: dry-run by default. --apply requires --confirm-missing-rewards and an
expected player id. The DB repair ledger prevents re-running the same order.
"""

from __future__ import annotations

import argparse
import json

from game.db import begin_write_transaction, commit, db, rollback
from game.shop import get_order, repair_fulfilled_order


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order-id", type=int, required=True)
    ap.add_argument("--expected-player-id", type=int, required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm-missing-rewards", action="store_true")
    args = ap.parse_args()

    conn = db()
    try:
        order = get_order(args.order_id, conn=conn)
        if not order:
            print(json.dumps({"ok": False, "reason": "order_not_found"}))
            return 2
        summary = {
            "order_id": int(order["id"]),
            "player_id": int(order["player_id"]),
            "status": str(order.get("status") or ""),
            "provider": str(order.get("provider") or ""),
            "amount_cents": int(order.get("amount_cents") or 0),
            "items": order.get("items") or [],
        }
        if int(order["player_id"]) != int(args.expected_player_id):
            print(json.dumps({"ok": False, "reason": "player_mismatch", "order": summary}))
            return 3
        if not args.apply:
            print(json.dumps({"ok": True, "dry_run": True, "order": summary}, indent=2))
            return 0
        if not args.confirm_missing_rewards:
            print(json.dumps({"ok": False, "reason": "missing_rewards_confirmation_required"}))
            return 4

        begin_write_transaction(conn)
        ok, reason, repaired = repair_fulfilled_order(
            args.order_id,
            conn=conn,
            expected_player_id=args.expected_player_id,
            reason=args.reason,
            metadata={"tool": "repair_shop_fulfillment.py"},
        )
        if not ok:
            rollback(conn)
            print(json.dumps({"ok": False, "reason": reason}, indent=2))
            return 5
        commit(conn)
        print(
            json.dumps(
                {
                    "ok": True,
                    "reason": reason,
                    "order_id": args.order_id,
                    "player_id": args.expected_player_id,
                    "status": (repaired or {}).get("status"),
                    "fulfill_reason": (repaired or {}).get("fulfill_reason"),
                    "granted": (repaired or {}).get("granted"),
                },
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        try:
            rollback(conn)
        except Exception:
            pass
        print(json.dumps({"ok": False, "reason": "exception", "error": str(exc)}))
        return 10
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
