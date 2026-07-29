"""
GC-842 — Building finish visibility (slim delta refresh, no include_panel lag).

Run: python -m pytest tests/test_gc842_building_finish_visibility.py -v
"""

from __future__ import annotations

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


def test_gc842_main_js_finish_uses_panel_delta_refresh():
    """The panel_delta_buildings client path (refreshBuildingsFinishState)
    was superseded by a canonical include_panel refresh for ALL timer-zero
    completions (commit afd88f1, "Timer-zero queue completion now forces a
    canonical include_panel refresh") and removed as dead code — nothing
    called it anymore once requestBuildingsFinishRefresh started routing
    through the shared requestQueueTimerZeroRefresh debounce below. The
    server-side panel_delta_buildings capability itself is untouched (see
    test_gc842_api_game_state_panel_delta_buildings /
    test_gc842_finish_delta_smaller_than_full_panel). Assert the current
    canonical path: building finish -> requestBuildingsFinishRefresh ->
    requestQueueTimerZeroRefresh -> forceCanonicalGameStateRefresh
    (include_panel=1), never a page reload.
    """
    src = _read("static/main.js")
    assert "panel_delta_buildings=" in src
    assert "function requestBuildingsFinishRefresh(meta)" in src
    assert "function requestQueueTimerZeroRefresh(meta)" in src
    finish_fn = src.split("function requestBuildingsFinishRefresh(meta)")[1].split(
        "function clearFinishRefreshArmed"
    )[0]
    assert 'domain: "buildings"' in finish_fn
    assert "requestQueueTimerZeroRefresh(" in finish_fn
    timer_zero = src.split("function requestQueueTimerZeroRefresh(meta)")[1].split(
        "function markCardQueueZeroRefresh"
    )[0]
    assert 'forceCanonicalGameStateRefresh("queue_timer_zero")' in timer_zero
    assert "reloadCurrentPage" not in timer_zero
    canonical_refresh = src.split("async function forceCanonicalGameStateRefresh(reason, opts)")[1].split(
        "\n  }\n", 1
    )[0]
    assert "include_panel=1" in canonical_refresh
    assert "forcePanel: true" in canonical_refresh


def test_gc842_api_game_state_panel_delta_buildings(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 2, "crystal_mine": 1, "solar_plant": 1})

    r = client.get("/api/game-state?panel_delta_buildings=metal_mine")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert "buildings_panel" not in body
    delta = body.get("buildings_panel_delta") or {}
    flat = [row for rows in delta.values() for row in (rows or [])]
    row = next((x for x in flat if x.get("key") == "metal_mine"), None)
    assert row is not None
    assert row.get("level") == 2
    assert "can_afford" in row
    assert body.get("build_queue") is not None


def test_gc842_finish_delta_smaller_than_full_panel(game_client):
    import json

    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 2, "crystal_mine": 1, "solar_plant": 1})

    delta = client.get("/api/game-state?panel_delta_buildings=metal_mine").get_json()
    full = client.get("/api/game-state?include_panel=1").get_json()
    assert len(json.dumps(delta, separators=(",", ":"))) < len(json.dumps(full, separators=(",", ":")))
