"""Defense unit detail card payload for the global properties modal."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from .combat_models import combat_stats_for_defense
from .defense_defs import defense_icon_static_path, get_defense, unit_build_cost

DefenseDetailCard = Dict[str, Any]
DefenseDetailError = str | None


def build_defense_detail_card(
    defense_key: str,
    *,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
) -> Tuple[DefenseDetailCard | None, DefenseDetailError]:
    key = str(defense_key or "").strip()
    spec = get_defense(key)
    if not spec:
        return None, "defense_detail_not_found"

    stats = combat_stats_for_defense(key)
    cost = unit_build_cost(key)
    build_cost = spec.get("build_cost") or cost

    card: DefenseDetailCard = {
        "defense_key": key,
        "name_key": spec.get("name_key", f"defense_{key}"),
        "description_key": spec.get("description_key", ""),
        "role": spec.get("role", "turret"),
        "role_key": f"defense_role_{spec.get('role', 'turret')}",
        "attack": int(stats.attack if stats else spec.get("attack", 0) or 0),
        "shield": int(stats.shield if stats else spec.get("shield", 0) or 0),
        "hull": int(stats.hull if stats else spec.get("hull", 0) or 0),
        "score_value": int(stats.score_value if stats else spec.get("score_value", 0) or 0),
        "icon": defense_icon_static_path(key),
        "build_cost_metal": int(build_cost.get("metal", 0) or 0),
        "build_cost_crystal": int(build_cost.get("crystal", 0) or 0),
        "build_seconds": int(spec.get("build_seconds", 0) or 0),
        "required_defense_factory_level": int(
            spec.get("required_defense_factory_level", 0) or 0
        ),
    }
    if buildings is not None and research is not None:
        from .defense_requirements import requirements_summary_for_client

        req_summary = requirements_summary_for_client(
            key, buildings=buildings, research=research
        )
        card["requirements"] = req_summary
        card["requirements_items"] = list(req_summary.get("items") or [])
    return card, None
