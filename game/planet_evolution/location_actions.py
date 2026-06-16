"""Role-based location actions for World Map colonies (GC-570) — presentation only."""

from __future__ import annotations

from typing import Any, Dict, List

# Static role → shell routes. Labels resolved in template via label_key.
ROLE_LOCATION_ACTIONS: Dict[str, List[Dict[str, str]]] = {
    "homeworld": [
        {"action_key": "overview", "label_key": "location_action_overview", "href": "/overview", "icon": "📊"},
        {"action_key": "evolution", "label_key": "location_action_evolution", "href": "/planet-evolution", "icon": "🧬"},
        {"action_key": "buildings", "label_key": "location_action_buildings", "href": "/buildings", "icon": "🏗"},
        {"action_key": "research", "label_key": "location_action_research", "href": "/research", "icon": "🔬"},
        {"action_key": "shipyard", "label_key": "location_action_shipyard", "href": "/shipyard", "icon": "⚓"},
        {"action_key": "fleet", "label_key": "location_action_fleet", "href": "/fleet", "icon": "🚀"},
        {"action_key": "defense", "label_key": "location_action_defense", "href": "/defense", "icon": "🛡"},
        {"action_key": "trade", "label_key": "location_action_trade", "href": "/trader-hub", "icon": "🏪"},
        {"action_key": "logistics", "label_key": "location_action_storage", "href": "/logistics", "icon": "📦"},
    ],
    "mining": [
        {"action_key": "mines", "label_key": "location_action_mines", "href": "/buildings", "icon": "⛏"},
        {"action_key": "storage", "label_key": "location_action_storage", "href": "/logistics", "icon": "📦"},
        {"action_key": "defense", "label_key": "location_action_defense", "href": "/defense", "icon": "🛡"},
        {"action_key": "trade", "label_key": "location_action_trade", "href": "/trader-hub", "icon": "🏪"},
    ],
    "research": [
        {"action_key": "planet_tech", "label_key": "location_action_planet_tech", "href": "/planet-evolution", "icon": "🧬"},
        {"action_key": "research", "label_key": "location_action_research", "href": "/research", "icon": "🔬"},
        {"action_key": "defense", "label_key": "location_action_defense", "href": "/defense", "icon": "🛡"},
        {"action_key": "buildings", "label_key": "location_action_buildings", "href": "/buildings", "icon": "🏗"},
    ],
    "shipyard": [
        {"action_key": "shipyard", "label_key": "location_action_shipyard", "href": "/shipyard", "icon": "⚓"},
        {"action_key": "fleet", "label_key": "location_action_fleet", "href": "/fleet", "icon": "🚀"},
        {"action_key": "defense", "label_key": "location_action_defense", "href": "/defense", "icon": "🛡"},
        {"action_key": "buildings", "label_key": "location_action_buildings", "href": "/buildings", "icon": "🏗"},
    ],
    "fortress": [
        {"action_key": "defense", "label_key": "location_action_defense", "href": "/defense", "icon": "🛡"},
        {"action_key": "buildings", "label_key": "location_action_buildings", "href": "/buildings", "icon": "🏗"},
        {"action_key": "fleet", "label_key": "location_action_fleet", "href": "/fleet", "icon": "🚀"},
    ],
    "trade": [
        {"action_key": "trade", "label_key": "location_action_trade", "href": "/trader-hub", "icon": "🏪"},
        {"action_key": "storage", "label_key": "location_action_storage", "href": "/logistics", "icon": "📦"},
        {"action_key": "routes", "label_key": "location_action_routes", "href": "/logistics", "icon": "🔀"},
        {"action_key": "buildings", "label_key": "location_action_buildings", "href": "/buildings", "icon": "🏗"},
    ],
    "frontier": [
        {"action_key": "buildings", "label_key": "location_action_buildings", "href": "/buildings", "icon": "🏗"},
        {"action_key": "defense", "label_key": "location_action_defense", "href": "/defense", "icon": "🛡"},
    ],
    "general": [
        {"action_key": "buildings", "label_key": "location_action_buildings", "href": "/buildings", "icon": "🏗"},
        {"action_key": "defense", "label_key": "location_action_defense", "href": "/defense", "icon": "🛡"},
    ],
}


_HOMEWORLD_ROLE_KEYS = frozenset({"homeworld", "genesis_ark"})


def build_location_actions(role_key: str, *, is_homeworld: bool = False) -> List[Dict[str, str]]:
    """PJAX action links for a colony role — no gameplay logic."""
    role = str(role_key or "general").strip().lower()
    if is_homeworld or role in _HOMEWORLD_ROLE_KEYS:
        key = "homeworld"
    else:
        key = role if role in ROLE_LOCATION_ACTIONS else "general"
    return [dict(row) for row in ROLE_LOCATION_ACTIONS[key]]
