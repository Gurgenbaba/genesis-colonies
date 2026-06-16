"""Empire identity layer — colony roles and homeworld framing (GC-560). Display only, no gameplay."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import sqlite3

from ..defense_defs import DEFENSE_ORDER
from ..models import get_planet_buildings, get_planet_defense, get_planets_by_player

ROLE_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "homeworld": {
        "label_key": "empire_role_homeworld",
        "icon": "🏛",
        "subtitle_key": "empire_homeworld_subtitle",
    },
    "mining": {
        "label_key": "empire_role_mining",
        "icon": "⛏",
        "subtitle_key": "empire_role_mining",
    },
    "research": {
        "label_key": "empire_role_research",
        "icon": "🔬",
        "subtitle_key": "empire_role_research",
    },
    "shipyard": {
        "label_key": "empire_role_shipyard",
        "icon": "⚓",
        "subtitle_key": "empire_role_shipyard",
    },
    "fortress": {
        "label_key": "empire_role_fortress",
        "icon": "🛡",
        "subtitle_key": "empire_role_fortress",
    },
    "trade": {
        "label_key": "empire_role_trade",
        "icon": "🏪",
        "subtitle_key": "empire_role_trade",
    },
    "frontier": {
        "label_key": "empire_role_frontier",
        "icon": "🌌",
        "subtitle_key": "empire_role_frontier",
    },
    "general": {
        "label_key": "empire_role_general",
        "icon": "🌍",
        "subtitle_key": "empire_role_general",
    },
}

_MINING_KEYS = ("metal_mine", "crystal_mine", "fuel_cell_plant")
_RESEARCH_KEYS = ("research_lab", "academy")
_SHIPYARD_KEYS = ("orbital_shipyard",)
_FORTRESS_BUILDING_KEYS = ("defense_factory", "barracks", "shield_generator", "radar_array")
_FRONTIER_INFRA_MAX = 8


def _level_sum(buildings: Dict[str, int], keys: Tuple[str, ...]) -> int:
    return sum(max(0, int(buildings.get(key) or 0)) for key in keys)


def _total_building_levels(buildings: Dict[str, int]) -> int:
    return sum(max(0, int(level or 0)) for level in buildings.values())


def _defense_unit_total(planet_id: int, conn: sqlite3.Connection) -> int:
    defense = get_planet_defense(planet_id, conn=conn) or {}
    return sum(max(0, int(defense.get(key) or 0)) for key in DEFENSE_ORDER)


def _has_active_trade_routes(planet_id: int, owner_player_id: int, conn: sqlite3.Connection) -> bool:
    from .repository import get_trade_routes

    pid = int(planet_id)
    for route in get_trade_routes(int(owner_player_id), conn=conn):
        if int(route.get("source_planet_id") or 0) == pid or int(route.get("target_planet_id") or 0) == pid:
            return True
    return False


def _is_trade_specialization(planet_row: Dict[str, Any]) -> bool:
    spec = str(planet_row.get("specialization_key") or "").lower()
    return "trade" in spec


def derive_colony_role_key(
    planet_id: int,
    *,
    planet_row: Optional[Dict[str, Any]] = None,
    conn: sqlite3.Connection,
) -> str:
    """Return role key for a non-homeworld colony (display only)."""
    pid = int(planet_id)
    buildings = get_planet_buildings(pid, conn=conn) or {}

    if planet_row is None:
        from .repository import get_planet_row

        planet_row = get_planet_row(pid, conn=conn) or {}

    owner_id = int(planet_row.get("player_id") or 0)
    if owner_id and (_has_active_trade_routes(pid, owner_id, conn) or _is_trade_specialization(planet_row)):
        return "trade"

    scores = {
        "mining": _level_sum(buildings, _MINING_KEYS),
        "research": _level_sum(buildings, _RESEARCH_KEYS),
        "shipyard": _level_sum(buildings, _SHIPYARD_KEYS) * 2,
        "fortress": _level_sum(buildings, _FORTRESS_BUILDING_KEYS) + _defense_unit_total(pid, conn),
    }

    total_infra = _total_building_levels(buildings)
    if total_infra <= _FRONTIER_INFRA_MAX and max(scores.values()) <= 2:
        return "frontier"

    best_key = max(scores, key=lambda k: scores[k])
    best_score = scores[best_key]
    if best_score <= 0:
        return "frontier" if total_infra <= _FRONTIER_INFRA_MAX else "general"

    tied = [key for key, score in scores.items() if score == best_score]
    if len(tied) > 1:
        return "general"
    return best_key


def role_payload(role_key: str) -> Dict[str, str]:
    role = ROLE_DEFINITIONS.get(role_key) or ROLE_DEFINITIONS["general"]
    return {
        "empire_role_key": role_key,
        "empire_role_label_key": role["label_key"],
        "empire_role_icon": role["icon"],
        "empire_subtitle_key": role.get("subtitle_key") or role["label_key"],
        "identity_title_key": role.get("subtitle_key") or role["label_key"],
    }


def empire_identity_for_planet(
    planet_row: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
) -> Dict[str, str]:
    """Identity fields for switcher / empire card payloads."""
    if bool(planet_row.get("is_homeworld")):
        return role_payload("homeworld")

    planet_role = str(planet_row.get("planet_role") or "").strip()
    if planet_role:
        from .strategic_worlds import empire_role_key_for_planet_role

        mapped = empire_role_key_for_planet_role(planet_role)
        if mapped != "general":
            return role_payload(mapped)

    role_key = derive_colony_role_key(
        int(planet_row["id"]),
        planet_row=planet_row,
        conn=conn,
    )
    return role_payload(role_key)


def build_colonies_identity(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    from ..galaxy import GalaxyCoordinateError, get_planet_coordinates
    from .repository import get_active_planet_id

    uid = int(player_id)
    active_id = int(get_active_planet_id(uid, conn=conn) or 0)
    planets = get_planets_by_player(uid, conn=conn)

    def _sort_key(row: Dict[str, Any]) -> Tuple[int, str, int]:
        return (
            0 if bool(row.get("is_homeworld")) else 1,
            str(row.get("name") or "").lower(),
            int(row.get("id") or 0),
        )

    rows: List[Dict[str, Any]] = []
    for planet in sorted(planets, key=_sort_key):
        pid = int(planet["id"])
        coords_formatted = ""
        try:
            coords_formatted = get_planet_coordinates(planet)["formatted"]
        except GalaxyCoordinateError:
            coords_formatted = ""

        identity = empire_identity_for_planet(planet, conn=conn)
        row: Dict[str, Any] = {
            "planet_id": pid,
            "name": planet.get("name"),
            "coordinates_formatted": coords_formatted,
            "is_homeworld": bool(planet.get("is_homeworld")),
            "is_active": pid == active_id,
            **identity,
        }
        world_x = planet.get("world_x")
        world_y = planet.get("world_y")
        world_key = planet.get("world_key")
        if world_key and world_x is not None and world_y is not None:
            row["world_key"] = str(world_key)
            row["world_x"] = float(world_x)
            row["world_y"] = float(world_y)
            row["planet_role"] = str(planet.get("planet_role") or "")
            row["origin_world_key"] = str(planet.get("origin_world_key") or world_key)
        rows.append(row)
    return rows
