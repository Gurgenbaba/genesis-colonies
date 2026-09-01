#!/usr/bin/env python3
"""GC-PG-HIGHSPEED-001D: non-blocking PostgreSQL hot-path index ensure.

Runs once from the container entrypoint after numbered migrations and before the
new Gunicorn process starts. PostgreSQL uses CREATE INDEX CONCURRENTLY on a
direct autocommit connection so the still-live previous deployment can continue
World Boss / Shipyard writes while an index is built.

SQLite is intentionally a no-op.
"""

from __future__ import annotations

from typing import Any


HOTPATH_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "world_boss_events",
        "idx_world_boss_events_status_window_id",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_world_boss_events_status_window_id "
        "ON world_boss_events(status, ends_at, starts_at, id);",
    ),
    (
        "world_boss_events",
        "idx_world_boss_events_status_updated",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_world_boss_events_status_updated "
        "ON world_boss_events(status, updated_at DESC);",
    ),
    (
        "shipyard_queue",
        "idx_shipyard_queue_planet_status_pos_id",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_shipyard_queue_planet_status_pos_id "
        "ON shipyard_queue(planet_id, status, queue_position, id);",
    ),
    (
        "shipyard_queue",
        "idx_shipyard_queue_status_finish_planet",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_shipyard_queue_status_finish_planet "
        "ON shipyard_queue(status, finish_at, planet_id);",
    ),
)


def _table_exists(conn: Any, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name = ? LIMIT 1;",
        (str(table_name),),
    ).fetchone()
    return row is not None


def ensure_hotpath_indexes() -> int:
    from game.config import init_config
    from game.db import get_db_backend

    init_config()
    if get_db_backend() != "postgres":
        print("[GC] PostgreSQL hotpath indexes: skipped (non-postgres backend).")
        return 0

    from game.db_pg import connect_postgres_migration

    conn = connect_postgres_migration()
    created_or_present = 0
    try:
        for table_name, index_name, sql in HOTPATH_INDEXES:
            if not _table_exists(conn, table_name):
                print(f"[GC] PostgreSQL hotpath index {index_name}: table {table_name} absent; skip.")
                continue
            try:
                conn.execute(sql)
                created_or_present += 1
                print(f"[GC] PostgreSQL hotpath index ready: {index_name}")
            except Exception as exc:
                # Performance indexes must never turn an otherwise healthy deploy
                # into an outage. Autocommit keeps a failed statement isolated.
                print(f"[GC] WARNING: hotpath index {index_name} skipped: {exc}")
        return created_or_present
    finally:
        conn.close()


if __name__ == "__main__":
    ensure_hotpath_indexes()
