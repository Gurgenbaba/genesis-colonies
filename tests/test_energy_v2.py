from __future__ import annotations

import pytest

from game.energy_v2 import (
    candidate_snapshot,
    effective_energy_tech_level,
    geothermal_output,
    mine_demand,
    orbital_output_per_unit,
    solar_output,
)


def test_equal_level_solar_is_deliberately_about_seventy_five_percent():
    snap = candidate_snapshot(
        metal_level=50,
        crystal_level=50,
        fuel_level=50,
        solar_level=50,
    )
    assert snap.ratio == pytest.approx(0.75, abs=0.01)


def test_energy_tech_does_not_delete_global_mine_demand():
    base = mine_demand(500, 500, 500)
    assert base > 0
    # Energy Technology belongs to the secondary-source side in V2.
    low = candidate_snapshot(
        metal_level=500,
        crystal_level=500,
        fuel_level=500,
        solar_level=0,
        geothermal_level=50,
        energy_tech=0,
    )
    high = candidate_snapshot(
        metal_level=500,
        crystal_level=500,
        fuel_level=500,
        solar_level=0,
        geothermal_level=50,
        energy_tech=50,
    )
    assert low.demand == high.demand == base
    assert high.geothermal > low.geothermal


def test_geothermal_energy_tech_scaling_is_strong_and_monotone():
    assert geothermal_output(50, 0) == 10_000
    assert geothermal_output(50, 20) > geothermal_output(50, 0)
    assert geothermal_output(50, 50) > geothermal_output(50, 20)
    assert geothermal_output(50, 100) > geothermal_output(50, 50)


def test_energy_tech_candidate_tail_is_unbounded_but_diminishing():
    e50 = effective_energy_tech_level(50)
    e100 = effective_energy_tech_level(100)
    e200 = effective_energy_tech_level(200)
    assert 0 < e50 < e100 < e200
    assert (e100 - e50) > (e200 - e100) / 2
    assert effective_energy_tech_level(10_000) > e200


def test_ascension_draw_bps_apply_per_mine_without_zeroing_demand():
    normal = mine_demand(200, 200, 200)
    optimized = mine_demand(
        200,
        200,
        200,
        metal_draw_bps=8000,
        crystal_draw_bps=8000,
        fuel_draw_bps=8000,
    )
    assert 0 < optimized < normal
    assert optimized == pytest.approx(normal * 0.8, rel=0.01)


def test_orbital_source_rewards_hotter_worlds():
    assert orbital_output_per_unit(100) > orbital_output_per_unit(-100)


def test_candidate_curves_remain_monotone_at_long_levels():
    assert solar_output(50) < solar_output(500) < solar_output(1000)
    assert mine_demand(50, 50, 50) < mine_demand(500, 500, 500) < mine_demand(1000, 1000, 1000)
