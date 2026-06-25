"""
GC-863B — Research cost rebalance (round numbers, steeper curve).

Run: python -m pytest tests/test_gc863b_research_cost_rebalance.py -v
"""

from __future__ import annotations

import pytest

from game.economy_balance import (
    RESEARCH_COST_ANCHOR_TOTAL,
    power_upgrade_cost,
    research_cost_anchor_total,
    research_upgrade_cost,
)
from game.research import RESEARCH_TECHS, get_research_cost

_BENCHMARK_LEVELS = (1, 10, 20, 30, 40, 50, 75, 100)
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


class TestGc863bRoundNumbers:
    @pytest.mark.parametrize("tech_key", sorted(RESEARCH_TECHS.keys()))
    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_costs_use_round_numbers(self, tech_key: str, level: int) -> None:
        metal, crystal, total = _combined(tech_key, level)
        assert _is_round_genesis_cost(total), f"{tech_key} L{level} total={total}"
        assert _is_round_genesis_cost(metal), f"{tech_key} L{level} metal={metal}"
        assert _is_round_genesis_cost(crystal), f"{tech_key} L{level} crystal={crystal}"
        assert metal + crystal == total


class TestGc863bCostCurve:
    def test_early_l1_more_expensive_than_gc863a(self) -> None:
        _, _, total = _combined("energy_tech", 1)
        assert total > _PRE_GC863B_ENERGY_L1
        assert total == 1_000

    def test_anchor_l10_l20_l30_raised(self) -> None:
        assert research_cost_anchor_total(10) == pytest.approx(3_000.0)
        assert research_cost_anchor_total(20) == pytest.approx(12_500.0)
        assert research_cost_anchor_total(30) == pytest.approx(50_000.0)
        assert research_cost_anchor_total(30) > 22_000.0

    def test_level_50_achievement_anchor(self) -> None:
        assert RESEARCH_COST_ANCHOR_TOTAL[50] == 25_000_000.0
        _, _, total = _combined("energy_tech", 50)
        assert total == 25_000_000

    @pytest.mark.parametrize("level", (10, 20, 30, 40, 50, 60, 80, 100, 120))
    def test_anchor_monotone(self, level: int) -> None:
        if level <= 10:
            return
        assert research_cost_anchor_total(level) >= research_cost_anchor_total(level - 1)

    def test_higher_tier_costs_more_at_same_level(self) -> None:
        _, _, energy = _combined("energy_tech", 25)
        _, _, navigation = _combined("navigation_tech", 25)
        assert navigation > energy


class TestGc863bBuildingsUntouched:
    def test_building_costs_not_changed(self) -> None:
        metal, crystal = power_upgrade_cost("metal_mine", 10)
        assert metal + crystal > 0
        metal50, crystal50 = power_upgrade_cost("research_lab", 50)
        assert metal50 + crystal50 >= 10_000_000


class TestGc863bBeforeAfterSnapshot:
    """Documents GC-863B energy_tech benchmark totals (tier 1.0)."""

    def test_energy_tech_benchmark_table(self) -> None:
        expected = {
            1: 1_000,
            10: 3_000,
            20: 12_500,
            30: 50_000,
            40: 2_000_000,
            50: 25_000_000,
            75: 114_000_000,
            100: 500_000_000,
        }
        for level, want in expected.items():
            _, _, got = _combined("energy_tech", level)
            assert got == want, f"energy_tech L{level}: got {got}, want {want}"
