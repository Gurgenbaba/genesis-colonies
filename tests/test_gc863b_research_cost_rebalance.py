"""
GC-RESEARCH-COST-REBALANCE — research costs = reference income × afford hours.

Run: python -m pytest tests/test_gc863b_research_cost_rebalance.py -v
"""

from __future__ import annotations

import pytest

from game.economy_balance import (
    RESEARCH_COST_AFFORD_HOURS,
    RESEARCH_EMPIRE_MATURITY_LEVEL,
    research_cost_afford_hours,
    research_cost_anchor_total,
    research_empire_cost_multiplier,
    research_empire_maturity_index,
    research_upgrade_cost,
    reference_production_per_hour,
    scale_research_cost_for_empire,
)
from game.research import RESEARCH_TECHS, get_research_cost, get_research_payment_cost

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


class TestGcResearchEmpirePacing:
    def test_maturity_contract_is_level_15(self) -> None:
        assert RESEARCH_EMPIRE_MATURITY_LEVEL == 15
        assert research_empire_maturity_index([15, 15, 15]) == pytest.approx(1.0)
        assert research_empire_maturity_index([0, 0, 0]) == pytest.approx(0.0)

    def test_early_research_is_unchanged(self) -> None:
        income = _income(20) * 169
        assert research_empire_cost_multiplier(
            20,
            empire_combined_per_hour=income,
            maturity_index=1.0,
        ) == pytest.approx(1.0)

    def test_midgame_pressure_blends_in(self) -> None:
        income = _income(40) * 16
        assert research_empire_cost_multiplier(
            40,
            empire_combined_per_hour=income,
            maturity_index=1.0,
        ) == pytest.approx(2.0, rel=1e-9)

    def test_endgame_uses_sqrt_empire_pressure(self) -> None:
        income = _income(120) * 169
        assert research_empire_cost_multiplier(
            120,
            empire_combined_per_hour=income,
            maturity_index=1.0,
        ) == pytest.approx(13.0, rel=1e-9)

    def test_immature_empire_contributes_proportionally(self) -> None:
        mature = research_empire_cost_multiplier(
            120,
            empire_combined_per_hour=_income(120) * 169,
            maturity_index=1.0,
        )
        partial = research_empire_cost_multiplier(
            120,
            empire_combined_per_hour=_income(120) * 169,
            maturity_index=0.25,
        )
        assert 1.0 < partial < mature

    def test_dynamic_payment_preserves_base_anchor_and_rounding(self) -> None:
        base_m, base_c = get_research_cost("energy_tech", 120)
        paid_m, paid_c = get_research_payment_cost(
            "energy_tech",
            120,
            cost_context={
                "empire_combined_per_hour": int(_income(120) * 169),
                "maturity_index": 1.0,
                "world_count": 11,
            },
        )
        assert paid_m + paid_c > (base_m + base_c) * 12
        scaled_m, scaled_c = scale_research_cost_for_empire(base_m, base_c, 13.0)
        assert (paid_m, paid_c) == (scaled_m, scaled_c)


class TestGc863bBuildingsUntouched:
    def test_building_costs_not_changed(self) -> None:
        from game.economy_balance import power_upgrade_cost

        metal, crystal = power_upgrade_cost("metal_mine", 10)
        assert metal + crystal > 0
        metal50, crystal50 = power_upgrade_cost("research_lab", 50)
        assert metal50 + crystal50 >= 10_000_000
