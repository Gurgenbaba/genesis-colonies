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
    get_techtree_page_context as _tt_get_techtree_page_context,
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
    planet_accrued = _res.project_planet_resource_balances(planet, conn=conn)
    buildings = get_planet_buildings(planet_id, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    resolver = get_effect_resolver(
        uid,
        buildings=buildings,
        research=research,
        conn=conn,
        force_refresh=True,
        planet=planet_accrued,
    )
    energy_total, energy_used = resolver.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    storage_caps = get_storage_capacity(buildings, user_id=uid, conn=conn)

    player_view = dict(player)
    player_view["metal"] = planet_accrued["metal"]
    player_view["crystal"] = planet_accrued["crystal"]
    player_view["fuel_cells"] = planet_accrued.get("fuel_cells", 0)
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
        player_fleet_is_dirty,
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

        fleet_dirty = player_fleet_is_dirty(uid, conn=conn, now=now)
        has_due = player_has_due_queue_work(uid, conn=conn, now=now) or fleet_dirty
        has_pending = player_has_pending_queue_work(uid, conn=conn)
        should_finish = has_due or (
            has_pending and seconds_until_poll_finish_allowed(uid, conn=conn) <= 0.0
        )
        need_write = bool(should_finish or persist_resources or fleet_dirty)

        try:
            if need_write:
                if should_finish:
                    finish_t0 = time.perf_counter()
                    finish_result = finish_player_due_work(
                        uid,
                        conn,
                        source="game_state",
                        update_scores=True,
                        recalc_ranks=False,
                    )
                    finish_ms = (time.perf_counter() - finish_t0) * 1000.0
                    try:
                        from .live_state import record_request_perf_phase, set_request_perf_meta

                        record_request_perf_phase("finish_ms", finish_ms)
                        derived = int(finish_result.get("derived_sync_count") or 0)
                        if derived > 0:
                            set_request_perf_meta("derived_sync_count", derived)
                    except Exception:
                        pass
                    record_poll_queue_finish(uid, conn=conn)
                    try:
                        from .alliance import finish_due_alliance_projects, get_player_alliance

                        membership = get_player_alliance(uid, conn=conn)
                        if membership:
                            finish_due_alliance_projects(
                                conn=conn, alliance_id=int(membership["alliance_id"])
                            )
                    except Exception:
                        pass
                    from .live_state import mark_request_live_refreshed

                    mark_request_live_refreshed()

                if not in_transaction(conn):
                    begin_write_transaction(conn)

                sync_t0 = time.perf_counter()
                planet, buildings, ratio, energy_total, energy_used = _res.update_planet_resources(
                    planet,
                    conn=conn,
                    skip_queue_finish=True,
                )
                try:
                    from .live_state import record_request_perf_phase

                    record_request_perf_phase(
                        "resource_sync_ms", (time.perf_counter() - sync_t0) * 1000.0
                    )
                except Exception:
                    pass
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
    recalc_ranks: bool = False,
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

        from .live_state import current_action_perf, current_ssr_perf

        perf = current_action_perf()
        ssr = current_ssr_perf()
        live_t0 = time.perf_counter()
        finish_t0 = time.perf_counter()
        finish_result = finish_player_due_work(
            uid,
            conn,
            source=str(finish_source or "live_state"),
            update_scores=True,
            recalc_ranks=bool(recalc_ranks),
        )
        try:
            from .live_state import set_request_perf_meta

            derived = int(finish_result.get("derived_sync_count") or 0)
            if derived > 0:
                set_request_perf_meta("derived_sync_count", derived)
        except Exception:
            pass
        try:
            from .alliance import finish_due_alliance_projects, get_player_alliance

            membership = get_player_alliance(uid, conn=conn)
            if membership:
                finish_due_alliance_projects(conn=conn, alliance_id=int(membership["alliance_id"]))
        except Exception:
            pass
        finish_ms = (time.perf_counter() - finish_t0) * 1000.0
        if perf is not None:
            perf.add_finish_ms(finish_ms)
        if ssr is not None:
            ssr.add_finish_ms(finish_ms)
        try:
            from .live_state import record_request_perf_phase

            record_request_perf_phase("finish_ms", finish_ms)
        except Exception:
            pass

        from .live_state import mark_request_live_refreshed

        mark_request_live_refreshed()

        if not in_transaction(conn):
            begin_write_transaction(conn)

        sync_t0 = time.perf_counter()
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
        if perf is not None:
            perf.add_resource_sync_ms((time.perf_counter() - sync_t0) * 1000.0)
            perf.add_live_state_ms((time.perf_counter() - live_t0) * 1000.0)
        if ssr is not None:
            ssr.add_resource_sync_ms((time.perf_counter() - sync_t0) * 1000.0)
        try:
            from .live_state import record_request_perf_phase

            sync_ms = (time.perf_counter() - sync_t0) * 1000.0
            record_request_perf_phase("resource_sync_ms", sync_ms)
            record_request_perf_phase("live_state_ms", (time.perf_counter() - live_t0) * 1000.0)
        except Exception:
            pass

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
        user_id=user_id_int,
        conn=conn,
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
    *,
    queue_mode: str = "single",
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
        queue_mode=queue_mode,
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
            if isinstance(payload, dict) and payload.get("max_level") is not None:
                return False, "max_level_reached", payload
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

def queue_research(player: dict, tech_key: str, *, queue_mode: str = "single"):
    """
    Thin-Wrapper um game.research.queue_research.

    Erwartete Signatur in research.py:
        queue_research(player, tech_key, user_id=None)
    """
    return _queue_research(player, tech_key, queue_mode=queue_mode)


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


def get_techtree_page_context(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
):
    """Wrapper um game.techtree.get_techtree_page_context."""
    return _tt_get_techtree_page_context(
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


# ============================================================================ #
# PLANET LIMIT (game-state / header HUD)
# ============================================================================ #

MAX_PLANETS_PER_PLAYER_MIN = 1
MAX_PLANETS_PER_PLAYER_MAX = 50
DEFAULT_MAX_COLONIES_PER_PLAYER = 9


def get_max_planets_per_player(*, conn=None) -> int:
    """
    Hard admin cap for owned planets (homeworld + colonies).
    """
    from .models import get_game_settings

    settings = get_game_settings(conn=conn) if conn is not None else get_game_settings()
    settings = settings or {}
    raw_max = settings.get("max_colonies_per_player")
    try:
        max_val = int(raw_max) if raw_max is not None else DEFAULT_MAX_COLONIES_PER_PLAYER
    except (TypeError, ValueError):
        max_val = DEFAULT_MAX_COLONIES_PER_PLAYER
    return max(MAX_PLANETS_PER_PLAYER_MIN, min(MAX_PLANETS_PER_PLAYER_MAX, int(max_val)))


def check_planet_cap_available(
    player_id: int,
    *,
    conn,
    world_key: str | None = None,
    world_type: str | None = None,
    site_key: str | None = None,
) -> tuple[bool, str]:
    """Return whether the player may found another colony (evolution slots + admin hard cap)."""
    _ = (world_key, world_type, site_key)  # legacy world-map args ignored for galaxy gameplay
    from .planet_evolution.expansion_protocol import can_found_colony

    return can_found_colony(int(player_id), conn=conn)


def get_planet_limit_block(
    player_id: int,
    *,
    conn=None,
) -> Dict[str, Any]:
    """
    Expansion gate summary for /api/game-state and empire page (no slot counter).
    """
    from .models import db as _db
    from .planet_evolution.expansion_protocol import get_expansion_limit_block

    uid = int(player_id)
    own_conn = conn is None
    if own_conn:
        conn = _db()

    try:
        return get_expansion_limit_block(uid, conn=conn)
    finally:
        if own_conn and conn is not None:
            conn.close()


# ============================================================================ #
# LIVE STATE TIMERS (GC-540)
# ============================================================================ #


def live_server_timestamp() -> int:
    """Canonical unix seconds for client timer sync."""
    return int(time.time())


def attach_canonical_server_time(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure game-state and action payloads expose server_now + server_time + state_version."""
    ts = time.time()
    payload["server_now"] = int(ts)
    payload["server_time"] = float(ts)
    payload["state_version"] = float(ts)
    return payload


def game_state_panel_finish_source() -> str:
    """Finish source for timer-driven full panel refresh (overview activities, queues)."""
    return "game_state_panel"


def normalize_queue_job_timer_fields(
    *,
    finish_at: float,
    remaining: int,
    is_active: bool = True,
    next_finish_at: float | None = None,
) -> dict[str, int]:
    """
    Canonical timer payload for queue jobs (build/research/shipyard client tick).
    Emits int unix seconds — compatible with central GC timer attrs.
    """
    finish_int = int(finish_at or 0)
    next_int = int(next_finish_at or 0) if next_finish_at else (finish_int if is_active else 0)
    rem = max(0, int(remaining))
    countdown = finish_int if is_active and finish_int else 0
    next_countdown = next_int if is_active and next_int else 0
    return {
        "finish_at": finish_int,
        "finish_time": finish_int,
        "countdown_at": countdown,
        "next_countdown_at": next_countdown,
        "next_finish_at": next_int,
        "remaining": rem,
        "remaining_seconds": rem,
    }
