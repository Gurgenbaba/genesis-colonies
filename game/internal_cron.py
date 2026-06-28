"""
Internal HTTP cron handlers — run inside the web process (same SQLite volume).

Railway SQLite deployments must not use a separate worker service; external schedulers
call POST /api/internal/cron/ranking with GC_INTERNAL_CRON_TOKEN.

Admin manual trigger: POST /api/admin/ranking/recompute (@require_admin_api, force=1).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from flask import Request

from game.config import get_internal_cron_token
from game.ranking_worker import run_ranking_worker

logger = logging.getLogger(__name__)


def _recompute_log(prefix: str, msg: str) -> None:
    line = f"[{prefix}] {msg}"
    print(line, flush=True)
    logger.info("%s", msg)


def build_ranking_recompute_payload(result: Dict[str, Any]) -> Dict[str, Any]:
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
    if result.get("scores_updated") is not None:
        payload["scores_updated"] = int(result.get("scores_updated") or 0)
    if result.get("top_score_after") is not None:
        payload["top_score"] = int(result.get("top_score_after") or 0)
    errors = list(result.get("errors") or [])
    if errors:
        payload["errors"] = errors
    return payload


def execute_ranking_recompute(
    *,
    force: bool,
    source: str,
    allow_empty: bool = False,
) -> Dict[str, Any]:
    """Canonical ranking batch job — shared by HTTP cron and admin recompute."""
    return build_ranking_recompute_payload(
        run_ranking_worker(
            source=source,
            force=force,
            persist=True,
            allow_empty=allow_empty,
        )
    )


def log_ranking_recompute_result(
    payload: Dict[str, Any],
    *,
    log_prefix: str,
    source_label: str,
) -> None:
    if payload.get("skipped_interval"):
        _recompute_log(
            log_prefix,
            f"source={source_label} skipped_interval=true "
            f"next_run_in_sec={payload.get('next_run_in_sec', 0)} "
            f"duration_ms={payload.get('duration_ms', 0)}",
        )
    elif payload.get("ok"):
        _recompute_log(
            log_prefix,
            f"source={source_label} "
            f"players_updated={payload.get('players_updated', 0)} "
            f"ranks_assigned={payload.get('ranks_assigned', 0)} "
            f"duration_ms={payload.get('duration_ms', 0)}",
        )
    else:
        _recompute_log(
            log_prefix,
            f"source={source_label} ok=false "
            f"players_updated={payload.get('players_updated', 0)} "
            f"duration_ms={payload.get('duration_ms', 0)} "
            f"errors={payload.get('errors', [])}",
        )


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
        _recompute_log("ranking-http-cron", "unauthorized")
        return {"ok": False, "error": auth_err or "unauthorized"}, 401

    force = parse_force_flag(request)
    _recompute_log("ranking-http-cron", f"request_received force={str(force).lower()}")
    try:
        payload = execute_ranking_recompute(force=force, source="http_cron")
    except Exception as exc:
        logger.exception("internal cron ranking failed")
        _recompute_log("ranking-http-cron", f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    log_ranking_recompute_result(payload, log_prefix="ranking-http-cron", source_label="http")
    status = 200 if payload["ok"] else 500
    return payload, status


def handle_admin_ranking_recompute() -> Tuple[Dict[str, Any], int]:
    """Admin session trigger — always force=1 to bypass interval guard."""
    _recompute_log("ranking-admin", "start source=admin force=true")
    try:
        payload = execute_ranking_recompute(force=True, source="admin")
    except Exception as exc:
        logger.exception("admin ranking recompute failed")
        _recompute_log("ranking-admin", f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    log_ranking_recompute_result(payload, log_prefix="ranking-admin", source_label="admin")
    status = 200 if payload["ok"] else 500
    return payload, status


def handle_internal_cron_vote_reengagement(request: Request) -> Tuple[Dict[str, Any], int]:
    """Staggered vote re-engagement for inactive universe players."""
    authorized, auth_err = verify_internal_cron_request(request)
    if not authorized:
        logger.info("vote-reengagement-http-cron unauthorized")
        return {"ok": False, "error": auth_err or "unauthorized"}, 401

    from game.db import begin_write_transaction, commit, db, rollback
    from game.vote_reengagement import run_vote_reengagement

    force = parse_force_flag(request)
    conn = db()
    try:
        begin_write_transaction(conn)
        payload = run_vote_reengagement(conn=conn, force=force, source="http_cron")
        if payload.get("ok"):
            commit(conn)
        else:
            rollback(conn)
    except Exception as exc:
        rollback(conn)
        logger.exception("internal cron vote reengagement failed")
        return {"ok": False, "error": str(exc)}, 500
    finally:
        conn.close()

    status = 200 if payload.get("ok") else 500
    return payload, status


def handle_admin_vote_reengagement_run(*, force: bool = True) -> Tuple[Dict[str, Any], int]:
    from game.db import begin_write_transaction, commit, db, rollback
    from game.vote_reengagement import run_vote_reengagement

    conn = db()
    try:
        begin_write_transaction(conn)
        payload = run_vote_reengagement(conn=conn, force=force, source="admin")
        if payload.get("ok"):
            commit(conn)
        else:
            rollback(conn)
    except Exception as exc:
        rollback(conn)
        logger.exception("admin vote reengagement run failed")
        return {"ok": False, "error": str(exc)}, 500
    finally:
        conn.close()
    status = 200 if payload.get("ok") else 500
    return payload, status
