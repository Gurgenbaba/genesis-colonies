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
    src = _read("static/main.js")
    assert "panel_delta_buildings=" in src
    assert "function refreshBuildingsFinishState(reason)" in src
    assert "function requestBuildingsFinishRefresh(meta)" in src
    fn = src.split("function refreshPageAfterQueueEvent(reason)")[1].split(
        "/** Lightweight HUD refresh"
    )[0]
    assert 'reasonStr === "page_init"' in fn
    assert "include_panel=1" in fn
    assert "refreshBuildingsFinishState(reasonStr)" in fn
    delta_fn = src.split("function refreshBuildingsFinishState(reason)")[1].split(
        "function requestBuildingsFinishRefresh"
    )[0]
    assert "buildBuildingsFinishDeltaUrl(keys)" in delta_fn


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
