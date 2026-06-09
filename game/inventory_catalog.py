"""
GC-540 — Inventory item & container catalog (single source of truth).
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Tuple

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
    "booster_production_25": {"item_type": "booster", "category": "booster", "rarity": "uncommon", "name_key": "inv_booster_production_25", "icon": "⚡"},
    "booster_production_50": {"item_type": "booster", "category": "booster", "rarity": "rare", "name_key": "inv_booster_production_50", "icon": "⚡"},
    "booster_production_100": {"item_type": "booster", "category": "booster", "rarity": "epic", "name_key": "inv_booster_production_100", "icon": "⚡"},
    "booster_energy_50": {"item_type": "booster", "category": "booster", "rarity": "rare", "name_key": "inv_booster_energy_50", "icon": "🔋"},
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
    "evo_planet_xp_500": {"item_type": "consumable", "category": "planet_evolution", "rarity": "uncommon", "name_key": "inv_evo_planet_xp_500", "icon": "🪐"},
    "evo_planet_xp_5000": {"item_type": "consumable", "category": "planet_evolution", "rarity": "rare", "name_key": "inv_evo_planet_xp_5000", "icon": "🪐"},
    "evo_planet_xp_50000": {"item_type": "consumable", "category": "planet_evolution", "rarity": "epic", "name_key": "inv_evo_planet_xp_50000", "icon": "🪐"},
    # --- Research artifacts ---
    "research_data_energy": {"item_type": "consumable", "category": "research", "rarity": "uncommon", "name_key": "inv_research_data_energy", "icon": "💾"},
    "research_data_mining": {"item_type": "consumable", "category": "research", "rarity": "uncommon", "name_key": "inv_research_data_mining", "icon": "💾"},
    "research_data_weapons": {"item_type": "consumable", "category": "research", "rarity": "uncommon", "name_key": "inv_research_data_weapons", "icon": "💾"},
    "research_instant_level": {"item_type": "consumable", "category": "research", "rarity": "legendary", "name_key": "inv_research_instant_level", "icon": "📜"},
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
}

GRANTABLE_ITEM_KEYS: FrozenSet[str] = frozenset(ITEM_CATALOG.keys())

INVENTORY_ITEM_TYPES = frozenset({"booster", "fragment", "consumable", "module", "special"})


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
    return entry


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
