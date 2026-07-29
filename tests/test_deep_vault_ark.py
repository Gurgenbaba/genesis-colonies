"""Deep Vault Ark — save hauler hull (live-alpha feedback)."""

from __future__ import annotations

import random
import uuid
import math

import pytest

from game.combat import simulate_battle
from game.combat_models import COMBAT_UNIT_SHIP, combat_stats_for_ship, make_combat_side, stacks_from_counts
from game.db import db
from game.expedition_events import calculate_expo_value, count_expedition_ships, expedition_ship_fleet_value
from game.fleet import preview_fleet_flight
from game.fleet_calc import calculate_distance, calculate_flight_seconds, calculate_fuel_cost, calculate_total_cargo
from game.fleet_defs import ACTIVE_SHIP_KEYS, SHIPS, get_ship
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db
from game.shipyard import build_ships


@pytest.fixture
def save_ship_db(tmp_path, monkeypatch):
    db_path = tmp_path / "deep_vault_ark.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"dva_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Saver", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _grant_prereqs(conn, uid: int, planet_id: int) -> None:
    conn.execute(
        """
        UPDATE planet_buildings
        SET orbital_shipyard = 10, metal_storage = 10, crystal_storage = 10,
            research_lab = 10, command_center = 10
        WHERE planet_id = ?;
        """,
        (int(planet_id),),
    )
    for tech in ("storage_tech", "mining_tech", "fuel_efficiency"):
        conn.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (int(uid), tech, 10),
        )
    conn.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (500_000, 500_000, 500_000, int(planet_id)),
    )


def test_deep_vault_ark_definition():
    assert "deep_vault_ark" in ACTIVE_SHIP_KEYS
    spec = get_ship("deep_vault_ark")
    assert spec is not None
    assert spec["role"] == "cargo"
    assert int(spec["cargo"]) >= 100000
    assert int(spec["speed"]) <= 500
    assert int(spec["fuel"]) == 25
    assert int(spec["attack"]) <= 5
    assert int(spec["required_shipyard_level"]) >= 6
    assert int(spec["build_seconds"]) <= 260


def test_deep_vault_ark_fuel_rebalance():
    """Save hauler: lower fuel stat than pre-rebalance (120); transporters unchanged."""
    assert int(SHIPS["mule_courier"]["fuel"]) == 10
    assert int(SHIPS["atlas_hauler"]["fuel"]) == 50

    adj_system = calculate_distance((1, 1, 5), (1, 2, 5))
    cross_galaxy = calculate_distance((1, 1, 5), (2, 1, 5))

    ark_adj = calculate_fuel_cost({"deep_vault_ark": 1}, adj_system, 100)
    ark_cross = calculate_fuel_cost({"deep_vault_ark": 1}, cross_galaxy, 100)
    pre_adj = int(math.ceil(120 * adj_system / 35000.0))
    pre_cross = int(math.ceil(120 * cross_galaxy / 35000.0))

    assert ark_adj < pre_adj
    assert ark_cross < pre_cross
    assert pre_adj == 14
    assert pre_cross == 82

    mule_small = calculate_fuel_cost({"mule_courier": 1}, adj_system, 100)
    atlas_routine = calculate_fuel_cost({"atlas_hauler": 1}, adj_system, 100)
    assert ark_adj > mule_small
    assert ark_adj < atlas_routine

    full_save_equiv = calculate_fuel_cost({"mule_courier": 20}, adj_system, 100)
    assert ark_adj < full_save_equiv


def test_deep_vault_ark_not_expedition_loot_ship():
    assert expedition_ship_fleet_value("deep_vault_ark") == 0
    assert count_expedition_ships({"deep_vault_ark": 3}) == 0
    assert calculate_expo_value({"deep_vault_ark": 5, "solar_skiff": 1}) > 0


def test_deep_vault_ark_cargo_and_slow_preview(save_ship_db):
    assert calculate_total_cargo({"deep_vault_ark": 2}) == 200000
    atlas = int(SHIPS["atlas_hauler"]["speed"])
    ark = int(SHIPS["deep_vault_ark"]["speed"])
    assert ark < atlas
    slow = calculate_flight_seconds(1000, ark, 100)
    fast = calculate_flight_seconds(1000, atlas, 100)
    assert slow > fast * 5

    uid = _player()
    conn = db()
    try:
        hw = get_homeworld(uid, conn=conn)
        origin = dict(hw)
        # Use a guaranteed different in-system slot. Position 1 previously made
        # target_position=max(1, pos-1) collapse to the same coords → distance 0
        # and flight_seconds=0 under random homeworld placement.
        origin_pos = int(origin["position"])
        target_pos = 2 if origin_pos == 1 else origin_pos - 1
        preview = preview_fleet_flight(
            origin_planet=origin,
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=target_pos,
            ships={"deep_vault_ark": 1},
            resources={},
            speed_percent=100,
            player_id=uid,
            mission_type="transport",
            conn=conn,
        )
        assert int(preview["flight_seconds"]) > 0
        assert int(preview["cargo_total"]) == 100000
        assert int(preview["fuel_cost"]) == calculate_fuel_cost(
            {"deep_vault_ark": 1},
            int(preview["distance"]),
            100,
            fuel_efficiency_level=0,
        )
    finally:
        conn.close()


def test_deep_vault_ark_build(save_ship_db):
    uid = _player()
    conn = db()
    try:
        hw = get_homeworld(uid, conn=conn)
        pid = int(hw["id"])
        _grant_prereqs(conn, uid, pid)
        conn.commit()
        ok, reason, result = build_ships(
            player_id=uid, planet_id=pid, ship_key="deep_vault_ark", amount=1, conn=conn
        )
        assert ok, reason
        assert int(result.get("queued") or result.get("amount") or 1) >= 1
    finally:
        conn.close()


def test_deep_vault_ark_combat_does_not_crash():
    stats = combat_stats_for_ship("deep_vault_ark")
    assert stats is not None
    attacker = make_combat_side(
        "attacker",
        stacks_from_counts({"deep_vault_ark": 2}, unit_type=COMBAT_UNIT_SHIP),
    )
    defender = make_combat_side(
        "defender",
        stacks_from_counts({"falcon_interceptor": 1}, unit_type=COMBAT_UNIT_SHIP),
    )
    outcome = simulate_battle(attacker, defender, rng=random.Random(42))
    assert outcome.winner in ("attacker", "defender", "draw")
