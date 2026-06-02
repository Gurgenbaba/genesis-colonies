#!/usr/bin/env python3
"""
Repair stuck fleet movements (GC-511).

- Outbound ``attack`` with ``arrival_at <= now`` → ``failed``
- ``returning`` with ``return_at <= now`` → ``failed``

Stops ``process_fleet_tick`` from retrying the same row every request.

Safe to run multiple times (only updates rows still in the source status).

Examples:
  python scripts/repair_stuck_fleet_arrivals.py
  python scripts/repair_stuck_fleet_arrivals.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mark stuck outbound attacks and overdue returns as failed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List stuck movements without updating",
    )
    args = parser.parse_args()

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application
    from game.db import begin_write_transaction, commit, db, resolve_db_path, rollback
    from game.fleet import fleet_schema_ready

    bootstrap_application(skip_migration_check=True)

    now = time.time()
    conn = db()

    if not fleet_schema_ready(conn):
        print("Fleet schema not ready — run migrations first.")
        conn.close()
        return 1
    repaired = 0

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, player_id, status, mission_type, arrival_at, return_at,
                   target_galaxy, target_system, target_position
            FROM fleet_movements
            WHERE (
                status = 'outbound'
                AND mission_type = 'attack'
                AND arrival_at <= ?
            ) OR (
                status = 'returning'
                AND return_at IS NOT NULL
                AND return_at <= ?
            )
            ORDER BY id ASC;
            """,
            (now, now),
        )
        rows = cur.fetchall()
        if not rows:
            print(f"No stuck fleet movements (db={resolve_db_path()}).")
            return 0

        if args.dry_run:
            print(f"Dry run — would repair {len(rows)} movement(s) (db={resolve_db_path()}):")
            for row in rows:
                coords = (
                    f"[{row['target_galaxy']}:{row['target_system']}:"
                    f"{row['target_position']}]"
                )
                print(
                    f"  fleet_id={row['id']} player_id={row['player_id']} "
                    f"status={row['status']} mission={row['mission_type']} "
                    f"arrival_at={row['arrival_at']} return_at={row['return_at']} "
                    f"coords={coords}"
                )
            print("\nRun without --dry-run to apply.")
            return 0

        begin_write_transaction(conn)
        for row in rows:
            movement_id = int(row["id"])
            status = str(row["status"] or "")
            if status == "outbound":
                cur.execute(
                    """
                    UPDATE fleet_movements
                    SET status = 'failed', updated_at = ?
                    WHERE id = ? AND status = 'outbound';
                    """,
                    (now, movement_id),
                )
            elif status == "returning":
                cur.execute(
                    """
                    UPDATE fleet_movements
                    SET status = 'failed', updated_at = ?
                    WHERE id = ? AND status = 'returning';
                    """,
                    (now, movement_id),
                )
            else:
                continue
            if int(cur.rowcount or 0) > 0:
                repaired += 1
        commit(conn)
    except Exception as exc:
        rollback(conn)
        print(f"Repair failed: {exc}")
        raise
    finally:
        conn.close()

    print(f"Repaired {repaired} stuck fleet movement(s) (db={resolve_db_path()}).")
    if repaired:
        print("Restart the app if it was running; fleet tick will no longer retry these movements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
