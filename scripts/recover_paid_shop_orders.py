#!/usr/bin/env python3
"""Recover paid PayPal shop orders after a fulfillment outage.

Safe defaults:
- dry-run unless --apply is supplied
- PayPal is the source of truth for open orders
- only COMPLETED PayPal orders are eligible
- amount/currency/owner checks are delegated to the normal recovery pipeline
- falsely-fulfilled orders are never regranted automatically; use explicit
  --repair-fulfilled ORDER_ID:PLAYER_ID after payment/reward verification

Examples:
  python scripts/recover_paid_shop_orders.py --since-hours 72
  python scripts/recover_paid_shop_orders.py --since-hours 72 --apply
  python scripts/recover_paid_shop_orders.py --apply \
      --repair-fulfilled 42:39 --repair-fulfilled 22:39
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_repair(value: str) -> tuple[int, int]:
    try:
        order_s, player_s = str(value).split(":", 1)
        order_id, player_id = int(order_s), int(player_s)
    except Exception as exc:
        raise argparse.ArgumentTypeError("expected ORDER_ID:PLAYER_ID") from exc
    if order_id <= 0 or player_id <= 0:
        raise argparse.ArgumentTypeError("order/player ids must be positive")
    return order_id, player_id


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--since-hours", type=float, default=72.0)
    p.add_argument("--apply", action="store_true")
    p.add_argument(
        "--repair-fulfilled",
        action="append",
        default=[],
        type=_parse_repair,
        metavar="ORDER_ID:PLAYER_ID",
        help="Explicitly regrant an order known to have been falsely marked fulfilled.",
    )
    return p.parse_args()


def _emit(kind: str, **payload) -> None:
    print(json.dumps({"kind": kind, **payload}, ensure_ascii=False, sort_keys=True))


def main() -> int:
    args = _args()
    backend = os.environ.get("GC_DB_BACKEND", "sqlite").strip().lower()
    if backend != "postgres":
        _emit("fatal", reason="postgres_required", backend=backend)
        return 2

    from game.config import init_config
    from game.db import begin_write_transaction, commit, db, rollback
    from game.db_pg import close_pool
    from game.shop import (
        STATUS_FAILED,
        STATUS_PAID,
        STATUS_PENDING,
        get_order,
        recover_paypal_return_for_player,
        repair_fulfilled_order,
    )

    init_config()
    cutoff = time.time() - max(0.0, float(args.since_hours)) * 3600.0
    conn = db()
    recovered = 0
    repaired = 0
    skipped = 0
    failed = 0
    try:
        rows = conn.execute(
            """
            SELECT id, player_id, provider_session_id, provider_payment_id,
                   amount_cents, currency, status, fulfill_reason, created_at
            FROM shop_orders
            WHERE provider = 'paypal'
              AND created_at >= ?
              AND status IN (?, ?, ?)
            ORDER BY id ASC;
            """,
            (cutoff, STATUS_PENDING, STATUS_PAID, STATUS_FAILED),
        ).fetchall()
        _emit(
            "scan",
            apply=bool(args.apply),
            since_hours=float(args.since_hours),
            open_orders=len(rows),
            explicit_repairs=len(args.repair_fulfilled),
        )

        for row in rows:
            order_id = int(row["id"])
            player_id = int(row["player_id"])
            token = str(row["provider_session_id"] or "").strip()
            if not token:
                skipped += 1
                _emit(
                    "skip",
                    order_id=order_id,
                    player_id=player_id,
                    status=str(row["status"]),
                    reason="missing_provider_session_id",
                )
                continue
            if not args.apply:
                _emit(
                    "candidate",
                    order_id=order_id,
                    player_id=player_id,
                    status=str(row["status"]),
                    provider_session_id_present=True,
                )
                continue

            begin_write_transaction(conn)
            try:
                ok, reason, out = recover_paypal_return_for_player(
                    player_id, token, conn=conn
                )
                if ok:
                    commit(conn)
                    recovered += 1
                    _emit(
                        "recovered",
                        order_id=order_id,
                        player_id=player_id,
                        reason=reason,
                        final_status=str((out or {}).get("status") or ""),
                    )
                else:
                    rollback(conn)
                    if reason == "paypal_not_paid":
                        skipped += 1
                        _emit(
                            "skip",
                            order_id=order_id,
                            player_id=player_id,
                            reason=reason,
                        )
                    else:
                        failed += 1
                        _emit(
                            "failure",
                            order_id=order_id,
                            player_id=player_id,
                            reason=reason,
                        )
            except Exception as exc:
                rollback(conn)
                failed += 1
                _emit(
                    "failure",
                    order_id=order_id,
                    player_id=player_id,
                    reason=type(exc).__name__,
                )

        for order_id, player_id in args.repair_fulfilled:
            order = get_order(order_id, conn=conn)
            if not order:
                failed += 1
                _emit("failure", order_id=order_id, player_id=player_id, reason="order_not_found")
                continue
            if int(order["player_id"]) != player_id:
                failed += 1
                _emit("failure", order_id=order_id, player_id=player_id, reason="player_mismatch")
                continue
            if not args.apply:
                _emit(
                    "explicit_repair_candidate",
                    order_id=order_id,
                    player_id=player_id,
                    status=str(order.get("status") or ""),
                    fulfill_reason=str(order.get("fulfill_reason") or ""),
                )
                continue

            begin_write_transaction(conn)
            try:
                ok, reason, out = repair_fulfilled_order(
                    order_id,
                    conn=conn,
                    expected_player_id=player_id,
                    reason="postgres_payment_outage_verified_paid_missing_rewards",
                    metadata={
                        "runner": "scripts/recover_paid_shop_orders.py",
                        "incident": "GC-PROD-PAYPAL-PG-43",
                    },
                )
                if not ok:
                    rollback(conn)
                    failed += 1
                    _emit("failure", order_id=order_id, player_id=player_id, reason=reason)
                    continue
                commit(conn)
                repaired += 1
                _emit(
                    "repaired",
                    order_id=order_id,
                    player_id=player_id,
                    reason=reason,
                    final_status=str((out or {}).get("status") or ""),
                    granted=(out or {}).get("granted"),
                )
            except Exception as exc:
                rollback(conn)
                failed += 1
                _emit(
                    "failure",
                    order_id=order_id,
                    player_id=player_id,
                    reason=type(exc).__name__,
                )

        _emit(
            "summary",
            apply=bool(args.apply),
            recovered=recovered,
            repaired=repaired,
            skipped=skipped,
            failed=failed,
        )
        return 1 if failed else 0
    finally:
        try:
            conn.close()
        finally:
            close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
