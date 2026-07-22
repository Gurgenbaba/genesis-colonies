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


def _pjax_html_misses(payload_bytes: int, budgets: dict) -> list[str]:
    ceiling = float(budgets.get("pjax_html_bytes") or 0)
    if ceiling > 0 and payload_bytes > ceiling:
        return ["pjax_html_bytes"]
    return []


def _sample_get(client, path: str, *, headers: dict | None = None) -> dict:
    t0 = time.perf_counter()
    resp = client.get(path, headers=headers or {})
    total_ms = (time.perf_counter() - t0) * 1000.0
    body = resp.get_data() or b""
    return {
        "path": path,
        "status": resp.status_code,
        "total_ms": round(total_ms, 1),
        "bytes": len(body),
        "headers": headers or {},
    }


def _try_login_baseline_user(client) -> bool:
    """Opt-in auth for PJAX HTML samples (GC_PERF_BASELINE_LOGIN=1)."""
    flag = os.environ.get("GC_PERF_BASELINE_LOGIN", "0").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    try:
        from game.models import create_user, db, ensure_player_and_homeworld

        conn = db()
        ok, _err, user = create_user("perf_baseline_user", "perf-baseline-pass-123")
        if not ok and user is None:
            cur = conn.execute(
                "SELECT id FROM users WHERE username = ? LIMIT 1;",
                ("perf_baseline_user",),
            )
            row = cur.fetchone()
            if not row:
                conn.close()
                return False
            uid = int(row["id"] if hasattr(row, "keys") else row[0])
        else:
            uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="PerfBaseline", conn=conn)
        conn.commit()
        conn.close()
        with client.session_transaction() as sess:
            sess["user_id"] = uid
        return True
    except Exception:
        return False


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
        sample = _sample_get(client, "/api/game-state")
        misses = []
        if sample["status"] == 200:
            misses = _eval_diet(sample["total_ms"], sample["bytes"])
        sample["budget_miss"] = misses
        sample["note"] = "unauthenticated unless session cookie provided"
        results.append(sample)

        # GC-PERF-PJAX-BYTES-HEAVY-001: measure PE PJAX HTML size when logged in.
        logged_in = _try_login_baseline_user(client)
        pe = _sample_get(
            client,
            "/planet-evolution",
            headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},
        )
        pe["budget_miss"] = (
            _pjax_html_misses(pe["bytes"], budgets) if pe["status"] == 200 else []
        )
        pe["note"] = (
            "pjax_html_bytes sample"
            if logged_in
            else "pjax sample skipped auth (unauthenticated redirect likely)"
        )
        pe["pjax"] = True
        results.append(pe)

    return {"mode": "test_client", "budgets": budgets, "samples": results}


def _run_via_url(base_url: str) -> dict:
    import urllib.request

    from game.config import get_perf_budgets

    budgets = get_perf_budgets()
    samples = []
    for path, headers in (
        ("/api/game-state", {}),
        (
            "/planet-evolution",
            {"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},
        ),
    ):
        url = base_url.rstrip("/") + path
        t0 = time.perf_counter()
        req = urllib.request.Request(url, method="GET", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                status = resp.status
        except Exception as exc:
            samples.append({"path": path, "error": str(exc)})
            continue
        total_ms = (time.perf_counter() - t0) * 1000.0
        if path == "/api/game-state":
            misses = _eval_diet(total_ms, len(body)) if status == 200 else []
        else:
            misses = _pjax_html_misses(len(body), budgets) if status == 200 else []
        samples.append(
            {
                "path": path,
                "status": status,
                "total_ms": round(total_ms, 1),
                "bytes": len(body),
                "budget_miss": misses,
                "pjax": bool(headers),
            }
        )
    return {"mode": "url", "budgets": budgets, "samples": samples}


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
