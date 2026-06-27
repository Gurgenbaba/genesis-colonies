"""
Request-scoped guard for the single-pass live refresh pipeline.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_action_perf_trace: ContextVar[Optional["ActionPerfTrace"]] = ContextVar(
    "gc_action_perf_trace", default=None
)


def is_action_perf_debug_enabled() -> bool:
    from game.config import is_action_perf_debug_enabled as _enabled

    return _enabled()


class ActionPerfTrace:
    """GC-841: request-scoped timings for mutation action routes."""

    __slots__ = (
        "route",
        "started_at",
        "finish_ms",
        "mutate_ms",
        "live_state_ms",
        "resource_sync_ms",
        "payload_ms",
    )

    def __init__(self, route: str) -> None:
        self.route = str(route or "action")
        self.started_at = time.perf_counter()
        self.finish_ms = 0.0
        self.mutate_ms = 0.0
        self.live_state_ms = 0.0
        self.resource_sync_ms = 0.0
        self.payload_ms = 0.0

    def add_finish_ms(self, ms: float) -> None:
        self.finish_ms += max(0.0, float(ms))

    def add_mutate_ms(self, ms: float) -> None:
        self.mutate_ms += max(0.0, float(ms))

    def add_live_state_ms(self, ms: float) -> None:
        self.live_state_ms += max(0.0, float(ms))

    def add_resource_sync_ms(self, ms: float) -> None:
        self.resource_sync_ms += max(0.0, float(ms))

    def add_payload_ms(self, ms: float) -> None:
        self.payload_ms += max(0.0, float(ms))

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000.0

    def as_dict(self, *, response_bytes: int = 0) -> Dict[str, Any]:
        return {
            "route": self.route,
            "total_ms": round(self.total_ms, 1),
            "finish_ms": round(self.finish_ms, 1),
            "mutate_ms": round(self.mutate_ms, 1),
            "live_state_ms": round(self.live_state_ms, 1),
            "resource_sync_ms": round(self.resource_sync_ms, 1),
            "payload_ms": round(self.payload_ms, 1),
            "bytes": int(response_bytes or 0),
        }

    def emit_log(self, *, response_bytes: int = 0) -> Dict[str, Any]:
        data = self.as_dict(response_bytes=response_bytes)
        logger.info(
            "[GC ACTION PERF] route=%s total=%sms finish=%sms mutate=%sms "
            "live_state=%sms resource_sync=%sms payload=%sms bytes=%s",
            data["route"],
            data["total_ms"],
            data["finish_ms"],
            data["mutate_ms"],
            data["live_state_ms"],
            data["resource_sync_ms"],
            data["payload_ms"],
            data["bytes"],
        )
        return data


def start_action_perf(route: str) -> Optional[ActionPerfTrace]:
    if not is_action_perf_debug_enabled():
        return None
    trace = ActionPerfTrace(route)
    _action_perf_trace.set(trace)
    return trace


def current_action_perf() -> Optional[ActionPerfTrace]:
    return _action_perf_trace.get()


def finish_action_perf(*, response_bytes: int = 0) -> Optional[Dict[str, Any]]:
    trace = _action_perf_trace.get()
    if trace is None:
        return None
    _action_perf_trace.set(None)
    return trace.emit_log(response_bytes=response_bytes)


_ssr_perf_trace: ContextVar[Optional["SsrPerfTrace"]] = ContextVar(
    "gc_ssr_perf_trace", default=None
)


def is_ssr_perf_debug_enabled() -> bool:
    from game.config import is_ssr_perf_debug_enabled as _enabled

    return _enabled()


class SsrPerfTrace:
    """GC-853: request-scoped timings for SSR page routes (e.g. /buildings)."""

    __slots__ = (
        "route",
        "tab",
        "started_at",
        "live_context_ms",
        "finish_ms",
        "resource_sync_ms",
        "buildings_panel_ms",
        "cards_ms",
        "tech_data_ms",
        "fleet_panel_ms",
        "logistics_panel_ms",
        "template_ms",
    )

    def __init__(self, route: str, *, tab: str = "") -> None:
        self.route = str(route or "page")
        self.tab = str(tab or "")
        self.started_at = time.perf_counter()
        self.live_context_ms = 0.0
        self.finish_ms = 0.0
        self.resource_sync_ms = 0.0
        self.buildings_panel_ms = 0.0
        self.cards_ms = 0.0
        self.tech_data_ms = 0.0
        self.fleet_panel_ms = 0.0
        self.logistics_panel_ms = 0.0
        self.template_ms = 0.0

    def add_live_context_ms(self, ms: float) -> None:
        self.live_context_ms += max(0.0, float(ms))

    def add_finish_ms(self, ms: float) -> None:
        self.finish_ms += max(0.0, float(ms))

    def add_resource_sync_ms(self, ms: float) -> None:
        self.resource_sync_ms += max(0.0, float(ms))

    def add_buildings_panel_ms(self, ms: float) -> None:
        self.buildings_panel_ms += max(0.0, float(ms))

    def add_cards_ms(self, ms: float) -> None:
        self.cards_ms += max(0.0, float(ms))

    def add_tech_data_ms(self, ms: float) -> None:
        self.tech_data_ms += max(0.0, float(ms))

    def add_fleet_panel_ms(self, ms: float) -> None:
        self.fleet_panel_ms += max(0.0, float(ms))

    def add_logistics_panel_ms(self, ms: float) -> None:
        self.logistics_panel_ms += max(0.0, float(ms))

    def add_template_ms(self, ms: float) -> None:
        self.template_ms += max(0.0, float(ms))

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000.0

    def as_dict(self, *, response_bytes: int = 0) -> Dict[str, Any]:
        return {
            "route": self.route,
            "tab": self.tab,
            "total_ms": round(self.total_ms, 1),
            "live_context_ms": round(self.live_context_ms, 1),
            "finish_ms": round(self.finish_ms, 1),
            "resource_sync_ms": round(self.resource_sync_ms, 1),
            "buildings_panel_ms": round(self.buildings_panel_ms, 1),
            "cards_ms": round(self.cards_ms, 1),
            "tech_data_ms": round(self.tech_data_ms, 1),
            "fleet_panel_ms": round(self.fleet_panel_ms, 1),
            "logistics_panel_ms": round(self.logistics_panel_ms, 1),
            "template_ms": round(self.template_ms, 1),
            "bytes": int(response_bytes or 0),
        }

    def emit_log(self, *, response_bytes: int = 0) -> Dict[str, Any]:
        data = self.as_dict(response_bytes=response_bytes)
        logger.info(
            "[GC SSR PERF] route=%s tab=%s total=%sms live_context=%sms finish=%sms "
            "resource_sync=%sms buildings_panel=%sms cards=%sms tech_data=%sms "
            "fleet_panel=%sms logistics_panel=%sms template=%sms bytes=%s",
            data["route"],
            data["tab"],
            data["total_ms"],
            data["live_context_ms"],
            data["finish_ms"],
            data["resource_sync_ms"],
            data["buildings_panel_ms"],
            data["cards_ms"],
            data["tech_data_ms"],
            data["fleet_panel_ms"],
            data["logistics_panel_ms"],
            data["template_ms"],
            data["bytes"],
        )
        return data


def start_ssr_perf(route: str, *, tab: str = "") -> Optional[SsrPerfTrace]:
    if not is_ssr_perf_debug_enabled():
        return None
    trace = SsrPerfTrace(route, tab=tab)
    _ssr_perf_trace.set(trace)
    return trace


def current_ssr_perf() -> Optional[SsrPerfTrace]:
    return _ssr_perf_trace.get()


def finish_ssr_perf(*, response_bytes: int = 0) -> Optional[Dict[str, Any]]:
    trace = _ssr_perf_trace.get()
    if trace is None:
        return None
    _ssr_perf_trace.set(None)
    return trace.emit_log(response_bytes=response_bytes)


def get_request_context_planet(user_id: int, *, conn) -> Dict[str, Any]:
    """Request-scoped memo for get_context_planet (GC-741)."""
    uid = int(user_id)
    try:
        from flask import g, has_request_context

        if has_request_context():
            cache = getattr(g, "gc_context_planet_by_user", None)
            if cache is None:
                cache = {}
                g.gc_context_planet_by_user = cache
            if uid in cache:
                return cache[uid]
    except ImportError:
        pass

    from game.planet_evolution.repository import get_context_planet

    planet = get_context_planet(uid, conn=conn)
    try:
        from flask import g, has_request_context

        if has_request_context():
            g.gc_context_planet_by_user[uid] = planet
    except ImportError:
        pass
    return planet


def mark_request_live_refreshed() -> None:
    """Mark that finish + derived sync already ran this HTTP request."""
    try:
        from flask import g, has_request_context

        if has_request_context():
            g.gc_live_state_refreshed = True
    except ImportError:
        pass


def request_live_state_already_refreshed() -> bool:
    try:
        from flask import g, has_request_context

        return bool(has_request_context() and getattr(g, "gc_live_state_refreshed", False))
    except ImportError:
        return False


def coerce_skip_finish(skip_finish: bool) -> bool:
    """
    Effective skip_finish for queue read paths (GC-833).

    After refresh_player_live_state / poll finish in the same HTTP request, skip a
    second finish pass. Before that, never skip — even when callers pass
    skip_finish=True — so due jobs cannot appear as 100 % / 0 s / active.
    """
    _ = skip_finish
    return request_live_state_already_refreshed()


def defense_finish_source(action: str) -> str:
    """Stable finish_source token for defense mutations."""
    key = str(action or "action").strip().lower() or "action"
    return f"api_defense_{key}"


def defense_panel_for_game_state(user_id: int, *, conn) -> Optional[Dict[str, Any]]:
    """Defense queue + stock slice for /api/game-state include_panel."""
    from game.defense import build_defense_api_payload, defense_queue_table_ready
    from game.models import defense_schema_ready
    from game.planet_evolution.repository import get_context_planet

    if not defense_schema_ready(conn) or not defense_queue_table_ready(conn):
        return None

    planet = get_context_planet(user_id, conn=conn)
    if not planet:
        return None

    pid = int(planet["id"])
    payload = build_defense_api_payload(int(user_id), pid, conn=conn)
    queue = payload.pop("defense_queue", {"queue": [], "summary": {}})
    return {
        "queue": queue,
        "defenses": {"ready": True, **payload},
    }


def _inactive_nav_badge() -> Dict[str, Any]:
    return {"active": False, "count": 0, "label": ""}


def _nav_badge_entry(*, active: bool, count: int = 0, label: str = "") -> Dict[str, Any]:
    if not active:
        return _inactive_nav_badge()
    return {
        "active": True,
        "count": max(0, int(count)),
        "label": str(label),
    }


def nav_badges_for_game_state(user_id: int, *, conn) -> Dict[str, Any]:
    """Action hints for left-menu navigation (GC-702)."""
    from game.galactic_directives.state import count_pending_government_votes
    from game.referrals import count_claimable_referral_rewards
    from game.vote_rewards import count_voteable_providers

    uid = int(user_id)
    vote_count = count_voteable_providers(uid, conn=conn)
    gov_count = count_pending_government_votes(uid, conn=conn)
    referral_count = count_claimable_referral_rewards(uid, conn=conn, read_only=True)
    from game.directives.service import count_claimable_directives

    directive_count = count_claimable_directives(uid, conn=conn)
    return {
        "vote_center": _nav_badge_entry(
            active=vote_count > 0,
            count=vote_count,
            label=str(vote_count) if vote_count > 0 else "",
        ),
        "government": _nav_badge_entry(
            active=gov_count > 0,
            count=gov_count,
            label="!" if gov_count > 0 else "",
        ),
        "referrals": _nav_badge_entry(
            active=referral_count > 0,
            count=referral_count,
            label="!" if referral_count > 0 else "",
        ),
        "imperial_directives": _nav_badge_entry(
            active=directive_count > 0,
            count=directive_count,
            label=str(directive_count) if directive_count > 0 else "",
        ),
    }


def imperial_directives_for_game_state(user_id: int, *, conn) -> Dict[str, Any]:
    """Compact Imperial Directives summary for /api/game-state (GC-914A)."""
    from game.directives.service import get_imperial_directives_summary

    return get_imperial_directives_summary(int(user_id), conn=conn)


def fleet_hud_for_game_state(user_id: int, *, conn) -> Optional[Dict[str, Any]]:
    """Player-wide active fleet slice for /api/game-state (GC-640A)."""
    from game.fleet import (
        build_active_fleets_payload,
        build_fleet_incoming_attack_alerts,
        fleet_schema_ready,
        get_fleet_slot_status,
        process_fleet_tick,
    )
    from game.queue_poll import player_fleet_is_dirty

    if not fleet_schema_ready(conn):
        return None

    uid = int(user_id)
    if player_fleet_is_dirty(uid, conn=conn):
        process_fleet_tick(player_id=uid, conn=conn)

    return {
        "active_fleets": build_active_fleets_payload(uid, conn=conn),
        "fleet_slots": get_fleet_slot_status(uid, conn=conn),
        "fleet_alerts": build_fleet_incoming_attack_alerts(uid, conn=conn),
    }


def shipyard_panel_for_game_state(user_id: int, *, conn) -> Optional[Dict[str, Any]]:
    """Shipyard queue + stock slice for /api/game-state include_panel (GC-630)."""
    from game.fleet import fleet_schema_ready
    from game.planet_evolution.repository import get_context_planet
    from game.shipyard import build_shipyard_api_payload
    from game.shipyard_queue import shipyard_queue_table_ready

    if not fleet_schema_ready(conn) or not shipyard_queue_table_ready(conn):
        return None

    planet = get_context_planet(user_id, conn=conn)
    if not planet:
        return None

    pid = int(planet["id"])
    payload = build_shipyard_api_payload(int(user_id), pid, conn=conn)
    queue = payload.pop("shipyard_queue", {"queue": [], "summary": {}})
    return {
        "queue": queue,
        "ships": {"ready": True, **payload},
    }


def _head_card_jobs(card_jobs, *, max_queued: int = 0):
    """Active job first; optional queued slots (position 2..N) for one domain."""
    if not card_jobs:
        return []
    active = next((dict(j) for j in card_jobs if str(j.get("status") or "") == "active"), None)
    out: list = []
    if active:
        out.append(active)
    if max_queued > 0:
        for j in card_jobs:
            pos = int(j.get("queue_position") or 0)
            if pos >= 2 and pos <= max_queued + 1:
                out.append(dict(j))
    if not out and card_jobs:
        out.append(dict(card_jobs[0]))
    return out


def global_queue_hud_for_game_state(
    user_id: int,
    *,
    buildings: Optional[Dict[str, int]] = None,
    conn,
    planet: Optional[Dict[str, Any]] = None,
    build_queue: Optional[Dict[str, Any]] = None,
    research: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    GC-643 — unified queue HUD slice for /api/game-state panel polls.
    Head jobs only (building: active + queue #2; others: active).
    """
    import time

    from game.buildings import get_build_queue_status_for_planet
    from game.queue_card import (
        map_build_queue_to_card_jobs,
        map_defense_queue_to_card_jobs,
        map_research_queue_to_card_jobs,
        map_shipyard_queue_to_card_jobs,
    )
    from game.research import get_research_status

    if planet is None:
        planet = get_request_context_planet(int(user_id), conn=conn)
    if not planet:
        return {"jobs": [], "planet_id": 0, "planet_name": ""}

    pid = int(planet["id"])
    now = time.time()
    hud_jobs: list = []

    bq = build_queue if isinstance(build_queue, dict) else None
    if bq is None:
        bq = get_build_queue_status_for_planet(pid, conn=conn, skip_finish=True)
    hud_jobs.extend(
        _head_card_jobs(map_build_queue_to_card_jobs(bq, now=now), max_queued=1)
    )

    bld = buildings if isinstance(buildings, dict) else None
    if bld is None:
        from game.models import get_planet_buildings

        bld = get_planet_buildings(pid, conn=conn)

    research_status = research if isinstance(research, dict) else None
    if research_status is None:
        research_status = get_research_status(
            user_id=int(user_id),
            buildings=bld,
            skip_finish=True,
            conn=conn,
        )
    hud_jobs.extend(_head_card_jobs(map_research_queue_to_card_jobs(research_status, now=now)))

    try:
        from game.fleet import fleet_schema_ready
        from game.shipyard_queue import shipyard_queue_for_client, shipyard_queue_table_ready

        if fleet_schema_ready(conn) and shipyard_queue_table_ready(conn):
            sy_level = int((bld or {}).get("orbital_shipyard") or 0)
            sy_q = shipyard_queue_for_client(int(user_id), pid, sy_level, conn=conn)
            hud_jobs.extend(_head_card_jobs(map_shipyard_queue_to_card_jobs(sy_q, now=now)))
    except Exception:
        pass

    try:
        from game.defense import defense_queue_for_client, defense_queue_table_ready
        from game.models import defense_schema_ready

        if defense_schema_ready(conn) and defense_queue_table_ready(conn):
            def_q = defense_queue_for_client(int(user_id), pid, conn=conn)
            hud_jobs.extend(_head_card_jobs(map_defense_queue_to_card_jobs(def_q, now=now)))
    except Exception:
        pass

    return {
        "jobs": hud_jobs,
        "planet_id": pid,
        "planet_name": str(planet.get("name") or ""),
    }


def research_poll_slice(research: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """GC-747: queue timers + summary only — no full tech catalog on poll."""
    if not isinstance(research, dict):
        return {"active": None, "queue": [], "summary": {"count": 0, "limit": 3}}
    out: Dict[str, Any] = {
        "active": research.get("active"),
        "queue": list(research.get("queue") or []),
        "summary": dict(research.get("summary") or {}),
    }
    card_jobs = research.get("card_jobs")
    if card_jobs is not None:
        out["card_jobs"] = card_jobs
    card_jobs_by_owner = research.get("card_jobs_by_owner")
    if card_jobs_by_owner is not None:
        out["card_jobs_by_owner"] = card_jobs_by_owner
    mini_queue_jobs = research.get("mini_queue_jobs")
    if mini_queue_jobs is not None:
        out["mini_queue_jobs"] = mini_queue_jobs
    return out


def account_safety_hud_for_game_state(user_id: int, *, conn) -> Dict[str, Any]:
    """Lightweight vacation/deletion slice for shell HUD (player-scoped, self-heal)."""
    from game.options import get_account_safety_hud_state

    return get_account_safety_hud_state(int(user_id), conn=conn, self_heal=True)


def apply_lightweight_game_state_diet(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    GC-747 / GC-802: normal poll diet — keep shell HUD slices, drop page-catalog blocks.

    Keeps: planet_limit, planets (switcher), active_planet (+ sidebar_nav for role nav),
    active_fleets, fleet_slots, fleet_alerts, account_safety (vacation HUD).
    Drops: player_stats, building_queue, research_queue, planet_teaser, research.techs.
    """
    for key in (
        "player_stats",
        "building_queue",
        "research_queue",
        "planet_teaser",
    ):
        payload.pop(key, None)
    if "research" in payload:
        payload["research"] = research_poll_slice(payload.get("research"))
    return payload


def apply_action_state_diet(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    GC-840: mutation action state — keep HUD + queue slices, drop page-catalog blocks.

    Full buildings_panel stays on page init / include_panel=1 / timer-finish refresh.
    """
    for key in (
        "player_stats",
        "planet_teaser",
        "exchange",
        "scrapyard",
        "auction_house",
        "defense",
        "shipyard",
        "shipyard_queue",
        "global_queue_hud",
        "building_queue",
        "research_queue",
    ):
        payload.pop(key, None)
    overview = payload.get("overview")
    if isinstance(overview, dict):
        overview.pop("status", None)
        overview.pop("rows", None)
    return payload
