"""
GC-540 — Weighted container loot pools (speedgame-tuned).

Metal/crystal/fuel: scaled reward with a 5 000–10 000 floor (× container tier).
Ships/defense: diminishing % of owned units (log curve), 5 000–10 000 floor below 100k,
hard cap 100 000 units per roll (× tier on floor/% only, cap absolute).
"""

from __future__ import annotations

import json
import math
import random
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

LootEntry = Dict[str, Any]

LOOT_POOL_SETTINGS_KEY = "inventory_loot_pool_overrides"

from .economy_balance import (
    LOOT_BASE_PRODUCTION_HOURS as _EB_LOOT_HOURS,
    LOOT_RESOURCE_FLOOR_MAX as _EB_FLOOR_MAX,
    LOOT_RESOURCE_FLOOR_MIN as _EB_FLOOR_MIN,
)

# Discord feedback: reward ≈ 50 % of 1 h production at highest empire mine level.
LOOT_BASE_PRODUCTION_HOURS = _EB_LOOT_HOURS
LOOT_FALLBACK_MINE_LEVEL = 1

LOOT_FLEET_FRACTION = 0.10
LOOT_DEFENSE_FRACTION = 0.10

# Ships / defense: floor until 10 % of stock would reach LOOT_UNIT_FLOOR_MAX (~100k hulls).
LOOT_UNIT_FLOOR_MIN = 5_000
LOOT_UNIT_FLOOR_MAX = 10_000
LOOT_UNIT_FLOOR_THRESHOLD = 100_000
LOOT_UNIT_AMOUNT_CAP = 100_000

# (empire stock, (frac_lo, frac_hi)) — log-linear interpolation between anchors.
LOOT_UNIT_FRACTION_ANCHORS: Tuple[Tuple[int, Tuple[float, float]], ...] = (
    (100_000, (0.05, 0.10)),
    (1_000_000, (0.03, 0.05)),
    (1_000_000_000, (0.00005, 0.0001)),
)

LOOT_FUEL_STOCK_FRACTION = 0.10
LOOT_RESOURCE_FLOOR_MIN = _EB_FLOOR_MIN
LOOT_RESOURCE_FLOOR_MAX = _EB_FLOOR_MAX

# Backward-compatible aliases for tests
LOOT_ZERO_FLEET_SHIP_MIN = LOOT_UNIT_FLOOR_MIN
LOOT_ZERO_FLEET_SHIP_MAX = LOOT_UNIT_FLOOR_MAX
LOOT_ZERO_FLEET_FUEL_MIN = LOOT_RESOURCE_FLOOR_MIN
LOOT_ZERO_FLEET_FUEL_MAX = LOOT_RESOURCE_FLOOR_MAX

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
        {"weight": 16, "reward_type": "resource", "reward_key": "fuel_cells", "stock_fraction": LOOT_FUEL_STOCK_FRACTION},
        {"weight": 10, "reward_type": "ship", "reward_key": "spark_drone", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "ship", "reward_key": "mule_courier", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "defense", "reward_key": "sentinel_turret", "defense_fraction": LOOT_DEFENSE_FRACTION},
        {"weight": 6, "reward_type": "item", "reward_key": "fragment_dna_common", "min_amount": 1, "max_amount": 3},
        {"weight": 5, "reward_type": "booster", "reward_key": "booster_build_5m", "min_amount": 1, "max_amount": 1},
        {"weight": 3, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_rare": [
        {"weight": 18, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 18, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 12, "reward_type": "resource", "reward_key": "fuel_cells", "stock_fraction": LOOT_FUEL_STOCK_FRACTION},
        {"weight": 10, "reward_type": "ship", "reward_key": "veil_probe", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 10, "reward_type": "ship", "reward_key": "falcon_interceptor", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "defense", "reward_key": "plasma_arc", "defense_fraction": LOOT_DEFENSE_FRACTION},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_build_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 6, "reward_type": "booster", "reward_key": "booster_research_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 5, "reward_type": "item", "reward_key": "fragment_dna_rare", "min_amount": 1, "max_amount": 2},
        {"weight": 4, "reward_type": "item", "reward_key": "research_data_mining", "min_amount": 1, "max_amount": 1},
        {"weight": 2, "reward_type": "item", "reward_key": "container_epic", "min_amount": 1, "max_amount": 1},
    ],
    "container_epic": [
        {"weight": 15, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 15, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "stock_fraction": LOOT_FUEL_STOCK_FRACTION},
        {"weight": 10, "reward_type": "ship", "reward_key": "ironclad_frigate", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "ship", "reward_key": "atlas_hauler", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "defense", "reward_key": "ion_bastion", "defense_fraction": LOOT_DEFENSE_FRACTION},
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
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "stock_fraction": LOOT_FUEL_STOCK_FRACTION},
        {"weight": 9, "reward_type": "ship", "reward_key": "harvest_reclaimer", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 7, "reward_type": "ship", "reward_key": "seed_ark", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "defense", "reward_key": "orbital_shield", "defense_fraction": LOOT_DEFENSE_FRACTION},
        {"weight": 8, "reward_type": "defense", "reward_key": "pulse_barrier", "defense_fraction": LOOT_DEFENSE_FRACTION},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_build_24h", "min_amount": 1, "max_amount": 1},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_research_24h", "min_amount": 1, "max_amount": 1},
        {"weight": 6, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 2},
        {"weight": 5, "reward_type": "item", "reward_key": "fragment_genesis", "min_amount": 1, "max_amount": 3},
        {"weight": 5, "reward_type": "item", "reward_key": "mythic_genesis_core", "min_amount": 1, "max_amount": 1},
    ],
    "container_wreckage": [
        {"weight": 25, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 20, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 15, "reward_type": "resource", "reward_key": "fuel_cells", "stock_fraction": LOOT_FUEL_STOCK_FRACTION},
        {"weight": 12, "reward_type": "ship", "reward_key": "spark_drone", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 10, "reward_type": "ship", "reward_key": "solar_skiff", "fleet_fraction": LOOT_FLEET_FRACTION},
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
        {"weight": 14, "reward_type": "resource", "reward_key": "fuel_cells", "stock_fraction": LOOT_FUEL_STOCK_FRACTION},
        {"weight": 14, "reward_type": "defense", "reward_key": "flak_array", "defense_fraction": LOOT_DEFENSE_FRACTION},
        {"weight": 12, "reward_type": "defense", "reward_key": "sentinel_turret", "defense_fraction": LOOT_DEFENSE_FRACTION},
        {"weight": 10, "reward_type": "ship", "reward_key": "ironclad_frigate", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 10, "reward_type": "ship", "reward_key": "falcon_interceptor", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "booster", "reward_key": "booster_build_1h", "min_amount": 1, "max_amount": 2},
        {"weight": 6, "reward_type": "booster", "reward_key": "booster_shipyard_15m", "min_amount": 1, "max_amount": 2},
        {"weight": 8, "reward_type": "item", "reward_key": "fleet_computer", "min_amount": 1, "max_amount": 1},
    ],
    "container_event_special": [
        {"weight": 14, "reward_type": "resource", "reward_key": "metal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 14, "reward_type": "resource", "reward_key": "crystal", "production_hours": LOOT_BASE_PRODUCTION_HOURS},
        {"weight": 10, "reward_type": "resource", "reward_key": "fuel_cells", "stock_fraction": LOOT_FUEL_STOCK_FRACTION},
        {"weight": 9, "reward_type": "ship", "reward_key": "atlas_hauler", "fleet_fraction": LOOT_FLEET_FRACTION},
        {"weight": 8, "reward_type": "defense", "reward_key": "plasma_arc", "defense_fraction": LOOT_DEFENSE_FRACTION},
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
    """Metal/crystal mine-scaled resources."""
    if str(entry.get("reward_type") or "") != "resource":
        return False
    if entry.get("stock_fraction") is not None:
        return False
    return entry.get("production_hours") is not None


def is_fuel_stock_scaled_loot(entry: LootEntry) -> bool:
    return (
        str(entry.get("reward_type") or "") == "resource"
        and str(entry.get("reward_key") or "") == "fuel_cells"
        and entry.get("stock_fraction") is not None
    )


def is_fleet_scaled_ship_loot(entry: LootEntry) -> bool:
    return (
        str(entry.get("reward_type") or "") == "ship"
        and entry.get("fleet_fraction") is not None
    )


def is_defense_scaled_loot(entry: LootEntry) -> bool:
    return (
        str(entry.get("reward_type") or "") == "defense"
        and entry.get("defense_fraction") is not None
    )


def is_diminishing_unit_loot(entry: LootEntry) -> bool:
    return is_fleet_scaled_ship_loot(entry) or is_defense_scaled_loot(entry)


def is_dynamic_loot_entry(entry: LootEntry) -> bool:
    return (
        is_scaled_resource_loot(entry)
        or is_fuel_stock_scaled_loot(entry)
        or is_diminishing_unit_loot(entry)
    )


def container_resource_multiplier(container_key: str) -> float:
    return float(CONTAINER_RESOURCE_MULTIPLIER.get(str(container_key), 1.0))


def _loot_resource_floor(rng: random.Random, tier_mult: float) -> int:
    return max(1, int(math.ceil(rng.randint(LOOT_RESOURCE_FLOOR_MIN, LOOT_RESOURCE_FLOOR_MAX) * tier_mult)))


def _unit_uses_fixed_floor(basis: int) -> bool:
    """Below ~100k stock, or when 10 % would not yet reach the floor band."""
    stock = max(0, int(basis))
    if stock <= 0:
        return True
    if stock < LOOT_UNIT_FLOOR_THRESHOLD:
        return True
    return stock * LOOT_UNIT_FRACTION_ANCHORS[0][1][1] < LOOT_UNIT_FLOOR_MAX


def _interp_unit_fraction_band(count: int) -> Tuple[float, float]:
    """Log-linear (frac_lo, frac_hi) between LOOT_UNIT_FRACTION_ANCHORS."""
    anchors = LOOT_UNIT_FRACTION_ANCHORS
    c = max(1, int(count))
    if c <= anchors[0][0]:
        return anchors[0][1]
    if c >= anchors[-1][0]:
        return anchors[-1][1]
    for i in range(len(anchors) - 1):
        c0, band0 = anchors[i]
        c1, band1 = anchors[i + 1]
        if c <= c1:
            if c <= c0:
                return band0
            log_span = math.log10(c1) - math.log10(c0)
            if log_span <= 0:
                return band1
            t = (math.log10(c) - math.log10(c0)) / log_span
            lo = band0[0] + t * (band1[0] - band0[0])
            hi = band0[1] + t * (band1[1] - band0[1])
            return (max(0.0, lo), max(lo, hi))
    return anchors[-1][1]


def resolve_diminishing_unit_amount(
    basis: int,
    *,
    rng: random.Random,
    tier_mult: float,
) -> int:
    """
    Ships/defense loot: 5k–10k floor under ~100k stock, then shrinking % band, cap 100k.
    """
    tier = max(0.0, float(tier_mult))
    stock = max(0, int(basis))
    if _unit_uses_fixed_floor(stock):
        rolled = rng.randint(LOOT_UNIT_FLOOR_MIN, LOOT_UNIT_FLOOR_MAX)
        return min(max(1, int(math.ceil(rolled * tier))), LOOT_UNIT_AMOUNT_CAP)
    frac_lo, frac_hi = _interp_unit_fraction_band(stock)
    frac = rng.uniform(frac_lo, frac_hi)
    amount = int(math.ceil(stock * frac * tier))
    return min(max(1, amount), LOOT_UNIT_AMOUNT_CAP)


def apply_loot_amount_floor(
    amount: int,
    reward_type: str,
    *,
    rng: random.Random,
    tier_mult: float,
) -> int:
    """Resource floor only — ships/defense use resolve_diminishing_unit_amount."""
    amt = max(0, int(amount))
    if str(reward_type) == "resource":
        return max(amt, _loot_resource_floor(rng, tier_mult))
    if str(reward_type) in ("ship", "defense"):
        return min(max(1, amt), LOOT_UNIT_AMOUNT_CAP)
    return max(1, amt)


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
    """Half-hour (default) of empire max-mine production × container tier (metal/crystal)."""
    hours = float(entry.get("production_hours") or LOOT_BASE_PRODUCTION_HOURS)
    tier_mult = container_resource_multiplier(container_key)
    if production_per_hour is None:
        production_per_hour = empire_resource_production_per_hour(user_id, conn=conn)
    per_hour = int(production_per_hour.get(str(reward_key), 0) or 0)
    amount = int(per_hour * hours * tier_mult)
    return max(0, amount)


def get_empire_total_fuel_cells(user_id: int, *, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT COALESCE(SUM(fuel_cells), 0) AS total FROM planets WHERE player_id = ?;",
        (int(user_id),),
    )
    row = cur.fetchone()
    return int(row["total"] or 0) if row else 0


def empire_total_ship_count(
    user_id: int,
    *,
    conn,
    ship_counts: Optional[Dict[str, int]] = None,
) -> int:
    if ship_counts is None:
        from .fleet import get_player_owned_ship_counts

        ship_counts = get_player_owned_ship_counts(int(user_id), conn=conn)
    return sum(max(0, int(v)) for v in (ship_counts or {}).values())


def resolve_scaled_ship_amount(
    ship_key: str,
    entry: LootEntry,
    *,
    user_id: int,
    container_key: str,
    conn,
    rng: random.Random,
    ship_counts: Optional[Dict[str, int]] = None,
) -> int:
    """Diminishing % of owned hulls (per type, else total fleet)."""
    from .fleet_defs import canonical_ship_key

    if ship_counts is None:
        from .fleet import get_player_owned_ship_counts

        ship_counts = get_player_owned_ship_counts(int(user_id), conn=conn)
    total = empire_total_ship_count(user_id, conn=conn, ship_counts=ship_counts)
    tier_mult = container_resource_multiplier(container_key)
    sk = canonical_ship_key(ship_key)
    owned = int(ship_counts.get(sk, 0) or 0)
    basis = owned if owned > 0 else total
    return resolve_diminishing_unit_amount(basis, rng=rng, tier_mult=tier_mult)


def resolve_scaled_defense_amount(
    defense_key: str,
    entry: LootEntry,
    *,
    user_id: int,
    container_key: str,
    conn,
    rng: random.Random,
    defense_counts: Optional[Dict[str, int]] = None,
) -> int:
    """Diminishing % of owned defense (per type, else total stock)."""
    if defense_counts is None:
        from .models import get_player_defense_counts

        defense_counts = get_player_defense_counts(int(user_id), conn=conn)
    total = sum(max(0, int(v)) for v in (defense_counts or {}).values())
    tier_mult = container_resource_multiplier(container_key)
    dk = str(defense_key or "")
    owned = int((defense_counts or {}).get(dk, 0) or 0)
    basis = owned if owned > 0 else total
    return resolve_diminishing_unit_amount(basis, rng=rng, tier_mult=tier_mult)


def resolve_scaled_fuel_amount(
    entry: LootEntry,
    *,
    user_id: int,
    container_key: str,
    conn,
    rng: random.Random,
    fuel_stock: Optional[int] = None,
    ship_counts: Optional[Dict[str, int]] = None,
) -> int:
    """10 % of empire fuel stock × container tier (floor applied by resolve_loot_entry_amount)."""
    if fuel_stock is None:
        fuel_stock = get_empire_total_fuel_cells(user_id, conn=conn)
    tier_mult = container_resource_multiplier(container_key)
    frac = float(entry.get("stock_fraction") or LOOT_FUEL_STOCK_FRACTION)
    return max(0, int(math.ceil(int(fuel_stock) * frac * tier_mult)))


def resolve_loot_entry_amount(
    entry: LootEntry,
    *,
    user_id: int,
    container_key: str,
    conn,
    rng: random.Random,
    loot_context: Optional[Dict[str, Any]] = None,
) -> int:
    """Resolve amount for any dynamic loot pool entry."""
    ctx = loot_context or {}
    rtype = str(entry.get("reward_type") or "")
    rkey = str(entry.get("reward_key") or "")
    tier_mult = container_resource_multiplier(container_key)
    if is_scaled_resource_loot(entry):
        amount = resolve_scaled_resource_amount(
            rkey,
            entry,
            user_id=int(user_id),
            container_key=container_key,
            conn=conn,
            production_per_hour=ctx.get("production_per_hour"),
        )
    elif is_fuel_stock_scaled_loot(entry):
        amount = resolve_scaled_fuel_amount(
            entry,
            user_id=int(user_id),
            container_key=container_key,
            conn=conn,
            rng=rng,
            fuel_stock=ctx.get("fuel_stock"),
            ship_counts=ctx.get("ship_counts"),
        )
    elif is_fleet_scaled_ship_loot(entry):
        amount = resolve_scaled_ship_amount(
            rkey,
            entry,
            user_id=int(user_id),
            container_key=container_key,
            conn=conn,
            rng=rng,
            ship_counts=ctx.get("ship_counts"),
        )
    elif is_defense_scaled_loot(entry):
        amount = resolve_scaled_defense_amount(
            rkey,
            entry,
            user_id=int(user_id),
            container_key=container_key,
            conn=conn,
            rng=rng,
            defense_counts=ctx.get("defense_counts"),
        )
    else:
        lo = int(entry.get("min_amount") or 1)
        hi = int(entry.get("max_amount") or lo)
        if hi < lo:
            hi = lo
        amount = int(rng.randint(lo, hi))
    return apply_loot_amount_floor(amount, rtype, rng=rng, tier_mult=tier_mult)


def build_loot_roll_context(user_id: int, container_key: str, *, conn) -> Dict[str, Any]:
    from .fleet import get_player_owned_ship_counts
    from .models import get_player_defense_counts

    ship_counts = get_player_owned_ship_counts(int(user_id), conn=conn)
    return {
        "user_id": int(user_id),
        "container_key": str(container_key),
        "conn": conn,
        "production_per_hour": empire_resource_production_per_hour(int(user_id), conn=conn),
        "ship_counts": ship_counts,
        "defense_counts": get_player_defense_counts(int(user_id), conn=conn),
        "fuel_stock": get_empire_total_fuel_cells(int(user_id), conn=conn),
    }


def scaled_loot_amount_label(
    entry: LootEntry,
    *,
    container_key: str,
    amount: Optional[int] = None,
) -> str:
    """Human-readable label for inventory loot reference UI."""
    if is_fleet_scaled_ship_loot(entry) or is_defense_scaled_loot(entry):
        if amount is not None:
            return str(amount)
        return "5k–10k floor / diminishing % · cap 100k"
    if is_fuel_stock_scaled_loot(entry):
        if amount is not None:
            return str(amount)
        return "~10% fuel stock × tier"
    hours = float(entry.get("production_hours") or LOOT_BASE_PRODUCTION_HOURS)
    tier = container_resource_multiplier(container_key)
    effective_hours = hours * tier
    if amount is not None:
        return str(amount)
    pct = int(round(effective_hours * 100))
    return f"~{pct}% max-mine/h"


def scaled_resource_amount_label(
    entry: LootEntry,
    *,
    container_key: str,
    amount: Optional[int] = None,
) -> str:
    """Backward-compatible alias for mine-scaled resource labels."""
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
