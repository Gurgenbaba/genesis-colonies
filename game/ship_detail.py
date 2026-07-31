"""Ship detail card payload for the global ship properties modal."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from game.fleet_defs import canonical_ship_key, get_ship, ship_icon_static_path
from game.shipyard import (
    base_unit_seconds_for_ship,
    production_metrics_at_yard,
    shipyard_level_from_buildings,
    unit_build_seconds,
)

ShipDetailCard = Dict[str, Any]
ShipDetailError = str | None


def build_ship_detail_card(
    ship_key: str,
    *,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
    player_id: int | None = None,
    conn=None,
    planet: Mapping[str, Any] | None = None,
    effect_ctx: Mapping[str, Any] | None = None,
) -> Tuple[ShipDetailCard | None, ShipDetailError]:
    key = canonical_ship_key(ship_key)
    spec = get_ship(key)
    if not spec:
        return None, "ship_detail_not_found"

    build_cost = spec.get("build_cost") or {}
    base_speed = int(spec.get("speed", 0) or 0)
    base_cargo = int(spec.get("cargo", 0) or 0)
    base_fuel = int(spec.get("fuel", 0) or 0)
    base_attack = int(spec.get("attack", 0) or 0)
    base_shield = int(spec.get("shield", 0) or 0)
    base_hull = int(spec.get("hull", 0) or 0)

    card: ShipDetailCard = {
        "ship_key": key,
        "name_key": spec.get("name_key", f"fleet_ship_{key}"),
        "description_key": spec.get("description_key", ""),
        "role": spec.get("role", ""),
        "role_key": f"shipyard_role_{spec.get('role', '')}",
        "speed": base_speed,
        "cargo": base_cargo,
        "fuel": base_fuel,
        "attack": base_attack,
        "shield": base_shield,
        "hull": base_hull,
        "crew": spec.get("crew"),
        "icon": ship_icon_static_path(key),
        "build_cost_metal": int(build_cost.get("metal", 0) or 0),
        "build_cost_crystal": int(build_cost.get("crystal", 0) or 0),
        "build_cost_fuel_cells": int(build_cost.get("fuel_cells", 0) or 0),
        "build_seconds": int(spec.get("build_seconds", 0) or 0),
        "required_shipyard_level": int(spec.get("required_shipyard_level", 0) or 0),
        "phase2_only": bool(spec.get("phase2_only")),
    }
    sy_level = shipyard_level_from_buildings(buildings)
    card["production"] = production_metrics_at_yard(
        base_unit_seconds=base_unit_seconds_for_ship(key),
        shipyard_level=sy_level,
        effective_unit_seconds=unit_build_seconds(key, sy_level),
    )
    if buildings is not None and research is not None:
        from game.ship_requirements import requirements_summary_for_client
        from game.technical_data import build_unit_technical_block

        req_summary = requirements_summary_for_client(
            key, buildings=buildings, research=research
        )
        card["requirements"] = req_summary
        card["requirements_items"] = list(req_summary.get("items") or [])
        card["technical"] = build_unit_technical_block(
            base_attack=base_attack,
            base_shield=base_shield,
            base_hull=base_hull,
            base_build_seconds=int(card["build_seconds"]),
            production=card["production"],
            buildings=buildings,
            research_levels=research,
            next_yard_unit_seconds=unit_build_seconds(key, sy_level + 1),
            player_id=player_id,
            conn=conn,
            planet=planet,
            base_speed=base_speed,
            base_cargo=base_cargo,
            base_fuel=base_fuel,
            effect_ctx=effect_ctx,
        )
        mobility = (card["technical"] or {}).get("mobility") or {}
        for mob_key in ("speed", "cargo", "fuel"):
            stat = mobility.get(mob_key)
            if isinstance(stat, dict):
                card[mob_key] = int(stat.get("effective") or 0)
                card[f"{mob_key}_stat"] = stat
        combat = (card["technical"] or {}).get("combat") or {}
        for combat_key in ("attack", "shield", "hull"):
            if combat.get(combat_key) is not None:
                card[combat_key] = int(combat.get(combat_key) or 0)
            stat = combat.get(f"{combat_key}_stat")
            if isinstance(stat, dict):
                card[f"{combat_key}_stat"] = stat
        from game.combat_models import build_rapid_fire_matchup_payload

        card["technical"].update(build_rapid_fire_matchup_payload(key, "ship"))
    return card, None
