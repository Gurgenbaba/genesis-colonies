"""Unbounded runtime arithmetic contracts for fleet cargo and weighted allocation."""

from __future__ import annotations

from pathlib import Path

from game.exact_math import scale_int
from game.expedition_events import calculate_expedition_loot_cap
from game.fleet_calc import calculate_total_cargo, split_ships_by_weights

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400


def test_total_cargo_scales_10_pow_400_ship_count_without_float_roundtrip():
    unit_cargo = calculate_total_cargo({"mule_courier": 1})
    assert unit_cargo > 0

    total = calculate_total_cargo(
        {"mule_courier": HUGE},
        cargo_multiplier=1.5,
    )

    assert total == (unit_cargo * HUGE * 3) // 2


def test_expedition_cargo_cap_can_be_scaled_exactly_at_10_pow_400():
    unit_cap = calculate_expedition_loot_cap({"solar_skiff": 1})
    huge_cap = calculate_expedition_loot_cap({"solar_skiff": HUGE})

    assert unit_cap > 0
    assert huge_cap == unit_cap * HUGE
    assert scale_int(huge_cap, 1.25) == (huge_cap * 5) // 4


def test_weighted_ship_split_handles_10_pow_400_quantities_exactly():
    total = HUGE * 6
    parts = split_ships_by_weights(
        {"falcon_interceptor": total},
        [1, 2, 3],
    )

    assert parts == [
        {"falcon_interceptor": HUGE},
        {"falcon_interceptor": HUGE * 2},
        {"falcon_interceptor": HUGE * 3},
    ]
    assert sum(int(part.get("falcon_interceptor", 0)) for part in parts) == total


def test_weighted_ship_split_tie_break_stays_stable():
    parts = split_ships_by_weights(
        {"falcon_interceptor": 1},
        [HUGE, HUGE],
    )
    assert parts == [{"falcon_interceptor": 1}, {}]


def test_fleet_big_number_sources_have_no_cargo_or_split_float_roundtrip():
    fleet = (ROOT / "game" / "fleet.py").read_text(encoding="utf-8")
    calc = (ROOT / "game" / "fleet_calc.py").read_text(encoding="utf-8")

    assert "scale_int(calculate_expedition_loot_cap(ships), cargo_mult)" in fleet
    assert "math.floor(float(calculate_expedition_loot_cap(ships))" not in fleet

    assert "total = scale_int(total, mult)" in calc
    assert "total * mult" not in calc

    assert "products = [qty * wi for wi in w]" in calc
    assert "product // total_w" in calc
    assert "product % total_w" in calc
    assert "(qty * wi) / float(total_w)" not in calc
