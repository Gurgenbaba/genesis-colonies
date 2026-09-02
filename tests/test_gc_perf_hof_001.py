"""GC-PERF-HOF-001 — keep incremental Combat HoF cursor scans indexed."""

from __future__ import annotations

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import init_db
from game.pg_hotpath_indexes import HOTPATH_INDEXES


@pytest.fixture()
def hof_perf_db(tmp_path, monkeypatch):
    db_file = tmp_path / "hof_perf.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    dbmod._DB_PATH = None
    init_db()

    import migrate

    migrate.main()
    yield db_file
    dbmod._DB_PATH = None


def test_combat_hof_cursor_index_is_migrated_for_sqlite(hof_perf_db):
    conn = db()
    try:
        rows = conn.execute("PRAGMA index_list('player_messages');").fetchall()
        names = {str(row["name"]) for row in rows}
        assert "idx_player_messages_combat_cursor" in names
    finally:
        conn.close()


def test_combat_hof_cursor_query_uses_index(hof_perf_db):
    conn = db()
    try:
        rows = conn.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT id, metadata_json, created_at
            FROM player_messages
            WHERE category = 'combat'
              AND id > ?
              AND (deleted_at IS NULL OR deleted_at = 0)
            ORDER BY id ASC
            LIMIT ?;
            """,
            (0, 40),
        ).fetchall()
        detail = "\n".join(str(row["detail"]) for row in rows)
        assert "idx_player_messages_combat_cursor" in detail, detail
    finally:
        conn.close()


def test_postgres_combat_hof_cursor_index_is_concurrent():
    matches = [
        (table, name, sql)
        for table, name, sql in HOTPATH_INDEXES
        if name == "idx_player_messages_combat_cursor"
    ]
    assert len(matches) == 1
    table, _, sql = matches[0]
    normalized = " ".join(str(sql).split()).upper()
    assert table == "player_messages"
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS IDX_PLAYER_MESSAGES_COMBAT_CURSOR" in normalized
    assert "ON PLAYER_MESSAGES(CATEGORY, ID)" in normalized
