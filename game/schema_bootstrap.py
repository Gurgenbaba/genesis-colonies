"""
GC-PERF-PG-SCHEMA-001 — core schema bootstrap before numbered migrations.

SQLite historically creates users/players/planets/… via ``models.init_db()`` before
``migrate.py`` runs (migrations start at 006). Empty Postgres has no such tables.

This module applies the same CREATE TABLE IF NOT EXISTS core (rewritten for PG)
without running default-admin seeding (that stays in init_db / first app bootstrap).
"""

from __future__ import annotations

import logging
from typing import Any, List

logger = logging.getLogger(__name__)

# Minimal core matching models.init_db CREATE TABLE blocks (pre-migration baseline).
_CORE_DDL: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        email TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        banned_until INTEGER DEFAULT NULL,
        last_seen INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(id) REFERENCES users(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS planets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        is_homeworld INTEGER NOT NULL DEFAULT 0,
        metal REAL NOT NULL DEFAULT 0 CHECK(metal >= 0),
        crystal REAL NOT NULL DEFAULT 0 CHECK(crystal >= 0),
        fuel_cells REAL NOT NULL DEFAULT 500 CHECK(fuel_cells >= 0),
        last_update REAL NOT NULL,
        energy_total INTEGER NOT NULL DEFAULT 0,
        energy_used INTEGER NOT NULL DEFAULT 0,
        galaxy INTEGER NOT NULL DEFAULT 1,
        system INTEGER,
        position INTEGER,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS planet_buildings (
        planet_id INTEGER PRIMARY KEY,
        metal_mine INTEGER DEFAULT 0 CHECK(metal_mine >= 0),
        crystal_mine INTEGER DEFAULT 0 CHECK(crystal_mine >= 0),
        solar_plant INTEGER DEFAULT 0 CHECK(solar_plant >= 0),
        research_lab INTEGER DEFAULT 0 CHECK(research_lab >= 0),
        academy INTEGER DEFAULT 0 CHECK(academy >= 0),
        metal_storage INTEGER DEFAULT 0 CHECK(metal_storage >= 0),
        crystal_storage INTEGER DEFAULT 0 CHECK(crystal_storage >= 0),
        command_center INTEGER DEFAULT 0 CHECK(command_center >= 0),
        shipyard INTEGER DEFAULT 0 CHECK(shipyard >= 0),
        fuel_cell_plant INTEGER DEFAULT 0 CHECK(fuel_cell_plant >= 0),
        defense_factory INTEGER DEFAULT 0 CHECK(defense_factory >= 0),
        barracks INTEGER DEFAULT 0 CHECK(barracks >= 0),
        radar_array INTEGER DEFAULT 0 CHECK(radar_array >= 0),
        shield_generator INTEGER DEFAULT 0 CHECK(shield_generator >= 0),
        terraformer INTEGER DEFAULT 0 CHECK(terraformer >= 0),
        nanofactory INTEGER DEFAULT 0 CHECK(nanofactory >= 0),
        geothermal_nexus INTEGER DEFAULT 0 CHECK(geothermal_nexus >= 0),
        planet_core_nexus INTEGER DEFAULT 0 CHECK(planet_core_nexus >= 0),
        FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS build_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        planet_id INTEGER NOT NULL,
        building_type TEXT NOT NULL,
        start_time REAL NOT NULL,
        finish_time REAL NOT NULL,
        FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS research_levels (
        user_id INTEGER NOT NULL,
        tech_key TEXT NOT NULL,
        level INTEGER NOT NULL CHECK(level >= 0),
        PRIMARY KEY (user_id, tech_key),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS research_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        tech_key TEXT NOT NULL,
        finish_at REAL NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS action_idempotency (
        user_id INTEGER NOT NULL,
        request_id TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (user_id, request_id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS game_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS bans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        reason TEXT,
        banned_until INTEGER NOT NULL,
        created_at INTEGER NOT NULL,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS player_scores (
        player_id INTEGER PRIMARY KEY,
        score_total INTEGER NOT NULL DEFAULT 0,
        score_buildings INTEGER NOT NULL DEFAULT 0,
        score_research INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
    );
    """,
]


def core_schema_ready(conn: Any) -> bool:
    from game.db import table_exists

    return table_exists(conn, "players") and table_exists(conn, "planets") and table_exists(
        conn, "users"
    )


# Columns that store signed 64-bit values. SQLite INTEGER is i64; Postgres INTEGER is i32.
# Expanded GC-DB-POSTGRES-001 Phase 1 from production-copy overflow scan.
_POSTGRES_I64_COLUMNS: List[tuple[str, str]] = [
    ("planets", "dna_seed"),
    ("players", "banned_until"),
    ("bans", "banned_until"),
    ("build_queue", "cost_metal"),
    ("build_queue", "cost_crystal"),
    ("research_queue", "cost_metal"),
    ("research_queue", "cost_crystal"),
    ("shipyard_queue", "cost_metal"),
    ("shipyard_queue", "cost_crystal"),
    ("pirate_bot_state", "seed"),
    ("troop_queue", "cost_metal"),
    ("troop_queue", "cost_crystal"),
]

_INT32_MAX = 2147483647
_INT32_MIN = -2147483648


def scan_sqlite_int32_overflow_columns(sqlite_conn: Any) -> List[tuple[str, str, int, int]]:
    """Return (table, column, min, max) for INTEGER columns outside Postgres int4."""
    tables = [
        str(r[0])
        for r in sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY 1"
        )
    ]
    hits: List[tuple[str, str, int, int]] = []
    for table in tables:
        cols = sqlite_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
        for col in cols:
            name = str(col[1] if not hasattr(col, "keys") else col["name"])
            ctype = str(col[2] if not hasattr(col, "keys") else col["type"] or "").upper()
            if "INT" not in ctype and ctype not in ("", "NUMERIC"):
                # SQLite affinity: bare INTEGER / INT*; also scan untyped numeric storage
                continue
            if ctype and "INT" not in ctype and ctype != "NUMERIC":
                continue
            try:
                row = sqlite_conn.execute(
                    f'SELECT MAX("{name}"), MIN("{name}") FROM "{table}" '
                    f'WHERE typeof("{name}") = \'integer\''
                ).fetchone()
            except Exception:
                continue
            if not row or row[0] is None:
                continue
            mx, mn = int(row[0]), int(row[1])
            if mx > _INT32_MAX or mn < _INT32_MIN:
                hits.append((table, name, mn, mx))
    return hits


def ensure_postgres_i64_columns_from_sqlite(
    pg_conn: Any, sqlite_conn: Any
) -> List[str]:
    """
    Widen static i64 list plus any INTEGER columns that overflow int4 in the
    SQLite source (production-copy import rehearsal).
    """
    from game.db import get_db_backend

    if get_db_backend() != "postgres":
        return []
    discovered = {
        (t, c) for t, c, _mn, _mx in scan_sqlite_int32_overflow_columns(sqlite_conn)
    }
    # Temporarily extend the static list for this call.
    extra = sorted(discovered - set(_POSTGRES_I64_COLUMNS))
    if extra:
        _POSTGRES_I64_COLUMNS.extend(extra)
    try:
        return ensure_postgres_i64_columns(pg_conn)
    finally:
        # Keep discovered columns in the module list for subsequent init_db calls
        # in the same process (idempotent ALTER).
        pass


def ensure_postgres_i64_columns(conn: Any) -> List[str]:
    """
    Widen known 64-bit columns to BIGINT on Postgres (idempotent).

    Required because SQLite migrations declare INTEGER (64-bit there) and
    planet DNA seeds use the full signed 64-bit range.
    """
    from game.db import get_db_backend, table_exists

    if get_db_backend() != "postgres":
        return []
    widened: List[str] = []
    for table, column in _POSTGRES_I64_COLUMNS:
        if not table_exists(conn, table):
            continue
        row = conn.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ?
              AND column_name = ?
            LIMIT 1;
            """,
            (table, column),
        ).fetchone()
        if not row:
            continue
        data_type = str(row["data_type"] if isinstance(row, dict) else row[0]).lower()
        if data_type in ("bigint", "int8"):
            continue
        if data_type not in ("integer", "int", "int4", "smallint", "int2"):
            continue
        conn.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT;"
        )
        widened.append(f"{table}.{column}")
        logger.info("[schema_bootstrap] widened %s.%s to BIGINT", table, column)
    return widened


def bootstrap_core_schema(conn: Any) -> int:
    """
    Create core tables if missing. Returns number of statements executed.

    On Postgres, DDL is rewritten via sql_pg_rewrite. Idempotent on re-run.
    """
    from game.db import get_db_backend
    from game.sql_pg_rewrite import is_idempotent_postgres_error, rewrite_sqlite_statement

    if core_schema_ready(conn):
        return 0

    backend = get_db_backend()
    executed = 0
    for raw in _CORE_DDL:
        sql = raw.strip()
        if backend == "postgres":
            sql = rewrite_sqlite_statement(sql)
            if not sql:
                continue
        try:
            conn.execute(sql)
            executed += 1
        except Exception as exc:
            if backend == "postgres" and is_idempotent_postgres_error(exc):
                logger.debug("core schema skip idempotent: %s", exc)
                continue
            raise
    return executed
