#!/usr/bin/env python3
"""GC-822 — Live economy audit CLI (read-only).

Usage:
  python scripts/economy_live_audit.py
  python scripts/economy_live_audit.py --player-id 42
  python scripts/economy_live_audit.py --top 20 --min-mine 30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="GC-822 live economy audit (read-only)")
    parser.add_argument("--player-id", type=int, default=0, help="Audit single player")
    parser.add_argument("--top", type=int, default=25, help="Max players in universe scan")
    parser.add_argument("--min-mine", type=int, default=0, help="Min max mine level filter")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    from game.db import db
    from game.economy_live_audit import audit_player, audit_universe, player_audit_to_dict

    conn = db()
    try:
        if args.player_id > 0:
            audit = audit_player(int(args.player_id), conn=conn)
            payload = player_audit_to_dict(audit)
        else:
            payload = audit_universe(conn=conn, limit=int(args.top), min_max_mine_level=int(args.min_mine))

        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
