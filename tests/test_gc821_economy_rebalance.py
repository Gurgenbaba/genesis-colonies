"""
GC-821 — economy consumer rebalance after GC-820 production formula.

Run: python -m pytest tests/test_gc821_economy_rebalance.py -v
"""

from __future__ import annotations

import pytest

from game.buildings import get_build_time, get_upgrade_cost
from game.economy_balance import (
    BENCHMARK_LEVELS,
    EXCHANGE_DAILY_LIMIT_MIN,
    LOOT_RESOURCE_FLOOR_MIN,
    STORAGE_BASE_CAPACITY,
    balance_snapshot_table,
    mine_upgrade_metal_hours,
    power_build_seconds,
    power_upgrade_cost,
    reference_production_per_hour,
)
from game.effects import EffectResolver
from game.exchange import _EXCHANGE_SETTING_DEFAULTS
from game.fleet_defs import SHIPS
class TestGc821CLootFloors:
    def test_loot_floors_raised(self):
        assert LOOT_RESOURCE_FLOOR_MIN >= 12_000
from game.production_formula import calculate_resource_output, ProductionContext


class TestGc821ABuildingCosts:
    def test_power_cost_monotone_with_level(self):
        prev = 0
        for lvl in range(4, 121):
            metal, _ = power_upgrade_cost("metal_mine", lvl)
            assert metal > prev
            prev = metal

    def test_mine_upgrade_hours_bounded_at_benchmarks(self):
        from game.economy_balance import MINE_UPGRADE_ROI_TARGET_HOURS, ROI_BENCHMARK_LEVELS

        for lvl in ROI_BENCHMARK_LEVELS:
            hours = mine_upgrade_metal_hours(lvl)
            target = MINE_UPGRADE_ROI_TARGET_HOURS[lvl]
            assert target * 0.65 <= hours <= target * 1.35, f"L{lvl} ROI {hours}h"

    def test_build_time_power_scaling(self):
        t10 = power_build_seconds("metal_mine", 10)
        t30 = power_build_seconds("metal_mine", 30)
        t120 = power_build_seconds("metal_mine", 120)
        assert t10 < t30 < t120

    def test_get_upgrade_cost_delegates_to_economy_balance(self):
        assert get_upgrade_cost("metal_mine", 9) == power_upgrade_cost("metal_mine", 10)

    def test_get_build_time_delegates_to_power_curve(self):
        er = EffectResolver({}, {}, settings={"build_speed": 1.0})
        assert get_build_time("metal_mine", 20, user_id=None) == power_build_seconds("metal_mine", 20)
        assert er.get_build_time_seconds("metal_mine", 20) == power_build_seconds("metal_mine", 20)


class TestGc821BStorageAndExchange:
    def test_storage_base_capacity_without_building(self):
        er = EffectResolver({}, {})
        caps = er.get_storage_capacity()
        assert caps["metal"] == STORAGE_BASE_CAPACITY
        assert caps["crystal"] == STORAGE_BASE_CAPACITY
        assert caps["fuel_cells"] == STORAGE_BASE_CAPACITY

    def test_storage_level_one_adds_production_anchor_to_base(self):
        from game.economy_balance import storage_capacity_anchor

        er = EffectResolver({"metal_storage": 1}, {})
        caps = er.get_storage_capacity()
        assert caps["metal"] == STORAGE_BASE_CAPACITY + storage_capacity_anchor("metal", 1)

    def test_exchange_daily_limit_min_default(self):
        assert int(_EXCHANGE_SETTING_DEFAULTS["exchange_daily_limit_min"]) == EXCHANGE_DAILY_LIMIT_MIN

    def test_production_reference_uses_gc820(self):
        ref = reference_production_per_hour("metal", 30)
        ctx = ProductionContext("metal", 30, slot=9)
        assert ref == pytest.approx(calculate_resource_output("metal", ctx))


class TestGc821CLootFloors:
    def test_loot_floors_raised(self):
        assert LOOT_RESOURCE_FLOOR_MIN >= 12_000


class TestGc821DMilitaryCosts:
    def test_spark_drone_cost_scaled(self):
        cost = SHIPS["spark_drone"]["build_cost"]
        assert cost["metal"] == 625

    def test_balance_snapshot_table_has_benchmarks(self):
        table = balance_snapshot_table()
        for lvl in BENCHMARK_LEVELS:
            assert lvl in table["production_per_hour"]
            assert lvl in table["metal_upgrade_hours"]
            assert table["production_per_hour"][lvl]["metal"] > 0
