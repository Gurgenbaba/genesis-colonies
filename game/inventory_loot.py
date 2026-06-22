"""
GC-540 — Weighted container loot pools (speedgame-tuned).

Resource drops scale to empire max mine level: half of that mine's hourly output
(× container tier multiplier). Fixed min/max only for legacy admin overrides.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

LootEntry = Dict[str, Any]

LOOT_POOL_SETTINGS_KEY = "inventory_loot_pool_overrides"

# Discord feedback: reward ≈ 50 % of 1 h production at highest empire mine level.
LOOT_BASE_PRODUCTION_HOURS = 0.5
LOOT_FALLBACK_MINE_LEVEL = 1

RESOURCE_MINE_KEYS: Dict[str, str] = {
    "metal": "metal_mine",
    "crystal": "crystal_mine",
    "fuel_cells": "fuel_cell_plant",
}

# Relative value between container tiers (applied on top of LOOT_BASE_PRODUCTION_HOURS).
CONTAINER_RESOURCE_MULTIPLIER: Dict[str, float] = {
    "container_basic": 1.0,
    "container_wreckage": 1.5,
    "container_rare": 2.5,
    "container_research_cache": 2.0,
    "container_military_cache": 2.0,
    "container_epic": 5.0,
    "container_relic": 10.0,
    "container_event_special": 3.0,
    "container_mythic": 15.0,
    "container_ancient_relic": 25.0,
    "container_void_artifact": 50.0,
}

# reward_type: resource | item | booster | ship | defense
# Resource entries: production_hours (default LOOT_BASE_PRODUCTION_HOURS) — no fixed min/max.
LOOT_POOLS: Dict[str, List[LootEntry]] = {
    "container_basic": [
        {"weight": 22, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 22, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 16, "reward_type": "resource", "reward_key": "fuel_cells", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 10, "reward_type": "ship", "reward_key": "spark_drone", "min_amount": 1, "max_amount": 3},
        {"weight": 8, "reward_type": "ship", "reward_key": "mule_courier", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "defense", "reward_key": "sentinel_turret", "min_amount": 1, "max_amount": 5},
        {"weight": 6, "reward_type": "item", "reward_key": "fragment_dna_common", "min_amount": 1, "max_amount": 3},
        {"weight": 5, "reward_type": "booster", "reward_key": "booster_build_5m", "min_amount": 1, "max_amount": 1},
        {"weight": 3, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_rare": [
        {"weight": 18, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 18, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 12, "reward_type": "resource", "reward_key": "fuel_cells", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
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
        {"weight": 15, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 15, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
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
        {"weight": 14, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 14, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
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
        {"weight": 25, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 20, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 15, "reward_type": "resource", "reward_key": "fuel_cells", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 12, "reward_type": "ship", "reward_key": "spark_drone", "min_amount": 2, "max_amount": 8},
        {"weight": 10, "reward_type": "ship", "reward_key": "solar_skiff", "min_amount": 1, "max_amount": 4},
        {"weight": 8, "reward_type": "item", "reward_key": "fragment_wreck_reactor", "min_amount": 1, "max_amount": 3},
        {"weight": 6, "reward_type": "item", "reward_key": "fragment_wreck_hull", "min_amount": 1, "max_amount": 3},
        {"weight": 4, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_research_cache": [
        {"weight": 20, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 15, "reward_type": "booster", "reward_key": "booster_research_15m", "min_amount": 1, "max_amount": 3},
        {"weight": 12, "reward_type": "booster", "reward_key": "booster_research_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 12, "reward_type": "item", "reward_key": "research_data_energy", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "item", "reward_key": "research_data_weapons", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "item", "reward_key": "fragment_dna_rare", "min_amount": 1, "max_amount": 3},
        {"weight": 8, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 2},
        {"weight": 3, "reward_type": "item", "reward_key": "research_instant_level", "min_amount": 1, "max_amount": 1},
    ],
    "container_military_cache": [
        {"weight": 18, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 14, "reward_type": "resource", "reward_key": "fuel_cells", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 14, "reward_type": "defense", "reward_key": "flak_array", "min_amount": 4, "max_amount": 15},
        {"weight": 12, "reward_type": "defense", "reward_key": "sentinel_turret", "min_amount": 5, "max_amount": 20},
        {"weight": 10, "reward_type": "ship", "reward_key": "ironclad_frigate", "min_amount": 1, "max_amount": 4},
        {"weight": 10, "reward_type": "ship", "reward_key": "falcon_interceptor", "min_amount": 2, "max_amount": 6},
        {"weight": 8, "reward_type": "booster", "reward_key": "booster_build_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 6, "reward_type": "booster", "reward_key": "booster_shipyard_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "item", "reward_key": "fleet_computer", "min_amount": 1, "max_amount": 1},
    ],
    "container_event_special": [
        {"weight": 14, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 14, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
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
    "container_mythic": [
        {"weight": 40, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 35, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 15, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 2},
        {"weight": 10, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
    ],
    "container_ancient_relic": [
        {"weight": 35, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 30, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 20, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 15, "reward_type": "item", "reward_key": "fragment_quantum", "min_amount": 1, "max_amount": 2},
    ],
    "container_void_artifact": [
        {"weight": 30, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 25, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 20, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 3},
        {"weight": 15, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
        {"weight": 10, "reward_type": "item", "reward_key": "expo_alien_relic", "min_amount": 1, "max_amount": 1},
    ],
}


def is_scaled_resource_loot(entry: LootEntry) -> bool:
    return (
        str(entry.get("reward_type") or "") == "resource"
        and entry.get("production_hours") is not None
    )


def container_resource_multiplier(container_key: str) -> float:
    return float(CONTAINER_RESOURCE_MULTIPLIER.get(str(container_key), 1.0))


def get_empire_max_mine_levels(user_id: int, *, conn) -> Dict[str, int]:
    """Highest mine/plant level per resource type across all player planets."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COALESCE(MAX(pb.metal_mine), 0) AS metal_mine,
            COALESCE(MAX(pb.crystal_mine), 0) AS crystal_mine,
            COALESCE(MAX(pb.fuel_cell_plant), 0) AS fuel_cell_plant
        FROM planet_buildings pb
        INNER JOIN planets p ON p.id = pb.planet_id
        WHERE p.player_id = ?;
        """,
        (int(user_id),),
    )
    row = cur.fetchone()
    if not row:
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    return {
        "metal": int(row["metal_mine"] or 0),
        "crystal": int(row["crystal_mine"] or 0),
        "fuel_cells": int(row["fuel_cell_plant"] or 0),
    }


def empire_resource_production_per_hour(user_id: int, *, conn) -> Dict[str, int]:
    """Hourly output at empire max mine levels (ratio 1.0, account research)."""
    from .logic import get_building_production_per_hour

    levels = get_empire_max_mine_levels(user_id, conn=conn)
    buildings = {
        "metal_mine": levels["metal"] if levels["metal"] > 0 else LOOT_FALLBACK_MINE_LEVEL,
        "crystal_mine": levels["crystal"] if levels["crystal"] > 0 else LOOT_FALLBACK_MINE_LEVEL,
        "fuel_cell_plant": levels["fuel_cells"] if levels["fuel_cells"] > 0 else LOOT_FALLBACK_MINE_LEVEL,
    }
    prod = get_building_production_per_hour(buildings, 1.0, user_id=int(user_id), conn=conn)
    return {
        "metal": int(prod.get("metal_mine") or 0),
        "crystal": int(prod.get("crystal_mine") or 0),
        "fuel_cells": int(prod.get("fuel_cell_plant") or 0),
    }


def resolve_scaled_resource_amount(
    reward_key: str,
    entry: LootEntry,
    *,
    user_id: int,
    container_key: str,
    conn,
    production_per_hour: Optional[Dict[str, int]] = None,
) -> int:
    """Half-hour (default) of empire max-mine production × container tier."""
    hours = float(entry.get("production_hours") or LOOT_BASE_PRODUCTION_HOURS)
    tier_mult = container_resource_multiplier(container_key)
    if production_per_hour is None:
        production_per_hour = empire_resource_production_per_hour(user_id, conn=conn)
    per_hour = int(production_per_hour.get(str(reward_key), 0) or 0)
    amount = int(per_hour * hours * tier_mult)
    return max(1, amount)


def scaled_resource_amount_label(
    entry: LootEntry,
    *,
    container_key: str,
    amount: Optional[int] = None,
) -> str:
    """Human-readable label for inventory loot reference UI."""
    hours = float(entry.get("production_hours") or LOOT_BASE_PRODUCTION_HOURS)
    tier = container_resource_multiplier(container_key)
    effective_hours = hours * tier
    if amount is not None:
        return str(amount)
    pct = int(round(effective_hours * 100))
    return f"~{pct}% max-mine/h"


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
