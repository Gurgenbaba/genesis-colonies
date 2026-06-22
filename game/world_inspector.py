"""
World Inspector read helpers — debris visibility for Command Map (GC-700D-B).

Read-only layer over ``debris_fields``; no fleet/combat mutations.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlencode

from game.combat import DEBRIS_FIELD_TTL_SECONDS


def format_debris_ttl_display(remaining_seconds: int) -> str:
    """Compact remaining-time label for UI tooltips and inspector rows."""
    seconds = max(0, int(remaining_seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def debris_remaining_seconds(
    updated_at: Optional[float],
    *,
    now: Optional[float] = None,
) -> int:
    if updated_at is None:
        return int(DEBRIS_FIELD_TTL_SECONDS)
    now_ts = float(now if now is not None else time.time())
    expires_at = float(updated_at) + float(DEBRIS_FIELD_TTL_SECONDS)
    return max(0, int(expires_at - now_ts))


def fleet_recycle_href(galaxy: int, system: int, position: int) -> str:
    query = urlencode(
        {
            "mission": "recycle",
            "target_galaxy": int(galaxy),
            "target_system": int(system),
            "target_position": int(position),
        }
    )
    return f"/fleet?{query}"


def build_debris_field_payload(
    metal: int,
    crystal: int,
    *,
    updated_at: Optional[float] = None,
    now: Optional[float] = None,
    galaxy: int = 0,
    system: int = 0,
    position: int = 0,
) -> Optional[Dict[str, Any]]:
    m = max(0, int(metal))
    c = max(0, int(crystal))
    if m <= 0 and c <= 0:
        return None

    ttl_remaining = debris_remaining_seconds(updated_at, now=now)
    payload: Dict[str, Any] = {
        "metal": m,
        "crystal": c,
        "total": m + c,
        "ttl_seconds": int(DEBRIS_FIELD_TTL_SECONDS),
        "ttl_remaining_seconds": ttl_remaining,
        "ttl_display": format_debris_ttl_display(ttl_remaining),
        "has_debris": True,
    }
    if updated_at is not None:
        payload["updated_at"] = float(updated_at)
        payload["ttl_expires_at"] = float(updated_at) + float(DEBRIS_FIELD_TTL_SECONDS)

    g, s, p = int(galaxy), int(system), int(position)
    if g > 0 and s > 0 and p > 0:
        payload["coordinates"] = {"galaxy": g, "system": s, "position": p}
        payload["recycle_href"] = fleet_recycle_href(g, s, p)

    return payload


def get_debris_field_payload(
    galaxy: int,
    system: int,
    position: int,
    conn: sqlite3.Connection,
    *,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    from game.combat import debris_schema_ready

    if not debris_schema_ready(conn):
        return None

    cur = conn.cursor()
    cur.execute(
        """
        SELECT metal, crystal, updated_at
        FROM debris_fields
        WHERE galaxy = ? AND system = ? AND position = ?
        LIMIT 1;
        """,
        (int(galaxy), int(system), int(position)),
    )
    row = cur.fetchone()
    if not row:
        return None

    updated_at = float(row["updated_at"]) if row["updated_at"] is not None else None
    return build_debris_field_payload(
        int(row["metal"] or 0),
        int(row["crystal"] or 0),
        updated_at=updated_at,
        now=now,
        galaxy=int(galaxy),
        system=int(system),
        position=int(position),
    )


def debris_payload_for_planet(
    planet_id: int,
    conn: sqlite3.Connection,
    *,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    from game.galaxy import GalaxyCoordinateError, get_planet_coordinates
    from game.planet_evolution.repository import get_planet_row

    row = get_planet_row(int(planet_id), conn=conn)
    if not row:
        return None
    try:
        coords = get_planet_coordinates(row)
    except GalaxyCoordinateError:
        return None
    return get_debris_field_payload(
        int(coords["galaxy"]),
        int(coords["system"]),
        int(coords["position"]),
        conn,
        now=now,
    )


def build_debris_recycle_mission_action(
    debris: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    if not debris or not debris.get("has_debris"):
        return None
    href = str(debris.get("recycle_href") or "").strip()
    if not href:
        return None
    return {
        "action_key": "recycle",
        "mission": "recycle",
        "label_key": "combat_report_send_recycler",
        "enabled": True,
        "blocked_reason_key": "",
        "href": href,
    }


def attach_debris_to_inspector_payload(
    payload: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
    planet_id: int = 0,
    galaxy: int = 0,
    system: int = 0,
    position: int = 0,
    now: Optional[float] = None,
) -> None:
    """Mutates Command Center / inspector payload with debris block when present."""
    debris: Optional[Dict[str, Any]] = None
    pid = int(planet_id or 0)
    if pid:
        debris = debris_payload_for_planet(pid, conn, now=now)
    elif int(galaxy) > 0 and int(system) > 0 and int(position) > 0:
        debris = get_debris_field_payload(
            int(galaxy),
            int(system),
            int(position),
            conn,
            now=now,
        )

    if not debris:
        return

    payload["debris"] = debris
    recycle = build_debris_recycle_mission_action(debris)
    if not recycle:
        return

    actions = list(payload.get("mission_actions") or [])
    if any(str(row.get("action_key") or "") == "recycle" for row in actions):
        payload["mission_actions"] = actions
        return
    actions.append(recycle)
    payload["mission_actions"] = actions
