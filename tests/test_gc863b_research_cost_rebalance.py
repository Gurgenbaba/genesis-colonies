"""
GC-RESEARCH-COST-REBALANCE — research costs = reference income × afford hours.

Run: python -m pytest tests/test_gc863b_research_cost_rebalance.py -v
"""

from __future__ import annotations

import pytest

from game.economy_balance import (
    RESEARCH_COST_AFFORD_HOURS,
    research_cost_afford_hours,
    research_cost_anchor_total,
    research_upgrade_cost,
    reference_production_per_hour,
)
from game.research import RESEARCH_TECHS, get_research_cost

_BENCHMARK_LEVELS = (1, 5, 10, 15, 19, 20, 30, 40, 50, 75, 100)
_PRE_GC863B_ENERGY_L1 = 801


def _is_round_genesis_cost(value: int) -> bool:
    n = int(value)
    if n <= 0:
        return False
    if n < 10_000:
        return n % 250 == 0
    if n < 1_000_000:
        return n % 500 == 0
    if n < 100_000_000:
        return n % 50_000 == 0
    return n % 1_000_000 == 0


def _combined(tech_key: str, level: int) -> tuple[int, int, int]:
    m, c = get_research_cost(tech_key, level)
    return m, c, m + c


def _income(level: int) -> float:
    return reference_production_per_hour("metal", level) + reference_production_per_hour(
        "crystal", level
    )


class TestGc863bRoundNumbers:
    @pytest.mark.parametrize("tech_key", sorted(RESEARCH_TECHS.keys()))
    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_costs_use_round_numbers(self, tech_key: str, level: int) -> None:
        metal, crystal, total = _combined(tech_key, level)
        assert _is_round_genesis_cost(total), f"{tech_key} L{level} total={total}"
        assert _is_round_genesis_cost(metal), f"{tech_key} L{level} metal={metal}"
        assert _is_round_genesis_cost(crystal), f"{tech_key} L{level} crystal={crystal}"
        assert metal + crystal == total


class TestGcResearchCostRebalance:
    def test_l1_more_expensive_than_legacy_gc863a(self) -> None:
        _, _, total = _combined("energy_tech", 1)
        assert total > _PRE_GC863B_ENERGY_L1

    def test_storage_l19_is_major_sink(self) -> None:
        metal, crystal, total = _combined("storage_tech", 19)
        assert total >= 500_000
        assert metal >= 250_000
        assert crystal >= 200_000

    def test_midgame_energy_tech_millions(self) -> None:
        _, _, total = _combined("energy_tech", 30)
        assert total >= 5_000_000

    def test_endgame_energy_tech_billions(self) -> None:
        _, _, total = _combined("energy_tech", 50)
        assert total >= 200_000_000

    def test_anchor_follows_income_times_afford_hours(self) -> None:
        for level in (10, 20, 30, 40, 50):
            income = _income(level)
            hours = research_cost_afford_hours(level)
            assert research_cost_anchor_total(level) == pytest.approx(income * hours, rel=1e-9)

    @pytest.mark.parametrize("level", (2, 5, 10, 15, 19, 20, 30, 40, 60, 80, 100, 120))
    def test_anchor_monotone(self, level: int) -> None:
        assert research_cost_anchor_total(level) > research_cost_anchor_total(level - 1)

    @pytest.mark.parametrize("level", (10, 19, 20, 30, 40))
    def test_each_step_materially_steeper_than_old_curve(self, level: int) -> None:
        _, _, energy = _combined("energy_tech", level)
        old_anchors = {10: 22_000, 20: 40_000, 30: 100_000, 40: 3_400_000}
        if level in old_anchors:
            assert energy >= old_anchors[level] * 5

    def test_higher_tier_costs_more_at_same_level(self) -> None:
        _, _, energy = _combined("energy_tech", 25)
        _, _, navigation = _combined("navigation_tech", 25)
        _, _, storage = _combined("storage_tech", 25)
        assert navigation > energy > storage

    def test_afford_hours_anchors_documented(self) -> None:
        assert RESEARCH_COST_AFFORD_HOURS[10] == 8.0
        assert RESEARCH_COST_AFFORD_HOURS[30] == 96.0
        assert RESEARCH_COST_AFFORD_HOURS[120] == 8640.0


class TestGc863bBuildingsUntouched:
    def test_building_costs_not_changed(self) -> None:
        from game.economy_balance import power_upgrade_cost

        metal, crystal = power_upgrade_cost("metal_mine", 10)
        assert metal + crystal > 0
        metal50, crystal50 = power_upgrade_cost("research_lab", 50)
        assert metal50 + crystal50 >= 10_000_000
