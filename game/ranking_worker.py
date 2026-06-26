"""
Background ranking worker — batch score + rank refresh (cron / CLI).

Gameplay paths must not call compute_player_scores() directly; use score_events or admin
force-recalc. The worker batch-refreshes all players on a schedule as a safety net.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

from .db import (
    count_table_rows,
    db,
    gather_db_startup_diagnostics,
    gather_score_stats,
)
from .ranking import recalculate_all_rankings
from .runtime_state import get_runtime_value, set_runtime_value

logger = logging.getLogger(__name__)

RANKING_WORKER_KEY = "ranking_worker_last"
RANKING_WORKER_INTERVAL_SEC = 600  # 10 minutes


def _empty_worker_status() -> Dict[str, Any]:
    return {
        "last_run_at": None,
        "last_run_source": None,
        "ok": None,
        "players_updated": 0,
        "ranks_assigned": 0,
        "duration_ms": 0,
        "errors": [],
        "errors_count": 0,
        "skipped_interval": False,
        "next_run_in_sec": None,
    }


def _worker_log(msg: str) -> None:
    line = f"[ranking-worker] {msg}"
    print(line, flush=True)
    logger.info("%s", msg)


def _log_worker_event(event: str, **fields: Any) -> None:
    parts = [f"ranking_worker_{event}"] + [f"{key}={value}" for key, value in fields.items()]
    msg = " ".join(parts)
    print(msg, flush=True)
    logger.info("%s", msg)


def _load_last_run_record(conn=None) -> Optional[Dict[str, Any]]:
    raw = get_runtime_value(RANKING_WORKER_KEY, conn=conn)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _log_startup_diagnostics(source: str, conn) -> None:
    diag = gather_db_startup_diagnostics(conn=conn)
    fields: Dict[str, Any] = {
        "source": source,
        "db_backend": diag.get("db_backend"),
    }
    if diag.get("db_path"):
        fields["db"] = diag["db_path"]
        fields["db_exists"] = str(bool(diag.get("db_exists"))).lower()
        fields["db_size_bytes"] = int(diag.get("db_size_bytes") or 0)
    fields["players"] = int(diag.get("players") or 0)
    fields["planets"] = int(diag.get("planets") or 0)
    if diag.get("migrations_readable"):
        fields["migrations"] = f"{diag.get('migrations_applied', 0)}/{diag.get('migrations_total', 0)}"
        fields["migrations_current"] = str(bool(diag.get("migrations_current"))).lower()
    elif diag.get("migrations_error"):
        fields["migrations_error"] = diag["migrations_error"]
    _log_worker_event("start", **fields)


def get_ranking_worker_status(conn=None) -> Dict[str, Any]:
    raw = get_runtime_value(RANKING_WORKER_KEY, conn=conn)
    if not raw:
        out = _empty_worker_status()
        out["next_run_in_sec"] = 0
        return out
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        out = _empty_worker_status()
        out["ok"] = False
        out["parse_error"] = True
        return out

    errors = list(data.get("errors") or [])
    at = data.get("at")
    next_in = seconds_until_ranking_worker_allowed(conn=conn)
    return {
        "last_run_at": at,
        "last_run_source": data.get("source"),
        "ok": data.get("ok"),
        "players_updated": int(data.get("players_updated") or 0),
        "ranks_assigned": int(data.get("ranks_assigned") or 0),
        "duration_ms": int(data.get("duration_ms") or 0),
        "errors": errors,
        "errors_count": len(errors),
        "skipped_interval": bool(data.get("skipped_interval")),
        "next_run_in_sec": max(0, int(next_in)),
    }


def seconds_until_ranking_worker_allowed(
    *,
    now: Optional[float] = None,
    conn=None,
) -> float:
    """Seconds until the next scheduled worker run is allowed (0 = ready)."""
    data = _load_last_run_record(conn=conn)
    if not data:
        return 0.0
    if not data.get("ok"):
        return 0.0
    try:
        last_at = float(data.get("at") or 0)
    except (TypeError, ValueError):
        return 0.0
    if last_at <= 0:
        return 0.0
    now_f = float(now if now is not None else time.time())
    remaining = (last_at + RANKING_WORKER_INTERVAL_SEC) - now_f
    return max(0.0, remaining)


def record_ranking_worker_result(result: Dict[str, Any], *, source: str, conn=None) -> None:
    payload = {
        "at": int(time.time()),
        "source": str(source or "cron"),
        "ok": bool(result.get("ok", True)),
        "players_updated": int(result.get("players_updated") or 0),
        "ranks_assigned": int(result.get("ranks_assigned") or 0),
        "duration_ms": int(result.get("duration_ms") or 0),
        "errors": list(result.get("errors") or []),
        "skipped_interval": bool(result.get("skipped_interval")),
    }
    set_runtime_value(RANKING_WORKER_KEY, json.dumps(payload, ensure_ascii=False), conn=conn)


def _gather_counts(conn) -> Dict[str, int]:
    return {
        "players": count_table_rows(conn, "players"),
        "planets": count_table_rows(conn, "planets"),
    }


def run_ranking_worker(
    *,
    source: str = "cron",
    force: bool = False,
    persist: bool = True,
    allow_empty: bool = False,
) -> Dict[str, Any]:
    """
    Recompute all player scores and rank columns. Intended for cron every 10 minutes.

    When force=False, skips if the last successful run was within RANKING_WORKER_INTERVAL_SEC.
    """
    started = time.perf_counter()
    conn = db()
    try:
        _log_startup_diagnostics(source, conn)
        counts = _gather_counts(conn)
        before_stats = gather_score_stats(conn)
        players = int(counts["players"])
        planets = int(counts["planets"])

        if players == 0 and planets == 0 and not allow_empty:
            duration_ms = int((time.perf_counter() - started) * 1000)
            result = {
                "ok": False,
                "skipped_interval": False,
                "players_updated": 0,
                "ranks_assigned": 0,
                "duration_ms": duration_ms,
                "errors": ["empty database: players=0 planets=0"],
                "players_seen": 0,
                "planets": 0,
                "scores_before": before_stats["scores_rows"],
                "scores_after": before_stats["scores_rows"],
                "scores_updated": 0,
                "top_score_before": before_stats["top_score"],
                "top_score_after": before_stats["top_score"],
            }
            _log_worker_event(
                "error",
                reason="empty_database",
                players=0,
                planets=0,
                duration_ms=duration_ms,
            )
            return result

        if not force:
            wait = seconds_until_ranking_worker_allowed(conn=conn)
            if wait > 0:
                last_run = _load_last_run_record(conn=conn) or {}
                duration_ms = int((time.perf_counter() - started) * 1000)
                skipped = {
                    "ok": True,
                    "skipped_interval": True,
                    "players_updated": 0,
                    "ranks_assigned": 0,
                    "duration_ms": duration_ms,
                    "errors": [],
                    "next_run_in_sec": int(wait),
                    "players_seen": players,
                    "planets": planets,
                    "scores_before": before_stats["scores_rows"],
                    "scores_after": before_stats["scores_rows"],
                    "scores_updated": 0,
                    "top_score_before": before_stats["top_score"],
                    "top_score_after": before_stats["top_score"],
                }
                _log_worker_event(
                    "skip",
                    reason="guard_recent",
                    last_run=int(last_run.get("at") or 0),
                    last_source=last_run.get("source") or "unknown",
                    wait_sec=int(wait),
                    duration_ms=duration_ms,
                )
                return skipped

        result = recalculate_all_rankings(refresh_scores=True, conn=conn)
        conn.commit()

        after_stats = gather_score_stats(conn)
        result["skipped_interval"] = False
        result.setdefault("errors", [])
        result["players_seen"] = players
        result["planets"] = planets
        result["scores_before"] = before_stats["scores_rows"]
        result["scores_after"] = after_stats["scores_rows"]
        result["scores_updated"] = int(result.get("players_updated") or 0)
        result["top_score_before"] = before_stats["top_score"]
        result["top_score_after"] = after_stats["top_score"]

        if result.get("ok"):
            _log_worker_event(
                "success",
                updated_players=int(result.get("players_updated") or 0),
                ranks_assigned=int(result.get("ranks_assigned") or 0),
                duration_ms=int(result.get("duration_ms") or 0),
            )
        else:
            _log_worker_event(
                "error",
                updated_players=int(result.get("players_updated") or 0),
                duration_ms=int(result.get("duration_ms") or 0),
                errors=";".join(result.get("errors") or []),
            )

        if persist and result.get("ok") and not result.get("skipped_interval"):
            record_ranking_worker_result(result, source=source, conn=conn)
            conn.commit()

        return result
    except Exception as exc:
        logger.exception("ranking worker failed")
        try:
            conn.rollback()
        except Exception:
            pass
        duration_ms = int((time.perf_counter() - started) * 1000)
        _log_worker_event("error", message=str(exc), duration_ms=duration_ms)
        return {
            "ok": False,
            "skipped_interval": False,
            "players_updated": 0,
            "ranks_assigned": 0,
            "duration_ms": duration_ms,
            "errors": [str(exc)],
        }
    finally:
        conn.close()


def worker_exit_code(result: Dict[str, Any], *, allow_empty: bool) -> int:
    if not result.get("ok"):
        return 1
    if result.get("skipped_interval"):
        return 0
    players = int(result.get("players_seen") or 0)
    planets = int(result.get("planets") or 0)
    if players == 0 and planets == 0 and not allow_empty:
        return 1
    if players > 0 and int(result.get("scores_updated") or 0) == 0:
        return 1
    return 0


def _cli_main() -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Genesis Colonies ranking worker")
    parser.add_argument("--source", default="cli")
    parser.add_argument("--force", action="store_true", help="Ignore 10-minute interval guard")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Allow run when players=0 and planets=0 (default: exit 1)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from game.bootstrap import bootstrap_application
    from game.config import init_config, is_production

    init_config()

    if is_production():
        from game.db import get_db_backend, resolve_db_path

        if get_db_backend() == "sqlite":
            db_path = resolve_db_path()
            if not db_path.exists():
                _worker_log(f"fatal: production db file missing path={db_path}")
                _worker_log("exit=1")
                return 1

    skip_mig = os.environ.get("GC_SKIP_MIGRATION_CHECK", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    bootstrap_application(skip_migration_check=skip_mig)

    _worker_log(f"cli_env app_env={os.environ.get('APP_ENV') or os.environ.get('FLASK_ENV') or 'development'}")

    try:
        result = run_ranking_worker(
            source=args.source,
            force=bool(args.force),
            persist=not args.no_persist,
            allow_empty=bool(args.allow_empty),
        )
    except Exception as exc:
        logger.exception("ranking worker failed")
        _worker_log(f"exit=1 error={exc}")
        return 1

    if result.get("skipped_interval"):
        _worker_log(f"skipped_interval next_run_in_sec={result.get('next_run_in_sec')}")
    elif result.get("ok"):
        _worker_log(
            f"scores_updated={result.get('scores_updated', result.get('players_updated'))} "
            f"scores_after={result.get('scores_after', '')} "
            f"top_score_after={result.get('top_score_after', '')}"
        )

    if result.get("errors"):
        for err in result["errors"]:
            _worker_log(f"error={err}")

    code = worker_exit_code(result, allow_empty=bool(args.allow_empty))
    _worker_log(f"exit={code}")
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(_cli_main())
