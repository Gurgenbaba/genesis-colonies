"""
GC-853 — Buildings SSR backend profiling instrumentation (measure only).

Run: python -m pytest tests/test_gc853_buildings_ssr_perf_instrumentation.py -v
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc853_ssr_perf_helpers_gated():
    from game.live_state import SsrPerfTrace, finish_ssr_perf, start_ssr_perf

    assert start_ssr_perf("/buildings", tab="resources") is None
    trace = SsrPerfTrace("/buildings", tab="resources")
    trace.add_live_context_ms(100.0)
    trace.add_finish_ms(40.0)
    trace.add_resource_sync_ms(30.0)
    trace.add_buildings_panel_ms(20.0)
    trace.add_cards_ms(12.0)
    trace.add_tech_data_ms(8.0)
    trace.add_template_ms(5.0)
    data = trace.as_dict(response_bytes=4096)
    assert data["route"] == "/buildings"
    assert data["tab"] == "resources"
    assert data["live_context_ms"] == 100.0
    assert data["finish_ms"] == 40.0
    assert data["resource_sync_ms"] == 30.0
    assert data["buildings_panel_ms"] == 20.0
    assert data["cards_ms"] == 12.0
    assert data["tech_data_ms"] == 8.0
    assert data["template_ms"] == 5.0
    assert data["bytes"] == 4096
    assert finish_ssr_perf(response_bytes=1) is None


def test_gc853_server_log_format_contract():
    src = _read("game/live_state.py")
    assert "[GC SSR PERF] route=%s tab=%s total=%sms live_context=%sms finish=%sms" in src
    assert "resource_sync=%sms buildings_panel=%sms cards=%sms tech_data=%sms" in src
    assert "template=%sms bytes=%s" in src


def test_gc853_config_flag_reads_env(monkeypatch):
    from game.config import is_ssr_perf_debug_enabled

    monkeypatch.delenv("GC_SSR_PERF_DEBUG", raising=False)
    assert is_ssr_perf_debug_enabled() is False
    monkeypatch.setenv("GC_SSR_PERF_DEBUG", "1")
    assert is_ssr_perf_debug_enabled() is True


def test_gc853_buildings_without_debug_has_no_ssr_log(game_client, monkeypatch, caplog):
    monkeypatch.delenv("GC_SSR_PERF_DEBUG", raising=False)
    caplog.set_level(logging.INFO)
    client, _pid = game_client

    resp = client.get("/buildings?tab=resources")
    assert resp.status_code == 200
    assert not any("[GC SSR PERF]" in rec.message for rec in caplog.records)


def test_gc853_buildings_with_debug_emits_one_ssr_log(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_SSR_PERF_DEBUG", "1")
    caplog.set_level(logging.INFO)
    client, _pid = game_client

    resp = client.get("/buildings?tab=resources")
    assert resp.status_code == 200
    hits = [rec for rec in caplog.records if "[GC SSR PERF]" in rec.message]
    assert len(hits) == 1
    msg = hits[0].message
    assert "route=/buildings" in msg
    assert "tab=resources" in msg
    for key in (
        "total=",
        "live_context=",
        "finish=",
        "resource_sync=",
        "buildings_panel=",
        "cards=",
        "tech_data=",
        "template=",
        "bytes=",
    ):
        assert key in msg
