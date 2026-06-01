"""Planet-scoped defense unit definitions — Genesis Colonies registry (no combat resolver)."""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List

DEFENSE_ORDER: List[str] = [
    "sentinel_turret",
    "plasma_arc",
    "ion_bastion",
    "flak_array",
    "pulse_barrier",
    "orbital_shield",
]

ACTIVE_DEFENSE_KEYS: FrozenSet[str] = frozenset(DEFENSE_ORDER)

DEFENSES: Dict[str, Dict[str, Any]] = {
    "sentinel_turret": {
        "name_key": "defense_sentinel_turret",
        "description_key": "defense_sentinel_turret_desc",
        "role": "turret",
        "required_defense_factory_level": 1,
        "requirements": {"buildings": {"defense_factory": 1}, "research": {"weapon_tech": 2}},
        "build_cost": {"metal": 200, "crystal": 100},
        "build_seconds": 30,
        "score_value": 300,
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
        "build_cost": {"metal": 2000, "crystal": 500},
        "build_seconds": 120,
        "score_value": 2500,
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
        "build_cost": {"metal": 5000, "crystal": 3000},
        "build_seconds": 300,
        "score_value": 8000,
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
        "build_cost": {"metal": 15000, "crystal": 8000},
        "build_seconds": 600,
        "score_value": 23000,
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
        "build_cost": {"metal": 10000, "crystal": 10000},
        "build_seconds": 900,
        "score_value": 20000,
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
        "build_cost": {"metal": 50000, "crystal": 50000},
        "build_seconds": 3600,
        "score_value": 100000,
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


def unit_build_cost(defense_key: str) -> Dict[str, int]:
    spec = get_defense(defense_key) or {}
    raw = spec.get("build_cost") or {}
    return {
        "metal": max(0, int(raw.get("metal") or 0)),
        "crystal": max(0, int(raw.get("crystal") or 0)),
    }


def defense_score_value(defense_key: str) -> int:
    """Ranking points per stored unit (Empire score: amount × score_value)."""
    from .combat_models import combat_stats_for_defense

    stats = combat_stats_for_defense(defense_key)
    if stats is not None:
        return int(stats.score_value)
    spec = get_defense(defense_key) or {}
    raw = spec.get("score_value")
    if raw is not None:
        return max(0, int(raw))
    cost = unit_build_cost(defense_key)
    return max(0, int(cost.get("metal") or 0) + int(cost.get("crystal") or 0))


def defense_combat_stats(defense_key: str):
    """Combat profile for resolver — see ``game.combat_models``."""
    from .combat_models import combat_stats_for_defense

    return combat_stats_for_defense(defense_key)


def defense_defs_for_client() -> List[Dict[str, Any]]:
    return [{"key": key, **DEFENSES[key]} for key in DEFENSE_ORDER if key in DEFENSES]


def defense_icon_filename(defense_key: str) -> str:
    return f"{str(defense_key or '').strip()}.svg"


def defense_icon_static_path(defense_key: str) -> str:
    return f"/static/img/defense/{defense_icon_filename(defense_key)}"
