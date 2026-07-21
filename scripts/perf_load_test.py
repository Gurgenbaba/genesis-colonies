#!/usr/bin/env python3
"""
GC-PERF-LOAD-001 — concurrent diet-poll load probe (local).

Usage:
  python scripts/perf_load_test.py --workers 8 --requests 40

Uses Flask test client (no live server). Reports p50/p95 total_ms and budget misses.
Set GC_PERF_BUDGET_ASSERT=1 to exit non-zero on diet budget misses.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _one_poll(app):
    t0 = time.perf_counter()
    with app.test_client() as client:
        resp = client.get("/api/game-state")
        body = resp.get_data() or b""
        status = resp.status_code
    ms = (time.perf_counter() - t0) * 1000.0
    return {"status": status, "total_ms": ms, "bytes": len(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--requests", type=int, default=20)
    args = parser.parse_args()

    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")
    from app import app
    from game.config import get_perf_budgets
    from game.live_state import evaluate_request_perf_budgets

    budgets = get_perf_budgets()
    samples = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = [pool.submit(_one_poll, app) for _ in range(max(1, args.requests))]
        for fut in as_completed(futs):
            samples.append(fut.result())

    times = [s["total_ms"] for s in samples]
    times_sorted = sorted(times)
    p50 = times_sorted[len(times_sorted) // 2] if times_sorted else 0.0
    p95 = times_sorted[int(len(times_sorted) * 0.95)] if times_sorted else 0.0

    misses = []
    for s in samples:
        if s["status"] == 200:
            m = evaluate_request_perf_budgets(
                total_ms=s["total_ms"],
                response_bytes=s["bytes"],
                sql_count=0,
                sql_write_count=0,
                finish_source="game_state",
                include_panel=0,
            )
            if m:
                misses.extend(m)

    report = {
        "workers": args.workers,
        "requests": args.requests,
        "p50_ms": round(p50, 1),
        "p95_ms": round(p95, 1),
        "mean_ms": round(statistics.mean(times), 1) if times else 0.0,
        "budgets": budgets,
        "budget_miss_keys": sorted(set(misses)),
        "status_counts": {
            str(k): sum(1 for s in samples if s["status"] == k)
            for k in sorted({s["status"] for s in samples})
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    assert_on = os.environ.get("GC_PERF_BUDGET_ASSERT", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if assert_on and misses:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
