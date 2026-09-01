"""GC-PG-HIGHSPEED-001D regression gates for additive hot-path indexes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from migrate import _required_tables

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "159_pg_hotpath_indexes.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_hotpath_migration_declares_optional_module_preconditions():
    assert _required_tables(_sql()) == ["world_boss_events", "shipyard_queue"]


def test_hotpath_migration_is_additive_only():
    sql = _sql().upper()
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
    assert "ALTER TABLE" not in sql
    assert "DELETE FROM" not in sql
    assert "UPDATE " not in sql


def test_hotpath_indexes_match_world_boss_and_shipyard_query_shapes():
    sql = _sql().lower()
    assert "world_boss_events(status, ends_at, starts_at, id)" in sql
    assert "world_boss_events(status, updated_at desc)" in sql
    assert "shipyard_queue(planet_id, status, queue_position, id)" in sql
    assert "shipyard_queue(status, finish_at, planet_id)" in sql


def test_hotpath_migration_is_idempotent_on_compatible_schema():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE world_boss_events ("
            "id INTEGER PRIMARY KEY, status TEXT, starts_at REAL, ends_at REAL, updated_at REAL)"
        )
        conn.execute(
            "CREATE TABLE shipyard_queue ("
            "id INTEGER PRIMARY KEY, planet_id INTEGER, status TEXT, "
            "queue_position INTEGER, finish_at REAL)"
        )
        conn.executescript(_sql())
        conn.executescript(_sql())
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert {
            "idx_world_boss_events_status_window_id",
            "idx_world_boss_events_status_updated",
            "idx_shipyard_queue_planet_status_pos_id",
            "idx_shipyard_queue_status_finish_planet",
        } <= indexes
    finally:
        conn.close()
