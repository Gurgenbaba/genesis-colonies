"""Galaxy Heat counter (EPIC-21 / GC-P01–P02)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ..db import table_exists
from .log import log_pirate_action

logger = logging.getLogger(__name__)

HEAT_TABLE = "galaxy_heat"
HEAT_MAX = 1000

# kind -> heat delta (defaults; balance later)
HEAT_EVENT_AMOUNTS: Dict[str, int] = {
    "combat": 8,
    "expedition": 3,
    "asteroid": 4,
    "world_boss": 12,
    "colonize": 6,
    "pirate_base_spawn": 0,
    "pirate_base_destroyed": -15,
    "raid": 5,
}

HEAT_THRESHOLDS: Dict[str, int] = {
    "patrol": 150,
    "raids": 300,
    "elite": 500,
    "crisis": 700,
    "war": 1000,
}

_KIND_COUNTER = {
    "combat": "combat_events",
    "expedition": "expo_events",
    "asteroid": "asteroid_events",
    "world_boss": "boss_events",
    "colonize": "colonize_events",
}


def _now() -> float:
    return time.time()


def schema_ready(conn) -> bool:
    return table_exists(conn, HEAT_TABLE)


def heat_band(heat: int) -> str:
    h = max(0, min(HEAT_MAX, int(heat)))
    if h >= HEAT_THRESHOLDS["war"]:
        return "war"
    if h >= HEAT_THRESHOLDS["crisis"]:
        return "crisis"
    if h >= HEAT_THRESHOLDS["elite"]:
        return "elite"
    if h >= HEAT_THRESHOLDS["raids"]:
        return "raids"
    if h >= HEAT_THRESHOLDS["patrol"]:
        return "patrol"
    return "calm"


def get_galaxy_heat(conn, galaxy_id: int) -> Dict[str, Any]:
    gid = int(galaxy_id)
    if not schema_ready(conn):
        return {
            "galaxy_id": gid,
            "heat": 0,
            "band": "calm",
            "thresholds": dict(HEAT_THRESHOLDS),
            "updated_at": None,
        }
    cur = conn.execute(
        """
        SELECT galaxy_id, heat, combat_events, expo_events, asteroid_events,
               boss_events, colonize_events, updated_at
        FROM galaxy_heat WHERE galaxy_id = ? LIMIT 1;
        """,
        (gid,),
    )
    row = cur.fetchone()
    if not row:
        return {
            "galaxy_id": gid,
            "heat": 0,
            "band": "calm",
            "thresholds": dict(HEAT_THRESHOLDS),
            "updated_at": None,
            "counters": {
                "combat": 0,
                "expedition": 0,
                "asteroid": 0,
                "world_boss": 0,
                "colonize": 0,
            },
        }
    heat = int(row["heat"] or 0)
    return {
        "galaxy_id": gid,
        "heat": heat,
        "band": heat_band(heat),
        "thresholds": dict(HEAT_THRESHOLDS),
        "updated_at": float(row["updated_at"]) if row["updated_at"] is not None else None,
        "counters": {
            "combat": int(row["combat_events"] or 0),
            "expedition": int(row["expo_events"] or 0),
            "asteroid": int(row["asteroid_events"] or 0),
            "world_boss": int(row["boss_events"] or 0),
            "colonize": int(row["colonize_events"] or 0),
        },
    }


def record_heat_event(
    conn,
    galaxy_id: int,
    kind: str,
    amount: Optional[int] = None,
    *,
    log: bool = True,
) -> Dict[str, Any]:
    """Apply a heat delta for ``galaxy_id``. Returns updated heat snapshot."""
    gid = int(galaxy_id)
    if not schema_ready(conn):
        return get_galaxy_heat(conn, gid)

    delta = int(amount) if amount is not None else int(HEAT_EVENT_AMOUNTS.get(kind, 1))
    before = get_galaxy_heat(conn, gid)
    old_heat = int(before["heat"])
    new_heat = max(0, min(HEAT_MAX, old_heat + delta))
    counter_col = _KIND_COUNTER.get(kind)
    now = _now()

    if before.get("updated_at") is None and old_heat == 0:
        # Ensure row exists (first event for this galaxy).
        conn.execute(
            """
            INSERT INTO galaxy_heat (galaxy_id, heat, updated_at)
            VALUES (?, 0, ?)
            ON CONFLICT(galaxy_id) DO NOTHING;
            """,
            (gid, now),
        )

    if counter_col and delta > 0:
        conn.execute(
            f"""
            UPDATE galaxy_heat
            SET heat = ?, {counter_col} = {counter_col} + 1, updated_at = ?
            WHERE galaxy_id = ?;
            """,
            (new_heat, now, gid),
        )
    else:
        conn.execute(
            """
            UPDATE galaxy_heat SET heat = ?, updated_at = ? WHERE galaxy_id = ?;
            """,
            (new_heat, now, gid),
        )

    after = get_galaxy_heat(conn, gid)
    if log and (delta != 0 or old_heat != new_heat):
        old_band = heat_band(old_heat)
        new_band = after["band"]
        log_pirate_action(
            conn,
            kind="heat_event",
            galaxy_id=gid,
            message=f"heat {old_heat}->{new_heat} ({kind} {delta:+d})",
            payload={
                "kind": kind,
                "delta": delta,
                "old_heat": old_heat,
                "new_heat": new_heat,
                "old_band": old_band,
                "new_band": new_band,
                "band_changed": old_band != new_band,
            },
            severity="info" if old_band == new_band else "warn",
        )
    return after
