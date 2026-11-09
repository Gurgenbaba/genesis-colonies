#!/usr/bin/env python3
"""Merge REPRO-005 phase artifacts into final summary (preserve micro causality)."""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path("artifacts/concurrency_repro/repro005")


def _load_json(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def main() -> None:
    # Prefer dedicated micro snapshot if present; else current summary may have it.
    current = _load_json(OUT / "repro005_summary.json") or {}
    micro_backup = _load_json(OUT / "micro_snapshot.json")
    if micro_backup:
        micro = micro_backup.get("micro") or micro_backup
        causality = micro_backup.get("causality")
    else:
        micro = current.get("micro")
        causality = current.get("causality")

    # Service reports
    service = {"S0": {}, "S5": {}}
    for state in ("S0", "S5"):
        for name in (
            "G1_gevent_w1",
            "T1_gthread_w1_t4",
            "G2_gevent_w2",
            "T2_gthread_w2_t2",
        ):
            p = OUT / f"{state}_{name}_report.json"
            if p.exists():
                service[state][name] = json.loads(p.read_text(encoding="utf-8"))

    thunder = current.get("thundering") or _load_json(OUT / "thunder_snapshot.json")
    ws = current.get("websocket") or {
        "status": "partial",
        "gevent_reason": "docker-entrypoint: long-lived /ws/galaxy with gevent",
        "route_present": True,
        "note": "No dedicated live WS soak; skip-path contract exists",
    }

    # Compact thundering
    thunder_compact = {}
    if isinstance(thunder, dict):
        for name, rep in thunder.items():
            if not isinstance(rep, dict):
                continue
            load = rep.get("load") or {}
            thunder_compact[name] = {
                "gs": load.get("game_state"),
                "healthz": load.get("healthz"),
                "slow5": load.get("slow5"),
            }

    # Rebuild causality from micro if missing
    if micro and not causality:
        g1 = ((micro.get("configs") or {}).get("G1_gevent_w1") or {}).get("avg") or {}
        t1 = ((micro.get("configs") or {}).get("T1_gthread_w1_t4") or {}).get("avg") or {}
        g_hz = float(g1.get("healthz_during_wait_ms") or 0)
        t_hz = float(t1.get("healthz_during_wait_ms") or 0)
        g_w = float(g1.get("writer_wait_ms") or 0)
        gevent_blocked = g_hz >= 2000 and g_w >= 2000
        gthread_ok = t_hz < max(500.0, g_hz * 0.25) if g_hz else t_hz < 500
        causality = {
            "SYSTEM_FAILURE_MECHANISM": "confirmed" if (gevent_blocked and gthread_ok) else "under investigation",
            "GEVENT_EVENT_LOOP_BLOCK": "confirmed yes" if gevent_blocked else "no",
            "gevent_w1": g1,
            "gthread_w1_t4": t1,
            "gate_gevent_healthz_high": gevent_blocked,
            "gate_gthread_healthz_low": gthread_ok,
        }

    def _compact(state_map: dict) -> dict:
        out = {}
        for name, rep in state_map.items():
            load = rep.get("load") or {}
            out[name] = {
                "gs": load.get("game_state"),
                "healthz": load.get("healthz"),
                "slow5": load.get("slow5"),
                "auth": load.get("auth_ok_ratio_game_state"),
            }
        return out

    options = {
        "A_gthread_instead_of_gevent": {
            "freeze_risk": "low for HTTP availability under sqlite wait",
            "sqlite_writer_contention": "unchanged",
            "websocket_impact": "HIGH — gevent chosen for /ws/galaxy",
            "impl_risk": "low (GUNICORN_WORKER_CLASS override)",
            "deploy_risk": "medium — needs WS soak before prod",
            "expected_perf": "micro: healthz ~10ms vs ~5s; service: hz_p95 ~2s vs ~12s",
        },
        "B_more_gevent_workers": {
            "freeze_risk": "medium — other worker serves while one blocks",
            "sqlite_writer_contention": "may increase",
            "websocket_impact": "low",
            "impl_risk": "low",
            "deploy_risk": "low-medium",
            "expected_perf": "micro gevent w2: healthz stays ~7–110ms; service improves but stalls remain",
        },
        "C_remove_writes_from_GET_poll": {
            "freeze_risk": "low if hot path read-only",
            "sqlite_writer_contention": "reduced on poll",
            "websocket_impact": "none",
            "impl_risk": "medium-high",
            "deploy_risk": "medium",
            "expected_perf": "best structural fix for poll storms",
        },
        "D_offload_blocking_sqlite_to_threads": {
            "freeze_risk": "low for gevent loop",
            "sqlite_writer_contention": "unchanged",
            "websocket_impact": "none/low",
            "impl_risk": "high",
            "deploy_risk": "high",
            "expected_perf": "keeps gevent WS model",
        },
        "E_postgres_long_term": {
            "freeze_risk": "low",
            "sqlite_writer_contention": "eliminated",
            "websocket_impact": "none",
            "impl_risk": "very high",
            "deploy_risk": "high",
            "expected_perf": "architectural endgame",
        },
    }

    summary = {
        "SYSTEM_FAILURE_MECHANISM": (causality or {}).get("SYSTEM_FAILURE_MECHANISM", "under investigation"),
        "GEVENT_EVENT_LOOP_BLOCK": (causality or {}).get("GEVENT_EVENT_LOOP_BLOCK", "under investigation"),
        "HISTORICAL_INCIDENT_TRIGGER": "under investigation",
        "ROOT_CAUSE": {
            "Mechanism": (causality or {}).get("SYSTEM_FAILURE_MECHANISM"),
            "Trigger": "under investigation",
        },
        "WORKER_CLASS_MICROTEST": {
            "gevent_w1": (causality or {}).get("gevent_w1"),
            "gthread_w1_t4": (causality or {}).get("gthread_w1_t4"),
            "note": "hold_sec=5 BEGIN IMMEDIATE external lock; A=game-state write wait",
        },
        "S0": _compact(service.get("S0") or {}),
        "S5": _compact(service.get("S5") or {}),
        "THUNDERING_HERD": thunder_compact or thunder,
        "WEBSOCKET_GATE": (ws or {}).get("status", "partial"),
        "websocket_detail": ws,
        "BEST_WORKER_MODEL": (
            "experimental only: gthread w1 t4 best HTTP availability under lock; "
            "do NOT ship without websocket soak"
        ),
        "options_paper": options,
        "NEXT_ACTION": (
            "Mechanism confirmed. Do not flip worker class in production yet. "
            "Next: websocket/galaxy soak for gthread; search historical trigger "
            "(poll write herd / backup / reconcile / cron). Prefer evaluating C/D."
        ),
        "micro": micro,
        "causality": causality,
        "service": {k: _compact(v) for k, v in (service or {}).items()},
    }
    # Persist micro snapshot for future merges
    if micro:
        (OUT / "micro_snapshot.json").write_text(
            json.dumps({"micro": micro, "causality": causality}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (OUT / "repro005_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "SYSTEM_FAILURE_MECHANISM": summary["SYSTEM_FAILURE_MECHANISM"],
                "GEVENT_EVENT_LOOP_BLOCK": summary["GEVENT_EVENT_LOOP_BLOCK"],
                "MICRO": summary["WORKER_CLASS_MICROTEST"],
                "S0": summary["S0"],
                "S5": summary["S5"],
                "WEBSOCKET_GATE": summary["WEBSOCKET_GATE"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
