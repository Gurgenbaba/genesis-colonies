"""
GC-821 — economy consumer rebalance after GC-820 production formula.

Run: python -m pytest tests/test_gc821_economy_rebalance.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from game.buildings import get_build_time, get_upgrade_cost
from game.economy_balance import (
    BENCHMARK_LEVELS,
    EXCHANGE_DAILY_LIMIT_MIN,
    LOOT_RESOURCE_FLOOR_MIN,
    STORAGE_BASE_CAPACITY,
    STORAGE_LEVEL_GROWTH,
    balance_snapshot_table,
    mine_upgrade_metal_hours,
    power_build_seconds,
    power_upgrade_cost,
    reference_production_per_hour,
    storage_capacity_at_depot_level,
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

    def test_storage_level_one_uses_exponential_growth(self):
        er = EffectResolver({"metal_storage": 1}, {})
        caps = er.get_storage_capacity()
        assert caps["metal"] == storage_capacity_at_depot_level(1)

    def test_storage_curve_smooth_progression(self):
        caps = [storage_capacity_at_depot_level(lvl) for lvl in range(4)]
        assert caps[0] < caps[1] < caps[2] < caps[3]
        delta_l1 = caps[1] - caps[0]
        delta_l2 = caps[2] - caps[1]
        delta_l3 = caps[3] - caps[2]
        assert delta_l1 <= 3 * delta_l2
        assert delta_l2 <= delta_l3

    def test_storage_capacity_increases_monotonically_per_level(self):
        for resource, building in (
            ("metal", "metal_storage"),
            ("crystal", "crystal_storage"),
            ("fuel_cells", "fuel_storage"),
        ):
            previous = EffectResolver({building: 0}, {}).get_storage_capacity()[resource]
            for level in range(1, 51):
                cap = EffectResolver({building: level}, {}).get_storage_capacity()[resource]
                assert cap > previous, f"{resource} storage L{level} did not increase"
                previous = cap

    def test_storage_tech_is_additive_and_combines_with_storage_level(self):
        base = EffectResolver({"metal_storage": 18}, {}).get_storage_capacity()["metal"]
        tech10 = EffectResolver({"metal_storage": 18}, {"storage_tech": 10}).get_storage_capacity()["metal"]
        tech20 = EffectResolver({"metal_storage": 18}, {"storage_tech": 20}).get_storage_capacity()["metal"]

        assert tech10 == pytest.approx(int(base * (1 + 10 * 0.33)), rel=0.001)
        assert tech20 == pytest.approx(int(base * (1 + 20 * 0.33)), rel=0.001)
        assert tech20 > tech10 > base

    def test_terraformer_multiplies_final_storage_capacity(self):
        base = EffectResolver({"metal_storage": 5}, {}).get_storage_capacity()["metal"]
        terra3 = EffectResolver({"metal_storage": 5, "terraformer": 3}, {}).get_storage_capacity()["metal"]
        assert terra3 == pytest.approx(int(base * 1.15), rel=0.001)
        assert terra3 > base

    def test_storage_l18_to_l19_delta_grows_with_level(self):
        cap17 = EffectResolver({"metal_storage": 17}, {"storage_tech": 20}).get_storage_capacity()["metal"]
        cap18 = EffectResolver({"metal_storage": 18}, {"storage_tech": 20}).get_storage_capacity()["metal"]
        cap19 = EffectResolver({"metal_storage": 19}, {"storage_tech": 20}).get_storage_capacity()["metal"]
        d1 = storage_capacity_at_depot_level(1) - storage_capacity_at_depot_level(0)
        d18 = cap18 - cap17
        d19 = cap19 - cap18

        assert cap19 > cap18 > cap17
        assert d19 > d18 > d1

    def test_all_storage_resources_use_same_growth_rule(self):
        cases = (
            ("metal", "metal_storage"),
            ("crystal", "crystal_storage"),
            ("fuel_cells", "fuel_storage"),
        )
        for resource, building in cases:
            caps = EffectResolver({building: 30}, {"storage_tech": 5}).get_storage_capacity()
            expected_base = storage_capacity_at_depot_level(30)
            expected = int(expected_base * (1 + 5 * 0.33))
            assert caps[resource] == expected

    def test_storage_growth_constant(self):
        assert STORAGE_LEVEL_GROWTH == 1.92
        from game.economy_balance import STORAGE_LEVEL_GROWTH_LATE, STORAGE_LEVEL_GROWTH_PIVOT

        assert STORAGE_LEVEL_GROWTH_LATE == 1.35
        assert STORAGE_LEVEL_GROWTH_PIVOT == 10

    def test_storage_endgame_cap_sane_with_high_tech(self):
        """L22 + storage_tech 20 must stay well below trillion-scale caps."""
        cap = EffectResolver(
            {"fuel_storage": 22, "terraformer": 5},
            {"storage_tech": 20},
        ).get_storage_capacity()["fuel_cells"]
        assert cap < 100_000_000_000
        assert cap > 1_000_000_000

    def test_exchange_daily_limit_min_default(self):
        assert int(_EXCHANGE_SETTING_DEFAULTS["exchange_daily_limit_min"]) == EXCHANGE_DAILY_LIMIT_MIN

    def test_production_reference_uses_gc820(self):
        ref = reference_production_per_hour("metal", 30)
        ctx = ProductionContext("metal", 30, slot=9)
        assert ref == pytest.approx(calculate_resource_output("metal", ctx))

    def test_no_frontend_storage_formula(self):
        root = Path(__file__).resolve().parent.parent
        js = (root / "static" / "main.js").read_text(encoding="utf-8")
        forbidden = (
            "STORAGE_BASE_CAPACITY",
            "STORAGE_LEVEL_GROWTH",
            "storage_capacity_at_depot_level",
            "storage_tech_level",
            "storageTechLevel",
        )
        for token in forbidden:
            assert token not in js


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
