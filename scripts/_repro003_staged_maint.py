#!/usr/bin/env python3
"""REPRO-003 helper: timed maintenance stages (no production code changes).

Runs against GC_DB_PATH using whatever `game` is first on PYTHONPATH (historical
worktree or current branch). Prints one JSON object to stdout.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Prefer PYTHONPATH-injected tree; fall back to this repo.
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


def _norm_runtime(conn) -> None:
    """Identical ranking cadence for A/B/C: avoid first-run full reconcile."""
    from game.ranking_worker import FULL_RECONCILE_KEY, BUSY_KEY
    from game.runtime_state import set_runtime_value

    now = time.time()
    set_runtime_value(FULL_RECONCILE_KEY, str(now), conn=conn)
    set_runtime_value(BUSY_KEY, "0", conn=conn)
    conn.commit()


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "all").strip().lower()
    # modes: all | no_ranking | no_fleet | ranking_only | fleet_only | normalize_only
    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")
    os.environ["GC_MAINTENANCE_WORKER"] = "1"
    os.environ["GC_EMBEDDED_CRON"] = "0"

    from game.bootstrap import bootstrap_application
    from game.db import db
    from game.internal_cron import (
        execute_fleet_tick,
        execute_ranking_recompute,
        maybe_sqlite_volume_backup,
        record_maintenance_bag_heartbeat,
    )

    bootstrap_application(skip_migration_check=True)
    conn = db()
    try:
        _norm_runtime(conn)
    finally:
        conn.close()

    if mode == "normalize_only":
        print(json.dumps({"ok": True, "mode": mode}))
        return 0

    stages = []
    ranking_payload = None
    fleet_payload = None

    def _time(name: str, fn):
        t0 = time.perf_counter()
        err = None
        result = None
        try:
            result = fn()
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = f"{type(exc).__name__}: {exc}"
            result = {"ok": False, "error": err}
        ms = (time.perf_counter() - t0) * 1000.0
        stages.append(
            {
                "stage": name,
                "duration_ms": round(ms, 2),
                "ok": ok,
                "error": err,
                "result_keys": sorted(result.keys()) if isinstance(result, dict) else [],
                "summary": _summarize_payload(name, result) if isinstance(result, dict) else {},
            }
        )
        return result

    def _summarize_payload(name: str, payload: dict) -> dict:
        out = {
            "ok": payload.get("ok"),
            "mode": payload.get("mode"),
            "skipped_interval": payload.get("skipped_interval"),
            "duration_ms": payload.get("duration_ms"),
            "players_updated": payload.get("players_updated"),
            "dirty_cleared": payload.get("dirty_cleared"),
            "ranks_assigned": payload.get("ranks_assigned"),
        }
        if name == "fleet":
            # Surface nested post-maint hints if present
            for key in ("post_maint", "stages", "hold_ms", "source"):
                if key in payload:
                    out[key] = payload.get(key)
        if name == "sqlite_backup":
            out["ran"] = payload.get("ran") or payload.get("copied") or payload.get("skipped")
            out["bytes"] = payload.get("bytes") or payload.get("size")
        return {k: v for k, v in out.items() if v is not None}

    if mode in ("all", "no_fleet", "ranking_only"):
        ranking_payload = _time(
            "ranking",
            lambda: execute_ranking_recompute(force=False, source="repro003"),
        )
    if mode in ("all", "no_ranking", "fleet_only"):
        fleet_payload = _time(
            "fleet",
            # force=True so interval skip does not hide fleet cost in attribution runs
            lambda: execute_fleet_tick(force=True, source="repro003"),
        )
    if mode in ("all", "no_ranking", "no_fleet"):
        def _deletions():
            from game.options import maybe_run_due_account_deletions

            return maybe_run_due_account_deletions(force=False, source="repro003")

        def _privacy():
            from game.privacy_retention import maybe_run_privacy_retention_purge

            return maybe_run_privacy_retention_purge(force=False, source="repro003")

        _time("account_deletions", _deletions)
        _time("privacy_retention", _privacy)
        _time("sqlite_backup", lambda: maybe_sqlite_volume_backup(force=False))

    # Heartbeat from last ranking-like payload when available
    hb_payload = ranking_payload if isinstance(ranking_payload, dict) else {"ok": True, "mode": "n/a"}
    _time("heartbeat", lambda: record_maintenance_bag_heartbeat(hb_payload, source="repro003") or {"ok": True})

    total = round(sum(s["duration_ms"] for s in stages), 2)
    print(
        json.dumps(
            {
                "ok": True,
                "mode": mode,
                "total_ms": total,
                "stages": stages,
                "longest_stage": max(stages, key=lambda s: s["duration_ms"])["stage"] if stages else None,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
