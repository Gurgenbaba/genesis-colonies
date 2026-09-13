"""Strategic fleet decisions for the Living Universe shift crew.

This module is a decision layer only. It deliberately reuses the canonical
shipyard, fleet, asteroid and world-boss owners; it does not add queues,
movement state or combat math.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, localcontext
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

WORLD_BOSS_SAFE_HP_RATIO = Decimal("0.05")
WORLD_BOSS_MIN_COMBAT_POOL = 8
WORLD_BOSS_MIN_SELECTED_HULLS = 4
WORLD_BOSS_SAFETY_PARTS = 2_500
WORLD_BOSS_FALLBACK_SAFETY_PARTS = 5_000
ASTEROID_MAX_RECLAIMERS_PER_FLIGHT = 24
ASTEROID_RECLAIMER_TARGETS = {
    "economy": 16,
    "aggressive": 8,
    "turtle": 12,
    "spy": 8,
    "swarm": 10,
    "elite": 12,
}


def _stable_roll(player_id: int, namespace: str, sequence: int, modulo: int) -> int:
    cap = max(1, int(modulo))
    raw = f"living-universe:{namespace}:{int(player_id)}:{int(sequence)}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return int(digest[:16], 16) % cap


def _owned_planets(player_id: int, *, conn) -> list[Dict[str, Any]]:
    from .models import get_planets_by_player

    planets = [
        dict(row)
        for row in (get_planets_by_player(int(player_id), conn=conn) or [])
        if int(row["id"] or 0) > 0
    ]
    planets.sort(key=lambda row: int(row.get("id") or 0))
    return planets


def _maybe_build_reclaimers(
    conn,
    player_id: int,
    *,
    personality: str,
    planets: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Grow a real Reclaimer reserve through the canonical shipyard."""
    from .fleet import get_planet_ships
    from .shipyard import build_ships

    target = max(2, int(ASTEROID_RECLAIMER_TARGETS.get(str(personality), 10)))
    empire_hangar = 0
    for planet in planets:
        empire_hangar += max(
            0,
            int(get_planet_ships(int(planet["id"]), conn=conn).get("harvest_reclaimer") or 0),
        )
    if empire_hangar >= target:
        return {
            "ok": True,
            "built": False,
            "reason": "reserve_ready",
            "have": empire_hangar,
            "target": target,
        }

    amount = min(8, max(1, target - empire_hangar))
    for planet in planets:
        planet_id = int(planet["id"])
        ok, reason, meta = build_ships(
            player_id=int(player_id),
            planet_id=planet_id,
            ship_key="harvest_reclaimer",
            amount=int(amount),
            conn=conn,
        )
        if ok:
            return {
                "ok": True,
                "built": True,
                "planet_id": planet_id,
                "ship_key": "harvest_reclaimer",
                "amount": int(amount),
                "target": target,
                "meta": meta,
            }
        if str(reason or "") not in {
            "not_enough_resources",
            "queue_full",
            "requirements",
            "shipyard_level",
        }:
            break
    return {
        "ok": True,
        "built": False,
        "reason": "shipyard_blocked",
        "have": empire_hangar,
        "target": target,
    }


def _asteroid_pair_rank(
    planet: Mapping[str, Any], asteroid: Mapping[str, Any]
) -> Tuple[int, int, int, int, int]:
    pg = int(planet.get("galaxy") or 1)
    ps = int(planet.get("system") or 1)
    ag = int(asteroid.get("galaxy") or 1)
    ass = int(asteroid.get("system") or 1)
    total = max(0, int(asteroid.get("total") or 0))
    return (
        0 if pg == ag else 1,
        abs(pg - ag),
        abs(ps - ass),
        -total,
        int(asteroid.get("id") or 0),
    )


def maybe_harvest_asteroid(
    conn,
    player_id: int,
    *,
    now: float,
    action_seq: int,
    personality: str,
) -> Dict[str, Any]:
    """Fly a real recycle mission to a useful active asteroid or prepare hulls."""
    from .asteroids import list_active_asteroids
    from .fleet import get_planet_ships, send_fleet

    planets = _owned_planets(int(player_id), conn=conn)
    if not planets:
        return {"ok": False, "sent": False, "built": False, "reason": "no_planets"}

    asteroids = [
        dict(row)
        for row in list_active_asteroids(conn=conn, now=float(now), limit=64)
        if int(row.get("total") or 0) > 0
        and int(row.get("recycler_slots_needed") or 0) > 0
    ]
    if not asteroids:
        return {"ok": True, "sent": False, "built": False, "reason": "no_asteroid"}

    origin_rows: list[tuple[Dict[str, Any], int]] = []
    for planet in planets:
        planet_id = int(planet["id"])
        available = max(
            0,
            int(get_planet_ships(planet_id, conn=conn).get("harvest_reclaimer") or 0),
        )
        if available > 0:
            origin_rows.append((planet, available))

    if not origin_rows:
        build = _maybe_build_reclaimers(
            conn,
            int(player_id),
            personality=str(personality),
            planets=planets,
        )
        return {
            "ok": True,
            "sent": False,
            "built": bool(build.get("built")),
            "reason": "preparing_reclaimers",
            "shipyard": build,
        }

    pairs: list[tuple[Tuple[int, int, int, int, int], Dict[str, Any], int, Dict[str, Any]]] = []
    for planet, available in origin_rows:
        for asteroid in asteroids:
            pairs.append((_asteroid_pair_rank(planet, asteroid), planet, available, asteroid))
    pairs.sort(key=lambda item: item[0])
    if not pairs:
        return {"ok": True, "sent": False, "built": False, "reason": "no_route"}

    # Nearby/rich targets lead, but rotate a little among the best few so all
    # autonomous commanders do not dog-pile the exact same field in lockstep.
    shortlist = pairs[: min(5, len(pairs))]
    pick = shortlist[
        _stable_roll(int(player_id), "asteroid-target", int(action_seq), len(shortlist))
    ]
    _rank, planet, available, asteroid = pick
    needed = max(1, int(asteroid.get("recycler_slots_needed") or 1))

    # A large field with only one available hull looks artificial. Build the
    # reserve first; a genuinely tiny one-slot remainder may still be cleaned up.
    if needed > 1 and available < 2:
        build = _maybe_build_reclaimers(
            conn,
            int(player_id),
            personality=str(personality),
            planets=planets,
        )
        return {
            "ok": True,
            "sent": False,
            "built": bool(build.get("built")),
            "reason": "preparing_reclaimers",
            "shipyard": build,
        }

    amount = max(
        1,
        min(
            int(available),
            int(needed),
            int(ASTEROID_MAX_RECLAIMERS_PER_FLIGHT),
        ),
    )
    speed_choices = (80, 90, 100)
    speed_percent = speed_choices[
        _stable_roll(int(player_id), "asteroid-speed", int(action_seq), len(speed_choices))
    ]
    ok, reason, meta = send_fleet(
        player_id=int(player_id),
        origin_planet_id=int(planet["id"]),
        mission_type="recycle",
        target_galaxy=int(asteroid["galaxy"]),
        target_system=int(asteroid["system"]),
        target_position=int(asteroid["position"]),
        ships={"harvest_reclaimer": int(amount)},
        resources={},
        speed_percent=int(speed_percent),
        conn=conn,
    )
    if not ok:
        return {
            "ok": True,
            "sent": False,
            "built": False,
            "reason": str(reason or "blocked"),
            "planet_id": int(planet["id"]),
            "asteroid_id": int(asteroid["id"]),
        }
    effective_ships = dict((meta or {}).get("effective_ships") or {"harvest_reclaimer": amount})
    return {
        "ok": True,
        "sent": True,
        "built": False,
        "fleet_id": int((meta or {}).get("fleet", {}).get("id") or 0),
        "planet_id": int(planet["id"]),
        "asteroid_id": int(asteroid["id"]),
        "coords": str(asteroid.get("coords") or ""),
        "ships": effective_ships,
        "speed_percent": int(speed_percent),
    }


def _world_boss_force_for_event(
    conn,
    player_id: int,
    event: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    from .fleet import get_planet_ships
    from .world_boss import (
        combat_ships_from_hangar,
        defender_ships_for_event,
        select_world_boss_auto_attack_ships,
    )

    defender = defender_ships_for_event(event, conn=conn)
    max_hp = max(1, int(event.get("max_hp") or 1))
    event_id = int(event.get("id") or 0)
    best: Optional[Dict[str, Any]] = None
    for planet in _owned_planets(int(player_id), conn=conn):
        planet_id = int(planet["id"])
        hangar = get_planet_ships(planet_id, conn=conn)
        pool = combat_ships_from_hangar(hangar)
        pool_count = int(sum(max(0, int(v or 0)) for v in pool.values()))
        if pool_count < WORLD_BOSS_MIN_COMBAT_POOL:
            continue
        ships, meta = select_world_boss_auto_attack_ships(
            hangar,
            defender_ships=defender,
            max_hp=max_hp,
            event_id=event_id,
            conn=conn,
            safety_parts=WORLD_BOSS_SAFETY_PARTS,
        )
        sent_count = int(sum(max(0, int(v or 0)) for v in ships.values()))
        if sent_count < WORLD_BOSS_MIN_SELECTED_HULLS:
            ships, meta = select_world_boss_auto_attack_ships(
                hangar,
                defender_ships=defender,
                max_hp=max_hp,
                event_id=event_id,
                conn=conn,
                safety_parts=WORLD_BOSS_FALLBACK_SAFETY_PARTS,
            )
            sent_count = int(sum(max(0, int(v or 0)) for v in ships.values()))
        if sent_count < WORLD_BOSS_MIN_SELECTED_HULLS:
            continue
        candidate = {
            "planet_id": planet_id,
            "ships": dict(ships),
            "sent_count": sent_count,
            "damage_estimate": int((meta or {}).get("damage_estimate") or 0),
            "pool_count": pool_count,
        }
        if best is None or (
            int(candidate["damage_estimate"]), int(candidate["sent_count"])
        ) > (
            int(best["damage_estimate"]), int(best["sent_count"])
        ):
            best = candidate
    return best


def maybe_join_world_boss(
    conn,
    player_id: int,
    *,
    now: float,
    personality: str,
    fallback_planet_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Join at most once per boss with a credible canonical combat force."""
    from .world_boss import can_player_attack_boss, execute_instant_attack, list_active_events

    for event in list_active_events(conn=conn, now=float(now), limit=3):
        max_hp = max(1, int(event.get("max_hp") or 1))
        current_hp = max(0, int(event.get("current_hp") or 0))
        with localcontext() as ctx:
            ctx.prec = max(64, len(str(max_hp)) + 32)
            if Decimal(current_hp) <= Decimal(max_hp) * WORLD_BOSS_SAFE_HP_RATIO:
                continue
        ok, _reason, contribution = can_player_attack_boss(
            int(player_id),
            int(event["id"]),
            conn=conn,
            now=float(now),
            enforce_cooldown=False,
            check_inflight=False,
        )
        if not ok or int((contribution or {}).get("waves") or 0) > 0:
            continue
        force = _world_boss_force_for_event(conn, int(player_id), event)
        if not force:
            if fallback_planet_id is not None:
                try:
                    from .auto_empire import try_build_ships

                    build = try_build_ships(
                        conn,
                        player_id=int(player_id),
                        planet_id=int(fallback_planet_id),
                        personality=str(personality),
                    )
                    return {
                        "ok": True,
                        "joined": False,
                        "building": bool(build.get("ok")),
                        "reason": "preparing_combat_fleet",
                        "shipyard": build,
                    }
                except Exception:
                    pass
            return {
                "ok": True,
                "joined": False,
                "building": False,
                "reason": "insufficient_combat_force",
            }
        strike = execute_instant_attack(
            int(player_id),
            int(event["id"]),
            dict(force["ships"]),
            planet_id=int(force["planet_id"]),
            conn=conn,
            now=float(now),
            auto_select=False,
            hit_mult=1,
        )
        if strike.get("ok"):
            return {
                "ok": True,
                "joined": True,
                "building": False,
                "event_id": int(event["id"]),
                "damage": int(strike.get("damage") or 0),
                "planet_id": int(force["planet_id"]),
                "ships": dict(force["ships"]),
                "sent_count": int(force["sent_count"]),
                "pool_count": int(force["pool_count"]),
            }
        return {
            "ok": True,
            "joined": False,
            "building": False,
            "reason": str(strike.get("error") or "attack_blocked"),
        }
    return {"ok": True, "joined": False, "building": False, "reason": "no_eligible_boss"}
