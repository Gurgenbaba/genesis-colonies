#!/usr/bin/env python3
"""
CLI: run Genesis Colonies ranking worker (local / manual only).

One-shot: computes all scores/ranks, prints JSON, exits 0/1.

Deprecated for Railway SQLite deployment — volumes are service-bound; a separate
worker process cannot share /data/game.db with the web service. Use the web
service HTTP cron instead:

  POST /api/internal/cron/ranking
  Authorization: Bearer $GC_INTERNAL_CRON_TOKEN

Examples (local dev):
  python scripts/run_ranking_worker.py
  python scripts/run_ranking_worker.py --source manual --force
  python scripts/run_ranking_worker.py --force --allow-empty
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
