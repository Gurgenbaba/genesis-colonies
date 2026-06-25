"""
GC-540 / GC-864 — Container loot pools (meta / progression only).

Containers grant boosters, fragments, items, and nested containers — never
direct resources, ships, or defense units.
"""

from __future__ import annotations

import json
import random
from copy import deepcopy
from typing import Any, Dict, List, Optional

LootEntry = Dict[str, Any]

LOOT_POOL_SETTINGS_KEY = "inventory_loot_pool_overrides"

# GC-864 — allowed container reward types (no economy inflation).
META_LOOT_REWARD_TYPES = frozenset({"item", "booster"})
FORBIDDEN_LOOT_REWARD_TYPES = frozenset({"resource", "ship", "defense"})

# reward_type: item | booster only
LOOT_POOLS: Dict[str, List[LootEntry]] = {
    "container_basic": [
        {"weight": 30, "reward_type": "booster", "reward_key": "booster_build_5m", "min_amount": 1, "max_amount": 1},
        {"weight": 28, "reward_type": "item", "reward_key": "fragment_dna_common", "min_amount": 1, "max_amount": 2},
        {"weight": 25, "reward_type": "booster", "reward_key": "booster_research_5m", "min_amount": 1, "max_amount": 1},
        {"weight": 15, "reward_type": "item", "reward_key": "research_data_energy", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_rare": [
        {"weight": 20, "reward_type": "booster", "reward_key": "booster_build_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 18, "reward_type": "booster", "reward_key": "booster_research_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 25, "reward_type": "item", "reward_key": "fragment_dna_rare", "min_amount": 1, "max_amount": 2},
        {"weight": 15, "reward_type": "item", "reward_key": "research_data_mining", "min_amount": 1, "max_amount": 1},
        {"weight": 10, "reward_type": "item", "reward_key": "research_data_energy", "min_amount": 1, "max_amount": 1},
        {"weight": 10, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "container_epic", "min_amount": 1, "max_amount": 1},
    ],
    "container_epic": [
        {"weight": 18, "reward_type": "booster", "reward_key": "booster_build_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 18, "reward_type": "booster", "reward_key": "booster_research_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 14, "reward_type": "booster", "reward_key": "booster_shipyard_1h", "min_amount": 1, "max_amount": 1},
        {"weight": 12, "reward_type": "item", "reward_key": "fragment_alien", "min_amount": 1, "max_amount": 2},
        {"weight": 12, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "item", "reward_key": "evo_planet_xp_5000", "min_amount": 1, "max_amount": 1},
        {"weight": 6, "reward_type": "item", "reward_key": "fragment_dna_epic", "min_amount": 1, "max_amount": 1},
        {"weight": 1, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
    ],
    "container_relic": [
        {"weight": 16, "reward_type": "booster", "reward_key": "booster_build_24h", "min_amount": 1, "max_amount": 1},
        {"weight": 16, "reward_type": "booster", "reward_key": "booster_research_24h", "min_amount": 1, "max_amount": 1},
        {"weight": 18, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 20, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 3},
        {"weight": 14, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
        {"weight": 12, "reward_type": "item", "reward_key": "fragment_quantum", "min_amount": 1, "max_amount": 2},
        {"weight": 4, "reward_type": "item", "reward_key": "fragment_dna_epic", "min_amount": 1, "max_amount": 1},
    ],
    "container_wreckage": [
        {"weight": 35, "reward_type": "item", "reward_key": "fragment_wreck_reactor", "min_amount": 1, "max_amount": 3},
        {"weight": 35, "reward_type": "item", "reward_key": "fragment_wreck_hull", "min_amount": 1, "max_amount": 3},
        {"weight": 18, "reward_type": "item", "reward_key": "fragment_dna_common", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "booster", "reward_key": "booster_build_5m", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_research_cache": [
        {"weight": 24, "reward_type": "booster", "reward_key": "booster_research_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 18, "reward_type": "booster", "reward_key": "booster_research_1h", "min_amount": 1, "max_amount": 1},
        {"weight": 16, "reward_type": "item", "reward_key": "research_data_energy", "min_amount": 1, "max_amount": 1},
        {"weight": 14, "reward_type": "item", "reward_key": "research_data_weapons", "min_amount": 1, "max_amount": 1},
        {"weight": 14, "reward_type": "item", "reward_key": "fragment_dna_rare", "min_amount": 1, "max_amount": 2},
        {"weight": 12, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "research_instant_level", "min_amount": 1, "max_amount": 1},
    ],
    "container_military_cache": [
        {"weight": 22, "reward_type": "booster", "reward_key": "booster_build_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 20, "reward_type": "booster", "reward_key": "booster_shipyard_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 18, "reward_type": "booster", "reward_key": "booster_shipyard_1h", "min_amount": 1, "max_amount": 1},
        {"weight": 17, "reward_type": "item", "reward_key": "fleet_computer", "min_amount": 1, "max_amount": 1},
        {"weight": 12, "reward_type": "item", "reward_key": "fleet_hyperdrive_module", "min_amount": 1, "max_amount": 1},
        {"weight": 11, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 1},
    ],
    "container_event_special": [
        {"weight": 18, "reward_type": "booster", "reward_key": "booster_production_50", "min_amount": 1, "max_amount": 1},
        {"weight": 18, "reward_type": "item", "reward_key": "expo_alien_relic", "min_amount": 1, "max_amount": 1},
        {"weight": 14, "reward_type": "item", "reward_key": "fragment_dna_epic", "min_amount": 1, "max_amount": 1},
        {"weight": 14, "reward_type": "item", "reward_key": "fleet_hyperdrive_module", "min_amount": 1, "max_amount": 1},
        {"weight": 12, "reward_type": "item", "reward_key": "placeholder_special_item", "min_amount": 1, "max_amount": 1},
        {"weight": 10, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 1},
        {"weight": 10, "reward_type": "booster", "reward_key": "booster_build_1h", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "mythic_ancient_nexus", "min_amount": 1, "max_amount": 1},
    ],
    "container_mythic": [
        {"weight": 45, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 2},
        {"weight": 30, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 15, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
        {"weight": 8, "reward_type": "item", "reward_key": "fragment_quantum", "min_amount": 1, "max_amount": 2},
        {"weight": 2, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
    ],
    "container_ancient_relic": [
        {"weight": 40, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 35, "reward_type": "item", "reward_key": "fragment_quantum", "min_amount": 1, "max_amount": 2},
        {"weight": 17, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
    ],
    "container_void_artifact": [
        {"weight": 35, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 3},
        {"weight": 25, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
        {"weight": 20, "reward_type": "item", "reward_key": "expo_alien_relic", "min_amount": 1, "max_amount": 1},
        {"weight": 12, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "item", "reward_key": "fragment_quantum", "min_amount": 1, "max_amount": 2},
    ],
}


def is_meta_loot_reward_type(reward_type: str) -> bool:
    return str(reward_type or "").strip().lower() in META_LOOT_REWARD_TYPES


def is_forbidden_loot_reward_type(reward_type: str) -> bool:
    return str(reward_type or "").strip().lower() in FORBIDDEN_LOOT_REWARD_TYPES


def sanitize_loot_pool(pool: List[LootEntry]) -> List[LootEntry]:
    """Strip economy reward types (resource / ship / defense)."""
    return [
        dict(e)
        for e in pool
        if is_meta_loot_reward_type(str(e.get("reward_type") or ""))
        and int(e.get("weight") or 0) > 0
    ]


def pool_has_forbidden_rewards(pool: List[LootEntry]) -> bool:
    return any(is_forbidden_loot_reward_type(str(e.get("reward_type") or "")) for e in pool)


def is_dynamic_loot_entry(entry: LootEntry) -> bool:
    """Containers no longer use mine/fleet-scaled economy entries."""
    return False


def is_scaled_resource_loot(entry: LootEntry) -> bool:
    return False


def is_fuel_stock_scaled_loot(entry: LootEntry) -> bool:
    return False


def is_fleet_scaled_ship_loot(entry: LootEntry) -> bool:
    return False


def is_defense_scaled_loot(entry: LootEntry) -> bool:
    return False


def is_diminishing_unit_loot(entry: LootEntry) -> bool:
    return False


def container_resource_multiplier(container_key: str) -> float:
    return 1.0


def resolve_loot_entry_amount(
    entry: LootEntry,
    *,
    user_id: int,
    container_key: str,
    conn,
    rng: random.Random,
    loot_context: Optional[Dict[str, Any]] = None,
) -> int:
    """Resolve amount for item/booster pool entries."""
    _ = user_id, container_key, conn, loot_context
    lo = int(entry.get("min_amount") or 1)
    hi = int(entry.get("max_amount") or lo)
    if hi < lo:
        hi = lo
    return max(1, int(rng.randint(lo, hi)))


def build_loot_roll_context(user_id: int, container_key: str, *, conn) -> Dict[str, Any]:
    return {
        "user_id": int(user_id),
        "container_key": str(container_key),
        "conn": conn,
    }


def scaled_loot_amount_label(
    entry: LootEntry,
    *,
    container_key: str,
    amount: Optional[int] = None,
) -> str:
    lo = int(entry.get("min_amount") or 1)
    hi = int(entry.get("max_amount") or lo)
    if amount is not None:
        return str(amount)
    if lo == hi:
        return str(lo)
    return f"{lo}–{hi}"


def scaled_resource_amount_label(
    entry: LootEntry,
    *,
    container_key: str,
    amount: Optional[int] = None,
) -> str:
    return scaled_loot_amount_label(entry, container_key=container_key, amount=amount)


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
    """Effective loot pools: defaults + admin overrides, meta-only."""
    pools = {k: deepcopy(v) for k, v in LOOT_POOLS.items()}
    for key, entries in load_pool_overrides(conn).items():
        if key in pools and entries:
            pools[key] = deepcopy(entries)
    return {k: sanitize_loot_pool(v) for k, v in pools.items() if sanitize_loot_pool(v)}


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
