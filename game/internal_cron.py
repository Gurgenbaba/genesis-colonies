"""
Internal HTTP cron handlers — run inside the web process (same SQLite volume by default).

Railway SQLite deployments must not use a separate worker service (volume is service-bound).
Maintenance runs via:

1. **Embedded cron** (default in production) — in-process loop, no external scheduler
2. Optional HTTP: POST /api/internal/cron/* with GC_INTERNAL_CRON_TOKEN (manual / force)

Endpoints:
  - ranking, fleet-tick, vote-reengagement, queue-tick (GC-PERF-WORKER-001)
  - galactic-directives (GC-720I monthly mandate resolve)

With GC_DB_BACKEND=postgres, a dedicated ``scripts/run_game_worker.py`` process is supported.
Vote re-engagement piggybacks on the ranking maintenance bag (30-minute interval guard).

Do NOT set Railway ``cronSchedule`` on the web service — that expects the process to exit.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import Request

from game.config import (
    get_embedded_backup_keep,
    get_embedded_cron_interval_sec,
    get_internal_cron_token,
    is_embedded_backup_enabled,
    is_embedded_cron_enabled,
)
from game.fleet_worker import run_fleet_worker
from game.ranking_worker import run_ranking_worker

logger = logging.getLogger(__name__)

_EMBEDDED_THREAD: Optional[threading.Thread] = None
_EMBEDDED_STOP = threading.Event()
_EMBEDDED_LOCK_FH: Any = None
_EMBEDDED_STARTED = False


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


def execute_vote_reengagement(
    *,
    force: bool,
    source: str,
    catch_all: bool = False,
    batch_size: Optional[int] = None,
) -> Dict[str, Any]:
    """Canonical vote re-engagement batch — shared by HTTP cron and ranking piggyback."""
    from game.db import begin_write_transaction, commit, db, rollback
    from game.vote_reengagement import run_vote_reengagement

    conn = db()
    try:
        begin_write_transaction(conn)
        payload = run_vote_reengagement(
            conn=conn,
            force=force,
            catch_all=catch_all,
            batch_size=batch_size,
            persist=True,
            source=source,
        )
        if payload.get("ok") and not payload.get("skipped_interval"):
            commit(conn)
        else:
            rollback(conn)
        return payload
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def log_vote_reengagement_result(
    payload: Dict[str, Any],
    *,
    log_prefix: str,
    source_label: str,
) -> None:
    if payload.get("skipped_disabled"):
        _recompute_log(log_prefix, f"source={source_label} skipped_disabled=true")
    elif payload.get("skipped_interval"):
        _recompute_log(
            log_prefix,
            f"source={source_label} skipped_interval=true "
            f"next_run_in_sec={payload.get('next_run_in_sec', 0)} "
            f"duration_ms={payload.get('duration_ms', 0)}",
        )
    elif payload.get("ok"):
        _recompute_log(
            log_prefix,
            f"source={source_label} created={payload.get('created', 0)} "
            f"slot={payload.get('slot', 0)} duration_ms={payload.get('duration_ms', 0)}",
        )
    else:
        _recompute_log(
            log_prefix,
            f"source={source_label} ok=false "
            f"duration_ms={payload.get('duration_ms', 0)} "
            f"errors={payload.get('errors', [])}",
        )


def execute_fleet_tick(*, force: bool, source: str) -> Dict[str, Any]:
    """Canonical global fleet tick — shared by HTTP cron and request safety net."""
    return run_fleet_worker(force=force, source=source, persist=True)


def execute_queue_tick(*, force: bool, source: str) -> Dict[str, Any]:
    """
    GC-PERF-WORKER-001: global due-queue finish via tick_runner (same engine as admin/CLI).

    ``force`` is accepted for API symmetry; queue tick always processes currently due work.
    """
    from game.tick_runner import run_tick

    _ = force  # reserved for future interval guard parity with fleet/ranking
    return run_tick(scope="due", source=str(source or "http_cron"), persist=True)


def log_queue_tick_result(
    payload: Dict[str, Any],
    *,
    log_prefix: str,
    source_label: str,
) -> None:
    finished = payload.get("finished") or {}
    _recompute_log(
        log_prefix,
        f"source={source_label} ok={str(bool(payload.get('ok'))).lower()} "
        f"players={payload.get('players_processed', 0)} "
        f"buildings={finished.get('buildings', 0)} "
        f"research={finished.get('research', 0)} "
        f"shipyard={finished.get('shipyard', 0)} "
        f"defense={finished.get('defense', 0)} "
        f"duration_ms={payload.get('duration_ms', 0)}",
    )


def log_fleet_tick_result(
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
            f"arrivals={payload.get('processed_arrivals', 0)} "
            f"holding={payload.get('processed_holding', 0)} "
            f"returns={payload.get('processed_returns', 0)} "
            f"duration_ms={payload.get('duration_ms', 0)}",
        )
    else:
        _recompute_log(
            log_prefix,
            f"source={source_label} ok=false "
            f"duration_ms={payload.get('duration_ms', 0)} "
            f"errors={payload.get('errors', [])}",
        )


def _maybe_run_fleet_tick(*, force: bool, source: str) -> Dict[str, Any]:
    """Run global fleet tick when due; never raises — ranking cron stays resilient."""
    try:
        payload = execute_fleet_tick(force=force, source=source)
        log_fleet_tick_result(
            payload,
            log_prefix="fleet-http-cron",
            source_label=source,
        )
        return payload
    except Exception as exc:
        logger.exception("fleet tick piggyback failed")
        _recompute_log("fleet-http-cron", f"source={source} error={exc}")
        return {"ok": False, "error": str(exc)}


def _maybe_run_vote_reengagement(*, force: bool, source: str) -> Dict[str, Any]:
    """Run vote re-engagement when due; never raises — ranking cron stays resilient."""
    try:
        payload = execute_vote_reengagement(force=force, source=source)
        log_vote_reengagement_result(
            payload,
            log_prefix="vote-reengagement-http-cron",
            source_label=source,
        )
        return payload
    except Exception as exc:
        logger.exception("vote reengagement piggyback failed")
        _recompute_log("vote-reengagement-http-cron", f"source={source} error={exc}")
        return {"ok": False, "error": str(exc)}


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
        payload = run_maintenance_bag(force=force, source="http_cron")
    except Exception as exc:
        logger.exception("internal cron ranking failed")
        _recompute_log("ranking-http-cron", f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    status = 200 if payload.get("ok") else 500
    return payload, status


def run_maintenance_bag(*, force: bool = False, source: str = "embedded_cron") -> Dict[str, Any]:
    """
    Canonical web-service maintenance bag (ranking + fleet + vote + deletions + backup).

    Shared by HTTP cron and the embedded in-process scheduler. Interval guards inside
    ranking/fleet/vote keep frequent ticks cheap.
    """
    try:
        payload = execute_ranking_recompute(force=force, source=source)
    except Exception as exc:
        logger.exception("maintenance bag ranking failed")
        _recompute_log("maintenance-bag", f"source={source} ranking_error={exc}")
        return {"ok": False, "error": str(exc)}

    log_ranking_recompute_result(
        payload,
        log_prefix="ranking-http-cron" if source == "http_cron" else "ranking-embedded-cron",
        source_label="http" if source == "http_cron" else source,
    )

    fleet_payload = _maybe_run_fleet_tick(force=False, source=source)
    payload["fleet_tick"] = fleet_payload

    vote_payload = _maybe_run_vote_reengagement(force=False, source=source)
    payload["vote_reengagement"] = vote_payload

    try:
        from game.options import maybe_run_due_account_deletions

        payload["account_deletions"] = maybe_run_due_account_deletions(
            force=force,
            source=source,
        )
    except Exception as exc:
        logger.exception("maintenance bag account deletion worker failed")
        payload["account_deletions"] = {"ok": False, "error": str(exc)}

    try:
        payload["sqlite_backup"] = maybe_sqlite_volume_backup(force=force)
    except Exception as exc:
        logger.exception("maintenance bag sqlite backup failed")
        payload["sqlite_backup"] = {"ok": False, "error": str(exc)}

    return payload


def maybe_sqlite_volume_backup(*, force: bool = False) -> Dict[str, Any]:
    """
    Online SQLite backup into <db-parent>/backups/game-YYYYMMDD.db (Railway /data volume).

    Skips when disabled, non-sqlite, or today's file already exists (unless force).
    """
    if not is_embedded_backup_enabled():
        return {"ok": True, "skipped": "disabled"}

    from game.db import get_db_backend, resolve_db_path

    if get_db_backend() != "sqlite":
        return {"ok": True, "skipped": "not_sqlite"}

    src = resolve_db_path()
    if not src.is_file():
        return {"ok": False, "error": "db_missing", "path": str(src)}

    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    backup_dir = src.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / f"game-{day}.db"
    if dst.exists() and not force:
        return {"ok": True, "skipped": "already_today", "path": str(dst)}

    import sqlite3

    tmp = backup_dir / f"game-{day}.db.tmp"
    try:
        if tmp.exists():
            tmp.unlink()
        source_conn = sqlite3.connect(str(src), timeout=30.0)
        try:
            dest_conn = sqlite3.connect(str(tmp), timeout=30.0)
            try:
                source_conn.backup(dest_conn)
                dest_conn.commit()
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
        # Windows needs handles closed before replace/rename.
        if dst.exists():
            dst.unlink()
        os.replace(str(tmp), str(dst))
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise

    keep = get_embedded_backup_keep()
    pruned = _prune_sqlite_backups(backup_dir, keep=keep)
    return {
        "ok": True,
        "path": str(dst),
        "bytes": int(dst.stat().st_size),
        "pruned": pruned,
    }


def _prune_sqlite_backups(backup_dir: Path, *, keep: int) -> int:
    files = sorted(
        (p for p in backup_dir.glob("game-*.db") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    pruned = 0
    for old in files[keep:]:
        try:
            old.unlink()
            pruned += 1
        except OSError:
            logger.warning("could not prune backup %s", old)
    return pruned


def _acquire_embedded_leader_lock() -> bool:
    """Single leader across gunicorn workers (file lock next to SQLite DB)."""
    global _EMBEDDED_LOCK_FH
    from game.db import get_db_backend, resolve_db_path

    if get_db_backend() == "sqlite":
        lock_path = resolve_db_path().parent / ".gc_embedded_cron.lock"
    else:
        lock_path = Path(os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp") / (
            "gc_embedded_cron.lock"
        )
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "a+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt

            if fh.tell() == 0:
                fh.write("0")
                fh.flush()
            try:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fh.close()
                return False
        else:
            import fcntl

            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        _EMBEDDED_LOCK_FH = fh
        return True
    except OSError as exc:
        logger.warning("embedded cron leader lock failed: %s", exc)
        return False


def _embedded_cron_loop() -> None:
    interval = get_embedded_cron_interval_sec()
    _recompute_log(
        "embedded-cron",
        f"started interval_sec={interval} backup={str(is_embedded_backup_enabled()).lower()}",
    )
    # Small delay so gunicorn/healthcheck can finish boot before first heavy tick.
    _EMBEDDED_STOP.wait(min(15.0, interval))
    while not _EMBEDDED_STOP.is_set():
        started = time.monotonic()
        try:
            run_maintenance_bag(force=False, source="embedded_cron")
        except Exception:
            logger.exception("embedded cron tick failed")
        elapsed = time.monotonic() - started
        wait_for = max(1.0, interval - elapsed)
        _EMBEDDED_STOP.wait(wait_for)
    _recompute_log("embedded-cron", "stopped")


def start_embedded_cron_if_enabled() -> bool:
    """
    Start daemon maintenance thread when enabled (production default).

    Returns True if the thread was started in this process.
    """
    global _EMBEDDED_THREAD, _EMBEDDED_STARTED
    if _EMBEDDED_STARTED:
        return False
    _EMBEDDED_STARTED = True

    # Flask debug reloader parent process
    if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
        return False
    if not is_embedded_cron_enabled():
        _recompute_log("embedded-cron", "disabled")
        return False
    if not _acquire_embedded_leader_lock():
        _recompute_log("embedded-cron", "skipped_not_leader")
        return False

    _EMBEDDED_STOP.clear()
    thread = threading.Thread(
        target=_embedded_cron_loop,
        name="gc-embedded-cron",
        daemon=True,
    )
    _EMBEDDED_THREAD = thread
    thread.start()
    return True


def stop_embedded_cron_for_tests() -> None:
    """Test helper — stop the daemon thread and release the leader lock."""
    global _EMBEDDED_THREAD, _EMBEDDED_LOCK_FH, _EMBEDDED_STARTED
    _EMBEDDED_STOP.set()
    thread = _EMBEDDED_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    _EMBEDDED_THREAD = None
    if _EMBEDDED_LOCK_FH is not None:
        try:
            _EMBEDDED_LOCK_FH.close()
        except Exception:
            pass
        _EMBEDDED_LOCK_FH = None
    _EMBEDDED_STARTED = False
    _EMBEDDED_STOP.clear()


def handle_internal_cron_fleet_tick(request: Request) -> Tuple[Dict[str, Any], int]:
    """
    Process due fleet movements for all players on the active web-service database.

    Auth: Authorization: Bearer <GC_INTERNAL_CRON_TOKEN>
    Optional: ?force=1 or JSON {"force": true} to bypass the idle interval guard.
    """
    authorized, auth_err = verify_internal_cron_request(request)
    if not authorized:
        _recompute_log("fleet-http-cron", "unauthorized")
        return {"ok": False, "error": auth_err or "unauthorized"}, 401

    force = parse_force_flag(request)
    _recompute_log("fleet-http-cron", f"request_received force={str(force).lower()}")
    try:
        payload = execute_fleet_tick(force=force, source="http_cron")
    except Exception as exc:
        logger.exception("internal cron fleet tick failed")
        _recompute_log("fleet-http-cron", f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    log_fleet_tick_result(payload, log_prefix="fleet-http-cron", source_label="http")
    status = 200 if payload.get("ok") else 500
    return payload, status


def handle_internal_cron_queue_tick(request: Request) -> Tuple[Dict[str, Any], int]:
    """
    GC-PERF-WORKER-001: process due build/research/shipyard/defense queues globally.

    Auth: Authorization: Bearer <GC_INTERNAL_CRON_TOKEN>
    Uses the same ``finish_due_work`` owner as request-path finishes (no parallel queue).
    """
    authorized, auth_err = verify_internal_cron_request(request)
    if not authorized:
        _recompute_log("queue-http-cron", "unauthorized")
        return {"ok": False, "error": auth_err or "unauthorized"}, 401

    force = parse_force_flag(request)
    _recompute_log("queue-http-cron", f"request_received force={str(force).lower()}")
    try:
        payload = execute_queue_tick(force=force, source="http_cron")
    except Exception as exc:
        logger.exception("internal cron queue tick failed")
        _recompute_log("queue-http-cron", f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    log_queue_tick_result(payload, log_prefix="queue-http-cron", source_label="http")
    # Fleet is already part of run_tick; expose nested summary if present.
    status = 200 if payload.get("ok") else 500
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

    force = parse_force_flag(request)
    _recompute_log(
        "vote-reengagement-http-cron",
        f"request_received force={str(force).lower()}",
    )
    try:
        payload = execute_vote_reengagement(force=force, source="http_cron")
    except Exception as exc:
        logger.exception("internal cron vote reengagement failed")
        _recompute_log("vote-reengagement-http-cron", f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    log_vote_reengagement_result(
        payload,
        log_prefix="vote-reengagement-http-cron",
        source_label="http",
    )
    status = 200 if payload.get("ok") else 500
    return payload, status


def execute_galactic_directives_resolve(*, force: bool, source: str) -> Dict[str, Any]:
    """GC-720I: resolve overdue galactic directive cycles for all galaxies."""
    from game.galactic_directives import resolve_due_cycles

    _ = force  # reserved for interval-guard symmetry with other cron jobs
    result = resolve_due_cycles()
    payload = {
        "ok": bool(result.get("ok")),
        "resolved_count": len(result.get("resolved") or []),
        "synced": int(result.get("synced") or 0),
        "galaxies": int(result.get("galaxies") or 0),
        "server_time": int(result.get("server_time") or 0),
        "source": str(source or "http_cron"),
    }
    if result.get("resolved"):
        payload["resolved"] = list(result["resolved"])
    return payload


def log_galactic_directives_resolve_result(
    payload: Dict[str, Any],
    *,
    log_prefix: str,
    source_label: str,
) -> None:
    _recompute_log(
        log_prefix,
        f"source={source_label} ok={str(bool(payload.get('ok'))).lower()} "
        f"resolved={payload.get('resolved_count', 0)} "
        f"synced={payload.get('synced', 0)} "
        f"galaxies={payload.get('galaxies', 0)}",
    )


def handle_internal_cron_galactic_directives(request: Request) -> Tuple[Dict[str, Any], int]:
    """Token-gated galactic directive mandate resolve (GC-720I)."""
    authorized, auth_err = verify_internal_cron_request(request)
    if not authorized:
        _recompute_log("gd-http-cron", "unauthorized")
        return {"ok": False, "error": auth_err or "unauthorized"}, 401

    force = parse_force_flag(request)
    _recompute_log("gd-http-cron", f"request_received force={str(force).lower()}")
    try:
        payload = execute_galactic_directives_resolve(force=force, source="http_cron")
    except Exception as exc:
        logger.exception("internal cron galactic directives resolve failed")
        _recompute_log("gd-http-cron", f"error={exc}")
        return {"ok": False, "error": str(exc)}, 500

    log_galactic_directives_resolve_result(
        payload,
        log_prefix="gd-http-cron",
        source_label="http",
    )
    status = 200 if payload.get("ok") else 500
    return payload, status


def handle_admin_vote_reengagement_run(
    *,
    force: bool = True,
    catch_all: bool = False,
    batch_size: Optional[int] = None,
) -> Tuple[Dict[str, Any], int]:
    try:
        payload = execute_vote_reengagement(
            force=force,
            catch_all=catch_all,
            batch_size=batch_size,
            source="admin",
        )
    except Exception as exc:
        logger.exception("admin vote reengagement run failed")
        return {"ok": False, "error": str(exc)}, 500
    status = 200 if payload.get("ok") else 500
    return payload, status
