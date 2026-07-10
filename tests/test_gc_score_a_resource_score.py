"""
GC-SCORE-A — canonical resource_score module tests.

Run: python -m pytest tests/test_gc_score_a_resource_score.py -v
"""

from __future__ import annotations

import pytest

from game.production_formula import STANDARD_PRODUCTION_PER_HOUR
from game.resource_score import (
    RESOURCE_SCORE_DIVISORS,
    SCORE_CRYSTAL_DIVISOR,
    SCORE_FUEL_DIVISOR,
    SCORE_METAL_DIVISOR,
    add_score_from_cost_dicts,
    normalize_cost_dict,
    production_ratio_matches_score_divisors,
    score_from_cost_dict,
    score_from_resources,
    score_neutral_exchange_rates,
)


def test_divisors_match_production_3_2_1_ratio():
    metal = STANDARD_PRODUCTION_PER_HOUR["metal"]
    crystal = STANDARD_PRODUCTION_PER_HOUR["crystal"]
    fuel = STANDARD_PRODUCTION_PER_HOUR["fuel_cells"]
    assert metal / crystal == pytest.approx(1.5)
    assert metal / fuel == pytest.approx(3.0)
    assert crystal / fuel == pytest.approx(2.0)
    assert SCORE_METAL_DIVISOR / SCORE_CRYSTAL_DIVISOR == pytest.approx(1.5)
    assert SCORE_METAL_DIVISOR / SCORE_FUEL_DIVISOR == pytest.approx(3.0)
    assert SCORE_CRYSTAL_DIVISOR / SCORE_FUEL_DIVISOR == pytest.approx(2.0)
    assert production_ratio_matches_score_divisors() is True


def test_score_from_resources_single_resource_floor():
    assert score_from_resources(metal=1500) == 1
    assert score_from_resources(crystal=1000) == 1
    assert score_from_resources(fuel_cells=500) == 1
    assert score_from_resources(metal=1499) == 0
    assert score_from_resources(crystal=999) == 0
    assert score_from_resources(fuel_cells=499) == 0


def test_score_from_resources_combined():
    # 1M Ferronit in storage
    assert score_from_resources(metal=1_000_000) == 666
    # Building example from SCORE_SYSTEM.md
    assert score_from_resources(metal=450_000, crystal=300_000, fuel_cells=50_000) == 700
    # Research cumulative example: 7000/1500 + 3500/1000 + 500/500 = 4+3+1
    assert score_from_resources(metal=7_000, crystal=3_500, fuel_cells=500) == 8
    # Ship example: 60k / 40k / 10k
    assert score_from_resources(metal=60_000, crystal=40_000, fuel_cells=10_000) == 100


def test_score_from_resources_clamps_negative():
    assert score_from_resources(metal=-500, crystal=-1, fuel_cells=-99) == 0


def test_score_from_cost_dict():
    assert score_from_cost_dict({"metal": 60_000, "crystal": 40_000, "fuel_cells": 10_000}) == 100
    assert score_from_cost_dict({"metal": 1500}) == 1
    assert score_from_cost_dict({}) == 0
    assert score_from_cost_dict(None) == 0


def test_normalize_cost_dict():
    assert normalize_cost_dict({"metal": "1500", "crystal": 0.0}) == {
        "metal": 1500,
        "crystal": 0,
        "fuel_cells": 0,
    }
    assert normalize_cost_dict({"metal": -10, "fuel_cells": 500}) == {
        "metal": 0,
        "crystal": 0,
        "fuel_cells": 500,
    }


def test_add_score_from_cost_dicts_research_levels():
    levels = (
        {"metal": 1000, "crystal": 500, "fuel_cells": 0},
        {"metal": 2000, "crystal": 1000, "fuel_cells": 0},
        {"metal": 4000, "crystal": 2000, "fuel_cells": 500},
    )
    assert add_score_from_cost_dicts(*levels) == score_from_resources(
        metal=7_000, crystal=3_500, fuel_cells=500
    )


def test_hundred_ships_scale_linearly():
    unit = {"metal": 60_000, "crystal": 40_000, "fuel_cells": 10_000}
    assert score_from_cost_dict(unit) * 100 == score_from_resources(
        metal=6_000_000, crystal=4_000_000, fuel_cells=1_000_000
    )


def test_score_neutral_exchange_rates():
    rates = score_neutral_exchange_rates()
    assert rates["metal_per_crystal"] == pytest.approx(1.5)
    assert rates["metal_per_fuel_cell"] == pytest.approx(3.0)
    assert rates["crystal_per_fuel_cell"] == pytest.approx(2.0)
    assert rates["crystal_per_metal"] == pytest.approx(1000 / 1500)


def test_resource_score_divisors_registry():
    assert RESOURCE_SCORE_DIVISORS == {
        "metal": 1500,
        "crystal": 1000,
        "fuel_cells": 500,
    }
