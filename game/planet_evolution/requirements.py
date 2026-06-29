"""Requirement validation for planet evolution actions."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple, Union

from ..models import get_planet_buildings, get_research_levels
from .dna import all_trait_keys
from .repository import (
    get_discoveries,
    get_locked_choices,
    get_planet_dna,
    get_planet_research_levels,
    get_planet_row,
)


def _as_dict(raw: Any) -> Dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def check_requirements(
    planet_id: int,
    requirements_json: Union[Dict[str, Any], str, None],
    conn: sqlite3.Connection,
) -> Tuple[bool, List[str]]:
    req = _as_dict(requirements_json)
    if not req:
        return True, []

    missing: List[str] = []
    planet = get_planet_row(planet_id, conn=conn) or {}
    player_id = planet.get("player_id")
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    planet_research = get_planet_research_levels(planet_id, conn=conn)
    imperial = get_research_levels(int(player_id), conn=conn) if player_id else {}

    dna = get_planet_dna(planet_id, conn=conn) or {}
    reveal = int(planet.get("dna_reveal_tier") or 0)
    traits = set(all_trait_keys(dna, reveal_tier=max(reveal, 1)))
    locked = get_locked_choices(planet_id, conn=conn)

    if "planet_level_min" in req:
        need = int(req["planet_level_min"])
        if int(planet.get("planet_level") if planet.get("planet_level") is not None else 0) < need:
            missing.append(f"planet_level>={need}")

    if "specialization_tier_min" in req:
        need = int(req["specialization_tier_min"])
        if int(planet.get("specialization_tier") or 0) < need:
            missing.append(f"specialization_tier>={need}")

    if "specialization" in req:
        spec = str(req["specialization"])
        if str(planet.get("specialization_key") or "") != spec:
            missing.append(f"specialization={spec}")

    for b_key, need_lvl in (_as_dict(req.get("buildings"))).items():
        if int(buildings.get(str(b_key), 0) or 0) < int(need_lvl):
            missing.append(f"building:{b_key}>={need_lvl}")

    for r_key, need_lvl in (_as_dict(req.get("planet_research"))).items():
        if int(planet_research.get(str(r_key), 0) or 0) < int(need_lvl):
            missing.append(f"planet_research:{r_key}>={need_lvl}")

    pr_any = req.get("planet_research_any")
    if pr_any is not None:
        if isinstance(pr_any, list):
            min_lvl = int(req.get("planet_research_any_min", 1))
            if not any(int(planet_research.get(str(r_key), 0) or 0) >= min_lvl for r_key in pr_any):
                missing.append(f"planet_research_any:{pr_any}>={min_lvl}")
        elif isinstance(pr_any, dict):
            if not any(
                int(planet_research.get(str(r_key), 0) or 0) >= int(need_lvl)
                for r_key, need_lvl in pr_any.items()
            ):
                missing.append(f"planet_research_any:{list(pr_any.keys())}")
        else:
            missing.append("planet_research_any:invalid")

    for r_key, need_lvl in (_as_dict(req.get("imperial_research"))).items():
        if int(imperial.get(str(r_key), 0) or 0) < int(need_lvl):
            missing.append(f"imperial_research:{r_key}>={need_lvl}")

    traits_any = req.get("traits_any") or []
    if traits_any and not any(str(t) in traits for t in traits_any):
        missing.append(f"traits_any:{traits_any}")

    traits_none = req.get("traits_none") or []
    for t in traits_none:
        if str(t) in traits:
            missing.append(f"traits_none:{t}")

    for group, choice in (_as_dict(req.get("locked_choices"))).items():
        if str(locked.get(str(group), "")) != str(choice):
            missing.append(f"locked_choice:{group}={choice}")

    archetypes = req.get("culture_archetype_any") or []
    if archetypes:
        current = str(planet.get("culture_archetype") or "")
        if current not in [str(a) for a in archetypes]:
            missing.append(f"culture_archetype_any:{archetypes}")

    discoveries_any = req.get("discoveries_any") or []
    if discoveries_any:
        have = {str(d["discovery_key"]) for d in get_discoveries(planet_id, conn=conn)}
        if not any(str(k) in have for k in discoveries_any):
            missing.append(f"discoveries_any:{discoveries_any}")

    culture_min = _as_dict(req.get("culture_min"))
    if culture_min:
        from .repository import get_planet_culture

        culture = get_planet_culture(planet_id, conn=conn)
        for stat, minimum in culture_min.items():
            val = float(culture.get(str(stat), 0) or 0)
            if val < float(minimum):
                missing.append(f"culture:{stat}>={minimum}")

    history_tags_any = req.get("history_tags_any") or []
    if history_tags_any:
        from .repository import get_legacy_tags

        tags = set(get_legacy_tags(planet_id, conn=conn))
        if not any(str(t) in tags for t in history_tags_any):
            missing.append(f"history_tags_any:{history_tags_any}")

    pr_min = _as_dict(req.get("planet_research_min"))
    if pr_min.get("any_t5_completed"):
        need = int(pr_min["any_t5_completed"])
        from .definitions import get_research_defs

        t5_done = 0
        for tech_key, lvl in planet_research.items():
            if int(lvl) <= 0:
                continue
            rdef = get_research_defs().get(tech_key) or {}
            if int(rdef.get("tier") or 0) >= 5:
                t5_done += 1
        if t5_done < need:
            missing.append(f"planet_research_t5>={need}")

    return len(missing) == 0, missing
