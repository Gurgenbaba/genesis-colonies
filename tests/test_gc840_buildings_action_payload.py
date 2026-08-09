"""
GC-840 — Buildings action payload slimdown contracts.

Run: python -m pytest tests/test_gc840_buildings_action_payload.py -v
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

from game.buildings import get_buildings_panel_delta, get_buildings_panel_rows
from game.models import get_homeworld

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _set_buildings(planet_id: int, levels: dict) -> None:
    from game.models import save_planet_buildings

    save_planet_buildings(planet_id, levels)


def test_gc840_main_js_patches_buildings_panel_delta():
    src = _read("static/main.js")
    assert "data.buildings_panel || data.buildings_panel_delta" in src
    assert "state.buildings_panel || state.buildings_panel_delta" in src


def test_gc840_action_response_uses_delta_not_full_panel(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})

    r = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc840-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert "state" in body
    state = body["state"]
    assert "buildings_panel" not in state
    delta = state.get("buildings_panel_delta") or {}
    assert isinstance(delta, dict) and delta
    flat = [row for rows in delta.values() for row in (rows or [])]
    assert any(row.get("key") == "metal_mine" for row in flat)
    owners = (state.get("build_queue") or {}).get("card_jobs_by_owner") or {}
    if body.get("ok"):
        assert owners


def test_gc840_action_payload_smaller_than_full_panel(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})

    action = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc840-size-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()
    panel = client.get(
        "/api/game-state?include_panel=1&panel_page=buildings"
    ).get_json()

    action_bytes = len(json.dumps(action.get("state") or {}, separators=(",", ":")))
    panel_bytes = len(json.dumps(panel or {}, separators=(",", ":")))
    # Action diet must stay smaller than a scoped buildings panel (absolute KB
    # caps drift with HUD slices; relative size is the GC-840 contract).
    assert action_bytes < panel_bytes
    assert "buildings_panel" not in (action.get("state") or {})


def test_gc840_action_state_diet_strips_page_catalog(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})

    state = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc840-diet-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()["state"]

    for heavy in ("exchange", "scrapyard", "shipyard", "defense", "global_queue_hud", "planet_teaser", "codex"):
        assert heavy not in state
    assert state.get("build_queue") is not None
    assert state.get("resources") or state.get("player")


def test_get_buildings_panel_delta_only_requested_keys():
    planet = get_homeworld(player_id=1)
    if not planet:
        pytest.skip("no homeworld")
    planet = dict(planet)
    planet["player_id"] = planet.get("player_id") or 1
    buildings = {"metal_mine": 2, "crystal_mine": 1, "solar_plant": 1}

    full_count = sum(len(rows or []) for rows in get_buildings_panel_rows(planet, buildings).values())
    delta = get_buildings_panel_delta(planet, buildings, building_keys=["metal_mine"])
    delta_count = sum(len(rows or []) for rows in delta.values())

    assert delta_count == 1
    assert full_count > delta_count
    row = delta["resources"][0]
    assert row["key"] == "metal_mine"
    assert "requirements_items" in row
    assert "can_afford" in row
    assert "resource_items" in row
    assert any(item.get("kind") == "resource" for item in row["resource_items"])


def test_buildings_unaffordable_action_uses_warn_resource_hover():
    tpl = _read("templates/buildings.html")
    chunks = tpl.split("{% elif not b.can_afford %}")
    chunk = chunks[2].split("{% else %}")[0]
    assert "gc-bld-head-action-btn--warn" in chunk
    assert "render_req_hover_attrs(b.resource_items)" in chunk
    assert "gc-bld-head-action-btn--afford" not in chunk


def test_research_unaffordable_action_uses_warn_resource_hover():
    tpl = _read("templates/research.html")
    chunks = tpl.split("{% elif not can_afford %}")
    chunk = chunks[2].split("{% else %}")[0]
    assert "gc-bld-head-action-btn--warn" in chunk
    assert "render_req_hover_attrs(tech.resource_items)" in chunk
    assert "gc-bld-head-action-btn--afford" not in chunk


def test_main_js_unaffordable_buildings_use_warn_hover():
    src = _read("static/main.js")
    assert "function unmetBuildingHoverItems" in src
    assert "function unmetResearchHoverItems" in src
    assert 'if (!b.can_afford) return "warn"' in src
    assert 'if (tech.can_afford === false) return "warn"' in src


def test_gc840_cancel_action_uses_delta(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})

    up = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc840-cancel-up-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()
    if not up.get("ok"):
        pytest.skip("upgrade failed in fixture")

    job_id = (up.get("job") or {}).get("job_id") or (up.get("job") or {}).get("id")
    if not job_id:
        queue = (up.get("state") or {}).get("build_queue") or {}
        jobs = queue.get("queue") or []
        job_id = jobs[0]["id"] if jobs else None
    assert job_id

    cancel = client.post(
        "/api/buildings/cancel",
        json={"job_id": int(job_id), "request_id": f"gc840-cancel-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()
    state = cancel.get("state") or {}
    assert "buildings_panel" not in state
    assert state.get("buildings_panel_delta")
