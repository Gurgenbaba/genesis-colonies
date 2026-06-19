"""
GC-540 — Weighted container loot pools (speedgame-tuned).
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

LootEntry = Dict[str, Any]

LOOT_POOL_SETTINGS_KEY = "inventory_loot_pool_overrides"

# reward_type: resource | item | booster | ship | defense
LOOT_POOLS: Dict[str, List[LootEntry]] = {
    "container_basic": [
        {"weight": 22, "reward_type": "resource", "reward_key": "metal", "min_amount": 10_000, "max_amount": 50_000},
        {"weight": 22, "reward_type": "resource", "reward_key": "crystal", "min_amount": 10_000, "max_amount": 50_000},
        {"weight": 16, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 100, "max_amount": 500},
        {"weight": 10, "reward_type": "ship", "reward_key": "spark_drone", "min_amount": 1, "max_amount": 3},
        {"weight": 8, "reward_type": "ship", "reward_key": "mule_courier", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "defense", "reward_key": "sentinel_turret", "min_amount": 1, "max_amount": 5},
        {"weight": 6, "reward_type": "item", "reward_key": "fragment_dna_common", "min_amount": 1, "max_amount": 3},
        {"weight": 5, "reward_type": "booster", "reward_key": "booster_build_5m", "min_amount": 1, "max_amount": 1},
        {"weight": 3, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_rare": [
        {"weight": 18, "reward_type": "resource", "reward_key": "metal", "min_amount": 100_000, "max_amount": 500_000},
        {"weight": 18, "reward_type": "resource", "reward_key": "crystal", "min_amount": 100_000, "max_amount": 500_000},
        {"weight": 12, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 1_000, "max_amount": 5_000},
        {"weight": 10, "reward_type": "ship", "reward_key": "veil_probe", "min_amount": 2, "max_amount": 6},
        {"weight": 10, "reward_type": "ship", "reward_key": "falcon_interceptor", "min_amount": 1, "max_amount": 3},
        {"weight": 8, "reward_type": "defense", "reward_key": "plasma_arc", "min_amount": 2, "max_amount": 8},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_build_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 6, "reward_type": "booster", "reward_key": "booster_research_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 5, "reward_type": "item", "reward_key": "fragment_dna_rare", "min_amount": 1, "max_amount": 2},
        {"weight": 4, "reward_type": "item", "reward_key": "research_data_mining", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "container_epic", "min_amount": 1, "max_amount": 1},
    ],
    "container_epic": [
        {"weight": 15, "reward_type": "resource", "reward_key": "metal", "min_amount": 500_000, "max_amount": 2_000_000},
        {"weight": 15, "reward_type": "resource", "reward_key": "crystal", "min_amount": 500_000, "max_amount": 2_000_000},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 5_000, "max_amount": 20_000},
        {"weight": 10, "reward_type": "ship", "reward_key": "ironclad_frigate", "min_amount": 1, "max_amount": 3},
        {"weight": 8, "reward_type": "ship", "reward_key": "atlas_hauler", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "defense", "reward_key": "ion_bastion", "min_amount": 3, "max_amount": 12},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_build_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_research_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 6, "reward_type": "booster", "reward_key": "booster_shipyard_1h", "min_amount": 1, "max_amount": 1},
        {"weight": 5, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 2},
        {"weight": 4, "reward_type": "item", "reward_key": "evo_planet_xp_5000", "min_amount": 1, "max_amount": 1},
        {"weight": 3, "reward_type": "item", "reward_key": "fragment_alien", "min_amount": 1, "max_amount": 2},
        {"weight": 2, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
    ],
    "container_relic": [
        {"weight": 14, "reward_type": "resource", "reward_key": "metal", "min_amount": 2_000_000, "max_amount": 10_000_000},
        {"weight": 14, "reward_type": "resource", "reward_key": "crystal", "min_amount": 2_000_000, "max_amount": 10_000_000},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 20_000, "max_amount": 100_000},
        {"weight": 9, "reward_type": "ship", "reward_key": "harvest_reclaimer", "min_amount": 1, "max_amount": 3},
        {"weight": 7, "reward_type": "ship", "reward_key": "seed_ark", "min_amount": 1, "max_amount": 1},
        {"weight": 8, "reward_type": "defense", "reward_key": "orbital_shield", "min_amount": 2, "max_amount": 8},
        {"weight": 8, "reward_type": "defense", "reward_key": "pulse_barrier", "min_amount": 3, "max_amount": 10},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_build_24h", "min_amount": 1, "max_amount": 1},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_research_24h", "min_amount": 1, "max_amount": 1},
        {"weight": 6, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 5, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 3},
        {"weight": 5, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
    ],
    "container_wreckage": [
        {"weight": 25, "reward_type": "resource", "reward_key": "metal", "min_amount": 50_000, "max_amount": 250_000},
        {"weight": 20, "reward_type": "resource", "reward_key": "crystal", "min_amount": 25_000, "max_amount": 150_000},
        {"weight": 15, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 500, "max_amount": 2_500},
        {"weight": 12, "reward_type": "ship", "reward_key": "spark_drone", "min_amount": 2, "max_amount": 8},
        {"weight": 10, "reward_type": "ship", "reward_key": "solar_skiff", "min_amount": 1, "max_amount": 4},
        {"weight": 8, "reward_type": "item", "reward_key": "fragment_wreck_reactor", "min_amount": 1, "max_amount": 3},
        {"weight": 6, "reward_type": "item", "reward_key": "fragment_wreck_hull", "min_amount": 1, "max_amount": 3},
        {"weight": 4, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_research_cache": [
        {"weight": 20, "reward_type": "resource", "reward_key": "crystal", "min_amount": 200_000, "max_amount": 800_000},
        {"weight": 15, "reward_type": "booster", "reward_key": "booster_research_15m", "min_amount": 1, "max_amount": 3},
        {"weight": 12, "reward_type": "booster", "reward_key": "booster_research_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 12, "reward_type": "item", "reward_key": "research_data_energy", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "item", "reward_key": "research_data_weapons", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "item", "reward_key": "fragment_dna_rare", "min_amount": 1, "max_amount": 3},
        {"weight": 8, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 2},
        {"weight": 3, "reward_type": "item", "reward_key": "research_instant_level", "min_amount": 1, "max_amount": 1},
    ],
    "container_military_cache": [
        {"weight": 18, "reward_type": "resource", "reward_key": "metal", "min_amount": 250_000, "max_amount": 1_000_000},
        {"weight": 14, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 2_000, "max_amount": 10_000},
        {"weight": 14, "reward_type": "defense", "reward_key": "flak_array", "min_amount": 4, "max_amount": 15},
        {"weight": 12, "reward_type": "defense", "reward_key": "sentinel_turret", "min_amount": 5, "max_amount": 20},
        {"weight": 10, "reward_type": "ship", "reward_key": "ironclad_frigate", "min_amount": 1, "max_amount": 4},
        {"weight": 10, "reward_type": "ship", "reward_key": "falcon_interceptor", "min_amount": 2, "max_amount": 6},
        {"weight": 8, "reward_type": "booster", "reward_key": "booster_build_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 6, "reward_type": "booster", "reward_key": "booster_shipyard_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "item", "reward_key": "fleet_computer", "min_amount": 1, "max_amount": 1},
    ],
    "container_event_special": [
        {"weight": 14, "reward_type": "resource", "reward_key": "metal", "min_amount": 300_000, "max_amount": 1_500_000},
        {"weight": 14, "reward_type": "resource", "reward_key": "crystal", "min_amount": 300_000, "max_amount": 1_500_000},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 3_000, "max_amount": 15_000},
        {"weight": 9, "reward_type": "ship", "reward_key": "atlas_hauler", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "defense", "reward_key": "plasma_arc", "min_amount": 3, "max_amount": 10},
        {"weight": 8, "reward_type": "booster", "reward_key": "booster_production_50", "min_amount": 1, "max_amount": 1},
        {"weight": 7, "reward_type": "item", "reward_key": "expo_alien_relic", "min_amount": 1, "max_amount": 1},
        {"weight": 6, "reward_type": "item", "reward_key": "fragment_dna_epic", "min_amount": 1, "max_amount": 2},
        {"weight": 5, "reward_type": "item", "reward_key": "fleet_hyperdrive_module", "min_amount": 1, "max_amount": 1},
        {"weight": 4, "reward_type": "item", "reward_key": "placeholder_special_item", "min_amount": 1, "max_amount": 1},
        {"weight": 3, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "mythic_ancient_nexus", "min_amount": 1, "max_amount": 1},
    ],
    # GC-402E — expedition jackpot containers (minimal pools; tune later).
    "container_mythic": [
        {"weight": 40, "reward_type": "resource", "reward_key": "metal", "min_amount": 5_000_000, "max_amount": 25_000_000},
        {"weight": 35, "reward_type": "resource", "reward_key": "crystal", "min_amount": 3_000_000, "max_amount": 15_000_000},
        {"weight": 15, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
    ],
    "container_ancient_relic": [
        {"weight": 35, "reward_type": "resource", "reward_key": "metal", "min_amount": 10_000_000, "max_amount": 50_000_000},
        {"weight": 30, "reward_type": "resource", "reward_key": "crystal", "min_amount": 8_000_000, "max_amount": 40_000_000},
        {"weight": 20, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 15, "reward_type": "item", "reward_key": "fragment_quantum", "min_amount": 1, "max_amount": 2},
    ],
    "container_void_artifact": [
        {"weight": 30, "reward_type": "resource", "reward_key": "metal", "min_amount": 25_000_000, "max_amount": 100_000_000},
        {"weight": 25, "reward_type": "resource", "reward_key": "crystal", "min_amount": 20_000_000, "max_amount": 80_000_000},
        {"weight": 20, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 3},
        {"weight": 15, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
        {"weight": 10, "reward_type": "item", "reward_key": "expo_alien_relic", "min_amount": 1, "max_amount": 1},
    ],
}


def _parse_pool_overrides_raw(raw: Any) -> Dict[str, List[LootEntry]]:
    if not raw:
        return {}
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(parsed, dict):
        return {}
    out: Dict[str, List[LootEntry]] = {}
    for key, entries in parsed.items():
        if not isinstance(key, str) or not isinstance(entries, list):
            continue
        out[key] = [dict(e) for e in entries if isinstance(e, dict)]
    return out


def load_pool_overrides(conn=None) -> Dict[str, List[LootEntry]]:
    from .models import get_game_settings

    settings = get_game_settings(conn) or {}
    return _parse_pool_overrides_raw(settings.get(LOOT_POOL_SETTINGS_KEY))


def save_pool_overrides(overrides: Dict[str, List[LootEntry]]) -> None:
    from .models import save_game_settings

    payload = {k: v for k, v in overrides.items() if v}
    save_game_settings({LOOT_POOL_SETTINGS_KEY: json.dumps(payload, separators=(",", ":"))})


def get_loot_pools(conn=None) -> Dict[str, List[LootEntry]]:
    """Effective loot pools: code defaults merged with admin overrides."""
    pools = {k: deepcopy(v) for k, v in LOOT_POOLS.items()}
    for key, entries in load_pool_overrides(conn).items():
        if key in pools and entries:
            pools[key] = deepcopy(entries)
    return pools


def set_container_pool_override(container_key: str, entries: List[LootEntry]) -> None:
    overrides = load_pool_overrides()
    overrides[str(container_key)] = deepcopy(entries)
    save_pool_overrides(overrides)


def clear_container_pool_override(container_key: str) -> None:
    overrides = load_pool_overrides()
    key = str(container_key)
    if key not in overrides:
        return
    del overrides[key]
    save_pool_overrides(overrides)


def pool_has_override(container_key: str, conn=None) -> bool:
    return str(container_key) in load_pool_overrides(conn)
