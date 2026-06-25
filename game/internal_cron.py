"""
Internal HTTP cron handlers — run inside the web process (same SQLite volume).

Railway SQLite deployments must not use a separate worker service; external schedulers
call POST /api/internal/cron/ranking with GC_INTERNAL_CRON_TOKEN.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from flask import Request

from game.config import get_internal_cron_token
from game.ranking_worker import run_ranking_worker

logger = logging.getLogger(__name__)


def _cron_log(msg: str) -> None:
    line = f"[ranking-http-cron] {msg}"
    print(line, flush=True)
    logger.info("%s", msg)


def _parse_bearer_token(request: Request) -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def verify_internal_cron_request(request: Request) -> Tuple[bool, str]:
    """Return (authorized, error_message)."""
    expected = get_internal_cron_token()
    if not expected:
        return False, "unauthorized"
    provided = _parse_bearer_token(request)
    if not provided or provided != expected:
        return False, "unauthorized"
    return True, ""


def parse_force_flag(request: Request) -> bool:
    val = str(request.args.get("force", "") or "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        raw = body.get("force")
        if raw in (True, 1, "1", "true", "yes", "on"):
            return True
    return False


def handle_internal_cron_ranking(request: Request) -> Tuple[Dict[str, Any], int]:
    """
    Recompute ranking scores + ranks on the active web-service database.

    Auth: Authorization: Bearer <GC_INTERNAL_CRON_TOKEN>
    Optional: ?force=1 or JSON {"force": true} to bypass the 10-minute guard.
    """
    authorized, auth_err = verify_internal_cron_request(request)
    if not authorized:
        _cron_log("unauthorized")
        return {"ok": False, "error": auth_err or "unauthorized"}, 401

    force = parse_force_flag(request)
    _cron_log(f"start source=http force={str(force).lower()}")
    try:
        result = run_ranking_worker(
            source="http_cron",
            force=force,
            persist=True,
            allow_empty=False,
        )
    except Exception as exc:
        logger.exception("internal cron ranking failed")
        _cron_log(f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    payload: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "players_updated": int(result.get("players_updated") or 0),
        "ranks_assigned": int(result.get("ranks_assigned") or 0),
        "duration_ms": int(result.get("duration_ms") or 0),
        "skipped_interval": bool(result.get("skipped_interval")),
    }
    if result.get("players_seen") is not None:
        payload["players_seen"] = int(result["players_seen"])
    if result.get("next_run_in_sec") is not None:
        payload["next_run_in_sec"] = int(result["next_run_in_sec"])
    errors = list(result.get("errors") or [])
    if errors:
        payload["errors"] = errors

    if payload["skipped_interval"]:
        _cron_log(
            "source=http "
            f"skipped_interval=true next_run_in_sec={payload.get('next_run_in_sec', 0)} "
            f"duration_ms={payload['duration_ms']}"
        )
    elif payload["ok"]:
        _cron_log(
            "source=http "
            f"players_updated={payload['players_updated']} "
            f"ranks_assigned={payload['ranks_assigned']} "
            f"duration_ms={payload['duration_ms']}"
        )
    else:
        _cron_log(
            "source=http ok=false "
            f"players_updated={payload['players_updated']} "
            f"duration_ms={payload['duration_ms']} "
            f"errors={errors}"
        )

    status = 200 if payload["ok"] else 500
    return payload, status
