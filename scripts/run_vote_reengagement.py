#!/usr/bin/env python3
"""CLI: staggered vote re-engagement for inactive universe players."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.db import begin_write_transaction, commit, db, rollback
from game.vote_reengagement import run_vote_reengagement


def main() -> int:
    parser = argparse.ArgumentParser(description="Run vote re-engagement batch for inactive players")
    parser.add_argument("--force", action="store_true", help="Ignore interval guard and stagger slots")
    parser.add_argument(
        "--catch-all",
        action="store_true",
        help="Reward all currently voteable inactive players (ignores interval/slots; safety cap 5000)",
    )
    parser.add_argument("--batch-size", type=int, default=None, help="Max votes per run (ignored with --catch-all)")
    parser.add_argument("--source", default="cli", help="Source label for logs")
    args = parser.parse_args()

    conn = db()
    try:
        begin_write_transaction(conn)
        payload = run_vote_reengagement(
            conn=conn,
            force=bool(args.force),
            catch_all=bool(args.catch_all),
            batch_size=args.batch_size,
            source=str(args.source or "cli"),
        )
        if payload.get("ok"):
            commit(conn)
        else:
            rollback(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    print(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
