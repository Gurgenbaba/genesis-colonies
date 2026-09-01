"""GC-PG-175 — active planet context must not contend on PostgreSQL players rows."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class _FakeCursor:
    def __init__(self):
        self.sql: list[str] = []
        self.params: list[tuple] = []
        self._last = ""

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.sql.append(text)
        self.params.append(tuple(params or ()))
        self._last = text
        return self

    def fetchone(self):
        if "SELECT active_planet_id FROM player_context" in self._last:
            return {"active_planet_id": 22}
        if "SELECT id FROM planets" in self._last:
            return {"id": 22}
        return None


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()

    def cursor(self):
        return self.cur


def test_postgres_switch_writes_player_context_not_players(monkeypatch):
    from game.planet_evolution import repository

    conn = _FakeConn()
    monkeypatch.setattr(repository, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(repository, "table_exists", lambda _conn, table: table == "player_context")

    repository.set_active_planet_id(7, 22, conn)

    joined = "\n".join(conn.cur.sql)
    assert "INSERT INTO player_context" in joined
    assert "UPDATE players SET active_planet_id" not in joined


def test_postgres_reader_prefers_canonical_context(monkeypatch):
    from game.planet_evolution import repository

    conn = _FakeConn()
    monkeypatch.setattr(repository, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(repository, "table_exists", lambda _conn, table: table == "player_context")
    monkeypatch.setattr(repository, "column_exists", lambda *_args: (_ for _ in ()).throw(AssertionError("legacy read must not be needed")))

    assert repository.get_active_planet_id(7, conn=conn) == 22
    joined = "\n".join(conn.cur.sql)
    assert "SELECT active_planet_id FROM player_context" in joined
    assert "SELECT active_planet_id FROM players" not in joined


def test_migration_160_backfills_owned_active_planet_only():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE players (id INTEGER PRIMARY KEY, active_planet_id INTEGER);
        CREATE TABLE planets (id INTEGER PRIMARY KEY, player_id INTEGER);
        INSERT INTO users(id) VALUES (1), (2);
        INSERT INTO players(id, active_planet_id) VALUES (1, 11), (2, 11);
        INSERT INTO planets(id, player_id) VALUES (11, 1), (22, 2);
        """
    )
    migration = (ROOT / "migrations/160_player_context.sql").read_text(encoding="utf-8")
    conn.executescript(migration)
    rows = conn.execute(
        "SELECT player_id, active_planet_id FROM player_context ORDER BY player_id"
    ).fetchall()
    assert rows == [(1, 11)]


def test_source_keeps_sqlite_legacy_fallback():
    src = (ROOT / "game/planet_evolution/repository.py").read_text(encoding="utf-8")
    assert 'get_db_backend() == "postgres" and table_exists(conn, "player_context")' in src
    assert "INSERT INTO player_context" in src
    assert "UPDATE players SET active_planet_id = ? WHERE id = ?;" in src
