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
# Railway production uses embedded_cron (maintenance bag); must be allowlisted or autoplay never runs.
_BACKGROUND_MAINTENANCE_SOURCES = frozenset(
    {
        "cron",
        "http_cron",
        "fleet_cron",
        "internal_cron",
        "ranking_cron",
        "embedded_cron",
        "game_worker",
        "maintenance_worker",  # GC-PERF-PROD-002 sidecar process
    }
)


def _is_background_maintenance_source(source: str) -> bool:
    return str(source or "").strip().lower() in _BACKGROUND_MAINTENANCE_SOURCES


def _stage_skip_streak_key(stage: str) -> str:
    return f"post_maint_skip_streak_{stage}"


def get_stage_skip_streak(stage: str, *, conn=None) -> int:
    """Consecutive budget-skips since the last successful run of `stage` (GC-2610)."""
    try:
        raw = get_runtime_value(_stage_skip_streak_key(stage), conn=conn)
        return max(0, int(raw or 0))
    except Exception:
        return 0


def _record_stage_skip(conn, stage: str) -> None:
    try:
        streak = get_stage_skip_streak(stage, conn=conn) + 1
        set_runtime_value(_stage_skip_streak_key(stage), str(streak), conn=conn)
    except Exception:
        logger.exception("post-maint skip-streak persist failed stage=%s", stage)


def _record_stage_success(conn, stage: str) -> None:
    try:
        set_runtime_value(_stage_skip_streak_key(stage), "0", conn=conn)
    except Exception:
        logger.exception("post-maint skip-streak reset failed stage=%s", stage)


def _maybe_run_post_fleet_maintenance(conn, *, source: str) -> None:
    """
    HoF catch-up and combat-balance bot scheduler.

    Runs only on cron sources with the fleet worker connection — never opens a
    second writer during live page loads (SQLite lock safety).

    Stages commit separately so one long pirate play-loop cannot hold
    BEGIN IMMEDIATE across the entire maintenance bag (Railway hang after idle).
    """
    if not _is_background_maintenance_source(source):
        return

    budget_sec = float(os.environ.get("GC_POST_FLEET_MAINTENANCE_BUDGET_SEC", "25"))
    started = time.perf_counter()

    def _over_budget() -> bool:
        return (time.perf_counter() - started) >= budget_sec

    def _run_stage(name: str, fn, *, manage_tx: bool = True) -> None:
        """Run one post-maint stage.

        manage_tx=True (default): wrap fn in one BEGIN IMMEDIATE — fine for
        short stages. manage_tx=False: fn owns short write transactions
        (GC-PERF-AUTOPLAY-001 inactive_autoplay) so HTTP writers are not blocked
        for the entire multi-player economy pass.
        """
        if _over_budget():
            _worker_log(f"post-maint skip={name} budget_sec={budget_sec}")
            try:
                begin_write_transaction(conn)
                try:
                    _record_stage_skip(conn, name)
                    commit(conn)
                except Exception:
                    rollback(conn)
                    raise
            except Exception:
                logger.exception(
                    "post fleet maintenance skip-streak failed source=%s stage=%s", source, name
                )
            return
        stage_t0 = time.perf_counter()
        try:
            if not manage_tx:
                fn()
                begin_write_transaction(conn)
                try:
                    _record_stage_success(conn, name)
                    commit(conn)
                except Exception:
                    rollback(conn)
                    raise
            else:
                begin_write_transaction(conn)
                try:
                    fn()
                    _record_stage_success(conn, name)
                    commit(conn)
                except Exception:
                    rollback(conn)
                    raise
            hold_ms = (time.perf_counter() - stage_t0) * 1000.0
            _worker_log(
                f"post-maint stage={name} hold_ms={hold_ms:.0f} manage_tx={int(manage_tx)}"
            )
        except Exception:
            logger.exception("post fleet maintenance stage failed source=%s stage=%s", source, name)

    try:
        def _hof() -> None:
            from .combat_hof import maybe_sync_combat_hof_incremental

            hof_sync = maybe_sync_combat_hof_incremental(conn=conn)
            if hof_sync.get("inserted"):
                _worker_log(f"hof-sync inserted={hof_sync.get('inserted')}")

        def _combat_bots() -> None:
            from .combat_balance_bots import maybe_run_next_scheduled_scenario

            bot_result = maybe_run_next_scheduled_scenario(conn=conn)
            if bot_result.get("ok") and bot_result.get("fleet_movement_id"):
                _worker_log(
                    f"combat-bots scenario={bot_result.get('scenario_key')} "
                    f"fleet={bot_result.get('fleet_movement_id')}"
                )

        def _world_boss() -> None:
            from .world_boss import maybe_tick_world_boss_schedule

            wb_tick = maybe_tick_world_boss_schedule(conn=conn)
            auto = wb_tick.get("auto_attack") or {}
            if (
                wb_tick.get("expired_ids")
                or wb_tick.get("spawned_event_id")
                or int(auto.get("fired") or 0) > 0
                or int(auto.get("stopped") or 0) > 0
            ):
                _worker_log(
                    f"world-boss expired={wb_tick.get('expired_ids')} "
                    f"spawned={wb_tick.get('spawned_event_id')} "
                    f"auto_fired={auto.get('fired')} auto_stopped={auto.get('stopped')}"
                )

        def _asteroids() -> None:
            from .asteroids import maybe_tick_asteroid_schedule

            ast_tick = maybe_tick_asteroid_schedule(conn=conn)
            if ast_tick.get("expired_ids") or ast_tick.get("spawned"):
                _worker_log(
                    f"asteroids expired={ast_tick.get('expired_ids')} "
                    f"spawned={len(ast_tick.get('spawned') or [])}"
                )

        def _pirates() -> None:
            from .pirates.bases import maybe_tick_pirate_bases

            pirate_tick = maybe_tick_pirate_bases(conn=conn)
            play = pirate_tick.get("play_loop") or {}
            if (
                pirate_tick.get("expired_ids")
                or pirate_tick.get("escalated_ids")
                or pirate_tick.get("spawned")
                or play.get("count")
                or play.get("economy_ok")
                or pirate_tick.get("write_commits")
            ):
                _worker_log(
                    f"pirates expired={pirate_tick.get('expired_ids')} "
                    f"escalated={pirate_tick.get('escalated_ids')} "
                    f"spawned={pirate_tick.get('spawned')} "
                    f"play_steps={play.get('count')} "
                    f"play_active={play.get('active')} "
                    f"economy_ok={play.get('economy_ok')} "
                    f"write_commits={pirate_tick.get('write_commits') or play.get('write_commits')} "
                    f"hold_ms={pirate_tick.get('hold_ms') or play.get('hold_ms')} "
                    f"error={play.get('error')}"
                )

        def _inactive_autoplay() -> None:
            from .inactive_autoplay import maybe_tick_inactive_autoplay

            ia = maybe_tick_inactive_autoplay(conn, source="fleet_worker")
            if (
                ia.get("woke_count")
                or ia.get("enqueued")
                or ia.get("session_ticks")
                or ia.get("error")
                or ia.get("hold_ms")
            ):
                _worker_log(
                    f"inactive_autoplay woke={ia.get('woke_count')} "
                    f"roster={ia.get('roster_size') or ia.get('active_sessions')} "
                    f"enqueued={ia.get('enqueued')} "
                    f"ticks={ia.get('session_ticks')} "
                    f"hold_ms={ia.get('hold_ms')} "
                    f"write_commits={ia.get('write_commits')} "
                    f"error={ia.get('error')}"
                )

        def _debris() -> None:
            from .combat import expire_due_debris_fields

            debris_expired = expire_due_debris_fields(conn=conn)
            if debris_expired:
                _worker_log(f"debris expired={debris_expired}")

        _run_stage("hof", _hof)
        _run_stage("combat_bots", _combat_bots)
        _run_stage("world_boss", _world_boss)
        _run_stage("asteroids", _asteroids)
        # GC-2610: inactive_autoplay before pirates — pirate economy-for-all-bots is
        # the most expensive stage and must not starve inactive accounts of budget.
        # GC-PERF-AUTOPLAY-001 / GC-PERF-TK-001: both heavy stages manage short
        # write transactions themselves so Timekeeper/live HTTP can interleave.
        _run_stage("inactive_autoplay", _inactive_autoplay, manage_tx=False)
        _run_stage("pirates", _pirates, manage_tx=False)
        _run_stage("debris", _debris)
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
            # Auto-attack must not wait on fleet arrivals — cheap tick even when idle-skipped.
            auto_attack: Dict[str, Any] = {}
            try:
                from .world_boss import tick_world_boss_auto_attacks

                begin_write_transaction(conn)
                try:
                    auto_attack = tick_world_boss_auto_attacks(conn=conn)
                    commit(conn)
                except Exception:
                    rollback(conn)
                    raise
                if int(auto_attack.get("fired") or 0) > 0 or int(auto_attack.get("stopped") or 0) > 0:
                    _worker_log(
                        f"world-boss auto (idle-skip) fired={auto_attack.get('fired')} "
                        f"stopped={auto_attack.get('stopped')}"
                    )
            except Exception:
                logger.exception("world_boss auto tick on skipped_interval failed")
                auto_attack = {"ok": False, "error": "tick_failed"}
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
                "auto_attack": auto_attack,
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

        # GC-PERF-LOCK-001: no mega-IMMEDIATE around all due fleets — process_fleet_tick
        # owns short per-movement write TXs so HTTP (touch_player_online) can interleave.
        tick_result = process_fleet_tick(
            player_id=None, conn=conn, manage_transaction=True
        )

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
                begin_write_transaction(conn)
                record_fleet_worker_result(result, source=source, conn=conn)
                commit(conn)
            except Exception:
                try:
                    rollback(conn)
                except Exception:
                    pass
                logger.exception("record_fleet_worker_result failed")
        _worker_log(
            f"source={source} arrivals={result['processed_arrivals']} "
            f"holding={result['processed_holding']} returns={result['processed_returns']} "
            f"duration_ms={duration_ms}"
        )
        return result
    except Exception as exc:
        try:
            rollback(conn)
        except Exception:
            pass
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
                begin_write_transaction(conn)
                record_fleet_worker_result(result, source=source, conn=conn)
                commit(conn)
            except Exception:
                try:
                    rollback(conn)
                except Exception:
                    pass
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
