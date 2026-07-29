"""
GC-PERF-002 — navigation latency instrumentation contracts.

Run: python -m pytest tests/test_gc_perf_002_nav_latency.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_nav_perf_debug_client_config():
    from game.config import get_client_runtime_config, is_nav_perf_debug_enabled

    cfg = get_client_runtime_config()
    assert "nav_perf_debug" in cfg
    assert cfg["nav_perf_debug"] is is_nav_perf_debug_enabled()


def test_nav_perf_browser_contract_in_main_js():
    src = _read("static/main.js")
    assert "window.GC_NAV_PERF_DEBUG = true" in src
    assert "function beginNavPerf(fromPath, toUrl)" in src
    assert "function finishNavPerf(extra)" in src
    assert 'console.info("[GC NAV PERF]"' in src
    assert "concurrent_requests" in src


def test_request_perf_phase_keys_include_nav_latency_fields():
    from game.live_state import _REQUEST_PERF_META_KEYS, _REQUEST_PERF_PHASE_KEYS

    for key in (
        "before_request_ms",
        "handler_ms",
        "after_request_ms",
        "db_connection_ms",
        "page_context_ms",
        "template_render_ms",
        "account_deletion_worker_ms",
    ):
        assert key in _REQUEST_PERF_PHASE_KEYS
    for key in ("route", "pjax", "account_deletions_ran"):
        assert key in _REQUEST_PERF_META_KEYS


def test_page_live_context_sets_finish_source_meta():
    src = _read("app.py")
    block = src.split("def _load_page_live_context(")[1].split("\n\n\ndef _load_player_view_with_resources")[0]
    assert 'set_request_perf_meta("finish_source", src)' in block
    assert 'set_request_perf_meta("route"' in block
    assert 'set_request_perf_meta("pjax", 1)' in block
    assert 'record_request_perf_phase(\n            "page_context_ms"' in block or 'record_request_perf_phase("page_context_ms"' in block


def test_db_connection_perf_phase():
    src = _read("game/db.py")
    assert "db_connection_ms" in src
    assert "is_request_perf_sampled()" in src


def test_buildings_pjax_request_perf_slow_log(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    client, _pid = game_client

    caplog.set_level("INFO")
    resp = client.get(
        "/buildings",
        headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    perf_logs = [rec.message for rec in caplog.records if "[GC REQUEST PERF]" in rec.message]
    assert perf_logs, "expected [GC REQUEST PERF] log for /buildings PJAX"
    msg = perf_logs[-1]
    assert "finish_source=buildings" in msg
    assert "pjax=1" in msg
    assert "route=/buildings" in msg
