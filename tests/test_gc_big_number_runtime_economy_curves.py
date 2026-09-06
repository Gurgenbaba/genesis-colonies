"""No-max runtime arithmetic contract for canonical economy curves."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from game.economy_balance import (
    NANOFACTORY_PERSISTED_COST_MAX,
    nanofactory_upgrade_cost,
    power_build_seconds,
    power_upgrade_cost,
    research_cost_anchor_total,
    research_upgrade_cost,
)

ROOT = Path(__file__).resolve().parents[1]


def test_nanofactory_cost_has_no_historical_i64_clamp():
    metal, crystal = nanofactory_upgrade_cost(20_000)
    assert metal == 10_000 * (1 << 20_000)
    assert crystal == 5_000 * (1 << 20_000)
    assert metal > NANOFACTORY_PERSISTED_COST_MAX
    assert metal > 10**308


def test_polynomial_building_cost_handles_10_pow_400_level():
    level = 10**400
    metal, crystal = power_upgrade_cost("research_lab", level)
    assert isinstance(metal, int)
    assert isinstance(crystal, int)
    assert metal > 10**800
    assert crystal > metal
    assert metal + crystal > 0


def test_polynomial_build_time_handles_10_pow_400_level():
    seconds = power_build_seconds("metal_mine", 10**400)
    assert isinstance(seconds, int)
    assert seconds > 10**500


def test_exponential_mine_cost_survives_beyond_ieee754_output_range():
    metal, crystal = power_upgrade_cost("metal_mine", 20_000)
    assert isinstance(metal, int)
    assert isinstance(crystal, int)
    assert metal > 10**308
    assert crystal > 0


def test_research_cost_uses_decimal_production_reference_at_level_20000():
    anchor = research_cost_anchor_total(20_000)
    assert isinstance(anchor, Decimal)
    assert anchor > Decimal(10) ** 308

    metal, crystal = research_upgrade_cost(1000, 500, 20_000)
    assert isinstance(metal, int)
    assert isinstance(crystal, int)
    assert metal > 10**308
    assert crystal > 0
    assert (metal + crystal) % 5_000_000 == 0


def test_normal_balance_values_remain_stable():
    assert nanofactory_upgrade_cost(1) == (20_000, 10_000)
    assert nanofactory_upgrade_cost(10) == (10_240_000, 5_120_000)
    assert nanofactory_upgrade_cost(25) == (335_544_320_000, 167_772_160_000)

    assert power_upgrade_cost("research_lab", 50) == power_upgrade_cost("research_lab", 50)
    assert power_build_seconds("metal_mine", 120) > power_build_seconds("metal_mine", 60)


def test_economy_curve_source_has_no_nanofactory_runtime_cap():
    source = (ROOT / "game" / "economy_balance.py").read_text(encoding="utf-8")

    assert "min(raw_metal, NANOFACTORY_PERSISTED_COST_MAX)" not in source
    assert "min(raw_crystal, NANOFACTORY_PERSISTED_COST_MAX)" not in source
    assert "growth = 1 << lvl" in source
    assert "if lvl > _EXACT_CURVE_LEVEL_THRESHOLD:" in source
    assert "_research_income_reference_decimal" in source
