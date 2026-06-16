"""Fleet send/preview origin planet scope (GC-557C)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import sqlite3

logger = logging.getLogger(__name__)


def _owned_planet_id(player_id: int, planet_id: int, *, conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (int(planet_id), int(player_id)),
    ).fetchone()
    return int(row["id"]) if row else None


def resolve_fleet_origin_planet_id(
    player_id: int,
    request_origin_planet_id: Optional[int],
    *,
    conn: sqlite3.Connection,
    dom_planet_id: Optional[int] = None,
) -> Tuple[int, Dict[str, Any]]:
    """
    Resolve fleet origin to an owned planet; default = context planet.

    Logs WARN when request/context/active/dom disagree (scope mismatch).
    """
    from .planet_evolution.repository import get_active_planet_id, get_context_planet

    context = get_context_planet(int(player_id), conn=conn)
    context_id = int(context["id"])
    active_id = int(get_active_planet_id(int(player_id), conn=conn) or context_id)
    req_raw = int(request_origin_planet_id) if request_origin_planet_id else context_id
    owned_req = _owned_planet_id(int(player_id), req_raw, conn=conn)
    resolved = int(owned_req if owned_req is not None else context_id)
    dom_id = int(dom_planet_id) if dom_planet_id else None

    audit: Dict[str, Any] = {
        "request_origin_planet": req_raw,
        "context_planet": context_id,
        "active_planet": active_id,
        "resolved_origin_planet": resolved,
    }
    if dom_id is not None:
        audit["dom_planet"] = dom_id

    scope_ids = {context_id, active_id, resolved}
    if owned_req is not None:
        scope_ids.add(req_raw)
    if dom_id is not None:
        scope_ids.add(dom_id)

    if len(scope_ids) > 1:
        logger.warning("Fleet Origin Scope Mismatch: %s", audit)

    return resolved, audit
