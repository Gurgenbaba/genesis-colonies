"""GC-PG-HIGHSPEED-001D regression gates for additive hot-path indexes."""

from __future__ import annotations

from pathlib import Path

import game.pg_hotpath_indexes as hot

ROOT = Path(__file__).resolve().parents[1]


class _Conn:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, sql, params=None):  # noqa: ANN001
        self.sql.append(str(sql))
        return self

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_sqlite_is_noop(monkeypatch):
    monkeypatch.setattr(hot, "get_db_backend", lambda: "sqlite")
    assert hot.ensure_postgres_hotpath_indexes() == 0


def test_caller_owned_connection_is_not_committed_or_closed(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(hot, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(hot, "table_exists", lambda _conn, _table: True)

    attempted = hot.ensure_postgres_hotpath_indexes(conn=conn)

    assert attempted == len(hot.HOTPATH_INDEXES)
    assert conn.committed is False
    assert conn.rolled_back is False
    assert conn.closed is False


def test_startup_owned_connection_commits_and_closes(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(hot, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(hot, "db", lambda: conn)
    monkeypatch.setattr(hot, "table_exists", lambda _conn, _table: True)
    monkeypatch.setattr(hot, "commit", lambda c: c.commit())
    monkeypatch.setattr(hot, "rollback", lambda c: c.rollback())

    hot.ensure_postgres_hotpath_indexes()

    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True


def test_missing_optional_tables_are_skipped(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(hot, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(hot, "table_exists", lambda _conn, _table: False)

    assert hot.ensure_postgres_hotpath_indexes(conn=conn) == 0
    assert conn.sql == []


def test_index_catalog_covers_world_boss_and_shipyard_query_shapes():
    sql = "\n".join(entry[2].lower() for entry in hot.HOTPATH_INDEXES)
    assert "world_boss_events(status, ends_at, starts_at, id)" in sql
    assert "world_boss_events(status, updated_at desc)" in sql
    assert "shipyard_queue(planet_id, status, queue_position, id)" in sql
    assert "shipyard_queue(status, finish_at, planet_id)" in sql


def test_bootstrap_runs_hotpath_ensure_best_effort_after_db_init():
    src = (ROOT / "game" / "bootstrap.py").read_text(encoding="utf-8")
    init_pos = src.index("_init_db_with_retry()")
    ensure_pos = src.index("ensure_postgres_hotpath_indexes()")
    purge_pos = src.index("purge_stale_idempotency_global()", ensure_pos)
    assert init_pos < ensure_pos < purge_pos
