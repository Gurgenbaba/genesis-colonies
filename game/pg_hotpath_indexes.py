"""Small PostgreSQL-only index ensure for live hot paths.

GC-PG-HIGHSPEED-001D: these indexes are additive and idempotent.  They live
outside the numbered migration stream because a few historical migration
fixtures intentionally exercise partial schemas; startup can safely inspect the
actual production schema before creating an index.
"""

from __future__ import annotations

import logging

from .db import commit, db, get_db_backend, rollback, table_exists

logger = logging.getLogger(__name__)


HOTPATH_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "world_boss_events",
        "idx_world_boss_events_status_window_id",
        "CREATE INDEX IF NOT EXISTS idx_world_boss_events_status_window_id "
        "ON world_boss_events(status, ends_at, starts_at, id);",
    ),
    (
        "world_boss_events",
        "idx_world_boss_events_status_updated",
        "CREATE INDEX IF NOT EXISTS idx_world_boss_events_status_updated "
        "ON world_boss_events(status, updated_at DESC);",
    ),
    (
        "shipyard_queue",
        "idx_shipyard_queue_planet_status_pos_id",
        "CREATE INDEX IF NOT EXISTS idx_shipyard_queue_planet_status_pos_id "
        "ON shipyard_queue(planet_id, status, queue_position, id);",
    ),
    (
        "shipyard_queue",
        "idx_shipyard_queue_status_finish_planet",
        "CREATE INDEX IF NOT EXISTS idx_shipyard_queue_status_finish_planet "
        "ON shipyard_queue(status, finish_at, planet_id);",
    ),
)


def ensure_postgres_hotpath_indexes(*, conn=None) -> int:
    """Create missing additive indexes and return how many DDLs were attempted.

    The helper never owns or changes pool sizing/timeouts.  When a connection is
    supplied, its transaction ownership remains with the caller.  Startup uses
    the no-argument form, so this helper owns that short transaction.
    """
    if get_db_backend() != "postgres":
        return 0

    own_conn = conn is None
    if own_conn:
        conn = db()

    attempted = 0
    try:
        for table_name, _index_name, sql in HOTPATH_INDEXES:
            if not table_exists(conn, table_name):
                continue
            conn.execute(sql)
            attempted += 1
        if own_conn:
            commit(conn)
        return attempted
    except Exception:
        if own_conn:
            try:
                rollback(conn)
            except Exception:
                pass
        raise
    finally:
        if own_conn and conn is not None:
            conn.close()
