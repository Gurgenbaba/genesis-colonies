"""
Background fleet tick worker — process due fleet_movements for all players.

Fleet arrivals, holding end, and returns must advance while players are offline.
Gameplay polls only refresh one player; this worker runs globally on a schedule
(HTTP cron) and as a throttled safety net during authenticated live requests.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from .db import begin_write_transaction, commit, db, rollback
from .runtime_state import get_runtime_value, set_runtime_value

logger = logging.getLogger(__name__)

FLEET_WORKER_KEY = "fleet_worker_last"
FLEET_WORKER_INTERVAL_SEC = float(os.environ.get("GC_FLEET_WORKER_INTERVAL_SEC", "60"))
# Bot scheduler + HoF catch-up only on dedicated cron ticks — never during page/game-state polls.
_BACKGROUND_MAINTENANCE_SOURCES = frozenset(
    {
        "cron",
        "http_cron",
        "fleet_cron",
        "internal_cron",
        "ranking_cron",
    }
)


def _is_background_maintenance_source(source: str) -> bool:
    return str(source or "").strip().lower() in _BACKGROUND_MAINTENANCE_SOURCES


def _maybe_run_post_fleet_maintenance(conn, *, source: str) -> None:
    """
    HoF catch-up and combat-balance bot scheduler.

    Runs only on cron sources with the fleet worker connection — never opens a
    second writer during live page loads (SQLite lock safety).
    """
    if not _is_background_maintenance_source(source):
        return
    try:
        begin_write_transaction(conn)
        try:
            from .combat_hof import maybe_sync_combat_hof_incremental

            hof_sync = maybe_sync_combat_hof_incremental(conn=conn)
            if hof_sync.get("inserted"):
                _worker_log(f"hof-sync inserted={hof_sync.get('inserted')}")

            from .combat_balance_bots import maybe_run_next_scheduled_scenario

            bot_result = maybe_run_next_scheduled_scenario(conn=conn)
            if bot_result.get("ok") and bot_result.get("fleet_movement_id"):
                _worker_log(
                    f"combat-bots scenario={bot_result.get('scenario_key')} "
                    f"fleet={bot_result.get('fleet_movement_id')}"
                )

            from .world_boss import maybe_tick_world_boss_schedule

            wb_tick = maybe_tick_world_boss_schedule(conn=conn)
            if wb_tick.get("expired_ids") or wb_tick.get("spawned_event_id"):
                _worker_log(
                    f"world-boss expired={wb_tick.get('expired_ids')} "
                    f"spawned={wb_tick.get('spawned_event_id')}"
                )
            commit(conn)
        except Exception:
            rollback(conn)
            raise
    except Exception:
        logger.exception("post fleet maintenance failed source=%s", source)


def _empty_worker_status() -> Dict[str, Any]:
    return {
        "last_run_at": None,
        "last_run_source": None,
        "ok": None,
        "processed_arrivals": 0,
        "processed_returns": 0,
        "processed_holding": 0,
        "duration_ms": 0,
        "errors": [],
        "errors_count": 0,
        "skipped_interval": False,
        "next_run_in_sec": None,
    }


def _worker_log(msg: str) -> None:
    line = f"[fleet-worker] {msg}"
    print(line, flush=True)
    logger.info("%s", msg)


def _load_last_run_record(conn=None) -> Optional[Dict[str, Any]]:
    raw = get_runtime_value(FLEET_WORKER_KEY, conn=conn)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def seconds_until_fleet_worker_allowed(
    *,
    now: Optional[float] = None,
    conn=None,
) -> float:
    """Seconds until the next idle fleet worker run is allowed (0 = ready)."""
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
    remaining = (last_at + FLEET_WORKER_INTERVAL_SEC) - now_f
    return max(0.0, remaining)


def any_due_fleet_movements(
    *,
    now: Optional[float] = None,
    conn=None,
) -> bool:
    """True when any fleet movement phase is past due (all players)."""
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    ts = float(now if now is not None else time.time())
    try:
        from .fleet import fleet_schema_ready
        from .queue_poll import DUE_TIME_EPSILON_SEC

        if not fleet_schema_ready(conn):
            return False
        due_ts = ts + DUE_TIME_EPSILON_SEC
        row = conn.execute(
            """
            SELECT 1 FROM fleet_movements
            WHERE (
                (status = 'outbound' AND arrival_at <= ?)
                OR (status = 'holding' AND holding_until <= ?)
                OR (status = 'returning' AND return_at <= ?)
            )
            LIMIT 1;
            """,
            (due_ts, due_ts, due_ts),
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        if owns_conn and conn is not None:
            conn.close()


def should_run_global_fleet_tick(
    *,
    force: bool = False,
    now: Optional[float] = None,
    conn=None,
) -> bool:
    """Run when forced, when any movement is due, or on idle interval."""
    if force:
        return True
    if any_due_fleet_movements(now=now, conn=conn):
        return True
    return seconds_until_fleet_worker_allowed(now=now, conn=conn) <= 0.0


def record_fleet_worker_result(result: Dict[str, Any], *, source: str, conn=None) -> None:
    payload = {
        "at": int(time.time()),
        "source": str(source or "cron"),
        "ok": bool(result.get("ok", True)),
        "processed_arrivals": int(result.get("processed_arrivals") or 0),
        "processed_returns": int(result.get("processed_returns") or 0),
        "processed_holding": int(result.get("processed_holding") or 0),
        "duration_ms": int(result.get("duration_ms") or 0),
        "errors": list(result.get("errors") or []),
        "skipped_interval": bool(result.get("skipped_interval")),
    }
    set_runtime_value(FLEET_WORKER_KEY, json.dumps(payload, ensure_ascii=False), conn=conn)


def get_fleet_worker_status(conn=None) -> Dict[str, Any]:
    raw = get_runtime_value(FLEET_WORKER_KEY, conn=conn)
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
    next_in = seconds_until_fleet_worker_allowed(conn=conn)
    return {
        "last_run_at": data.get("at"),
        "last_run_source": data.get("source"),
        "ok": data.get("ok"),
        "processed_arrivals": int(data.get("processed_arrivals") or 0),
        "processed_returns": int(data.get("processed_returns") or 0),
        "processed_holding": int(data.get("processed_holding") or 0),
        "duration_ms": int(data.get("duration_ms") or 0),
        "errors": errors,
        "errors_count": len(errors),
        "skipped_interval": bool(data.get("skipped_interval")),
        "next_run_in_sec": max(0, int(next_in)),
    }


def run_fleet_worker(
    *,
    source: str = "cron",
    force: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """
    Process due fleet movements for all players (player_id=None).

    When force=False, skips idle runs within FLEET_WORKER_INTERVAL_SEC unless
    any movement is globally due.
    """
    started = time.perf_counter()
    conn = db()
    try:
        if not force and not should_run_global_fleet_tick(force=False, conn=conn):
            wait = seconds_until_fleet_worker_allowed(conn=conn)
            duration_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "skipped_interval": True,
                "processed_arrivals": 0,
                "processed_returns": 0,
                "processed_holding": 0,
                "duration_ms": duration_ms,
                "errors": [],
                "next_run_in_sec": max(0, int(wait)),
            }

        from .fleet import fleet_schema_ready, process_fleet_tick

        if not fleet_schema_ready(conn):
            duration_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "skipped_interval": False,
                "processed_arrivals": 0,
                "processed_returns": 0,
                "processed_holding": 0,
                "duration_ms": duration_ms,
                "errors": [],
                "schema_not_ready": True,
            }

        begin_write_transaction(conn)
        tick_result = process_fleet_tick(player_id=None, conn=conn)
        commit(conn)

        _maybe_run_post_fleet_maintenance(conn, source=source)

        duration_ms = int((time.perf_counter() - started) * 1000)
        result = {
            "ok": not bool(tick_result.get("errors")),
            "skipped_interval": False,
            "processed_arrivals": int(tick_result.get("processed_arrivals") or 0),
            "processed_returns": int(tick_result.get("processed_returns") or 0),
            "processed_holding": int(tick_result.get("processed_holding") or 0),
            "duration_ms": duration_ms,
            "errors": list(tick_result.get("errors") or []),
        }

        if persist:
            try:
                record_fleet_worker_result(result, source=source, conn=conn)
            except Exception:
                logger.exception("record_fleet_worker_result failed")
        _worker_log(
            f"source={source} arrivals={result['processed_arrivals']} "
            f"holding={result['processed_holding']} returns={result['processed_returns']} "
            f"duration_ms={duration_ms}"
        )
        return result
    except Exception as exc:
        rollback(conn)
        duration_ms = int((time.perf_counter() - started) * 1000)
        result = {
            "ok": False,
            "skipped_interval": False,
            "processed_arrivals": 0,
            "processed_returns": 0,
            "processed_holding": 0,
            "duration_ms": duration_ms,
            "errors": [str(exc)],
        }
        if persist:
            try:
                record_fleet_worker_result(result, source=source, conn=conn)
            except Exception:
                logger.exception("record_fleet_worker_result failed")
        logger.exception("run_fleet_worker failed source=%s", source)
        return result
    finally:
        conn.close()


def maybe_run_global_fleet_tick(
    *,
    force: bool = False,
    source: str = "request",
) -> Optional[Dict[str, Any]]:
    """
    Best-effort global fleet tick for live requests / cron piggyback.

    Never raises — request paths must stay resilient.
    """
    try:
        return run_fleet_worker(force=force, source=source, persist=True)
    except Exception:
        logger.exception("maybe_run_global_fleet_tick failed source=%s", source)
        return None
