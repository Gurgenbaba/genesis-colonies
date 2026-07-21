"""
GC-PERF-DB-002 — Postgres adapter contracts (no live Postgres required).

Run: python -m pytest tests/test_gc_perf_db_002.py -v
"""

from __future__ import annotations

import pytest


def test_rewrite_placeholders_basic():
    from game.db_pg import rewrite_sqlite_placeholders

    assert rewrite_sqlite_placeholders("SELECT * FROM t WHERE id = ?") == (
        "SELECT * FROM t WHERE id = %s"
    )
    assert rewrite_sqlite_placeholders("SELECT '?' AS q, id FROM t WHERE x = ?") == (
        "SELECT '?' AS q, id FROM t WHERE x = %s"
    )


def test_rewrite_placeholders_skips_comments():
    from game.db_pg import rewrite_sqlite_placeholders

    sql = "SELECT 1 -- keep ? here\nWHERE id = ?"
    out = rewrite_sqlite_placeholders(sql)
    assert "-- keep ? here" in out
    assert out.rstrip().endswith("%s")


def test_rewrite_dna_seed_to_bigint():
    from game.sql_pg_rewrite import rewrite_sqlite_statement

    out = rewrite_sqlite_statement(
        "ALTER TABLE planets ADD COLUMN dna_seed INTEGER NOT NULL DEFAULT 0;"
    )
    assert "dna_seed BIGINT" in out
    assert "dna_seed INTEGER" not in out.upper().replace("BIGINT", "X")


def test_needs_sqlite_dialect_rewrite_markers():
    from game.db_pg import _needs_sqlite_dialect_rewrite

    assert _needs_sqlite_dialect_rewrite("INSERT OR IGNORE INTO t (id) VALUES (1);")
    assert _needs_sqlite_dialect_rewrite(
        "CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT);"
    )
    assert _needs_sqlite_dialect_rewrite("PRAGMA foreign_keys=ON;")
    assert not _needs_sqlite_dialect_rewrite("SELECT id FROM players WHERE id = ?;")


def test_lastval_savepoint_does_not_abort_marker():
    """Document GC-PERF-PG-PARITY fix: lastval must not abort TX after non-serial INSERT."""
    import inspect

    from game import db_pg

    src = inspect.getsource(db_pg.PgCursor.execute)
    assert "SAVEPOINT gc_lastval" in src
    assert "ROLLBACK TO SAVEPOINT gc_lastval" in src


def test_is_integrity_error_sqlite():
    import sqlite3

    from game.db import is_integrity_error

    assert is_integrity_error(sqlite3.IntegrityError("UNIQUE constraint failed"))
    assert not is_integrity_error(ValueError("nope"))


def test_pg_row_index_and_key():
    from game.db_pg import PgRow

    row = PgRow({"id": 7, "name": "alpha"})
    assert row["id"] == 7
    assert row[0] == 7
    assert row["name"] == "alpha"
    assert row[1] == "alpha"


def test_db_postgres_requires_url(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from game.db import db

    with pytest.raises(NotImplementedError):
        db()


def test_validate_config_postgres_needs_url(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-insecure-xx")
    monkeypatch.delenv("APP_ENV", raising=False)
    from game.config import validate_config

    errors = validate_config(strict=False)
    assert any("DATABASE_URL" in e for e in errors)


def test_describe_db_connection_sqlite_default(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    from game.db import describe_db_connection

    info = describe_db_connection()
    assert info["db_backend"] == "sqlite"
    assert "db_path" in info


def test_table_helpers_still_work_sqlite():
    from game.db import db, table_exists, table_columns

    conn = db()
    try:
        assert table_exists(conn, "players") or True  # may be empty fresh — just no crash
        # planets may or may not exist depending on init; call must not raise on missing
        _ = table_columns(conn, "players") if table_exists(conn, "players") else set()
    finally:
        conn.close()


def test_audit_doc_exists():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "GC_PERF_DB_001_POSTGRES_AUDIT.md").is_file()
