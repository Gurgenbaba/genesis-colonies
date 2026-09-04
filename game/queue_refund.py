"""
GC-831 — Central queue cancel refund rules.

Genesis-style (uniform across queue types):
  - Pending (not started): 100%
  - Active (in progress): 50%
  - Completed: 0% (not cancellable)
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any, Dict, Mapping, Optional, Tuple

REFUND_RATIO_PENDING = 1.0
REFUND_RATIO_ACTIVE = 0.5
REFUND_RATIO_COMPLETED = 0.0


def refund_ratio_for_job(*, start_time: float, finish_time: float, now: float) -> float:
    ft = float(finish_time)
    st = float(start_time)
    ts = float(now)
    if ft <= ts:
        return REFUND_RATIO_COMPLETED
    if st > ts:
        return REFUND_RATIO_PENDING
    return REFUND_RATIO_ACTIVE


def refund_percent_for_ratio(ratio: float) -> int:
    return int(round(float(ratio) * 100))


def scaled_refund_amount(base: int | float, ratio: float) -> int:
    """Exact decimal refund math; never round huge queue costs through binary float."""
    try:
        amount = max(Decimal(0), Decimal(str(base)))
        factor = max(Decimal(0), Decimal(str(ratio)))
        return int((amount * factor).to_integral_value(rounding=ROUND_FLOOR))
    except (InvalidOperation, ValueError, TypeError):
        return int(math.floor(max(0.0, float(base)) * max(0.0, float(ratio))))


def apply_planet_refund(
    conn,
    planet_id: int,
    *,
    metal: int = 0,
    crystal: int = 0,
    fuel_cells: float = 0,
) -> None:
    if int(metal) <= 0 and int(crystal) <= 0 and float(fuel_cells) <= 0:
        return
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal = metal + ?,
            crystal = crystal + ?,
            fuel_cells = fuel_cells + ?
        WHERE id = ?;
        """,
        (int(metal), int(crystal), float(fuel_cells), int(planet_id)),
    )


def refund_from_stored_costs(
    conn,
    planet_id: int,
    costs: Mapping[str, Any],
    *,
    start_time: float,
    finish_time: float,
    now: float,
) -> Dict[str, Any]:
    ratio = refund_ratio_for_job(start_time=start_time, finish_time=finish_time, now=now)
    refund_m = scaled_refund_amount(costs.get("cost_metal") or costs.get("metal") or 0, ratio)
    refund_c = scaled_refund_amount(costs.get("cost_crystal") or costs.get("crystal") or 0, ratio)
    refund_f = scaled_refund_amount(costs.get("cost_fuel_cells") or costs.get("fuel_cells") or 0, ratio)
    apply_planet_refund(
        conn,
        int(planet_id),
        metal=refund_m,
        crystal=refund_c,
        fuel_cells=float(refund_f),
    )
    return {
        "refund_metal": refund_m,
        "refund_crystal": refund_c,
        "refund_fuel_cells": float(refund_f),
        "refund_ratio": ratio,
    }


def resolve_build_job_cost(
    conn,
    planet_id: int,
    *,
    job_id: int,
    building_type: str,
) -> Tuple[int, int]:
    from .buildings import get_upgrade_cost
    from .models import get_build_queue_rows, get_planet_buildings

    buildings = get_planet_buildings(int(planet_id), conn=conn)
    current_level = int(buildings.get(building_type, 0) or 0)
    position = 0
    found = False
    for row in get_build_queue_rows(int(planet_id), conn=conn):
        if str(row["building_type"]) != str(building_type):
            continue
        if int(row["id"]) == int(job_id):
            found = True
            break
        position += 1
    if not found:
        return 0, 0
    return get_upgrade_cost(str(building_type), current_level + position)


def refund_build_job(
    conn,
    planet_id: int,
    *,
    job_id: int,
    building_type: str,
    start_time: float,
    finish_time: float,
    now: float,
    cost_metal: int = 0,
    cost_crystal: int = 0,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    stored_m = int(cost_metal or 0)
    stored_c = int(cost_crystal or 0)
    if stored_m > 0 or stored_c > 0:
        cost_m, cost_c = stored_m, stored_c
    else:
        cost_m, cost_c = resolve_build_job_cost(
            conn,
            int(planet_id),
            job_id=int(job_id),
            building_type=str(building_type),
        )
    ratio = refund_ratio_for_job(start_time=start_time, finish_time=finish_time, now=now)
    refund_m = scaled_refund_amount(cost_m, ratio)
    refund_c = scaled_refund_amount(cost_c, ratio)
    apply_planet_refund(conn, int(planet_id), metal=refund_m, crystal=refund_c)
    return {
        "refund_metal": refund_m,
        "refund_crystal": refund_c,
        "refund_ratio": ratio,
        "cost_metal": int(cost_m),
        "cost_crystal": int(cost_c),
    }


def resolve_research_job_cost(
    conn,
    user_id: int,
    *,
    job_id: int,
    tech_key: str,
) -> Tuple[int, int]:
    from .models import get_research_queue_rows, get_research_levels
    from .research import get_research_cost

    levels = get_research_levels(int(user_id), conn=conn)
    current = int(levels.get(tech_key, 0) or 0)
    position = 0
    found = False
    for row in get_research_queue_rows(int(user_id), conn=conn):
        if str(row["tech_key"]) != str(tech_key):
            continue
        if int(row["id"]) == int(job_id):
            found = True
            break
        position += 1
    if not found:
        return 0, 0
    target = current + position + 1
    return get_research_cost(str(tech_key), target)


def refund_research_job(
    conn,
    planet_id: int,
    user_id: int,
    *,
    job_id: int,
    tech_key: str,
    start_time: float,
    finish_time: float,
    now: float,
    cost_metal: int = 0,
    cost_crystal: int = 0,
) -> Dict[str, Any]:
    stored_m = int(cost_metal or 0)
    stored_c = int(cost_crystal or 0)
    if stored_m > 0 or stored_c > 0:
        cost_m, cost_c = stored_m, stored_c
    else:
        cost_m, cost_c = resolve_research_job_cost(
            conn,
            int(user_id),
            job_id=int(job_id),
            tech_key=str(tech_key),
        )
    ratio = refund_ratio_for_job(start_time=start_time, finish_time=finish_time, now=now)
    refund_m = scaled_refund_amount(cost_m, ratio)
    refund_c = scaled_refund_amount(cost_c, ratio)
    apply_planet_refund(conn, int(planet_id), metal=refund_m, crystal=refund_c)
    return {
        "refund_metal": refund_m,
        "refund_crystal": refund_c,
        "refund_ratio": ratio,
        "cost_metal": int(cost_m),
        "cost_crystal": int(cost_c),
    }


def refund_planet_evolution_research_job(
    conn,
    planet_id: int,
    *,
    tech_key: str,
    target_level: int,
    start_time: float,
    finish_time: float,
    now: float,
) -> Dict[str, Any]:
    from .planet_evolution.planet_research import compute_planet_research_cost

    cost_m, cost_c = compute_planet_research_cost(str(tech_key), int(target_level))
    ratio = refund_ratio_for_job(start_time=start_time, finish_time=finish_time, now=now)
    refund_m = scaled_refund_amount(cost_m, ratio)
    refund_c = scaled_refund_amount(cost_c, ratio)
    apply_planet_refund(conn, int(planet_id), metal=refund_m, crystal=refund_c)
    return {
        "refund_metal": refund_m,
        "refund_crystal": refund_c,
        "refund_ratio": ratio,
        "cost_metal": int(cost_m),
        "cost_crystal": int(cost_c),
    }


def refund_summary_percents() -> Dict[str, int]:
    return {
        "refund_percent": refund_percent_for_ratio(REFUND_RATIO_PENDING),
        "refund_percent_pending": refund_percent_for_ratio(REFUND_RATIO_PENDING),
        "refund_percent_active": refund_percent_for_ratio(REFUND_RATIO_ACTIVE),
    }
