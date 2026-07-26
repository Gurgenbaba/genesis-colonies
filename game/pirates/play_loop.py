"""Player-like action loop for living pirate AIs (EPIC-21 Phase 3 / GC-P26).

One primary strategic action per bot per tick after finishing due work / economy enqueue.
Canonical missions only — no hangar cheat restock in the loop.

Cron safety (Railway / single Gunicorn worker): only a round-robin slice of bots
runs per tick so ranking/fleet HTTP cron cannot monopolize SQLite for minutes.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .accounts import FACTION_BOTS, bootstrap_faction_bots
from .bot_state import ensure_bot_state
from .heat import HEAT_THRESHOLDS, get_galaxy_heat
from .log import log_pirate_action
from .settings import is_pirates_ai_enabled

logger = logging.getLogger(__name__)

VIABLE_MINE = 4
VIABLE_LAB = 2
VIABLE_SHIPYARD = 2
VIABLE_COMBAT_SHIPS = 8
RESERVE_COMBAT_SHIPS = {
    "aggressive": 0.25,
    "turtle": 0.50,
    "spy": 0.35,
    "swarm": 0.25,
    "elite": 0.30,
    "economy": 0.40,
}

# Keep HTTP cron responsive on 1 sync worker + SQLite (Railway default).
PLAY_LOOP_CURSOR_KEY = "pirate_play_loop_cursor"
PLAY_BOTS_PER_TICK = max(1, int(os.environ.get("GC_PIRATE_PLAY_BOTS_PER_TICK", "2")))


def _now() -> float:
    return time.time()


def _personality(conn, bot: Mapping[str, Any]) -> str:
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


def _home_buildings(conn, planet_id: int) -> Dict[str, int]:
    from ..models import get_planet_buildings

    return get_planet_buildings(int(planet_id), conn=conn)


def _combat_ship_count(ships: Mapping[str, int]) -> int:
    utility = {
        "veil_probe",
        "harvest_reclaimer",
        "seed_ark",
        "atlas_hauler",
        "mule_courier",
        "deep_vault_ark",
    }
    return sum(int(v or 0) for k, v in ships.items() if str(k) not in utility)


def _defense_count(conn, planet_id: int) -> int:
    try:
        from ..db import table_exists

        if not table_exists(conn, "planet_defense"):
            return 0
        cur = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS c FROM planet_defense WHERE planet_id = ?;",
            (int(planet_id),),
        )
        return int((cur.fetchone() or {"c": 0})["c"] or 0)
    except Exception:
        return 0


def _needs_economy(buildings: Mapping[str, int]) -> bool:
    return (
        int(buildings.get("metal_mine") or 0) < VIABLE_MINE
        or int(buildings.get("crystal_mine") or 0) < VIABLE_MINE
        or int(buildings.get("solar_plant") or 0) < VIABLE_MINE
        or int(buildings.get("research_lab") or 0) < VIABLE_LAB
        or int(buildings.get("orbital_shipyard") or 0) < VIABLE_SHIPYARD
    )


def _needs_rebuild(
    conn,
    bot: Mapping[str, Any],
    ships: Mapping[str, int],
    *,
    personality: str,
) -> bool:
    combat = _combat_ship_count(ships)
    defense = _defense_count(conn, int(bot["planet_id"]))
    if combat < VIABLE_COMBAT_SHIPS:
        return True
    if personality in ("turtle", "economy") and defense < 10:
        return True
    if int(ships.get("veil_probe") or 0) < 5 and personality == "spy":
        return True
    return False


def _intel_stale(conn, bot: Mapping[str, Any], *, now: float) -> bool:
    cur = conn.execute(
        """
        SELECT MAX(updated_at) AS u FROM pirate_intel
        WHERE bot_player_id = ?;
        """,
        (int(bot["player_id"]),),
    )
    row = cur.fetchone()
    if not row or row["u"] is None:
        return True
    return float(row["u"] or 0) < float(now) - 6 * 3600


def _colony_wipe_cooling(conn, bot: Mapping[str, Any], *, now: float) -> bool:
    state = ensure_bot_state(
        conn,
        bot_player_id=int(bot["player_id"]),
        faction_key=str(bot.get("faction_key") or ""),
        now=now,
    )
    until = (state.get("mood") or {}).get("colony_wipe_cooldown_until")
    if until is None:
        return False
    try:
        return float(until) > float(now)
    except (TypeError, ValueError):
        return False


def decide_bot_action(
    conn,
    bot: Mapping[str, Any],
    *,
    now: Optional[float] = None,
) -> str:
    """Return one of: economy, rebuild, spy, raid, colonize, recycle, idle."""
    ts = float(now if now is not None else _now())
    planet_id = int(bot["planet_id"])
    galaxy = int(bot.get("galaxy") or 1)
    heat = int(get_galaxy_heat(conn, galaxy).get("heat") or 0)
    personality = _personality(conn, bot)
    buildings = _home_buildings(conn, planet_id)

    from ..fleet import get_planet_ships

    ships = get_planet_ships(planet_id, conn=conn)

    if _needs_economy(buildings):
        return "economy"
    if _needs_rebuild(conn, bot, ships, personality=personality):
        return "rebuild"
    if heat >= HEAT_THRESHOLDS["patrol"] and _intel_stale(conn, bot, now=ts):
        if int(ships.get("veil_probe") or 0) >= 5:
            return "spy"
        return "rebuild"
    if heat >= HEAT_THRESHOLDS["raids"] and _combat_ship_count(ships) >= VIABLE_COMBAT_SHIPS:
        return "raid"
    if (
        heat >= HEAT_THRESHOLDS["patrol"]
        and int(ships.get("seed_ark") or 0) >= 1
        and not _colony_wipe_cooling(conn, bot, now=ts)
    ):
        return "colonize"
    if heat >= HEAT_THRESHOLDS["patrol"] and int(ships.get("harvest_reclaimer") or 0) >= 1:
        return "recycle"
    return "economy"


def run_bot_play_step(
    conn,
    bot: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    force_playtime: bool = False,
) -> Dict[str, Any]:
    """Finish/enqueue economy lightly, then one strategic mission."""
    from ..models import get_planets_by_player
    from .economy import plan_bot_planet_tick

    ts = float(now if now is not None else _now())
    action = decide_bot_action(conn, bot, now=ts)
    faction_key = str(bot.get("faction_key") or "")
    out: Dict[str, Any] = {
        "faction_key": faction_key,
        "player_id": int(bot["player_id"]),
        "action": action,
        "ok": False,
    }

    planets = get_planets_by_player(int(bot["player_id"]), conn=conn) or []
    home_id = int(bot.get("planet_id") or 0)
    econ_results: List[Dict[str, Any]] = []

    if action in ("economy", "rebuild"):
        for planet in planets:
            is_home = int(planet["id"]) == home_id or bool(planet.get("is_homeworld"))
            try:
                econ_results.append(
                    plan_bot_planet_tick(
                        conn, bot, planet, now=ts, is_home=is_home
                    )
                )
            except Exception:
                logger.exception("play_loop economy failed planet=%s", planet.get("id"))
            if len(econ_results) >= 2:
                break
    else:
        # Finish due work on home before missions (player-like).
        for planet in planets:
            if int(planet["id"]) != home_id and not planet.get("is_homeworld"):
                continue
            try:
                from ..queue_engine import finish_due_work_once

                finish_due_work_once(
                    player_id=int(bot["player_id"]),
                    planet_id=int(planet["id"]),
                    now=ts,
                    conn=conn,
                    source="pirates",
                    update_scores=False,
                    recalc_ranks=False,
                    manage_transaction=False,
                    dedup=False,
                )
            except Exception:
                logger.exception("play_loop finish failed")
            break

    out["economy"] = econ_results
    if action in ("economy", "rebuild"):
        out["ok"] = any(
            r.get("build") or r.get("research") or r.get("ships") or r.get("defense")
            for r in econ_results
        ) or bool(econ_results)
        log_pirate_action(
            conn,
            kind="bot_play_loop",
            faction_key=faction_key,
            bot_player_id=int(bot["player_id"]),
            message=f"action={action}",
            payload={"action": action, "economy": bool(out["ok"])},
        )
        return out

    if action == "spy":
        from .brain import dispatch_spy_from_home

        res = dispatch_spy_from_home(conn, bot, now=ts, force_playtime=force_playtime)
        out["result"] = res
        out["ok"] = bool(res.get("ok"))
    elif action == "raid":
        from .brain import dispatch_raid_from_home

        res = dispatch_raid_from_home(conn, bot, now=ts, force_playtime=force_playtime)
        out["result"] = res
        out["ok"] = bool(res.get("ok"))
    elif action == "colonize":
        from .brain import dispatch_colonize_from_home

        res = dispatch_colonize_from_home(
            conn, bot, now=ts, force_playtime=force_playtime
        )
        out["result"] = res
        out["ok"] = bool(res.get("ok"))
    elif action == "recycle":
        out["ok"] = False
        out["result"] = {"ok": False, "error": "recycle_via_secondary"}
    else:
        out["ok"] = True

    log_pirate_action(
        conn,
        kind="bot_play_loop",
        faction_key=faction_key,
        bot_player_id=int(bot["player_id"]),
        message=f"action={action} ok={out['ok']}",
        payload={"action": action, "result": out.get("result")},
    )
    return out


def _round_robin_bots(
    conn,
    roster: Sequence[Mapping[str, Any]],
    *,
    max_bots: int,
    process_all: bool = False,
) -> List[Mapping[str, Any]]:
    """Advance a persistent cursor so all factions get turns without one huge tick."""
    n = len(roster)
    if n <= 0:
        return []
    if process_all or max_bots >= n:
        return list(roster)

    from ..runtime_state import get_runtime_value, set_runtime_value

    try:
        raw = get_runtime_value(PLAY_LOOP_CURSOR_KEY, conn=conn)
        start = int(float(raw or 0)) % n
    except Exception:
        start = 0
    limit = max(1, int(max_bots))
    selected = [roster[(start + i) % n] for i in range(limit)]
    try:
        set_runtime_value(PLAY_LOOP_CURSOR_KEY, str((start + limit) % n), conn=conn)
    except Exception:
        logger.exception("play_loop cursor persist failed")
    return selected


def run_play_loop_tick(
    conn,
    *,
    now: Optional[float] = None,
    bots: Optional[Sequence[Mapping[str, Any]]] = None,
    force_playtime: bool = False,
    max_bots: Optional[int] = None,
    process_all: bool = False,
) -> Dict[str, Any]:
    """Soft-On tick: round-robin bot steps; base raids + recycle as secondary."""
    if not is_pirates_ai_enabled(conn=conn):
        return {"ok": False, "error": "ai_disabled", "steps": []}

    ts = float(now if now is not None else _now())
    roster = list(bots) if bots is not None else bootstrap_faction_bots(conn=conn)
    limit = int(max_bots) if max_bots is not None else PLAY_BOTS_PER_TICK
    active = _round_robin_bots(
        conn, roster, max_bots=limit, process_all=bool(process_all)
    )
    steps: List[Dict[str, Any]] = []
    for bot in active:
        try:
            steps.append(
                run_bot_play_step(
                    conn, bot, now=ts, force_playtime=force_playtime
                )
            )
        except Exception:
            logger.exception(
                "play_loop step failed faction=%s", bot.get("faction_key")
            )
            steps.append(
                {
                    "faction_key": bot.get("faction_key"),
                    "ok": False,
                    "error": "exception",
                }
            )

    from .brain import run_raid_brain_tick, run_recycle_brain_tick

    # Home raids already happen in play steps; base raids fill remaining budget.
    raids = run_raid_brain_tick(conn, now=ts, skip_home_raids=True)
    recycles = run_recycle_brain_tick(conn, now=ts)
    return {
        "ok": True,
        "steps": steps,
        "raids": raids.get("raids") or [],
        "recycles": recycles.get("recycles") or [],
        "spies": [s for s in steps if s.get("action") == "spy" and s.get("ok")],
        "colonizes": [s for s in steps if s.get("action") == "colonize" and s.get("ok")],
        "count": len(steps),
        "roster": len(roster),
        "active": len(active),
        "bots_per_tick": limit if not process_all else len(roster),
    }


def reserve_fraction_for_personality(personality: str) -> float:
    return float(RESERVE_COMBAT_SHIPS.get(str(personality), 0.30))
