#!/usr/bin/env python3
"""
CLI: run Genesis Colonies queue tick (cron/worker).

Examples:
  python scripts/run_tick.py
  python scripts/run_tick.py --batch-size 50 --source cron
  python scripts/run_tick.py --player-id 3
  python -m game.tick_runner
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.tick_runner import _cli_main

if __name__ == "__main__":
    raise SystemExit(_cli_main())
