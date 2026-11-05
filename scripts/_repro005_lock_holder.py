#!/usr/bin/env python3
"""Hold SQLite BEGIN IMMEDIATE for N seconds (REPRO-005 lock microtest).

Run inside the same Docker container (or against the same DB file) so the
web worker's BEGIN IMMEDIATE must wait on this connection.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.environ.get("GC_DB_PATH", ""))
    parser.add_argument("--hold-sec", type=float, default=5.0)
    parser.add_argument("--busy-timeout-ms", type=int, default=30000)
    args = parser.parse_args()
    db = str(args.db or "").strip()
    if not db:
        print("missing --db / GC_DB_PATH", file=sys.stderr)
        return 2

    print(
        f"[LOCK] open={db} hold_sec={args.hold_sec} busy_timeout_ms={args.busy_timeout_ms}",
        flush=True,
    )
    conn = sqlite3.connect(db, timeout=max(1.0, args.busy_timeout_ms / 1000.0))
    try:
        conn.execute(f"PRAGMA busy_timeout={int(args.busy_timeout_ms)}")
        t0 = time.perf_counter()
        conn.execute("BEGIN IMMEDIATE")
        acquired = (time.perf_counter() - t0) * 1000.0
        print(f"[LOCK] acquired_ms={acquired:.1f}", flush=True)
        # Touch a tiny write so the lock is a real reserved write lock.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _repro005_lock_probe (id INTEGER PRIMARY KEY, t REAL)"
        )
        conn.execute("INSERT INTO _repro005_lock_probe(t) VALUES (?)", (time.time(),))
        time.sleep(max(0.1, float(args.hold_sec)))
        conn.commit()
        print(f"[LOCK] released after_hold_sec={args.hold_sec}", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
