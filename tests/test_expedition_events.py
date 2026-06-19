"""Expedition loot scaling — fleet value, cargo cap, determinism."""

from __future__ import annotations

import pytest

from game.expedition_events import (
    EXPEDITION_LOOT_FACTOR,
    calculate_fleet_value,
    resolve_expedition_outcome,
)

# ~13,024,000 fleet score (matches reported full-fleet expeditions).
_LARGE_FLEET = {"seed_ark": 163}
_LARGE_FLEET_VALUE = calculate_fleet_value(_LARGE_FLEET)

_SMALL_FLEET = {"solar_skiff": 1}
_SMALL_FLEET_VALUE = calculate_fleet_value(_SMALL_FLEET)


def _find_movement_for_event(event_key: str, *, ships: dict, cargo_total: int = 5_000_000) -> int:
    for movement_id in range(1, 5000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_total,
            expedition_ship_count=1,
            flight_seconds=120,
            ships=ships,
        )
        if outcome["event_key"] == event_key:
            return movement_id
    raise AssertionError(f"no movement_id produced event {event_key!r}")


def test_calculate_fleet_value_uses_ship_scores():
    assert _LARGE_FLEET_VALUE == pytest.approx(13_040_000, rel=0.01)
    assert _SMALL_FLEET_VALUE == 7000


def test_large_fleet_loot_beats_old_flat_ceiling():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_LARGE_FLEET)
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=5_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    assert outcome["event_key"] == "mineral_deposit"
    assert int(outcome["reward_total"]) > 67_867
    assert int(outcome["reward_total"]) >= 200_000


def test_large_fleet_mineral_and_debris_in_target_band():
    for event_key in ("mineral_deposit", "debris_salvage"):
        movement_id = _find_movement_for_event(event_key, ships=_LARGE_FLEET)
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=5_000_000,
            expedition_ship_count=1,
            flight_seconds=120,
            ships=_LARGE_FLEET,
        )
        total = int(outcome["reward_total"])
        assert total > 67_867
        assert 200_000 <= total <= 900_000


def test_ancient_stash_can_exceed_normal_events():
    movement_id = _find_movement_for_event("ancient_stash", ships=_LARGE_FLEET)
    ancient = resolve_expedition_outcome(
        movement_id,
        cargo_total=5_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    mineral_id = _find_movement_for_event("mineral_deposit", ships=_LARGE_FLEET)
    mineral = resolve_expedition_outcome(
        mineral_id,
        cargo_total=5_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    assert int(ancient["reward_total"]) > int(mineral["reward_total"])


def test_large_fleet_produces_much_more_than_small_fleet():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_LARGE_FLEET)
    large = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    small = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
    )
    assert int(large["reward_total"]) > int(small["reward_total"]) * 10


def test_small_fleet_still_produces_modest_loot():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_SMALL_FLEET)
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=50_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
    )
    total = int(outcome["reward_total"])
    assert 200 <= total <= 25_000


def test_loot_capped_by_cargo_capacity():
    movement_id = _find_movement_for_event("ancient_stash", ships=_LARGE_FLEET)
    cargo_cap = 12_345
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=cargo_cap,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    assert int(outcome["reward_total"]) <= cargo_cap


def test_outcome_deterministic_for_same_movement_and_fleet():
    kwargs = dict(
        cargo_total=250_000,
        expedition_ship_count=2,
        flight_seconds=90,
        ships={"solar_skiff": 2, "falcon_interceptor": 10},
    )
    first = resolve_expedition_outcome(9001, **kwargs)
    second = resolve_expedition_outcome(9001, **kwargs)
    assert first == second


def test_event_multiplier_changes_loot_magnitude():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_LARGE_FLEET)
    mineral = resolve_expedition_outcome(
        movement_id,
        cargo_total=5_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    ancient_id = _find_movement_for_event("ancient_stash", ships=_LARGE_FLEET)
    ancient = resolve_expedition_outcome(
        ancient_id,
        cargo_total=5_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    assert int(ancient["reward_total"]) > int(mineral["reward_total"])


def test_sqrt_scaling_formula_reference():
    import math

    loot_score = math.sqrt(_LARGE_FLEET_VALUE)
    base_loot = loot_score * EXPEDITION_LOOT_FACTOR
    assert base_loot == pytest.approx(342_527, rel=0.01)
