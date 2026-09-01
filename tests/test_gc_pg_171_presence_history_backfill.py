from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "159_player_presence_history_backfill.sql"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE players (id INTEGER PRIMARY KEY REFERENCES users(id), last_seen INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute(
        """
        CREATE TABLE player_presence (
            player_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            last_seen INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


def test_presence_history_backfill_keeps_newest_and_is_idempotent():
    migration = MIGRATION.read_text(encoding="utf-8")
    conn = _conn()
    try:
        conn.executemany("INSERT INTO users (id) VALUES (?)", [(1,), (2,), (3,), (4,)])
        conn.executemany(
            "INSERT INTO players (id, last_seen) VALUES (?, ?)",
            [(1, 100), (2, 200), (3, 300), (4, 0)],
        )
        # id=2 canonical presence is newer and must win.
        # id=3 legacy presence is newer and must be rescued once.
        conn.executemany(
            "INSERT INTO player_presence (player_id, last_seen, updated_at) VALUES (?, ?, ?)",
            [(2, 250, 250), (3, 150, 150)],
        )

        conn.executescript(migration)
        conn.executescript(migration)

        rows = {
            int(row[0]): (int(row[1]), int(row[2]))
            for row in conn.execute(
                "SELECT player_id, last_seen, updated_at FROM player_presence ORDER BY player_id"
            ).fetchall()
        }
        assert rows == {
            1: (100, 100),
            2: (250, 250),
            3: (300, 300),
        }
    finally:
        conn.close()


def test_presence_history_backfill_is_portable_and_non_destructive():
    migration = MIGRATION.read_text(encoding="utf-8")
    upper = migration.upper()

    assert "GC-REQUIRES-TABLES: USERS, PLAYERS, PLAYER_PRESENCE" in upper
    assert "INSERT OR " not in upper
    assert "PRAGMA" not in upper
    assert "DROP TABLE" not in upper
    assert "DROP COLUMN" not in upper
    assert "UPDATE PLAYERS" not in upper
    assert "UPDATE PLAYER_PRESENCE" in upper
    assert "INSERT INTO PLAYER_PRESENCE" in upper
