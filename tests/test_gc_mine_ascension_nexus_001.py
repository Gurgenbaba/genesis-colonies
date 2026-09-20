"""Nodebuster mine progression integration contract."""

from __future__ import annotations

import pytest

import game.buildings as buildings_mod
from game.db import db
from game.mine_evolution import evolve_mine
from game.mine_evolution.nodebuster import (
    QUEUE_SAFETY_SENTINEL,
    get_state,
    purchase_skill,
)
from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

pytest_plugins = ["tests.test_game_state_live"]


def _fund(planet_id: int, amount: int = 10**9) -> None:
    conn = db()
    try:
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
            (int(amount), int(amount), int(planet_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _set_level(uid: int, level: int) -> dict:
    planet = dict(get_homeworld(player_id=int(uid)))
    levels = get_planet_buildings(int(planet["id"]))
    levels["planet_core_nexus"] = 50
    levels["geothermal_nexus"] = 50
    levels["metal_mine"] = int(level)
    save_planet_buildings(int(planet["id"]), levels)
    return planet


def test_nodebuster_mines_have_no_ascension_hard_gate(game_client, monkeypatch):
    _client, uid = game_client
    planet = _set_level(uid, 200)
    pid = int(planet["id"])
    _fund(pid)

    monkeypatch.setattr(buildings_mod, "get_upgrade_cost", lambda *_a, **_k: (1, 1))
    monkeypatch.setattr(
        buildings_mod.BuildingsPanelContext,
        "build_time_seconds",
        lambda self, building_type, target_level: 60,
    )

    cap = buildings_mod._effective_building_queue_cap(
        "metal_mine",
        200,
        planet_id=pid,
        evolution_rank=0,
    )
    assert cap == QUEUE_SAFETY_SENTINEL

    ok, reason, queued = buildings_mod.queue_build_for_planet(
        dict(planet),
        get_planet_buildings(pid),
        "metal_mine",
        user_id=int(uid),
    )
    assert ok, reason
    assert int(queued["target_level"]) == 201
    assert int(queued["max_level"]) == QUEUE_SAFETY_SENTINEL


def test_rebuild_skills_discount_cost_and_time_only_through_best_depth(game_client, monkeypatch):
    _client, uid = game_client
    planet = _set_level(uid, 400)
    pid = int(planet["id"])
    _fund(pid)

    ok, reason, asc = evolve_mine(int(uid), dict(planet), "metal_mine")
    assert ok, reason
    assert asc["points_gain"] == 11
    assert int(get_planet_buildings(pid)["metal_mine"]) == 0

    ok, reason, _ = purchase_skill(int(uid), dict(planet), "metal_mine", "frugal_rebuild")
    assert ok, reason
    ok, reason, _ = purchase_skill(int(uid), dict(planet), "metal_mine", "rapid_rebuild")
    assert ok, reason

    monkeypatch.setattr(buildings_mod, "get_upgrade_cost", lambda *_a, **_k: (100, 100))
    monkeypatch.setattr(
        buildings_mod.BuildingsPanelContext,
        "build_time_seconds",
        lambda self, building_type, target_level: 100,
    )

    ok, reason, queued = buildings_mod.queue_build_for_planet(
        dict(planet),
        get_planet_buildings(pid),
        "metal_mine",
        user_id=int(uid),
    )
    assert ok, reason
    assert int(queued["duration"]) == 95

    conn = db()
    try:
        row = conn.execute(
            """
            SELECT cost_metal, cost_crystal, start_time, finish_time
            FROM build_queue
            WHERE planet_id = ? AND building_type = 'metal_mine'
            ORDER BY id DESC LIMIT 1;
            """,
            (pid,),
        ).fetchone()
        assert row is not None
        assert int(row["cost_metal"]) == 96
        assert int(row["cost_crystal"]) == 96
        assert round(float(row["finish_time"]) - float(row["start_time"])) == 95
    finally:
        conn.close()


def test_ascension_preserves_lifetime_building_score(game_client):
    _client, uid = game_client
    planet = _set_level(uid, 250)
    pid = int(planet["id"])

    from game.ranking import compute_player_scores

    before = compute_player_scores(int(uid))["building_score"]
    assert before > 0

    ok, reason, _ = evolve_mine(int(uid), dict(planet), "metal_mine")
    assert ok, reason
    assert int(get_planet_buildings(pid)["metal_mine"]) == 0

    after = compute_player_scores(int(uid))["building_score"]
    assert after == before
    assert get_state(pid, "metal_mine")["best_depth"] == 250


def test_nodebuster_vacation_probe_reuses_mutation_connection():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "game"
        / "mine_evolution"
        / "nodebuster.py"
    ).read_text(encoding="utf-8")
    block = source.split("def ascend_mine(", 1)[1]
    assert "vacation_blocks_outbound(int(user_id), conn=conn)" in block
    assert "vacation_blocks_outbound(int(user_id), conn=db())" not in block
