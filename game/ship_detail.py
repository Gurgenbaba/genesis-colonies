"""Ship detail card payload for the global ship properties modal."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from game.fleet_defs import canonical_ship_key, get_ship, ship_icon_static_path

ShipDetailCard = Dict[str, Any]
ShipDetailError = str | None


def build_ship_detail_card(
    ship_key: str,
    *,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
) -> Tuple[ShipDetailCard | None, ShipDetailError]:
    key = canonical_ship_key(ship_key)
    spec = get_ship(key)
    if not spec:
        return None, "ship_detail_not_found"

    build_cost = spec.get("build_cost") or {}
    card: ShipDetailCard = {
        "ship_key": key,
        "name_key": spec.get("name_key", f"fleet_ship_{key}"),
        "description_key": spec.get("description_key", ""),
        "role": spec.get("role", ""),
        "role_key": f"shipyard_role_{spec.get('role', '')}",
        "speed": int(spec.get("speed", 0) or 0),
        "cargo": int(spec.get("cargo", 0) or 0),
        "fuel": int(spec.get("fuel", 0) or 0),
        "attack": int(spec.get("attack", 0) or 0),
        "shield": int(spec.get("shield", 0) or 0),
        "hull": int(spec.get("hull", 0) or 0),
        "crew": spec.get("crew"),
        "icon": ship_icon_static_path(key),
        "build_cost_metal": int(build_cost.get("metal", 0) or 0),
        "build_cost_crystal": int(build_cost.get("crystal", 0) or 0),
        "build_cost_fuel_cells": int(build_cost.get("fuel_cells", 0) or 0),
        "build_seconds": int(spec.get("build_seconds", 0) or 0),
        "required_shipyard_level": int(spec.get("required_shipyard_level", 0) or 0),
        "phase2_only": bool(spec.get("phase2_only")),
    }
    if buildings is not None and research is not None:
        from game.ship_requirements import requirements_summary_for_client

        req_summary = requirements_summary_for_client(
            key, buildings=buildings, research=research
        )
        card["requirements"] = req_summary
        card["requirements_items"] = list(req_summary.get("items") or [])
    return card, None
