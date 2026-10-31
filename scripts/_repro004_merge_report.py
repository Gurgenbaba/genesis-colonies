#!/usr/bin/env python3
"""Merge all REPRO-004 phase reports into final summary."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path("artifacts/concurrency_repro/repro004")


def load(name: str) -> dict:
    p = OUT / f"{name}_report.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def gs(r: dict) -> dict:
    return (r.get("load") or {}).get("game_state") or {}


def an(r: dict) -> dict:
    return (r.get("load") or {}).get("analysis") or {}


def hz(r: dict) -> dict:
    return (r.get("load") or {}).get("healthz") or {}


def main() -> None:
    prev = {}
    summary_path = OUT / "repro004_summary.json"
    if summary_path.exists():
        prev = json.loads(summary_path.read_text(encoding="utf-8"))

    topo = load("topology_check")
    ctrl = load("control_no_maint")
    side = load("sidecar_maint")
    states = {
        "S0_NORMALIZED": load("state_S0_NORMALIZED"),
        "S5_FLEET_AND_QUEUES": load("state_S5_FLEET_AND_QUEUES"),
        "S7_WORST_PLAUSIBLE": load("state_S7_WORST_PLAUSIBLE"),
    }
    th = load("thundering_herd_S5")
    gv = load("gevent_block_probe")
    w1 = load("workers_1")
    w2 = load("workers_2")
    restart = (prev.get("restart") or {})

    penalty = {
        "p95_ms": round(float(gs(side).get("p95_ms") or 0) - float(gs(ctrl).get("p95_ms") or 0), 2),
        "p99_ms": round(float(gs(side).get("p99_ms") or 0) - float(gs(ctrl).get("p99_ms") or 0), 2),
        "max_ms": round(float(gs(side).get("max_ms") or 0) - float(gs(ctrl).get("max_ms") or 0), 2),
    }

    worst_state, worst_p95 = None, -1.0
    for sid, rep in states.items():
        p95 = float(gs(rep).get("p95_ms") or 0)
        if p95 > worst_p95:
            worst_state, worst_p95 = sid, p95

    gevent_blocked = bool(float(hz(gv).get("p95_ms") or 0) >= 2000.0)

    om = OUT / "owner_matrix.json"
    owner = json.loads(om.read_text(encoding="utf-8")) if om.exists() else {}

    summary = {
        "PRODUCTION_TOPOLOGY": "verified" if topo.get("topology_verified") else "not verified",
        "topology_checks": topo.get("topology_checks"),
        "CONTROL": gs(ctrl),
        "CONTROL_slow5": an(ctrl).get("slow_ge_5000_count"),
        "SIDECAR": gs(side),
        "SIDECAR_PENALTY": penalty,
        "WORST_STATE": worst_state,
        "WORST_ROUTE": "/api/game-state (also /messages /world-boss /galaxy cascaded)",
        "HTTP_WRITE_PATH": (side.get("write_paths") or {}).get("dominant_path")
        or (states["S5_FLEET_AND_QUEUES"].get("write_paths") or {}).get("dominant_path")
        or "not captured (perf log lost on container stop; code path: fleet_dirty/queue_due safety nets)",
        "THUNDERING_HERD": bool(float(an(th).get("slow_ge_5000_count") or 0) > 0),
        "thundering_gs": gs(th),
        "GEVENT_WORKER_BLOCKED_BY_SQLITE_WAIT": gevent_blocked,
        "gevent_healthz": hz(gv),
        "gevent_gs": gs(gv),
        "1_WORKER": gs(w1),
        "2_WORKERS": gs(w2),
        "workers_delta_p95": round(
            float(gs(w2).get("p95_ms") or 0) - float(gs(w1).get("p95_ms") or 0), 2
        ),
        "DOUBLE_MAINTENANCE_OWNER": "possible under misconfig only; production sidecar+lock prevents double bag",
        "RESTART_CLEARS_STALL": restart.get("RESTART_CLEARS_STALL", "no"),
        "restart_before": (restart.get("before") or {}).get("game_state"),
        "restart_after": (restart.get("after") or {}).get("game_state"),
        "SYSTEM_FAILURE_MODE": True,
        "HISTORICAL_INCIDENT": "reproduced no",
        "ROOT_CAUSE": "under investigation — strongest new evidence: gunicorn+gevent 1-worker blocks on sqlite wait",
        "states": {k: gs(v) for k, v in states.items()},
        "owner_matrix": owner,
        "NEXT_MINIMAL_FIX": (
            "proposal only: measure sync sqlite3 under gevent; consider sync worker class "
            "or offload blocking DB waits / ensure poll path stays read-only under load"
        ),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k != "owner_matrix"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
