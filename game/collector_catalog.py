"""
GC-965A — Collector Exchange offer catalog (single source of truth).

Offer definitions live here only — not duplicated in DB (GC-000).
See docs/COLLECTOR_EXCHANGE.md.
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from game.fleet_defs import ACTIVE_SHIP_KEYS
from game.inventory_catalog import ITEM_CATALOG, is_known_item_key

CollectorOffer = Dict[str, Any]
CollectorSpecialist = Dict[str, Any]

# Items that may appear in inventory but must never be exchange inputs (prestige-only).
PRESTIGE_ONLY_ITEM_KEYS: FrozenSet[str] = frozenset(
    {
        "fragment_genesis",
        "mythic_genesis_core",
        "mythic_ancient_nexus",
        "artifact_core_fragment",
        "fragment_quantum",
    }
)

# Rewards without a gameplay use handler — not redeemable via Collector Exchange (GC-968A).
COLLECTOR_LOCKED_REWARD_KEYS: FrozenSet[str] = frozenset(
    {
        "utility_repair_drone",
        "utility_fleet_instant_recall",
        "utility_alien_scanner",
        "utility_pirate_scanner",
        "utility_anomaly_scanner",
        "utility_fleet_queue_plus_1",
    }
)

# Prestige / collectible-only rewards allowed when explicitly listed (no fake gameplay).
COLLECTOR_COSMETIC_REWARD_KEYS: FrozenSet[str] = frozenset(
    {
        "expo_star_chart",
    }
)

ALLOWED_REWARD_TYPES = frozenset(
    {"item", "booster", "container", "ship", "item_weighted", "ship_weighted"}
)

COLLECTOR_SPECIALISTS: Dict[str, CollectorSpecialist] = {
    "xenobiologist": {
        "name_key": "collector_spec_xenobiologist",
        "icon": "🧬",
        "description_key": "collector_spec_xenobiologist_desc",
        "sort": 10,
    },
    "scrapmaster": {
        "name_key": "collector_spec_scrapmaster",
        "icon": "🔧",
        "description_key": "collector_spec_scrapmaster_desc",
        "sort": 20,
    },
    "energy_engineer": {
        "name_key": "collector_spec_energy_engineer",
        "icon": "⚡",
        "description_key": "collector_spec_energy_engineer_desc",
        "sort": 30,
    },
    "hyper_technician": {
        "name_key": "collector_spec_hyper_technician",
        "icon": "🚀",
        "description_key": "collector_spec_hyper_technician_desc",
        "sort": 40,
    },
}

COLLECTOR_OFFERS: Dict[str, CollectorOffer] = {
    # --- Xenobiologe ---
    "xeno_dna_common_research_booster": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_common",
        "input_amount": 50,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_research_30m", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_common_research_booster",
        "category_key": "collector_cat_research",
        "sort": 10,
        "enabled": True,
    },
    "xeno_dna_common_research_pct": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_common",
        "input_amount": 50,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_research_pct_2_24h", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_common_research_pct",
        "category_key": "collector_cat_research",
        "sort": 11,
        "enabled": True,
    },
    "xeno_dna_common_planet_xp": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_common",
        "input_amount": 50,
        "rewards": [{"reward_type": "item", "reward_key": "evo_planet_xp_250", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_common_planet_xp",
        "category_key": "collector_cat_planet_evolution",
        "sort": 12,
        "enabled": True,
    },
    "xeno_dna_common_dna_capsule": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_common",
        "input_amount": 50,
        "rewards": [{"reward_type": "item", "reward_key": "dna_core_common", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_common_dna_capsule",
        "category_key": "collector_cat_planet_evolution",
        "sort": 13,
        "enabled": True,
    },
    "xeno_dna_rare_research_bundle": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_rare",
        "input_amount": 25,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_research_6h", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_rare_research_bundle",
        "category_key": "collector_cat_research",
        "sort": 20,
        "enabled": True,
    },
    "xeno_dna_rare_evo_xp": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_rare",
        "input_amount": 25,
        "rewards": [{"reward_type": "item", "reward_key": "evo_planet_xp_5000", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_rare_evo_xp",
        "category_key": "collector_cat_planet_evolution",
        "sort": 21,
        "enabled": True,
    },
    "xeno_dna_rare_research_crate": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_rare",
        "input_amount": 25,
        "rewards": [{"reward_type": "container", "reward_key": "container_research_cache", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_rare_research_crate",
        "category_key": "collector_cat_research",
        "sort": 22,
        "enabled": True,
    },
    "xeno_dna_rare_random_module": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_rare",
        "input_amount": 25,
        "rewards": [
            {
                "reward_type": "item_weighted",
                "pool": [
                    {"weight": 34, "reward_key": "research_data_energy", "amount": 1},
                    {"weight": 33, "reward_key": "research_data_mining", "amount": 1},
                    {"weight": 33, "reward_key": "research_data_weapons", "amount": 1},
                ],
            }
        ],
        "name_key": "collector_offer_xeno_dna_rare_random_module",
        "category_key": "collector_cat_research",
        "sort": 23,
        "enabled": True,
    },
    "xeno_dna_epic_research_24h": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_epic",
        "input_amount": 10,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_research_24h", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_epic_research_24h",
        "category_key": "collector_cat_research",
        "sort": 30,
        "enabled": True,
    },
    "xeno_dna_epic_planet_xp_big": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_epic",
        "input_amount": 10,
        "rewards": [{"reward_type": "item", "reward_key": "evo_planet_xp_50000", "amount": 1}],
        "name_key": "collector_offer_xeno_dna_epic_planet_xp_big",
        "category_key": "collector_cat_planet_evolution",
        "sort": 31,
        "enabled": True,
    },
    "xeno_alien_scanner": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_alien",
        "input_amount": 15,
        "rewards": [{"reward_type": "item", "reward_key": "utility_alien_scanner", "amount": 1}],
        "name_key": "collector_offer_xeno_alien_scanner",
        "category_key": "collector_cat_expedition",
        "sort": 40,
        "enabled": True,
    },
    "xeno_alien_expo_booster": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_alien",
        "input_amount": 10,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_expedition_loot_25_24h", "amount": 1}],
        "name_key": "collector_offer_xeno_alien_expo_booster",
        "category_key": "collector_cat_expedition",
        "sort": 41,
        "enabled": True,
    },
    "xeno_alien_loot_booster": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_alien",
        "input_amount": 10,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_container_luck_24h", "amount": 1}],
        "name_key": "collector_offer_xeno_alien_loot_booster",
        "category_key": "collector_cat_expedition",
        "sort": 42,
        "enabled": True,
    },
    # --- Schrottmeister ---
    "scrap_hull_shipyard_15m": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_hull",
        "input_amount": 20,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_shipyard_15m", "amount": 2}],
        "name_key": "collector_offer_scrap_hull_shipyard_15m",
        "category_key": "collector_cat_shipyard",
        "sort": 10,
        "enabled": True,
    },
    "scrap_hull_shipyard_1h": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_hull",
        "input_amount": 20,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_shipyard_1h", "amount": 1}],
        "name_key": "collector_offer_scrap_hull_shipyard_1h",
        "category_key": "collector_cat_shipyard",
        "sort": 11,
        "enabled": True,
    },
    "scrap_hull_repair_drones": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_hull",
        "input_amount": 20,
        "rewards": [{"reward_type": "item", "reward_key": "utility_repair_drone", "amount": 3}],
        "name_key": "collector_offer_scrap_hull_repair_drones",
        "category_key": "collector_cat_shipyard",
        "sort": 12,
        "enabled": True,
    },
    "scrap_hull_random_ship_small": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_hull",
        "input_amount": 20,
        "rewards": [
            {
                "reward_type": "ship_weighted",
                "pool": [
                    {"weight": 50, "ship_key": "spark_drone", "amount": 5},
                    {"weight": 50, "ship_key": "mule_courier", "amount": 3},
                ],
            }
        ],
        "name_key": "collector_offer_scrap_hull_random_ship_small",
        "category_key": "collector_cat_shipyard",
        "sort": 13,
        "enabled": True,
    },
    "scrap_hull_reconstruction": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_hull",
        "input_amount": 100,
        "rewards": [
            {
                "reward_type": "ship_weighted",
                "pool": [
                    {"weight": 50, "ship_key": "atlas_hauler", "amount": 10},
                    {"weight": 30, "ship_key": "falcon_interceptor", "amount": 5},
                    {"weight": 20, "ship_key": "ironclad_frigate", "amount": 2},
                ],
            }
        ],
        "name_key": "collector_offer_scrap_hull_reconstruction",
        "category_key": "collector_cat_wreck",
        "sort": 100,
        "enabled": True,
    },
    "scrap_reactor_defense_booster": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_reactor",
        "input_amount": 15,
        "rewards": [
            {"reward_type": "booster", "reward_key": "booster_build_1h", "amount": 1},
            {"reward_type": "booster", "reward_key": "booster_shipyard_15m", "amount": 1},
        ],
        "name_key": "collector_offer_scrap_reactor_defense_booster",
        "category_key": "collector_cat_shipyard",
        "sort": 20,
        "enabled": True,
    },
    "scrap_reactor_fuel_cells": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_reactor",
        "input_amount": 15,
        "rewards": [{"reward_type": "item", "reward_key": "resource_pack_fuel", "amount": 2}],
        "name_key": "collector_offer_scrap_reactor_fuel_cells",
        "category_key": "collector_cat_resources",
        "sort": 21,
        "enabled": True,
    },
    "scrap_computer_fleet_slot": {
        "specialist_key": "scrapmaster",
        "input_key": "fleet_computer",
        "input_amount": 5,
        "rewards": [{"reward_type": "item", "reward_key": "utility_fleet_queue_plus_1", "amount": 1}],
        "name_key": "collector_offer_scrap_computer_fleet_slot",
        "category_key": "collector_cat_fleet",
        "sort": 30,
        "enabled": True,
    },
    # --- Energieingenieur ---
    "energy_core_production_25": {
        "specialist_key": "energy_engineer",
        "input_key": "research_data_energy",
        "input_amount": 3,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_production_25", "amount": 1}],
        "name_key": "collector_offer_energy_core_production_25",
        "category_key": "collector_cat_production",
        "sort": 10,
        "enabled": True,
    },
    "energy_core_production_50": {
        "specialist_key": "energy_engineer",
        "input_key": "research_data_energy",
        "input_amount": 5,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_production_50", "amount": 1}],
        "name_key": "collector_offer_energy_core_production_50",
        "category_key": "collector_cat_production",
        "sort": 11,
        "enabled": True,
    },
    "energy_core_energy_surge": {
        "specialist_key": "energy_engineer",
        "input_key": "research_data_energy",
        "input_amount": 5,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_energy_surge_24h", "amount": 1}],
        "name_key": "collector_offer_energy_core_energy_surge",
        "category_key": "collector_cat_energy",
        "sort": 12,
        "enabled": True,
    },
    "energy_core_planet_xp": {
        "specialist_key": "energy_engineer",
        "input_key": "research_data_energy",
        "input_amount": 8,
        "rewards": [{"reward_type": "item", "reward_key": "evo_planet_xp_500", "amount": 1}],
        "name_key": "collector_offer_energy_core_planet_xp",
        "category_key": "collector_cat_planet_evolution",
        "sort": 13,
        "enabled": True,
    },
    "energy_mining_production": {
        "specialist_key": "energy_engineer",
        "input_key": "research_data_mining",
        "input_amount": 3,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_production_25", "amount": 1}],
        "name_key": "collector_offer_energy_mining_production",
        "category_key": "collector_cat_production",
        "sort": 20,
        "enabled": True,
    },
    "energy_weapons_build": {
        "specialist_key": "energy_engineer",
        "input_key": "research_data_weapons",
        "input_amount": 3,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_build_1h", "amount": 1}],
        "name_key": "collector_offer_energy_weapons_build",
        "category_key": "collector_cat_build",
        "sort": 21,
        "enabled": True,
    },
    # --- Hypertechniker ---
    "hyper_fleet_speed_25": {
        "specialist_key": "hyper_technician",
        "input_key": "fleet_hyperdrive_module",
        "input_amount": 5,
        "rewards": [{"reward_type": "booster", "reward_key": "booster_fleet_speed_25_24h", "amount": 1}],
        "name_key": "collector_offer_hyper_fleet_speed_25",
        "category_key": "collector_cat_fleet",
        "sort": 10,
        "enabled": True,
    },
    "hyper_instant_recall": {
        "specialist_key": "hyper_technician",
        "input_key": "fleet_hyperdrive_module",
        "input_amount": 20,
        "rewards": [{"reward_type": "item", "reward_key": "utility_fleet_instant_recall", "amount": 1}],
        "name_key": "collector_offer_hyper_instant_recall",
        "category_key": "collector_cat_fleet",
        "sort": 11,
        "enabled": True,
    },
    "hyper_legendary_crate": {
        "specialist_key": "hyper_technician",
        "input_key": "fleet_hyperdrive_module",
        "input_amount": 50,
        "rewards": [{"reward_type": "container", "reward_key": "container_relic", "amount": 1}],
        "name_key": "collector_offer_hyper_legendary_crate",
        "category_key": "collector_cat_loot",
        "sort": 12,
        "enabled": True,
    },
    "hyper_nav_expo_bundle": {
        "specialist_key": "hyper_technician",
        "input_key": "fleet_nav_chip",
        "input_amount": 8,
        "rewards": [
            {"reward_type": "booster", "reward_key": "booster_expedition_loot_25_24h", "amount": 1},
            {"reward_type": "item", "reward_key": "expo_star_chart", "amount": 1},
        ],
        "name_key": "collector_offer_hyper_nav_expo_bundle",
        "category_key": "collector_cat_expedition",
        "sort": 20,
        "enabled": True,
    },
    "hyper_pirate_scanner": {
        "specialist_key": "hyper_technician",
        "input_key": "fragment_alien",
        "input_amount": 20,
        "rewards": [{"reward_type": "item", "reward_key": "utility_pirate_scanner", "amount": 1}],
        "name_key": "collector_offer_hyper_pirate_scanner",
        "category_key": "collector_cat_expedition",
        "sort": 30,
        "enabled": True,
    },
    "hyper_anomaly_scanner": {
        "specialist_key": "hyper_technician",
        "input_key": "fragment_artifact_alpha",
        "input_amount": 12,
        "rewards": [{"reward_type": "item", "reward_key": "utility_anomaly_scanner", "amount": 1}],
        "name_key": "collector_offer_hyper_anomaly_scanner",
        "category_key": "collector_cat_expedition",
        "sort": 31,
        "enabled": True,
    },
}


def is_prestige_only_item(item_key: str) -> bool:
    return str(item_key or "").strip() in PRESTIGE_ONLY_ITEM_KEYS


def is_valid_collector_reward_key(reward_key: str) -> bool:
    key = str(reward_key or "").strip()
    if not key:
        return False
    return is_known_item_key(key)


def collector_reward_is_redeemable(reward_key: str, *, reward_type: str = "item") -> bool:
    """GC-968A — reward must have a real effect, ship grant, container, or cosmetic allow-list."""
    key = str(reward_key or "").strip()
    rtype = str(reward_type or "item").strip()
    if not key:
        return False
    if key in COLLECTOR_LOCKED_REWARD_KEYS:
        return False
    if rtype in ("ship", "ship_weighted"):
        return True
    if rtype == "container":
        return is_known_item_key(key)
    if key in COLLECTOR_COSMETIC_REWARD_KEYS:
        return True
    if not is_known_item_key(key):
        return False
    from game.inventory_boosters import item_has_implemented_use_effect
    from game.inventory_catalog import item_is_craft_material, item_is_exchange_material

    if item_has_implemented_use_effect(key):
        return True
    if item_is_exchange_material(key) or item_is_craft_material(key):
        return True
    return False


def offer_rewards_are_redeemable(offer: Mapping[str, Any]) -> bool:
    rewards = offer.get("rewards")
    if not isinstance(rewards, list) or not rewards:
        return False
    for reward in rewards:
        if not isinstance(reward, dict):
            return False
        rtype = str(reward.get("reward_type") or "")
        if rtype in ("item_weighted", "ship_weighted"):
            pool = reward.get("pool")
            if not isinstance(pool, list) or not pool:
                return False
            for entry in pool:
                if not isinstance(entry, dict):
                    return False
                if rtype == "ship_weighted":
                    ship_key = str(entry.get("ship_key") or "")
                    if ship_key not in ACTIVE_SHIP_KEYS:
                        return False
                    continue
                rkey = str(entry.get("reward_key") or "")
                if not collector_reward_is_redeemable(rkey, reward_type="item"):
                    return False
            continue
        if rtype == "ship":
            ship_key = str(reward.get("ship_key") or reward.get("reward_key") or "")
            if ship_key not in ACTIVE_SHIP_KEYS:
                return False
            continue
        rkey = str(reward.get("reward_key") or "")
        if not collector_reward_is_redeemable(rkey, reward_type=rtype):
            return False
    return True


def is_valid_collector_input_key(item_key: str) -> bool:
    key = str(item_key or "").strip()
    if not key or is_prestige_only_item(key):
        return False
    return is_known_item_key(key)


def _validate_reward_entry(reward: Mapping[str, Any], *, offer_key: str, path: str) -> List[str]:
    errors: List[str] = []
    rtype = str(reward.get("reward_type") or "").strip()
    if rtype not in ALLOWED_REWARD_TYPES:
        errors.append(f"{offer_key}: invalid reward_type at {path}: {rtype!r}")
        return errors

    if rtype in ("item_weighted", "ship_weighted"):
        pool = reward.get("pool")
        if not isinstance(pool, list) or not pool:
            errors.append(f"{offer_key}: empty pool at {path}")
            return errors
        total_weight = 0
        for idx, entry in enumerate(pool):
            if not isinstance(entry, dict):
                errors.append(f"{offer_key}: invalid pool entry at {path}[{idx}]")
                continue
            weight = int(entry.get("weight") or 0)
            if weight <= 0:
                errors.append(f"{offer_key}: non-positive weight at {path}[{idx}]")
                continue
            total_weight += weight
            if rtype == "ship_weighted":
                ship_key = str(entry.get("ship_key") or "")
                if ship_key not in ACTIVE_SHIP_KEYS:
                    errors.append(f"{offer_key}: unknown ship_key {ship_key!r} at {path}[{idx}]")
                amt = int(entry.get("amount") or 0)
                if amt <= 0:
                    errors.append(f"{offer_key}: invalid ship amount at {path}[{idx}]")
            else:
                rkey = str(entry.get("reward_key") or "")
                if not is_valid_collector_reward_key(rkey):
                    errors.append(f"{offer_key}: unknown reward_key {rkey!r} at {path}[{idx}]")
                amt = int(entry.get("amount") or 0)
                if amt <= 0:
                    errors.append(f"{offer_key}: invalid item amount at {path}[{idx}]")
        if total_weight <= 0:
            errors.append(f"{offer_key}: pool weight sum must be > 0 at {path}")
        return errors

    if rtype == "ship":
        ship_key = str(reward.get("ship_key") or reward.get("reward_key") or "")
        if ship_key not in ACTIVE_SHIP_KEYS:
            errors.append(f"{offer_key}: unknown ship reward at {path}: {ship_key!r}")
        if int(reward.get("amount") or 0) <= 0:
            errors.append(f"{offer_key}: invalid ship amount at {path}")
        return errors

    rkey = str(reward.get("reward_key") or "")
    if not is_valid_collector_reward_key(rkey):
        errors.append(f"{offer_key}: unknown reward_key {rkey!r} at {path}")
    if int(reward.get("amount") or 0) <= 0:
        errors.append(f"{offer_key}: invalid reward amount at {path}")
    return errors


def validate_collector_catalog() -> List[str]:
    """Return human-readable validation errors; empty list means valid."""
    errors: List[str] = []
    if len(COLLECTOR_OFFERS) != len(set(COLLECTOR_OFFERS.keys())):
        errors.append("duplicate offer keys in COLLECTOR_OFFERS")

    for offer_key, offer in COLLECTOR_OFFERS.items():
        specialist_key = str(offer.get("specialist_key") or "")
        if specialist_key not in COLLECTOR_SPECIALISTS:
            errors.append(f"{offer_key}: unknown specialist_key {specialist_key!r}")

        input_key = str(offer.get("input_key") or "")
        if not is_valid_collector_input_key(input_key):
            if is_prestige_only_item(input_key):
                errors.append(f"{offer_key}: prestige-only input {input_key!r} is not redeemable")
            else:
                errors.append(f"{offer_key}: invalid input_key {input_key!r}")

        input_amount = int(offer.get("input_amount") or 0)
        if input_amount <= 0:
            errors.append(f"{offer_key}: input_amount must be > 0")

        rewards = offer.get("rewards")
        if not isinstance(rewards, list) or not rewards:
            errors.append(f"{offer_key}: rewards must be a non-empty list")
            continue

        for idx, reward in enumerate(rewards):
            if not isinstance(reward, dict):
                errors.append(f"{offer_key}: reward[{idx}] must be a dict")
                continue
            errors.extend(_validate_reward_entry(reward, offer_key=offer_key, path=f"rewards[{idx}]"))

        if "name_key" not in offer:
            errors.append(f"{offer_key}: missing name_key")

    for prestige_key in PRESTIGE_ONLY_ITEM_KEYS:
        for offer_key, offer in COLLECTOR_OFFERS.items():
            if str(offer.get("input_key") or "") == prestige_key:
                errors.append(f"{offer_key}: prestige-only item {prestige_key!r} used as input")

    return errors


def assert_collector_catalog_valid() -> None:
    errors = validate_collector_catalog()
    if errors:
        raise ValueError("Invalid collector catalog:\n- " + "\n- ".join(errors))


def get_collector_offer(offer_key: str) -> Optional[CollectorOffer]:
    return COLLECTOR_OFFERS.get(str(offer_key or "").strip())


def list_collector_offers(*, specialist_key: Optional[str] = None) -> Tuple[CollectorOffer, ...]:
    rows: List[CollectorOffer] = []
    for key, offer in COLLECTOR_OFFERS.items():
        if specialist_key and str(offer.get("specialist_key") or "") != specialist_key:
            continue
        rows.append({"offer_key": key, **offer})
    rows.sort(key=lambda row: (int(row.get("sort") or 0), str(row.get("offer_key") or "")))
    return tuple(rows)


def list_collector_specialists() -> Tuple[Dict[str, Any], ...]:
    rows: List[Dict[str, Any]] = []
    for key, spec in COLLECTOR_SPECIALISTS.items():
        rows.append({"specialist_key": key, **spec})
    rows.sort(key=lambda row: int(row.get("sort") or 0))
    return tuple(rows)


def flatten_reward_preview(rewards: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic preview rows for UI/state (weighted pools show all options)."""
    preview: List[Dict[str, Any]] = []
    for reward in rewards:
        rtype = str(reward.get("reward_type") or "")
        if rtype in ("item_weighted", "ship_weighted"):
            for entry in reward.get("pool") or []:
                if rtype == "ship_weighted":
                    preview.append(
                        {
                            "reward_type": "ship",
                            "reward_key": str(entry.get("ship_key") or ""),
                            "amount": int(entry.get("amount") or 0),
                            "weight": int(entry.get("weight") or 0),
                        }
                    )
                else:
                    preview.append(
                        {
                            "reward_type": "item",
                            "reward_key": str(entry.get("reward_key") or ""),
                            "amount": int(entry.get("amount") or 0),
                            "weight": int(entry.get("weight") or 0),
                        }
                    )
            continue
        if rtype == "ship":
            preview.append(
                {
                    "reward_type": "ship",
                    "reward_key": str(reward.get("ship_key") or reward.get("reward_key") or ""),
                    "amount": int(reward.get("amount") or 0),
                }
            )
            continue
        preview.append(
            {
                "reward_type": rtype,
                "reward_key": str(reward.get("reward_key") or ""),
                "amount": int(reward.get("amount") or 0),
            }
        )
    return preview


# Fail fast on import in dev/tests — catalog must always be consistent.
assert_collector_catalog_valid()
