"""
Zentrale Logik-Fassade für Genesis Colonies.

Dieses Modul bündelt die wichtigsten Funktionen für app.py und Templates
und delegiert die eigentliche Arbeit an spezialisierte Module:

- game.resources:   Ressourcen-Tick, Produktion, Lager
- game.buildings:   Gebäude-Kosten, Bauzeiten, Build-Queue
- game.research:    Forschungs-Logik & Research-Queue
- game.techtree:    Tech-Tree-Daten (Gebäude + Forschung)

WICHTIG:
- Multi-User-fähig.
- Keine hardcodierten player_id/user_id Defaults.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

from .models import get_homeworld, get_planet_buildings, get_research_levels
from . import resources as _res
from .resources import (
    update_resources as _update_resources,
    apply_resource_delta_unbounded as _apply_resource_delta_unbounded,
    get_building_production_per_hour as _core_get_bpph,
    get_storage_capacity as _core_get_storage_capacity,
)

from .buildings import (
    get_build_queue_status_for_planet,
    queue_build_for_planet as _queue_build_for_planet,
    cancel_build_job_for_planet as _cancel_build_job_for_planet,
    complete_finished_builds_for_planet,  # finish + score trigger in buildings/models
)

from .research import (
    queue_research as _queue_research,  # signature: (player, tech_key, user_id=None)
    cancel_research_job as _cancel_research_job,
    get_research_status as _get_research_status,
    get_research_modifiers as _get_research_modifiers,
    complete_finished_research as _complete_finished_research,
)
from .effects import get_effect_resolver
from .effects.effect_resolver import EffectResolver

from .techtree import (
    get_techtree_data as _tt_get_techtree_data,
    get_building_tree_status as _tt_get_building_tree_status,
)


# ============================================================================ #
# RESSOURCEN
# ============================================================================ #


def _read_player_live_state_no_writes(
    uid: int,
    conn,
    player: Dict[str, Any],
    planet: Dict[str, Any],
) -> Tuple[Any, Dict[str, int], float, int, int, Dict[str, int]]:
    """Pure read path for polling when writes are skipped (e.g. SQLite lock)."""
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    resolver = get_effect_resolver(
        uid,
        buildings=buildings,
        research=research,
        conn=conn,
        force_refresh=True,
    )
    energy_total, energy_used = resolver.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    storage_caps = get_storage_capacity(buildings, user_id=uid, conn=conn)

    player_view = dict(player)
    player_view["metal"] = planet["metal"]
    player_view["crystal"] = planet["crystal"]
    player_view["fuel_cells"] = planet.get("fuel_cells", 0)
    player_view["energy_total"] = int(energy_total)
    player_view["energy_used"] = int(energy_used)
    return player_view, buildings, ratio, int(energy_total), int(energy_used), storage_caps


def read_player_live_state_for_poll(
    player_id: int,
    conn=None,
) -> Tuple[Any, Dict[str, int], float, int, int, Dict[str, int]]:
    """
    Game-state polling path: throttled queue finish, no rank/score seeding writes.

    - Finishes due queue work player-wide when due or on poll interval.
    - Skips rank recalculation on poll (recalc_ranks=False).
    - May still persist resource accrual when idle time warrants it.
    """
    from .db import begin_write_transaction, in_transaction
    from .models import db as _db, load_player, rollback
    from .queue_engine import finish_player_due_work
    from .queue_poll import (
        player_has_due_queue_work,
        player_has_pending_queue_work,
        record_poll_queue_finish,
        seconds_until_poll_finish_allowed,
    )

    uid = int(player_id)
    own_conn = conn is None
    if own_conn:
        conn = _db()

    try:
        from .planet_evolution.repository import get_context_planet

        planet = get_context_planet(uid, conn=conn)
        planet_id = int(planet["id"])

        player = load_player(uid, conn=conn)
        if not player:
            raise RuntimeError(f"player {uid} not found")

        now = time.time()
        last_raw = planet.get("last_update")
        last = float(last_raw) if last_raw is not None else now
        persist_resources = (now - last) >= 120.0

        has_due = player_has_due_queue_work(uid, conn=conn)
        has_pending = player_has_pending_queue_work(uid, conn=conn)
        should_finish = has_due or (
            has_pending and seconds_until_poll_finish_allowed(uid, conn=conn) <= 0.0
        )
        need_write = bool(should_finish or persist_resources)

        try:
            if need_write:
                if should_finish:
                    finish_player_due_work(
                        uid,
                        conn,
                        source="game_state",
                        update_scores=True,
                        recalc_ranks=False,
                    )
                    record_poll_queue_finish(uid, conn=conn)
                    from .live_state import mark_request_live_refreshed

                    mark_request_live_refreshed()

                if not in_transaction(conn):
                    begin_write_transaction(conn)

                planet, buildings, ratio, energy_total, energy_used = _res.update_planet_resources(
                    planet,
                    conn=conn,
                    skip_queue_finish=True,
                )
                storage_caps = get_storage_capacity(buildings, user_id=uid, conn=conn)

                if in_transaction(conn):
                    from .models import commit

                    commit(conn)
            else:
                player_view, buildings, ratio, energy_total, energy_used, storage_caps = (
                    _read_player_live_state_no_writes(uid, conn, player, planet)
                )
                return player_view, buildings, ratio, energy_total, energy_used, storage_caps

            player_view = dict(player)
            player_view["metal"] = planet["metal"]
            player_view["crystal"] = planet["crystal"]
            player_view["fuel_cells"] = planet.get("fuel_cells", 0)
            player_view["energy_total"] = int(energy_total)
            player_view["energy_used"] = int(energy_used)

            return player_view, buildings, ratio, int(energy_total), int(energy_used), storage_caps

        except sqlite3.OperationalError:
            logger.warning(
                "read_player_live_state_for_poll locked, read-only fallback player_id=%s",
                uid,
                exc_info=True,
            )
            if own_conn:
                try:
                    rollback(conn)
                except Exception:
                    pass
            from .planet_evolution.repository import get_context_planet

            player = load_player(uid, conn=conn) or player
            planet = get_context_planet(uid, conn=conn)
            return _read_player_live_state_no_writes(uid, conn, player, planet)

    except Exception:
        if own_conn:
            rollback(conn)
        raise
    finally:
        if own_conn and conn is not None:
            conn.close()


def refresh_player_live_state(
    player_id: int,
    conn=None,
    *,
    finish_source: str = "live_state",
) -> Tuple[Any, Dict[str, int], float, int, int, Dict[str, int]]:
    """
    Single authoritative refresh for API/polling:
    1) finish due queue work + sync derived planet state
    2) recompute resources/energy via EffectResolver (skip second finish pass)
    """
    from .db import begin_write_transaction, commit, in_transaction
    from .models import db as _db, get_homeworld, load_player
    from .queue_engine import finish_player_due_work

    uid = int(player_id)
    own_conn = conn is None
    if own_conn:
        conn = _db()

    try:
        from .planet_evolution.repository import get_context_planet

        player = load_player(uid, conn=conn)
        if not player:
            raise RuntimeError(f"player {uid} not found")

        planet = get_context_planet(uid, conn=conn)

        finish_player_due_work(
            uid,
            conn,
            source=str(finish_source or "live_state"),
        )
        from .live_state import mark_request_live_refreshed

        mark_request_live_refreshed()

        if not in_transaction(conn):
            begin_write_transaction(conn)

        planet, buildings, ratio, energy_total, energy_used = _res.update_planet_resources(
            planet,
            conn=conn,
            skip_queue_finish=True,
        )
        storage_caps = get_storage_capacity(buildings, user_id=uid, conn=conn)

        player_view = dict(player)
        player_view["metal"] = planet["metal"]
        player_view["crystal"] = planet["crystal"]
        player_view["fuel_cells"] = planet.get("fuel_cells", 0)
        player_view["energy_total"] = int(energy_total)
        player_view["energy_used"] = int(energy_used)

        if own_conn:
            commit(conn)

        from .live_state import mark_request_live_refreshed

        mark_request_live_refreshed()

        return player_view, buildings, ratio, int(energy_total), int(energy_used), storage_caps

    except Exception:
        if own_conn:
            from .models import rollback

            rollback(conn)
        raise
    finally:
        if own_conn and conn is not None:
            conn.close()


def update_planet_resources(planet: dict, conn=None):
    """
    Thin-Wrapper um game.resources.update_planet_resources.

    Rückgabe:
        (planet, buildings, ratio, energy_total, energy_used)

    ✅ conn-safe wenn resources.update_planet_resources(conn=...) unterstützt.
    """
    return _res.update_planet_resources(planet, conn=conn)


def update_resources(player: dict, conn=None):
    """
    Wrapper um resources.update_resources.

    Erwartet:
        player: dict mit mindestens player['id'] (players.id / user_id)

    Rückgabe:
        (player_view, buildings, ratio, energy_total, energy_used)

    ✅ conn-safe (wenn resources.py conn durchreicht).
    """
    return _update_resources(player, conn=conn)


def get_building_production_per_hour(
    buildings: Dict[str, int],
    ratio: float,
    user_id: Optional[int] = None,
    research: Optional[Dict[str, int]] = None,
    conn=None,
) -> Dict[str, int]:
    """
    Liefert die Produktion pro Stunde je Ressource.

    ✅ user_id strikt int
    ✅ research optional (sonst DB)
    ✅ mods aus research.get_research_modifiers (single source of truth)
    """
    user_id_int: Optional[int] = int(user_id) if user_id is not None else None

    if research is None:
        if user_id_int is not None:
            research = get_research_levels(user_id_int, conn=conn)
        else:
            research = {}

    mods = _get_research_modifiers(user_id_int, conn=conn) if user_id_int is not None else None

    return _core_get_bpph(
        buildings=buildings,
        ratio=ratio,
        research=research,
        mods=mods,
    )


def get_storage_capacity(
    buildings: Dict[str, int],
    user_id: Optional[int] = None,
    research: Optional[Dict[str, int]] = None,
    conn=None,
) -> Dict[str, int]:
    """
    Berechnet Lagerkapazitäten (Metall/Kristall).

    ✅ user_id strikt int
    ✅ research optional (sonst DB)
    ✅ mods aus research.get_research_modifiers
    """
    user_id_int: Optional[int] = int(user_id) if user_id is not None else None

    if research is None:
        if user_id_int is not None:
            research = get_research_levels(user_id_int, conn=conn)
        else:
            research = {}

    mods = _get_research_modifiers(user_id_int, conn=conn) if user_id_int is not None else None

    return _core_get_storage_capacity(
        buildings=buildings,
        research=research,
        mods=mods,
    )


def apply_resource_delta_unbounded(
    planet: dict,
    delta_metal: int = 0,
    delta_crystal: int = 0,
) -> None:
    """
    Admin-/Event-Helfer: Ressourcen ohne Cap anpassen.
    """
    return _apply_resource_delta_unbounded(
        planet,
        delta_metal=delta_metal,
        delta_crystal=delta_crystal,
    )


# ============================================================================ #
# BUILD QUEUE
# ============================================================================ #

def get_build_queue_status(
    user_id: int,
    *,
    skip_finish: bool = False,
    conn=None,
) -> Dict[str, Any]:
    """
    Liefert die Build-Queue für den aktiven Spielplaneten.

    skip_finish=True: Caller hat bereits refresh_player_live_state / finish_due_work ausgeführt.
    """
    user_id_int = int(user_id)

    from .planet_evolution.repository import get_context_planet

    planet = get_context_planet(user_id_int, conn=conn)
    planet_id = int(planet["id"])

    from .live_state import coerce_skip_finish

    skip_finish = coerce_skip_finish(skip_finish)
    if not skip_finish:
        from .queue_engine import finish_active_planet_due_work

        finish_active_planet_due_work(
            user_id_int,
            planet_id,
            conn,
            source="game_state",
        )
    return get_build_queue_status_for_planet(planet_id, conn=conn, skip_finish=True)


def queue_build(
    player: dict,
    buildings: Dict[str, int],
    building_type: str,
) -> Tuple[bool, str, Any]:
    """
    Komfortfunktion für app.py (Upgrade-Route).

    Rückgabe:
        (ok, reason, payload)

    reason mapping:
        - not_enough_resources -> payload = (need_m, need_c)
        - queue_full
        - requirements
        - unknown_building
    """
    user_id = int(player.get("id"))
    from .planet_evolution.repository import get_context_planet

    planet = get_context_planet(user_id)

    ok, reason, payload = _queue_build_for_planet(
        planet=planet,
        buildings=buildings,
        building_type=building_type,
        user_id=user_id,
    )

    if not ok:
        if reason == "resources":
            need_m = int(payload.get("cost_metal", 0))
            need_c = int(payload.get("cost_crystal", 0))
            return False, "not_enough_resources", (need_m, need_c)
        if reason == "queue_full":
            return False, "queue_full", payload
        if reason == "requirements":
            return False, "requirements", payload
        if reason == "invalid":
            return False, "unknown_building", payload
        return False, reason, payload

    return True, "ok", payload


def cancel_build(player: dict, job_id: int) -> Tuple[bool, str, Any]:
    user_id = int(player.get("id"))
    from .planet_evolution.repository import get_context_planet

    planet = get_context_planet(user_id)

    ok, reason, payload = _cancel_build_job_for_planet(
        planet_id=int(planet["id"]),
        job_id=int(job_id),
        user_id=user_id,
    )
    return ok, reason, payload


# ============================================================================ #
# RESEARCH
# ============================================================================ #

def queue_research(player: dict, tech_key: str):
    """
    Thin-Wrapper um game.research.queue_research.

    Erwartete Signatur in research.py:
        queue_research(player, tech_key, user_id=None)
    """
    return _queue_research(player, tech_key)


def cancel_research(player: dict, job_id: int):
    user_id = int(player.get("id"))
    return _cancel_research_job(user_id=user_id, job_id=int(job_id))


def get_research_status(
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
    *,
    skip_finish: bool = False,
    conn=None,
) -> dict:
    """
    Wrapper um game.research.get_research_status.

    skip_finish=True: Caller hat bereits refresh_player_live_state ausgeführt.
    """
    from .live_state import coerce_skip_finish

    return _get_research_status(
        user_id=int(user_id),
        buildings=buildings,
        skip_finish=coerce_skip_finish(bool(skip_finish)),
        conn=conn,
    )


def get_research_modifiers(user_id: int, conn=None) -> Dict[str, float]:
    """
    Einziger offizieller Mods-Endpunkt (delegiert an EffectResolver).
    """
    return _get_research_modifiers(int(user_id), conn=conn)


def get_effect_debug_snapshot(user_id: int, conn=None) -> Dict[str, Any]:
    """Admin/debug: vollständige Effekt-Aufschlüsselung für einen Spieler."""
    resolver = get_effect_resolver(int(user_id), conn=conn, force_refresh=True)
    return resolver.debug_snapshot()


def complete_finished_research(user_id: int, conn=None) -> bool:
    """
    Exponiert research.complete_finished_research (optional fürs Polling/Finisher).
    """
    return _complete_finished_research(int(user_id), conn=conn)


# ============================================================================ #
# TECHTREE
# ============================================================================ #

def get_techtree_data(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
):
    """
    Wrapper um game.techtree.get_techtree_data.
    """
    return _tt_get_techtree_data(
        buildings=buildings,
        research=research,
        user_id=user_id,
    )


def get_building_tree_status(
    user_id: Optional[int] = None,
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
):
    """
    Wrapper um game.techtree.get_building_tree_status.
    """
    if user_id is not None and (buildings is None or research is None):
        return _tt_get_building_tree_status(user_id=int(user_id))

    return _tt_get_building_tree_status(
        buildings=buildings,
        research=research,
        user_id=int(user_id) if user_id is not None else None,
    )
