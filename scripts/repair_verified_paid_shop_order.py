#!/usr/bin/env python3
"""Repair one verified-paid shop order whose rewards are missing.

This is an operator-only incident tool. It does not contact PayPal. Before
using --apply, independently verify both that payment was received and that the
player did not receive the rewards.

Examples:
  python scripts/repair_verified_paid_shop_order.py 22:39
  python scripts/repair_verified_paid_shop_order.py 22:39 \
      --apply --confirm-payment-and-missing-rewards
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_target(value: str) -> tuple[int, int]:
    try:
        order_s, player_s = str(value).split(":", 1)
        order_id, player_id = int(order_s), int(player_s)
    except Exception as exc:
        raise argparse.ArgumentTypeError("expected ORDER_ID:PLAYER_ID") from exc
    if order_id <= 0 or player_id <= 0:
        raise argparse.ArgumentTypeError("order/player ids must be positive")
    return order_id, player_id


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=_parse_target, metavar="ORDER_ID:PLAYER_ID")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-payment-and-missing-rewards",
        action="store_true",
        help="Required with --apply after independent operator verification.",
    )
    return parser.parse_args()


def _emit(kind: str, **payload) -> None:
    print(json.dumps({"kind": kind, **payload}, ensure_ascii=False, sort_keys=True))


def main() -> int:
    args = _args()
    backend = os.environ.get("GC_DB_BACKEND", "sqlite").strip().lower()
    if backend != "postgres":
        _emit("fatal", reason="postgres_required", backend=backend)
        return 2

    order_id, player_id = args.target
    if args.apply and not args.confirm_payment_and_missing_rewards:
        _emit(
            "fatal",
            reason="explicit_confirmation_required",
            order_id=order_id,
            player_id=player_id,
        )
        return 2

    from game.config import init_config
    from game.db import begin_write_transaction, commit, db, rollback
    from game.db_pg import close_pool
    from game.shop import get_order
    from game.shop_recovery import repair_verified_paid_order

    init_config()
    conn = db()
    try:
        order = get_order(order_id, conn=conn)
        if not order:
            _emit("failure", order_id=order_id, player_id=player_id, reason="order_not_found")
            return 1
        if int(order["player_id"]) != player_id:
            _emit("failure", order_id=order_id, player_id=player_id, reason="player_mismatch")
            return 1

        _emit(
            "candidate",
            apply=bool(args.apply),
            order_id=order_id,
            player_id=player_id,
            status=str(order.get("status") or ""),
            paid_at_present=bool(order.get("paid_at")),
            provider=str(order.get("provider") or ""),
            provider_payment_id_present=bool(order.get("provider_payment_id")),
            provider_session_id_present=bool(order.get("provider_session_id")),
        )
        if not args.apply:
            return 0

        begin_write_transaction(conn)
        try:
            ok, reason, out = repair_verified_paid_order(
                order_id,
                conn=conn,
                expected_player_id=player_id,
                reason="operator_verified_paid_and_missing_rewards_after_paypal_session_expired",
                metadata={
                    "runner": "scripts/repair_verified_paid_shop_order.py",
                    "incident": "GC-PROD-PAYPAL-PG-43",
                    "operator_confirmation": True,
                },
            )
            if not ok:
                rollback(conn)
                _emit("failure", order_id=order_id, player_id=player_id, reason=reason)
                return 1
            commit(conn)
            _emit(
                "repaired",
                order_id=order_id,
                player_id=player_id,
                reason=reason,
                final_status=str((out or {}).get("status") or ""),
                granted=(out or {}).get("granted"),
            )
            return 0
        except Exception as exc:
            rollback(conn)
            _emit(
                "failure",
                order_id=order_id,
                player_id=player_id,
                reason=type(exc).__name__,
            )
            return 1
    finally:
        try:
            conn.close()
        finally:
            close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
