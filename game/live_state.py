"""
Request-scoped guard for the single-pass live refresh pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


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
    After refresh_player_live_state in the same request, force skip_finish=True
    so get_research_status / get_build_queue_status never run a second finish pass.
    """
    if skip_finish:
        return True
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
