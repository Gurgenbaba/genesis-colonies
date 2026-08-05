"""Map initiation steps to world-state progress (building/tech levels, hangar, …)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def world_progress_for_step(
    player_id: int,
    step: Dict[str, Any] | None,
    *,
    conn,
) -> Optional[int]:
    """
    Absolute progress from live colony/account state for credit-capable steps.

    Returns None when the step is event-only (visits / fleet sends without history gate).
    Building/research targets are **level thresholds** (have Solar ≥ 3), not "build N more".
    """
    if not step:
        return None
    pid = int(player_id)
    if pid <= 0:
        return None

    objective = str(step.get("objective_key") or "")
    filters = step.get("filters") if isinstance(step.get("filters"), dict) else {}
    target = max(1, int(step.get("target") or 1))

    if objective == "upgrade_buildings":
        types = [str(x) for x in (filters.get("building_types") or []) if str(x).strip()]
        if not types:
            return None
        from ..models import get_planet_buildings
        from ..planet_evolution.repository import get_context_planet

        planet = get_context_planet(pid, conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        level = max(int(buildings.get(b) or 0) for b in types)
        return min(target, max(0, level))

    if objective == "complete_research":
        from ..models import get_research_levels

        levels = get_research_levels(pid, conn=conn) or {}
        keys = [str(x) for x in (filters.get("research_keys") or []) if str(x).strip()]
        if keys:
            level = max(int(levels.get(k) or 0) for k in keys)
            return min(target, max(0, level))
        # Any completed research counts as 1 toward a generic research step.
        any_lvl = 1 if any(int(v or 0) > 0 for v in levels.values()) else 0
        return min(target, any_lvl)

    if objective == "build_ships":
        from ..fleet import get_planet_ships
        from ..planet_evolution.repository import get_context_planet

        planet = get_context_planet(pid, conn=conn)
        ships = get_planet_ships(int(planet["id"]), conn=conn) or {}
        total = sum(int(v or 0) for v in ships.values())
        return min(target, 1 if total > 0 else 0)

    if objective == "build_defense":
        from ..models import get_player_defense_counts

        counts = get_player_defense_counts(pid, conn=conn) or {}
        total = sum(int(v or 0) for v in counts.values())
        return min(target, 1 if total > 0 else 0)

    return None
