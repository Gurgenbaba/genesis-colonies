"""World location progression for strategic expedition sites (GC-583D)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..db import table_exists
from .world_colonization import (
    EXPEDITION_WORLD_TYPES,
    WorldKeyError,
    is_expedition_world_type,
    parse_world_key,
)

PROGRESS_MILESTONE_THRESHOLDS: Tuple[int, ...] = (1, 5, 10)

FAMILIARITY_TIERS: Tuple[Tuple[int, str, str], ...] = (
    (10, "outpost_prepared", "world_familiarity_outpost_prepared"),
    (5, "stabilized", "world_familiarity_stabilized"),
    (1, "mapped", "world_familiarity_mapped"),
    (0, "unknown", "world_familiarity_unknown"),
)


def world_progress_schema_ready(*, conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "world_progress")


def default_progress_payload() -> Dict[str, Any]:
    status, label_key = familiarity_from_count(0)
    return {
        "expedition_count": 0,
        "familiarity_status": status,
        "familiarity_label_key": label_key,
        "next_milestone": next_milestone_from_count(0),
    }


def familiarity_from_count(count: int) -> Tuple[str, str]:
    total = max(0, int(count))
    for threshold, status, label_key in FAMILIARITY_TIERS:
        if total >= threshold:
            return status, label_key
    return "unknown", "world_familiarity_unknown"


def next_milestone_from_count(count: int) -> Optional[int]:
    total = max(0, int(count))
    for threshold in PROGRESS_MILESTONE_THRESHOLDS:
        if total < threshold:
            return threshold
    return None


def build_progress_payload(expedition_count: int) -> Dict[str, Any]:
    total = max(0, int(expedition_count))
    status, label_key = familiarity_from_count(total)
    return {
        "expedition_count": total,
        "familiarity_status": status,
        "familiarity_label_key": label_key,
        "next_milestone": next_milestone_from_count(total),
    }


def get_world_progress_row(
    player_id: int,
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    if not world_progress_schema_ready(conn=conn):
        return None
    row = conn.execute(
        """
        SELECT player_id, world_key, expedition_count, last_expedition_at
        FROM world_progress
        WHERE player_id = ? AND world_key = ?;
        """,
        (int(player_id), str(world_key)),
    ).fetchone()
    return dict(row) if row else None


def build_world_progress_map(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Dict[str, Any]]:
    """Map world_key → progression payload for expedition world fields."""
    if not world_progress_schema_ready(conn=conn):
        return {}
    rows = conn.execute(
        """
        SELECT world_key, expedition_count
        FROM world_progress
        WHERE player_id = ?;
        """,
        (int(player_id),),
    ).fetchall()
    return {
        str(row["world_key"]): build_progress_payload(int(row["expedition_count"] or 0))
        for row in rows
    }


def attach_world_location_progress(
    nodes: List[Dict[str, Any]],
    progress_map: Mapping[str, Mapping[str, Any]],
) -> None:
    """Annotate expedition world_field nodes with familiarity progress (GC-583D)."""
    default = default_progress_payload()
    for node in nodes:
        if str(node.get("node_kind") or "") != "world_field":
            continue
        if not node.get("is_expedition"):
            continue
        wk = str(node.get("world_key") or "").strip()
        block = dict(progress_map.get(wk) or default)
        node.update(block)


def record_world_expedition_progress(
    player_id: int,
    world_key: str,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Increment expedition progress after a completed world-key expedition (583D)."""
    if not world_progress_schema_ready(conn=conn):
        return None
    wk = str(world_key or "").strip()
    if not wk:
        return None
    try:
        parsed = parse_world_key(wk)
    except WorldKeyError:
        return None
    if not is_expedition_world_type(parsed["world_type"]):
        return None

    ts = float(now if now is not None else time.time())
    conn.execute(
        """
        INSERT INTO world_progress (player_id, world_key, expedition_count, last_expedition_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(player_id, world_key) DO UPDATE SET
            expedition_count = expedition_count + 1,
            last_expedition_at = excluded.last_expedition_at;
        """,
        (int(player_id), wk, ts),
    )
    row = get_world_progress_row(int(player_id), wk, conn=conn)
    if not row:
        return build_progress_payload(1)
    return build_progress_payload(int(row["expedition_count"] or 0))


def progress_eligible_world_types() -> Tuple[str, ...]:
    return EXPEDITION_WORLD_TYPES
