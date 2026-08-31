"""GC-DB-POSTGRES-001 Phase 1 — int32 overflow → BIGINT widen for import."""

from __future__ import annotations

import sqlite3

from game.schema_bootstrap import (
    _INT32_MAX,
    scan_sqlite_int32_overflow_columns,
)


def test_scan_sqlite_int32_overflow_finds_banned_until(tmp_path) -> None:
    db = tmp_path / "overflow.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY, banned_until INTEGER);"
    )
    conn.execute(
        "INSERT INTO players (id, banned_until) VALUES (1, ?);",
        (_INT32_MAX + 100,),
    )
    conn.commit()
    hits = scan_sqlite_int32_overflow_columns(conn)
    conn.close()
    assert ("players", "banned_until", _INT32_MAX + 100, _INT32_MAX + 100) in [
        (t, c, mn, mx) for t, c, mn, mx in hits
    ]


def test_scan_ignores_in_range_integers(tmp_path) -> None:
    db = tmp_path / "ok.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, n INTEGER);")
    conn.execute("INSERT INTO players (id, n) VALUES (1, 42);")
    conn.commit()
    hits = scan_sqlite_int32_overflow_columns(conn)
    conn.close()
    assert hits == []
