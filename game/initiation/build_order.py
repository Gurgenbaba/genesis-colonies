"""Best-in-Slot build-order guide for Command Initiation (mine path to L100).

Server-authoritative advice only — does not enqueue jobs (auto_empire owns AI enqueue).
Uses EffectResolver + BUILDING_REQUIREMENTS / research requirements as single math/req owners.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from ..buildings import (
    get_building_icon,
    get_building_requirements_items,
    has_building_requirements,
)
from ..effects import EffectResolver
from ..research import (
    RESEARCH_TECHS,
    get_research_requirements_items,
    has_research_requirements,
)

GOAL_BUILDINGS: Tuple[str, ...] = (
    "metal_mine",
    "crystal_mine",
    "solar_plant",
    "fuel_cell_plant",
)
GOAL_LEVEL = 100
DISPLAY_STEPS = 80
NANO_UNLOCK_MINE_FLOOR = 6
SPEED_ROI_RATIO = 1.35
ENERGY_RATIO_TARGET = 0.98
ROI_LOOKAHEAD_LEVELS = 8
ROI_MAX_REMAINING_LEVELS = 36


def plan_build_order(
    player_id: int,
    *,
    conn,
    max_steps: int | None = None,
) -> Dict[str, Any]:
    """Personalized greedy plan from the active planet toward producer L100.

    Only computes the next ``max_steps`` actions (default: display window) so page
    loads stay cheap; refresh after upgrades for the next slice.
    """
    pid = int(player_id)
    empty = {
        "ready": False,
        "goal_level": GOAL_LEVEL,
        "goals": {},
        "current": {},
        "steps": [],
        "next": None,
        "complete": False,
        "truncated": False,
        "total_steps": 0,
    }
    if pid <= 0:
        return empty

    from ..models import get_planet_buildings, get_research_levels
    from ..planet_evolution.repository import get_context_planet

    planet = get_context_planet(pid, conn=conn)
    if not planet:
        return empty

    planet_id = int(planet["id"])
    buildings = dict(get_planet_buildings(planet_id, conn=conn) or {})
    research = dict(get_research_levels(pid, conn=conn) or {})
    planet_position = int(planet.get("position") or planet.get("slot") or 0) or None

    sim_b = {str(k): int(v or 0) for k, v in buildings.items()}
    sim_r = {str(k): int(v or 0) for k, v in research.items()}

    limit = max(1, int(max_steps if max_steps is not None else DISPLAY_STEPS))
    steps: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, int]] = set()

    for _ in range(limit):
        if _goals_met(sim_b):
            break
        action = _next_action(
            sim_b,
            sim_r,
            planet_position=planet_position,
        )
        if not action:
            break
        key = (str(action["kind"]), str(action["key"]), int(action["target_level"]))
        if key in seen:
            break
        seen.add(key)
        steps.append(action)
        if action["kind"] == "build":
            sim_b[str(action["key"])] = int(action["target_level"])
        else:
            sim_r[str(action["key"])] = int(action["target_level"])

    complete = _goals_met({str(k): int(v or 0) for k, v in buildings.items()})
    for i, step in enumerate(steps):
        step["index"] = i
        step["is_next"] = i == 0

    goals = {b: GOAL_LEVEL for b in GOAL_BUILDINGS}
    current = {b: int(buildings.get(b) or 0) for b in GOAL_BUILDINGS}
    # Truncated when goals not met and we filled the display window.
    truncated = (not complete) and (len(steps) >= limit) and not _goals_met(sim_b)

    return {
        "ready": True,
        "goal_level": GOAL_LEVEL,
        "goals": goals,
        "current": current,
        "steps": steps,
        "next": steps[0] if steps else None,
        "complete": complete,
        "truncated": truncated,
        "total_steps": len(steps),
        "planet_id": planet_id,
    }


def _goals_met(buildings: Dict[str, int]) -> bool:
    return all(int(buildings.get(b) or 0) >= GOAL_LEVEL for b in GOAL_BUILDINGS)


def _resolver(
    buildings: Dict[str, int],
    research: Dict[str, int],
    *,
    planet_position: int | None,
) -> EffectResolver:
    # No conn — guide planning must not hit live GD/diplomacy DB on every step.
    return EffectResolver(
        dict(buildings),
        dict(research),
        planet_position=planet_position,
    )


def _next_action(
    buildings: Dict[str, int],
    research: Dict[str, int],
    *,
    planet_position: int | None,
) -> Optional[Dict[str, Any]]:
    er = _resolver(buildings, research, planet_position=planet_position)

    # 1) Energy gate
    total, used = er.compute_energy()
    if EffectResolver.energy_ratio(total, used) < ENERGY_RATIO_TARGET:
        step = _toward_building(
            buildings,
            research,
            "solar_plant",
            int(buildings.get("solar_plant") or 0) + 1,
            reason_key="ini_bo_reason_energy",
            er=er,
        )
        if step:
            return step

    # 2) Cap gate — need nexus path when a producer is stuck below goal
    for b in GOAL_BUILDINGS:
        cur = int(buildings.get(b) or 0)
        mx = int(er.get_max_building_level(b))
        if cur >= mx and cur < GOAL_LEVEL:
            step = _raise_cap_step(buildings, research, er=er)
            if step:
                return step
            break

    # 3) Early nanofactory unlock once economy has a base
    if int(buildings.get("nanofactory") or 0) <= 0:
        mine_floor = min(
            int(buildings.get("metal_mine") or 0),
            int(buildings.get("crystal_mine") or 0),
            int(buildings.get("solar_plant") or 0),
        )
        if mine_floor >= NANO_UNLOCK_MINE_FLOOR:
            step = _toward_building(
                buildings,
                research,
                "nanofactory",
                1,
                reason_key="ini_bo_reason_speed",
                er=er,
            )
            if step:
                return step

    # 4) Economy push while producers can still grow under the current cap
    can_grow = False
    for b in GOAL_BUILDINGS:
        cur = int(buildings.get(b) or 0)
        mx = int(er.get_max_building_level(b))
        if cur < GOAL_LEVEL and cur < mx:
            can_grow = True
            break
    if can_grow:
        # Interleave speed occasionally once nano exists (every ~5 producer levels).
        nano = int(buildings.get("nanofactory") or 0)
        mine_sum = sum(int(buildings.get(b) or 0) for b in GOAL_BUILDINGS)
        if nano > 0 and mine_sum > 0 and mine_sum % 5 == 0:
            speed = _speed_investment_step(
                buildings,
                research,
                er=er,
                planet_position=planet_position,
            )
            if speed:
                return speed
        eco = _economy_push_step(buildings, research, er=er)
        if eco:
            return eco

    # 5) Speed ROI when producers are capped or goals nearly done
    speed = _speed_investment_step(
        buildings,
        research,
        er=er,
        planet_position=planet_position,
    )
    if speed:
        return speed

    return _economy_push_step(buildings, research, er=er)


def _raise_cap_step(
    buildings: Dict[str, int],
    research: Dict[str, int],
    *,
    er: EffectResolver,
) -> Optional[Dict[str, Any]]:
    """Prefer geothermal (+2 cap) then planet core (+1), else their prereqs."""
    for key in ("geothermal_nexus", "planet_core_nexus"):
        target = int(buildings.get(key) or 0) + 1
        mx = int(er.get_max_building_level(key))
        if target > mx:
            continue
        step = _toward_building(
            buildings,
            research,
            key,
            target,
            reason_key="ini_bo_reason_cap",
            er=er,
        )
        if step:
            return step
    return None


def _speed_investment_step(
    buildings: Dict[str, int],
    research: Dict[str, int],
    *,
    er: EffectResolver,
    planet_position: int | None,
) -> Optional[Dict[str, Any]]:
    remaining_levels = _remaining_producer_levels(buildings, er=er)
    if remaining_levels <= 0:
        return None

    # Skip expensive ROI while the grind is still huge; keep speed stack climbing.
    run_roi = remaining_levels <= ROI_MAX_REMAINING_LEVELS
    nano = int(buildings.get("nanofactory") or 0)
    bt = int(research.get("buildtime_tech") or 0)
    mine_avg = sum(int(buildings.get(b) or 0) for b in GOAL_BUILDINGS) // 4

    if not run_roi:
        target_nano = min(20, max(1, mine_avg // 5))
        if nano > 0 and nano < target_nano:
            step = _toward_building(
                buildings,
                research,
                "nanofactory",
                nano + 1,
                reason_key="ini_bo_reason_speed",
                er=er,
            )
            if step:
                return step
        target_bt = min(25, max(1, mine_avg // 4))
        if nano > 0 and bt < target_bt:
            step = _toward_research(
                buildings,
                research,
                "buildtime_tech",
                bt + 1,
                reason_key="ini_bo_reason_speed",
            )
            if step:
                return step
        return None

    remaining = _remaining_goal_seconds(buildings, research, er=er)
    if remaining <= 0:
        return None

    candidates: List[Tuple[float, Dict[str, Any]]] = []

    if nano > 0:
        nxt = nano + 1
        mx = int(er.get_max_building_level("nanofactory"))
        if nxt <= mx and has_building_requirements(buildings, research, "nanofactory"):
            cost = int(er.get_build_time_seconds("nanofactory", nxt))
            bumped_b = dict(buildings)
            bumped_b["nanofactory"] = nxt
            er2 = _resolver(bumped_b, research, planet_position=planet_position)
            savings = remaining - _remaining_goal_seconds(bumped_b, research, er=er2)
            if cost > 0 and savings > cost * SPEED_ROI_RATIO:
                step = _toward_building(
                    buildings,
                    research,
                    "nanofactory",
                    nxt,
                    reason_key="ini_bo_reason_speed",
                    er=er,
                )
                if step:
                    candidates.append((savings / max(cost, 1), step))

    if bt < 40 and (
        has_research_requirements(buildings, research, "buildtime_tech") or bt > 0
    ):
        nxt = bt + 1
        cost = int(er.get_research_time_seconds("buildtime_tech", nxt))
        bumped_r = dict(research)
        bumped_r["buildtime_tech"] = nxt
        er2 = _resolver(buildings, bumped_r, planet_position=planet_position)
        savings = remaining - _remaining_goal_seconds(buildings, bumped_r, er=er2)
        if cost > 0 and savings > cost * SPEED_ROI_RATIO:
            step = _toward_research(
                buildings,
                research,
                "buildtime_tech",
                nxt,
                reason_key="ini_bo_reason_speed",
            )
            if step:
                candidates.append((savings / max(cost, 1), step))

    if nano > 0:
        cc = int(buildings.get("command_center") or 0)
        nxt = cc + 1
        mx = int(er.get_max_building_level("command_center"))
        if nxt <= mx and nxt <= 20:
            cost = int(er.get_build_time_seconds("command_center", nxt))
            bumped_b = dict(buildings)
            bumped_b["command_center"] = nxt
            er2 = _resolver(bumped_b, research, planet_position=planet_position)
            savings = remaining - _remaining_goal_seconds(bumped_b, research, er=er2)
            if cost > 0 and savings > cost * (SPEED_ROI_RATIO + 0.5):
                step = _toward_building(
                    buildings,
                    research,
                    "command_center",
                    nxt,
                    reason_key="ini_bo_reason_speed",
                    er=er,
                )
                if step:
                    candidates.append((savings / max(cost, 1), step))

    if not candidates:
        if nano > 0 and bt < 10:
            step = _toward_research(
                buildings,
                research,
                "buildtime_tech",
                bt + 1,
                reason_key="ini_bo_reason_speed",
            )
            if step:
                return step
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _remaining_producer_levels(buildings: Dict[str, int], *, er: EffectResolver) -> int:
    total = 0
    for b in GOAL_BUILDINGS:
        cur = int(buildings.get(b) or 0)
        mx = int(er.get_max_building_level(b))
        total += max(0, min(GOAL_LEVEL, mx) - cur)
    return total


def _remaining_goal_seconds(
    buildings: Dict[str, int],
    _research: Dict[str, int],
    *,
    er: EffectResolver,
) -> int:
    """Lookahead sample of remaining producer build time (not full L100 sum)."""
    total = 0
    for b in GOAL_BUILDINGS:
        cur = int(buildings.get(b) or 0)
        mx = int(er.get_max_building_level(b))
        end = min(GOAL_LEVEL, mx, cur + ROI_LOOKAHEAD_LEVELS)
        for lvl in range(cur + 1, end + 1):
            total += int(er.get_build_time_seconds(b, lvl))
    return total


def _economy_push_step(
    buildings: Dict[str, int],
    research: Dict[str, int],
    *,
    er: EffectResolver,
) -> Optional[Dict[str, Any]]:
    metal = int(buildings.get("metal_mine") or 0)
    crystal = int(buildings.get("crystal_mine") or 0)
    solar = int(buildings.get("solar_plant") or 0)
    fuel = int(buildings.get("fuel_cell_plant") or 0)

    # Keep solar slightly ahead of mines.
    mine_peak = max(metal, crystal)
    if solar < min(GOAL_LEVEL, mine_peak + 1):
        mx = int(er.get_max_building_level("solar_plant"))
        if solar < mx:
            return _toward_building(
                buildings,
                research,
                "solar_plant",
                solar + 1,
                reason_key="ini_bo_reason_energy",
                er=er,
            )

    # Early unlocks that enable the efficient path (lab / fuel).
    if metal < 3 or crystal < 2:
        lag = "metal_mine" if metal <= crystal else "crystal_mine"
        if lag == "crystal_mine" and crystal < 2:
            lag = "crystal_mine"
        elif metal < 3:
            lag = "metal_mine"
        cur = int(buildings.get(lag) or 0)
        mx = int(er.get_max_building_level(lag))
        if cur < mx:
            return _toward_building(
                buildings,
                research,
                lag,
                cur + 1,
                reason_key="ini_bo_reason_mine",
                er=er,
            )

    if int(buildings.get("research_lab") or 0) < 1 and metal >= 3 and crystal >= 2:
        return _toward_building(
            buildings,
            research,
            "research_lab",
            1,
            reason_key="ini_bo_reason_mine",
            er=er,
        )

    if int(research.get("energy_tech") or 0) < 1 and int(buildings.get("research_lab") or 0) >= 1:
        return _toward_research(
            buildings,
            research,
            "energy_tech",
            1,
            reason_key="ini_bo_reason_mine",
        )

    if fuel < 1 and solar >= 1 and crystal >= 2:
        return _toward_building(
            buildings,
            research,
            "fuel_cell_plant",
            1,
            reason_key="ini_bo_reason_mine",
            er=er,
        )

    if int(research.get("mining_tech") or 0) < 1 and int(buildings.get("research_lab") or 0) >= 1:
        return _toward_research(
            buildings,
            research,
            "mining_tech",
            1,
            reason_key="ini_bo_reason_mine",
        )

    # Raise lagging producer among the four goals.
    candidates: List[Tuple[int, str]] = []
    for b in GOAL_BUILDINGS:
        cur = int(buildings.get(b) or 0)
        if cur >= GOAL_LEVEL:
            continue
        mx = int(er.get_max_building_level(b))
        if cur >= mx:
            continue
        candidates.append((cur, b))
    if not candidates:
        return _raise_cap_step(buildings, research, er=er)

    candidates.sort(key=lambda x: (x[0], GOAL_BUILDINGS.index(x[1])))
    lag_key = candidates[0][1]
    return _toward_building(
        buildings,
        research,
        lag_key,
        int(buildings.get(lag_key) or 0) + 1,
        reason_key="ini_bo_reason_mine",
        er=er,
    )


def _toward_building(
    buildings: Dict[str, int],
    research: Dict[str, int],
    key: str,
    target_level: int,
    *,
    reason_key: str,
    er: EffectResolver,
    _depth: int = 0,
) -> Optional[Dict[str, Any]]:
    if _depth > 24:
        return None
    key = str(key)
    cur = int(buildings.get(key) or 0)
    need = max(1, int(target_level))
    if cur >= need:
        return None

    mx = int(er.get_max_building_level(key))
    if cur >= mx:
        # Cap blocks this building — raise nexus instead.
        return _raise_cap_step(buildings, research, er=er) if key not in (
            "geothermal_nexus",
            "planet_core_nexus",
        ) else None

    if not has_building_requirements(buildings, research, key):
        items = get_building_requirements_items(key, buildings, research)
        for item in items:
            if item.get("met"):
                continue
            if item.get("kind") == "building":
                step = _toward_building(
                    buildings,
                    research,
                    str(item["key"]),
                    int(item["need"]),
                    reason_key=reason_key,
                    er=er,
                    _depth=_depth + 1,
                )
                if step:
                    return step
            elif item.get("kind") == "research":
                step = _toward_research(
                    buildings,
                    research,
                    str(item["key"]),
                    int(item["need"]),
                    reason_key=reason_key,
                    _depth=_depth + 1,
                )
                if step:
                    return step
        return None

    nxt = cur + 1
    return _serialize_step(
        kind="build",
        key=key,
        target_level=nxt,
        current_level=cur,
        reason_key=reason_key,
    )


def _toward_research(
    buildings: Dict[str, int],
    research: Dict[str, int],
    key: str,
    target_level: int,
    *,
    reason_key: str,
    _depth: int = 0,
) -> Optional[Dict[str, Any]]:
    if _depth > 24:
        return None
    key = str(key)
    if key not in RESEARCH_TECHS:
        return None
    cur = int(research.get(key) or 0)
    need = max(1, int(target_level))
    if cur >= need:
        return None

    if not has_research_requirements(buildings, research, key):
        items = get_research_requirements_items(key, buildings, research)
        for item in items:
            if item.get("met"):
                continue
            if item.get("kind") == "building":
                # Need a resolver for building path; use empty-effects-safe helper.
                er = EffectResolver(dict(buildings), dict(research))
                step = _toward_building(
                    buildings,
                    research,
                    str(item["key"]),
                    int(item["need"]),
                    reason_key=reason_key,
                    er=er,
                    _depth=_depth + 1,
                )
                if step:
                    return step
            elif item.get("kind") == "research":
                step = _toward_research(
                    buildings,
                    research,
                    str(item["key"]),
                    int(item["need"]),
                    reason_key=reason_key,
                    _depth=_depth + 1,
                )
                if step:
                    return step
        return None

    nxt = cur + 1
    return _serialize_step(
        kind="research",
        key=key,
        target_level=nxt,
        current_level=cur,
        reason_key=reason_key,
    )


def _serialize_step(
    *,
    kind: str,
    key: str,
    target_level: int,
    current_level: int,
    reason_key: str,
) -> Dict[str, Any]:
    if kind == "research":
        cfg = RESEARCH_TECHS.get(key) or {}
        icon = str(cfg.get("icon") or "bauoptimierung.png")
        image = f"img/research/{icon}" if not icon.startswith("img/") else icon
        route = "/research?" + urlencode({"highlight": key})
        title_key = str(cfg.get("label_key") or key)
    else:
        image = get_building_icon(key)
        route = "/buildings?" + urlencode({"highlight": key})
        title_key = key

    return {
        "kind": kind,
        "key": key,
        "target_level": int(target_level),
        "current_level": int(current_level),
        "reason_key": reason_key,
        "route": route,
        "image": image.lstrip("/"),
        "title_key": title_key,
        "label_fallback": key,
    }
