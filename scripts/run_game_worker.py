#!/usr/bin/env python3
"""
GC-PERF-WORKER-001 — long-running game worker loop.

Default/manual mode preserves the historical queue+fleet cron behavior.
Production PostgreSQL uses ``--queue-only``: due economy queues are completed in
this sidecar while fleet/World-Boss/post-maint remain owned by the separate
maintenance worker. This keeps `/api/game-state` out of the queue-finish write
path without multiplying the maintenance cadence.

Examples:
  python scripts/run_game_worker.py
  python scripts/run_game_worker.py --interval 5 --queue-only
  python scripts/run_game_worker.py --once --queue-only

Set GC_GAME_WORKER_PRIMARY=1 on web processes so polls only keep the stale-worker
safety net. PostgreSQL is the intended side-by-side production backend.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _default_interval() -> float:
    raw = os.environ.get("GC_GAME_WORKER_SEC", "").strip()
    try:
        return max(2.0, float(raw)) if raw else 5.0
    except (TypeError, ValueError):
        return 5.0


def _queue_heartbeat_interval(interval: float) -> float:
    """Persist liveness less often than the 5s due-work scan.

    The HTTP safety net treats the queue worker as stale only after a much larger
    window. A 15s idle heartbeat keeps plenty of headroom while cutting the
    steady-state runtime_state upsert rate by roughly two thirds. Real work and
    errors are persisted immediately.
    """
    raw = os.environ.get("GC_GAME_WORKER_HEARTBEAT_SEC", "").strip()
    try:
        requested = float(raw) if raw else 15.0
    except (TypeError, ValueError):
        requested = 15.0
    requested = min(30.0, max(5.0, requested))
    return max(float(interval), requested)


def _queue_tick_has_activity(result: Mapping[str, Any]) -> bool:
    if not bool(result.get("ok", True)) or bool(result.get("errors")):
        return True
    if int(result.get("players_processed") or 0) > 0:
        return True
    finished = result.get("finished") or {}
    if isinstance(finished, Mapping):
        return any(int(value or 0) > 0 for value in finished.values())
    return False


def _should_persist_queue_heartbeat(
    result: Mapping[str, Any],
    *,
    now_mono: float,
    last_persist_mono: float,
    heartbeat_sec: float,
) -> bool:
    if _queue_tick_has_activity(result):
        return True
    if float(last_persist_mono) <= 0:
        return True
    return (float(now_mono) - float(last_persist_mono)) >= float(heartbeat_sec)


def main() -> int:
    parser = argparse.ArgumentParser(description="Genesis Colonies game worker loop")
    parser.add_argument(
        "--interval",
        type=float,
        default=_default_interval(),
        help="Seconds between ticks (production queue-only default: 5)",
    )
    parser.add_argument("--once", action="store_true", help="Run a single tick then exit")
    parser.add_argument("--source", type=str, default="game_worker", help="Tick source label")
    parser.add_argument(
        "--queue-only",
        action="store_true",
        help="Finish due queues only; do not run global fleet/post-maint or inbox retention tail",
    )
    args = parser.parse_args()

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    interval = max(2.0, float(args.interval))
    heartbeat_sec = _queue_heartbeat_interval(interval)
    last_persist_mono = 0.0
    persist_queue_result = None

    if args.queue_only:
        from game.runtime_state import record_queue_tick_result
        from game.tick_runner import run_tick

        def _tick():
            # Queue completion cadence stays 5s, but idle liveness persistence is
            # throttled below so this sidecar does not write runtime_state every scan.
            return run_tick(
                scope="due",
                source=str(args.source or "queue_worker"),
                persist=False,
                update_scores=True,
                recalc_ranks=False,
                include_fleet_tail=False,
                include_inbox_retention=False,
            )

        persist_queue_result = record_queue_tick_result
        log_prefix = "queue-worker"
    else:
        from game.internal_cron import execute_queue_tick

        def _tick():
            return execute_queue_tick(force=True, source=args.source)

        log_prefix = "game-worker"

    start_extra = (
        f" heartbeat_sec={heartbeat_sec:.1f}"
        if args.queue_only
        else ""
    )
    print(
        f"[{log_prefix}] started interval_sec={interval:.1f} "
        f"queue_only={str(bool(args.queue_only)).lower()}{start_extra}",
        flush=True,
    )

    while True:
        started = time.perf_counter()
        result = _tick()
        heartbeat_persisted = False
        if args.queue_only and persist_queue_result is not None:
            now_mono = time.monotonic()
            if _should_persist_queue_heartbeat(
                result,
                now_mono=now_mono,
                last_persist_mono=last_persist_mono,
                heartbeat_sec=heartbeat_sec,
            ):
                try:
                    persist_queue_result(result)
                    last_persist_mono = now_mono
                    heartbeat_persisted = True
                except Exception as exc:
                    # Queue execution already succeeded; telemetry persistence is
                    # fail-open and will be retried on the next 5s scan.
                    print(
                        f"[{log_prefix}] heartbeat persist failed: {exc}",
                        flush=True,
                    )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        finished = result.get("finished") or {}
        heartbeat_extra = (
            f" heartbeat={1 if heartbeat_persisted else 0}"
            if args.queue_only
            else ""
        )
        print(
            f"[{log_prefix}] ok={str(bool(result.get('ok'))).lower()} "
            f"players={int(result.get('players_processed') or 0)} "
            f"buildings={int(finished.get('buildings') or 0)} "
            f"research={int(finished.get('research') or 0)} "
            f"shipyard={int(finished.get('shipyard') or 0)} "
            f"defense={int(finished.get('defense') or 0)} "
            f"troops={int(finished.get('troops') or 0)} "
            f"duration_ms={elapsed_ms}{heartbeat_extra}",
            flush=True,
        )
        if args.once:
            return 0 if result.get("ok") else 1
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
