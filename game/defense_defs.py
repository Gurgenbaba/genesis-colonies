"""Planet-scoped defense unit definitions — Genesis Colonies registry (no combat resolver)."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List

DEFENSE_ORDER: List[str] = [
    "slug_launcher",
    "sentinel_turret",
    "plasma_arc",
    "ion_bastion",
    "flak_array",
    "pulse_barrier",
    "orbital_shield",
]

ACTIVE_DEFENSE_KEYS: FrozenSet[str] = frozenset(DEFENSE_ORDER)

DEFENSES: Dict[str, Dict[str, Any]] = {
    "slug_launcher": {
        "name_key": "defense_slug_launcher",
        "description_key": "defense_slug_launcher_desc",
        "role": "turret",
        "required_defense_factory_level": 1,
        "requirements": {"buildings": {"defense_factory": 1}, "research": {}},
        "build_cost": {"metal": 2000, "crystal": 0, "fuel_cells": 0},
        "build_seconds": 20,
        "attack": 4,
        "shield": 0,
        "hull": 120,
        "rapid_fire_targets": {
            "spark_drone": 3,
            "veil_probe": 4,
            "mule_courier": 2,
        },
    },
    "sentinel_turret": {
        "name_key": "defense_sentinel_turret",
        "description_key": "defense_sentinel_turret_desc",
        "role": "turret",
        "required_defense_factory_level": 1,
        "requirements": {"buildings": {"defense_factory": 1}, "research": {"weapon_tech": 2}},
        "build_cost": {"metal": 250, "crystal": 125, "fuel_cells": 0},
        "build_seconds": 30,
        "attack": 5,
        "shield": 0,
        "hull": 200,
        "rapid_fire_targets": {"spark_drone": 2, "veil_probe": 3},
    },
    "plasma_arc": {
        "name_key": "defense_plasma_arc",
        "description_key": "defense_plasma_arc_desc",
        "role": "turret",
        "required_defense_factory_level": 2,
        "requirements": {
            "buildings": {"defense_factory": 2},
            "research": {"weapon_tech": 4},
        },
        "build_cost": {"metal": 2500, "crystal": 625, "fuel_cells": 750},
        "build_seconds": 120,
        "attack": 25,
        "shield": 0,
        "hull": 500,
        "rapid_fire_targets": {"falcon_interceptor": 2, "mule_courier": 2},
    },
    "ion_bastion": {
        "name_key": "defense_ion_bastion",
        "description_key": "defense_ion_bastion_desc",
        "role": "turret",
        "required_defense_factory_level": 4,
        "requirements": {
            "buildings": {"defense_factory": 4},
            "research": {"weapon_tech": 6, "armor_tech": 3},
        },
        "build_cost": {"metal": 6250, "crystal": 3750, "fuel_cells": 1500},
        "build_seconds": 300,
        "attack": 100,
        "shield": 0,
        "hull": 800,
        "rapid_fire_targets": {"ironclad_frigate": 2, "atlas_hauler": 2},
    },
    "flak_array": {
        "name_key": "defense_flak_array",
        "description_key": "defense_flak_array_desc",
        "role": "turret",
        "required_defense_factory_level": 5,
        "requirements": {
            "buildings": {"defense_factory": 5, "radar_array": 1},
            "research": {"weapon_tech": 8, "armor_tech": 4},
        },
        "build_cost": {"metal": 18750, "crystal": 10000, "fuel_cells": 2500},
        "build_seconds": 600,
        "attack": 250,
        "shield": 0,
        "hull": 1200,
        "rapid_fire_targets": {
            "spark_drone": 5,
            "veil_probe": 5,
            "falcon_interceptor": 4,
            "mule_courier": 3,
        },
    },
    "pulse_barrier": {
        "name_key": "defense_pulse_barrier",
        "description_key": "defense_pulse_barrier_desc",
        "role": "shield",
        "required_defense_factory_level": 6,
        "requirements": {
            "buildings": {"defense_factory": 6, "shield_generator": 1},
            "research": {"shield_tech": 6, "armor_tech": 3},
        },
        "build_cost": {"metal": 12500, "crystal": 12500, "fuel_cells": 8500},
        "build_seconds": 900,
        "attack": 1,
        "shield": 500,
        "hull": 2000,
        "rapid_fire_targets": {},
    },
    "orbital_shield": {
        "name_key": "defense_orbital_shield",
        "description_key": "defense_orbital_shield_desc",
        "role": "shield",
        "required_defense_factory_level": 8,
        "requirements": {
            "buildings": {"defense_factory": 8, "shield_generator": 3},
            "research": {"shield_tech": 8, "energy_tech": 5},
        },
        "build_cost": {"metal": 62500, "crystal": 62500, "fuel_cells": 25000},
        "build_seconds": 3600,
        "attack": 0,
        "shield": 2000,
        "hull": 5000,
        "rapid_fire_targets": {},
    },
}


def is_known_defense_key(defense_key: str) -> bool:
    return str(defense_key or "").strip() in DEFENSES


def all_defense_keys() -> FrozenSet[str]:
    return ACTIVE_DEFENSE_KEYS


def get_defense(defense_key: str) -> Dict[str, Any] | None:
    return DEFENSES.get(str(defense_key or "").strip())


def defense_rapid_fire_targets(defense_key: str) -> Dict[str, int]:
    """``rapid_fire_targets`` from defense defs — target key → multiplier (values >= 2)."""
    spec = get_defense(defense_key) or {}
    raw = spec.get("rapid_fire_targets") or {}
    out: Dict[str, int] = {}
    if not isinstance(raw, dict):
        return out
    for target_key, value in raw.items():
        key = str(target_key or "").strip()
        mult = int(value or 0)
        if mult >= 2:
            out[key] = mult
    return out


def defense_rapid_fire_multiplier(defense_key: str, target_key: str) -> int:
    """Rapid-fire multiplier vs a target unit key (1 = no bonus shots)."""
    targets = defense_rapid_fire_targets(defense_key)
    key = str(target_key or "").strip()
    mult = int(targets.get(key, 0) or 0)
    return mult if mult >= 2 else 1


def unit_build_cost(defense_key: str) -> Dict[str, int]:
    spec = get_defense(defense_key) or {}
    raw = spec.get("build_cost") or {}
    return {
        "metal": max(0, int(raw.get("metal") or 0)),
        "crystal": max(0, int(raw.get("crystal") or 0)),
        "fuel_cells": max(0, int(raw.get("fuel_cells") or 0)),
    }


def defense_score_value(defense_key: str) -> int:
    """Wealth score per stored unit — canonical resource_score from build_cost."""
    from .resource_score import score_from_cost_dict

    return score_from_cost_dict(unit_build_cost(str(defense_key)))


def defense_combat_stats(defense_key: str):
    """Combat profile for resolver — see ``game.combat_models``."""
    from .combat_models import combat_stats_for_defense

    return combat_stats_for_defense(defense_key)


def rapid_fire_bonus_shot_chance(rapid_fire_multiplier: int) -> float:
    """Shared RF chance formula — see ``fleet_defs.rapid_fire_bonus_shot_chance``."""
    from .fleet_defs import rapid_fire_bonus_shot_chance as _chance

    return _chance(rapid_fire_multiplier)


def defense_display_name(defense_key: str, *, locale: str | None = None) -> str:
    """Player-facing defense label — same source as defense UI (`name_key` + i18n)."""
    from .i18n import tr
    from .mail import humanize_identifier_key

    key = str(defense_key or "").strip()
    spec = get_defense(key) or {}
    name_key = str(spec.get("name_key") or f"defense_{key}").strip()
    return tr(name_key, humanize_identifier_key(key), locale=locale)


def defense_defs_for_client() -> List[Dict[str, Any]]:
    return [{"key": key, **DEFENSES[key]} for key in DEFENSE_ORDER if key in DEFENSES]


def defense_icon_filename(defense_key: str) -> str:
    return f"{str(defense_key or '').strip()}.png"


def defense_icon_static_path(defense_key: str) -> str:
    return f"/static/img/defense/{defense_icon_filename(defense_key)}"
