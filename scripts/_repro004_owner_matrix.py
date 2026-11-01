#!/usr/bin/env python3
"""Static owner matrix for maintenance / fleet / ranking triggers (REPRO-004)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Curated from code audit — not exhaustive runtime proof.
OWNER_MATRIX = [
    {
        "owner": "run_maintenance_bag",
        "process": "maintenance sidecar OR embedded cron OR http cron",
        "trigger": "run_maintenance_worker_loop / _embedded_cron_loop / POST /api/internal/cron/ranking",
        "write": True,
        "interval_guard": "ranking/fleet/vote interval guards inside bag",
        "notes": "Canonical bag orchestrator",
    },
    {
        "owner": "execute_ranking_recompute",
        "process": "via run_maintenance_bag",
        "trigger": "bag stage ranking",
        "write": True,
        "interval_guard": "ranking worker interval + full reconcile cadence",
        "notes": "Can full-reconcile when due",
    },
    {
        "owner": "execute_fleet_tick / run_fleet_worker",
        "process": "via run_maintenance_bag or http fleet cron",
        "trigger": "bag stage fleet / POST /api/internal/cron/fleet-tick",
        "write": True,
        "interval_guard": "fleet worker interval",
        "notes": "Post-maint stages split in fleet_worker",
    },
    {
        "owner": "start_embedded_cron_if_enabled",
        "process": "gunicorn web (in-process thread)",
        "trigger": "app bootstrap when GC_EMBEDDED_CRON=1 and GC_MAINTENANCE_WORKER=0",
        "write": True,
        "interval_guard": "disabled when sidecar owns bag",
        "notes": "Logs disabled_sidecar_owns_bag in prod topology",
    },
    {
        "owner": "read_player_live_state_for_poll",
        "process": "gunicorn web",
        "trigger": "GET /api/game-state (+ SSR live refresh)",
        "write": "conditional",
        "interval_guard": "queue poll finish interval; fleet_dirty immediate",
        "notes": "Safety-net writes on poll when due/dirty",
    },
    {
        "owner": "finish_player_due_work / finish_due_work_once",
        "process": "gunicorn web + workers",
        "trigger": "game_state poll, page loads, actions",
        "write": True,
        "interval_guard": "queue_poll throttling",
        "notes": "Per-player short write txs",
    },
    {
        "owner": "process_fleet_tick",
        "process": "gunicorn web + fleet worker",
        "trigger": "fleet_dirty on poll; fleet worker cron",
        "write": True,
        "interval_guard": "dedup in fleet paths",
        "notes": "HTTP path when fleet dirty",
    },
    {
        "owner": "maybe_sqlite_volume_backup",
        "process": "maintenance bag only",
        "trigger": "bag stage sqlite_backup",
        "write": True,
        "interval_guard": "skip if backup exists today",
        "notes": "161MB copy can hold writer seconds",
    },
    {
        "owner": "POST /api/internal/cron/*",
        "process": "gunicorn web",
        "trigger": "Bearer GC_INTERNAL_CRON_TOKEN",
        "write": True,
        "interval_guard": "manual/ops only",
        "notes": "Can run full bag via ranking endpoint",
    },
    {
        "owner": "run_ranking_worker.py / run_fleet_worker.py",
        "process": "standalone scripts",
        "trigger": "manual CLI",
        "write": True,
        "interval_guard": "script-specific",
        "notes": "Not production default path",
    },
]


def main() -> int:
    out = ROOT / "artifacts/concurrency_repro/repro004/owner_matrix.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "double_maintenance_owner_possible": (
            "Theoretically yes if GC_MAINTENANCE_WORKER=0 AND GC_EMBEDDED_CRON=1 "
            "while also hitting http cron — production config sets sidecar ON + embedded OFF. "
            "Leader lock file (.gc_embedded_cron.lock) prevents double bag between sidecar and embedded."
        ),
        "production_intended": {
            "sidecar": "ON (GC_MAINTENANCE_WORKER=1)",
            "embedded_cron": "OFF (GC_EMBEDDED_CRON=0)",
        },
        "owners": OWNER_MATRIX,
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
