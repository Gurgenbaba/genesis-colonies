#!/usr/bin/env python3
"""
GC-PERF-WORKER-001 — long-running game worker loop.

Default/manual mode preserves the historical queue+fleet cron behavior.
Production PostgreSQL uses ``--queue-only``: due economy queues are completed in
this sidecar while fleet/World-Boss/post-maint remain owned by the separate
maintenance worker. This keeps `/api/game-state` out of the queue-finish write
path without multiplying the maintenance cadence.

Examples:
  python scripts/run_game_worker.py
  python scripts/run_game_worker.py --interval 5 --queue-only
  python scripts/run_game_worker.py --once --queue-only

Set GC_GAME_WORKER_PRIMARY=1 on web processes so polls only keep the stale-worker
safety net. PostgreSQL is the intended side-by-side production backend.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _default_interval() -> float:
    raw = os.environ.get("GC_GAME_WORKER_SEC", "").strip()
    try:
        return max(2.0, float(raw)) if raw else 5.0
    except (TypeError, ValueError):
        return 5.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis Colonies game worker loop")
    parser.add_argument(
        "--interval",
        type=float,
        default=_default_interval(),
        help="Seconds between ticks (production queue-only default: 5)",
    )
    parser.add_argument("--once", action="store_true", help="Run a single tick then exit")
    parser.add_argument("--source", type=str, default="game_worker", help="Tick source label")
    parser.add_argument(
        "--queue-only",
        action="store_true",
        help="Finish due queues only; do not run global fleet/post-maint or inbox retention tail",
    )
    args = parser.parse_args()

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    interval = max(2.0, float(args.interval))

    if args.queue_only:
        from game.tick_runner import run_tick

        def _tick():
            return run_tick(
                scope="due",
                source=str(args.source or "queue_worker"),
                persist=True,
                update_scores=True,
                recalc_ranks=False,
                include_fleet_tail=False,
                include_inbox_retention=False,
            )

        log_prefix = "queue-worker"
    else:
        from game.internal_cron import execute_queue_tick

        def _tick():
            return execute_queue_tick(force=True, source=args.source)

        log_prefix = "game-worker"

    print(
        f"[{log_prefix}] started interval_sec={interval:.1f} "
        f"queue_only={str(bool(args.queue_only)).lower()}",
        flush=True,
    )

    while True:
        started = time.perf_counter()
        result = _tick()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        finished = result.get("finished") or {}
        print(
            f"[{log_prefix}] ok={str(bool(result.get('ok'))).lower()} "
            f"players={int(result.get('players_processed') or 0)} "
            f"buildings={int(finished.get('buildings') or 0)} "
            f"research={int(finished.get('research') or 0)} "
            f"shipyard={int(finished.get('shipyard') or 0)} "
            f"defense={int(finished.get('defense') or 0)} "
            f"troops={int(finished.get('troops') or 0)} "
            f"duration_ms={elapsed_ms}",
            flush=True,
        )
        if args.once:
            return 0 if result.get("ok") else 1
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
