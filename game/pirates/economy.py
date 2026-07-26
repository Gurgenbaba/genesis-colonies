"""Living AI economy planner (EPIC-21 Phase 2 / GC-P21–P23).

Bots progress through canonical owner APIs: buildings, research, defense, shipyard.
No second queue engine. Cheat hangar combat restock is retired — only utility floors remain.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .accounts import FACTION_BOTS, bootstrap_faction_bots
from .bot_state import ensure_bot_state
from .log import log_pirate_action
from .settings import is_pirates_ai_enabled

logger = logging.getLogger(__name__)

# Soft-On bootstrap resources so bots can start real queues.
BOT_RESOURCE_SEED = {
    "metal": 2_500_000,
    "crystal": 1_500_000,
    "fuel_cells": 500_000,
}

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

# Target levels for mid→late player-like viability (GC-P28).
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

# Personality → preferred combat / defense / ship mixes.
PERSONALITY_SHIP_BIAS: Dict[str, List[Tuple[str, int]]] = {
    "aggressive": [
        ("falcon_interceptor", 24),
        ("ironclad_frigate", 12),
        ("spark_drone", 30),
        ("eclipse_runner", 4),
        ("veil_probe", 8),
        ("harvest_reclaimer", 2),
        ("seed_ark", 1),
    ],
    "turtle": [
        ("ironclad_frigate", 18),
        ("falcon_interceptor", 10),
        ("spark_drone", 16),
        ("atlas_hauler", 6),
        ("veil_probe", 6),
        ("harvest_reclaimer", 3),
        ("seed_ark", 1),
    ],
    "spy": [
        ("veil_probe", 24),
        ("falcon_interceptor", 12),
        ("spark_drone", 16),
        ("eclipse_runner", 4),
        ("ironclad_frigate", 4),
        ("harvest_reclaimer", 2),
        ("seed_ark", 1),
    ],
    "swarm": [
        ("spark_drone", 60),
        ("falcon_interceptor", 16),
        ("veil_probe", 10),
        ("ironclad_frigate", 4),
        ("harvest_reclaimer", 2),
        ("seed_ark", 1),
    ],
    "elite": [
        ("ironclad_frigate", 16),
        ("falcon_interceptor", 20),
        ("eclipse_runner", 6),
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
    "elite": [("slug_launcher", 40), ("sentinel_turret", 25), ("plasma_arc", 12), ("ion_bastion", 6)],
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


def _now() -> float:
    return time.time()


def _personality_for_bot(conn, bot: Mapping[str, Any]) -> str:
    fk = str(bot.get("faction_key") or "")
    meta = FACTION_BOTS.get(fk) or {}
    personality = str(meta.get("personality") or "aggressive")
    try:
        state = ensure_bot_state(
            conn, bot_player_id=int(bot["player_id"]), faction_key=fk
        )
        if state.get("personality"):
            personality = str(state["personality"])
    except Exception:
        pass
    return personality


def ensure_bot_resource_seed(conn, bot: Mapping[str, Any]) -> Dict[str, Any]:
    """One-time Soft-On resource seed so queues can start (not combat hangar cheat)."""
    from ..models import get_planets_by_player

    player_id = int(bot["player_id"])
    faction_key = str(bot.get("faction_key") or "")
    state = ensure_bot_state(conn, bot_player_id=player_id, faction_key=faction_key)
    mood = dict(state.get("mood") or {})
    if mood.get("economy_seeded"):
        return {"ok": True, "seeded": False, "reason": "already"}

    planets = get_planets_by_player(player_id, conn=conn) or []
    if not planets:
        return {"ok": False, "error": "no_planets"}

    for planet in planets:
        pid = int(planet["id"])
        conn.execute(
            """
            UPDATE planets
            SET metal = max(COALESCE(metal, 0), ?),
                crystal = max(COALESCE(crystal, 0), ?),
                fuel_cells = max(COALESCE(fuel_cells, 0), ?)
            WHERE id = ?;
            """,
            (
                int(BOT_RESOURCE_SEED["metal"]),
                int(BOT_RESOURCE_SEED["crystal"]),
                int(BOT_RESOURCE_SEED["fuel_cells"]),
                pid,
            ),
        )

    mood["economy_seeded"] = True
    mood["economy_seeded_at"] = _now()
    import json

    conn.execute(
        """
        UPDATE pirate_bot_state
        SET mood_json = ?, updated_at = ?
        WHERE bot_player_id = ?;
        """,
        (json.dumps(mood), _now(), player_id),
    )
    log_pirate_action(
        conn,
        kind="bot_economy_seed",
        faction_key=faction_key,
        bot_player_id=player_id,
        message="one-time resource seed for living economy",
        payload={"resources": dict(BOT_RESOURCE_SEED), "planets": len(planets)},
    )
    return {"ok": True, "seeded": True, "planets": len(planets)}


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


def _try_enqueue_building(
    conn,
    *,
    player_id: int,
    planet: Mapping[str, Any],
    building_type: str,
    now: float,
) -> Dict[str, Any]:
    from ..buildings import (
        BuildingsPanelContext,
        get_upgrade_cost,
        has_building_requirements,
    )
    from ..models import (
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
    # Bots progress on worker cadence — keep jobs short enough to finish between ticks.
    duration = max(5, min(duration, 90))
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
    }


def _try_enqueue_research(
    conn,
    *,
    player_id: int,
    tech_key: str,
    now: float,
) -> Dict[str, Any]:
    from ..models import (
        add_research_job,
        get_homeworld,
        get_planet_buildings,
        get_research_levels,
        get_research_queue_rows,
        try_spend_resources_conn,
    )
    from ..research import (
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
    duration = max(5, min(duration, 120))
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
    }


def _try_build_ships(
    conn,
    *,
    player_id: int,
    planet_id: int,
    personality: str,
) -> Dict[str, Any]:
    from ..fleet import get_planet_ships
    from ..shipyard import build_ships

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


def _try_build_defense(
    conn,
    *,
    player_id: int,
    planet_id: int,
    personality: str,
) -> Dict[str, Any]:
    from ..db import table_exists
    from ..defense import build_defense

    if not table_exists(conn, "planet_defense"):
        return {"ok": False, "error": "no_defense_table"}

    cur = conn.execute(
        "SELECT defense_key, amount FROM planet_defense WHERE planet_id = ?;",
        (int(planet_id),),
    )
    current = {str(r["defense_key"]): int(r["amount"] or 0) for r in cur.fetchall()}
    targets = PERSONALITY_DEFENSE_BIAS.get(personality) or PERSONALITY_DEFENSE_BIAS["aggressive"]
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


def plan_bot_planet_tick(
    conn,
    bot: Mapping[str, Any],
    planet: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    is_home: bool = True,
) -> Dict[str, Any]:
    """Finish due work then enqueue at most one job per domain for this planet."""
    from ..queue_engine import finish_due_work_once

    ts = float(now if now is not None else _now())
    player_id = int(bot["player_id"])
    planet_id = int(planet["id"])
    faction_key = str(bot.get("faction_key") or "")
    personality = _personality_for_bot(conn, bot)
    out: Dict[str, Any] = {
        "planet_id": planet_id,
        "finished": {},
        "build": None,
        "research": None,
        "ships": None,
        "defense": None,
    }

    try:
        finished = finish_due_work_once(
            player_id=player_id,
            planet_id=planet_id,
            now=ts,
            conn=conn,
            source="pirates",
            update_scores=False,
            recalc_ranks=False,
            manage_transaction=False,
            dedup=False,
        )
        out["finished"] = finished.get("finished") or {}
    except Exception:
        logger.exception("bot finish_due_work failed planet=%s", planet_id)

    # Buildings first (economy → infrastructure). Colonies prioritize mines/defense.
    build_order = COLONY_BUILD_PRIORITY if not is_home else BUILD_PRIORITY
    for bkey in build_order:
        if int(BUILD_TARGETS.get(bkey, 0)) <= 0:
            continue
        res = _try_enqueue_building(
            conn,
            player_id=player_id,
            planet=planet,
            building_type=bkey,
            now=ts,
        )
        if res.get("ok"):
            out["build"] = res
            break

    # Research only from homeworld (account-scoped).
    if is_home:
        for tech in RESEARCH_PRIORITY:
            res = _try_enqueue_research(
                conn, player_id=player_id, tech_key=tech, now=ts
            )
            if res.get("ok"):
                out["research"] = res
                break

    ship_res = _try_build_ships(
        conn, player_id=player_id, planet_id=planet_id, personality=personality
    )
    if ship_res.get("ok"):
        out["ships"] = ship_res

    def_res = _try_build_defense(
        conn, player_id=player_id, planet_id=planet_id, personality=personality
    )
    if def_res.get("ok"):
        out["defense"] = def_res

    if any(out.get(k) for k in ("build", "research", "ships", "defense")):
        log_pirate_action(
            conn,
            kind="bot_economy_tick",
            faction_key=faction_key,
            bot_player_id=player_id,
            message=f"economy planet={planet_id}",
            payload={
                "planet_id": planet_id,
                "is_home": bool(is_home),
                "build": out.get("build"),
                "research": out.get("research"),
                "ships": out.get("ships"),
                "defense": out.get("defense"),
                "personality": personality,
            },
        )
    return out


def run_economy_brain_tick(
    conn,
    *,
    now: Optional[float] = None,
    bots: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Per Soft-On tick: seed resources, utility floor, plan all bot planets."""
    if not is_pirates_ai_enabled(conn=conn):
        return {"ok": False, "error": "ai_disabled", "bots": []}

    ts = float(now if now is not None else _now())
    from ..models import get_planets_by_player

    roster = list(bots) if bots is not None else bootstrap_faction_bots(conn=conn)
    results: List[Dict[str, Any]] = []
    for bot in roster:
        faction_key = str(bot.get("faction_key") or "")
        try:
            ensure_bot_resource_seed(conn, bot)
        except Exception:
            logger.exception("resource seed failed faction=%s", faction_key)

        player_id = int(bot["player_id"])
        planets = get_planets_by_player(player_id, conn=conn) or []
        home_id = int(bot.get("planet_id") or (planets[0]["id"] if planets else 0))
        planet_results = []
        for planet in planets:
            is_home = int(planet["id"]) == home_id or bool(planet.get("is_homeworld"))
            try:
                planet_results.append(
                    plan_bot_planet_tick(
                        conn, bot, planet, now=ts, is_home=is_home
                    )
                )
            except Exception:
                logger.exception(
                    "economy planet tick failed faction=%s planet=%s",
                    faction_key,
                    planet.get("id"),
                )
        results.append(
            {
                "faction_key": faction_key,
                "player_id": player_id,
                "planets": planet_results,
            }
        )
    return {"ok": True, "bots": results, "count": len(results)}
