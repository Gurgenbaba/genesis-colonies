"""Imperium region definitions — spatial nebula zones (GC-564 / GC-564B). Display only."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional

# Spatial nebula zones (% of canvas) — ellipses behind nodes, not horizontal bands.
IMPERIUM_REGIONS: Dict[str, Dict[str, Any]] = {
    "genesis_core": {
        "label_key": "imperium_region_genesis_core",
        "sort_order": 10,
        "tone": "core",
        "layout_zone": {
            "kind": "ellipse",
            "cx_pct": 50.0,
            "cy_pct": 52.0,
            "rx_pct": 28.0,
            "ry_pct": 22.0,
        },
    },
    "outer_rim": {
        "label_key": "imperium_region_outer_rim",
        "sort_order": 20,
        "tone": "rim",
        "layout_zone": {
            "kind": "ellipse",
            "cx_pct": 50.0,
            "cy_pct": 22.0,
            "rx_pct": 32.0,
            "ry_pct": 18.0,
        },
    },
    "ancient_sector": {
        "label_key": "imperium_region_ancient_sector",
        "sort_order": 30,
        "tone": "ancient",
        "layout_zone": {
            "kind": "ellipse",
            "cx_pct": 72.0,
            "cy_pct": 30.0,
            "rx_pct": 26.0,
            "ry_pct": 20.0,
        },
    },
    "dark_expanse": {
        "label_key": "imperium_region_dark_expanse",
        "sort_order": 40,
        "tone": "dark",
        "layout_zone": {
            "kind": "ellipse",
            "cx_pct": 50.0,
            "cy_pct": 10.0,
            "rx_pct": 38.0,
            "ry_pct": 14.0,
        },
    },
}

# Command Map hub anchor (Genesis Ark visual center).
MAP_HUB_CX_PCT = 50.0
MAP_HUB_CY_PCT = 52.0


def region_for_colony(_planet_row: Optional[Mapping[str, Any]] = None) -> str:
    """MVP: all player colonies live in Genesis Core."""
    return "genesis_core"


def region_is_dimmed(region_key: str, sites_in_region: List[Dict[str, Any]]) -> bool:
    if str(region_key) == "genesis_core":
        return False
    if not sites_in_region:
        return True
    return all(bool(s.get("is_locked")) for s in sites_in_region)


def build_regions_payload(
    *,
    expansion_sites: List[Dict[str, Any]],
    colony_count: int,
) -> List[Dict[str, Any]]:
    sites_by_region: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for site in expansion_sites:
        rk = str(site.get("region_key") or "outer_rim")
        sites_by_region[rk].append(site)

    rows: List[Dict[str, Any]] = []
    for region_key in sorted(IMPERIUM_REGIONS.keys(), key=lambda k: IMPERIUM_REGIONS[k]["sort_order"]):
        defn = IMPERIUM_REGIONS[region_key]
        zone = dict(defn["layout_zone"])
        region_sites = sites_by_region.get(region_key, [])
        teaser_count = len(region_sites)
        node_count = int(colony_count) if region_key == "genesis_core" else teaser_count
        rows.append(
            {
                "region_key": region_key,
                "label_key": str(defn.get("label_key") or region_key),
                "sort_order": int(defn.get("sort_order") or 0),
                "tone": str(defn.get("tone") or "core"),
                "layout_zone": zone,
                "node_count": node_count,
                "teaser_count": teaser_count,
                "is_dimmed": region_is_dimmed(region_key, region_sites),
            }
        )
    return rows
