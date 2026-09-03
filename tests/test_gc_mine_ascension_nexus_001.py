"""GC-MINE-ASC-NEXUS-001 — Nexus-to-Ascension gameplay contract."""

from __future__ import annotations

import game.buildings as buildings_mod
import game.mine_evolution.service as evolution_service
from game.db import db
from game.effects.effect_resolver import EffectResolver
from game.mine_evolution import evolve_mine, get_evolution_rank
from game.models import get_homeworld, get_planet_buildings, save_planet_buildings

pytest_plugins = ["tests.test_game_state_live"]


def _fund(planet_id: int, amount: int = 100_000) -> None:
    conn = db()
    try:
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
            (int(amount), int(amount), int(planet_id)),
        )
        conn.commit()
    finally:
        conn.close()


def _row(rows_by_tab: dict, key: str) -> dict:
    return next(row for row in rows_by_tab.get("resources", []) if row.get("key") == key)


def test_rank_one_unlocks_only_the_ascended_mine_beyond_200(game_client, monkeypatch):
    _client, uid = game_client
    planet = get_homeworld(player_id=int(uid))
    assert planet is not None
    pid = int(planet["id"])

    buildings = get_planet_buildings(pid)
    buildings.update(
        {
            "planet_core_nexus": 50,
            "geothermal_nexus": 50,
            "metal_mine": 200,
            "crystal_mine": 200,
            "fuel_cell_plant": 200,
        }
    )
    save_planet_buildings(pid, buildings)
    _fund(pid)

    # Keep this regression about gating, not astronomical high-level balance costs.
    monkeypatch.setattr(buildings_mod, "get_upgrade_cost", lambda *_a, **_k: (1, 1))
    monkeypatch.setattr(
        buildings_mod.BuildingsPanelContext,
        "build_time_seconds",
        lambda self, building_type, target_level: 60,
    )

    base_resolver = EffectResolver(get_planet_buildings(pid), {})
    assert base_resolver.get_max_building_level("metal_mine") == 200
    assert base_resolver.get_max_building_level("crystal_mine") == 200

    # Rank 0 at L200 is the Ascension gate for every mine independently.
    ok, reason, blocked = buildings_mod.queue_build_for_planet(
        dict(planet),
        get_planet_buildings(pid),
        "metal_mine",
        user_id=int(uid),
    )
    assert not ok
    assert reason == "ascension_required"
    assert int(blocked["max_level"]) == 200

    ok, reason, asc = evolve_mine(int(uid), dict(planet), "metal_mine")
    assert ok, reason
    assert int(asc["evolution_rank"]) == 1
    assert get_evolution_rank(pid, "metal_mine") == 1
    assert get_evolution_rank(pid, "crystal_mine") == 0
    assert int(get_planet_buildings(pid)["metal_mine"]) == 200

    # SSR/card state must immediately expose 225 for metal, while crystal stays 200.
    conn = db()
    try:
        live_planet = dict(get_homeworld(player_id=int(uid), conn=conn))
        live_buildings = get_planet_buildings(pid, conn=conn)
        rows = buildings_mod.get_buildings_panel_rows(
            live_planet,
            live_buildings,
            active_tab="resources",
            conn=conn,
        )
    finally:
        conn.close()
    assert int(_row(rows, "metal_mine")["max_level"]) == 225
    assert int(_row(rows, "metal_mine")["evolution_rank"]) == 1
    assert int(_row(rows, "crystal_mine")["max_level"]) == 200
    assert int(_row(rows, "crystal_mine")["evolution_rank"]) == 0

    # The selected mine can build L201 immediately after Ascension I.
    ok, reason, queued = buildings_mod.queue_build_for_planet(
        dict(planet),
        get_planet_buildings(pid),
        "metal_mine",
        user_id=int(uid),
    )
    assert ok, reason
    assert int(queued["target_level"]) == 201

    # A different mine did not inherit that rank and remains at its own L200 gate.
    ok, reason, crystal_blocked = buildings_mod.queue_build_for_planet(
        dict(planet),
        get_planet_buildings(pid),
        "crystal_mine",
        user_id=int(uid),
    )
    assert not ok
    assert reason == "ascension_required"
    assert int(crystal_blocked["max_level"]) == 200
    assert int(crystal_blocked["evolution_rank"]) == 0


def test_legacy_level_387_can_catch_up_then_build_toward_400(game_client, monkeypatch):
    _client, uid = game_client
    planet = get_homeworld(player_id=int(uid))
    assert planet is not None
    pid = int(planet["id"])

    levels = get_planet_buildings(pid)
    levels.update(
        {
            "planet_core_nexus": 50,
            "geothermal_nexus": 50,
            "metal_mine": 387,
        }
    )
    save_planet_buildings(pid, levels)
    _fund(pid)

    # Simulate a legacy/high-level mine whose persisted rank still stops at the
    # L375 milestone. The level is never reduced; one sequential catch-up
    # Ascension raises this mine's next gate to L400.
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO planet_mine_evolution (planet_id, building_type, evolution_rank, updated_at)
            VALUES (?, 'metal_mine', 7, 0)
            ON CONFLICT(planet_id, building_type) DO UPDATE SET evolution_rank = 7;
            """,
            (pid,),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(evolution_service, "tribute_cost_for_next_rank", lambda *_a, **_k: (1, 1))
    monkeypatch.setattr(buildings_mod, "get_upgrade_cost", lambda *_a, **_k: (1, 1))
    monkeypatch.setattr(
        buildings_mod.BuildingsPanelContext,
        "build_time_seconds",
        lambda self, building_type, target_level: 60,
    )

    ok, reason, blocked = buildings_mod.queue_build_for_planet(
        dict(planet), get_planet_buildings(pid), "metal_mine", user_id=int(uid)
    )
    assert not ok
    assert reason == "ascension_required"
    assert int(blocked["max_level"]) == 375
    assert int(blocked["evolution_rank"]) == 7
    assert int(get_planet_buildings(pid)["metal_mine"]) == 387

    ok, reason, asc = evolve_mine(int(uid), dict(planet), "metal_mine")
    assert ok, reason
    assert int(asc["evolution_rank"]) == 8
    assert int(get_planet_buildings(pid)["metal_mine"]) == 387

    ok, reason, queued = buildings_mod.queue_build_for_planet(
        dict(planet), get_planet_buildings(pid), "metal_mine", user_id=int(uid)
    )
    assert ok, reason
    assert int(queued["target_level"]) == 388
    assert int(queued["max_level"]) == 400


def test_rank_progression_extends_exact_next_milestone_per_mine():
    assert buildings_mod._effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=0
    ) == 200
    assert buildings_mod._effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=1
    ) == 225
    assert buildings_mod._effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=2
    ) == 250
    assert buildings_mod._effective_building_queue_cap(
        "crystal_mine", 137, planet_id=1, evolution_rank=0
    ) == 137


def test_ascension_vacation_probe_reuses_mutation_connection():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "game"
        / "mine_evolution"
        / "service.py"
    ).read_text(encoding="utf-8")
    block = source.split("def evolve_mine(", 1)[1]
    assert "vacation_blocks_outbound(int(user_id), conn=conn)" in block
    assert "vacation_blocks_outbound(int(user_id), conn=db())" not in block
