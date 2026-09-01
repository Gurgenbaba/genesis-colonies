"""
Galaxy coordinate engine — single source of truth for universe positions.

Universe layout (v1):
  Galaxy:    1
  Systems:   1–499
  Positions: 1–15 per system (7485 slots total)
"""

from __future__ import annotations

import random
import re
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .db import db, table_exists, column_exists

GALAXY_MIN = 1
SYSTEM_MIN = 1
SYSTEM_MAX = 499
POSITION_MIN = 1
POSITION_MAX = 15
EXPEDITION_SLOT_POSITION = 16
MINIMAP_RADIUS = 4
HOMEWORLD_RANDOM_ATTEMPTS = 300

_COORD_QUERY_RE = re.compile(
    r"^\s*\[?\s*(\d+)\s*:\s*(\d+)\s*(?::\s*(\d+)\s*)?\]?\s*$"
)


class GalaxyCoordinateError(ValueError):
    """Invalid or unavailable galaxy coordinates."""


_GALAXY_MAX_CACHE: Tuple[float, int] = (0.0, 1)
_GALAXY_MAX_TTL_SEC = 60.0


def get_galaxy_max(conn: Optional[sqlite3.Connection] = None) -> int:
    """Playable galaxies from game settings (admin: galaxy_count)."""
    global _GALAXY_MAX_CACHE
    cached_at, cached_val = _GALAXY_MAX_CACHE
    now = time.time()
    if cached_val >= 1 and (now - cached_at) <= _GALAXY_MAX_TTL_SEC:
        return int(cached_val)

    own = conn is None
    if own:
        conn = db()
    try:
        from .models import get_game_settings

        settings = get_game_settings(conn=conn) if conn is not None else get_game_settings()
        raw = settings.get("galaxy_count", "1")
        value = max(1, min(20, int(raw)))
        _GALAXY_MAX_CACHE = (now, value)
        return value
    except Exception:
        return int(cached_val) if cached_val >= 1 else 1
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


def galaxy_view_href(raw: str) -> Optional[str]:
    """Relative URL to :func:`galaxy_view` with system/position highlight when parseable."""
    from urllib.parse import quote

    text = str(raw or "").strip()
    if not text:
        return None
    parsed = parse_coordinate_query(text)
    if not parsed:
        return None
    if "position" in parsed:
        q = format_coordinates(
            int(parsed["galaxy"]),
            int(parsed["system"]),
            int(parsed["position"]),
        )
    else:
        q = f"{int(parsed['galaxy'])}:{int(parsed['system'])}"
    return f"/galaxy?q={quote(q)}"


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


def _sequential_free_slot(
    occupied: Set[Tuple[int, int, int]],
    galaxy_min: int,
    galaxy_max: int,
) -> Optional[Tuple[int, int, int]]:
    for g in range(int(galaxy_min), int(galaxy_max) + 1):
        for system in range(SYSTEM_MIN, SYSTEM_MAX + 1):
            for position in range(POSITION_MIN, POSITION_MAX + 1):
                key = (g, system, position)
                if key not in occupied:
                    return key
    return None


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
    strategy: str = "sequential",
) -> Tuple[int, int, int]:
    """
    Find a free planet slot (positions 1–15 only).

    ``strategy="sequential"`` — scan order (galaxy asc, system asc, position asc)
    within the requested galaxy. Used for colonization and repair.

    ``strategy="random"`` — random slot across galaxies 1..galaxy_count, then
    sequential fallback. Used for new-player homeworld bootstrap only.
    Must be called inside a write transaction when assigning to avoid races.
    """
    gmax = get_galaxy_max(conn)
    occupied = _load_occupied(conn, exclude_planet_id=exclude_planet_id)

    if strategy == "random":
        found = None
        for _ in range(HOMEWORLD_RANDOM_ATTEMPTS):
            g = random.randint(GALAXY_MIN, gmax)
            system = random.randint(SYSTEM_MIN, SYSTEM_MAX)
            position = random.randint(POSITION_MIN, POSITION_MAX)
            key = (g, system, position)
            if key not in occupied:
                found = key
                break
        if found is None:
            found = _sequential_free_slot(occupied, GALAXY_MIN, gmax)
        if found is None:
            raise GalaxyCoordinateError("no free galaxy coordinates remaining")
        validate_coordinates(found[0], found[1], found[2], galaxy_max=gmax, conn=conn)
        return found

    g = int(galaxy)
    if g < GALAXY_MIN or g > gmax:
        raise GalaxyCoordinateError(f"galaxy out of range: {g}")

    found = _sequential_free_slot(occupied, g, g)
    if found is None:
        raise GalaxyCoordinateError("no free galaxy coordinates remaining")
    return found


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


def _attach_slot_presentation(
    slot: Dict[str, Any],
    position: int,
    *,
    planet_row: Optional[Dict[str, Any]] = None,
    occupied: bool = False,
) -> None:
    from .planet_visuals import slot_galaxy_ring_presentation

    slot.update(
        slot_galaxy_ring_presentation(
            position,
            planet_row=planet_row,
            occupied=occupied,
        )
    )


# GC-2612: "recently active" pulse window for the galaxy ring badge — purely
# visual (Living Universe Pulse), no ranking/PvP impact.
RECENTLY_ACTIVE_WINDOW_SEC = 2 * 3600


def _player_activity_select(conn: sqlite3.Connection, *, alias: str = "pl") -> str:
    """Optional vacation + last_seen columns for galaxy slot player flags."""
    parts: List[str] = []
    if column_exists(conn, "players", "vacation_mode_active"):
        parts.append(f"COALESCE({alias}.vacation_mode_active, 0) AS vacation_mode_active")
    else:
        parts.append("0 AS vacation_mode_active")
    if column_exists(conn, "players", "last_seen"):
        parts.append(f"COALESCE({alias}.last_seen, 0) AS last_seen")
    else:
        parts.append("0 AS last_seen")
    return ", ".join(parts)


def _viewer_allied_player_ids(viewer_player_id: Optional[int], conn: sqlite3.Connection) -> Set[int]:
    """Players sharing an alliance with the viewer (excluding viewer)."""
    viewer_id = int(viewer_player_id or 0)
    if viewer_id <= 0 or not table_exists(conn, "alliance_members"):
        return set()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT am2.player_id
        FROM alliance_members am1
        INNER JOIN alliance_members am2
            ON am2.alliance_id = am1.alliance_id
        WHERE am1.player_id = ?;
        """,
        (viewer_id,),
    )
    return {int(row["player_id"]) for row in cur.fetchall() if int(row["player_id"]) != viewer_id}


def _attach_player_status_flags(
    slot: Dict[str, Any],
    *,
    viewer_player_id: Optional[int],
    conn: sqlite3.Connection,
    pirate_profiles: Optional[Mapping[int, Mapping[str, Any]]] = None,
    noob_strengths: Optional[Mapping[int, Optional[str]]] = None,
) -> None:
    """Vacation / inactive / noob-protection strength hints for galaxy presentation."""
    if not slot.get("occupied"):
        slot["vacation_active"] = False
        slot["inactive"] = False
        slot["recently_active"] = False
        slot["attack_strength"] = None
        return

    from .ranking import ranking_inactive_from_last_seen

    slot["vacation_active"] = bool(int(slot.pop("_vacation_mode_active", slot.get("vacation_active", 0)) or 0))
    last_seen = int(slot.pop("_last_seen", slot.get("last_seen", 0)) or 0)
    slot["inactive"] = ranking_inactive_from_last_seen(last_seen)
    # GC-2612: "living universe" pulse — independent of is_ai/inactive, so real
    # players who dropped by recently also show the chip (not only AI/inactive).
    slot["recently_active"] = bool(last_seen > 0 and (time.time() - last_seen) < RECENTLY_ACTIVE_WINDOW_SEC)

    target_player_id = int(slot.get("player_id") or 0)
    ai = None
    if pirate_profiles is not None:
        ai = pirate_profiles.get(target_player_id)
    elif target_player_id > 0:
        try:
            from .pirates.accounts import get_pirate_ai_profile

            ai = get_pirate_ai_profile(target_player_id, conn=conn)
        except Exception:
            ai = None
    if ai:
        slot["is_ai"] = True
        slot["inactive"] = False
        slot["player_mode"] = ai.get("player_mode")
        slot["ai_kind"] = ai.get("ai_kind")
        slot["ai_faction_key"] = ai.get("faction_key")
        slot["ai_personality"] = ai.get("personality")
        slot["ai_mode_key"] = ai.get("mode_key")
        slot["ai_badge_key"] = ai.get("badge_key")
        slot["ai_badge_title_key"] = ai.get("badge_title_key")
        slot["ai_name_key"] = ai.get("name_key")
        slot["ai_commander_key"] = ai.get("commander_key")
    else:
        slot["is_ai"] = False

    strength: Optional[str] = None
    viewer_id = int(viewer_player_id or 0)
    if (
        viewer_id > 0
        and target_player_id > 0
        and target_player_id != viewer_id
        and not slot.get("is_ally_planet")
        and not slot.get("is_own_planet")
        and not slot.get("is_ai")
    ):
        if noob_strengths is not None:
            strength = noob_strengths.get(target_player_id)
        else:
            from .fleet import get_noob_protection_status

            info = get_noob_protection_status(viewer_id, target_player_id, conn=conn)
            if not info.get("allowed"):
                def_score = int(info.get("defender_score") or 0)
                max_def = int(info.get("max_defender_score") or 0)
                min_def = int(info.get("min_defender_score") or 0)
                if def_score > max_def:
                    strength = "too_strong"
                elif def_score < min_def:
                    strength = "too_weak"
    slot["attack_strength"] = strength


def _slot_planet_meta(
    planet_row: Dict[str, Any],
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    from .planet_evolution.dna import effective_planet_class
    from .planet_visuals import temperature_range_for_position
    from .planet_evolution.scoring import compute_single_planet_score
    from .planet_evolution.ux_copy import planet_class_label_key

    planet_class = effective_planet_class(planet_row)
    coords = get_planet_coordinates(planet_row)
    position = int(coords.get("position") or planet_row.get("position") or 0)
    temp = temperature_range_for_position(position)
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


def sync_galaxy_view_session_for_planet(session: Any, planet: Mapping[str, Any]) -> None:
    """Align Flask session galaxy coords with active/context planet (e.g. after planet switch)."""
    coords = get_planet_coordinates(planet)
    session["galaxy_view_galaxy"] = int(coords["galaxy"])
    session["galaxy_view_system"] = int(coords["system"])


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


def get_debris_for_system(
    galaxy: int,
    system: int,
    conn: sqlite3.Connection,
    *,
    now: Optional[float] = None,
) -> Dict[int, Dict[str, Any]]:
    """Map position → debris row for one system (amounts + ``updated_at`` for TTL).

    GC-PG-HIGHSPEED-001A: read-only composition — filter expired rows here;
    physical DELETE stays on maintenance ``expire_due_debris_fields``.
    """
    from .combat import DEBRIS_FIELD_TTL_SECONDS, debris_schema_ready

    out: Dict[int, Dict[str, Any]] = {}
    if not debris_schema_ready(conn):
        return out
    ts = float(now if now is not None else time.time())
    cutoff = ts - float(DEBRIS_FIELD_TTL_SECONDS)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT position, metal, crystal, updated_at
        FROM debris_fields
        WHERE galaxy = ? AND system = ?
          AND (position BETWEEN ? AND ? OR position = ?)
          AND updated_at > ?;
        """,
        (
            int(galaxy),
            int(system),
            POSITION_MIN,
            POSITION_MAX,
            EXPEDITION_SLOT_POSITION,
            cutoff,
        ),
    )
    for row in cur.fetchall():
        pos = int(row["position"])
        metal = max(0, int(float(row["metal"] or 0)))
        crystal = max(0, int(float(row["crystal"] or 0)))
        if metal <= 0 and crystal <= 0:
            continue
        updated_at = float(row["updated_at"]) if row["updated_at"] is not None else None
        out[pos] = {"metal": metal, "crystal": crystal, "updated_at": updated_at}
    return out


def _attach_debris_to_slot(
    slot: Dict[str, Any],
    debris: Mapping[str, Any] | None,
    *,
    galaxy: int,
    system: int,
    position: int,
) -> None:
    from .world_inspector import build_debris_field_payload

    d = dict(debris or {})
    payload = build_debris_field_payload(
        int(d.get("metal") or 0),
        int(d.get("crystal") or 0),
        updated_at=d.get("updated_at"),
        galaxy=int(galaxy),
        system=int(system),
        position=int(position),
    )
    if payload:
        slot["debris"] = payload
        slot["has_debris"] = True
        return
    slot["debris"] = {"metal": 0, "crystal": 0, "total": 0, "has_debris": False}
    slot["has_debris"] = False


def _attach_world_boss_to_slot(
    slot: Dict[str, Any],
    boss: Mapping[str, Any] | None,
    *,
    viewer_player_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """EPIC-20 — stamp active world boss metadata onto a galaxy slot."""
    if not boss:
        slot["world_boss"] = None
        slot["has_world_boss"] = False
        return
    payload = dict(boss)
    if viewer_player_id is not None and conn is not None and payload.get("event_id"):
        try:
            from .world_boss import can_player_attack_boss

            ok_atk, reason, meta = can_player_attack_boss(
                int(viewer_player_id), int(payload["event_id"]), conn=conn
            )
            payload["viewer_can_attack"] = bool(ok_atk)
            payload["viewer_attack_block_reason"] = reason if not ok_atk else ""
            payload["viewer_attack_meta"] = dict(meta or {})
        except Exception:
            payload["viewer_can_attack"] = None
            payload["viewer_attack_block_reason"] = ""
            payload["viewer_attack_meta"] = {}
    slot["world_boss"] = payload
    slot["has_world_boss"] = True


def _attach_asteroid_to_slot(
    slot: Dict[str, Any],
    asteroid: Mapping[str, Any] | None,
) -> None:
    """GC-AST — stamp active asteroid field metadata onto a galaxy slot."""
    if not asteroid:
        slot["asteroid"] = None
        slot["has_asteroid"] = False
        return
    payload = dict(asteroid)
    total = (
        int(payload.get("metal") or 0)
        + int(payload.get("crystal") or 0)
        + int(payload.get("fuel_cells") or 0)
    )
    if total <= 0:
        slot["asteroid"] = None
        slot["has_asteroid"] = False
        return
    slot["asteroid"] = payload
    slot["has_asteroid"] = True


def _attach_pirate_base_to_slot(
    slot: Dict[str, Any],
    base: Mapping[str, Any] | None,
    *,
    viewer_player_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """EPIC-21 — stamp active pirate base onto a galaxy slot."""
    if not base:
        slot["pirate_base"] = None
        slot["has_pirate_base"] = False
        return
    payload = dict(base)
    if viewer_player_id is not None and conn is not None and payload.get("base_id"):
        try:
            from .pirates.bases import can_player_attack_base

            ok_atk, reason, meta = can_player_attack_base(
                int(viewer_player_id), int(payload["base_id"]), conn=conn
            )
            payload["viewer_can_attack"] = bool(ok_atk)
            payload["viewer_attack_block_reason"] = reason if not ok_atk else ""
            payload["viewer_attack_meta"] = dict(meta or {})
        except Exception:
            payload["viewer_can_attack"] = None
            payload["viewer_attack_block_reason"] = ""
            payload["viewer_attack_meta"] = {}
        try:
            from .pirates.bounty import get_player_bounty

            fk = str(payload.get("faction_key") or "")
            if fk:
                bounty = get_player_bounty(int(viewer_player_id), fk, conn=conn)
                payload["viewer_bounty_credits"] = int(bounty.get("credits") or 0)
                payload["viewer_bounty_kills"] = int(bounty.get("kills") or 0)
        except Exception:
            payload["viewer_bounty_credits"] = 0
            payload["viewer_bounty_kills"] = 0
    slot["pirate_base"] = payload
    slot["has_pirate_base"] = True


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
    own = conn is None
    if own:
        conn = db()

    validate_coordinates(galaxy, system, POSITION_MIN, conn=conn)

    allied_player_ids = _viewer_allied_player_ids(viewer_player_id, conn)

    by_position: Dict[int, Dict[str, Any]] = {}
    occupied_player_ids: List[int] = []
    if _coords_schema_ready(conn):
        cur = conn.cursor()
        has_planet_class = column_exists(conn, "planets", "planet_class")
        class_col = "p.planet_class" if has_planet_class else "'terrestrial' AS planet_class"
        player_activity = _player_activity_select(conn, alias="pl")
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
                {class_col},
                {player_activity}
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
                and player_id in allied_player_ids
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
                "_vacation_mode_active": int(row_dict.get("vacation_mode_active") or 0),
                "_last_seen": int(row_dict.get("last_seen") or 0),
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
            occupied_player_ids.append(player_id)

    pirate_profiles: Dict[int, Dict[str, Any]] = {}
    noob_strengths: Dict[int, Optional[str]] = {}
    if occupied_player_ids:
        try:
            from .pirates.accounts import pirate_ai_profiles_by_ids

            pirate_profiles = pirate_ai_profiles_by_ids(
                occupied_player_ids,
                conn=conn,
                ensure_state=False,
            )
        except Exception:
            pirate_profiles = {}
        if viewer_player_id is not None:
            try:
                from .fleet import noob_attack_strength_by_defender_ids

                noob_strengths = noob_attack_strength_by_defender_ids(
                    int(viewer_player_id),
                    occupied_player_ids,
                    conn=conn,
                )
            except Exception:
                noob_strengths = {}

    debris_by_position = get_debris_for_system(int(galaxy), int(system), conn)
    try:
        from .world_boss import get_bosses_for_system

        bosses_by_position = get_bosses_for_system(int(galaxy), int(system), conn=conn)
    except Exception:
        bosses_by_position = {}
    try:
        from .asteroids import get_asteroids_for_system

        asteroids_by_position = get_asteroids_for_system(
            int(galaxy),
            int(system),
            conn=conn,
            viewer_player_id=viewer_player_id,
        )
    except Exception:
        asteroids_by_position = {}
    try:
        from .pirates.bases import get_bases_for_system

        pirate_bases_by_position = get_bases_for_system(
            int(galaxy), int(system), conn=conn
        )
    except Exception:
        pirate_bases_by_position = {}

    from .planet_visuals import temperature_range_for_position

    slots: List[Dict[str, Any]] = []
    for pos in range(POSITION_MIN, POSITION_MAX + 1):
        if pos in by_position:
            slot = by_position[pos]
            _attach_debris_to_slot(
                slot,
                debris_by_position.get(pos),
                galaxy=int(galaxy),
                system=int(system),
                position=pos,
            )
            _attach_world_boss_to_slot(
                slot,
                bosses_by_position.get(pos),
                viewer_player_id=viewer_player_id,
                conn=conn,
            )
            _attach_asteroid_to_slot(slot, asteroids_by_position.get(pos))
            _attach_pirate_base_to_slot(
                slot,
                pirate_bases_by_position.get(pos),
                viewer_player_id=viewer_player_id,
                conn=conn,
            )
            _attach_slot_presentation(slot, pos, planet_row={"position": pos}, occupied=True)
            _attach_player_status_flags(
                slot,
                viewer_player_id=viewer_player_id,
                conn=conn,
                pirate_profiles=pirate_profiles,
                noob_strengths=noob_strengths,
            )
            slots.append(slot)
        else:
            is_highlighted = (
                highlight_position is not None and pos == int(highlight_position)
            )
            slot = {
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
                "temperature_display": temperature_range_for_position(pos)["display"],
                "planet_score": None,
                "is_own_planet": False,
                "is_ally_planet": False,
                "is_active_planet": False,
                "is_highlighted": is_highlighted,
                "colony_target": False,
            }
            _attach_debris_to_slot(
                slot,
                debris_by_position.get(pos),
                galaxy=int(galaxy),
                system=int(system),
                position=pos,
            )
            _attach_world_boss_to_slot(
                slot,
                bosses_by_position.get(pos),
                viewer_player_id=viewer_player_id,
                conn=conn,
            )
            _attach_asteroid_to_slot(slot, asteroids_by_position.get(pos))
            _attach_pirate_base_to_slot(
                slot,
                pirate_bases_by_position.get(pos),
                viewer_player_id=viewer_player_id,
                conn=conn,
            )
            _attach_slot_presentation(slot, pos, occupied=False)
            slots.append(slot)

    try:
        from .playercard import map_equipped_name_styles

        style_map = map_equipped_name_styles(
            [int(s["player_id"]) for s in slots if s.get("player_id")],
            conn=conn,
        )
    except Exception:
        style_map = {}
    for slot in slots:
        pid = int(slot.get("player_id") or 0)
        slot["name_style"] = style_map.get(pid, "none") if pid > 0 else "none"

    available_reclaimers = 0
    if active_planet_id is not None and int(active_planet_id) > 0:
        try:
            from .fleet import get_planet_ships

            ships = get_planet_ships(int(active_planet_id), conn=conn)
            available_reclaimers = max(0, int(ships.get("harvest_reclaimer") or 0))
        except Exception:
            available_reclaimers = 0

    active_asteroid_board: List[Dict[str, Any]] = []
    asteroid_schedule: Dict[str, Any] = {}
    try:
        from .asteroids import build_asteroid_board_entries, build_schedule_info

        active_asteroid_board = build_asteroid_board_entries(
            conn=conn,
            current_galaxy=int(galaxy),
            current_system=int(system),
            viewer_player_id=viewer_player_id,
        )
        asteroid_schedule = build_schedule_info(conn=conn)
    except Exception:
        active_asteroid_board = []
        asteroid_schedule = {}

    galaxy_heat: Dict[str, Any] = {
        "galaxy_id": int(galaxy),
        "heat": 0,
        "band": "calm",
        "thresholds": {},
    }
    try:
        from .pirates import get_galaxy_heat

        galaxy_heat = get_galaxy_heat(conn, int(galaxy))
    except Exception:
        pass

    result = {
        "galaxy": int(galaxy),
        "system": int(system),
        "slots": slots,
        "slot_count": POSITION_MAX,
        "highlight_position": highlight_position,
        "available_reclaimers": available_reclaimers,
        "active_asteroid_board": active_asteroid_board,
        "asteroid_schedule": asteroid_schedule,
        "galaxy_heat": galaxy_heat,
    }

    if own:
        conn.close()
    return result


def count_empty_galaxy_slots(*, conn: sqlite3.Connection) -> int:
    """Unoccupied classic [G:S:P] slots (positions 1–15) for colonization hints."""
    gmax = get_galaxy_max(conn)
    total = gmax * (SYSTEM_MAX - SYSTEM_MIN + 1) * (POSITION_MAX - POSITION_MIN + 1)
    cur = conn.execute(
        """
        SELECT COUNT(*) AS occupied
        FROM planets
        WHERE galaxy BETWEEN ? AND ?
          AND system BETWEEN ? AND ?
          AND position BETWEEN ? AND ?;
        """,
        (GALAXY_MIN, gmax, SYSTEM_MIN, SYSTEM_MAX, POSITION_MIN, POSITION_MAX),
    )
    row = cur.fetchone()
    occupied = int(row["occupied"] if row else 0)
    return max(0, int(total) - occupied)


# ---------------------------------------------------------------------------
# Planet relocation (evacuation move)
# ---------------------------------------------------------------------------

RELOCATION_DURATION_SECONDS = 3600
RELOCATION_COOLDOWN_SECONDS = 86400


def player_has_seed_ark(player_id: int, *, conn: sqlite3.Connection) -> bool:
    """True if any owned colony has at least one seed_ark (colonization ship)."""
    from .fleet import get_planet_ships
    from .models import get_planets_by_player

    for planet in get_planets_by_player(int(player_id), conn=conn):
        ships = get_planet_ships(int(planet["id"]), conn=conn) or {}
        if int(ships.get("seed_ark") or 0) >= 1:
            return True
    return False


def relocation_schema_ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "planet_relocations")


def _relocation_cooldown_column_ready(conn: sqlite3.Connection) -> bool:
    return column_exists(conn, "planets", "relocation_cooldown_until")


def _fetch_active_relocation_row(
    conn: sqlite3.Connection,
    planet_id: int,
) -> Optional[Dict[str, Any]]:
    if not relocation_schema_ready(conn):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM planet_relocations
        WHERE planet_id = ? AND status = 'active'
        ORDER BY id DESC
        LIMIT 1;
        """,
        (int(planet_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _relocation_row_to_client(
    row: Dict[str, Any],
    *,
    now: float,
) -> Dict[str, Any]:
    finish_at = float(row.get("finish_at") or 0)
    remaining = max(0, int(finish_at - float(now)))
    return {
        "active": True,
        "relocation_id": int(row.get("id") or 0),
        "from": format_coordinates(
            int(row.get("from_galaxy") or 0),
            int(row.get("from_system") or 0),
            int(row.get("from_position") or 0),
        ),
        "target": format_coordinates(
            int(row.get("target_galaxy") or 0),
            int(row.get("target_system") or 0),
            int(row.get("target_position") or 0),
        ),
        "target_galaxy": int(row.get("target_galaxy") or 0),
        "target_system": int(row.get("target_system") or 0),
        "target_position": int(row.get("target_position") or 0),
        "started_at": int(float(row.get("started_at") or 0)),
        "finish_at": int(finish_at),
        "remaining_seconds": remaining,
        "can_start": False,
        "cooldown_until": 0,
        "cooldown_remaining_seconds": 0,
    }


def get_relocation_client_state(
    planet_id: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """UI/API block for planet manage modal and game-state."""
    if now is None:
        now = time.time()
    now_f = float(now)
    pid = int(planet_id)

    idle: Dict[str, Any] = {
        "active": False,
        "relocation_id": 0,
        "from": "",
        "target": "",
        "target_galaxy": 0,
        "target_system": 0,
        "target_position": 0,
        "started_at": 0,
        "finish_at": 0,
        "remaining_seconds": 0,
        "can_start": True,
        "cooldown_until": 0,
        "cooldown_remaining_seconds": 0,
    }

    if not relocation_schema_ready(conn):
        idle["can_start"] = False
        return idle

    active = _fetch_active_relocation_row(conn, pid)
    if active:
        return _relocation_row_to_client(active, now=now_f)

    cooldown_until = 0.0
    if _relocation_cooldown_column_ready(conn):
        cur = conn.cursor()
        cur.execute(
            "SELECT relocation_cooldown_until FROM planets WHERE id = ? LIMIT 1;",
            (pid,),
        )
        row = cur.fetchone()
        if row:
            cooldown_until = float(row["relocation_cooldown_until"] or 0)

    if cooldown_until > now_f:
        idle["can_start"] = False
        idle["cooldown_until"] = int(cooldown_until)
        idle["cooldown_remaining_seconds"] = max(0, int(cooldown_until - now_f))

    return idle


def start_planet_relocation(
    player_id: int,
    target_galaxy: int,
    target_system: int,
    target_position: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Schedule evacuation move of the player's active planet to a free slot.
    Move completes after RELOCATION_DURATION_SECONDS via finish_due_relocations.
    """
    from .db import begin_write_transaction, commit, rollback
    from .options import write_account_audit
    from .planet_evolution.repository import get_context_planet

    own = conn is None
    if own:
        conn = db()
    assert conn is not None

    if not relocation_schema_ready(conn):
        if own:
            conn.close()
        return False, "planet_relocation_unavailable", {}

    try:
        planet = get_context_planet(int(player_id), conn=conn)
        if not planet or not planet.get("id"):
            return False, "planet_error_not_found", {}

        planet_id = int(planet["id"])
        coords = get_planet_coordinates(planet)
        from_g = int(coords["galaxy"])
        from_s = int(coords["system"])
        from_p = int(coords["position"])

        tg = int(target_galaxy)
        ts = int(target_system)
        tp = int(target_position)

        try:
            validate_coordinates(tg, ts, tp, conn=conn)
        except GalaxyCoordinateError:
            return False, "planet_relocation_invalid_coords", {}

        if (from_g, from_s, from_p) == (tg, ts, tp):
            return False, "planet_relocation_same_slot", {}

        now = time.time()

        state = get_relocation_client_state(planet_id, conn=conn, now=now)
        if state.get("active"):
            return False, "planet_relocation_already_active", state
        if not state.get("can_start"):
            return False, "planet_relocation_cooldown", state

        if not coordinate_is_available(conn, tg, ts, tp):
            return False, "planet_relocation_slot_taken", {}

        begin_write_transaction(conn)
        if not coordinate_is_available(conn, tg, ts, tp):
            rollback(conn)
            return False, "planet_relocation_slot_taken", {}

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planet_relocations (
                planet_id, player_id,
                from_galaxy, from_system, from_position,
                target_galaxy, target_system, target_position,
                started_at, finish_at, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?);
            """,
            (
                planet_id,
                int(player_id),
                from_g,
                from_s,
                from_p,
                tg,
                ts,
                tp,
                float(now),
                float(now) + float(RELOCATION_DURATION_SECONDS),
                float(now),
            ),
        )
        write_account_audit(
            int(player_id),
            "planet_relocation_started",
            payload={
                "planet_id": planet_id,
                "from": format_coordinates(from_g, from_s, from_p),
                "target": format_coordinates(tg, ts, tp),
                "finish_at": float(now) + float(RELOCATION_DURATION_SECONDS),
            },
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        result = get_relocation_client_state(planet_id, conn=conn, now=now)
        result["planet_id"] = planet_id
        return True, "planet_relocation_started", result
    except Exception:
        if own:
            rollback(conn)
        return False, "planet_relocation_failed", {}
    finally:
        if own and conn is not None:
            conn.close()


def finish_due_relocations(
    conn: sqlite3.Connection,
    *,
    player_id: Optional[int] = None,
    now: Optional[float] = None,
) -> int:
    """Apply completed relocation jobs. Returns number of planets moved."""
    if not relocation_schema_ready(conn):
        return 0

    if now is None:
        now = time.time()
    now_f = float(now)

    from .options import write_account_audit

    cur = conn.cursor()
    params: List[Any] = [now_f]
    sql = """
        SELECT *
        FROM planet_relocations
        WHERE status = 'active' AND finish_at <= ?
    """
    if player_id is not None:
        sql += " AND player_id = ?"
        params.append(int(player_id))
    sql += " ORDER BY finish_at ASC, id ASC;"
    cur.execute(sql, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return 0

    moved = 0
    for row in rows:
        rid = int(row["id"])
        planet_id = int(row["planet_id"])
        pid_player = int(row["player_id"])
        tg = int(row["target_galaxy"])
        ts = int(row["target_system"])
        tp = int(row["target_position"])

        try:
            if not coordinate_is_available(conn, tg, ts, tp, exclude_planet_id=planet_id):
                cur.execute(
                    "UPDATE planet_relocations SET status = 'failed' WHERE id = ?;",
                    (rid,),
                )
                write_account_audit(
                    pid_player,
                    "planet_relocation_failed",
                    payload={
                        "planet_id": planet_id,
                        "target": format_coordinates(tg, ts, tp),
                        "reason": "slot_taken",
                    },
                    conn=conn,
                )
                continue

            assert_coordinate_available(conn, tg, ts, tp, exclude_planet_id=planet_id)
            cur.execute(
                """
                UPDATE planets
                SET galaxy = ?, system = ?, position = ?
                WHERE id = ? AND player_id = ?;
                """,
                (tg, ts, tp, planet_id, pid_player),
            )
            if int(cur.rowcount or 0) <= 0:
                cur.execute(
                    "UPDATE planet_relocations SET status = 'failed' WHERE id = ?;",
                    (rid,),
                )
                continue

            cooldown_until = now_f + float(RELOCATION_COOLDOWN_SECONDS)
            if _relocation_cooldown_column_ready(conn):
                cur.execute(
                    """
                    UPDATE planets
                    SET relocation_cooldown_until = ?
                    WHERE id = ?;
                    """,
                    (cooldown_until, planet_id),
                )

            cur.execute(
                "UPDATE planet_relocations SET status = 'completed' WHERE id = ?;",
                (rid,),
            )
            write_account_audit(
                pid_player,
                "planet_relocation_completed",
                payload={
                    "planet_id": planet_id,
                    "from": format_coordinates(
                        int(row["from_galaxy"]),
                        int(row["from_system"]),
                        int(row["from_position"]),
                    ),
                    "target": format_coordinates(tg, ts, tp),
                    "cooldown_until": cooldown_until,
                },
                conn=conn,
            )
            moved += 1
        except Exception:
            cur.execute(
                "UPDATE planet_relocations SET status = 'failed' WHERE id = ?;",
                (rid,),
            )
            write_account_audit(
                pid_player,
                "planet_relocation_failed",
                payload={
                    "planet_id": planet_id,
                    "target": format_coordinates(tg, ts, tp),
                    "reason": "error",
                },
                conn=conn,
            )

    return moved
