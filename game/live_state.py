"""
Request-scoped guard for the single-pass live refresh pipeline.
"""

from __future__ import annotations

import logging
import random
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REQUEST_PERF_PHASE_KEYS = frozenset(
    {
        "before_request_ms",
        "handler_ms",
        "after_request_ms",
        "fleet_tick_ms",
        "account_deletion_worker_ms",
        "live_context_ms",
        "page_context_ms",
        "live_state_ms",
        "finish_ms",
        "mutate_ms",
        "resource_sync_ms",
        "payload_ms",
        "buildings_panel_ms",
        "cards_ms",
        "tech_data_ms",
        "fleet_panel_ms",
        "logistics_panel_ms",
        "template_ms",
        "template_render_ms",
        "db_connection_ms",
        "db_begin_immediate_ms",
        "db_write_transaction_ms",
        "db_transaction_ms",
    }
)

_REQUEST_PERF_META_KEYS = frozenset(
    {
        "finish_source",
        "route",
        "pjax",
        "include_panel",
        "panel_delta",
        "fleet_tick_ran",
        "fleet_tick_source",
        "derived_sync_count",
        "account_deletions_ran",
        "method",
        "endpoint",
        "path",
        "status",
        "bytes",
        "content_type",
        "sample",
        "sql_count",
        "sql_write_count",
        "had_exception",
        "diet_payload_bytes",
        "budget_miss",
        "state_version",
        "delta_since",
        "diet_early_exit",
        "diet_probe_skip",
    }
)

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
    from game.models import defense_schema_ready, get_planet_buildings
    from game.planet_evolution.repository import get_context_planet

    if not defense_schema_ready(conn) or not defense_queue_table_ready(conn):
        return None

    planet = get_context_planet(user_id, conn=conn)
    if not planet:
        return None

    pid = int(planet["id"])
    payload = build_defense_api_payload(int(user_id), pid, conn=conn)
    queue = payload.pop("defense_queue", {"queue": [], "summary": {}})
    troops_state = None
    try:
        from game.troops import build_troops_state, troop_queue_table_ready, troops_schema_ready

        if troops_schema_ready(conn) and troop_queue_table_ready(conn):
            bld = get_planet_buildings(pid, conn=conn) or {}
            troops_state = build_troops_state(
                pid,
                barracks_level=int(bld.get("barracks") or 0),
                conn=conn,
            )
    except Exception:
        troops_state = None
    defenses: Dict[str, Any] = {"ready": True, **payload}
    if troops_state is not None:
        # Nest under defenses so applyDefenseState sees troops after panel patch;
        # keep top-level for slim / explicit client reads.
        defenses["troops"] = troops_state
    out: Dict[str, Any] = {
        "queue": queue,
        "defenses": defenses,
    }
    if troops_state is not None:
        out["troops"] = troops_state
    return out


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
    from game.vote_rewards import count_vote_center_attention

    uid = int(user_id)
    vote_count = count_vote_center_attention(uid, conn=conn)
    gov_count = count_pending_government_votes(uid, conn=conn)
    referral_count = count_claimable_referral_rewards(uid, conn=conn, read_only=True)
    from game.directives.service import count_claimable_directives

    directive_count = count_claimable_directives(uid, conn=conn)
    wb_active = False
    wb_count = 0
    try:
        from game.world_boss import list_active_events

        active_events = list_active_events(conn=conn, limit=10)
        wb_count = len(active_events)
        wb_active = wb_count > 0
    except Exception:
        wb_active = False
        wb_count = 0

    login_available = False
    bp_claimable = 0
    story_attention = 0
    server_event_count = 0
    try:
        from game.server_events import list_active_events as list_server_events
        from game.server_events import schema_ready as server_events_ready

        if server_events_ready(conn):
            server_event_count = len(list_server_events(now=None, conn=conn))
    except Exception:
        server_event_count = 0
    try:
        from game.login_rewards import serialize_for_client as lr_serialize

        lr = lr_serialize(uid, conn=conn)
        login_available = bool(lr.get("ready") and lr.get("available"))
    except Exception:
        login_available = False
    try:
        from game.battle_pass import serialize_for_client as bp_serialize

        bp = bp_serialize(uid, conn=conn)
        bp_claimable = int(bp.get("claimable_count") or 0) if bp.get("ready") else 0
    except Exception:
        bp_claimable = 0
    try:
        from game.story.service import count_story_attention

        story_attention = count_story_attention(uid, conn=conn)
    except Exception:
        story_attention = 0

    initiation_attention = 0
    try:
        from game.initiation.service import count_initiation_attention

        initiation_attention = count_initiation_attention(uid, conn=conn)
    except Exception:
        initiation_attention = 0

    live_events_count = 0
    try:
        from game.overview_page import build_overview_live_events

        live_events_count = len(build_overview_live_events(user_id=uid, conn=conn))
    except Exception:
        live_events_count = server_event_count + wb_count

    alliance_count = 0
    try:
        from game.alliance import count_alliance_nav_attention

        alliance_count = int(count_alliance_nav_attention(uid, conn=conn) or 0)
    except Exception:
        alliance_count = 0

    auction_count = 0
    try:
        from game.auction_house import count_auction_nav_attention

        auction_count = int(count_auction_nav_attention(uid, conn=conn) or 0)
    except Exception:
        auction_count = 0

    inventory_count = 0
    try:
        from game.case_battles import count_case_battles_nav_attention

        inventory_count = int(count_case_battles_nav_attention(uid, conn=conn) or 0)
    except Exception:
        inventory_count = 0

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
        "story": _nav_badge_entry(
            active=story_attention > 0,
            count=story_attention,
            label=str(story_attention) if story_attention > 0 else "",
        ),
        "initiation": _nav_badge_entry(
            active=initiation_attention > 0,
            count=initiation_attention,
            label="!" if initiation_attention > 0 else "",
        ),
        "world_boss": _nav_badge_entry(
            active=wb_active,
            count=wb_count,
            label=str(wb_count) if wb_count > 1 else ("LIVE" if wb_active else ""),
        ),
        "live_events": _nav_badge_entry(
            active=live_events_count > 0,
            count=live_events_count,
            label=str(live_events_count) if live_events_count > 0 else "",
        ),
        "login_rewards": _nav_badge_entry(
            active=login_available,
            count=1 if login_available else 0,
            label="!" if login_available else "",
        ),
        "premium": _nav_badge_entry(
            active=bp_claimable > 0,
            count=bp_claimable,
            label=str(bp_claimable) if bp_claimable > 0 else "",
        ),
        "alliance": _nav_badge_entry(
            active=alliance_count > 0,
            count=alliance_count,
            label=str(alliance_count) if alliance_count > 0 else "",
        ),
        "auction_house": _nav_badge_entry(
            active=auction_count > 0,
            count=auction_count,
            label=str(auction_count) if auction_count > 0 else "",
        ),
        "inventory": _nav_badge_entry(
            active=inventory_count > 0,
            count=inventory_count,
            label=str(inventory_count) if inventory_count > 0 else "",
        ),
    }


def imperial_directives_for_game_state(user_id: int, *, conn) -> Dict[str, Any]:
    """Compact Imperial Directives summary for /api/game-state (GC-914A)."""
    from game.directives.service import get_imperial_directives_summary

    return get_imperial_directives_summary(int(user_id), conn=conn)


def initiation_for_game_state(user_id: int, *, conn) -> Dict[str, Any]:
    """Compact Command Initiation HUD slice (diet-safe)."""
    from game.initiation.service import get_initiation_summary

    return get_initiation_summary(int(user_id), conn=conn, ensure=True)


def fleet_hud_for_game_state(user_id: int, *, conn) -> Optional[Dict[str, Any]]:
    """Player-wide active fleet slice for /api/game-state (GC-640A)."""
    from game.fleet import (
        build_active_fleets_payload,
        build_fleet_incoming_attack_alerts,
        enrich_fleet_alerts_with_radar,
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

    alerts = build_fleet_incoming_attack_alerts(uid, conn=conn)
    alerts = enrich_fleet_alerts_with_radar(alerts, uid, conn=conn)
    return {
        "active_fleets": build_active_fleets_payload(uid, conn=conn),
        "fleet_slots": get_fleet_slot_status(uid, conn=conn),
        "fleet_alerts": alerts,
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


def attach_timekeeper_domain_queue_slices(
    payload: Dict[str, Any],
    user_id: int,
    domain: str,
    *,
    conn,
) -> Dict[str, Any]:
    """
    GC-PERF-TK-004: slim TK apply must still return the boosted production queue.

    ``build_queue`` / ``research`` already live on the base payload. Shipyard,
    defense, and troops panels are include_panel-only and were diet-stripped —
    without a queue slice the client cannot patch timers (looks like a no-op click).
    Catalog (ships/defenses stock) stays omitted.
    """
    if not isinstance(payload, dict):
        return payload
    dom = str(domain or "").strip().lower()
    if dom in ("building", "build", "buildings"):
        dom = "build"
    if dom == "shipyard":
        try:
            panel = shipyard_panel_for_game_state(int(user_id), conn=conn)
        except Exception:
            panel = None
        if panel and isinstance(panel.get("queue"), dict):
            payload["shipyard"] = {"queue": panel["queue"]}
            payload["shipyard_queue"] = panel["queue"]
    elif dom == "defense":
        try:
            panel = defense_panel_for_game_state(int(user_id), conn=conn)
        except Exception:
            panel = None
        if panel and isinstance(panel.get("queue"), dict):
            # Queue only — mirror shipyard slim shape for patchDefensePanelFromGameState
            slim: Dict[str, Any] = {"queue": panel["queue"]}
            if isinstance(panel.get("troops"), dict):
                slim["troops"] = panel["troops"]
            payload["defense"] = slim
    elif dom == "troops":
        try:
            panel = defense_panel_for_game_state(int(user_id), conn=conn)
        except Exception:
            panel = None
        if panel and isinstance(panel.get("troops"), dict):
            payload["defense"] = {
                "queue": panel.get("queue") if isinstance(panel.get("queue"), dict) else {"queue": []},
                "troops": panel["troops"],
            }
    return payload


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


def _fleet_alerts_for_notification_heartbeat(user_id: int, *, conn) -> Dict[str, Any]:
    """
    GC-PERF-RADAR-001: incoming fleets + Threat Net fingerprint only.

    Full ``radar_contacts`` rows stay on ``/api/game-state`` (Fleet HUD / Galaxy).
    """
    fleet_alerts: Dict[str, Any] = {
        "incoming_attack_count": 0,
        "next_attack_arrival": None,
        "has_incoming_attack": False,
        "alert_key": "",
        "incoming_attacks": [],
        "incoming_hostile_attack_count": 0,
    }
    try:
        from game.fleet import (
            build_fleet_incoming_attack_alerts,
            enrich_fleet_alerts_with_radar_fingerprint,
            fleet_schema_ready,
        )

        if fleet_schema_ready(conn):
            fleet_alerts = (
                build_fleet_incoming_attack_alerts(int(user_id), conn=conn)
                or fleet_alerts
            )
            fleet_alerts = enrich_fleet_alerts_with_radar_fingerprint(
                fleet_alerts, int(user_id), conn=conn
            )
    except Exception:
        pass
    return fleet_alerts


def notification_summary_for_client(user_id: int, *, conn) -> Dict[str, Any]:
    """
    Tiny notification heartbeat — unread + attack alerts only.

    Must not run queue finish or full live refresh (client polls ~12s).
    GC-PERF-RADAR-001: Threat Net contributes fingerprint/counts, not contact rows.
    """
    from game import messages as messages_logic
    from game.logic import attach_canonical_server_time

    uid = int(user_id)
    unread = 0
    latest_id: int | None = None
    new_items: list = []
    try:
        unread = int(messages_logic.unread_count(uid, conn=conn, prepare=False) or 0)
        raw_latest = messages_logic.latest_inbox_message_id(uid, conn=conn, prepare=False)
        latest_id = int(raw_latest) if raw_latest else None
        if unread > 0:
            new_items = messages_logic.notification_toast_items(
                uid, limit=16, conn=conn, prepare=False
            )
    except Exception:
        unread = 0
        latest_id = None
        new_items = []

    fleet_alerts = _fleet_alerts_for_notification_heartbeat(uid, conn=conn)

    alert_key = str(fleet_alerts.get("alert_key") or "")
    revision = f"{unread}:{latest_id or 0}:{alert_key}"
    payload: Dict[str, Any] = {
        "ok": True,
        "unread_messages_count": max(0, unread),
        "latest_message_id": latest_id,
        "fleet_alerts": fleet_alerts,
        "notification_revision": revision,
        "notifications": {
            "unread_count": max(0, unread),
            "newest_id": latest_id,
            "new_items": new_items,
        },
    }
    return attach_canonical_server_time(payload)


_ACTIVE_PLANET_POLL_KEYS = (
    "planet_id",
    "name",
    "is_homeworld",
    "empire_role_key",
    "empire_role_icon",
    "empire_identity_key",
    "planet_class",
    "planet_class_label_key",
    "coordinates_formatted",
    "position",
    "landscape_url",
    "landscape_webp_url",
    "herocard_url",
    "herocard_webp_url",
    "herocard_webp_srcset",
    "herocard_webp_sizes",
    "accent_color",
    "secondary_color",
    "glow_color",
    "planet_effect",
    "theme_key",
    "theme_group",
    "slot_label_key",
)

_PLANET_SWITCHER_POLL_KEYS = (
    "planet_id",
    "name",
    "is_homeworld",
    "is_active",
    "planet_class",
    "planet_class_label_key",
    "coordinates_formatted",
    "position",
    "empire_role_key",
    "empire_role_icon",
    "empire_role_label_key",
    "empire_subtitle_key",
    "identity_title_key",
    "empire_identity_key",
    "herocard_url",
    "herocard_webp_url",
    "status_indicators",
)

_FLEET_DRAWER_ITEM_POLL_KEYS = (
    "id",
    "movement_id",
    "mission",
    "mission_type",
    "mission_label_key",
    "status",
    "status_label",
    "phase",
    "leg_phase",
    "leg_label_key",
    "origin_name",
    "origin_coords",
    "target_name",
    "target_coords",
    "ship_count",
    "ships_breakdown",
    "loaded_resources",
    "total_seconds",
    "duration_seconds",
    "flight_seconds",
    "progress_pct",
    "remaining_seconds",
    "countdown_at",
    "arrival_at",
    "return_at",
    "departure_at",
    "started_at",
    "holding_until",
    "home_at",
    "can_recall",
    "can_cancel",
    "action_label_key",
    "cancel_reason",
)


def active_planet_poll_slice(active_planet: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """GC-PERF-005: shell poll — landscape/theme/switcher fields only."""
    if not isinstance(active_planet, dict):
        return {}
    return {k: active_planet[k] for k in _ACTIVE_PLANET_POLL_KEYS if k in active_planet}


def planets_poll_slice(planets: Optional[Any]) -> List[Dict[str, Any]]:
    if not isinstance(planets, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in planets:
        if not isinstance(row, dict):
            continue
        slim = {k: row[k] for k in _PLANET_SWITCHER_POLL_KEYS if k in row}
        if slim:
            out.append(slim)
    return out


def active_fleet_item_poll_slice(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    slim = {k: item[k] for k in _FLEET_DRAWER_ITEM_POLL_KEYS if k in item}
    if "movement_id" not in slim and "id" in slim:
        slim["movement_id"] = slim["id"]
    return slim


def active_fleets_poll_slice(active_fleets: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(active_fleets, dict):
        return {
            "count": 0,
            "active_fleet_count": 0,
            "fleets_confirmed_empty": True,
            "visible_limit": 1,
            "next_remaining_seconds": 0,
            "items": [],
        }
    items = [
        active_fleet_item_poll_slice(row)
        for row in (active_fleets.get("items") or [])
        if isinstance(row, dict)
    ]
    return {
        "count": int(active_fleets.get("count") or len(items) or 0),
        "active_fleet_count": int(active_fleets.get("active_fleet_count") or len(items) or 0),
        "fleets_confirmed_empty": bool(active_fleets.get("fleets_confirmed_empty", len(items) == 0)),
        "visible_limit": max(1, int(active_fleets.get("visible_limit") or 1)),
        "next_remaining_seconds": max(0, int(active_fleets.get("next_remaining_seconds") or 0)),
        "items": items,
    }


# Match Fleet HUD contact cap — diet keeps overflow count, trims heavy ship maps.
_DIET_RADAR_CONTACT_CAP = 8
_DIET_RADAR_CONTACT_KEYS = (
    "movement_id",
    "tier",
    "threat_class",
    "mission_type",
    "match_edge",
    "sensor_planet_id",
    "arrival_at",
    "eta_band",
    "origin",
    "target",
    "owner_id",
    "owner_name",
    "ships_by_role",
)


def fleet_alerts_poll_slice(fleet_alerts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """GC-PERF-RADAR-001: diet keeps Threat Net HUD fields; drops full ``ships`` maps."""
    if not isinstance(fleet_alerts, dict):
        return {
            "incoming_attack_count": 0,
            "next_attack_arrival": None,
            "has_incoming_attack": False,
            "alert_key": "",
            "incoming_attacks": [],
            "incoming_hostile_attack_count": 0,
            "radar_contact_count": 0,
            "radar_contacts": [],
            "radar_sensors": [],
            "has_radar_sensor": False,
            "has_radar_contact": False,
        }
    out = dict(fleet_alerts)
    contacts = out.get("radar_contacts")
    if isinstance(contacts, list):
        slim_contacts: List[Dict[str, Any]] = []
        for row in contacts[:_DIET_RADAR_CONTACT_CAP]:
            if not isinstance(row, dict):
                continue
            slim = {k: row[k] for k in _DIET_RADAR_CONTACT_KEYS if k in row}
            if slim:
                slim_contacts.append(slim)
        out["radar_contacts"] = slim_contacts
        # Preserve authoritative count for overflow UI even when contacts are capped.
        if "radar_contact_count" not in out:
            out["radar_contact_count"] = len(contacts)
    else:
        out["radar_contacts"] = []
    sensors = out.get("radar_sensors")
    if isinstance(sensors, list):
        slim_sensors: List[Dict[str, Any]] = []
        for row in sensors:
            if not isinstance(row, dict):
                continue
            slim_sensors.append(
                {
                    "planet_id": row.get("planet_id"),
                    "name": row.get("name"),
                    "galaxy": row.get("galaxy"),
                    "system": row.get("system"),
                    "position": row.get("position"),
                    "scan_range": row.get("scan_range"),
                }
            )
        out["radar_sensors"] = slim_sensors
    else:
        out["radar_sensors"] = []
    # Drop empty radar_alert_key noise from diet when idle.
    if not out.get("radar_alert_key"):
        out.pop("radar_alert_key", None)
    return out


def apply_lightweight_game_state_diet(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    GC-747 / GC-802 / GC-PERF-005: normal poll diet — shell HUD only.

    Keeps: resources, queues, fleet HUD, switcher planets, score, nav badges.
    Drops: page catalogs, codex, buildings map, relocation, heavy fleet rows.
    """
    for key in (
        "player_stats",
        "building_queue",
        "research_queue",
        "planet_teaser",
        "buildings",
        "codex",
        "imperial_directives",
        "planet_relocation",
        "has_seed_ark",
    ):
        payload.pop(key, None)

    resources = payload.get("resources")
    if isinstance(resources, dict) and "storage" in resources and "storage" in payload:
        resources = dict(resources)
        resources.pop("storage", None)
        payload["resources"] = resources

    if "research" in payload:
        payload["research"] = research_poll_slice(payload.get("research"))

    if "active_planet" in payload:
        payload["active_planet"] = active_planet_poll_slice(payload.get("active_planet"))

    if "planets" in payload:
        payload["planets"] = planets_poll_slice(payload.get("planets"))

    if "active_fleets" in payload:
        payload["active_fleets"] = active_fleets_poll_slice(payload.get("active_fleets"))

    if "fleet_alerts" in payload:
        payload["fleet_alerts"] = fleet_alerts_poll_slice(payload.get("fleet_alerts"))

    unread = payload.get("unread_messages_count")
    latest = payload.get("latest_message_id")
    alert_key = str((payload.get("fleet_alerts") or {}).get("alert_key") or "")
    payload["notification_revision"] = f"{max(0, int(unread or 0))}:{int(latest or 0) if latest else 0}:{alert_key}"

    try:
        payload["poll_version"] = compute_poll_version(payload)
    except Exception:
        # Never break diet polls — fingerprint is best-effort.
        payload["poll_version"] = int(payload.get("server_time") or time.time())

    try:
        pid = int(payload.get("player_id") or 0)
        if pid > 0:
            remember_diet_poll_fingerprint(
                pid,
                version=int(payload["poll_version"]),
                unread=int(payload.get("unread_messages_count") or 0),
            )
    except Exception:
        pass

    try:
        import json

        diet_bytes = len(json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"))
        set_request_perf_meta("diet_payload_bytes", diet_bytes)
        set_request_perf_meta("state_version", int(payload["poll_version"]))
    except Exception:
        pass

    return payload


def compute_state_version(payload: Dict[str, Any]) -> int:
    """Alias kept for tests — prefer ``compute_poll_version`` (GC-PERF-STATE-002)."""
    return compute_poll_version(payload)


def _queue_fp_for_poll(queue: Any) -> Any:
    """Stable queue fingerprint — ids/finish times only (ignore ticking remaining)."""
    if isinstance(queue, dict):
        queue = queue.get("queue") or queue.get("jobs") or []
    if not isinstance(queue, list):
        return []
    out = []
    for job in queue:
        if not isinstance(job, dict):
            continue
        out.append(
            {
                "id": job.get("id") or job.get("job_id"),
                "status": job.get("status"),
                "finish_at": int(float(job.get("finish_at") or job.get("finish_time") or 0)),
                "building_key": job.get("building_key")
                or job.get("key")
                or job.get("building_type"),
                "tech_key": job.get("tech_key"),
            }
        )
    return out


def _fleet_fp_for_poll(fleets: Any) -> Any:
    if not isinstance(fleets, dict):
        return fleets
    items = fleets.get("items") or fleets.get("fleets") or []
    slim_items = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            slim_items.append(
                {
                    "id": item.get("movement_id") or item.get("id"),
                    "status": item.get("status"),
                    "arrival_at": int(float(item.get("arrival_at") or 0)),
                    "return_at": int(float(item.get("return_at") or 0)),
                }
            )
    return {
        "count": fleets.get("count") or fleets.get("active_fleet_count"),
        "items": slim_items,
    }


def _hash_poll_slim(slim: Dict[str, Any]) -> int:
    import hashlib
    import json

    raw = json.dumps(slim, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def poll_slim_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the HUD slim dict hashed by ``compute_poll_version``."""
    energy = payload.get("energy") if isinstance(payload.get("energy"), dict) else {}
    active = payload.get("active_planet") if isinstance(payload.get("active_planet"), dict) else {}
    research = payload.get("research") if isinstance(payload.get("research"), dict) else {}
    return {
        "notification_revision": payload.get("notification_revision"),
        "unread_messages_count": payload.get("unread_messages_count"),
        "build_queue": _queue_fp_for_poll(payload.get("build_queue")),
        "research_queue": _queue_fp_for_poll(research.get("queue")),
        "active_fleets": _fleet_fp_for_poll(payload.get("active_fleets")),
        "energy_used": int(energy.get("used") or 0),
        "energy_total": int(energy.get("total") or 0),
        "planet_id": active.get("id") or active.get("planet_id"),
        "last_update": int(float(active.get("last_update") or 0)),
        "score": payload.get("score"),
        "nav_badges": payload.get("nav_badges"),
    }


def compute_poll_version(payload: Dict[str, Any]) -> int:
    """
    GC-PERF-STATE-002: stable int fingerprint of diet HUD fields.

    Excludes continuously projected resource floats so idle polls can short-circuit
    via ``?since=``. Version changes when queues/fleets/notifications/energy caps
    or committed resource snapshot markers change.
    """
    return _hash_poll_slim(poll_slim_from_payload(payload))


def _notification_revision_for_probe(user_id: int, *, conn) -> tuple[str, int]:
    """
    GC-PERF-RADAR-001: probe revision without toast-item assembly.

    Uses the same unread + alert_key shape as diet ``notification_revision``.
    """
    from game import messages as messages_logic

    uid = int(user_id)
    unread = 0
    latest_id = 0
    try:
        unread = int(messages_logic.unread_count(uid, conn=conn, prepare=False) or 0)
        raw_latest = messages_logic.latest_inbox_message_id(uid, conn=conn, prepare=False)
        latest_id = int(raw_latest) if raw_latest else 0
    except Exception:
        unread = 0
        latest_id = 0
    fleet_alerts = _fleet_alerts_for_notification_heartbeat(uid, conn=conn)
    alert_key = str(fleet_alerts.get("alert_key") or "")
    return f"{unread}:{latest_id}:{alert_key}", unread


def probe_poll_version(player_id: int, conn) -> Optional[int]:
    """
    GC-PERF-STATE-004: cheap HUD fingerprint matching ``compute_poll_version``.

    Reads queue/fleet/unread/energy/score/nav owners without diet payload assembly.
    GC-PERF-RADAR-001: Threat Net via fingerprint only (no contact rows / toast items).
    Returns None on error so callers fall back to a full diet build.
    """
    try:
        uid = int(player_id)
        from game.buildings import get_build_queue_status_for_planet
        from game.fleet import build_active_fleets_payload, fleet_schema_ready
        from game.logic import _read_player_live_state_no_writes
        from game.models import get_player_rank, load_player
        from game.planet_evolution.repository import get_context_planet
        from game.ranking import get_player_score_cached
        from game.research import get_research_status

        planet = get_context_planet(uid, conn=conn)
        if not planet:
            return None
        player = load_player(uid, conn=conn)
        if not player:
            return None

        _player_view, buildings, _ratio, energy_total, energy_used, _storage = (
            _read_player_live_state_no_writes(uid, conn, player, planet)
        )
        build_queue = get_build_queue_status_for_planet(
            int(planet["id"]), conn=conn, skip_finish=True
        )
        research = get_research_status(
            user_id=uid,
            buildings=buildings,
            skip_finish=True,
            conn=conn,
        )
        fleets: Dict[str, Any] = {}
        if fleet_schema_ready(conn):
            fleets = active_fleets_poll_slice(build_active_fleets_payload(uid, conn=conn))

        revision, unread = _notification_revision_for_probe(uid, conn=conn)
        score_raw = get_player_score_cached(uid, read_only=True) or {
            "total": 0,
            "buildings": 0,
            "research": 0,
        }
        rank, total_players = get_player_rank(uid)
        score = {
            "total": int(score_raw.get("total", 0) or 0),
            "buildings": int(score_raw.get("buildings", 0) or 0),
            "research": int(score_raw.get("research", 0) or 0),
            "rank": int(rank) if rank else None,
            "total_players": int(total_players) if total_players else None,
        }
        # Match diet fingerprint: active_planet poll slice historically omits last_update.
        stub = {
            "notification_revision": revision,
            "unread_messages_count": unread,
            "build_queue": build_queue,
            "research": research_poll_slice(research),
            "active_fleets": fleets,
            "energy": {"used": int(energy_used), "total": int(energy_total)},
            "active_planet": {
                "planet_id": int(planet["id"]),
                "last_update": 0,
            },
            "score": score,
            "nav_badges": nav_badges_for_game_state(uid, conn=conn),
        }
        return compute_poll_version(stub)
    except Exception:
        logger.debug("probe_poll_version failed player_id=%s", player_id, exc_info=True)
        return None


def try_diet_poll_early_unchanged(
    player_id: int,
    since: int,
    *,
    conn=None,
) -> Optional[Dict[str, Any]]:
    """
    GC-PERF-STATE-004 / STATE-005: tiny ``{unchanged:true}`` before full diet build.

    Due queue/fleet work always forces a full build so finish stays on the poll owner path.
    STATE-005: if process-local fingerprint still matches ``since`` and unread is unchanged,
    skip the heavy ``probe_poll_version`` (EffectResolver + nav badges).
    """
    from game import messages as messages_logic
    from game.logic import attach_canonical_server_time
    from game.models import db as _db
    from game.queue_poll import player_fleet_is_dirty, player_has_due_queue_work

    owns_conn = conn is None
    if owns_conn:
        conn = _db()
    try:
        now = time.time()
        uid = int(player_id)
        if player_has_due_queue_work(uid, conn=conn, now=now) or player_fleet_is_dirty(
            uid, conn=conn, now=now
        ):
            clear_diet_poll_fingerprint(uid)
            set_request_perf_meta("diet_early_exit", 0)
            return None

        cached = _DIET_POLL_FP_CACHE.get(uid)
        if cached is not None and int(cached[0]) == int(since):
            try:
                unread = int(messages_logic.unread_count(uid, conn=conn, prepare=False) or 0)
            except Exception:
                unread = -1
            if unread == int(cached[1]):
                set_request_perf_meta("diet_early_exit", 1)
                set_request_perf_meta("diet_probe_skip", 1)
                envelope: Dict[str, Any] = {
                    "ok": True,
                    "unchanged": True,
                    "since": int(since),
                    "version": int(since),
                    "poll_version": int(since),
                    "diet_early_exit": 1,
                    "diet_probe_skip": 1,
                }
                return attach_canonical_server_time(envelope)

        ver = probe_poll_version(uid, conn)
        if ver is None or int(ver) != int(since):
            set_request_perf_meta("diet_early_exit", 0)
            return None
        try:
            unread = int(messages_logic.unread_count(uid, conn=conn, prepare=False) or 0)
        except Exception:
            unread = 0
        remember_diet_poll_fingerprint(uid, version=int(ver), unread=unread)
        set_request_perf_meta("diet_early_exit", 1)
        set_request_perf_meta("diet_probe_skip", 0)
        envelope = {
            "ok": True,
            "unchanged": True,
            "since": int(since),
            "version": int(ver),
            "poll_version": int(ver),
            "diet_early_exit": 1,
        }
        return attach_canonical_server_time(envelope)
    except Exception:
        logger.debug("try_diet_poll_early_unchanged failed", exc_info=True)
        set_request_perf_meta("diet_early_exit", 0)
        return None
    finally:
        if owns_conn and conn is not None:
            conn.close()


# GC-PERF-STATE-005: process-local diet fingerprint (safe for single-worker SQLite default).
_DIET_POLL_FP_CACHE: Dict[int, tuple] = {}


def remember_diet_poll_fingerprint(player_id: int, *, version: int, unread: int) -> None:
    _DIET_POLL_FP_CACHE[int(player_id)] = (int(version), max(0, int(unread or 0)))


def clear_diet_poll_fingerprint(player_id: Optional[int] = None) -> None:
    if player_id is None:
        _DIET_POLL_FP_CACHE.clear()
        return
    _DIET_POLL_FP_CACHE.pop(int(player_id), None)


def build_delta_game_state(
    payload: Dict[str, Any],
    *,
    since: Optional[int] = None,
) -> Dict[str, Any]:
    """
    GC-PERF-STATE-002: if ``since`` matches current ``poll_version``, return tiny unchanged envelope.

    ``state_version`` remains the server clock (GC-557C). Delta uses ``poll_version`` only.
    """
    version = int(payload.get("poll_version") or compute_poll_version(payload))
    payload["poll_version"] = version
    if since is not None and int(since) == version:
        return {
            "ok": True,
            "unchanged": True,
            "since": int(since),
            "version": version,
            "poll_version": version,
            "server_time": payload.get("server_time"),
            "server_now": payload.get("server_now"),
            "state_version": payload.get("state_version"),
        }
    out = dict(payload)
    out["unchanged"] = False
    out["version"] = version
    out["poll_version"] = version
    if since is not None:
        out["since"] = int(since)
        out["changed"] = {
            "resources": payload.get("resources"),
            "energy": payload.get("energy"),
            "build_queue": payload.get("build_queue"),
            "research": payload.get("research"),
            "active_fleets": payload.get("active_fleets"),
            "notification_revision": payload.get("notification_revision"),
        }
    return out


def evaluate_request_perf_budgets(
    *,
    total_ms: float,
    response_bytes: int,
    sql_count: int,
    sql_write_count: int,
    finish_source: str = "",
    include_panel: Any = None,
) -> List[str]:
    """
    GC-PERF-CORE-001: compare request metrics against documented budgets.

    Returns list of miss keys (e.g. ``diet_poll_ms``). Empty = within budget.
    """
    try:
        from game.config import get_perf_budgets

        budgets = get_perf_budgets()
    except Exception:
        return []

    misses: List[str] = []
    src = str(finish_source or "")
    is_diet_poll = src == "game_state" and not bool(include_panel)
    is_action = src.startswith("action") or "upgrade" in src or "cancel" in src
    is_pjax = "pjax" in src or src.endswith("_ssr")

    if is_diet_poll:
        if total_ms > float(budgets.get("diet_poll_ms", 40.0)):
            misses.append("diet_poll_ms")
        diet_bytes = response_bytes
        try:
            state = _request_perf_state()
            if state and "diet_payload_bytes" in state.meta:
                diet_bytes = int(state.meta["diet_payload_bytes"])
        except Exception:
            pass
        if diet_bytes > float(budgets.get("diet_payload_bytes", 15_360.0)):
            misses.append("diet_payload_bytes")
        if sql_count > float(budgets.get("diet_sql_count", 5.0)):
            misses.append("diet_sql_count")
        if sql_write_count > float(budgets.get("diet_sql_write_count", 0.0)):
            misses.append("diet_sql_write_count")
    elif is_action:
        if total_ms > float(budgets.get("action_ms", 120.0)):
            misses.append("action_ms")
    elif is_pjax:
        if total_ms > float(budgets.get("pjax_ssr_ms", 100.0)):
            misses.append("pjax_ssr_ms")

    return misses


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
        "codex",
    ):
        payload.pop(key, None)
    overview = payload.get("overview")
    if isinstance(overview, dict):
        overview.pop("status", None)
        overview.pop("rows", None)
    return payload


# ---------------------------------------------------------------------------
# GC-PERF-REQUEST-TRACE — global slow-request profiling (extends GC-841/GC-853)
# ---------------------------------------------------------------------------


class RequestPerfState:
    """Request-scoped timings stored on Flask ``g.gc_request_perf``."""

    __slots__ = (
        "sampled",
        "started_at",
        "phases",
        "meta",
        "sql_count",
        "sql_write_count",
        "logged",
        "_write_tx_started_at",
        "_handler_started_at",
        "_after_started_at",
    )

    def __init__(self, *, sampled: bool) -> None:
        self.sampled = bool(sampled)
        self.started_at = time.perf_counter()
        self.phases: Dict[str, float] = {}
        self.meta: Dict[str, Any] = {}
        self.sql_count = 0
        self.sql_write_count = 0
        self.logged = False
        self._write_tx_started_at: Optional[float] = None
        self._handler_started_at: Optional[float] = None
        self._after_started_at: Optional[float] = None


def is_request_perf_debug_enabled() -> bool:
    from game.config import is_request_perf_debug_enabled as _enabled

    return _enabled()


def _request_perf_state() -> Optional[RequestPerfState]:
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return None
        return getattr(g, "gc_request_perf", None)
    except ImportError:
        return None


def is_request_perf_sampled() -> bool:
    state = _request_perf_state()
    return bool(state and state.sampled)


def start_request_perf(
    *,
    method: str = "",
    endpoint: str = "",
    path: str = "",
) -> None:
    """Begin request-scoped profiling when enabled and sampling selects this request."""
    if not is_request_perf_debug_enabled():
        return
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return
        sample_rate = 0.0
        try:
            from game.config import get_request_perf_sample

            sample_rate = float(get_request_perf_sample())
        except Exception:
            sample_rate = 1.0
        sampled = sample_rate >= 1.0 or (sample_rate > 0.0 and random.random() < sample_rate)
        state = RequestPerfState(sampled=sampled)
        g.gc_request_perf = state
        if sampled:
            set_request_perf_meta("method", str(method or ""))
            set_request_perf_meta("endpoint", str(endpoint or ""))
            set_request_perf_meta("path", str(path or ""))
            set_request_perf_meta("sample", 1)
    except Exception:
        logger.debug("start_request_perf failed", exc_info=True)


def mark_request_perf_enter_handler() -> None:
    """GC-PERF-PROD-001: end of before_request → start of view handler."""
    state = _request_perf_state()
    if state is None or not state.sampled or state._handler_started_at is not None:
        return
    try:
        now = time.perf_counter()
        record_request_perf_phase(
            "before_request_ms", (now - float(state.started_at)) * 1000.0
        )
        state._handler_started_at = now
    except Exception:
        logger.debug("mark_request_perf_enter_handler failed", exc_info=True)


def mark_request_perf_enter_after() -> None:
    """GC-PERF-PROD-001: end of view handler → start of after_request."""
    state = _request_perf_state()
    if state is None or not state.sampled or state._after_started_at is not None:
        return
    try:
        now = time.perf_counter()
        started = state._handler_started_at
        if started is not None:
            record_request_perf_phase(
                "handler_ms", (now - float(started)) * 1000.0
            )
        state._after_started_at = now
    except Exception:
        logger.debug("mark_request_perf_enter_after failed", exc_info=True)


def record_request_perf_phase(name: str, duration_ms: float) -> None:
    if not name or name not in _REQUEST_PERF_PHASE_KEYS:
        return
    try:
        state = _request_perf_state()
        if state is None or not state.sampled:
            return
        key = str(name)
        state.phases[key] = float(state.phases.get(key, 0.0)) + max(0.0, float(duration_ms))
    except Exception:
        logger.debug("record_request_perf_phase failed name=%s", name, exc_info=True)


def set_request_perf_meta(name: str, value: Any) -> None:
    if not name or name not in _REQUEST_PERF_META_KEYS:
        return
    try:
        state = _request_perf_state()
        if state is None or not state.sampled:
            return
        state.meta[str(name)] = value
    except Exception:
        logger.debug("set_request_perf_meta failed name=%s", name, exc_info=True)


def record_request_perf_sql_statement(sql: str) -> None:
    """Count SQL statements via sqlite trace callback (no per-statement timing)."""
    try:
        state = _request_perf_state()
        if state is None or not state.sampled:
            return
        state.sql_count += 1
        normalized = str(sql or "").lstrip().upper()
        if normalized.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            state.sql_write_count += 1
    except Exception:
        pass


def attach_request_perf_sql_trace(conn) -> None:
    if not is_request_perf_sampled():
        return
    try:
        conn.set_trace_callback(record_request_perf_sql_statement)
    except Exception:
        pass


def mark_request_perf_write_tx_started() -> None:
    try:
        state = _request_perf_state()
        if state is None or not state.sampled:
            return
        state._write_tx_started_at = time.perf_counter()
    except Exception:
        pass


def mark_request_perf_write_tx_finished() -> None:
    try:
        state = _request_perf_state()
        if state is None or not state.sampled:
            return
        started = state._write_tx_started_at
        if started is None:
            return
        elapsed_ms = (time.perf_counter() - float(started)) * 1000.0
        state._write_tx_started_at = None
        record_request_perf_phase("db_write_transaction_ms", elapsed_ms)
        record_request_perf_phase("db_transaction_ms", elapsed_ms)
    except Exception:
        pass


def _merge_existing_perf_traces(state: RequestPerfState) -> None:
    """Reuse Action/SSR trace buckets — do not recompute the same phases."""
    perf = current_action_perf()
    if perf is not None:
        for key, val in (
            ("finish_ms", perf.finish_ms),
            ("mutate_ms", perf.mutate_ms),
            ("live_state_ms", perf.live_state_ms),
            ("resource_sync_ms", perf.resource_sync_ms),
            ("payload_ms", perf.payload_ms),
        ):
            if val > 0 and key not in state.phases:
                state.phases[key] = float(val)
    ssr = current_ssr_perf()
    if ssr is not None:
        for key, val in (
            ("live_context_ms", ssr.live_context_ms),
            ("page_context_ms", ssr.live_context_ms),
            ("finish_ms", ssr.finish_ms),
            ("resource_sync_ms", ssr.resource_sync_ms),
            ("buildings_panel_ms", ssr.buildings_panel_ms),
            ("cards_ms", ssr.cards_ms),
            ("tech_data_ms", ssr.tech_data_ms),
            ("fleet_panel_ms", ssr.fleet_panel_ms),
            ("logistics_panel_ms", ssr.logistics_panel_ms),
            ("template_ms", ssr.template_ms),
            ("template_render_ms", ssr.template_ms),
        ):
            if val > 0 and key not in state.phases:
                state.phases[key] = float(val)
        if ssr.route:
            state.meta.setdefault("route", ssr.route)
        if ssr.tab and "finish_source" not in state.meta:
            state.meta["finish_source"] = f"{ssr.route}:{ssr.tab}"


def _response_byte_length(response) -> int:
    try:
        content_length = response.headers.get("Content-Length")
        if content_length is not None and str(content_length).strip().isdigit():
            return int(content_length)
    except Exception:
        pass
    try:
        data = response.get_data()
        return len(data) if data is not None else 0
    except Exception:
        return 0


def _emit_request_perf_log(
    state: RequestPerfState,
    *,
    status: int,
    response_bytes: int,
    content_type: str,
    had_exception: bool = False,
) -> None:
    if state.logged:
        return
    try:
        from game.config import get_request_perf_slow_ms

        slow_ms = float(get_request_perf_slow_ms())
    except Exception:
        slow_ms = 500.0

    total_ms = (time.perf_counter() - state.started_at) * 1000.0
    if total_ms < slow_ms:
        state.logged = True
        return

    _merge_existing_perf_traces(state)

    state.meta["status"] = int(status)
    state.meta["bytes"] = int(response_bytes or 0)
    if content_type:
        state.meta["content_type"] = str(content_type)
    if had_exception:
        state.meta["had_exception"] = 1
    state.meta["sql_count"] = int(state.sql_count)
    state.meta["sql_write_count"] = int(state.sql_write_count)

    misses = evaluate_request_perf_budgets(
        total_ms=total_ms,
        response_bytes=int(response_bytes or 0),
        sql_count=int(state.sql_count),
        sql_write_count=int(state.sql_write_count),
        finish_source=str(state.meta.get("finish_source") or ""),
        include_panel=state.meta.get("include_panel"),
    )
    if misses:
        state.meta["budget_miss"] = ",".join(misses)

    parts = [
        f"method={state.meta.get('method', '')}",
        f"endpoint={state.meta.get('endpoint', '')}",
        f"path={state.meta.get('path', '')}",
        f"status={int(status)}",
        f"total_ms={round(total_ms, 1)}",
        f"bytes={int(response_bytes or 0)}",
        f"sample={state.meta.get('sample', 1)}",
    ]

    for meta_key in (
        "finish_source",
        "route",
        "pjax",
        "include_panel",
        "panel_delta",
        "fleet_tick_ran",
        "fleet_tick_source",
        "derived_sync_count",
        "account_deletions_ran",
        "content_type",
        "sql_count",
        "sql_write_count",
        "diet_payload_bytes",
        "budget_miss",
        "state_version",
        "delta_since",
        "had_exception",
    ):
        if meta_key in state.meta:
            parts.append(f"{meta_key}={state.meta[meta_key]}")

    for phase_key in sorted(state.phases.keys()):
        parts.append(f"{phase_key}={round(state.phases[phase_key], 1)}")

    logger.info("[GC REQUEST PERF] %s", " ".join(parts))
    state.logged = True


def finish_request_perf_after(response):
    """Log slow requests after the handler returns a response."""
    state = _request_perf_state()
    if state is None or not state.sampled:
        return response
    try:
        after_started = state._after_started_at
        if after_started is not None and "after_request_ms" not in state.phases:
            record_request_perf_phase(
                "after_request_ms",
                (time.perf_counter() - float(after_started)) * 1000.0,
            )
        status = int(getattr(response, "status_code", 200) or 200)
        content_type = str(response.headers.get("Content-Type") or "")
        response_bytes = _response_byte_length(response)
        _emit_request_perf_log(
            state,
            status=status,
            response_bytes=response_bytes,
            content_type=content_type,
        )
        if not is_production_request_perf_header():
            response.headers["X-GC-Request-Perf-Total-Ms"] = str(
                round((time.perf_counter() - state.started_at) * 1000.0, 1)
            )
    except Exception:
        logger.debug("finish_request_perf_after failed", exc_info=True)
    return response


def finish_request_perf_teardown(exc: BaseException | None = None) -> None:
    """Fallback when after_request did not emit (rare); never raises."""
    state = _request_perf_state()
    if state is None or not state.sampled or state.logged:
        return
    try:
        status = 500 if exc is not None else 0
        _emit_request_perf_log(
            state,
            status=status,
            response_bytes=0,
            content_type="",
            had_exception=exc is not None,
        )
    except Exception:
        logger.debug("finish_request_perf_teardown failed", exc_info=True)


def is_production_request_perf_header() -> bool:
    try:
        from game.config import is_production

        return bool(is_production())
    except Exception:
        return False
