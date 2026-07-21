"""
GC-PERF-CORE-001 — performance budgets and diet-byte contracts.

Run: python -m pytest tests/test_gc_perf_core_001.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def test_perf_budgets_defaults(monkeypatch):
    from game.config import get_perf_budgets

    for key in (
        "GC_PERF_BUDGET_DIET_POLL_MS",
        "GC_PERF_BUDGET_DIET_PAYLOAD_BYTES",
        "GC_PERF_BUDGET_ACTION_MS",
        "GC_PERF_BUDGET_PJAX_SSR_MS",
        "GC_PERF_BUDGET_DIET_SQL_COUNT",
        "GC_PERF_BUDGET_DIET_SQL_WRITE_COUNT",
    ):
        monkeypatch.delenv(key, raising=False)

    budgets = get_perf_budgets()
    assert budgets["diet_poll_ms"] == 40.0
    assert budgets["diet_payload_bytes"] == 15_360.0
    assert budgets["action_ms"] == 120.0
    assert budgets["pjax_ssr_ms"] == 100.0
    assert budgets["diet_sql_count"] == 5.0
    assert budgets["diet_sql_write_count"] == 0.0
    assert budgets["definition_lookup_ms"] == 1.0


def test_perf_budgets_env_override(monkeypatch):
    from game.config import get_perf_budgets

    monkeypatch.setenv("GC_PERF_BUDGET_DIET_POLL_MS", "55")
    assert get_perf_budgets()["diet_poll_ms"] == 55.0


def test_evaluate_diet_poll_budget_misses():
    from game.live_state import evaluate_request_perf_budgets

    misses = evaluate_request_perf_budgets(
        total_ms=80.0,
        response_bytes=20_000,
        sql_count=12,
        sql_write_count=2,
        finish_source="game_state",
        include_panel=0,
    )
    assert "diet_poll_ms" in misses
    assert "diet_payload_bytes" in misses
    assert "diet_sql_count" in misses
    assert "diet_sql_write_count" in misses


def test_evaluate_diet_poll_within_budget():
    from game.live_state import evaluate_request_perf_budgets

    misses = evaluate_request_perf_budgets(
        total_ms=20.0,
        response_bytes=8_000,
        sql_count=3,
        sql_write_count=0,
        finish_source="game_state",
        include_panel=0,
    )
    assert misses == []


def test_diet_payload_bytes_recorded(game_client, monkeypatch):
    from flask import g

    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "999999")

    client, _pid = game_client
    with client.application.test_request_context("/api/game-state"):
        pass

    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    assert len(raw) < 16_384


def test_perf_core_doc_exists():
    assert (ROOT / "docs" / "GC_PERF_CORE.md").is_file()
    text = (ROOT / "docs" / "GC_PERF_CORE.md").read_text(encoding="utf-8")
    assert "GC-PERF-CORE-001" in text
    assert "diet_poll_ms" in text or "Diet" in text


def test_perf_baseline_script_exists():
    script = ROOT / "scripts" / "perf_baseline.py"
    assert script.is_file()
    src = script.read_text(encoding="utf-8")
    assert "get_perf_budgets" in src
    assert "game-state" in src
