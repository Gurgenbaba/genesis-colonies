"""AI colony destruction (EPIC-21 Phase 2 / GC-P24).

Combat wipe of pirate-bot colonies only — never homeworld. Requires planet_breaker hull
and a full military wipe (hangar + defense empty after combat). Analog to classic
moon-destroy: expensive, intentional, rare.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

PLANET_BREAKER_KEY = "planet_breaker"
COLONY_DESTROY_BOUNTY = 5000
COLONY_DESTROY_HEAT = 20
WIPE_COOLDOWN_SEC = 24 * 3600
RECOLONIZE_COOLDOWN_SEC = 6 * 3600
COMBAT_VS_BOT_BOUNTY = 150


def _now() -> float:
    return time.time()


def destroy_colony_planet(
    conn,
    *,
    planet_id: int,
    owner_player_id: int,
    reason: str = "combat_wipe",
) -> Dict[str, Any]:
    """Delete a non-homeworld colony. Hard-blocks homeworld and last planet."""
    from ..models import get_homeworld, get_planets_by_player
    from ..planet_evolution.repository import set_active_planet_id

    pid = int(planet_id)
    owner = int(owner_player_id)
    cur = conn.execute(
        """
        SELECT id, player_id, COALESCE(is_homeworld, 0) AS is_homeworld,
               galaxy, system, position, name
        FROM planets WHERE id = ? LIMIT 1;
        """,
        (pid,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "planet_missing"}
    if int(row["player_id"]) != owner:
        return {"ok": False, "error": "owner_mismatch"}
    if int(row["is_homeworld"] or 0):
        return {"ok": False, "error": "homeworld_protected"}

    planets = get_planets_by_player(owner, conn=conn) or []
    if len(planets) <= 1:
        return {"ok": False, "error": "last_planet"}

    homeworld = get_homeworld(owner, conn=conn)
    if not homeworld:
        return {"ok": False, "error": "no_homeworld"}
    hw_id = int(homeworld["id"])

    # Bounce inbound fleets targeting this planet (mark returning / failed safely).
    try:
        from ..fleet import recall_fleet_movement

        cur = conn.execute(
            """
            SELECT id, player_id FROM fleet_movements
            WHERE target_planet_id = ? AND status IN ('outbound', 'holding');
            """,
            (pid,),
        )
        for mv in cur.fetchall():
            try:
                recall_fleet_movement(int(mv["player_id"]), int(mv["id"]), conn=conn)
            except Exception:
                logger.exception("recall inbound on colony destroy failed fleet=%s", mv["id"])
    except Exception:
        logger.exception("inbound recall pass failed planet=%s", pid)

    # Cancel outbound fleets originating from the doomed colony.
    try:
        from ..fleet import recall_fleet_movement

        cur = conn.execute(
            """
            SELECT id FROM fleet_movements
            WHERE origin_planet_id = ? AND player_id = ?
              AND status IN ('outbound', 'holding');
            """,
            (pid, owner),
        )
        for mv in cur.fetchall():
            recall_fleet_movement(owner, int(mv["id"]), conn=conn)
    except Exception:
        logger.exception("origin recall pass failed planet=%s", pid)

    try:
        set_active_planet_id(owner, hw_id, conn)
    except Exception:
        logger.exception("active planet switch failed owner=%s", owner)

    coords = (
        int(row["galaxy"] or 1),
        int(row["system"] or 1),
        int(row["position"] or 1),
    )
    name = str(row["name"] or "")
    cur = conn.execute(
        "DELETE FROM planets WHERE id = ? AND player_id = ? AND COALESCE(is_homeworld, 0) = 0;",
        (pid, owner),
    )
    if int(cur.rowcount or 0) <= 0:
        return {"ok": False, "error": "delete_failed"}

    try:
        from ..ranking import recompute_and_upsert_score

        recompute_and_upsert_score(owner, conn=conn)
    except Exception:
        logger.exception("score refresh after colony destroy failed owner=%s", owner)

    return {
        "ok": True,
        "deleted_planet_id": pid,
        "owner_player_id": owner,
        "active_planet_id": hw_id,
        "coords": coords,
        "name": name,
        "reason": reason,
    }


def _recent_wipe_on_planet(conn, planet_id: int, *, now: float) -> bool:
    cur = conn.execute(
        """
        SELECT 1 FROM pirate_action_log
        WHERE kind = 'bot_colony_destroyed'
          AND ts >= ?
          AND message LIKE ?
        LIMIT 1;
        """,
        (float(now) - WIPE_COOLDOWN_SEC, f"%planet={int(planet_id)}%"),
    )
    return cur.fetchone() is not None


def _consume_planet_breakers(
    conn,
    *,
    return_ships: Dict[str, int],
    amount: int = 1,
) -> Tuple[bool, Dict[str, int]]:
    key = PLANET_BREAKER_KEY
    have = int(return_ships.get(key) or 0)
    if have < amount:
        return False, return_ships
    out = dict(return_ships)
    left = have - amount
    if left > 0:
        out[key] = left
    else:
        out.pop(key, None)
    return True, out


def maybe_destroy_colony_after_combat(
    conn,
    *,
    attacker_id: int,
    defender_id: int,
    target_planet_id: int,
    combat_result: Any,
    return_ships: Mapping[str, int],
    movement_id: Optional[int] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Wipe non-homeworld colony after attacker win + full military wipe + breaker.

    AI victims: faction bounty + recolonize cooldown. Human victims: threat + heat.
    """
    import json

    from .accounts import faction_key_for_username, is_pirate_bot_player
    from .bounty import add_player_bounty
    from .heat import record_heat_event
    from .log import log_pirate_action

    ts = float(now if now is not None else _now())
    if combat_result is None:
        return {"ok": False, "error": "no_combat"}
    if str(getattr(combat_result, "winner", "") or "") != "attacker":
        return {"ok": False, "error": "attacker_must_win"}

    cur = conn.execute(
        """
        SELECT id, player_id, COALESCE(is_homeworld, 0) AS is_homeworld,
               galaxy, system, position
        FROM planets WHERE id = ? LIMIT 1;
        """,
        (int(target_planet_id),),
    )
    planet = cur.fetchone()
    if not planet:
        return {"ok": False, "error": "planet_missing"}
    if int(planet["is_homeworld"] or 0):
        return {"ok": False, "error": "homeworld_protected"}

    cur = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS c FROM planet_ships WHERE planet_id = ?;",
        (int(target_planet_id),),
    )
    ships_left = int((cur.fetchone() or {"c": 0})["c"] or 0)
    defense_left = 0
    try:
        from ..db import table_exists

        if table_exists(conn, "planet_defense"):
            cur = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS c FROM planet_defense WHERE planet_id = ?;",
                (int(target_planet_id),),
            )
            defense_left = int((cur.fetchone() or {"c": 0})["c"] or 0)
    except Exception:
        pass
    if ships_left > 0 or defense_left > 0:
        return {
            "ok": False,
            "error": "military_not_wiped",
            "ships_left": ships_left,
            "defense_left": defense_left,
        }

    ships = {str(k): int(v or 0) for k, v in dict(return_ships or {}).items()}
    ok_break, ships_after = _consume_planet_breakers(conn, return_ships=ships, amount=1)
    if not ok_break:
        return {"ok": False, "error": "breaker_required"}

    if _recent_wipe_on_planet(conn, int(target_planet_id), now=ts):
        return {"ok": False, "error": "wipe_cooldown"}

    wipe = destroy_colony_planet(
        conn,
        planet_id=int(target_planet_id),
        owner_player_id=int(defender_id),
        reason="combat_wipe",
    )
    if not wipe.get("ok"):
        return wipe

    defender_is_ai = is_pirate_bot_player(int(defender_id), conn=conn)
    faction_key = None
    if defender_is_ai:
        cur = conn.execute(
            "SELECT username FROM users WHERE id = ? LIMIT 1;",
            (int(defender_id),),
        )
        urow = cur.fetchone()
        username = str(urow["username"] or "") if urow else ""
        faction_key = faction_key_for_username(username) or "crimson_corsairs"
        try:
            add_player_bounty(
                conn,
                int(attacker_id),
                faction_key,
                credits=COLONY_DESTROY_BOUNTY,
                kills=1,
                now=ts,
            )
        except Exception:
            logger.exception("colony destroy bounty failed")
        try:
            from .bot_state import ensure_bot_state

            state = ensure_bot_state(
                conn, bot_player_id=int(defender_id), faction_key=faction_key, now=ts
            )
            mood = dict(state.get("mood") or {})
            mood["colony_wipe_cooldown_until"] = ts + RECOLONIZE_COOLDOWN_SEC
            conn.execute(
                "UPDATE pirate_bot_state SET mood_json = ?, updated_at = ? WHERE bot_player_id = ?;",
                (json.dumps(mood), ts, int(defender_id)),
            )
        except Exception:
            logger.exception("recolonize cooldown set failed")
    else:
        try:
            from .threat import recompute_player_threat

            recompute_player_threat(int(attacker_id), conn=conn)
        except Exception:
            logger.exception("human wipe threat recompute failed")

    try:
        record_heat_event(
            conn,
            int(planet["galaxy"] or 1),
            "combat",
            amount=COLONY_DESTROY_HEAT,
        )
    except Exception:
        logger.exception("colony destroy heat failed")

    log_kind = "bot_colony_destroyed" if defender_is_ai else "colony_destroyed"
    log_pirate_action(
        conn,
        kind=log_kind,
        faction_key=faction_key,
        bot_player_id=int(defender_id) if defender_is_ai else None,
        target_player_id=int(attacker_id),
        galaxy_id=int(planet["galaxy"] or 1),
        message=(
            f"colony wiped planet={target_planet_id} "
            f"by={attacker_id} coords={wipe.get('coords')}"
        ),
        severity="warn",
        payload={
            "planet_id": int(target_planet_id),
            "attacker_id": int(attacker_id),
            "defender_id": int(defender_id),
            "defender_is_ai": defender_is_ai,
            "movement_id": movement_id,
            "coords": wipe.get("coords"),
            "name": wipe.get("name"),
            "bounty": COLONY_DESTROY_BOUNTY if defender_is_ai else 0,
        },
    )
    wipe["return_ships"] = ships_after
    wipe["faction_key"] = faction_key
    wipe["defender_is_ai"] = defender_is_ai
    wipe["bounty"] = COLONY_DESTROY_BOUNTY if defender_is_ai else 0
    return wipe


def maybe_destroy_ai_colony_after_combat(*args, **kwargs) -> Dict[str, Any]:
    """Deprecated alias → maybe_destroy_colony_after_combat."""
    return maybe_destroy_colony_after_combat(*args, **kwargs)


def note_combat_vs_bot_bounty(
    conn,
    *,
    attacker_id: int,
    defender_id: int,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Small bounty when humans fight living AI (even without wipe)."""
    from .accounts import faction_key_for_username, is_pirate_bot_player
    from .bounty import add_player_bounty

    if not is_pirate_bot_player(int(defender_id), conn=conn):
        return {"ok": False, "error": "not_ai"}
    if is_pirate_bot_player(int(attacker_id), conn=conn):
        return {"ok": False, "error": "bot_vs_bot"}
    cur = conn.execute("SELECT username FROM users WHERE id = ? LIMIT 1;", (int(defender_id),))
    urow = cur.fetchone()
    username = str(urow["username"] or "") if urow else ""
    faction_key = faction_key_for_username(username)
    if not faction_key:
        return {"ok": False, "error": "no_faction"}
    return add_player_bounty(
        conn,
        int(attacker_id),
        faction_key,
        credits=COMBAT_VS_BOT_BOUNTY,
        kills=0,
        now=now,
    )
