"""Ship unlock prerequisites (buildings + research)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Tuple

from .fleet_defs import get_ship

# Orbital shipyard level is exposed via required_shipyard_level on catalog rows.
_SHIPYARD_BUILDING_KEYS = frozenset({"orbital_shipyard", "shipyard"})


def _building_level(buildings: Mapping[str, Any], key: str) -> int:
    return int(buildings.get(key, 0) or 0)


def _research_level(research: Mapping[str, Any], key: str) -> int:
    return int(research.get(key, 0) or 0)


def check_ship_requirements(
    ship_key: str,
    *,
    buildings: Mapping[str, Any],
    research: Mapping[str, Any],
) -> Tuple[bool, List[str]]:
    spec = get_ship(ship_key)
    if not spec:
        return False, ["ship_detail_not_found"]
    req = spec.get("requirements") or {}
    missing: List[str] = []

    for bkey, need in (req.get("buildings") or {}).items():
        have = _building_level(buildings, str(bkey))
        if have < int(need):
            missing.append(f"ship_req_building_{bkey}_{need}")

    for rkey, need in (req.get("research") or {}).items():
        have = _research_level(research, str(rkey))
        if have < int(need):
            missing.append(f"ship_req_research_{rkey}_{need}")

    return (len(missing) == 0), missing


def requirements_summary_for_client(
    ship_key: str,
    *,
    buildings: Mapping[str, Any],
    research: Mapping[str, Any],
) -> Dict[str, Any]:
    ok, missing = check_ship_requirements(ship_key, buildings=buildings, research=research)
    spec = get_ship(ship_key) or {}
    req = spec.get("requirements") or {}
    items: List[Dict[str, Any]] = []
    for bkey, need in sorted((req.get("buildings") or {}).items()):
        bkey_s = str(bkey)
        if bkey_s in _SHIPYARD_BUILDING_KEYS:
            continue
        have = _building_level(buildings, bkey_s)
        items.append(
            {
                "type": "building",
                "key": str(bkey),
                "required": int(need),
                "current": have,
                "met": have >= int(need),
            }
        )
    for rkey, need in sorted((req.get("research") or {}).items()):
        have = _research_level(research, str(rkey))
        items.append(
            {
                "type": "research",
                "key": str(rkey),
                "required": int(need),
                "current": have,
                "met": have >= int(need),
            }
        )
    return {"met": ok, "missing_keys": missing, "items": items}
