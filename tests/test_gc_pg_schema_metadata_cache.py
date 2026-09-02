"""GC-PERF-PG-SCHEMA-CACHE-001 — schema metadata must not hit information_schema per request."""

from __future__ import annotations

from game import db_pg


class _RowsCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _MetadataConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), tuple(params or ())))
        if "information_schema.columns" in str(sql):
            return _RowsCursor([{"name": "id"}, {"name": "status"}])
        if "information_schema.tables" in str(sql):
            return _RowsCursor([{"ok": 1}])
        raise AssertionError(f"unexpected SQL: {sql}")


class _RawDdlCursor:
    def __init__(self):
        self.description = None
        self.rowcount = -1
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((str(sql), tuple(params or ())))
        self.description = None
        self.rowcount = -1
        return self


def setup_function(_func):
    db_pg.clear_postgres_schema_metadata_cache()


def teardown_function(_func):
    db_pg.clear_postgres_schema_metadata_cache()


def test_postgres_table_columns_is_process_cached_and_copy_safe():
    conn = _MetadataConn()

    first = db_pg.postgres_table_columns(conn, "world_boss_contributions")
    second = db_pg.postgres_table_columns(conn, "world_boss_contributions")

    assert first == {"id", "status"}
    assert second == first
    column_queries = [sql for sql, _params in conn.calls if "information_schema.columns" in sql]
    assert len(column_queries) == 1

    first.add("mutated_by_caller")
    third = db_pg.postgres_table_columns(conn, "world_boss_contributions")
    assert "mutated_by_caller" not in third
    assert len([sql for sql, _params in conn.calls if "information_schema.columns" in sql]) == 1


def test_table_exists_and_columns_share_explicit_cache_invalidation():
    conn = _MetadataConn()

    assert db_pg.postgres_table_exists(conn, "demo") is True
    assert db_pg.postgres_table_exists(conn, "demo") is True
    assert db_pg.postgres_table_columns(conn, "demo") == {"id", "status"}
    assert db_pg.postgres_table_columns(conn, "demo") == {"id", "status"}

    assert len([sql for sql, _ in conn.calls if "information_schema.tables" in sql]) == 1
    assert len([sql for sql, _ in conn.calls if "information_schema.columns" in sql]) == 1

    db_pg.clear_postgres_schema_metadata_cache("demo")
    assert db_pg.postgres_table_exists(conn, "demo") is True
    assert db_pg.postgres_table_columns(conn, "demo") == {"id", "status"}

    assert len([sql for sql, _ in conn.calls if "information_schema.tables" in sql]) == 2
    assert len([sql for sql, _ in conn.calls if "information_schema.columns" in sql]) == 2


def test_pg_cursor_successful_ddl_invalidates_metadata_cache():
    conn = _MetadataConn()
    assert db_pg.postgres_table_columns(conn, "demo") == {"id", "status"}
    assert len(conn.calls) == 1

    raw = _RawDdlCursor()
    cursor = db_pg.PgCursor(raw)
    cursor.execute("ALTER TABLE demo ADD COLUMN cache_probe INTEGER;")

    assert db_pg.postgres_table_columns(conn, "demo") == {"id", "status"}
    assert len([sql for sql, _ in conn.calls if "information_schema.columns" in sql]) == 2
