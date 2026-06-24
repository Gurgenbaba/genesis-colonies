"""
GC-855 — Fleet SSR backend profiling instrumentation (measure only).

Run: python -m pytest tests/test_gc855_fleet_ssr_perf_instrumentation.py -v
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_ssr_perf_trace():
    from game.live_state import finish_ssr_perf

    finish_ssr_perf()
    yield
    finish_ssr_perf()


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc855_ssr_trace_includes_fleet_fields():
    from game.live_state import SsrPerfTrace

    trace = SsrPerfTrace("/fleet")
    trace.add_fleet_panel_ms(120.0)
    trace.add_logistics_panel_ms(45.0)
    data = trace.as_dict(response_bytes=2048)
    assert data["fleet_panel_ms"] == 120.0
    assert data["logistics_panel_ms"] == 45.0


def test_gc855_server_log_format_contract():
    src = _read("game/live_state.py")
    assert "fleet_panel=%sms logistics_panel=%sms" in src


def test_gc855_fleet_without_debug_has_no_ssr_log(game_client, monkeypatch, caplog):
    monkeypatch.delenv("GC_SSR_PERF_DEBUG", raising=False)
    caplog.set_level(logging.INFO)
    client, _pid = game_client

    resp = client.get("/fleet")
    assert resp.status_code == 200
    assert not any("[GC SSR PERF]" in rec.message for rec in caplog.records)


def test_gc855_fleet_with_debug_emits_one_ssr_log(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_SSR_PERF_DEBUG", "1")
    caplog.set_level(logging.INFO)
    client, _pid = game_client

    resp = client.get("/fleet")
    assert resp.status_code == 200
    hits = [rec for rec in caplog.records if "[GC SSR PERF]" in rec.message]
    assert len(hits) == 1
    msg = hits[0].message
    assert "route=/fleet" in msg
    for key in (
        "total=",
        "live_context=",
        "finish=",
        "resource_sync=",
        "fleet_panel=",
        "logistics_panel=",
        "template=",
        "bytes=",
    ):
        assert key in msg
