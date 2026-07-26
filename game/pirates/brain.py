"""Pirate raid brain — Spy→Intel→Attack (EPIC-21 / GC-P06–P07 / GC-P19).

Acts like a player: real ``send_fleet`` missions, visible ETA, strength-capped fleets.
Patrol spies + home raids + recycle when AI is on. No chat. Kill-switch gated.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .accounts import (
    bootstrap_faction_bots,
    ensure_faction_bot,
    is_pirate_bot_player,
)
from .bases import LIVE_STATUSES, list_live_bases
from .heat import HEAT_THRESHOLDS, get_galaxy_heat
from .log import log_pirate_action
from .settings import is_pirates_ai_enabled
from .threat import get_player_threat, recompute_player_threat

logger = logging.getLogger(__name__)

MAX_RAIDS_PER_TICK = 3
MAX_RAIDS_PER_TICK_WAR = 5
MAX_SPIES_PER_TICK = 3
MAX_RECYCLES_PER_TICK = 1
SPY_PROBE_COUNT = 5
INTEL_STALE_SEC = 6 * 3600
RAID_FLEET_FRACTION = 0.55
MIN_OPPORTUNITY = 35
ANTI_PILE_ON_SEC = 24 * 3600
HOME_RAID_STACK_FRACTION = 0.45
BOT_COLONY_SOFT_CAP = 4  # home + up to 3 extra colonies per faction bot
COMBAT_VS_BOT_BOUNTY = 150
COLONIZE_WIPE_COOLDOWN_SEC = 6 * 3600


def _now() -> float:
    return time.time()


def _write_intel(
    conn,
    *,
    bot_player_id: int,
    target_planet_id: int,
    target_player_id: int,
    galaxy: int,
    system: int,
    position: int,
    resources_score: int,
    fleet_score: int,
    defense_score: int,
    opportunity: int,
    now: float,
) -> None:
    conn.execute(
        """
        INSERT INTO pirate_intel (
            bot_player_id, target_planet_id, target_player_id,
            galaxy, system, position,
            resources_score, fleet_score, defense_score, opportunity,
            report_read_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bot_player_id, target_planet_id) DO UPDATE SET
            target_player_id = excluded.target_player_id,
            resources_score = excluded.resources_score,
            fleet_score = excluded.fleet_score,
            defense_score = excluded.defense_score,
            opportunity = excluded.opportunity,
            report_read_at = excluded.report_read_at,
            updated_at = excluded.updated_at;
        """,
        (
            int(bot_player_id),
            int(target_planet_id),
            int(target_player_id),
            int(galaxy),
            int(system),
            int(position),
            int(resources_score),
            int(fleet_score),
            int(defense_score),
            int(opportunity),
            float(now),
            float(now),
            float(now),
        ),
    )


def _score_opportunity(
    *,
    metal: int,
    crystal: int,
    fuel: int,
    fleet_score: int,
    defense_score: int,
    offline_hours: float,
    threat: int,
    bounty_credits: int = 0,
    turtle: float = 0.2,
) -> int:
    """OGX-like opportunity 0–100 from loot vs defense + inactivity + bounty."""
    loot = max(0, int(metal) + int(crystal) + int(fuel) // 2)
    risk = max(1, int(defense_score) + int(fleet_score) // 2)
    # Turtle factions treat defended worlds as higher risk.
    risk = int(risk * (1.0 + 0.6 * max(0.0, min(1.0, float(turtle)))))
    raw = (float(loot) / float(risk)) * 12.0
    raw += min(30.0, max(0.0, offline_hours) * 1.5)
    # Famous / high-threat players draw elite attention (not ignored).
    if threat >= 70:
        raw += 10.0
    elif threat <= 5:
        raw -= 8.0  # soft ignore low threat
    # Per-faction revenge bounty.
    if bounty_credits >= 5000:
        raw += 18.0
    elif bounty_credits >= 2000:
        raw += 12.0
    elif bounty_credits >= 500:
        raw += 6.0
    return int(max(0, min(100, round(raw))))


def _candidate_planets(conn, galaxy: int, *, limit: int = 40) -> List[Dict[str, Any]]:
    from ..db import column_exists

    vac_col = (
        "COALESCE(pl.vacation_mode_active, 0)"
        if column_exists(conn, "players", "vacation_mode_active")
        else "0"
    )
    cur = conn.execute(
        f"""
        SELECT p.id AS planet_id, p.player_id, p.galaxy, p.system, p.position,
               p.metal, p.crystal, COALESCE(p.fuel_cells, 0) AS fuel_cells,
               pl.name AS owner_name,
               COALESCE(pl.last_seen, 0) AS last_seen,
               {vac_col} AS vacation_mode_active
        FROM planets p
        INNER JOIN players pl ON pl.id = p.player_id
        WHERE p.galaxy = ?
        ORDER BY (COALESCE(p.metal,0) + COALESCE(p.crystal,0)) DESC
        LIMIT ?;
        """,
        (int(galaxy), int(limit)),
    )
    return [dict(r) for r in cur.fetchall()]


def _planet_military(conn, planet_id: int) -> Tuple[int, int]:
    from ..scoring import compute_destroyed_raw_from_losses

    cur = conn.execute(
        "SELECT ship_key, amount FROM planet_ships WHERE planet_id = ? AND amount > 0;",
        (int(planet_id),),
    )
    ships = {str(r["ship_key"]): int(r["amount"]) for r in cur.fetchall()}
    fleet_score = int(compute_destroyed_raw_from_losses(ships)) if ships else 0
    defense_score = 0
    try:
        from ..db import table_exists
        from ..defense_defs import defense_score_value

        if table_exists(conn, "planet_defense"):
            cur = conn.execute(
                "SELECT defense_key, amount FROM planet_defense WHERE planet_id = ? AND amount > 0;",
                (int(planet_id),),
            )
            for r in cur.fetchall():
                defense_score += defense_score_value(str(r["defense_key"])) * int(r["amount"] or 0)
    except Exception:
        pass
    return fleet_score, defense_score


def _recently_raided(conn, target_player_id: int, *, now: float) -> bool:
    cur = conn.execute(
        """
        SELECT 1 FROM pirate_action_log
        WHERE kind = 'raid_dispatch'
          AND target_player_id = ?
          AND ts >= ?
        LIMIT 1;
        """,
        (int(target_player_id), float(now) - ANTI_PILE_ON_SEC),
    )
    return cur.fetchone() is not None


def _raid_fleet_from_hangar(
    conn,
    *,
    planet_id: int,
    fraction: float = RAID_FLEET_FRACTION,
    reserve_fraction: float = 0.30,
    reserve_keys: Optional[Tuple[str, ...]] = ("veil_probe", "seed_ark", "harvest_reclaimer"),
) -> Dict[str, int]:
    """Take a fraction of the real hangar for a raid — keep personality reserve at home."""
    from ..fleet import get_planet_ships

    reserve_keys_set = set(reserve_keys or ())
    ships = get_planet_ships(int(planet_id), conn=conn)
    fleet: Dict[str, int] = {}
    keep_ratio = max(0.0, min(0.75, float(reserve_fraction)))
    for k, v in ships.items():
        key = str(k)
        if key in reserve_keys_set:
            continue
        total = int(v or 0)
        if total <= 0:
            continue
        keep = int(max(0, round(total * keep_ratio)))
        available = max(0, total - keep)
        n = int(max(0, round(available * float(fraction))))
        if n > 0:
            fleet[key] = n
    return fleet


def _fresh_intel_row(
    conn, *, bot_player_id: int, target_planet_id: int, now: float
) -> Optional[Dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT * FROM pirate_intel
        WHERE bot_player_id = ? AND target_planet_id = ?
          AND updated_at >= ?
        LIMIT 1;
        """,
        (int(bot_player_id), int(target_planet_id), float(now) - INTEL_STALE_SEC),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def ingest_spy_report_for_intel(
    conn,
    *,
    bot_player_id: int,
    meta: Mapping[str, Any],
    snapshot: Optional[Mapping[str, Any]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Write ``pirate_intel`` from a real spy-report metadata payload (fleet arrival)."""
    ts = float(now if now is not None else _now())
    snap = dict(snapshot or {})
    planet_id = int(meta.get("target_planet_id") or snap.get("planet_id") or 0)
    if planet_id <= 0:
        return {"ok": False, "error": "no_planet"}

    cur = conn.execute(
        """
        SELECT id, player_id, galaxy, system, position,
               COALESCE(metal,0) AS metal, COALESCE(crystal,0) AS crystal,
               COALESCE(fuel_cells,0) AS fuel_cells
        FROM planets WHERE id = ? LIMIT 1;
        """,
        (planet_id,),
    )
    prow = cur.fetchone()
    if not prow:
        return {"ok": False, "error": "planet_missing"}

    target_player_id = int(prow["player_id"] or snap.get("player_id") or 0)
    resources = dict(meta.get("resources") or {})
    metal = int(resources.get("metal") if resources.get("metal") is not None else prow["metal"] or 0)
    crystal = int(
        resources.get("crystal") if resources.get("crystal") is not None else prow["crystal"] or 0
    )
    fuel = int(
        resources.get("fuel_cells")
        if resources.get("fuel_cells") is not None
        else prow["fuel_cells"] or 0
    )

    from ..scoring import compute_destroyed_raw_from_losses

    ships = {
        str(k): max(0, int(v or 0))
        for k, v in dict(meta.get("ships") or {}).items()
        if int(v or 0) > 0
    }
    fleet_score = int(compute_destroyed_raw_from_losses(ships)) if ships else 0
    defense_score = 0
    try:
        from ..defense_defs import defense_score_value

        for k, v in dict(meta.get("defense") or {}).items():
            defense_score += defense_score_value(str(k)) * max(0, int(v or 0))
    except Exception:
        pass

    threat_info = get_player_threat(target_player_id, conn=conn) if target_player_id else {"threat": 0}
    threat = int(threat_info.get("threat") or 0)
    last_seen = 0.0
    if target_player_id:
        cur = conn.execute(
            "SELECT COALESCE(last_seen, 0) AS last_seen FROM players WHERE id = ?;",
            (target_player_id,),
        )
        last_seen = float((cur.fetchone() or {"last_seen": 0})["last_seen"] or 0)
    offline_h = max(0.0, (ts - last_seen) / 3600.0) if last_seen > 0 else 48.0
    opp = _score_opportunity(
        metal=metal,
        crystal=crystal,
        fuel=fuel,
        fleet_score=fleet_score,
        defense_score=defense_score,
        offline_hours=offline_h,
        threat=threat,
    )
    _write_intel(
        conn,
        bot_player_id=int(bot_player_id),
        target_planet_id=planet_id,
        target_player_id=target_player_id,
        galaxy=int(prow["galaxy"]),
        system=int(prow["system"]),
        position=int(prow["position"]),
        resources_score=metal + crystal,
        fleet_score=fleet_score,
        defense_score=defense_score,
        opportunity=opp,
        now=ts,
    )
    log_pirate_action(
        conn,
        kind="spy_intel",
        bot_player_id=int(bot_player_id),
        target_player_id=target_player_id or None,
        galaxy_id=int(prow["galaxy"]),
        message=(
            f"intel from spy report planet={planet_id} "
            f"opp={opp} fleet={fleet_score} def={defense_score}"
        ),
        payload={
            "target_planet_id": planet_id,
            "opportunity": opp,
            "fleet_score": fleet_score,
            "defense_score": defense_score,
            "resources_score": metal + crystal,
        },
    )
    return {"ok": True, "opportunity": opp, "target_planet_id": planet_id}


def _pick_best_target(
    conn,
    *,
    bot_player_id: int,
    galaxy: int,
    faction_key: str,
    now: float,
    opportunity_floor: int = MIN_OPPORTUNITY,
    turtle: float = 0.2,
    spy_bias: float = 0.5,
) -> Optional[Dict[str, Any]]:
    from .bounty import get_player_bounty

    best = None
    best_opp = -1
    intel_writes = 0
    for cand in _candidate_planets(conn, galaxy):
        pid = int(cand["player_id"])
        if pid == int(bot_player_id):
            continue
        if is_pirate_bot_player(pid, conn=conn):
            continue
        if int(cand.get("vacation_mode_active") or 0):
            continue
        if _recently_raided(conn, pid, now=now):
            continue
        try:
            from ..combat_balance_bots import is_combat_balance_bot_player

            if is_combat_balance_bot_player(pid, conn=conn):
                continue
        except Exception:
            pass

        threat_info = get_player_threat(pid, conn=conn)
        if int(threat_info.get("threat") or 0) == 0:
            threat_info = recompute_player_threat(pid, conn=conn)
        threat = int(threat_info.get("threat") or 0)
        bounty = get_player_bounty(pid, faction_key, conn=conn)
        bounty_credits = int(bounty.get("credits") or 0)

        last_seen = float(cand.get("last_seen") or 0)
        offline_h = max(0.0, (now - last_seen) / 3600.0) if last_seen > 0 else 48.0

        # Prefer fresh spy-derived intel when available.
        stored = _fresh_intel_row(
            conn, bot_player_id=bot_player_id, target_planet_id=int(cand["planet_id"]), now=now
        )
        if stored:
            fleet_score = int(stored.get("fleet_score") or 0)
            defense_score = int(stored.get("defense_score") or 0)
            resources_score = int(stored.get("resources_score") or 0)
            metal = max(0, resources_score // 2)
            crystal = max(0, resources_score - metal)
            fuel = int(cand.get("fuel_cells") or 0)
            opp = int(stored.get("opportunity") or 0)
            if opp <= 0:
                opp = _score_opportunity(
                    metal=metal,
                    crystal=crystal,
                    fuel=fuel,
                    fleet_score=fleet_score,
                    defense_score=defense_score,
                    offline_hours=offline_h,
                    threat=threat,
                    bounty_credits=bounty_credits,
                    turtle=turtle,
                )
        else:
            fleet_score, defense_score = _planet_military(conn, int(cand["planet_id"]))
            metal = int(cand.get("metal") or 0)
            crystal = int(cand.get("crystal") or 0)
            fuel = int(cand.get("fuel_cells") or 0)
            opp = _score_opportunity(
                metal=metal,
                crystal=crystal,
                fuel=fuel,
                fleet_score=fleet_score,
                defense_score=defense_score,
                offline_hours=offline_h,
                threat=threat,
                bounty_credits=bounty_credits,
                turtle=turtle,
            )
            # Estimate fallback intel only when no spy report yet.
            write_intel = opp >= opportunity_floor or (
                spy_bias >= 0.7 and opp >= max(15, opportunity_floor - 15)
            )
            if write_intel and intel_writes < MAX_SPIES_PER_TICK:
                _write_intel(
                    conn,
                    bot_player_id=bot_player_id,
                    target_planet_id=int(cand["planet_id"]),
                    target_player_id=pid,
                    galaxy=int(cand["galaxy"]),
                    system=int(cand["system"]),
                    position=int(cand["position"]),
                    resources_score=metal + crystal,
                    fleet_score=fleet_score,
                    defense_score=defense_score,
                    opportunity=opp,
                    now=now,
                )
                intel_writes += 1
        if opp < opportunity_floor:
            continue
        better = opp > best_opp or (
            opp == best_opp
            and bounty_credits > int((best or {}).get("bounty_credits") or 0)
        )
        if better:
            best_opp = opp
            best = {
                **cand,
                "opportunity": opp,
                "threat": threat,
                "bounty_credits": bounty_credits,
                "fleet_score": fleet_score,
                "defense_score": defense_score,
                "offline_hours": offline_h,
                "from_spy_intel": bool(stored),
            }
    return best


def dispatch_raid_from_base(
    conn,
    base: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    force_playtime: bool = False,
) -> Dict[str, Any]:
    """Pick a target and send a real attack fleet from the faction bot."""
    if not is_pirates_ai_enabled(conn=conn):
        return {"ok": False, "error": "ai_disabled"}

    ts = float(now if now is not None else _now())
    galaxy = int(base["galaxy"])
    heat_snap = get_galaxy_heat(conn, galaxy)
    heat = int(heat_snap.get("heat") or 0)
    if heat < HEAT_THRESHOLDS["raids"]:
        return {"ok": False, "error": "heat_below_raids", "heat": heat}

    faction_key = str(base["faction_key"])
    bot = ensure_faction_bot(faction_key, conn=conn)
    if not bot:
        return {"ok": False, "error": "bot_missing"}

    from .bases import list_faction_defs
    from .bot_state import bot_may_act, ensure_bot_state, personality_raid_modifiers

    state = ensure_bot_state(
        conn, bot_player_id=int(bot["player_id"]), faction_key=faction_key, now=ts
    )
    if not force_playtime:
        gate = bot_may_act(state, now=ts)
        if not gate.get("ok"):
            log_pirate_action(
                conn,
                kind="raid_skip",
                faction_key=faction_key,
                base_id=int(base["id"]),
                galaxy_id=galaxy,
                bot_player_id=int(bot["player_id"]),
                message=f"gate: {gate.get('reason')}",
                payload=dict(gate),
            )
            return {"ok": False, "error": str(gate.get("reason") or "gated")}

    faction = next(
        (f for f in list_faction_defs(conn) if f["faction_key"] == faction_key),
        None,
    )
    mods = personality_raid_modifiers((faction or {}).get("personality") or {})
    opportunity_floor = int(mods["opportunity_floor"])
    fleet_fraction = float(mods["fleet_fraction"])
    if heat >= HEAT_THRESHOLDS["elite"]:
        fleet_fraction = min(0.85, fleet_fraction + 0.15)

    target = _pick_best_target(
        conn,
        bot_player_id=int(bot["player_id"]),
        galaxy=galaxy,
        faction_key=faction_key,
        now=ts,
        opportunity_floor=opportunity_floor,
        turtle=float(mods["turtle"]),
        spy_bias=float(mods["spy_bias"]),
    )
    if not target:
        log_pirate_action(
            conn,
            kind="raid_skip",
            faction_key=faction_key,
            base_id=int(base["id"]),
            galaxy_id=galaxy,
            message="no opportunity target",
        )
        return {"ok": False, "error": "no_target"}

    if heat >= HEAT_THRESHOLDS["elite"] and int(target.get("bounty_credits") or 0) >= 2000:
        fleet_fraction = min(0.9, fleet_fraction + 0.1)

    from .play_loop import reserve_fraction_for_personality

    reserve = reserve_fraction_for_personality(str(state.get("personality") or "aggressive"))
    fleet = _raid_fleet_from_hangar(
        conn,
        planet_id=int(bot["planet_id"]),
        fraction=fleet_fraction,
        reserve_fraction=reserve,
    )
    if not fleet:
        return {"ok": False, "error": "empty_fleet"}

    from ..fleet import send_fleet

    ok, reason, meta = send_fleet(
        player_id=int(bot["player_id"]),
        origin_planet_id=int(bot["planet_id"]),
        mission_type="attack",
        target_galaxy=int(target["galaxy"]),
        target_system=int(target["system"]),
        target_position=int(target["position"]),
        ships=fleet,
        resources={},
        speed_percent=100,
        conn=conn,
    )
    if not ok:
        log_pirate_action(
            conn,
            kind="raid_failed",
            faction_key=faction_key,
            base_id=int(base["id"]),
            galaxy_id=galaxy,
            target_player_id=int(target["player_id"]),
            message=f"send failed: {reason}",
            severity="error",
            payload={"reason": reason},
        )
        return {"ok": False, "error": reason}

    fleet_id = int((meta or {}).get("fleet", {}).get("id") or 0)
    if faction_key == "void_cult" and float(mods.get("spy_bias") or 0) >= 0.7:
        try:
            from .infiltration import start_infiltration

            start_infiltration(
                conn,
                planet_id=int(target["planet_id"]),
                faction_key=faction_key,
                effect_key="prod_sabotage",
                now=ts,
            )
        except Exception:
            logger.exception("void infiltration on raid failed")
    log_pirate_action(
        conn,
        kind="raid_dispatch",
        faction_key=faction_key,
        base_id=int(base["id"]),
        galaxy_id=galaxy,
        bot_player_id=int(bot["player_id"]),
        target_player_id=int(target["player_id"]),
        message=(
            f"raid → [{target['galaxy']}:{target['system']}:{target['position']}] "
            f"opp={target['opportunity']} bounty={target.get('bounty_credits', 0)}"
        ),
        severity="warn",
        payload={
            "fleet_id": fleet_id,
            "opportunity": target["opportunity"],
            "threat": target["threat"],
            "bounty_credits": target.get("bounty_credits", 0),
            "ships": fleet,
            "fleet_fraction": fleet_fraction,
            "target_planet_id": int(target["planet_id"]),
            "personality": mods,
        },
    )
    return {
        "ok": True,
        "fleet_id": fleet_id,
        "target_player_id": int(target["player_id"]),
        "opportunity": target["opportunity"],
        "bounty_credits": int(target.get("bounty_credits") or 0),
    }


def dispatch_raid_from_home(
    conn,
    bot: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    force_playtime: bool = False,
) -> Dict[str, Any]:
    """Attack from faction homeworld when heat allows (no live base required)."""
    if not is_pirates_ai_enabled(conn=conn):
        return {"ok": False, "error": "ai_disabled"}

    ts = float(now if now is not None else _now())
    faction_key = str(bot["faction_key"])
    galaxy = int(bot.get("galaxy") or 1)
    heat_snap = get_galaxy_heat(conn, galaxy)
    heat = int(heat_snap.get("heat") or 0)
    if heat < HEAT_THRESHOLDS["raids"]:
        return {"ok": False, "error": "heat_below_raids", "heat": heat}

    from .bases import list_faction_defs
    from .bot_state import bot_may_act, ensure_bot_state, personality_raid_modifiers
    from .play_loop import reserve_fraction_for_personality

    state = ensure_bot_state(
        conn, bot_player_id=int(bot["player_id"]), faction_key=faction_key, now=ts
    )
    if not force_playtime:
        gate = bot_may_act(state, now=ts)
        if not gate.get("ok"):
            log_pirate_action(
                conn,
                kind="raid_skip",
                faction_key=faction_key,
                galaxy_id=galaxy,
                bot_player_id=int(bot["player_id"]),
                message=f"home gate: {gate.get('reason')}",
                payload=dict(gate),
            )
            return {"ok": False, "error": str(gate.get("reason") or "gated")}

    faction = next(
        (f for f in list_faction_defs(conn) if f["faction_key"] == faction_key),
        None,
    )
    mods = personality_raid_modifiers((faction or {}).get("personality") or {})
    opportunity_floor = int(mods["opportunity_floor"])
    fleet_fraction = min(
        0.75, float(mods["fleet_fraction"]) * 0.9 + HOME_RAID_STACK_FRACTION * 0.1
    )
    if heat >= HEAT_THRESHOLDS["elite"]:
        fleet_fraction = min(0.85, fleet_fraction + 0.1)

    target = _pick_best_target(
        conn,
        bot_player_id=int(bot["player_id"]),
        galaxy=galaxy,
        faction_key=faction_key,
        now=ts,
        opportunity_floor=opportunity_floor,
        turtle=float(mods["turtle"]),
        spy_bias=float(mods["spy_bias"]),
    )
    if not target:
        return {"ok": False, "error": "no_target"}

    reserve = reserve_fraction_for_personality(str(state.get("personality") or "aggressive"))
    fleet = _raid_fleet_from_hangar(
        conn,
        planet_id=int(bot["planet_id"]),
        fraction=fleet_fraction,
        reserve_fraction=reserve,
    )
    if not fleet:
        return {"ok": False, "error": "empty_fleet"}

    from ..fleet import send_fleet

    ok, reason, meta = send_fleet(
        player_id=int(bot["player_id"]),
        origin_planet_id=int(bot["planet_id"]),
        mission_type="attack",
        target_galaxy=int(target["galaxy"]),
        target_system=int(target["system"]),
        target_position=int(target["position"]),
        ships=fleet,
        resources={},
        speed_percent=100,
        conn=conn,
    )
    if not ok:
        log_pirate_action(
            conn,
            kind="raid_failed",
            faction_key=faction_key,
            galaxy_id=galaxy,
            bot_player_id=int(bot["player_id"]),
            target_player_id=int(target["player_id"]),
            message=f"home send failed: {reason}",
            severity="error",
            payload={"reason": reason, "origin": "home"},
        )
        return {"ok": False, "error": reason}

    fleet_id = int((meta or {}).get("fleet", {}).get("id") or 0)
    log_pirate_action(
        conn,
        kind="raid_dispatch",
        faction_key=faction_key,
        galaxy_id=galaxy,
        bot_player_id=int(bot["player_id"]),
        target_player_id=int(target["player_id"]),
        message=(
            f"home raid → [{target['galaxy']}:{target['system']}:{target['position']}] "
            f"opp={target['opportunity']}"
        ),
        severity="warn",
        payload={
            "fleet_id": fleet_id,
            "opportunity": target["opportunity"],
            "threat": target["threat"],
            "ships": fleet,
            "origin": "home",
            "target_planet_id": int(target["planet_id"]),
            "from_spy_intel": bool(target.get("from_spy_intel")),
        },
    )
    return {
        "ok": True,
        "fleet_id": fleet_id,
        "target_player_id": int(target["player_id"]),
        "opportunity": target["opportunity"],
        "origin": "home",
    }


def dispatch_spy_from_home(
    conn,
    bot: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    force_playtime: bool = False,
) -> Dict[str, Any]:
    """Send a real spy fleet (veil_probe) from the faction homeworld."""
    if not is_pirates_ai_enabled(conn=conn):
        return {"ok": False, "error": "ai_disabled"}

    ts = float(now if now is not None else _now())
    faction_key = str(bot["faction_key"])
    galaxy = int(bot.get("galaxy") or 1)
    heat = int(get_galaxy_heat(conn, galaxy).get("heat") or 0)
    if heat < HEAT_THRESHOLDS["patrol"]:
        return {"ok": False, "error": "heat_below_patrol", "heat": heat}

    from .bot_state import bot_may_act, ensure_bot_state
    from ..fleet import get_planet_ships, send_fleet

    state = ensure_bot_state(
        conn, bot_player_id=int(bot["player_id"]), faction_key=faction_key, now=ts
    )
    if not force_playtime:
        gate = bot_may_act(state, now=ts)
        if not gate.get("ok"):
            return {"ok": False, "error": str(gate.get("reason") or "gated")}

    # Prefer targets without fresh intel.
    candidates = _candidate_planets(conn, galaxy, limit=30)
    target = None
    for cand in candidates:
        pid = int(cand["player_id"])
        if pid == int(bot["player_id"]) or is_pirate_bot_player(pid, conn=conn):
            continue
        if int(cand.get("vacation_mode_active") or 0):
            continue
        if _fresh_intel_row(
            conn,
            bot_player_id=int(bot["player_id"]),
            target_planet_id=int(cand["planet_id"]),
            now=ts,
        ):
            continue
        target = cand
        break
    if not target and candidates:
        for cand in candidates:
            pid = int(cand["player_id"])
            if pid == int(bot["player_id"]) or is_pirate_bot_player(pid, conn=conn):
                continue
            target = cand
            break
    if not target:
        return {"ok": False, "error": "no_target"}

    planet_id = int(bot["planet_id"])
    player_id = int(bot["player_id"])
    hangar = get_planet_ships(planet_id, conn=conn)
    probes = int(hangar.get("veil_probe") or 0)
    if probes < SPY_PROBE_COUNT:
        log_pirate_action(
            conn,
            kind="spy_skip",
            faction_key=faction_key,
            galaxy_id=galaxy,
            bot_player_id=player_id,
            message="need_ships: veil_probe",
            payload={"probes": probes, "need": SPY_PROBE_COUNT},
        )
        return {"ok": False, "error": "need_ships"}

    ok, reason, meta = send_fleet(
        player_id=player_id,
        origin_planet_id=planet_id,
        mission_type="spy",
        target_galaxy=int(target["galaxy"]),
        target_system=int(target["system"]),
        target_position=int(target["position"]),
        ships={"veil_probe": SPY_PROBE_COUNT},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    if not ok:
        log_pirate_action(
            conn,
            kind="spy_failed",
            faction_key=faction_key,
            galaxy_id=galaxy,
            bot_player_id=player_id,
            target_player_id=int(target["player_id"]),
            message=f"spy send failed: {reason}",
            severity="error",
            payload={"reason": reason},
        )
        return {"ok": False, "error": reason}

    fleet_id = int((meta or {}).get("fleet", {}).get("id") or 0)
    log_pirate_action(
        conn,
        kind="spy_dispatch",
        faction_key=faction_key,
        galaxy_id=galaxy,
        bot_player_id=player_id,
        target_player_id=int(target["player_id"]),
        message=(
            f"spy → [{target['galaxy']}:{target['system']}:{target['position']}] "
            f"probes={SPY_PROBE_COUNT}"
        ),
        payload={
            "fleet_id": fleet_id,
            "target_planet_id": int(target["planet_id"]),
            "probes": SPY_PROBE_COUNT,
        },
    )
    return {
        "ok": True,
        "fleet_id": fleet_id,
        "target_player_id": int(target["player_id"]),
        "target_planet_id": int(target["planet_id"]),
    }


def run_patrol_brain_tick(conn, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Heat ≥ patrol: dispatch real spy fleets from homeworlds."""
    ts = float(now if now is not None else _now())
    if not is_pirates_ai_enabled(conn=conn):
        return {"spies": [], "ai_enabled": False}

    bots = bootstrap_faction_bots(conn=conn)
    dispatched: List[Dict[str, Any]] = []
    for bot in bots:
        if len(dispatched) >= MAX_SPIES_PER_TICK:
            break
        res = dispatch_spy_from_home(conn, bot, now=ts)
        if res.get("ok"):
            dispatched.append(res)
    return {"spies": dispatched, "ai_enabled": True, "count": len(dispatched)}


def run_recycle_brain_tick(conn, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Opportunistic debris recycle near hot galaxies (max 1/tick)."""
    ts = float(now if now is not None else _now())
    if not is_pirates_ai_enabled(conn=conn):
        return {"recycles": [], "ai_enabled": False}

    from ..combat import debris_schema_ready
    from ..db import table_exists
    from ..fleet import get_planet_ships, send_fleet

    if not debris_schema_ready(conn) or not table_exists(conn, "debris_fields"):
        return {"recycles": [], "ai_enabled": True, "count": 0}

    cur = conn.execute(
        """
        SELECT galaxy, system, position, metal, crystal
        FROM debris_fields
        WHERE metal + crystal >= 500
        ORDER BY (metal + crystal) DESC
        LIMIT 8;
        """
    )
    fields = [dict(r) for r in cur.fetchall()]
    if not fields:
        return {"recycles": [], "ai_enabled": True, "count": 0}

    bots = bootstrap_faction_bots(conn=conn)
    dispatched: List[Dict[str, Any]] = []
    for field in fields:
        if len(dispatched) >= MAX_RECYCLES_PER_TICK:
            break
        g = int(field["galaxy"])
        heat = int(get_galaxy_heat(conn, g).get("heat") or 0)
        if heat < HEAT_THRESHOLDS["patrol"]:
            continue
        bot = next((b for b in bots if int(b.get("galaxy") or 0) == g), None) or (
            bots[0] if bots else None
        )
        if not bot:
            break
        planet_id = int(bot["planet_id"])
        player_id = int(bot["player_id"])
        hangar = get_planet_ships(planet_id, conn=conn)
        if int(hangar.get("harvest_reclaimer") or 0) < 1 or int(hangar.get("atlas_hauler") or 0) < 1:
            log_pirate_action(
                conn,
                kind="recycle_skip",
                faction_key=str(bot["faction_key"]),
                galaxy_id=g,
                bot_player_id=player_id,
                message="need_ships: reclaimers",
            )
            continue
        ships = {"harvest_reclaimer": 1, "atlas_hauler": 1}
        ok, reason, meta = send_fleet(
            player_id=player_id,
            origin_planet_id=planet_id,
            mission_type="recycle",
            target_galaxy=g,
            target_system=int(field["system"]),
            target_position=int(field["position"]),
            ships=ships,
            resources={},
            speed_percent=100,
            conn=conn,
        )
        if not ok:
            log_pirate_action(
                conn,
                kind="recycle_skip",
                faction_key=str(bot["faction_key"]),
                galaxy_id=g,
                bot_player_id=player_id,
                message=f"recycle failed: {reason}",
                payload={"reason": reason, "field": field},
            )
            continue
        fleet_id = int((meta or {}).get("fleet", {}).get("id") or 0)
        log_pirate_action(
            conn,
            kind="recycle_dispatch",
            faction_key=str(bot["faction_key"]),
            galaxy_id=g,
            bot_player_id=player_id,
            message=f"recycle → [{g}:{field['system']}:{field['position']}]",
            payload={"fleet_id": fleet_id, "ships": ships, "field": field},
        )
        dispatched.append({"ok": True, "fleet_id": fleet_id, "galaxy": g})
    return {"recycles": dispatched, "ai_enabled": True, "count": len(dispatched)}


def run_raid_brain_tick(
    conn,
    *,
    now: Optional[float] = None,
    skip_home_raids: bool = False,
) -> Dict[str, Any]:
    """Base raids first; optional homeworld fill (skipped when play_loop already raided)."""
    ts = float(now if now is not None else _now())
    if not is_pirates_ai_enabled(conn=conn):
        return {"raids": [], "ai_enabled": False}

    from .crisis import galaxy_in_pirate_war

    dispatched: List[Dict[str, Any]] = []
    bases = list_live_bases(conn, limit=50)
    bases = sorted(
        bases,
        key=lambda b: (int(b.get("activity") or 0), int(b.get("strength") or 0)),
        reverse=True,
    )
    war_pressure = any(
        galaxy_in_pirate_war(conn, int(b["galaxy"]))
        for b in bases
        if b.get("status") in LIVE_STATUSES
    )
    bots = bootstrap_faction_bots(conn=conn)
    if not war_pressure:
        war_pressure = any(
            galaxy_in_pirate_war(conn, int(b.get("galaxy") or 1)) for b in bots
        )
    raid_cap = MAX_RAIDS_PER_TICK_WAR if war_pressure else MAX_RAIDS_PER_TICK
    for base in bases:
        if len(dispatched) >= raid_cap:
            break
        if base.get("status") not in LIVE_STATUSES:
            continue
        res = dispatch_raid_from_base(conn, base, now=ts)
        if res.get("ok"):
            dispatched.append({**res, "origin": "base"})

    if not skip_home_raids and len(dispatched) < raid_cap:
        for bot in bots:
            if len(dispatched) >= raid_cap:
                break
            res = dispatch_raid_from_home(conn, bot, now=ts)
            if res.get("ok"):
                dispatched.append(res)

    return {
        "raids": dispatched,
        "ai_enabled": True,
        "count": len(dispatched),
        "war_pressure": war_pressure,
    }


MAX_COLONIZES_PER_TICK = 1


def dispatch_colonize_from_home(
    conn,
    bot: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    force_playtime: bool = False,
) -> Dict[str, Any]:
    """Send a real colonize fleet (seed_ark) to a free classic slot."""
    if not is_pirates_ai_enabled(conn=conn):
        return {"ok": False, "error": "ai_disabled"}

    import random

    ts = float(now if now is not None else _now())
    faction_key = str(bot["faction_key"])
    galaxy = int(bot.get("galaxy") or 1)
    heat = int(get_galaxy_heat(conn, galaxy).get("heat") or 0)
    if heat < HEAT_THRESHOLDS["patrol"]:
        return {"ok": False, "error": "heat_below_patrol", "heat": heat}

    from ..models import get_planets_by_player
    from ..fleet import get_planet_ships, send_fleet
    from .accounts import ensure_bot_expansion_ready, ensure_bot_planet_floor
    from .bases import _pick_free_slot
    from .bot_state import bot_may_act, ensure_bot_state

    ensure_bot_planet_floor(conn, dict(bot))
    ensure_bot_expansion_ready(conn, dict(bot))
    planets = get_planets_by_player(int(bot["player_id"]), conn=conn) or []
    if len(planets) >= BOT_COLONY_SOFT_CAP:
        return {"ok": False, "error": "colony_cap"}

    state = ensure_bot_state(
        conn, bot_player_id=int(bot["player_id"]), faction_key=faction_key, now=ts
    )
    mood = dict(state.get("mood") or {})
    cool_until = mood.get("colony_wipe_cooldown_until")
    if cool_until is not None:
        try:
            if float(cool_until) > ts:
                return {"ok": False, "error": "wipe_cooldown"}
        except (TypeError, ValueError):
            pass
    if not force_playtime:
        gate = bot_may_act(state, now=ts)
        if not gate.get("ok"):
            return {"ok": False, "error": str(gate.get("reason") or "gated")}

    # Prefer hottest galaxy for expansion, fall back to home galaxy.
    target_galaxy = galaxy
    try:
        cur = conn.execute(
            """
            SELECT galaxy_id FROM galaxy_heat
            WHERE heat >= ?
            ORDER BY heat DESC
            LIMIT 1;
            """,
            (HEAT_THRESHOLDS["patrol"],),
        )
        row = cur.fetchone()
        if row:
            target_galaxy = int(row["galaxy_id"])
    except Exception:
        pass

    coords = _pick_free_slot(
        conn, int(target_galaxy), rng=random.Random(int(ts) ^ int(bot["player_id"]))
    )
    if not coords:
        return {"ok": False, "error": "no_free_slot"}
    tg, tsys, tpos = coords

    planet_id = int(bot["planet_id"])
    player_id = int(bot["player_id"])
    hangar = get_planet_ships(planet_id, conn=conn)
    if int(hangar.get("seed_ark") or 0) < 1:
        log_pirate_action(
            conn,
            kind="colonize_skip",
            faction_key=faction_key,
            galaxy_id=int(tg),
            bot_player_id=player_id,
            message="need_ships: seed_ark",
        )
        return {"ok": False, "error": "need_ships"}

    ok, reason, meta = send_fleet(
        player_id=player_id,
        origin_planet_id=planet_id,
        mission_type="colonize",
        target_galaxy=int(tg),
        target_system=int(tsys),
        target_position=int(tpos),
        ships={"seed_ark": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    if not ok:
        log_pirate_action(
            conn,
            kind="colonize_failed",
            faction_key=faction_key,
            galaxy_id=int(tg),
            bot_player_id=player_id,
            message=f"colonize send failed: {reason}",
            severity="error",
            payload={"reason": reason, "coords": [tg, tsys, tpos]},
        )
        return {"ok": False, "error": reason}

    fleet_id = int((meta or {}).get("fleet", {}).get("id") or 0)
    log_pirate_action(
        conn,
        kind="colonize_dispatch",
        faction_key=faction_key,
        galaxy_id=int(tg),
        bot_player_id=player_id,
        message=f"colonize → [{tg}:{tsys}:{tpos}]",
        payload={"fleet_id": fleet_id, "coords": [tg, tsys, tpos]},
    )
    return {
        "ok": True,
        "fleet_id": fleet_id,
        "galaxy": int(tg),
        "system": int(tsys),
        "position": int(tpos),
    }


def run_colonize_brain_tick(conn, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Heat ≥ patrol: occasional Seed-Ark colonize from faction homes."""
    ts = float(now if now is not None else _now())
    if not is_pirates_ai_enabled(conn=conn):
        return {"colonizes": [], "ai_enabled": False}

    bots = bootstrap_faction_bots(conn=conn)
    dispatched: List[Dict[str, Any]] = []
    for bot in bots:
        if len(dispatched) >= MAX_COLONIZES_PER_TICK:
            break
        res = dispatch_colonize_from_home(conn, bot, now=ts)
        if res.get("ok"):
            dispatched.append(res)
    return {"colonizes": dispatched, "ai_enabled": True, "count": len(dispatched)}
