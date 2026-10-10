#!/usr/bin/env python3
"""Shared helpers for GC-PROD-INFINITY-LOAD-REPRO-004."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SECRET = "concurrency-repro-secret-key-32charsxx"

ROUTES = [
    "/api/game-state",
    "/api/notifications/summary",
    "/api/chat/bootstrap",
    "/overview",
    "/fleet",
    "/world-boss",
    "/messages",
    "/galaxy",
]

STATE_IDS = (
    "S0_NORMALIZED",
    "S1_BACKUP_DUE",
    "S2_FULL_RECONCILE_DUE",
    "S3_MANY_DUE_FLEETS",
    "S4_MANY_DUE_QUEUES",
    "S5_FLEET_AND_QUEUES",
    "S6_RECONCILE_FLEET_QUEUES",
    "S7_WORST_PLAUSIBLE",
)

PERF_LINE = re.compile(r"\[GC REQUEST PERF\]\s+(.*)")


def load_concurrency_repro():
    spec = importlib.util.spec_from_file_location(
        "concurrency_repro",
        ROOT / "scripts" / "prod_infinity_load_concurrency_repro.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["concurrency_repro"] = mod
    spec.loader.exec_module(mod)
    return mod


def repo_to_wsl_path(path: Path) -> str:
    p = path.resolve()
    s = str(p)
    if len(s) >= 2 and s[1] == ":":
        drive = s[0].lower()
        rest = s[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return s.replace("\\", "/")


def copy_seed(seed: Path, dest: Path) -> Path:
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(dest) + suffix)
        if p.exists():
            p.unlink()
    shutil.copy2(seed.resolve(), dest)
    return dest


def pct(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return float(sorted_vals[idx])


def summarize_ms(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0, "mean_ms": 0}
    s = sorted(values)
    return {
        "n": len(s),
        "p50_ms": round(pct(s, 50), 2),
        "p95_ms": round(pct(s, 95), 2),
        "p99_ms": round(pct(s, 99), 2),
        "max_ms": round(s[-1], 2),
        "mean_ms": round(statistics.mean(s), 2),
    }


def analyze_samples(samples, maint_samples=None) -> Dict[str, Any]:
    cr = load_concurrency_repro()
    return cr.analyze(samples, maint_samples or [])


def route_stats(analysis: Dict[str, Any], route: str) -> Dict[str, float]:
    return dict((analysis.get("by_route") or {}).get(route) or {})


def penalty(with_m: Dict[str, float], control: Dict[str, float]) -> Dict[str, float]:
    return {
        "p95_ms": round(float(with_m.get("p95_ms") or 0) - float(control.get("p95_ms") or 0), 2),
        "p99_ms": round(float(with_m.get("p99_ms") or 0) - float(control.get("p99_ms") or 0), 2),
        "max_ms": round(float(with_m.get("max_ms") or 0) - float(control.get("max_ms") or 0), 2),
    }


def parse_perf_log_line(line: str) -> Optional[Dict[str, Any]]:
    m = PERF_LINE.search(line)
    if not m:
        return None
    out: Dict[str, Any] = {}
    for part in m.group(1).split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            if "." in v:
                out[k] = float(v)
            elif v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
                out[k] = int(v)
            else:
                out[k] = v
        except ValueError:
            out[k] = v
    return out or None


def parse_server_perf(log_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not log_path.exists():
        return rows
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        row = parse_perf_log_line(line)
        if row:
            rows.append(row)
    return rows


def aggregate_write_paths(perf_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs = [r for r in perf_rows if str(r.get("path") or "") == "/api/game-state"]
    if not gs:
        return {"dominant_path": None, "n": 0}

    def _bucket(r: Dict[str, Any]) -> str:
        finish = float(r.get("finish_ms") or 0)
        fleet = float(r.get("fleet_tick_ms") or 0) or float(r.get("fleets_dirty_tick_ms") or 0)
        begin = float(r.get("db_begin_immediate_ms") or 0)
        write = float(r.get("db_write_transaction_ms") or 0)
        resource = float(r.get("resource_sync_ms") or 0)
        if finish >= max(fleet, begin, write, resource) and finish > 0:
            return "queue_finish"
        if fleet > 0:
            return "fleet_tick"
        if begin > 0 or write > 0:
            return "db_write"
        if resource > 0:
            return "resource_sync"
        return "read_only"

    buckets: Dict[str, int] = {}
    for r in gs:
        b = _bucket(r)
        buckets[b] = buckets.get(b, 0) + 1
    dominant = max(buckets.items(), key=lambda kv: kv[1])[0] if buckets else None
    return {
        "dominant_path": dominant,
        "buckets": buckets,
        "n": len(gs),
        "begin_immediate_p95": round(
            pct(sorted(float(r.get("db_begin_immediate_ms") or 0) for r in gs), 95),
            2,
        ),
        "write_hold_p95": round(
            pct(sorted(float(r.get("db_write_transaction_ms") or 0) for r in gs), 95),
            2,
        ),
        "finish_p95": round(pct(sorted(float(r.get("finish_ms") or 0) for r in gs), 95), 2),
        "fleet_tick_ran": sum(1 for r in gs if int(r.get("fleet_tick_ran") or 0) == 1),
    }


def verify_topology_logs(log_text: str) -> Dict[str, Any]:
    low = log_text.lower()
    return {
        "gunicorn_running": "starting gunicorn" in low or "booting worker with gevent" in low,
        "worker_class_gevent": "gevent" in low,
        "workers_1": bool(re.search(r"workers=1\b|workers\s*=\s*1\b|-w\s*1\b", log_text)),
        "maintenance_sidecar": "maintenance-worker" in low and "started" in low,
        "embedded_cron_off": "disabled_sidecar_owns_bag" in low or "embedded-cron disabled" in low,
    }


def topology_verified(checks: Dict[str, Any]) -> bool:
    required = (
        "gunicorn_running",
        "worker_class_gevent",
        "embedded_cron_off",
    )
    return all(bool(checks.get(k)) for k in required) and (
        bool(checks.get("maintenance_sidecar")) or bool(checks.get("no_sidecar_mode"))
    )
