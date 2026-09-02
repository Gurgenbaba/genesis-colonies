"""GC-PERF-RUNTIME-001 — runtime_state must not execute schema DDL in steady state."""

from __future__ import annotations

import sqlite3

from game.runtime_state import (
    ensure_runtime_state_table,
    get_runtime_value,
    set_runtime_value,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _ready_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE runtime_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        """
    )
    conn.execute(
        "CREATE INDEX idx_runtime_state_updated ON runtime_state (updated_at DESC);"
    )
    conn.commit()


def _ddl(statements: list[str]) -> list[str]:
    return [
        sql
        for sql in statements
        if "CREATE TABLE" in sql.upper() or "CREATE INDEX" in sql.upper()
    ]


def test_ready_runtime_state_reads_and_writes_execute_no_schema_ddl():
    conn = _conn()
    try:
        _ready_schema(conn)
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        assert get_runtime_value("missing", conn=conn) is None
        set_runtime_value("worker", "ok", conn=conn)
        assert get_runtime_value("worker", conn=conn) == "ok"

        assert _ddl(statements) == []
    finally:
        conn.close()


def test_explicit_ensure_is_read_only_when_schema_is_ready():
    conn = _conn()
    try:
        _ready_schema(conn)
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        ensure_runtime_state_table(conn)

        assert _ddl(statements) == []
        assert any("SELECT 1 FROM RUNTIME_STATE" in sql.upper() for sql in statements)
    finally:
        conn.close()


def test_missing_legacy_schema_is_repaired_lazily_once():
    conn = _conn()
    try:
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        set_runtime_value("legacy", "repaired", conn=conn)
        assert get_runtime_value("legacy", conn=conn) == "repaired"

        ddl_after_repair = _ddl(statements)
        assert any("CREATE TABLE" in sql.upper() for sql in ddl_after_repair)
        assert any("CREATE INDEX" in sql.upper() for sql in ddl_after_repair)

        statements.clear()
        ensure_runtime_state_table(conn)
        assert _ddl(statements) == []
    finally:
        conn.close()
