"""
Galaxy coordinate engine — single source of truth for universe positions.

Universe layout (v1):
  Galaxy:    1
  Systems:   1–499
  Positions: 1–15 per system (7485 slots total)
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from .db import db, table_exists, column_exists

GALAXY_MIN = 1
GALAXY_MAX = 1
SYSTEM_MIN = 1
SYSTEM_MAX = 499
POSITION_MIN = 1
POSITION_MAX = 15


class GalaxyCoordinateError(ValueError):
    """Invalid or unavailable galaxy coordinates."""


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        if raw is None or raw == "":
            return int(default)
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def validate_coordinates(galaxy: int, system: int, position: int) -> None:
    g, s, p = int(galaxy), int(system), int(position)
    if g < GALAXY_MIN or g > GALAXY_MAX:
        raise GalaxyCoordinateError(f"galaxy out of range: {g}")
    if s < SYSTEM_MIN or s > SYSTEM_MAX:
        raise GalaxyCoordinateError(f"system out of range: {s}")
    if p < POSITION_MIN or p > POSITION_MAX:
        raise GalaxyCoordinateError(f"position out of range: {p}")


def format_coordinates(galaxy: int, system: int, position: int) -> str:
    validate_coordinates(galaxy, system, position)
    return f"[{int(galaxy)}:{int(system)}:{int(position)}]"


def get_planet_coordinates(planet: Dict[str, Any]) -> Dict[str, Any]:
    """Return coordinate dict for a planet row; raises if incomplete."""
    galaxy = _safe_int(planet.get("galaxy"), 0)
    system = planet.get("system")
    position = planet.get("position")
    if galaxy < GALAXY_MIN:
        raise GalaxyCoordinateError("planet missing galaxy")
    if system is None or system == "":
        raise GalaxyCoordinateError("planet missing system")
    if position is None or position == "":
        raise GalaxyCoordinateError("planet missing position")
    system_i = int(system)
    position_i = int(position)
    validate_coordinates(galaxy, system_i, position_i)
    return {
        "galaxy": galaxy,
        "system": system_i,
        "position": position_i,
        "formatted": format_coordinates(galaxy, system_i, position_i),
    }


def _coords_schema_ready(conn: sqlite3.Connection) -> bool:
    return (
        table_exists(conn, "planets")
        and column_exists(conn, "planets", "galaxy")
        and column_exists(conn, "planets", "system")
        and column_exists(conn, "planets", "position")
    )


def _load_occupied(
    conn: sqlite3.Connection,
    *,
    exclude_planet_id: Optional[int] = None,
) -> Set[Tuple[int, int, int]]:
    if not _coords_schema_ready(conn):
        return set()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT galaxy, system, position
        FROM planets
        WHERE system IS NOT NULL
          AND position IS NOT NULL
          AND galaxy IS NOT NULL;
        """
    )
    occupied: Set[Tuple[int, int, int]] = set()
    for row in cur.fetchall():
        g = _safe_int(row["galaxy"], 0)
        s = row["system"]
        p = row["position"]
        if s is None or p is None:
            continue
        occupied.add((g, int(s), int(p)))
    if exclude_planet_id is not None:
        cur.execute(
            """
            SELECT galaxy, system, position
            FROM planets
            WHERE id = ? LIMIT 1;
            """,
            (int(exclude_planet_id),),
        )
        own = cur.fetchone()
        if own and own["system"] is not None and own["position"] is not None:
            occupied.discard(
                (
                    _safe_int(own["galaxy"], 1),
                    int(own["system"]),
                    int(own["position"]),
                )
            )
    return occupied


def coordinate_is_available(
    conn: sqlite3.Connection,
    galaxy: int,
    system: int,
    position: int,
    *,
    exclude_planet_id: Optional[int] = None,
) -> bool:
    validate_coordinates(galaxy, system, position)
    key = (int(galaxy), int(system), int(position))
    return key not in _load_occupied(conn, exclude_planet_id=exclude_planet_id)


def assert_coordinate_available(
    conn: sqlite3.Connection,
    galaxy: int,
    system: int,
    position: int,
    *,
    exclude_planet_id: Optional[int] = None,
) -> None:
    if not coordinate_is_available(
        conn, galaxy, system, position, exclude_planet_id=exclude_planet_id
    ):
        raise GalaxyCoordinateError(
            f"coordinate occupied: {format_coordinates(galaxy, system, position)}"
        )


def assign_free_coordinates(
    conn: sqlite3.Connection,
    *,
    galaxy: int = GALAXY_MIN,
    exclude_planet_id: Optional[int] = None,
) -> Tuple[int, int, int]:
    """
    Find the next free slot in scan order (system asc, position asc).
    Must be called inside a write transaction when assigning to avoid races.
    """
    g = int(galaxy)
    if g < GALAXY_MIN or g > GALAXY_MAX:
        raise GalaxyCoordinateError(f"galaxy out of range: {g}")

    occupied = _load_occupied(conn, exclude_planet_id=exclude_planet_id)
    for system in range(SYSTEM_MIN, SYSTEM_MAX + 1):
        for position in range(POSITION_MIN, POSITION_MAX + 1):
            key = (g, system, position)
            if key not in occupied:
                return key
    raise GalaxyCoordinateError("no free galaxy coordinates remaining")


def repair_missing_coordinates(conn: Optional[sqlite3.Connection] = None) -> int:
    """
    Assign coordinates to planets missing them; resolve duplicate slots.
    Idempotent — safe to run repeatedly.
    Returns number of planets updated.
    """
    own = conn is None
    if own:
        conn = db()
    assert conn is not None

    if not _coords_schema_ready(conn):
        if own:
            conn.close()
        return 0

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, galaxy, system, position
        FROM planets
        ORDER BY id ASC;
        """
    )
    rows = [dict(r) for r in cur.fetchall()]

    seen: Set[Tuple[int, int, int]] = set()
    needs_fix: List[int] = []

    for row in rows:
        pid = int(row["id"])
        galaxy = _safe_int(row.get("galaxy"), GALAXY_MIN)
        system = row.get("system")
        position = row.get("position")
        invalid = (
            system is None
            or system == ""
            or position is None
            or position == ""
        )
        if invalid:
            needs_fix.append(pid)
            continue
        try:
            validate_coordinates(galaxy, int(system), int(position))
        except GalaxyCoordinateError:
            needs_fix.append(pid)
            continue
        key = (galaxy, int(system), int(position))
        if key in seen:
            needs_fix.append(pid)
        else:
            seen.add(key)

    updated = 0
    for pid in needs_fix:
        g, s, p = assign_free_coordinates(conn, galaxy=GALAXY_MIN, exclude_planet_id=pid)
        assert_coordinate_available(conn, g, s, p, exclude_planet_id=pid)
        cur.execute(
            "UPDATE planets SET galaxy = ?, system = ?, position = ? WHERE id = ?;",
            (g, s, p, pid),
        )
        seen.add((g, s, p))
        updated += 1

    if own:
        conn.commit()
        conn.close()
    return updated


def list_system(
    galaxy: int,
    system: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Return exactly 15 slot entries for the given system (positions 1–15).
    Single query for occupied planets in that system.
    """
    validate_coordinates(galaxy, system, POSITION_MIN)

    own = conn is None
    if own:
        conn = db()

    by_position: Dict[int, Dict[str, Any]] = {}
    if _coords_schema_ready(conn):
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                p.id AS planet_id,
                p.name AS planet_name,
                p.galaxy,
                p.system,
                p.position,
                p.player_id,
                pl.name AS commander_name
            FROM planets p
            INNER JOIN players pl ON pl.id = p.player_id
            WHERE p.galaxy = ?
              AND p.system = ?
              AND p.position IS NOT NULL;
            """,
            (int(galaxy), int(system)),
        )
        for row in cur.fetchall():
            pos = int(row["position"])
            if pos < POSITION_MIN or pos > POSITION_MAX:
                continue
            coords = get_planet_coordinates(dict(row))
            by_position[pos] = {
                "position": pos,
                "occupied": True,
                "player_id": int(row["player_id"]),
                "commander_name": str(row["commander_name"] or ""),
                "planet_id": int(row["planet_id"]),
                "planet_name": str(row["planet_name"] or ""),
                "coordinates": {
                    "galaxy": coords["galaxy"],
                    "system": coords["system"],
                    "position": coords["position"],
                },
                "coordinates_formatted": coords["formatted"],
            }

    slots: List[Dict[str, Any]] = []
    for pos in range(POSITION_MIN, POSITION_MAX + 1):
        if pos in by_position:
            slots.append(by_position[pos])
        else:
            slots.append(
                {
                    "position": pos,
                    "occupied": False,
                    "player_id": None,
                    "commander_name": None,
                    "planet_id": None,
                    "planet_name": None,
                    "coordinates": {
                        "galaxy": int(galaxy),
                        "system": int(system),
                        "position": pos,
                    },
                    "coordinates_formatted": format_coordinates(galaxy, system, pos),
                }
            )

    result = {
        "galaxy": int(galaxy),
        "system": int(system),
        "slots": slots,
        "slot_count": POSITION_MAX,
    }

    if own:
        conn.close()
    return result
