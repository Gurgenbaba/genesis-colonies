"""Public, aggregate-only universe stats for external showcases.

Serves a handful of counters (players, colonies, fleets in flight, ...) for
the developer portfolio at gurgenbaba.github.io. Only totals leave the server,
never names, ids or coordinates. The payload is cached in-process so a busy
landing page can never turn into database load, and CORS is limited to an
explicit origin allowlist (``GC_PUBLIC_STATS_ORIGINS``).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = max(15, int(os.environ.get("GC_PUBLIC_STATS_CACHE_TTL", "60") or 60))
DEFAULT_ORIGINS = "https://gurgenbaba.github.io"
ACTIVE_WINDOW_SECONDS = 24 * 3600
_FLEET_ACTIVE_STATUSES = ("outbound", "holding", "returning")

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}


def allowed_origins() -> frozenset[str]:
    raw = os.environ.get("GC_PUBLIC_STATS_ORIGINS", DEFAULT_ORIGINS)
    return frozenset(o.strip().rstrip("/") for o in raw.split(",") if o.strip())


def _count(conn, sql: str, params: tuple = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row["cnt"] or 0) if row is not None else 0


def collect_public_stats(conn, *, now: float | None = None) -> dict[str, Any]:
    """Aggregate counters only. Missing optional tables count as zero."""
    from game.db import table_exists
    from game.presence_store import effective_last_seen_scalar_sql

    ts = time.time() if now is None else float(now)
    last_seen = effective_last_seen_scalar_sql(player_alias="p")
    stats: dict[str, Any] = {
        "players": _count(conn, "SELECT COUNT(*) AS cnt FROM players p WHERE p.is_admin = 0"),
        "active_24h": _count(
            conn,
            f"SELECT COUNT(*) AS cnt FROM players p WHERE p.is_admin = 0 AND {last_seen} >= ?",
            (int(ts - ACTIVE_WINDOW_SECONDS),),
        ),
        "colonies": _count(
            conn,
            "SELECT COUNT(*) AS cnt FROM planets pl JOIN players p ON p.id = pl.player_id WHERE p.is_admin = 0",
        ),
        "fleets_in_flight": 0,
        "alliances": 0,
    }
    if table_exists(conn, "fleet_movements"):
        marks = ", ".join("?" for _ in _FLEET_ACTIVE_STATUSES)
        stats["fleets_in_flight"] = _count(
            conn,
            "SELECT COUNT(*) AS cnt FROM fleet_movements fm JOIN players p ON p.id = fm.player_id "
            f"WHERE p.is_admin = 0 AND fm.status IN ({marks})",
            _FLEET_ACTIVE_STATUSES,
        )
    if table_exists(conn, "alliances"):
        stats["alliances"] = _count(conn, "SELECT COUNT(*) AS cnt FROM alliances")
    stats["generated_at"] = int(ts)
    return stats


def get_public_stats() -> dict[str, Any] | None:
    """Cached stats; serves the last good payload if the database hiccups."""
    now = time.time()
    with _CACHE_LOCK:
        if _CACHE["payload"] is not None and now < _CACHE["expires_at"]:
            return _CACHE["payload"]

    from game.db import db, rollback

    try:
        conn = db()
        try:
            payload = collect_public_stats(conn, now=now)
        finally:
            try:
                rollback(conn)
            except Exception:
                pass
            conn.close()
    except Exception:
        logger.warning("public stats collection failed", exc_info=True)
        with _CACHE_LOCK:
            # Back off so a failing database is not hammered by the landing page.
            _CACHE["expires_at"] = now + CACHE_TTL_SECONDS
            return _CACHE["payload"]

    with _CACHE_LOCK:
        _CACHE["payload"] = payload
        _CACHE["expires_at"] = now + CACHE_TTL_SECONDS
    return payload


def reset_public_stats_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["payload"] = None
        _CACHE["expires_at"] = 0.0


def register_public_stats_routes(app) -> None:
    from flask import jsonify, request

    endpoint = "api_public_stats"
    if endpoint in app.view_functions:
        return

    @app.get("/api/public/stats", endpoint=endpoint)
    def _public_stats():
        payload = get_public_stats()
        if payload is None:
            response = jsonify({"ok": False, "error": "stats_unavailable"})
            response.status_code = 503
        else:
            response = jsonify({"ok": True, **payload})
            response.headers["Cache-Control"] = f"private, max-age={CACHE_TTL_SECONDS}"
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if origin and origin in allowed_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response
