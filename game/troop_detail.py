"""Ground troop detail card payload for the global properties modal."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from .shipyard import production_metrics_at_yard
from .troop_defs import (
    get_troop,
    troop_icon_static_path,
    troop_score_value,
    troop_train_cost,
)
from .troops import base_unit_seconds_for_troop, unit_train_seconds

TroopDetailCard = Dict[str, Any]
TroopDetailError = str | None


def build_troop_detail_card(
    troop_key: str,
    *,
    buildings: Mapping[str, Any] | None = None,
) -> Tuple[TroopDetailCard | None, TroopDetailError]:
    key = str(troop_key or "").strip()
    spec = get_troop(key)
    if not spec:
        return None, "troop_detail_not_found"

    cost = troop_train_cost(key)
    req_barracks = int(spec.get("required_barracks_level") or 0)
    barracks_lvl = 0
    if buildings is not None:
        barracks_lvl = max(0, int(buildings.get("barracks") or 0))
    prod_lvl = max(1, barracks_lvl) if barracks_lvl > 0 else 1
    base_sec = base_unit_seconds_for_troop(key)
    cycle_sec = unit_train_seconds(key, prod_lvl)

    requirements_items = [
        {
            "type": "building",
            "key": "barracks",
            "required": req_barracks,
            "current": barracks_lvl,
            "met": barracks_lvl >= req_barracks,
        }
    ]

    card: TroopDetailCard = {
        "troop_key": key,
        "name_key": spec.get("name_key", f"troop_{key}"),
        "description_key": spec.get("description_key", ""),
        "role": "ground",
        "role_key": "troop_role_ground",
        "attack": int(spec.get("attack") or 0),
        "defense": int(spec.get("defense") or 0),
        "hull": int(spec.get("hull") or 0),
        "cargo_slots": max(1, int(spec.get("cargo_slots") or 1)),
        "score_value": troop_score_value(key),
        "icon": troop_icon_static_path(key),
        "train_cost_metal": int(cost.get("metal") or 0),
        "train_cost_crystal": int(cost.get("crystal") or 0),
        "train_cost_fuel_cells": int(cost.get("fuel_cells") or 0),
        "train_seconds": cycle_sec,
        "required_barracks_level": req_barracks,
        "requirements_items": requirements_items,
        "production": production_metrics_at_yard(
            base_unit_seconds=base_sec,
            shipyard_level=prod_lvl,
            effective_unit_seconds=cycle_sec,
        ),
    }
    return card, None
