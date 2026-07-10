"""
GC-863A — Percent-power building & research cost hardening.

Run: python -m pytest tests/test_gc863a_building_balance_hardening.py -v
"""

from __future__ import annotations

import math

import pytest

from game.economy_balance import (
    NANOFACTORY_COST_GROWTH,
    NANOFACTORY_CRYSTAL_BASE,
    NANOFACTORY_METAL_BASE,
    RESEARCH_COST_AFFORD_HOURS,
    nanofactory_upgrade_cost,
    power_upgrade_cost,
    reference_production_per_hour,
    research_cost_anchor_total,
    research_cost_afford_hours,
    research_upgrade_cost,
)
from game.shipyard import BUILD_TIME_LEVEL_FACTOR

_GC863_BENCHMARK_LEVELS = (10, 20, 30, 50)
_RESEARCH_LEVELS = (10, 20, 30, 40, 50, 80, 100, 120)
_PERCENT_BUILDINGS = (
    "orbital_shipyard",
    "research_lab",
    "academy",
    "command_center",
)

# Post-GC-863 (pre-863A) combined upgrade totals at L50.
_GC863_L50_TOTALS = {
    "orbital_shipyard": 1_944_544,
    "research_lab": 1_491_075,
    "academy": 2_064_564,
    "command_center": 1_569_340,
}

_GC863_ORBITAL_FACTOR = 0.96


def _combined_cost(building: str, level: int) -> int:
    metal, crystal = power_upgrade_cost(building, level)
    return metal + crystal


def _shipyard_reduction_pct(level: int) -> int:
    lvl = max(1, int(level))
    if lvl <= 1:
        return 0
    return int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)) * 100))


class TestGc863aOrbitalShipyardSpeed:
    @pytest.mark.parametrize(
        ("level", "max_reduction"),
        [(10, 25), (18, 40), (20, 42), (30, 55), (50, 75)],
    )
    def test_reduction_targets(self, level: int, max_reduction: int) -> None:
        red = _shipyard_reduction_pct(level)
        assert red <= max_reduction
        assert red >= max_reduction - 8

    def test_level_18_lower_than_gc863(self) -> None:
        old = int(round((1 - _GC863_ORBITAL_FACTOR ** 17) * 100))
        new = _shipyard_reduction_pct(18)
        assert old > new
        assert new <= 38


class TestGc863aPercentBuildingCosts:
    @pytest.mark.parametrize("building", _PERCENT_BUILDINGS)
    @pytest.mark.parametrize("level", _GC863_BENCHMARK_LEVELS)
    def test_higher_than_gc863(self, building: str, level: int) -> None:
        if level != 50:
            return
        assert _combined_cost(building, level) > _GC863_L50_TOTALS[building]

    @pytest.mark.parametrize("building", _PERCENT_BUILDINGS)
    def test_level_50_in_achievement_band(self, building: str) -> None:
        total = _combined_cost(building, 50)
        low, high = (10_000_000, 35_000_000)
        if building == "academy":
            low = 15_000_000
        assert low <= total <= high

    def test_level_10_not_extreme(self) -> None:
        for building in _PERCENT_BUILDINGS:
            assert _combined_cost(building, 10) < 1_500_000


class TestGc863aNanofactory:
    def test_growth_rate(self) -> None:
        assert NANOFACTORY_COST_GROWTH == pytest.approx(2.0)

    @pytest.mark.parametrize("level", (1, 10, 25, 50))
    def test_formula_unchanged(self, level: int) -> None:
        metal, crystal = nanofactory_upgrade_cost(level)
        assert metal == max(1, int(math.ceil(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))
        assert crystal == max(0, int(math.ceil(NANOFACTORY_CRYSTAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))

    def test_level_50_stays_in_billions(self) -> None:
        metal, crystal = nanofactory_upgrade_cost(50)
        assert metal >= 20_000_000_000
        assert crystal >= 10_000_000_000


class TestGc863aResearchCosts:
    def test_cost_anchor_tracks_production_times_afford_hours(self) -> None:
        for level in (10, 20, 30):
            income = reference_production_per_hour("metal", level) + reference_production_per_hour(
                "crystal", level
            )
            assert research_cost_anchor_total(level) == pytest.approx(
                income * research_cost_afford_hours(level), rel=1e-9
            )

    def test_level_50_anchor_in_hundreds_of_millions(self) -> None:
        assert RESEARCH_COST_AFFORD_HOURS[50] == 720.0
        assert research_cost_anchor_total(50) >= 200_000_000.0

    @pytest.mark.parametrize("level", (40, 50, 60, 80, 100, 120))
    def test_mid_late_anchors_raised(self, level: int) -> None:
        assert research_cost_anchor_total(level) >= 10_000_000.0

    def test_energy_tech_l50_not_trivial_vs_l54_mine(self) -> None:
        metal, crystal = research_upgrade_cost(1000, 500, 50)
        total = metal + crystal
        metal_ph = reference_production_per_hour("metal", 54)
        assert total >= metal_ph * 24
        assert total >= 200_000_000

    @pytest.mark.parametrize("level", _RESEARCH_LEVELS)
    def test_anchor_table_monotone(self, level: int) -> None:
        if level <= 10:
            return
        prev = research_cost_anchor_total(level - 1)
        cur = research_cost_anchor_total(level)
        assert cur >= prev
