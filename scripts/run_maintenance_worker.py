#!/usr/bin/env python3
"""
GC-PERF-PROD-002 — maintenance bag in a process separate from gunicorn.

Owns the same ``run_maintenance_bag`` as the former in-process embedded cron
(ranking + fleet/post-maint autoplay+pirates + vote + deletions + sqlite backup)
so HTTP workers do not share the GIL with multi-second Soft-On ticks.

Examples:
  python scripts/run_maintenance_worker.py
  python scripts/run_maintenance_worker.py --once

Production: ``scripts/docker-entrypoint.sh`` starts this as a sidecar and sets
``GC_EMBEDDED_CRON=0`` / ``GC_MAINTENANCE_WORKER=1`` on the web process.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _maybe_run_uni1_prelaunch_reset() -> None:
    token = str(os.environ.get("GC_UNI1_PRELAUNCH_RESET_TOKEN", "") or "").strip()
    if not token:
        return

    from game.uni1_prelaunch import run_uni1_prelaunch_reset_once

    result = run_uni1_prelaunch_reset_once(token)
    print(
        "[maintenance-worker] UNI1 prelaunch reset: "
        f"skipped={bool(result.get('skipped'))} "
        f"token={result.get('token')!r}",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis Colonies maintenance worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single maintenance bag tick then exit",
    )
    args = parser.parse_args()

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")
    # Sidecar owns the bag — never start an in-process cron thread here.
    os.environ["GC_MAINTENANCE_WORKER"] = "1"
    os.environ["GC_EMBEDDED_CRON"] = "0"

    from game.bootstrap import bootstrap_application
    from game.internal_cron import run_maintenance_worker_loop

    bootstrap_application(skip_migration_check=True)
    _maybe_run_uni1_prelaunch_reset()
    run_maintenance_worker_loop(once=bool(args.once))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
