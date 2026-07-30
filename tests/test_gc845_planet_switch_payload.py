"""
GC-845 — Planet switch action payload must stay slim (no full buildings_panel).

Run: python -m pytest tests/test_gc845_planet_switch_payload.py -v
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

from game.models import get_homeworld, save_planet_buildings

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc845_planet_switch_state_has_no_buildings_panel(game_client):
    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    save_planet_buildings(int(planet["id"]), {"metal_mine": 2, "crystal_mine": 1, "solar_plant": 1})

    body = client.post(
        "/api/planets/active",
        json={"planet_id": int(planet["id"]), "request_id": f"gc845-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()

    assert body.get("ok") is True
    state = body.get("state") or {}
    assert "buildings_panel" not in state
    assert "buildings_panel_delta" not in state
    for heavy in ("exchange", "shipyard", "defense", "planet_teaser", "global_queue_hud"):
        assert heavy not in state
    assert state.get("resources") or state.get("player")
    assert state.get("build_queue") is not None
    assert state.get("active_planet_id") == int(planet["id"])
    assert isinstance(body.get("planets"), list)


def test_gc845_planet_switch_payload_smaller_than_full_panel(game_client):
    client, pid = game_client
    planet = get_homeworld(player_id=pid)

    switch = client.post(
        "/api/planets/active",
        json={"planet_id": int(planet["id"])},
        headers={"Content-Type": "application/json"},
    ).get_json()
    full = client.get("/api/game-state?include_panel=1").get_json()

    switch_bytes = len(json.dumps(switch.get("state") or {}, separators=(",", ":")))
    full_bytes = len(json.dumps(full or {}, separators=(",", ":")))
    assert switch_bytes < full_bytes


def test_gc845_main_js_planet_switch_skips_panel_patch():
    """Planet switch must not run queue page patches (PJAX reload owns panels)."""
    src = _read("static/main.js")
    block = src.split("function applyActionState(json, reason)")[1].split("function logStatusPollErrorOnce")[0]
    assert "if (!isPlanetSwitch)" in block
    # Queue patch is gated behind !isPlanetSwitch via syncMountedQueuePagesFromState.
    assert "syncMountedQueuePagesFromState(state, reasonStr)" in block
    assert block.index("if (!isPlanetSwitch)") < block.index("syncMountedQueuePagesFromState(state, reasonStr)")
    assert "skipGameState: true" in src
    assert "skipPolling: true" in src


def test_gc_perf_planet_switch_003_skips_finish_and_fleet_tick():
    """GC-PERF-PLANET-SWITCH-003 — switch must not empire-finish or HTTP fleet-tick."""
    app_py = _read("app.py")
    logic_py = _read("game/logic.py")
    assert "def read_player_live_state_for_planet_switch(" in logic_py
    assert 'src == "api_planets_active"' in app_py
    assert "read_player_live_state_for_planet_switch" in app_py
    skip = app_py.split("_FLEET_TICK_SKIP_ENDPOINTS = frozenset")[1].split(")", 1)[0]
    assert "api_planets_set_active" in skip


def test_api_planets_active_does_not_call_finish_player_due_work(game_client, monkeypatch):
    """Pending Bauleiste must not force empire finish on planet switch."""
    from game.models import get_homeworld
    from game.planet_evolution.service import set_active_planet
    from game import queue_engine

    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    ok, reason = set_active_planet(pid, planet_id)
    assert ok, reason

    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("finish")
        raise AssertionError("finish_player_due_work must not run on planet switch")

    monkeypatch.setattr(queue_engine, "finish_player_due_work", _boom)
    monkeypatch.setattr("game.logic.finish_player_due_work", _boom, raising=False)

    body = client.post(
        "/api/planets/active",
        json={"planet_id": planet_id, "request_id": f"gc-ps003-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()
    assert body.get("ok") is True
    assert body.get("state", {}).get("active_planet_id") == planet_id
    assert calls == []
