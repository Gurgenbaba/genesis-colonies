"""Shared passive empire planner (EPIC-26 / GC-2600).

Canonical enqueue path for buildings, research, defense, and optional ships.
Used by pirate AI (duration caps + ships) and inactive autoplay (real durations, no ships).
No second queue engine — owners remain buildings / research / defense / shipyard.
"""

from __future__ import annotations

import hashlib
import logging
import random
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
    "crystal_tech",
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
    "crystal_tech": 7,
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

# GC-2618: shared personality pool. Pirates already assign one per faction
# bot (`pirates/economy.py::_personality_for_bot`); inactive-human autoplay
# had none (hardcoded "economy" for every account) — that is the single
# owner fixed here, reused by both callers instead of a second picker.
ALL_PERSONALITIES: List[str] = list(PERSONALITY_SHIP_BIAS.keys())


def personality_for_player(player_id: int) -> str:
    """Deterministic personality pick for autoplay accounts without one
    (inactive sticky-roster humans). Same account always resolves to the same
    personality — stable build/research order + defense bias — instead of
    every inactive account defaulting to "economy" and looking cloned.
    """
    if not ALL_PERSONALITIES:
        return "economy"
    digest = hashlib.md5(f"personality:{int(player_id)}".encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(ALL_PERSONALITIES)
    return ALL_PERSONALITIES[idx]

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

# GC-2618: per-personality reorderings of the SAME building/tech key sets above
# (never a different set — only the pick order changes) so autoplay accounts
# with different personalities don't converge on identical building/tech
# levels in lockstep. "economy" intentionally maps back to the original lists
# — no behavior change for the pre-existing default. Missing personalities
# fall back to the base list via `.get(personality, BASE_LIST)`.
BUILD_PRIORITY_BY_PERSONALITY: Dict[str, List[str]] = {
    "economy": BUILD_PRIORITY,
    "turtle": [
        "command_center",
        "metal_storage",
        "crystal_storage",
        "fuel_storage",
        "defense_factory",
        "shield_generator",
        "radar_array",
        "metal_mine",
        "crystal_mine",
        "solar_plant",
        "fuel_cell_plant",
        "research_lab",
        "barracks",
        "orbital_shipyard",
    ],
    "aggressive": [
        "metal_mine",
        "solar_plant",
        "crystal_mine",
        "fuel_cell_plant",
        "orbital_shipyard",
        "barracks",
        "command_center",
        "research_lab",
        "defense_factory",
        "metal_storage",
        "crystal_storage",
        "radar_array",
        "shield_generator",
        "fuel_storage",
    ],
    "elite": [
        "command_center",
        "metal_mine",
        "crystal_mine",
        "solar_plant",
        "research_lab",
        "orbital_shipyard",
        "fuel_cell_plant",
        "barracks",
        "defense_factory",
        "shield_generator",
        "radar_array",
        "metal_storage",
        "crystal_storage",
        "fuel_storage",
    ],
    "spy": [
        "research_lab",
        "radar_array",
        "metal_mine",
        "crystal_mine",
        "solar_plant",
        "fuel_cell_plant",
        "command_center",
        "orbital_shipyard",
        "metal_storage",
        "crystal_storage",
        "defense_factory",
        "barracks",
        "shield_generator",
        "fuel_storage",
    ],
    "swarm": [
        "metal_mine",
        "crystal_mine",
        "orbital_shipyard",
        "solar_plant",
        "fuel_cell_plant",
        "command_center",
        "barracks",
        "research_lab",
        "metal_storage",
        "crystal_storage",
        "defense_factory",
        "radar_array",
        "shield_generator",
        "fuel_storage",
    ],
}

COLONY_BUILD_PRIORITY_BY_PERSONALITY: Dict[str, List[str]] = {
    "economy": COLONY_BUILD_PRIORITY,
    "turtle": [
        "command_center",
        "metal_storage",
        "crystal_storage",
        "defense_factory",
        "metal_mine",
        "crystal_mine",
        "solar_plant",
        "fuel_cell_plant",
        "barracks",
        "orbital_shipyard",
    ],
    "aggressive": [
        "metal_mine",
        "solar_plant",
        "crystal_mine",
        "fuel_cell_plant",
        "orbital_shipyard",
        "barracks",
        "command_center",
        "defense_factory",
        "metal_storage",
        "crystal_storage",
    ],
    "elite": [
        "command_center",
        "metal_mine",
        "crystal_mine",
        "solar_plant",
        "orbital_shipyard",
        "fuel_cell_plant",
        "barracks",
        "defense_factory",
        "metal_storage",
        "crystal_storage",
    ],
    "spy": [
        "metal_mine",
        "crystal_mine",
        "solar_plant",
        "fuel_cell_plant",
        "command_center",
        "orbital_shipyard",
        "metal_storage",
        "crystal_storage",
        "defense_factory",
        "barracks",
    ],
    "swarm": [
        "metal_mine",
        "crystal_mine",
        "orbital_shipyard",
        "solar_plant",
        "fuel_cell_plant",
        "command_center",
        "barracks",
        "metal_storage",
        "crystal_storage",
        "defense_factory",
    ],
}

RESEARCH_PRIORITY_BY_PERSONALITY: Dict[str, List[str]] = {
    "economy": RESEARCH_PRIORITY,
    "turtle": [
        "shield_tech",
        "armor_tech",
        "storage_tech",
        "energy_tech",
        "mining_tech",
        "crystal_tech",
        "drone_tech",
        "weapon_tech",
        "engine_tech",
        "navigation_tech",
        "fuel_efficiency",
        "buildtime_tech",
    ],
    "aggressive": [
        "weapon_tech",
        "armor_tech",
        "engine_tech",
        "energy_tech",
        "mining_tech",
        "crystal_tech",
        "drone_tech",
        "shield_tech",
        "storage_tech",
        "navigation_tech",
        "fuel_efficiency",
        "buildtime_tech",
    ],
    "elite": [
        "energy_tech",
        "weapon_tech",
        "armor_tech",
        "shield_tech",
        "engine_tech",
        "mining_tech",
        "crystal_tech",
        "drone_tech",
        "storage_tech",
        "navigation_tech",
        "fuel_efficiency",
        "buildtime_tech",
    ],
    "spy": [
        "navigation_tech",
        "engine_tech",
        "drone_tech",
        "energy_tech",
        "mining_tech",
        "crystal_tech",
        "storage_tech",
        "weapon_tech",
        "armor_tech",
        "shield_tech",
        "fuel_efficiency",
        "buildtime_tech",
    ],
    "swarm": [
        "drone_tech",
        "energy_tech",
        "mining_tech",
        "crystal_tech",
        "engine_tech",
        "weapon_tech",
        "storage_tech",
        "armor_tech",
        "shield_tech",
        "navigation_tech",
        "fuel_efficiency",
        "buildtime_tech",
    ],
}

# GC-2618: max +/- deterministic per-(player, key) jitter applied to
# BUILD_TARGETS / RESEARCH_TARGETS caps, so accounts don't all plateau on the
# exact same levels (see `_stable_jitter`).
BUILD_TARGET_JITTER = 2
RESEARCH_TARGET_JITTER = 1

# GC-2618: chance a *standing* (already-active, non-wake) autoplay tick skips
# starting anything new this round — only passed by the inactive-roster RR
# loop and the pirate play-loop's per-cycle economy step (both via explicit
# `idle_chance=`), never the default, so every direct/test call of
# `plan_passive_planet_tick`/`plan_bot_planet_tick` stays fully deterministic.
# Real players don't optimize every single check-in; a perfectly monotonic
# per-tick staircase across dozens of accounts is what makes autoplay
# progress look robotic.
AUTOPLAY_STANDING_IDLE_CHANCE = 0.25

# Pirate Soft-On: shorten jobs so bots progress on worker cadence.
PIRATE_BUILD_DURATION_CAP = 90
PIRATE_RESEARCH_DURATION_CAP = 120

# GC-2616: 10h auto-refill for autoplay/AI Timekeeper auto-boost (see
# `_auto_boost_timekeeper` below).
AUTOPLAY_TIMEKEEPER_REFILL_SEC = 36_000


def _stable_jitter(player_id: int, key: str, spread: int) -> int:
    """Deterministic per-(player, key) offset in [-spread, +spread] (GC-2618).

    Stable across restarts/processes — Python's built-in `hash()` is salted
    per-process (`PYTHONHASHSEED`), so it cannot be used here. Used to spread
    out BUILD_TARGETS/RESEARCH_TARGETS caps a little per account instead of
    every autoplay account plateauing at the exact same level.
    """
    if spread <= 0:
        return 0
    digest = hashlib.md5(f"{int(player_id)}:{key}".encode("utf-8")).hexdigest()
    n = int(digest[:8], 16)
    return (n % (2 * spread + 1)) - spread


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
    target_cap = int(BUILD_TARGETS.get(building_type, 8)) + _stable_jitter(
        player_id, building_type, BUILD_TARGET_JITTER
    )
    target_cap = max(1, target_cap)
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
    target_cap = int(RESEARCH_TARGETS.get(tech_key, 5)) + _stable_jitter(
        player_id, tech_key, RESEARCH_TARGET_JITTER
    )
    target_cap = max(1, target_cap)
    if current >= target_cap:
        return {"ok": False, "error": "at_target"}
    if not has_research_requirements(buildings, levels, tech_key):
        return {"ok": False, "error": "requirements"}

    target = current + 1
    cost_m, cost_c = get_research_cost(tech_key, target)
    if not try_spend_resources_conn(conn, planet_id, int(cost_m), int(cost_c)):
        return {"ok": False, "error": "resources"}

    duration = int(
        get_research_time(
            tech_key,
            target,
            user_id=player_id,
            buildings=buildings,
            levels=levels,
            conn=conn,
        )
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


def _auto_boost_timekeeper(
    conn, *, player_id: int, planet_id: int, domain: str
) -> None:
    """GC-2616: keep defense/shipyard queues moving for autoplay accounts (inactive
    humans *and* AI pirates) using the real Timekeeper ledger — no parallel speed
    mechanic. Build/research are intentionally excluded here: they already
    force-complete same-tick via `duration_cap` + `chain_limit` above, so an
    auto-apply there would just spend balance with no visible extra effect.
    Refills to `AUTOPLAY_TIMEKEEPER_REFILL_SEC` whenever the balance is empty,
    same ledger (`timekeeper_balances`/`timekeeper_transactions`) a manually
    playing owner would see if they returned.
    """
    from . import timekeeper

    try:
        if timekeeper.get_balance(int(player_id), conn=conn) <= 0:
            timekeeper.credit(
                int(player_id),
                AUTOPLAY_TIMEKEEPER_REFILL_SEC,
                "autoplay_replenish",
                conn=conn,
            )
        timekeeper.apply_timekeeper(
            int(player_id), domain, planet_id=int(planet_id), mode="max", conn=conn
        )
    except Exception:
        logger.exception(
            "auto_empire timekeeper auto-boost failed player=%s domain=%s",
            player_id,
            domain,
        )


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
    idle_chance: float = 0.0,
) -> Dict[str, Any]:
    """Finish due work then enqueue jobs (optional chain when duration caps apply).

    `idle_chance` (GC-2618): default 0 keeps every direct caller/test fully
    deterministic. Autoplay tick-loops (inactive roster's standing RR slice,
    pirate play-loop's per-cycle economy step) pass a small nonzero value so
    an account occasionally starts nothing new for a round — see
    `AUTOPLAY_STANDING_IDLE_CHANCE` for why.
    """
    ts = float(now if now is not None else _now())
    planet_id = int(planet["id"])
    chains = max(1, min(5, int(chain_limit)))
    is_idle_tick = bool(idle_chance > 0 and random.random() < float(idle_chance))
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
        "idle": is_idle_tick,
    }

    # GC-2618: personality-specific pick order (same key sets, different
    # sequence) so accounts don't all build/research in lockstep.
    if not is_home:
        build_order = COLONY_BUILD_PRIORITY_BY_PERSONALITY.get(
            str(personality), COLONY_BUILD_PRIORITY
        )
    else:
        build_order = BUILD_PRIORITY_BY_PERSONALITY.get(str(personality), BUILD_PRIORITY)
    research_order = RESEARCH_PRIORITY_BY_PERSONALITY.get(
        str(personality), RESEARCH_PRIORITY
    )

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
        if allow_buildings and not is_idle_tick:
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

        if allow_research and is_home and not is_idle_tick:
            for tech in research_order:
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

    if allow_ships and not is_idle_tick:
        ship_res = try_build_ships(
            conn,
            player_id=int(player_id),
            planet_id=planet_id,
            personality=str(personality),
        )
        if ship_res.get("ok"):
            out["ships"] = ship_res
            _auto_boost_timekeeper(
                conn, player_id=int(player_id), planet_id=planet_id, domain="shipyard"
            )

    if allow_defense and not is_idle_tick:
        def_res = try_build_defense(
            conn,
            player_id=int(player_id),
            planet_id=planet_id,
            personality=str(personality),
        )
        if def_res.get("ok"):
            out["defense"] = def_res
            _auto_boost_timekeeper(
                conn, player_id=int(player_id), planet_id=planet_id, domain="defense"
            )

    if out["ships"] or out["defense"]:
        # Timekeeper auto-apply above may have just force-finished the
        # shipyard/defense head job — sync so counts/levels are visible
        # in-tick (matters for GC-2615 activity reporting).
        boosted_finished = _finish_due(
            conn,
            player_id=int(player_id),
            planet_id=planet_id,
            now=ts,
            source=str(source),
            update_scores=bool(update_scores),
        )
        if boosted_finished:
            for k, v in boosted_finished.items():
                try:
                    out["finished"][k] = int(out["finished"].get(k) or 0) + int(v or 0)
                except Exception:
                    out["finished"][k] = v

    return out
