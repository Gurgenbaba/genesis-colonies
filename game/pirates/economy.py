"""Living AI economy planner (EPIC-21 Phase 2 / GC-P21–P23).

Thin pirate wrapper around game.auto_empire — ships + duration caps + Soft-On seed.
No second queue engine. Cheat hangar combat restock is retired — only utility floors remain.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..auto_empire import (
    BUILD_PRIORITY,
    BUILD_TARGETS,
    COLONY_BUILD_PRIORITY,
    PERSONALITY_DEFENSE_BIAS,
    PERSONALITY_SHIP_BIAS,
    PIRATE_BUILD_DURATION_CAP,
    PIRATE_RESEARCH_DURATION_CAP,
    RESEARCH_PRIORITY,
    RESEARCH_TARGETS,
    plan_passive_planet_tick,
)
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

# Re-export ladders for callers/tests that imported from this module.
__all__ = [
    "BOT_RESOURCE_SEED",
    "BUILD_PRIORITY",
    "BUILD_TARGETS",
    "COLONY_BUILD_PRIORITY",
    "PERSONALITY_DEFENSE_BIAS",
    "PERSONALITY_SHIP_BIAS",
    "RESEARCH_PRIORITY",
    "RESEARCH_TARGETS",
    "ensure_bot_resource_seed",
    "plan_bot_planet_tick",
    "run_economy_brain_tick",
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


def plan_bot_planet_tick(
    conn,
    bot: Mapping[str, Any],
    planet: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    is_home: bool = True,
) -> Dict[str, Any]:
    """Finish due work then enqueue via shared auto_empire (ships + pirate caps)."""
    ts = float(now if now is not None else _now())
    player_id = int(bot["player_id"])
    planet_id = int(planet["id"])
    faction_key = str(bot.get("faction_key") or "")
    personality = _personality_for_bot(conn, bot)

    out = plan_passive_planet_tick(
        conn,
        player_id=player_id,
        planet=planet,
        now=ts,
        is_home=is_home,
        allow_buildings=True,
        allow_research=True,
        allow_ships=True,
        allow_defense=True,
        personality=personality,
        build_duration_cap=PIRATE_BUILD_DURATION_CAP,
        research_duration_cap=PIRATE_RESEARCH_DURATION_CAP,
        source="pirates",
        update_scores=True,
        chain_limit=3,
    )

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
