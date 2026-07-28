"""Shared passive empire planner (EPIC-26 / GC-2600).

Canonical enqueue path for buildings, research, defense, and optional ships.
Used by pirate AI (duration caps + ships) and inactive autoplay (real durations, no ships).
No second queue engine — owners remain buildings / research / defense / shipyard.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# Building ladder (early empire → combat infrastructure).
BUILD_PRIORITY: List[str] = [
    "metal_mine",
    "crystal_mine",
    "solar_plant",
    "fuel_cell_plant",
    "command_center",
    "research_lab",
    "metal_storage",
    "crystal_storage",
    "orbital_shipyard",
    "barracks",
    "defense_factory",
    "radar_array",
    "shield_generator",
    "fuel_storage",
]

BUILD_TARGETS: Dict[str, int] = {
    "metal_mine": 16,
    "crystal_mine": 14,
    "solar_plant": 16,
    "fuel_cell_plant": 12,
    "command_center": 8,
    "research_lab": 10,
    "metal_storage": 8,
    "crystal_storage": 8,
    "fuel_storage": 6,
    "orbital_shipyard": 10,
    "barracks": 6,
    "defense_factory": 7,
    "radar_array": 4,
    "shield_generator": 5,
}

RESEARCH_PRIORITY: List[str] = [
    "energy_tech",
    "mining_tech",
    "storage_tech",
    "drone_tech",
    "weapon_tech",
    "armor_tech",
    "shield_tech",
    "engine_tech",
    "navigation_tech",
    "fuel_efficiency",
    "buildtime_tech",
]

RESEARCH_TARGETS: Dict[str, int] = {
    "energy_tech": 8,
    "mining_tech": 7,
    "storage_tech": 8,
    "drone_tech": 6,
    "weapon_tech": 10,
    "armor_tech": 7,
    "shield_tech": 7,
    "engine_tech": 8,
    "navigation_tech": 7,
    "fuel_efficiency": 5,
    "buildtime_tech": 5,
}

PERSONALITY_SHIP_BIAS: Dict[str, List[Tuple[str, int]]] = {
    "aggressive": [
        ("falcon_interceptor", 24),
        ("ironclad_frigate", 12),
        ("spark_drone", 30),
        ("eclipse_runner", 4),
        ("solar_skiff", 2),
        ("veil_probe", 8),
        ("harvest_reclaimer", 2),
        ("seed_ark", 1),
    ],
    "turtle": [
        ("ironclad_frigate", 18),
        ("falcon_interceptor", 10),
        ("spark_drone", 16),
        ("atlas_hauler", 6),
        ("solar_skiff", 2),
        ("veil_probe", 6),
        ("harvest_reclaimer", 3),
        ("seed_ark", 1),
    ],
    "spy": [
        ("veil_probe", 24),
        ("falcon_interceptor", 12),
        ("spark_drone", 16),
        ("eclipse_runner", 4),
        ("solar_skiff", 2),
        ("ironclad_frigate", 4),
        ("harvest_reclaimer", 2),
        ("seed_ark", 1),
    ],
    "swarm": [
        ("spark_drone", 60),
        ("falcon_interceptor", 16),
        ("veil_probe", 10),
        ("solar_skiff", 2),
        ("ironclad_frigate", 4),
        ("harvest_reclaimer", 2),
        ("seed_ark", 1),
    ],
    "elite": [
        ("ironclad_frigate", 16),
        ("falcon_interceptor", 20),
        ("eclipse_runner", 6),
        ("solar_skiff", 3),
        ("spark_drone", 20),
        ("veil_probe", 8),
        ("harvest_reclaimer", 2),
        ("seed_ark", 1),
    ],
    "economy": [
        ("atlas_hauler", 10),
        ("ironclad_frigate", 10),
        ("falcon_interceptor", 8),
        ("spark_drone", 12),
        ("solar_skiff", 2),
        ("veil_probe", 6),
        ("harvest_reclaimer", 4),
        ("seed_ark", 2),
    ],
}

PERSONALITY_DEFENSE_BIAS: Dict[str, List[Tuple[str, int]]] = {
    "aggressive": [("slug_launcher", 30), ("sentinel_turret", 16), ("plasma_arc", 8)],
    "turtle": [
        ("slug_launcher", 55),
        ("sentinel_turret", 35),
        ("plasma_arc", 18),
        ("ion_bastion", 10),
        ("pulse_barrier", 6),
    ],
    "spy": [("slug_launcher", 20), ("sentinel_turret", 14), ("flak_array", 8)],
    "swarm": [("slug_launcher", 35), ("sentinel_turret", 18), ("flak_array", 12)],
    "elite": [
        ("slug_launcher", 40),
        ("sentinel_turret", 25),
        ("plasma_arc", 12),
        ("ion_bastion", 6),
    ],
    "economy": [("slug_launcher", 45), ("sentinel_turret", 28), ("plasma_arc", 10)],
}

COLONY_BUILD_PRIORITY: List[str] = [
    "metal_mine",
    "crystal_mine",
    "solar_plant",
    "fuel_cell_plant",
    "metal_storage",
    "crystal_storage",
    "command_center",
    "orbital_shipyard",
    "defense_factory",
    "barracks",
]

# Pirate Soft-On: shorten jobs so bots progress on worker cadence.
PIRATE_BUILD_DURATION_CAP = 90
PIRATE_RESEARCH_DURATION_CAP = 120


def _now() -> float:
    return time.time()


def _queue_has_building(conn, planet_id: int) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM build_queue WHERE planet_id = ? LIMIT 1;",
        (int(planet_id),),
    )
    return cur.fetchone() is not None


def _queue_has_research(conn, player_id: int) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM research_queue WHERE user_id = ? LIMIT 1;",
        (int(player_id),),
    )
    return cur.fetchone() is not None


def try_enqueue_building(
    conn,
    *,
    player_id: int,
    planet: Mapping[str, Any],
    building_type: str,
    now: float,
    duration_cap: Optional[int] = None,
) -> Dict[str, Any]:
    from .buildings import (
        BuildingsPanelContext,
        get_upgrade_cost,
        has_building_requirements,
    )
    from .models import (
        add_build_job,
        get_build_queue_rows,
        get_planet_buildings,
        get_research_levels,
        try_spend_resources_conn,
    )

    planet_id = int(planet["id"])
    if _queue_has_building(conn, planet_id):
        return {"ok": False, "error": "queue_busy"}

    buildings = get_planet_buildings(planet_id, conn=conn)
    research = get_research_levels(player_id, conn=conn)
    current = int(buildings.get(building_type, 0) or 0)
    target_cap = int(BUILD_TARGETS.get(building_type, 8))
    if current >= target_cap:
        return {"ok": False, "error": "at_target"}
    if not has_building_requirements(buildings, research, building_type):
        return {"ok": False, "error": "requirements"}

    cost_m, cost_c = get_upgrade_cost(building_type, current)
    if not try_spend_resources_conn(conn, planet_id, int(cost_m), int(cost_c)):
        return {"ok": False, "error": "resources"}

    hotpath = BuildingsPanelContext.for_queue_recalc(
        player_id, buildings, research, conn=conn
    )
    target_level = current + 1
    duration = int(hotpath.build_time_seconds(building_type, target_level))
    if duration_cap is not None:
        duration = max(5, min(duration, int(duration_cap)))
    else:
        duration = max(5, duration)
    rows = list(get_build_queue_rows(planet_id, conn=conn))
    last_finish = max((float(r["finish_time"]) for r in rows), default=now)
    start_time = max(now, last_finish)
    finish_time = start_time + duration
    job_id = add_build_job(
        planet_id,
        building_type,
        start_time,
        finish_time,
        conn=conn,
        cost_metal=int(cost_m),
        cost_crystal=int(cost_c),
    )
    return {
        "ok": True,
        "job_id": int(job_id),
        "building_type": building_type,
        "target_level": target_level,
        "duration": duration,
    }


def try_enqueue_research(
    conn,
    *,
    player_id: int,
    tech_key: str,
    now: float,
    duration_cap: Optional[int] = None,
) -> Dict[str, Any]:
    from .models import (
        add_research_job,
        get_homeworld,
        get_planet_buildings,
        get_research_levels,
        get_research_queue_rows,
        try_spend_resources_conn,
    )
    from .research import (
        RESEARCH_TECHS,
        get_research_cost,
        get_research_time,
        has_research_requirements,
        resolve_buildings_for_research,
    )

    if tech_key not in RESEARCH_TECHS:
        return {"ok": False, "error": "unknown_tech"}
    if _queue_has_research(conn, player_id):
        return {"ok": False, "error": "queue_busy"}

    home = get_homeworld(player_id, conn=conn)
    if not home:
        return {"ok": False, "error": "no_homeworld"}
    planet_id = int(home["id"])
    buildings = resolve_buildings_for_research(
        get_planet_buildings(planet_id, conn=conn),
        player_id,
        conn=conn,
    )
    levels = get_research_levels(player_id, conn=conn)
    if int(buildings.get("research_lab", 0) or 0) <= 0:
        return {"ok": False, "error": "no_lab"}
    current = int(levels.get(tech_key, 0) or 0)
    if current >= int(RESEARCH_TARGETS.get(tech_key, 5)):
        return {"ok": False, "error": "at_target"}
    if not has_research_requirements(buildings, levels, tech_key):
        return {"ok": False, "error": "requirements"}

    target = current + 1
    cost_m, cost_c = get_research_cost(tech_key, target)
    if not try_spend_resources_conn(conn, planet_id, int(cost_m), int(cost_c)):
        return {"ok": False, "error": "resources"}

    duration = int(
        get_research_time(tech_key, target, user_id=player_id, buildings=buildings)
    )
    if duration_cap is not None:
        duration = max(5, min(duration, int(duration_cap)))
    else:
        duration = max(5, duration)
    rows = list(get_research_queue_rows(player_id, conn=conn))
    last_finish = max((float(r["finish_at"]) for r in rows), default=now)
    start_time = max(now, last_finish)
    finish_time = start_time + duration
    job_id = add_research_job(
        player_id,
        tech_key,
        start_time,
        finish_time,
        conn=conn,
        cost_metal=int(cost_m),
        cost_crystal=int(cost_c),
    )
    return {
        "ok": True,
        "job_id": int(job_id),
        "tech_key": tech_key,
        "target_level": target,
        "duration": duration,
    }


def try_build_ships(
    conn,
    *,
    player_id: int,
    planet_id: int,
    personality: str,
) -> Dict[str, Any]:
    from .fleet import get_planet_ships
    from .shipyard import build_ships

    targets = PERSONALITY_SHIP_BIAS.get(personality) or PERSONALITY_SHIP_BIAS["aggressive"]
    current = get_planet_ships(planet_id, conn=conn)
    for ship_key, want in targets:
        have = int(current.get(ship_key) or 0)
        if have >= int(want):
            continue
        amount = min(8, max(1, int(want) - have))
        ok, reason, meta = build_ships(
            player_id=player_id,
            planet_id=planet_id,
            ship_key=ship_key,
            amount=amount,
            conn=conn,
        )
        if ok:
            return {
                "ok": True,
                "ship_key": ship_key,
                "amount": amount,
                "meta": meta,
            }
        if reason in ("not_enough_resources", "queue_full", "requirements", "shipyard_level"):
            continue
    return {"ok": False, "error": "no_ship_job"}


def try_build_defense(
    conn,
    *,
    player_id: int,
    planet_id: int,
    personality: str,
) -> Dict[str, Any]:
    from .db import table_exists
    from .defense import build_defense

    if not table_exists(conn, "planet_defense"):
        return {"ok": False, "error": "no_defense_table"}

    cur = conn.execute(
        "SELECT defense_key, amount FROM planet_defense WHERE planet_id = ?;",
        (int(planet_id),),
    )
    current = {str(r["defense_key"]): int(r["amount"] or 0) for r in cur.fetchall()}
    targets = (
        PERSONALITY_DEFENSE_BIAS.get(personality)
        or PERSONALITY_DEFENSE_BIAS["aggressive"]
    )
    for defense_key, want in targets:
        have = int(current.get(defense_key) or 0)
        if have >= int(want):
            continue
        amount = min(10, max(1, int(want) - have))
        ok, reason, meta = build_defense(
            player_id=player_id,
            planet_id=planet_id,
            defense_key=defense_key,
            amount=amount,
            conn=conn,
        )
        if ok:
            return {
                "ok": True,
                "defense_key": defense_key,
                "amount": amount,
                "meta": meta,
            }
    return {"ok": False, "error": "no_defense_job"}


def _finish_due(
    conn,
    *,
    player_id: int,
    planet_id: int,
    now: float,
    source: str,
    update_scores: bool,
) -> Dict[str, Any]:
    from .queue_engine import finish_due_work_once

    try:
        from .resources import update_planet_resources

        cur = conn.execute(
            "SELECT * FROM planets WHERE id = ? LIMIT 1;", (planet_id,)
        )
        row = cur.fetchone()
        if row:
            update_planet_resources(dict(row), conn=conn, skip_queue_finish=True)
    except Exception:
        logger.exception("auto_empire resource sync failed planet=%s", planet_id)

    try:
        finished = finish_due_work_once(
            player_id=int(player_id),
            planet_id=planet_id,
            now=float(now),
            conn=conn,
            source=str(source),
            update_scores=bool(update_scores),
            recalc_ranks=False,
            manage_transaction=False,
            dedup=False,
        )
        return finished.get("finished") or {}
    except Exception:
        logger.exception("auto_empire finish_due_work failed planet=%s", planet_id)
        return {}


def _force_complete_job(
    conn,
    *,
    table: str,
    id_col: str,
    job_id: int,
    finish_col: str,
    now: float,
) -> None:
    """Mark a just-enqueued capped job due so chain_limit can progress in one tick."""
    try:
        conn.execute(
            f"UPDATE {table} SET {finish_col} = ? WHERE {id_col} = ?;",
            (float(now) - 1.0, int(job_id)),
        )
    except Exception:
        logger.exception("auto_empire force-complete failed %s id=%s", table, job_id)


def plan_passive_planet_tick(
    conn,
    *,
    player_id: int,
    planet: Mapping[str, Any],
    now: Optional[float] = None,
    is_home: bool = True,
    allow_buildings: bool = True,
    allow_research: bool = True,
    allow_ships: bool = False,
    allow_defense: bool = True,
    personality: str = "economy",
    build_duration_cap: Optional[int] = None,
    research_duration_cap: Optional[int] = None,
    source: str = "auto_empire",
    update_scores: bool = True,
    chain_limit: int = 1,
) -> Dict[str, Any]:
    """Finish due work then enqueue jobs (optional chain when duration caps apply)."""
    ts = float(now if now is not None else _now())
    planet_id = int(planet["id"])
    chains = max(1, min(5, int(chain_limit)))
    out: Dict[str, Any] = {
        "planet_id": planet_id,
        "player_id": int(player_id),
        "finished": {},
        "build": None,
        "research": None,
        "ships": None,
        "defense": None,
        "builds": [],
        "researches": [],
        "chains": 0,
        "source": str(source),
    }

    build_order = COLONY_BUILD_PRIORITY if not is_home else BUILD_PRIORITY

    for step in range(chains):
        finished = _finish_due(
            conn,
            player_id=int(player_id),
            planet_id=planet_id,
            now=ts,
            source=str(source),
            update_scores=bool(update_scores),
        )
        if finished:
            # Merge finished counters loosely.
            for k, v in finished.items():
                try:
                    out["finished"][k] = int(out["finished"].get(k) or 0) + int(v or 0)
                except Exception:
                    out["finished"][k] = v

        progressed = False
        if allow_buildings:
            for bkey in build_order:
                if int(BUILD_TARGETS.get(bkey, 0)) <= 0:
                    continue
                res = try_enqueue_building(
                    conn,
                    player_id=int(player_id),
                    planet=planet,
                    building_type=bkey,
                    now=ts,
                    duration_cap=build_duration_cap,
                )
                if res.get("ok"):
                    out["build"] = res
                    out["builds"].append(res)
                    progressed = True
                    if build_duration_cap is not None and chains > 1:
                        _force_complete_job(
                            conn,
                            table="build_queue",
                            id_col="id",
                            job_id=int(res["job_id"]),
                            finish_col="finish_time",
                            now=ts,
                        )
                    break

        if allow_research and is_home:
            for tech in RESEARCH_PRIORITY:
                res = try_enqueue_research(
                    conn,
                    player_id=int(player_id),
                    tech_key=tech,
                    now=ts,
                    duration_cap=research_duration_cap,
                )
                if res.get("ok"):
                    out["research"] = res
                    out["researches"].append(res)
                    progressed = True
                    if research_duration_cap is not None and chains > 1:
                        _force_complete_job(
                            conn,
                            table="research_queue",
                            id_col="id",
                            job_id=int(res["job_id"]),
                            finish_col="finish_at",
                            now=ts,
                        )
                    break

        out["chains"] = step + 1
        # Without caps, one enqueue pass is enough (real timers).
        if build_duration_cap is None and research_duration_cap is None:
            break
        if not progressed:
            break

    # Always finish force-completed / due jobs so levels + scores apply in-tick.
    final_finished = _finish_due(
        conn,
        player_id=int(player_id),
        planet_id=planet_id,
        now=ts,
        source=str(source),
        update_scores=bool(update_scores),
    )
    if final_finished:
        for k, v in final_finished.items():
            try:
                out["finished"][k] = int(out["finished"].get(k) or 0) + int(v or 0)
            except Exception:
                out["finished"][k] = v

    if allow_ships:
        ship_res = try_build_ships(
            conn,
            player_id=int(player_id),
            planet_id=planet_id,
            personality=str(personality),
        )
        if ship_res.get("ok"):
            out["ships"] = ship_res

    if allow_defense:
        def_res = try_build_defense(
            conn,
            player_id=int(player_id),
            planet_id=planet_id,
            personality=str(personality),
        )
        if def_res.get("ok"):
            out["defense"] = def_res

    return out
