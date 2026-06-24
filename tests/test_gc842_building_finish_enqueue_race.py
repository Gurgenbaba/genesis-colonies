"""
GC-842 — Finish + immediate enqueue returns consistent buildings_panel_delta.

Run: python -m pytest tests/test_gc842_building_finish_enqueue_race.py -v
"""

from __future__ import annotations

import time
import uuid

import pytest

pytest_plugins = ["tests.test_game_state_live"]

from game.models import add_build_job, get_homeworld, get_planet_buildings


def _set_buildings(planet_id: int, levels: dict) -> None:
    from game.models import save_planet_buildings

    save_planet_buildings(planet_id, levels)


def _starter_levels() -> dict:
    return {
        "metal_mine": 1,
        "crystal_mine": 1,
        "solar_plant": 1,
        "metal_storage": 1,
        "crystal_storage": 1,
    }


def test_gc842_upgrade_after_due_job_finishes_and_requeues(game_client):
    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    _set_buildings(planet_id, _starter_levels())

    now = time.time()
    add_build_job(planet_id, "metal_mine", now - 120, now - 1)

    before = get_planet_buildings(planet_id)
    assert int(before.get("metal_mine") or 0) == 1

    body = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc842-race-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    ).get_json()

    assert body.get("ok") is True, body
    state = body.get("state") or {}
    assert "buildings_panel" not in state

    delta = state.get("buildings_panel_delta") or {}
    flat = [row for rows in delta.values() for row in (rows or [])]
    row = next((x for x in flat if x.get("key") == "metal_mine"), None)
    assert row is not None
    assert int(row.get("level") or 0) == 2
    assert row.get("queue_job"), "delta must include new queue_job after finish+enqueue"
    assert int(row.get("queue_count") or 0) >= 1

    owners = (state.get("build_queue") or {}).get("card_jobs_by_owner") or {}
    assert "metal_mine" in owners

    after = get_planet_buildings(planet_id)
    assert int(after.get("metal_mine") or 0) == 2

    queue = (state.get("build_queue") or {}).get("queue") or []
    assert any(str(j.get("building_type") or "") == "metal_mine" for j in queue)


def test_gc842_finish_delta_endpoint_after_manual_finish(game_client):
    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    _set_buildings(planet_id, _starter_levels())

    now = time.time()
    add_build_job(planet_id, "metal_mine", now - 120, now - 1)

    body = client.get("/api/game-state?panel_delta_buildings=metal_mine").get_json()
    assert body.get("ok") is True
    assert "buildings_panel" not in body
    delta = body.get("buildings_panel_delta") or {}
    flat = [row for rows in delta.values() for row in (rows or [])]
    row = next((x for x in flat if x.get("key") == "metal_mine"), None)
    assert row is not None
    assert int(row.get("level") or 0) == 2
    assert not row.get("queue_job")
