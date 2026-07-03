"""Central ship definitions for the fleet system — Genesis Colonies hull registry."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List

SHIP_ROLES = frozenset(
    {"cargo", "combat", "spy", "recycle", "expedition", "scout", "utility", "colony"}
)

MISSION_TYPES = frozenset(
    {"transport", "collect", "deploy", "spy", "attack", "hold", "expedition", "colonize", "recycle"}
)

# Player-facing mission order on fleet send UI.
FLEET_MISSION_ORDER: List[str] = [
    "transport",
    "collect",
    "recycle",
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

EXPEDITION_STAY_HOURS_MIN = 1
EXPEDITION_STAY_HOURS_MAX = 4
EXPEDITION_STAY_HOUR_SECONDS = 3600
DEFAULT_EXPEDITION_STAY_HOURS = 1

# Mass-expedition waves: 1s between departures so arrival/holding/return ticks do not overlap.
MASS_EXPEDITION_STAGGER_SECONDS = 1

# Admin game_settings keys per mission category (higher = shorter flight legs).
FLEET_SPEED_WAR_MISSIONS = frozenset({"attack", "spy"})
FLEET_SPEED_HOLD_MISSIONS = frozenset({"hold"})

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

# Max base build time per ship (4:20) — effective time may drop via yard level / bonuses (min 1s).
MAX_SHIP_BUILD_SECONDS = 260

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
        "deep_vault_ark",
    }
)

# build_cost: metal, crystal, fuel_cells — static defs; fuel_cells nur Mid/High-Tier (GC-860).
SHIPS: Dict[str, Dict[str, Any]] = {
    "spark_drone": {
        "name_key": "fleet_ship_spark_drone",
        "description_key": "fleet_ship_spark_drone_desc",
        "role": "scout",
        "required_shipyard_level": 1,
        "requirements": {"buildings": {"orbital_shipyard": 1, "research_lab": 1}, "research": {"energy_tech": 2}},
        "build_cost": {"metal": 625, "crystal": 250, "fuel_cells": 0},
        "build_seconds": 30,
        "score_value": 700,
        "speed": 20000,
        "cargo": 10,
        "fuel": 5,
        "attack": 1,
        "shield": 5,
        "hull": 200,
        "rapid_fire_targets": {"veil_probe": 2},
        "crew": 1,
    },
    "mule_courier": {
        "name_key": "fleet_ship_mule_courier",
        "description_key": "fleet_ship_mule_courier_desc",
        "role": "cargo",
        "required_shipyard_level": 1,
        "requirements": {"buildings": {"orbital_shipyard": 1}, "research": {"mining_tech": 3}},
        "build_cost": {"metal": 2500, "crystal": 2500, "fuel_cells": 0},
        "build_seconds": 120,
        "score_value": 4000,
        "speed": 5000,
        "cargo": 5000,
        "fuel": 10,
        "attack": 5,
        "shield": 10,
        "hull": 400,
        "rapid_fire_targets": {},
        "crew": 3,
    },
    "veil_probe": {
        "name_key": "fleet_ship_veil_probe",
        "description_key": "fleet_ship_veil_probe_desc",
        "role": "spy",
        "required_shipyard_level": 1,
        "requirements": {
            "buildings": {"orbital_shipyard": 1, "research_lab": 2},
            "research": {"drone_tech": 3},
        },
        "build_cost": {"metal": 1250, "crystal": 625, "fuel_cells": 0},
        "build_seconds": 60,
        "score_value": 1500,
        "speed": 100000000,
        "cargo": 0,
        "fuel": 1,
        "attack": 0,
        "shield": 0,
        "hull": 500,
        "rapid_fire_targets": {},
        "crew": 0,
    },
    "solar_skiff": {
        "name_key": "fleet_ship_solar_skiff",
        "description_key": "fleet_ship_solar_skiff_desc",
        "role": "expedition",
        "required_shipyard_level": 2,
        "requirements": {
            "buildings": {"orbital_shipyard": 2},
            "research": {"engine_tech": 3, "navigation_tech": 3},
        },
        "build_cost": {"metal": 5000, "crystal": 3750, "fuel_cells": 0},
        "build_seconds": 260,
        "score_value": 7000,
        "speed": 8000,
        "cargo": 2000,
        "fuel": 3,
        "attack": 5,
        "shield": 15,
        "hull": 800,
        "rapid_fire_targets": {},
        "crew": 4,
    },
    "falcon_interceptor": {
        "name_key": "fleet_ship_falcon_interceptor",
        "description_key": "fleet_ship_falcon_interceptor_desc",
        "role": "combat",
        "required_shipyard_level": 2,
        "requirements": {
            "buildings": {"orbital_shipyard": 2, "barracks": 1},
            "research": {"weapon_tech": 5},
        },
        "build_cost": {"metal": 3750, "crystal": 1250, "fuel_cells": 0},
        "build_seconds": 180,
        "score_value": 4000,
        "speed": 12500,
        "cargo": 50,
        "fuel": 20,
        "attack": 50,
        "shield": 10,
        "hull": 400,
        "rapid_fire_targets": {"spark_drone": 3, "veil_probe": 2},
        "crew": 5,
    },
    "ironclad_frigate": {
        "name_key": "fleet_ship_ironclad_frigate",
        "description_key": "fleet_ship_ironclad_frigate_desc",
        "role": "combat",
        "required_shipyard_level": 4,
        "requirements": {
            "buildings": {"orbital_shipyard": 4, "barracks": 2},
            "research": {"weapon_tech": 7, "armor_tech": 4},
        },
        "build_cost": {"metal": 18750, "crystal": 8750, "fuel_cells": 12500},
        "build_seconds": 240,
        "score_value": 22000,
        "speed": 10000,
        "cargo": 100,
        "fuel": 75,
        "attack": 150,
        "shield": 25,
        "hull": 1000,
        "rapid_fire_targets": {"falcon_interceptor": 2, "mule_courier": 2},
        "crew": 12,
    },
    "atlas_hauler": {
        "name_key": "fleet_ship_atlas_hauler",
        "description_key": "fleet_ship_atlas_hauler_desc",
        "role": "cargo",
        "required_shipyard_level": 4,
        "requirements": {
            "buildings": {"orbital_shipyard": 4},
            "research": {"storage_tech": 5, "mining_tech": 4},
        },
        "build_cost": {"metal": 7500, "crystal": 7500, "fuel_cells": 750},
        "build_seconds": 200,
        "score_value": 12000,
        "speed": 7500,
        "cargo": 25000,
        "fuel": 50,
        "attack": 5,
        "shield": 25,
        "hull": 1200,
        "rapid_fire_targets": {},
        "crew": 8,
    },
    "deep_vault_ark": {
        "name_key": "fleet_ship_deep_vault_ark",
        "description_key": "fleet_ship_deep_vault_ark_desc",
        "role": "cargo",
        "required_shipyard_level": 6,
        "requirements": {
            "buildings": {"orbital_shipyard": 6, "metal_storage": 5, "crystal_storage": 5},
            "research": {"storage_tech": 8, "mining_tech": 6, "fuel_efficiency": 5},
        },
        "build_cost": {"metal": 50000, "crystal": 50000, "fuel_cells": 25000},
        "build_seconds": 260,
        "score_value": 50000,
        "speed": 500,
        "cargo": 100000,
        "fuel": 120,
        "attack": 1,
        "shield": 10,
        "hull": 800,
        "rapid_fire_targets": {},
        "crew": 12,
    },
    "harvest_reclaimer": {
        "name_key": "fleet_ship_harvest_reclaimer",
        "description_key": "fleet_ship_harvest_reclaimer_desc",
        "role": "recycle",
        "required_shipyard_level": 5,
        "requirements": {
            "buildings": {"orbital_shipyard": 5},
            "research": {"drone_tech": 5, "fuel_efficiency": 4},
        },
        "build_cost": {"metal": 12500, "crystal": 7500, "fuel_cells": 7500},
        "build_seconds": 220,
        "score_value": 16000,
        "speed": 2000,
        "cargo": 20000,
        "fuel": 300,
        "attack": 1,
        "shield": 10,
        "hull": 1600,
        "rapid_fire_targets": {},
        "crew": 10,
    },
    "seed_ark": {
        "name_key": "fleet_ship_seed_ark",
        "description_key": "fleet_ship_seed_ark_desc",
        "role": "colony",
        "required_shipyard_level": 6,
        "requirements": {
            "buildings": {"orbital_shipyard": 6, "command_center": 3},
            "research": {"navigation_tech": 6, "storage_tech": 5},
        },
        "build_cost": {"metal": 62500, "crystal": 37500, "fuel_cells": 60000},
        "build_seconds": 260,
        "score_value": 80000,
        "speed": 1500,
        "cargo": 5000,
        "fuel": 200,
        "attack": 10,
        "shield": 50,
        "hull": 3000,
        "rapid_fire_targets": {},
        "crew": 50,
    },
    "eclipse_runner": {
        "name_key": "fleet_ship_eclipse_runner",
        "description_key": "fleet_ship_eclipse_runner_desc",
        "role": "expedition",
        "required_shipyard_level": 7,
        "build_cost": {"metal": 15000, "crystal": 10000, "fuel_cells": 62},
        "build_seconds": 260,
        "score_value": 20000,
        "speed": 6000,
        "cargo": 5000,
        "fuel": 40,
        "attack": 25,
        "shield": 40,
        "hull": 2000,
        "rapid_fire_targets": {"spark_drone": 2},
        "crew": 8,
        "phase2_only": True,
        "requirements": {
            "buildings": {"orbital_shipyard": 7},
            "research": {"engine_tech": 7, "shield_tech": 5},
        },
    },
}


def ship_icon_filename(ship_key: str) -> str:
    return f"{canonical_ship_key(ship_key)}.png"


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


def ship_rapid_fire_targets(ship_key: str) -> Dict[str, int]:
    """``rapid_fire_targets`` from ship defs — target key → multiplier (values >= 2)."""
    spec = get_ship(ship_key) or {}
    raw = spec.get("rapid_fire_targets") or {}
    out: Dict[str, int] = {}
    if not isinstance(raw, dict):
        return out
    for target_key, value in raw.items():
        key = canonical_ship_key(str(target_key))
        mult = int(value or 0)
        if mult >= 2:
            out[key] = mult
    return out


def ship_rapid_fire_multiplier(ship_key: str, target_key: str) -> int:
    """Rapid-fire multiplier vs a target hull key (1 = no bonus shots)."""
    targets = ship_rapid_fire_targets(ship_key)
    mult = int(targets.get(canonical_ship_key(target_key), 0) or 0)
    return mult if mult >= 2 else 1


def rapid_fire_bonus_shot_chance(rapid_fire_multiplier: int) -> float:
    """Probability of firing again after a hit when multiplier >= 2: (mult - 1) / mult."""
    mult = max(1, int(rapid_fire_multiplier))
    if mult < 2:
        return 0.0
    return (mult - 1) / mult


def ship_score_value(ship_key: str) -> int:
    """Ranking / combat empire value per hull (falls back to build cost)."""
    from .combat_models import combat_stats_for_ship

    stats = combat_stats_for_ship(ship_key)
    if stats is None:
        return 0
    return int(stats.score_value)


def ship_combat_stats(ship_key: str):
    """Combat profile for resolver — see ``game.combat_models``."""
    from .combat_models import combat_stats_for_ship

    return combat_stats_for_ship(ship_key)


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
