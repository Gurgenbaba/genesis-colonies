"""Regression gates for live-safe PostgreSQL hot-path index setup."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import game.pg_hotpath_indexes as hot

ROOT = Path(__file__).resolve().parents[1]


class _FakeConn:
    def __init__(self, *, fail_index: str | None = None) -> None:
        self.sql: list[str] = []
        self.closed = False
        self.fail_index = fail_index

    def execute(self, sql, params=None):  # noqa: ANN001
        text = str(sql)
        self.sql.append(text)
        if "information_schema.tables" in text:
            return SimpleNamespace(fetchone=lambda: {"exists": 1})
        if self.fail_index and self.fail_index in text:
            raise RuntimeError("synthetic optional index failure")
        return SimpleNamespace(fetchone=lambda: None)

    def close(self) -> None:
        self.closed = True


def test_index_catalog_is_concurrent_additive_and_targeted():
    sql = "\n".join(entry[2] for entry in hot.HOTPATH_INDEXES)
    upper = sql.upper()
    assert upper.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == len(hot.HOTPATH_INDEXES)
    assert "DROP TABLE" not in upper
    assert "DROP COLUMN" not in upper
    assert "ALTER TABLE" not in upper
    assert "DELETE FROM" not in upper
    assert "UPDATE " not in upper
    assert "world_boss_events(status, ends_at, starts_at, id)" in sql
    assert "shipyard_queue(planet_id, status, queue_position, id)" in sql
    assert "shipyard_queue(status, finish_at, planet_id)" in sql


def test_postgres_uses_one_direct_connection_low_session_limits_and_closes(monkeypatch):
    import game.config
    import game.db
    import game.db_pg

    conn = _FakeConn()
    monkeypatch.setattr(game.config, "init_config", lambda: None)
    monkeypatch.setattr(game.db, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(game.db_pg, "connect_postgres_migration", lambda: conn)

    assert hot.ensure_hotpath_indexes() == len(hot.HOTPATH_INDEXES)
    assert conn.closed is True
    assert "SET statement_timeout = '15000ms';" in conn.sql
    assert "SET lock_timeout = '1000ms';" in conn.sql
    ddl = [sql for sql in conn.sql if sql.upper().startswith("CREATE INDEX")]
    assert len(ddl) == len(hot.HOTPATH_INDEXES)
    assert all("CONCURRENTLY" in sql.upper() for sql in ddl)
    assert not any("BEGIN" in sql.upper() for sql in conn.sql)
    assert not any("SAVEPOINT" in sql.upper() for sql in conn.sql)


def test_optional_index_failure_does_not_abort_remaining_indexes(monkeypatch):
    import game.config
    import game.db
    import game.db_pg

    conn = _FakeConn(fail_index="idx_world_boss_events_status_window_id")
    monkeypatch.setattr(game.config, "init_config", lambda: None)
    monkeypatch.setattr(game.db, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(game.db_pg, "connect_postgres_migration", lambda: conn)

    ready = hot.ensure_hotpath_indexes()
    assert ready == len(hot.HOTPATH_INDEXES) - 1
    assert conn.closed is True
    assert any("idx_shipyard_queue_status_finish_planet" in sql for sql in conn.sql)


def test_connection_failure_is_fail_open(monkeypatch):
    import game.config
    import game.db
    import game.db_pg

    monkeypatch.setattr(game.config, "init_config", lambda: None)
    monkeypatch.setattr(game.db, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(
        game.db_pg,
        "connect_postgres_migration",
        lambda: (_ for _ in ()).throw(RuntimeError("synthetic connect failure")),
    )
    assert hot.ensure_hotpath_indexes() == 0


def test_sqlite_module_invocation_exits_zero_from_repo_root(tmp_path):
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env["GC_DB_PATH"] = str(tmp_path / "hotpath-index-noop.db")
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "game.pg_hotpath_indexes"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "skipped (non-postgres backend)" in proc.stdout


def test_entrypoint_invocation_is_absolute_fail_open_and_preserves_close_pool():
    src = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    migration_pos = src.index("python migrate.py")
    index_pos = src.index("python -m game.pg_hotpath_indexes")
    gunicorn_pos = src.index("exec gunicorn")
    assert migration_pos < index_pos < gunicorn_pos
    assert 'python -m game.pg_hotpath_indexes || echo' in src
    assert src.count("python -m game.pg_hotpath_indexes") == 1
    # #141 deploy-hygiene fix must remain intact for short-lived seed pools.
    assert src.count("from game.db_pg import close_pool") >= 2
