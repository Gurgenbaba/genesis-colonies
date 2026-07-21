#!/usr/bin/env python3
"""
GC-PERF-WORKER-001 — long-running game worker loop (queue + fleet).

Uses the same owners as HTTP cron / request path:
  - game.tick_runner.run_tick → finish_due_work
  - game.fleet_worker (already inside run_tick)

Examples:
  python scripts/run_game_worker.py
  python scripts/run_game_worker.py --interval 15 --once

Set GC_GAME_WORKER_PRIMARY=1 on web processes so diet polls skip periodic finish.
Requires Postgres (or careful single-writer SQLite) when running beside web workers.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis Colonies game worker loop")
    parser.add_argument("--interval", type=float, default=15.0, help="Seconds between ticks")
    parser.add_argument("--once", action="store_true", help="Run a single tick then exit")
    parser.add_argument("--source", type=str, default="game_worker", help="Tick source label")
    args = parser.parse_args()

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application
    from game.internal_cron import execute_queue_tick, log_queue_tick_result

    bootstrap_application(skip_migration_check=True)
    interval = max(1.0, float(args.interval))

    while True:
        result = execute_queue_tick(force=True, source=args.source)
        log_queue_tick_result(result, log_prefix="game-worker", source_label=args.source)
        print(json.dumps({"ok": result.get("ok"), "duration_ms": result.get("duration_ms"), "players": result.get("players_processed")}, ensure_ascii=False))
        if args.once:
            return 0 if result.get("ok") else 1
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
