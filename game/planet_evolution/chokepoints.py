"""Chokepoint gate nodes between imperium regions — Command Map paths (GC-565)."""

from __future__ import annotations

from typing import Any, Dict, List

# Ordered from hub outward — static definitions, no migration.
# layout_radius_world = gate distance from own hub (GC-571F).
CHOKEPOINTS: Dict[str, Dict[str, Any]] = {
    "helios_corridor": {
        "label_key": "chokepoint_helios_corridor",
        "connects_regions": ["genesis_core", "outer_rim"],
        "layout_bearing_deg": 0,
        "layout_radius_world": 480.0,
        "role_icon": "🚪",
    },
    "ancient_threshold": {
        "label_key": "chokepoint_ancient_threshold",
        "connects_regions": ["outer_rim", "ancient_sector"],
        "layout_bearing_deg": 35,
        "layout_radius_world": 540.0,
        "role_icon": "⛩",
    },
    "void_rift": {
        "label_key": "chokepoint_void_rift",
        "connects_regions": ["ancient_sector", "dark_expanse"],
        "layout_bearing_deg": 15,
        "layout_radius_world": 600.0,
        "role_icon": "🌀",
    },
}

CHOKEPOINT_CHAIN: List[str] = ["helios_corridor", "ancient_threshold", "void_rift"]

# Gates a site must pass through (prefix of CHOKEPOINT_CHAIN) by target region.
REGION_GATE_CHAIN: Dict[str, List[str]] = {
    "outer_rim": ["helios_corridor"],
    "ancient_sector": ["helios_corridor", "ancient_threshold"],
    "dark_expanse": ["helios_corridor", "ancient_threshold", "void_rift"],
}


def gate_chain_for_region(region_key: str) -> List[str]:
    """Ordered chokepoint keys from hub to sites in *region_key*."""
    return list(REGION_GATE_CHAIN.get(str(region_key or ""), []))


def _chokepoint_row(chokepoint_key: str, gate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "node_kind": "chokepoint",
        "chokepoint_key": chokepoint_key,
        "label_key": str(gate.get("label_key") or chokepoint_key),
        "connects_regions": list(gate.get("connects_regions") or []),
        "layout_bearing_deg": float(gate.get("layout_bearing_deg") or 0),
        "layout_radius_world": float(gate.get("layout_radius_world") or 480),
        "role_icon": str(gate.get("role_icon") or "🚪"),
        "empire_role_icon": str(gate.get("role_icon") or "🚪"),
    }


def list_chokepoints_for_map() -> List[Dict[str, Any]]:
    """All chokepoint nodes for Command Map layout."""
    rows: List[Dict[str, Any]] = []
    for key in CHOKEPOINT_CHAIN:
        gate = CHOKEPOINTS.get(key)
        if not gate:
            continue
        rows.append(_chokepoint_row(key, gate))
    return rows
