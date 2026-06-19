"""Expedition loot — full cargo fill on positive outcomes, event-driven split."""

from __future__ import annotations

import pytest

from game.expedition_events import (
    calculate_expedition_loot_cap,
    calculate_fleet_value,
    resolve_expedition_outcome,
)


def _large_fleet_ships() -> dict[str, int]:
    return {
        "seed_ark": 80,
        "ironclad_frigate": 120,
        "falcon_interceptor": 200,
        "solar_skiff": 10,
    }


def test_calculate_fleet_value_uses_ship_scores():
    ships = {"solar_skiff": 2, "falcon_interceptor": 1}
    expected = 2 * 7000 + 1 * 4000
    assert calculate_fleet_value(ships) == expected


def test_calculate_fleet_value_fallback_to_expedition_hull_count():
    from game.fleet_defs import ship_score_value

    assert calculate_fleet_value({}, expedition_ship_count=3) == 3 * ship_score_value("solar_skiff")


def test_positive_loot_fills_entire_cargo_capacity():
    cargo_cap = 9_900_000
    ships = _large_fleet_ships()

    for movement_id in range(1, 301):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_cap,
            ships=ships,
            expedition_ship_count=10,
            flight_seconds=120,
        )
        if outcome["event_key"] == "mineral_deposit":
            assert int(outcome["reward_total"]) == cargo_cap
            rewards = outcome["rewards"]
            assert sum(int(rewards[k]) for k in rewards) == cargo_cap
            assert int(rewards["metal"]) > 0
            assert int(rewards["crystal"]) > 0
            assert int(rewards.get("fuel_cells") or 0) == 0
            return
    pytest.fail("no mineral_deposit in sample")


def test_exact_cargo_fill_for_small_cap():
    cargo_cap = 67_867
    ships = {"solar_skiff": 1}

    for movement_id in range(1, 200):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_cap,
            ships=ships,
            expedition_ship_count=1,
            flight_seconds=60,
        )
        if outcome["event_key"] in {"mineral_deposit", "fuel_cache", "debris_salvage"}:
            assert int(outcome["reward_total"]) == cargo_cap
            return
    pytest.fail("no loot event in sample")


def test_loot_never_exceeds_cargo():
    ships = _large_fleet_ships()
    cargo_cap = calculate_expedition_loot_cap(ships)

    for movement_id in range(1, 201):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_cap,
            ships=ships,
            expedition_ship_count=10,
            flight_seconds=120,
        )
        assert int(outcome["reward_total"]) <= cargo_cap


def test_no_loot_events_return_zero():
    ships = _large_fleet_ships()
    for movement_id in range(1, 500):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=1_000_000,
            ships=ships,
            expedition_ship_count=10,
            flight_seconds=120,
        )
        if outcome["event_key"] in {"void_scan", "sensor_glitch", "nav_interference"}:
            assert int(outcome["reward_total"]) == 0


def test_outcome_deterministic_for_same_movement_and_fleet():
    ships = _large_fleet_ships()
    kwargs = dict(
        cargo_total=500_000,
        ships=ships,
        expedition_ship_count=10,
        flight_seconds=120,
    )
    first = resolve_expedition_outcome(4242, **kwargs)
    second = resolve_expedition_outcome(4242, **kwargs)
    assert first == second


def test_event_type_controls_distribution_not_total():
    cargo_cap = 1_000_000
    ships = {"solar_skiff": 5}

    mineral = fuel = None
    for movement_id in range(1, 400):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_cap,
            ships=ships,
            expedition_ship_count=5,
            flight_seconds=60,
        )
        if outcome["event_key"] == "mineral_deposit" and mineral is None:
            mineral = outcome["rewards"]
        elif outcome["event_key"] == "fuel_cache" and fuel is None:
            fuel = outcome["rewards"]
        if mineral and fuel:
            break

    assert mineral and fuel
    assert sum(mineral.values()) == cargo_cap
    assert sum(fuel.values()) == cargo_cap
    assert int(fuel["fuel_cells"]) > int(mineral.get("fuel_cells") or 0)


def test_resource_split_mineral_mostly_ores():
    cargo_cap = 500_000
    for movement_id in range(1, 200):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_cap,
            ships={"solar_skiff": 5},
            expedition_ship_count=5,
            flight_seconds=60,
        )
        if outcome["event_key"] != "mineral_deposit":
            continue
        rewards = outcome["rewards"]
        metal = int(rewards["metal"])
        crystal = int(rewards["crystal"])
        total = metal + crystal
        assert total == cargo_cap
        assert 0.45 <= metal / total <= 0.60
        assert 0.40 <= crystal / total <= 0.55
        return
    pytest.fail("no mineral_deposit in sample")


def test_resource_split_fuel_cache_mostly_fuel():
    cargo_cap = 500_000
    for movement_id in range(1, 200):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_cap,
            ships={"solar_skiff": 5},
            expedition_ship_count=5,
            flight_seconds=60,
        )
        if outcome["event_key"] != "fuel_cache":
            continue
        rewards = outcome["rewards"]
        total = sum(int(rewards[k]) for k in rewards)
        assert total == cargo_cap
        assert int(rewards["fuel_cells"]) / total >= 0.75
        return
    pytest.fail("no fuel_cache in sample")


def test_zero_cargo_yields_zero_loot_even_on_loot_event():
    for movement_id in range(1, 100):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=0,
            ships={"solar_skiff": 1},
            expedition_ship_count=1,
            flight_seconds=60,
        )
        if outcome["event_key"] in {"mineral_deposit", "ancient_stash"}:
            assert int(outcome["reward_total"]) == 0
            return
    pytest.fail("no loot event in sample")


def test_directive_loot_mult_scales_fill_below_cargo_cap():
    cargo = 1_000_000
    full = resolve_expedition_outcome(
        42,
        cargo_total=cargo,
        expedition_ship_count=3,
        flight_seconds=120,
        directive_flags={"expedition_loot_mult": 1.0},
    )
    reduced = resolve_expedition_outcome(
        42,
        cargo_total=cargo,
        expedition_ship_count=3,
        flight_seconds=120,
        directive_flags={"expedition_loot_mult": 0.5},
    )
    if int(full.get("reward_total") or 0) > 0:
        assert int(full["reward_total"]) == cargo
        assert int(reduced["reward_total"]) == cargo // 2
