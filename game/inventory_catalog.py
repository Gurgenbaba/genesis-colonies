"""
GC-540 — Inventory item & container catalog (single source of truth).
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

CONTAINER_KEYS: FrozenSet[str] = frozenset(
    {
        "container_basic",
        "container_rare",
        "container_epic",
        "container_relic",
        "container_wreckage",
        "container_research_cache",
        "container_military_cache",
        "container_event_special",
    }
)

CONTAINER_BASIC_KEY = "container_basic"
CONTAINER_BASIC_COOLDOWN_SEC = 24 * 60 * 60

# GC-543 — lootbox roller strip length (UI-only; server rewards unchanged).
ROLL_PREVIEW_MIN = 20
ROLL_PREVIEW_MAX = 40

CONTAINER_DISPLAY_ORDER: Tuple[str, ...] = (
    "container_basic",
    "container_rare",
    "container_epic",
    "container_relic",
    "container_wreckage",
    "container_research_cache",
    "container_military_cache",
    "container_event_special",
)

CONTAINER_IMAGES: Dict[str, str] = {
    "container_basic": "img/lootboxes/Basic_Container.png",
    "container_rare": "img/lootboxes/Rare_Container.png",
    "container_epic": "img/lootboxes/Epic_Container.png",
    "container_relic": "img/lootboxes/Relic_Container.png",
    "container_wreckage": "img/lootboxes/Wreckage_Container.png",
    "container_research_cache": "img/lootboxes/Research_Cache.png",
    "container_military_cache": "img/lootboxes/Military_Cache.png",
    "container_event_special": "img/lootboxes/Event_Container.png",
}

# All keys that may be stored in player_inventory_items or granted by admin.
ITEM_CATALOG: Dict[str, Dict[str, Any]] = {
    # --- Containers ---
    "container_basic": {"item_type": "container", "category": "container", "rarity": "common", "name_key": "inv_container_basic", "icon": "📦", "image": "img/lootboxes/Basic_Container.png"},
    "container_rare": {"item_type": "container", "category": "container", "rarity": "uncommon", "name_key": "inv_container_rare", "icon": "🎁", "image": "img/lootboxes/Rare_Container.png"},
    "container_epic": {"item_type": "container", "category": "container", "rarity": "epic", "name_key": "inv_container_epic", "icon": "💎", "image": "img/lootboxes/Epic_Container.png"},
    "container_relic": {"item_type": "container", "category": "container", "rarity": "legendary", "name_key": "inv_container_relic", "icon": "🏺", "image": "img/lootboxes/Relic_Container.png"},
    "container_wreckage": {"item_type": "container", "category": "container", "rarity": "uncommon", "name_key": "inv_container_wreckage", "icon": "🛸", "image": "img/lootboxes/Wreckage_Container.png"},
    "container_research_cache": {"item_type": "container", "category": "container", "rarity": "rare", "name_key": "inv_container_research_cache", "icon": "🔬", "image": "img/lootboxes/Research_Cache.png"},
    "container_military_cache": {"item_type": "container", "category": "container", "rarity": "rare", "name_key": "inv_container_military_cache", "icon": "⚔️", "image": "img/lootboxes/Military_Cache.png"},
    "container_event_special": {"item_type": "container", "category": "container", "rarity": "epic", "name_key": "inv_container_event_special", "icon": "✨", "image": "img/lootboxes/Event_Container.png"},
    # --- Boosters (inventory only; activation later) ---
    "booster_build_5m": {"item_type": "booster", "category": "booster", "rarity": "common", "name_key": "inv_booster_build_5m", "icon": "🔧"},
    "booster_build_15m": {"item_type": "booster", "category": "booster", "rarity": "uncommon", "name_key": "inv_booster_build_15m", "icon": "🔧"},
    "booster_build_1h": {"item_type": "booster", "category": "booster", "rarity": "rare", "name_key": "inv_booster_build_1h", "icon": "🔧"},
    "booster_build_6h": {"item_type": "booster", "category": "booster", "rarity": "epic", "name_key": "inv_booster_build_6h", "icon": "🔧"},
    "booster_build_24h": {"item_type": "booster", "category": "booster", "rarity": "legendary", "name_key": "inv_booster_build_24h", "icon": "🔧"},
    "booster_research_5m": {"item_type": "booster", "category": "booster", "rarity": "common", "name_key": "inv_booster_research_5m", "icon": "📡"},
    "booster_research_15m": {"item_type": "booster", "category": "booster", "rarity": "uncommon", "name_key": "inv_booster_research_15m", "icon": "📡"},
    "booster_research_1h": {"item_type": "booster", "category": "booster", "rarity": "rare", "name_key": "inv_booster_research_1h", "icon": "📡"},
    "booster_research_6h": {"item_type": "booster", "category": "booster", "rarity": "epic", "name_key": "inv_booster_research_6h", "icon": "📡"},
    "booster_research_24h": {"item_type": "booster", "category": "booster", "rarity": "legendary", "name_key": "inv_booster_research_24h", "icon": "📡"},
    "booster_shipyard_15m": {"item_type": "booster", "category": "booster", "rarity": "uncommon", "name_key": "inv_booster_shipyard_15m", "icon": "🛰️"},
    "booster_shipyard_1h": {"item_type": "booster", "category": "booster", "rarity": "rare", "name_key": "inv_booster_shipyard_1h", "icon": "🛰️"},
    # Legacy booster aliases (existing DB rows)
    "booster_build_15": {"item_type": "booster", "category": "booster", "rarity": "uncommon", "name_key": "inv_booster_build_15m", "icon": "🔧"},
    "booster_build_30": {"item_type": "booster", "category": "booster", "rarity": "rare", "name_key": "inv_booster_build_1h", "icon": "🔧"},
    "booster_build_60": {"item_type": "booster", "category": "booster", "rarity": "epic", "name_key": "inv_booster_build_6h", "icon": "🔧"},
    "booster_research_15": {"item_type": "booster", "category": "booster", "rarity": "uncommon", "name_key": "inv_booster_research_15m", "icon": "📡"},
    "booster_research_30": {"item_type": "booster", "category": "booster", "rarity": "rare", "name_key": "inv_booster_research_1h", "icon": "📡"},
    "booster_research_60": {"item_type": "booster", "category": "booster", "rarity": "epic", "name_key": "inv_booster_research_6h", "icon": "📡"},
    # --- Fragments & collectibles ---
    "fragment_dna_common": {"item_type": "fragment", "category": "planet_evolution", "rarity": "common", "name_key": "inv_fragment_dna_common", "icon": "🧬"},
    "fragment_dna_rare": {"item_type": "fragment", "category": "planet_evolution", "rarity": "rare", "name_key": "inv_fragment_dna_rare", "icon": "🧬"},
    "fragment_dna_epic": {"item_type": "fragment", "category": "planet_evolution", "rarity": "epic", "name_key": "inv_fragment_dna_epic", "icon": "🧬"},
    "fragment_artifact_alpha": {"item_type": "fragment", "category": "research", "rarity": "rare", "name_key": "inv_fragment_artifact_alpha", "icon": "🧩"},
    "artifact_core_fragment": {"item_type": "fragment", "category": "research", "rarity": "legendary", "name_key": "inv_artifact_core_fragment", "icon": "🧩"},
    "fragment_alien": {"item_type": "fragment", "category": "expedition", "rarity": "rare", "name_key": "inv_fragment_alien", "icon": "👽"},
    "fragment_quantum": {"item_type": "fragment", "category": "expedition", "rarity": "epic", "name_key": "inv_fragment_quantum", "icon": "⚛️"},
    "fragment_genesis": {"item_type": "fragment", "category": "mythic", "rarity": "legendary", "name_key": "inv_fragment_genesis", "icon": "🌌"},
    "fragment_wreck_reactor": {"item_type": "fragment", "category": "expedition", "rarity": "uncommon", "name_key": "inv_fragment_wreck_reactor", "icon": "🔩"},
    "fragment_wreck_hull": {"item_type": "fragment", "category": "expedition", "rarity": "uncommon", "name_key": "inv_fragment_wreck_hull", "icon": "🛡️"},
    # --- Planet evolution consumables (inventory; effect later) ---
    "evo_planet_xp_500": {
        "item_type": "consumable",
        "category": "planet_evolution",
        "rarity": "uncommon",
        "name_key": "inv_evo_planet_xp_500",
        "icon": "🪐",
        "use_kind": "planet_xp",
        "use_effect": {"xp": 500},
    },
    "evo_planet_xp_5000": {
        "item_type": "consumable",
        "category": "planet_evolution",
        "rarity": "rare",
        "name_key": "inv_evo_planet_xp_5000",
        "icon": "🪐",
        "use_kind": "planet_xp",
        "use_effect": {"xp": 5_000},
    },
    "evo_planet_xp_50000": {
        "item_type": "consumable",
        "category": "planet_evolution",
        "rarity": "epic",
        "name_key": "inv_evo_planet_xp_50000",
        "icon": "🪐",
        "use_kind": "planet_xp",
        "use_effect": {"xp": 50_000},
    },
    # --- Research artifacts ---
    "research_data_energy": {
        "item_type": "consumable",
        "category": "research",
        "rarity": "uncommon",
        "name_key": "inv_research_data_energy",
        "icon": "💾",
        "use_kind": "time_boost",
        "use_effect": {"target": "research", "seconds": 15 * 60},
    },
    "research_data_mining": {
        "item_type": "consumable",
        "category": "research",
        "rarity": "uncommon",
        "name_key": "inv_research_data_mining",
        "icon": "💾",
        "use_kind": "time_boost",
        "use_effect": {"target": "research", "seconds": 15 * 60},
    },
    "research_data_weapons": {
        "item_type": "consumable",
        "category": "research",
        "rarity": "uncommon",
        "name_key": "inv_research_data_weapons",
        "icon": "💾",
        "use_kind": "time_boost",
        "use_effect": {"target": "research", "seconds": 15 * 60},
    },
    "research_instant_level": {
        "item_type": "consumable",
        "category": "research",
        "rarity": "legendary",
        "name_key": "inv_research_instant_level",
        "icon": "📜",
        "use_kind": "research_instant",
    },
    "booster_production_25": {
        "item_type": "booster",
        "category": "booster",
        "rarity": "uncommon",
        "name_key": "inv_booster_production_25",
        "icon": "⚡",
        "use_kind": "production_grant",
        "use_effect": {"pct": 25, "hours": 1},
    },
    "booster_production_50": {
        "item_type": "booster",
        "category": "booster",
        "rarity": "rare",
        "name_key": "inv_booster_production_50",
        "icon": "⚡",
        "use_kind": "production_grant",
        "use_effect": {"pct": 50, "hours": 1},
    },
    "booster_production_100": {
        "item_type": "booster",
        "category": "booster",
        "rarity": "epic",
        "name_key": "inv_booster_production_100",
        "icon": "⚡",
        "use_kind": "production_grant",
        "use_effect": {"pct": 100, "hours": 1},
    },
    "booster_energy_50": {
        "item_type": "booster",
        "category": "booster",
        "rarity": "rare",
        "name_key": "inv_booster_energy_50",
        "icon": "🔋",
        "use_kind": "planet_xp",
        "use_effect": {"xp": 1_000},
    },
    # --- Fleet modules (inventory; effect later) ---
    "fleet_nav_chip": {"item_type": "module", "category": "fleet", "rarity": "rare", "name_key": "inv_fleet_nav_chip", "icon": "🧭"},
    "fleet_hyperdrive_module": {"item_type": "module", "category": "fleet", "rarity": "epic", "name_key": "inv_fleet_hyperdrive_module", "icon": "🚀"},
    "fleet_fuel_optimizer": {"item_type": "module", "category": "fleet", "rarity": "rare", "name_key": "inv_fleet_fuel_optimizer", "icon": "⛽"},
    "fleet_computer": {"item_type": "module", "category": "fleet", "rarity": "uncommon", "name_key": "inv_fleet_computer", "icon": "🖥️"},
    # --- Expedition / mythic ---
    "expo_alien_relic": {"item_type": "special", "category": "expedition", "rarity": "epic", "name_key": "inv_expo_alien_relic", "icon": "🏺"},
    "expo_star_chart": {"item_type": "special", "category": "expedition", "rarity": "rare", "name_key": "inv_expo_star_chart", "icon": "🗺️"},
    "mythic_genesis_core": {"item_type": "special", "category": "mythic", "rarity": "legendary", "name_key": "inv_mythic_genesis_core", "icon": "👑"},
    "mythic_ancient_nexus": {"item_type": "special", "category": "mythic", "rarity": "legendary", "name_key": "inv_mythic_ancient_nexus", "icon": "🔮"},
    "placeholder_special_item": {"item_type": "special", "category": "event", "rarity": "legendary", "name_key": "inv_placeholder_special_item", "icon": "⭐"},
    # --- Resource packs (usable on context planet) ---
    "resource_pack_ferronit": {
        "item_type": "consumable",
        "category": "resources",
        "rarity": "uncommon",
        "name_key": "inv_resource_pack_ferronit",
        "icon": "⚙️",
        "use_kind": "resource",
        "use_effect": {"metal": 50_000},
    },
    "resource_pack_crytite": {
        "item_type": "consumable",
        "category": "resources",
        "rarity": "uncommon",
        "name_key": "inv_resource_pack_crytite",
        "icon": "💎",
        "use_kind": "resource",
        "use_effect": {"crystal": 50_000},
    },
    "resource_pack_fuel": {
        "item_type": "consumable",
        "category": "resources",
        "rarity": "uncommon",
        "name_key": "inv_resource_pack_fuel",
        "icon": "🔋",
        "use_kind": "resource",
        "use_effect": {"fuel_cells": 5_000},
    },
    # --- Crafted DNA cores ---
    "dna_core_common": {
        "item_type": "consumable",
        "category": "planet_evolution",
        "rarity": "rare",
        "name_key": "inv_dna_core_common",
        "icon": "🧬",
        "use_kind": "planet_xp",
        "use_effect": {"xp": 2_500},
    },
    "dna_core_rare": {
        "item_type": "consumable",
        "category": "planet_evolution",
        "rarity": "epic",
        "name_key": "inv_dna_core_rare",
        "icon": "🧬",
        "use_kind": "planet_xp",
        "use_effect": {"xp": 10_000},
    },
    "dna_core_epic": {
        "item_type": "consumable",
        "category": "planet_evolution",
        "rarity": "legendary",
        "name_key": "inv_dna_core_epic",
        "icon": "🧬",
        "use_kind": "planet_xp",
        "use_effect": {"xp": 50_000},
    },
}

# Seconds removed from queue timers (build / research / shipyard boosters).
BOOSTER_TIME_SECONDS: Dict[str, int] = {
    "booster_build_5m": 5 * 60,
    "booster_build_15m": 15 * 60,
    "booster_build_1h": 60 * 60,
    "booster_build_6h": 6 * 60 * 60,
    "booster_build_24h": 24 * 60 * 60,
    "booster_research_5m": 5 * 60,
    "booster_research_15m": 15 * 60,
    "booster_research_1h": 60 * 60,
    "booster_research_6h": 6 * 60 * 60,
    "booster_research_24h": 24 * 60 * 60,
    "booster_shipyard_15m": 15 * 60,
    "booster_shipyard_1h": 60 * 60,
    # Legacy aliases (minutes in key name)
    "booster_build_15": 15 * 60,
    "booster_build_30": 60 * 60,
    "booster_build_60": 6 * 60 * 60,
    "booster_research_15": 15 * 60,
    "booster_research_30": 60 * 60,
    "booster_research_60": 6 * 60 * 60,
}

BOOSTER_QUEUE_TARGET: Dict[str, str] = {
    k: "build"
    for k in BOOSTER_TIME_SECONDS
    if k.startswith("booster_build")
}
BOOSTER_QUEUE_TARGET.update(
    {k: "research" for k in BOOSTER_TIME_SECONDS if k.startswith("booster_research")}
)
BOOSTER_QUEUE_TARGET.update(
    {k: "shipyard" for k in BOOSTER_TIME_SECONDS if k.startswith("booster_shipyard")}
)

# DNA fragment crafting (POST /api/inventory/craft).
CRAFT_RECIPES: Dict[str, Dict[str, Any]] = {
    "dna_core_common": {
        "output_key": "dna_core_common",
        "output_amount": 1,
        "requires": {"fragment_dna_common": 50},
        "name_key": "inv_craft_dna_core_common",
    },
    "dna_core_rare": {
        "output_key": "dna_core_rare",
        "output_amount": 1,
        "requires": {"fragment_dna_rare": 25},
        "name_key": "inv_craft_dna_core_rare",
    },
    "dna_core_epic": {
        "output_key": "dna_core_epic",
        "output_amount": 1,
        "requires": {"fragment_dna_epic": 10},
        "name_key": "inv_craft_dna_core_epic",
    },
}

COLLECTIBLE_ITEM_KEYS: FrozenSet[str] = frozenset(
    {
        "fragment_artifact_alpha",
        "artifact_core_fragment",
        "fragment_alien",
        "fragment_quantum",
        "fragment_genesis",
        "fragment_wreck_reactor",
        "fragment_wreck_hull",
        "fleet_nav_chip",
        "fleet_hyperdrive_module",
        "fleet_fuel_optimizer",
        "fleet_computer",
        "expo_alien_relic",
        "expo_star_chart",
        "mythic_genesis_core",
        "mythic_ancient_nexus",
        "placeholder_special_item",
    }
)

CRAFT_MATERIAL_KEYS: FrozenSet[str] = frozenset(
    {"fragment_dna_common", "fragment_dna_rare", "fragment_dna_epic"}
)

GRANTABLE_ITEM_KEYS: FrozenSet[str] = frozenset(ITEM_CATALOG.keys())

INVENTORY_ITEM_TYPES = frozenset({"booster", "fragment", "consumable", "module", "special", "blueprint"})


def container_image_path(item_key: str) -> str:
    key = str(item_key)
    return str(
        CONTAINER_IMAGES.get(key)
        or (ITEM_CATALOG.get(key) or {}).get("image")
        or "img/lootboxes/Generic_Supply_Container.png"
    )


def item_catalog_entry(item_key: str) -> Dict[str, Any]:
    spec = ITEM_CATALOG.get(str(item_key)) or {}
    key = str(item_key)
    entry = {
        "item_key": key,
        "item_type": str(spec.get("item_type") or "item"),
        "category": str(spec.get("category") or "misc"),
        "rarity": str(spec.get("rarity") or "common"),
        "name_key": str(spec.get("name_key") or f"inv_item_{key}"),
        "icon": str(spec.get("icon") or "📦"),
    }
    if key in CONTAINER_KEYS or spec.get("image"):
        entry["image"] = container_image_path(key)
    if spec.get("use_kind"):
        entry["use_kind"] = str(spec["use_kind"])
    if spec.get("use_effect"):
        entry["use_effect"] = dict(spec["use_effect"])
    if key in BOOSTER_TIME_SECONDS:
        entry["use_kind"] = "time_boost"
        entry["use_effect"] = {
            "target": BOOSTER_QUEUE_TARGET.get(key, "build"),
            "seconds": int(BOOSTER_TIME_SECONDS[key]),
        }
    return entry


def resolve_item_use_kind(item_key: str) -> Optional[str]:
    key = str(item_key)
    if key in COLLECTIBLE_ITEM_KEYS:
        return "collectible"
    if key in CRAFT_MATERIAL_KEYS:
        return "craft_material"
    spec = ITEM_CATALOG.get(key) or {}
    if spec.get("use_kind"):
        return str(spec["use_kind"])
    if key in BOOSTER_TIME_SECONDS:
        return "time_boost"
    if spec.get("item_type") == "blueprint":
        return "blueprint"
    return None


def item_is_usable(item_key: str) -> bool:
    kind = resolve_item_use_kind(item_key)
    return kind not in (None, "collectible", "craft_material")


def item_is_collectible(item_key: str) -> bool:
    return str(item_key) in COLLECTIBLE_ITEM_KEYS


def item_is_craft_material(item_key: str) -> bool:
    return str(item_key) in CRAFT_MATERIAL_KEYS


def craft_recipes_for_material(item_key: str) -> list[Dict[str, Any]]:
    """Recipes that consume this fragment (for UI progress)."""
    key = str(item_key)
    out: list[Dict[str, Any]] = []
    for recipe_key, recipe in CRAFT_RECIPES.items():
        req = int((recipe.get("requires") or {}).get(key) or 0)
        if req > 0:
            out.append(
                {
                    "recipe_key": recipe_key,
                    "output_key": str(recipe.get("output_key") or recipe_key),
                    "required_amount": req,
                    "name_key": str(recipe.get("name_key") or f"inv_craft_{recipe_key}"),
                }
            )
    return out


def is_known_item_key(item_key: str) -> bool:
    return str(item_key or "").strip() in ITEM_CATALOG


def admin_grant_catalog() -> list[Dict[str, Any]]:
    """Containers for admin grant UI."""
    out: list[Dict[str, Any]] = []
    for key in CONTAINER_DISPLAY_ORDER:
        meta = item_catalog_entry(key)
        out.append(
            {
                "item_key": key,
                "name_key": meta["name_key"],
                "rarity": meta["rarity"],
                "image": meta.get("image"),
            }
        )
    return out
