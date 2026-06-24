"""
Background ranking worker — batch score + rank refresh (cron / CLI).

Gameplay paths must not call compute_player_scores(); only this worker (or admin
force-recalc) updates player_scores on a schedule.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

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
    raw = get_runtime_value(RANKING_WORKER_KEY, conn=conn)
    if not raw:
        return 0.0
    try:
        data = json.loads(raw)
        last_at = float(data.get("at") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
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


def run_ranking_worker(
    *,
    source: str = "cron",
    force: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """
    Recompute all player scores and rank columns. Intended for cron every 10 minutes.

    When force=False, skips if the last successful run was within RANKING_WORKER_INTERVAL_SEC.
    """
    started = time.perf_counter()

    if not force:
        wait = seconds_until_ranking_worker_allowed()
        if wait > 0:
            skipped = {
                "ok": True,
                "skipped_interval": True,
                "players_updated": 0,
                "ranks_assigned": 0,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "errors": [],
                "next_run_in_sec": int(wait),
            }
            logger.info(
                "ranking worker skipped (interval) source=%s wait_sec=%.0f",
                source,
                wait,
            )
            if persist:
                record_ranking_worker_result(skipped, source=source)
            return skipped

    logger.info("ranking worker start source=%s force=%s", source, force)
    result = recalculate_all_rankings(refresh_scores=True)
    result["skipped_interval"] = False
    result.setdefault("errors", [])
    if persist:
        record_ranking_worker_result(result, source=source)
    logger.info(
        "ranking worker done source=%s players=%s ranks=%s duration_ms=%s errors=%s",
        source,
        result.get("players_updated"),
        result.get("ranks_assigned"),
        result.get("duration_ms"),
        len(result.get("errors") or []),
    )
    return result


def _cli_main() -> int:
    import argparse
    import json
    import os
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Genesis Colonies ranking worker")
    parser.add_argument("--source", default="cli")
    parser.add_argument("--force", action="store_true", help="Ignore 10-minute interval guard")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    result = run_ranking_worker(
        source=args.source,
        force=bool(args.force),
        persist=not args.no_persist,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_cli_main())
