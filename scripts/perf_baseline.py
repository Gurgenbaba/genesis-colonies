#!/usr/bin/env python3
"""
GC-PERF-CORE-001 — local performance baseline against a running app or test client.

Usage (test client, no server):
  python scripts/perf_baseline.py

Usage (against live URL):
  GC_PERF_BASELINE_URL=http://127.0.0.1:5000 python scripts/perf_baseline.py

Prints total_ms, bytes, sql phases when available, and budget miss keys.
Does not fail the process on misses unless GC_PERF_BUDGET_ASSERT=1.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _budgets():
    from game.config import get_perf_budgets

    return get_perf_budgets()


def _eval_diet(total_ms: float, payload_bytes: int, sql_count: int = 0, sql_write: int = 0):
    from game.live_state import evaluate_request_perf_budgets

    return evaluate_request_perf_budgets(
        total_ms=total_ms,
        response_bytes=payload_bytes,
        sql_count=sql_count,
        sql_write_count=sql_write,
        finish_source="game_state",
        include_panel=0,
    )


def _run_via_test_client() -> dict:
    os.environ.setdefault("GC_REQUEST_PERF_DEBUG", "1")
    os.environ.setdefault("GC_REQUEST_PERF_SLOW_MS", "0")
    os.environ.setdefault("GC_REQUEST_PERF_SAMPLE", "1.0")

    from app import app
    from game.config import get_perf_budgets

    budgets = get_perf_budgets()
    results = []

    with app.test_client() as client:
        # Login path varies; baseline measures anonymous → expect redirect/401
        # Prefer authenticated fixture via env GC_PERF_BASELINE_SESSION if set.
        t0 = time.perf_counter()
        resp = client.get("/api/game-state")
        total_ms = (time.perf_counter() - t0) * 1000.0
        body = resp.get_data() or b""
        payload_bytes = len(body)
        status = resp.status_code
        misses = []
        if status == 200:
            misses = _eval_diet(total_ms, payload_bytes)
        results.append(
            {
                "path": "/api/game-state",
                "status": status,
                "total_ms": round(total_ms, 1),
                "bytes": payload_bytes,
                "budget_miss": misses,
                "note": "unauthenticated unless session cookie provided",
            }
        )

    return {"mode": "test_client", "budgets": budgets, "samples": results}


def _run_via_url(base_url: str) -> dict:
    import urllib.request

    from game.config import get_perf_budgets

    budgets = get_perf_budgets()
    url = base_url.rstrip("/") + "/api/game-state"
    t0 = time.perf_counter()
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            status = resp.status
    except Exception as exc:
        return {
            "mode": "url",
            "budgets": budgets,
            "samples": [{"path": "/api/game-state", "error": str(exc)}],
        }
    total_ms = (time.perf_counter() - t0) * 1000.0
    misses = _eval_diet(total_ms, len(body)) if status == 200 else []
    return {
        "mode": "url",
        "budgets": budgets,
        "samples": [
            {
                "path": "/api/game-state",
                "status": status,
                "total_ms": round(total_ms, 1),
                "bytes": len(body),
                "budget_miss": misses,
            }
        ],
    }


def main() -> int:
    base = os.environ.get("GC_PERF_BASELINE_URL", "").strip()
    if base:
        report = _run_via_url(base)
    else:
        report = _run_via_test_client()

    print(json.dumps(report, indent=2, sort_keys=True))

    assert_on = os.environ.get("GC_PERF_BUDGET_ASSERT", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if assert_on:
        for sample in report.get("samples") or []:
            if sample.get("budget_miss"):
                print("BUDGET ASSERT FAILED:", sample.get("budget_miss"), file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
