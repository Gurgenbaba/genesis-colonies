#!/usr/bin/env python3
"""
CLI: run Genesis Colonies ranking worker (cron every 10 minutes).

One-shot: computes all scores/ranks, prints JSON, exits 0/1. Safe for Railway Cron
(separate service — not the web process).

Examples:
  python scripts/run_ranking_worker.py
  python scripts/run_ranking_worker.py --source cron
  python scripts/run_ranking_worker.py --force
  python -m game.ranking_worker

Railway Cron Service (same repo, env, volume/DB as web):
  Start:  python scripts/run_ranking_worker.py --source cron
  Schedule: */10 * * * *   (UTC)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.ranking_worker import _cli_main

if __name__ == "__main__":
    raise SystemExit(_cli_main())
