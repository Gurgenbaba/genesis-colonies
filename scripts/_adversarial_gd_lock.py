#!/usr/bin/env python3
"""Adversarial gd_cycles SCAN + lock-wait experiment (local temp DB only)."""
from __future__ import annotations

import shutil
import sqlite3
import threading
import time
from pathlib import Path

seed = Path("artifacts/prod_infinity_load_ab/100x/seed.db")
adv = Path("artifacts/prod_infinity_load_ab/adversarial")
adv.mkdir(parents=True, exist_ok=True)
dbp = adv / "adv.db"
if dbp.exists():
    dbp.unlink()
shutil.copy2(seed, dbp)

conn = sqlite3.connect(str(dbp))
conn.row_factory = sqlite3.Row
now = int(time.time())
for i in range(5000):
    g = 1 + (i % 9)
    try:
        conn.execute(
            """
            INSERT INTO gd_cycles (
                galaxy, year, month, vote_start_at, vote_end_at,
                effect_start_at, effect_end_at, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'vote_open', ?, ?);
            """,
            (
                g,
                2100 + (i // 12),
                1 + (i % 12),
                now - 10,
                now + 86400,
                now + 90000,
                now + 200000,
                now,
                now,
            ),
        )
    except Exception:
        pass
conn.commit()
print("gd_cycles", conn.execute("SELECT COUNT(*) AS c FROM gd_cycles").fetchone()["c"])
print(
    "vote_open",
    conn.execute(
        "SELECT COUNT(*) AS c FROM gd_cycles WHERE status = 'vote_open'"
    ).fetchone()["c"],
)
print("planets", conn.execute("SELECT COUNT(*) AS c FROM planets").fetchone()["c"])

pid = 2
galaxies = [
    int(r["galaxy"])
    for r in conn.execute(
        "SELECT DISTINCT galaxy FROM planets WHERE player_id = ?",
        (pid,),
    ).fetchall()
]
sql013 = (
    "SELECT COUNT(*) AS c FROM gd_cycles c "
    "WHERE c.status = 'vote_open' AND c.vote_start_at <= ? AND c.vote_end_at >= ? "
    "AND EXISTS (SELECT 1 FROM planets p WHERE p.player_id = ? AND p.galaxy = c.galaxy) "
    "AND NOT EXISTS (SELECT 1 FROM gd_votes v WHERE v.cycle_id = c.id AND v.player_id = ?)"
)
ph = ",".join("?" * len(galaxies))
sql_st = (
    f"SELECT COUNT(*) AS c FROM gd_cycles c WHERE c.galaxy IN ({ph}) "
    "AND c.status = 'vote_open' AND c.vote_start_at <= ? AND c.vote_end_at >= ? "
    "AND NOT EXISTS (SELECT 1 FROM gd_votes v WHERE v.cycle_id = c.id AND v.player_id = ?)"
)

for name, sql, params in [
    ("013", sql013, (now, now, pid, pid)),
    ("stable", sql_st, (*galaxies, now, now, pid)),
]:
    t0 = time.perf_counter()
    for _ in range(20):
        conn.execute(sql, params).fetchone()
    ms = (time.perf_counter() - t0) * 1000 / 20
    plan = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    print(name, "avg_ms", round(ms, 3), "plan0", plan[0])
conn.close()


def writer() -> None:
    c = sqlite3.connect(str(dbp), timeout=30)
    c.execute("PRAGMA busy_timeout=20000")
    t0 = time.perf_counter()
    c.execute("BEGIN IMMEDIATE")
    print("writer got lock", round((time.perf_counter() - t0) * 1000, 1))
    time.sleep(3)
    c.execute("COMMIT")
    c.close()
    print("writer released")


def reader(tag: str) -> None:
    c = sqlite3.connect(str(dbp), timeout=30)
    c.execute("PRAGMA busy_timeout=20000")
    c.row_factory = sqlite3.Row
    t0 = time.perf_counter()
    try:
        c.execute(sql013, (now, now, pid, pid)).fetchone()
        print(tag, "read_ok", round((time.perf_counter() - t0) * 1000, 1))
    except Exception as exc:  # noqa: BLE001
        print(tag, "read_err", exc, round((time.perf_counter() - t0) * 1000, 1))
    t1 = time.perf_counter()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("COMMIT")
        print(tag, "write_ok", round((time.perf_counter() - t1) * 1000, 1))
    except Exception as exc:  # noqa: BLE001
        print(tag, "write_err", exc, round((time.perf_counter() - t1) * 1000, 1))
    c.close()


wt = threading.Thread(target=writer)
wt.start()
time.sleep(0.2)
rts = [threading.Thread(target=reader, args=(f"R{i}",)) for i in range(4)]
for t in rts:
    t.start()
for t in rts:
    t.join()
wt.join()
