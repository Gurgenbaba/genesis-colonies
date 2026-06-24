"""
GC-841 — First-click action latency profiling contracts.

Run: python -m pytest tests/test_gc841_action_perf_instrumentation.py -v
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _set_buildings(planet_id: int, levels: dict) -> None:
    from game.models import save_planet_buildings

    save_planet_buildings(planet_id, levels)


def test_gc841_live_state_action_perf_helpers():
    from game.live_state import ActionPerfTrace, finish_action_perf, start_action_perf

    assert start_action_perf("/test") is None
    trace = ActionPerfTrace("/test")
    trace.add_finish_ms(10.5)
    trace.add_mutate_ms(20.0)
    trace.add_live_state_ms(300.0)
    trace.add_resource_sync_ms(120.0)
    trace.add_payload_ms(40.0)
    data = trace.as_dict(response_bytes=1234)
    assert data["route"] == "/test"
    assert data["finish_ms"] == 10.5
    assert data["mutate_ms"] == 20.0
    assert data["live_state_ms"] == 300.0
    assert data["resource_sync_ms"] == 120.0
    assert data["payload_ms"] == 40.0
    assert data["bytes"] == 1234
    assert finish_action_perf(response_bytes=1) is None


def test_gc841_main_js_client_perf_hooks():
    src = _read("static/main.js")
    assert "window.GC_PERF_DEBUG = true" in src
    assert "function beginActionPerfClick(route, meta)" in src
    assert "[GC ACTION PERF CLIENT]" in src
    assert "finishActionPerfAfterApply(reason)" in src


def test_gc841_server_log_format_contract():
    src = _read("game/live_state.py")
    assert "[GC ACTION PERF] route=%s total=%sms finish=%sms mutate=%sms" in src
    assert "resource_sync=%sms payload=%sms bytes=%s" in src


def test_gc841_upgrade_without_debug_has_no_action_perf(game_client, monkeypatch):
    monkeypatch.delenv("GC_PERF_DEBUG", raising=False)
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})

    body = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc841-off-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()

    assert "_action_perf" not in body
    assert "buildings_panel" not in (body.get("state") or {})
    assert (body.get("state") or {}).get("buildings_panel_delta")


def test_gc841_upgrade_with_debug_includes_action_perf(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_PERF_DEBUG", "1")
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})

    with caplog.at_level(logging.INFO):
        body = client.post(
            "/api/buildings/upgrade",
            json={"building_type": "metal_mine", "request_id": f"gc841-on-{uuid.uuid4().hex}"},
            headers={"Content-Type": "application/json"},
        ).get_json()

    perf = body.get("_action_perf") or {}
    assert perf.get("route") == "/api/buildings/upgrade"
    assert "total_ms" in perf
    assert "finish_ms" in perf
    assert "mutate_ms" in perf
    assert "live_state_ms" in perf
    assert "resource_sync_ms" in perf
    assert "payload_ms" in perf
    assert perf.get("bytes", 0) > 0
    assert any("[GC ACTION PERF]" in rec.message for rec in caplog.records)
    assert "buildings_panel" not in (body.get("state") or {})


def test_gc841_client_config_exposes_action_perf_flag(monkeypatch):
    from game.config import get_client_runtime_config

    monkeypatch.delenv("GC_PERF_DEBUG", raising=False)
    assert get_client_runtime_config()["action_perf_debug"] is False
    monkeypatch.setenv("GC_PERF_DEBUG", "1")
    assert get_client_runtime_config()["action_perf_debug"] is True


def test_gc841_debug_payload_still_smaller_than_full_panel(game_client, monkeypatch):
    monkeypatch.setenv("GC_PERF_DEBUG", "1")
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})

    action = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc841-size-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()
    panel = client.get("/api/game-state?include_panel=1").get_json()

    action_bytes = len(json.dumps(action, separators=(",", ":")))
    panel_bytes = len(json.dumps(panel, separators=(",", ":")))
    assert action_bytes < panel_bytes
