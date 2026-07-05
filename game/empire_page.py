"""Empire page context — player-wide colony aggregation (GC-620A)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .effects.effect_resolver import EffectResolver
from .galaxy import get_planet_coordinates
from .logic import get_planet_limit_block
from .models import (
    get_game_settings,
    get_planet_buildings,
    get_planet_defense,
    get_planets_by_player,
    get_research_levels,
    load_player,
)
from .overview_page import build_planet_meta
from .planet_evolution.scoring import compute_single_planet_score
from .player_display import commander_display_name
from .ranking import get_player_score_cached

# Fuel storage at or above this cap is treated as unlimited in the matrix UI.
_FUEL_STORAGE_UNLIMITED_CAP = 1_000_000_000


def _matrix_section_definitions() -> List[Dict[str, Any]]:
    """Row/column schema for the full empire matrix (GC-620D)."""
    from .buildings import BUILDING_ORDER
    from .defense_defs import DEFENSE_ORDER, DEFENSES
    from .fleet_defs import ACTIVE_SHIP_KEYS, SHIPS
    from .research import RESEARCH_TECHS

    def _rows(keys: List[str], label_fn) -> Tuple[Dict[str, Any], ...]:
        return tuple(
            {"key": key, "label_key": label_fn(key), "format": "int", "summable": True}
            for key in keys
        )

    building_rows = tuple(
        {
            "key": key,
            "label_key": f"building_{key}",
            "format": "level",
            "summable": True,
        }
        for key in BUILDING_ORDER
    )
    defense_rows = tuple(
        {
            "key": key,
            "label_key": str((DEFENSES.get(key) or {}).get("name_key") or f"defense_{key}"),
            "format": "count",
            "summable": True,
        }
        for key in DEFENSE_ORDER
    )
    ship_rows = tuple(
        {
            "key": key,
            "label_key": str((SHIPS.get(key) or {}).get("name_key") or f"fleet_ship_{key}"),
            "format": "count",
            "summable": True,
        }
        for key in sorted(ACTIVE_SHIP_KEYS)
    )
    research_rows = tuple(
        {
            "key": key,
            "label_key": str((cfg or {}).get("label_key") or key),
            "format": "level",
            "summable": False,
        }
        for key, cfg in RESEARCH_TECHS.items()
    )

    return [
        {
            "key": "resources",
            "label_key": "empire_matrix_resources",
            "scope": "colony",
            "rows": _rows(
                ("metal", "crystal", "fuel_cells", "energy_surplus"),
                lambda k: {
                    "metal": "resource_metal",
                    "crystal": "resource_crystal",
                    "fuel_cells": "resource_fuel_cells",
                    "energy_surplus": "empire_label_energy_surplus",
                }[k],
            ),
        },
        {
            "key": "production",
            "label_key": "empire_matrix_production",
            "scope": "colony",
            "rows": (
                {"key": "metal", "label_key": "empire_matrix_prod_metal", "format": "rate", "summable": True},
                {"key": "crystal", "label_key": "empire_matrix_prod_crystal", "format": "rate", "summable": True},
                {"key": "fuel_cells", "label_key": "empire_matrix_prod_fuel", "format": "rate", "summable": True},
                {"key": "metal_day", "label_key": "empire_matrix_prod_metal_day", "format": "int", "summable": True},
                {"key": "crystal_day", "label_key": "empire_matrix_prod_crystal_day", "format": "int", "summable": True},
                {"key": "fuel_cells_day", "label_key": "empire_matrix_prod_fuel_day", "format": "int", "summable": True},
            ),
        },
        {
            "key": "storage",
            "label_key": "empire_matrix_storage",
            "scope": "colony",
            "rows": (
                {"key": "metal", "label_key": "empire_matrix_storage_metal", "format": "int", "summable": True},
                {"key": "crystal", "label_key": "empire_matrix_storage_crystal", "format": "int", "summable": True},
                {
                    "key": "fuel_cells",
                    "label_key": "empire_matrix_storage_fuel",
                    "format": "storage_fuel",
                    "summable": False,
                },
            ),
        },
        {
            "key": "buildings",
            "label_key": "empire_matrix_buildings",
            "scope": "colony",
            "rows": building_rows,
        },
        {
            "key": "account_research",
            "label_key": "empire_matrix_research",
            "scope": "account",
            "rows": research_rows,
        },
        {
            "key": "defense",
            "label_key": "empire_matrix_defense",
            "scope": "colony",
            "rows": defense_rows,
        },
        {
            "key": "ships",
            "label_key": "empire_matrix_ships",
            "scope": "colony",
            "rows": ship_rows,
        },
    ]


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        if raw is None or raw == "":
            return int(default)
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _storage_total(caps: Dict[str, Any]) -> int:
    return (
        _safe_int(caps.get("metal"))
        + _safe_int(caps.get("crystal"))
        + _safe_int(caps.get("fuel_cells"))
    )


def _colony_rank_entry(colony: Dict[str, Any], *, value_key: str) -> Dict[str, Any]:
    return {
        "planet_id": _safe_int(colony.get("planet_id")),
        "name": str(colony.get("name") or ""),
        "value": _safe_int(colony.get(value_key)),
    }


def _pick_rank(
    colonies: List[Dict[str, Any]],
    *,
    value_key: str,
    highest: bool = True,
) -> Optional[Dict[str, Any]]:
    if not colonies:
        return None
    ranked = sorted(
        colonies,
        key=lambda c: (_safe_int(c.get(value_key)), str(c.get("name") or "")),
        reverse=highest,
    )
    winner = ranked[0]
    return _colony_rank_entry(winner, value_key=value_key)


def _storage_fuel_matrix_value(fuel_cap: int) -> int:
    cap = _safe_int(fuel_cap)
    if cap <= 0 or cap >= _FUEL_STORAGE_UNLIMITED_CAP:
        return -1
    return cap


def _build_colony_matrix_data(
    colony: Dict[str, Any],
    *,
    buildings: Dict[str, int],
    defense: Dict[str, int],
    ships: Dict[str, int],
) -> Dict[str, Dict[str, int]]:
    from .buildings import BUILDING_ORDER
    from .defense_defs import DEFENSE_ORDER
    from .fleet_defs import ACTIVE_SHIP_KEYS

    resources = colony.get("resources") if isinstance(colony.get("resources"), dict) else {}
    production = colony.get("production_per_hour") if isinstance(colony.get("production_per_hour"), dict) else {}
    storage = colony.get("storage") if isinstance(colony.get("storage"), dict) else {}
    energy = colony.get("energy") if isinstance(colony.get("energy"), dict) else {}

    metal_ph = _safe_int(production.get("metal"))
    crystal_ph = _safe_int(production.get("crystal"))
    fuel_ph = _safe_int(production.get("fuel_cells"))

    return {
        "resources": {
            "metal": _safe_int(resources.get("metal")),
            "crystal": _safe_int(resources.get("crystal")),
            "fuel_cells": _safe_int(resources.get("fuel_cells")),
            "energy_surplus": _safe_int(energy.get("surplus")),
        },
        "production": {
            "metal": metal_ph,
            "crystal": crystal_ph,
            "fuel_cells": fuel_ph,
            "metal_day": metal_ph * 24,
            "crystal_day": crystal_ph * 24,
            "fuel_cells_day": fuel_ph * 24,
        },
        "storage": {
            "metal": _safe_int(storage.get("metal")),
            "crystal": _safe_int(storage.get("crystal")),
            "fuel_cells": _storage_fuel_matrix_value(_safe_int(storage.get("fuel_cells"))),
        },
        "buildings": {
            key: _safe_int(buildings.get(key)) for key in BUILDING_ORDER
        },
        "defense": {
            key: _safe_int(defense.get(key)) for key in DEFENSE_ORDER
        },
        "ships": {
            key: _safe_int(ships.get(key)) for key in sorted(ACTIVE_SHIP_KEYS)
        },
    }


def _aggregate_matrix_totals(
    colony_values: List[Dict[str, Dict[str, int]]],
    sections: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    totals: Dict[str, Dict[str, int]] = {}
    for section in sections:
        if str(section.get("scope")) == "account":
            continue
        section_key = str(section["key"])
        totals[section_key] = {}
        for row in section.get("rows") or ():
            if not row.get("summable"):
                continue
            row_key = str(row["key"])
            if row.get("format") == "storage_fuel":
                continue
            total = 0
            for colony_data in colony_values:
                group = colony_data.get(section_key) if isinstance(colony_data.get(section_key), dict) else {}
                total += _safe_int(group.get(row_key))
            totals[section_key][row_key] = int(total)
    return totals


def _build_colony_matrix_header(colony: Dict[str, Any]) -> Dict[str, Any]:
    coords = colony.get("coordinates") if isinstance(colony.get("coordinates"), dict) else {}
    position = int(coords.get("position") or 0)
    from .planet_visuals import temperature_range_for_position

    temp = temperature_range_for_position(position)
    return {
        "planet_id": _safe_int(colony.get("planet_id")),
        "name": str(colony.get("name") or ""),
        "coordinates_display": str(coords.get("display") or ""),
        "planet_class_label_key": str(colony.get("planet_class_label_key") or ""),
        "planet_class": str(colony.get("planet_class") or "terrestrial"),
        "temperature_display": str(temp.get("display") or ""),
        "is_homeworld": bool(colony.get("is_homeworld")),
    }


def _build_empire_matrix(
    colonies: List[Dict[str, Any]],
    *,
    account_research: Dict[str, int],
) -> Dict[str, Any]:
    sections = _matrix_section_definitions()
    colony_headers: List[Dict[str, Any]] = []
    colony_values: List[Dict[str, Dict[str, int]]] = []

    for colony in colonies:
        colony_headers.append(_build_colony_matrix_header(colony))
        colony_values.append(
            colony.get("matrix_data") if isinstance(colony.get("matrix_data"), dict) else {}
        )

    account_values = {
        str(key): _safe_int(account_research.get(key))
        for key in (account_research or {}).keys()
    }
    from .research import RESEARCH_TECHS

    for tech_key in RESEARCH_TECHS:
        account_values[str(tech_key)] = _safe_int(account_research.get(tech_key))

    return {
        "colonies": colony_headers,
        "colony_values": colony_values,
        "sections": sections,
        "totals": _aggregate_matrix_totals(colony_values, sections),
        "account_values": account_values,
    }


def _build_colony_snapshot(
    planet: Dict[str, Any],
    *,
    player_id: int,
    research: Dict[str, int],
    settings: Dict[str, Any],
    conn,
) -> Dict[str, Any]:
    planet_id = _safe_int(planet.get("id"))
    buildings = get_planet_buildings(planet_id, conn=conn)
    from .galaxy import get_planet_coordinates

    coords = get_planet_coordinates(planet)
    position = int(coords.get("position") or 0) or None
    galaxy_id = int(coords.get("galaxy") or 0) or None
    resolver = EffectResolver(
        buildings,
        research,
        settings=settings,
        player_id=int(player_id),
        planet_id=planet_id,
        planet_position=position,
        galaxy_id=galaxy_id,
        conn=conn,
    )
    energy_total, energy_used = resolver.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    prod_by_building = resolver.get_building_production_per_hour(ratio)
    caps = resolver.get_storage_capacity()

    metal = _safe_int(planet.get("metal"))
    crystal = _safe_int(planet.get("crystal"))
    fuel_cells = _safe_int(planet.get("fuel_cells"))
    metal_cap = _safe_int(caps.get("metal"))
    crystal_cap = _safe_int(caps.get("crystal"))
    fuel_cap = _safe_int(caps.get("fuel_cells"))

    production = {
        "metal": _safe_int(prod_by_building.get("metal_mine")),
        "crystal": _safe_int(prod_by_building.get("crystal_mine")),
        "fuel_cells": _safe_int(prod_by_building.get("fuel_cell_plant")),
    }
    storage_total = _storage_total(caps)

    meta = build_planet_meta(planet)
    planet_score = 0
    try:
        planet_score = compute_single_planet_score(planet_id, conn=conn)
    except Exception:
        planet_score = 0

    defense: Dict[str, int] = {}
    ships: Dict[str, int] = {}
    try:
        defense = get_planet_defense(planet_id, conn=conn) or {}
    except Exception:
        defense = {}
    try:
        from .fleet import get_planet_ships

        ships = get_planet_ships(planet_id, conn=conn) or {}
    except Exception:
        ships = {}

    snapshot = {
        "planet_id": planet_id,
        "name": str(planet.get("name") or "Kolonie"),
        "is_homeworld": bool(_safe_int(planet.get("is_homeworld"))),
        "coordinates": meta.get("coordinates") or {},
        "planet_class": str(meta.get("planet_class") or "terrestrial"),
        "planet_class_label_key": str(meta.get("planet_class_label_key") or ""),
        "resources": {
            "metal": metal,
            "crystal": crystal,
            "fuel_cells": fuel_cells,
        },
        "storage": {
            "metal": metal_cap,
            "crystal": crystal_cap,
            "fuel_cells": fuel_cap,
        },
        "storage_fill": {
            "metal_pct": min(100, int(metal / metal_cap * 100)) if metal_cap > 0 else 0,
            "crystal_pct": min(100, int(crystal / crystal_cap * 100)) if crystal_cap > 0 else 0,
            "fuel_cells_pct": min(100, int(fuel_cells / fuel_cap * 100)) if fuel_cap > 0 else 0,
        },
        "production_per_hour": production,
        "energy": {
            "total": int(energy_total),
            "used": int(energy_used),
            "surplus": max(0, int(energy_total) - int(energy_used)),
        },
        "planet_score": int(planet_score),
        "storage_total": int(storage_total),
        "metal_production": production["metal"],
        "crystal_production": production["crystal"],
        "fuel_production": production["fuel_cells"],
    }
    snapshot["matrix_data"] = _build_colony_matrix_data(
        snapshot,
        buildings=buildings,
        defense=defense,
        ships=ships,
    )
    return snapshot


def _aggregate_production(colonies: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    for colony in colonies:
        prod = colony.get("production_per_hour") if isinstance(colony.get("production_per_hour"), dict) else {}
        totals["metal"] += _safe_int(prod.get("metal"))
        totals["crystal"] += _safe_int(prod.get("crystal"))
        totals["fuel_cells"] += _safe_int(prod.get("fuel_cells"))
    return totals


def get_empire_production_aggregate(player_id: int, *, conn=None) -> Dict[str, int]:
    """
    Empire-wide hourly production (all colonies) and 24h totals.
    Same EffectResolver path as build_empire_context / empire matrix.
    """
    from .models import db as _db

    uid = int(player_id)
    own_conn = conn is None
    if own_conn:
        conn = _db()

    try:
        planets = get_planets_by_player(uid, conn=conn)
        research = get_research_levels(user_id=uid, conn=conn)
        try:
            settings = get_game_settings(conn=conn)
        except TypeError:
            settings = get_game_settings()

        per_hour = {"metal": 0, "crystal": 0, "fuel_cells": 0}
        for planet in planets:
            if _safe_int(planet.get("player_id")) != uid:
                continue
            snapshot = _build_colony_snapshot(
                planet,
                player_id=uid,
                research=research,
                settings=settings or {},
                conn=conn,
            )
            prod = snapshot.get("production_per_hour") if isinstance(snapshot.get("production_per_hour"), dict) else {}
            per_hour["metal"] += _safe_int(prod.get("metal"))
            per_hour["crystal"] += _safe_int(prod.get("crystal"))
            per_hour["fuel_cells"] += _safe_int(prod.get("fuel_cells"))

        metal_day = int(per_hour["metal"]) * 24
        crystal_day = int(per_hour["crystal"]) * 24
        fuel_day = int(per_hour["fuel_cells"]) * 24
        return {
            "metal_per_hour": int(per_hour["metal"]),
            "crystal_per_hour": int(per_hour["crystal"]),
            "fuel_cells_per_hour": int(per_hour["fuel_cells"]),
            "metal_per_day": metal_day,
            "crystal_per_day": crystal_day,
            "fuel_cells_per_day": fuel_day,
            "total_per_day": metal_day + crystal_day + fuel_day,
        }
    finally:
        if own_conn and conn is not None:
            conn.close()


def _aggregate_energy(colonies: List[Dict[str, Any]]) -> Dict[str, int]:
    total = used = 0
    for colony in colonies:
        energy = colony.get("energy") if isinstance(colony.get("energy"), dict) else {}
        total += _safe_int(energy.get("total"))
        used += _safe_int(energy.get("used"))
    return {
        "total": int(total),
        "used": int(used),
        "surplus": max(0, int(total) - int(used)),
    }


def _build_rankings(colonies: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "strongest_colony": _pick_rank(colonies, value_key="planet_score", highest=True),
        "weakest_colony": _pick_rank(colonies, value_key="planet_score", highest=False),
        "highest_metal_production": _pick_rank(colonies, value_key="metal_production", highest=True),
        "highest_crystal_production": _pick_rank(colonies, value_key="crystal_production", highest=True),
        "highest_fuel_production": _pick_rank(colonies, value_key="fuel_production", highest=True),
        "largest_storage": _pick_rank(colonies, value_key="storage_total", highest=True),
    }


def _strip_ranking_fields(colony: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(colony)
    for key in (
        "storage_total",
        "metal_production",
        "crystal_production",
        "fuel_production",
        "matrix_data",
    ):
        out.pop(key, None)
    return out


def build_empire_context(player_id: int, *, conn=None) -> Dict[str, Any]:
    """
    Aggregate empire-wide colony data for the /empire page.

    All production and energy values are computed server-side via EffectResolver.
    Resource balances are ticked for every owned planet before aggregation.
    """
    from .models import db as _db
    from .resources import sync_player_planet_resources

    uid = int(player_id)
    own_conn = conn is None
    if own_conn:
        conn = _db()

    try:
        sync_player_planet_resources(uid, conn=conn, finish_queue_first=True, skip_fresh_sec=2.0)

        player = load_player(uid, conn=conn) or {}
        planets = get_planets_by_player(uid, conn=conn)
        research = get_research_levels(user_id=uid, conn=conn)
        try:
            settings = get_game_settings(conn=conn)
        except TypeError:
            settings = get_game_settings()

        colonies: List[Dict[str, Any]] = []
        for planet in planets:
            if _safe_int(planet.get("player_id")) != uid:
                continue
            colonies.append(
                _build_colony_snapshot(
                    planet,
                    player_id=uid,
                    research=research,
                    settings=settings or {},
                    conn=conn,
                )
            )

        scores = get_player_score_cached(uid, read_only=True)
        limit = get_planet_limit_block(uid, conn=conn)

        public_colonies = [_strip_ranking_fields(c) for c in colonies]

        return {
            "commander": {
                "id": uid,
                "name": commander_display_name(player.get("name")),
            },
            "colony_count": len(public_colonies),
            "colony_limit": dict(limit),
            "total_score": _safe_int(scores.get("total")),
            "production": _aggregate_production(colonies),
            "energy": _aggregate_energy(colonies),
            "colonies": public_colonies,
            "rankings": _build_rankings(colonies),
            "matrix": _build_empire_matrix(
                colonies,
                account_research=research,
            ),
        }
    finally:
        if own_conn and conn is not None:
            conn.close()
