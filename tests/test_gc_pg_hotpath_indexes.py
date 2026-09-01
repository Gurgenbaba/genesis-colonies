"""GC-PG-HIGHSPEED-001D regression gates for live-safe hot-path indexes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import scripts.ensure_pg_hotpath_indexes as hot

ROOT = Path(__file__).resolve().parents[1]


class _FakeConn:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.closed = False

    def execute(self, sql, params=None):  # noqa: ANN001
        text = str(sql)
        self.sql.append(text)
        if "information_schema.tables" in text:
            return SimpleNamespace(fetchone=lambda: {"exists": 1})
        return SimpleNamespace(fetchone=lambda: None)

    def close(self) -> None:
        self.closed = True


def test_hotpath_index_catalog_is_concurrent_and_additive():
    sql = "\n".join(entry[2] for entry in hot.HOTPATH_INDEXES)
    upper = sql.upper()
    assert upper.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == len(hot.HOTPATH_INDEXES)
    assert "DROP TABLE" not in upper
    assert "DROP COLUMN" not in upper
    assert "ALTER TABLE" not in upper
    assert "DELETE FROM" not in upper
    assert "UPDATE " not in upper


def test_hotpath_indexes_match_world_boss_and_shipyard_query_shapes():
    sql = "\n".join(entry[2].lower() for entry in hot.HOTPATH_INDEXES)
    assert "world_boss_events(status, ends_at, starts_at, id)" in sql
    assert "world_boss_events(status, updated_at desc)" in sql
    assert "shipyard_queue(planet_id, status, queue_position, id)" in sql
    assert "shipyard_queue(status, finish_at, planet_id)" in sql


def test_sqlite_path_is_noop_without_postgres_connection(monkeypatch):
    import game.config
    import game.db
    import game.db_pg

    monkeypatch.setattr(game.config, "init_config", lambda: None)
    monkeypatch.setattr(game.db, "get_db_backend", lambda: "sqlite")
    monkeypatch.setattr(
        game.db_pg,
        "connect_postgres_migration",
        lambda: (_ for _ in ()).throw(AssertionError("postgres connection opened on sqlite")),
    )

    assert hot.ensure_hotpath_indexes() == 0


def test_postgres_uses_one_direct_autocommit_connection_and_closes(monkeypatch):
    import game.config
    import game.db
    import game.db_pg

    conn = _FakeConn()
    monkeypatch.setattr(game.config, "init_config", lambda: None)
    monkeypatch.setattr(game.db, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(game.db_pg, "connect_postgres_migration", lambda: conn)

    assert hot.ensure_hotpath_indexes() == len(hot.HOTPATH_INDEXES)
    assert conn.closed is True
    ddl = [sql for sql in conn.sql if sql.upper().startswith("CREATE INDEX")]
    assert len(ddl) == len(hot.HOTPATH_INDEXES)
    assert all("CONCURRENTLY" in sql.upper() for sql in ddl)
    assert not any("BEGIN" in sql.upper() for sql in ddl)
    assert not any("SAVEPOINT" in sql.upper() for sql in conn.sql)


def test_entrypoint_runs_index_ensure_once_after_migrations_before_gunicorn():
    src = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    migration_pos = src.index("python migrate.py")
    index_pos = src.index("python scripts/ensure_pg_hotpath_indexes.py")
    gunicorn_pos = src.index("exec gunicorn")
    assert migration_pos < index_pos < gunicorn_pos
    assert src.count("python scripts/ensure_pg_hotpath_indexes.py") == 1
