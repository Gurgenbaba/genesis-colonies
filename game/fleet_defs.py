"""Central ship definitions for the fleet system — Genesis Colonies hull registry."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List

SHIP_ROLES = frozenset(
    {"cargo", "combat", "spy", "recycle", "expedition", "scout", "utility", "colony"}
)

MISSION_TYPES = frozenset({"transport", "collect", "deploy", "spy", "attack", "hold", "expedition", "colonize"})

# Player-facing mission order on fleet send UI.
FLEET_MISSION_ORDER: List[str] = [
    "transport",
    "collect",
    "deploy",
    "spy",
    "attack",
    "colonize",
    "hold",
    "expedition",
]

FLEET_STATUSES = frozenset({"outbound", "holding", "returning", "completed", "cancelled", "failed"})

PRESET_TYPES = frozenset({"raid", "farm", "spy", "transport", "deploy", "expedition", "custom"})

BATCH_TYPES = frozenset(
    {"mass_expedition", "distribute_resources", "collect_resources", "mass_transport", "custom"}
)

BATCH_STATUSES = frozenset({"pending", "running", "completed", "cancelled", "failed"})

ACTIVE_FLEET_STATUSES = frozenset({"outbound", "holding", "returning"})

EXPEDITION_POSITION = 16

DEFAULT_HOLD_SECONDS = 3600

FLEET_FUEL_RESOURCE = "fuel_cells"

VALID_RESOURCE_KEYS = frozenset({"metal", "crystal", "fuel_cells"})

# Legacy OGame-style keys → canonical Genesis Colonies keys (read-compat only).
LEGACY_SHIP_KEY_MAP: Dict[str, str] = {
    "small_cargo": "mule_courier",
    "large_cargo": "atlas_hauler",
    "light_fighter": "falcon_interceptor",
    "heavy_fighter": "ironclad_frigate",
    "spy_probe": "veil_probe",
    "recycler": "harvest_reclaimer",
    "expedition_vessel": "solar_skiff",
}

LEGACY_SHIP_KEYS: FrozenSet[str] = frozenset(LEGACY_SHIP_KEY_MAP.keys())

# Dev/admin seed fleet (canonical keys).
DEV_SEED_SHIPS: Dict[str, int] = {
    "spark_drone": 15,
    "mule_courier": 20,
    "veil_probe": 20,
    "solar_skiff": 5,
    "falcon_interceptor": 25,
    "ironclad_frigate": 10,
    "atlas_hauler": 10,
    "harvest_reclaimer": 5,
    "seed_ark": 1,
}

# Phase 1 active hulls (eclipse_runner prepared but optional).
ACTIVE_SHIP_KEYS: FrozenSet[str] = frozenset(
    {
        "spark_drone",
        "mule_courier",
        "veil_probe",
        "solar_skiff",
        "falcon_interceptor",
        "ironclad_frigate",
        "atlas_hauler",
        "harvest_reclaimer",
        "seed_ark",
    }
)

SHIPS: Dict[str, Dict[str, Any]] = {
    "spark_drone": {
        "name_key": "fleet_ship_spark_drone",
        "description_key": "fleet_ship_spark_drone_desc",
        "role": "scout",
        "required_shipyard_level": 1,
        "requirements": {"buildings": {"orbital_shipyard": 1, "research_lab": 1}},
        "build_cost": {"metal": 500, "crystal": 200, "fuel_cells": 0},
        "build_seconds": 30,
        "speed": 20000,
        "cargo": 10,
        "fuel": 5,
        "attack": 1,
        "shield": 5,
        "hull": 200,
        "crew": 1,
    },
    "mule_courier": {
        "name_key": "fleet_ship_mule_courier",
        "description_key": "fleet_ship_mule_courier_desc",
        "role": "cargo",
        "required_shipyard_level": 1,
        "requirements": {"buildings": {"orbital_shipyard": 1}, "research": {"mining_tech": 1}},
        "build_cost": {"metal": 2000, "crystal": 2000, "fuel_cells": 0},
        "build_seconds": 120,
        "speed": 5000,
        "cargo": 5000,
        "fuel": 10,
        "attack": 5,
        "shield": 10,
        "hull": 400,
        "crew": 3,
    },
    "veil_probe": {
        "name_key": "fleet_ship_veil_probe",
        "description_key": "fleet_ship_veil_probe_desc",
        "role": "spy",
        "required_shipyard_level": 1,
        "requirements": {
            "buildings": {"orbital_shipyard": 1, "research_lab": 2},
            "research": {"drone_tech": 1},
        },
        "build_cost": {"metal": 1000, "crystal": 500, "fuel_cells": 0},
        "build_seconds": 60,
        "speed": 100000000,
        "cargo": 0,
        "fuel": 1,
        "attack": 0,
        "shield": 0,
        "hull": 500,
        "crew": 0,
    },
    "solar_skiff": {
        "name_key": "fleet_ship_solar_skiff",
        "description_key": "fleet_ship_solar_skiff_desc",
        "role": "expedition",
        "required_shipyard_level": 2,
        "requirements": {
            "buildings": {"orbital_shipyard": 2},
            "research": {"engine_tech": 1, "navigation_tech": 1},
        },
        "build_cost": {"metal": 4000, "crystal": 3000, "fuel_cells": 10},
        "build_seconds": 300,
        "speed": 8000,
        "cargo": 2000,
        "fuel": 3,
        "attack": 5,
        "shield": 15,
        "hull": 800,
        "crew": 4,
    },
    "falcon_interceptor": {
        "name_key": "fleet_ship_falcon_interceptor",
        "description_key": "fleet_ship_falcon_interceptor_desc",
        "role": "combat",
        "required_shipyard_level": 2,
        "requirements": {
            "buildings": {"orbital_shipyard": 2, "barracks": 1},
            "research": {"weapon_tech": 2},
        },
        "build_cost": {"metal": 3000, "crystal": 1000, "fuel_cells": 0},
        "build_seconds": 180,
        "speed": 12500,
        "cargo": 50,
        "fuel": 20,
        "attack": 50,
        "shield": 10,
        "hull": 400,
        "crew": 5,
    },
    "ironclad_frigate": {
        "name_key": "fleet_ship_ironclad_frigate",
        "description_key": "fleet_ship_ironclad_frigate_desc",
        "role": "combat",
        "required_shipyard_level": 4,
        "requirements": {
            "buildings": {"orbital_shipyard": 4, "barracks": 2},
            "research": {"weapon_tech": 4, "armor_tech": 2},
        },
        "build_cost": {"metal": 15000, "crystal": 7000, "fuel_cells": 0},
        "build_seconds": 600,
        "speed": 10000,
        "cargo": 100,
        "fuel": 75,
        "attack": 150,
        "shield": 25,
        "hull": 1000,
        "crew": 12,
    },
    "atlas_hauler": {
        "name_key": "fleet_ship_atlas_hauler",
        "description_key": "fleet_ship_atlas_hauler_desc",
        "role": "cargo",
        "required_shipyard_level": 4,
        "requirements": {
            "buildings": {"orbital_shipyard": 4},
            "research": {"storage_tech": 3, "mining_tech": 2},
        },
        "build_cost": {"metal": 6000, "crystal": 6000, "fuel_cells": 0},
        "build_seconds": 480,
        "speed": 7500,
        "cargo": 25000,
        "fuel": 50,
        "attack": 5,
        "shield": 25,
        "hull": 1200,
        "crew": 8,
    },
    "harvest_reclaimer": {
        "name_key": "fleet_ship_harvest_reclaimer",
        "description_key": "fleet_ship_harvest_reclaimer_desc",
        "role": "recycle",
        "required_shipyard_level": 5,
        "requirements": {
            "buildings": {"orbital_shipyard": 5},
            "research": {"drone_tech": 3, "fuel_efficiency": 2},
        },
        "build_cost": {"metal": 10000, "crystal": 6000, "fuel_cells": 20},
        "build_seconds": 540,
        "speed": 2000,
        "cargo": 20000,
        "fuel": 300,
        "attack": 1,
        "shield": 10,
        "hull": 1600,
        "crew": 10,
    },
    "seed_ark": {
        "name_key": "fleet_ship_seed_ark",
        "description_key": "fleet_ship_seed_ark_desc",
        "role": "colony",
        "required_shipyard_level": 6,
        "requirements": {
            "buildings": {"orbital_shipyard": 6, "command_center": 3},
            "research": {"navigation_tech": 3, "storage_tech": 2},
        },
        "build_cost": {"metal": 50000, "crystal": 30000, "fuel_cells": 100},
        "build_seconds": 3600,
        "speed": 1500,
        "cargo": 5000,
        "fuel": 200,
        "attack": 10,
        "shield": 50,
        "hull": 3000,
        "crew": 50,
    },
    "eclipse_runner": {
        "name_key": "fleet_ship_eclipse_runner",
        "description_key": "fleet_ship_eclipse_runner_desc",
        "role": "expedition",
        "required_shipyard_level": 7,
        "build_cost": {"metal": 12000, "crystal": 8000, "fuel_cells": 50},
        "build_seconds": 900,
        "speed": 6000,
        "cargo": 5000,
        "fuel": 40,
        "attack": 25,
        "shield": 40,
        "hull": 2000,
        "crew": 8,
        "phase2_only": True,
        "requirements": {
            "buildings": {"orbital_shipyard": 7},
            "research": {"engine_tech": 4, "shield_tech": 2},
        },
    },
}


def ship_icon_filename(ship_key: str) -> str:
    return f"{canonical_ship_key(ship_key)}.svg"


def ship_icon_static_path(ship_key: str) -> str:
    return f"/static/img/ships/{ship_icon_filename(ship_key)}"


def canonical_ship_key(ship_key: str) -> str:
    k = str(ship_key or "").strip()
    return LEGACY_SHIP_KEY_MAP.get(k, k)


def is_known_ship_key(ship_key: str) -> bool:
    return canonical_ship_key(ship_key) in SHIPS


def all_ship_keys() -> FrozenSet[str]:
    return frozenset(SHIPS.keys())


def get_ship(ship_key: str) -> Dict[str, Any] | None:
    return SHIPS.get(canonical_ship_key(ship_key))


def ship_defs_for_client(*, include_phase2: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    keys = sorted(ACTIVE_SHIP_KEYS)
    if include_phase2:
        keys = sorted(set(keys) | {"eclipse_runner"})
    for key in keys:
        spec = SHIPS.get(key)
        if not spec:
            continue
        out.append({"key": key, **spec})
    return out


def ships_for_fleet_ui() -> List[Dict[str, Any]]:
    """Hull list shown on fleet send UI (Phase 1 active hulls only)."""
    return ship_defs_for_client(include_phase2=False)
