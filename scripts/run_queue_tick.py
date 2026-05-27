#!/usr/bin/env python3
"""
CLI: run Genesis Colonies queue tick (cron/worker).

Examples:
  python scripts/run_queue_tick.py
  python scripts/run_queue_tick.py --player-id 3
  python scripts/run_queue_tick.py --source worker
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis Colonies queue tick")
    parser.add_argument("--player-id", type=int, default=None, help="Limit to player id")
    parser.add_argument("--planet-id", type=int, default=None, help="Limit to planet id")
    parser.add_argument("--source", type=str, default="cli", help="Tick source label")
    parser.add_argument("--no-scores", action="store_true", help="Skip score recompute")
    parser.add_argument("--no-ranks", action="store_true", help="Skip rank recalc")
    args = parser.parse_args()

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application
    from game.tick_runner import run_queue_tick, run_tick

    bootstrap_application(skip_migration_check=True)

    if args.player_id is not None or args.planet_id is not None:
        result = run_queue_tick(
            player_id=args.player_id,
            planet_id=args.planet_id,
            source=args.source,
            update_scores=not args.no_scores,
            recalc_ranks=not args.no_ranks,
        )
    else:
        result = run_tick(
            scope="due",
            source=args.source,
            update_scores=not args.no_scores,
            recalc_ranks=not args.no_ranks,
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
