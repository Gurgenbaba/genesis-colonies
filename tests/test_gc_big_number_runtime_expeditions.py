"""Unbounded runtime arithmetic contract for expeditions."""

from __future__ import annotations

import math
import random
from pathlib import Path

from game.exact_math import (
    bounded_ratio_float,
    mul_div_floor,
    scale_int,
    sqrt_scaled_int,
)
from game.expedition_events import (
    EXPEDITION_LOOT_EXPONENT,
    _apply_cargo_cap,
    _compute_event_loot,
    _split_loot_total,
    apply_expedition_ship_losses,
    calculate_expo_value,
    expedition_ship_fleet_value,
    soft_cap_pirate_budget,
    virtual_pirate_fleet,
)

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400
ODYSSEY = "solar_skiff"


def test_exact_math_scales_beyond_ieee754_range():
    assert scale_int(HUGE, "0.125") == HUGE // 8
    assert scale_int(HUGE, "1.5", rounding="half_even") == (HUGE * 3) // 2
    assert mul_div_floor(HUGE, 7, 20) == (HUGE * 7) // 20
    assert bounded_ratio_float(HUGE, HUGE * 4) == 0.25
    assert sqrt_scaled_int(HUGE, "2.5") == 25 * 10**199


def test_normal_expo_reference_stays_compatible():
    hull_value = expedition_ship_fleet_value(ODYSSEY)
    per_hull = math.pow(hull_value, EXPEDITION_LOOT_EXPONENT)
    for amount in (1, 10, 100, 10_000):
        assert calculate_expo_value({ODYSSEY: amount}) == int(amount * per_hull)


def test_expo_value_is_linear_at_10_pow_400_hulls():
    one = calculate_expo_value({ODYSSEY: HUGE})
    two = calculate_expo_value({ODYSSEY: HUGE * 2})
    assert one > HUGE
    assert abs(two - (one * 2)) <= 1


def test_loot_split_and_cargo_scaling_handle_10_pow_400():
    split = _split_loot_total(
        HUGE,
        {"metal": 0.70, "crystal": 0.25, "fuel_cells": 0.05},
    )
    assert sum(split.values()) == HUGE
    assert split["metal"] == scale_int(HUGE, "0.70")
    assert split["crystal"] == scale_int(HUGE, "0.25")

    rewards = {
        "metal": HUGE,
        "crystal": HUGE,
        "fuel_cells": HUGE,
    }
    cargo = HUGE + 7
    _apply_cargo_cap(rewards, cargo)
    assert sum(rewards.values()) <= cargo
    assert sum(rewards.values()) >= cargo - 2


def test_event_loot_handles_huge_expo_without_float_overflow():
    rewards, debug = _compute_event_loot(
        random.Random(9917),
        "mineral_deposit",
        HUGE,
        cargo_total=HUGE * 4,
        event_factor=1.0,
        loot_quality_mult=1.25,
    )
    assert debug["expo_value"] == HUGE
    assert debug["raw_loot_total"] > 0
    assert sum(rewards.values()) == debug["raw_loot_total"]
    assert sum(rewards.values()) <= HUGE * 4


def test_ship_loss_budget_is_exact_for_huge_counts():
    fleet = {"solar_skiff": HUGE, "eclipse_runner": HUGE}
    remaining, losses = apply_expedition_ship_losses(
        fleet,
        25,
        min_remaining=1,
    )
    assert sum(losses.values()) == HUGE // 2
    assert sum(remaining.values()) == (HUGE * 3) // 2


def test_pirate_soft_cap_and_virtual_fleet_work_beyond_float_range():
    budget = soft_cap_pirate_budget(HUGE)
    assert budget > 0
    assert budget < HUGE

    fleet = virtual_pirate_fleet(HUGE, seed=987654)
    assert fleet
    assert all(isinstance(value, int) and value > 0 for value in fleet.values())


def test_expedition_source_has_no_unbounded_float_roundtrips():
    source = (ROOT / "game" / "expedition_events.py").read_text(encoding="utf-8")

    for forbidden in (
        "total = 0.0",
        "return float(max(0, int(expo_value)))",
        "int(total * share)",
        "base_loot * random_factor * profile_mult",
        "cargo_total / max(1, loaded)",
        "total * loss_pct / 100.0",
        "math.sqrt(float(over))",
        "int(budget * enemy_factor)",
        "remaining = float(pts)",
    ):
        assert forbidden not in source

    assert "sum_products_floor(terms)" in source
    assert "sqrt_scaled_int(over, _PIRATE_BUDGET_SOFT_SQRT_SCALE)" in source
