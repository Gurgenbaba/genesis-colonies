"""
Core schema validation for Genesis Colonies (SQLite).

Validates expected primary keys and queue/ranking columns at bootstrap.
Does not mutate the database.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from .db import column_exists, db, table_exists

logger = logging.getLogger(__name__)

# (table, required_columns, optional_columns)
_CORE_TABLE_SPECS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("players", ("id",), ()),
    ("planets", ("id", "player_id"), ()),
    ("build_queue", ("id", "planet_id", "building_type", "finish_time"), ()),
    ("research_queue", ("id", "user_id", "tech_key", "finish_at"), ()),
    (
        "player_scores",
        ("player_id", "score_total", "score_buildings", "score_research"),
        ("score_fleet", "score_defense", "rank_total", "rank_building", "rank_research"),
    ),
)

# Legacy/redundant columns — warn only (not fatal).
_LEGACY_DRIFT_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("planets", "planet_id", "use planets.id (alias AS planet_id in SQL)"),
    ("players", "player_id", "players use id; ownership is planets.player_id"),
)


def _missing_columns(conn, table: str, required: Tuple[str, ...]) -> List[str]:
    missing: List[str] = []
    for col in required:
        if not column_exists(conn, table, col):
            missing.append(f"{table}.{col}")
    return missing


def validate_core_schema(*, strict: bool = False) -> List[str]:
    """
    Verify core tables/columns. Returns human-readable issue strings.
    Logs warnings; raises RuntimeError if strict=True and issues exist.
    """
    issues: List[str] = []
    conn = db()
    try:
        for table, required, optional in _CORE_TABLE_SPECS:
            if not table_exists(conn, table):
                issues.append(f"missing table: {table}")
                continue
            issues.extend(_missing_columns(conn, table, required))
            for col in optional:
                if not column_exists(conn, table, col):
                    logger.debug("[schema] optional column absent: %s.%s", table, col)

        for table, col, hint in _LEGACY_DRIFT_COLUMNS:
            if table_exists(conn, table) and column_exists(conn, table, col):
                logger.warning(
                    "[schema] legacy drift: %s.%s present — %s",
                    table,
                    col,
                    hint,
                )
    finally:
        conn.close()

    for msg in issues:
        logger.warning("[schema] %s", msg)

    if strict and issues:
        raise RuntimeError("Core schema validation failed: " + "; ".join(issues))

    return issues
