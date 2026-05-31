"""
Galaxy coordinate engine — single source of truth for universe positions.

Universe layout (v1):
  Galaxy:    1
  Systems:   1–499
  Positions: 1–15 per system (7485 slots total)
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from .db import db, table_exists, column_exists

GALAXY_MIN = 1
SYSTEM_MIN = 1
SYSTEM_MAX = 499
POSITION_MIN = 1
POSITION_MAX = 15
EXPEDITION_SLOT_POSITION = 16
MINIMAP_RADIUS = 4

_COORD_QUERY_RE = re.compile(
    r"^\s*\[?\s*(\d+)\s*:\s*(\d+)\s*(?::\s*(\d+)\s*)?\]?\s*$"
)


class GalaxyCoordinateError(ValueError):
    """Invalid or unavailable galaxy coordinates."""


def get_galaxy_max(conn: Optional[sqlite3.Connection] = None) -> int:
    """Playable galaxies from game settings (admin: galaxy_count)."""
    own = conn is None
    if own:
        conn = db()
    try:
        from .models import get_game_settings

        settings = get_game_settings(conn=conn) if conn is not None else get_game_settings()
        raw = settings.get("galaxy_count", "1")
        return max(1, min(20, int(raw)))
    except Exception:
        return 1
    finally:
        if own and conn is not None:
            conn.close()


def get_universe_config(conn: Optional[sqlite3.Connection] = None) -> Dict[str, int]:
    galaxy_max = get_galaxy_max(conn)
    return {
        "galaxy_min": GALAXY_MIN,
        "galaxy_max": galaxy_max,
        "system_min": SYSTEM_MIN,
        "system_max": SYSTEM_MAX,
        "position_min": POSITION_MIN,
        "position_max": POSITION_MAX,
    }


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        if raw is None or raw == "":
            return int(default)
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def validate_coordinates(
    galaxy: int,
    system: int,
    position: int,
    *,
    galaxy_max: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    g, s, p = int(galaxy), int(system), int(position)
    gmax = int(galaxy_max if galaxy_max is not None else get_galaxy_max(conn))
    if g < GALAXY_MIN or g > gmax:
        raise GalaxyCoordinateError(f"galaxy out of range: {g}")
    if s < SYSTEM_MIN or s > SYSTEM_MAX:
        raise GalaxyCoordinateError(f"system out of range: {s}")
    if p == EXPEDITION_SLOT_POSITION:
        return
    if p < POSITION_MIN or p > POSITION_MAX:
        raise GalaxyCoordinateError(f"position out of range: {p}")


def clamp_galaxy(galaxy: int, *, conn: Optional[sqlite3.Connection] = None) -> int:
    gmax = get_galaxy_max(conn)
    return max(GALAXY_MIN, min(gmax, int(galaxy)))


def clamp_system(system: int) -> int:
    return max(SYSTEM_MIN, min(SYSTEM_MAX, int(system)))


def parse_coordinate_query(raw: str) -> Optional[Dict[str, int]]:
    """
    Parse [G:S:P], G:S:P, or G:S (position omitted → system jump only).
    """
    text = str(raw or "").strip()
    if not text:
        return None
    m = _COORD_QUERY_RE.match(text)
    if not m:
        return None
    galaxy = int(m.group(1))
    system = int(m.group(2))
    position = int(m.group(3)) if m.group(3) is not None else None
    out: Dict[str, int] = {"galaxy": galaxy, "system": system}
    if position is not None:
        out["position"] = position
    return out


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
    gmax = get_galaxy_max(conn)
    if g < GALAXY_MIN or g > gmax:
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


def _slot_planet_meta(
    planet_row: Dict[str, Any],
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    from .planet_evolution.dna import effective_planet_class
    from .overview_page import temperature_range_for_class
    from .planet_evolution.scoring import compute_single_planet_score
    from .planet_evolution.ux_copy import planet_class_label_key

    planet_class = effective_planet_class(planet_row)
    temp = temperature_range_for_class(planet_class)
    planet_id = int(planet_row.get("planet_id") or planet_row.get("id") or 0)
    score = compute_single_planet_score(planet_id, conn) if planet_id else 0
    return {
        "planet_class": planet_class,
        "planet_class_label_key": planet_class_label_key(planet_class),
        "temperature_display": temp["display"],
        "planet_score": int(score),
    }


def build_minimap_range(
    galaxy: int,
    center_system: int,
    *,
    viewer_player_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
    radius: int = MINIMAP_RADIUS,
) -> List[Dict[str, Any]]:
    """Systems around center_system with occupancy hints for range navigation."""
    galaxy = clamp_galaxy(galaxy, conn=conn)
    center = clamp_system(center_system)
    lo = max(SYSTEM_MIN, center - int(radius))
    hi = min(SYSTEM_MAX, center + int(radius))

    own = conn is None
    if own:
        conn = db()
    assert conn is not None

    counts: Dict[int, int] = {}
    own_systems: Set[int] = set()
    if _coords_schema_ready(conn):
        cur = conn.cursor()
        cur.execute(
            """
            SELECT system, COUNT(*) AS c
            FROM planets
            WHERE galaxy = ?
              AND system BETWEEN ? AND ?
              AND position IS NOT NULL
            GROUP BY system;
            """,
            (int(galaxy), lo, hi),
        )
        for row in cur.fetchall():
            counts[int(row["system"])] = int(row["c"])

        if viewer_player_id is not None:
            cur.execute(
                """
                SELECT DISTINCT system
                FROM planets
                WHERE galaxy = ?
                  AND system BETWEEN ? AND ?
                  AND player_id = ?
                  AND position IS NOT NULL;
                """,
                (int(galaxy), lo, hi, int(viewer_player_id)),
            )
            own_systems = {int(r["system"]) for r in cur.fetchall()}

    cells: List[Dict[str, Any]] = []
    for sys_num in range(lo, hi + 1):
        occupied = counts.get(sys_num, 0)
        cells.append(
            {
                "system": sys_num,
                "occupied_count": occupied,
                "has_occupancy": occupied > 0,
                "has_own_planet": sys_num in own_systems,
                "is_current": sys_num == center,
            }
        )

    if own:
        conn.close()
    return cells


def build_galaxy_nav(
    galaxy: int,
    system: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    cfg = get_universe_config(conn)
    gmax = cfg["galaxy_max"]
    galaxy = clamp_galaxy(galaxy, conn=conn)
    system = clamp_system(system)
    return {
        "galaxy": galaxy,
        "system": system,
        "galaxy_min": cfg["galaxy_min"],
        "galaxy_max": gmax,
        "system_min": cfg["system_min"],
        "system_max": cfg["system_max"],
        "prev_system": max(cfg["system_min"], system - 1),
        "next_system": min(cfg["system_max"], system + 1),
        "has_prev": system > cfg["system_min"],
        "has_next": system < cfg["system_max"],
        "prev_galaxy": max(cfg["galaxy_min"], galaxy - 1),
        "next_galaxy": min(gmax, galaxy + 1),
        "has_prev_galaxy": galaxy > cfg["galaxy_min"],
        "has_next_galaxy": galaxy < gmax,
        "multi_galaxy": gmax > 1,
    }


def resolve_view_coordinates(
    *,
    default_galaxy: int,
    default_system: int,
    req_galaxy: Optional[int] = None,
    req_system: Optional[int] = None,
    coord_query: Optional[str] = None,
    carry_system: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[int, int, Optional[int]]:
    """
    Merge URL/query inputs into a validated view target.
    When only ``req_galaxy`` is set, keeps ``carry_system`` (last viewed system) if valid.
    Returns (galaxy, system, optional_highlight_position).
    """
    galaxy = clamp_galaxy(default_galaxy, conn=conn)
    system = clamp_system(default_system)
    highlight_pos: Optional[int] = None
    parsed_query: Optional[Dict[str, int]] = None

    if coord_query:
        parsed_query = parse_coordinate_query(coord_query)
        if parsed_query:
            galaxy = clamp_galaxy(parsed_query["galaxy"], conn=conn)
            system = clamp_system(parsed_query["system"])
            if "position" in parsed_query:
                highlight_pos = max(
                    POSITION_MIN,
                    min(POSITION_MAX, int(parsed_query["position"])),
                )

    if req_galaxy is not None:
        galaxy = clamp_galaxy(req_galaxy, conn=conn)
        if req_system is None and parsed_query is None and carry_system is not None:
            system = clamp_system(int(carry_system))

    if req_system is not None:
        system = clamp_system(req_system)

    return galaxy, system, highlight_pos


def list_system(
    galaxy: int,
    system: int,
    conn: Optional[sqlite3.Connection] = None,
    *,
    viewer_player_id: Optional[int] = None,
    active_planet_id: Optional[int] = None,
    highlight_position: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Return exactly 15 slot entries for the given system (positions 1–15).
    Single query for occupied planets in that system.
    """
    validate_coordinates(galaxy, system, POSITION_MIN)

    own = conn is None
    if own:
        conn = db()

    from .alliance import are_players_allied

    by_position: Dict[int, Dict[str, Any]] = {}
    if _coords_schema_ready(conn):
        cur = conn.cursor()
        has_planet_class = column_exists(conn, "planets", "planet_class")
        class_col = "p.planet_class" if has_planet_class else "'terrestrial' AS planet_class"
        cur.execute(
            f"""
            SELECT
                p.id AS planet_id,
                p.name AS planet_name,
                p.galaxy,
                p.system,
                p.position,
                p.player_id,
                pl.name AS commander_name,
                {class_col}
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
            row_dict = dict(row)
            coords = get_planet_coordinates(row_dict)
            meta = _slot_planet_meta(row_dict, conn)
            pid = int(row["planet_id"])
            player_id = int(row["player_id"])
            is_own = (
                viewer_player_id is not None
                and player_id == int(viewer_player_id)
            )
            is_ally = (
                not is_own
                and viewer_player_id is not None
                and are_players_allied(int(viewer_player_id), player_id, conn=conn)
            )
            is_active = (
                active_planet_id is not None and pid == int(active_planet_id)
            )
            is_highlighted = (
                highlight_position is not None and pos == int(highlight_position)
            )
            by_position[pos] = {
                "position": pos,
                "occupied": True,
                "player_id": player_id,
                "commander_name": str(row["commander_name"] or ""),
                "planet_id": pid,
                "planet_name": str(row["planet_name"] or ""),
                "coordinates": {
                    "galaxy": coords["galaxy"],
                    "system": coords["system"],
                    "position": coords["position"],
                },
                "coordinates_formatted": coords["formatted"],
                "planet_class": meta["planet_class"],
                "planet_class_label_key": meta["planet_class_label_key"],
                "temperature_display": meta["temperature_display"],
                "planet_score": meta["planet_score"],
                "is_own_planet": is_own,
                "is_ally_planet": is_ally,
                "is_active_planet": is_active,
                "is_highlighted": is_highlighted,
                "colony_target": False,
            }

    slots: List[Dict[str, Any]] = []
    for pos in range(POSITION_MIN, POSITION_MAX + 1):
        if pos in by_position:
            slots.append(by_position[pos])
        else:
            is_highlighted = (
                highlight_position is not None and pos == int(highlight_position)
            )
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
                    "planet_class": None,
                    "planet_class_label_key": None,
                    "temperature_display": None,
                    "planet_score": None,
                    "is_own_planet": False,
                    "is_ally_planet": False,
                    "is_active_planet": False,
                    "is_highlighted": is_highlighted,
                    "colony_target": True,
                }
            )

    result = {
        "galaxy": int(galaxy),
        "system": int(system),
        "slots": slots,
        "slot_count": POSITION_MAX,
        "highlight_position": highlight_position,
    }

    if own:
        conn.close()
    return result
