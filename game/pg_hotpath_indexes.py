"""Optional PostgreSQL hot-path indexes for live production traffic.

This module is intentionally *not* imported by application bootstrap. The
container entrypoint invokes it once, after numbered migrations and before the
new Gunicorn process starts. PostgreSQL index creation is CONCURRENTLY on a
direct autocommit connection so the previous deployment can keep serving
World Boss / Orbital Shipyard writes.

The entire helper is fail-open: these are performance indexes, never a reason
to make the game unavailable. SQLite is a no-op.
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
        "world_boss_contributions",
        "idx_world_boss_contrib_auto_enabled_player_event",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_world_boss_contrib_auto_enabled_player_event "
        "ON world_boss_contributions(player_id, event_id) "
        "WHERE auto_attack_enabled = 1;",
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
    (
        "player_messages",
        "idx_player_messages_combat_cursor",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_player_messages_combat_cursor "
        "ON player_messages(category, id);",
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
    """Best-effort one-shot ensure; never tune app pool or gameplay locks."""
    try:
        from game.config import init_config
        from game.db import get_db_backend

        init_config()
        if get_db_backend() != "postgres":
            print("[GC] PostgreSQL hotpath indexes: skipped (non-postgres backend).")
            return 0

        from game.db_pg import connect_postgres_migration

        try:
            conn = connect_postgres_migration()
        except Exception as exc:
            print(f"[GC] WARNING: hotpath index connection unavailable; skip: {exc}")
            return 0

        ready = 0
        try:
            # Optional DDL must never stall a deployment indefinitely. These are
            # lower, one-shot limits on this direct connection only; application
            # pool/lock settings remain untouched.
            try:
                conn.execute("SET statement_timeout = '15000ms';")
                conn.execute("SET lock_timeout = '1000ms';")
            except Exception as exc:
                print(f"[GC] WARNING: hotpath index session limits unavailable: {exc}")

            for table_name, index_name, sql in HOTPATH_INDEXES:
                try:
                    if not _table_exists(conn, table_name):
                        print(
                            f"[GC] PostgreSQL hotpath index {index_name}: "
                            f"table {table_name} absent; skip."
                        )
                        continue
                    conn.execute(sql)
                    ready += 1
                    print(f"[GC] PostgreSQL hotpath index ready: {index_name}")
                except Exception as exc:
                    # Autocommit means one failed CONCURRENTLY statement cannot
                    # poison the next optional index attempt.
                    print(f"[GC] WARNING: hotpath index {index_name} skipped: {exc}")
            return ready
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        # Absolute fail-open boundary: optional index setup must never turn a
        # healthy application revision into another production outage.
        print(f"[GC] WARNING: PostgreSQL hotpath index ensure failed open: {exc}")
        return 0


def main() -> int:
    ensure_hotpath_indexes()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
