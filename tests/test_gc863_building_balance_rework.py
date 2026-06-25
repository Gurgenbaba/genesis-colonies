"""
GC-863 — Building balance rework (storage, solar, labs, military, infrastructure, nanofactory).

Run: python -m pytest tests/test_gc863_building_balance_rework.py -v
"""

from __future__ import annotations

import math

import pytest

from game.buildings import COMMAND_CENTER_NANOFACTORY_BUILD_BONUS_PER_LEVEL
from game.economy_balance import (
    NANOFACTORY_COST_GROWTH,
    NANOFACTORY_CRYSTAL_BASE,
    NANOFACTORY_METAL_BASE,
    STORAGE_PRODUCTION_HOUR_MULTIPLIER,
    nanofactory_upgrade_cost,
    power_upgrade_cost,
    reference_production_per_hour,
    storage_capacity_anchor,
)
from game.effects import EffectResolver
from game.shipyard import BUILD_TIME_LEVEL_FACTOR

# Pre-GC-863 cost curve K values (metal_frac/crystal_frac unchanged from BUILDING_UPGRADE_CURVES).
_LEGACY_COST_K: dict[str, float] = {
    "metal_storage": 420.0,
    "research_lab": 650.0,
    "academy": 900.0,
    "orbital_shipyard": 1100.0,
    "command_center": 1200.0,
    "solar_plant": 200.0,
}


def _legacy_power_upgrade_cost(building_type: str, target_level: int) -> tuple[int, int]:
    from game.economy_balance import BUILDING_UPGRADE_CURVES

    curve = BUILDING_UPGRADE_CURVES[building_type]
    lvl = max(1, int(target_level))
    k = _LEGACY_COST_K[building_type]
    total = max(1.0, k * (float(lvl) ** curve.exponent))
    metal = max(1, int(math.ceil(total * curve.metal_frac)))
    crystal = max(0, int(math.ceil(total * curve.crystal_frac)))
    return metal, crystal

_PRE_ORBITAL_SHIPYARD_FACTOR = 0.90
_BENCHMARK_LEVELS = (1, 10, 20, 30, 50)
_NANOFACTORY_LEVELS = (1, 10, 25, 50)


def _mine_draw_at_level(level: int) -> int:
    lvl = max(0, int(level))
    if lvl <= 0:
        return 0
    return (
        int(10 * (lvl ** 1.25))
        + int(6 * (lvl ** 1.25))
        + int(8 * (lvl ** 1.25))
    )


def _shipyard_reduction_pct(level: int) -> int:
    lvl = max(1, int(level))
    if lvl <= 1:
        return 0
    return int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)) * 100))


class TestGc863StorageCosts:
    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_metal_storage_costs_higher_than_pre_gc863(self, level: int):
        old_m, old_c = _legacy_power_upgrade_cost("metal_storage", level)
        new_m, new_c = power_upgrade_cost("metal_storage", level)
        assert new_m > old_m
        assert new_c >= old_c


class TestGc863StorageCapacity:
    @pytest.mark.parametrize(
        ("resource", "building"),
        [
            ("metal", "metal_storage"),
            ("crystal", "crystal_storage"),
            ("fuel_cells", "fuel_storage"),
        ],
    )
    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_capacity_follows_production_anchor(self, resource: str, building: str, level: int):
        anchor = storage_capacity_anchor(resource, level)
        expected = int(reference_production_per_hour(resource, level) * STORAGE_PRODUCTION_HOUR_MULTIPLIER)
        assert anchor == expected

        er = EffectResolver({building: level}, {})
        caps = er.get_storage_capacity()
        key = "fuel_cells" if resource == "fuel_cells" else resource
        assert caps[key] == anchor


class TestGc863SolarCalibration:
    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_solar_l50_matches_mine_draw_plus_one(self, level: int):
        mines = {
            "metal_mine": level,
            "crystal_mine": level,
            "fuel_cell_plant": level,
            "solar_plant": level,
        }
        er = EffectResolver(mines, {})
        total, used = er.compute_energy()
        assert total == _mine_draw_at_level(level) + 1
        assert used == _mine_draw_at_level(level)

    def test_solar_l50_exact_ticket_anchor(self):
        er = EffectResolver(
            {
                "metal_mine": 50,
                "crystal_mine": 50,
                "fuel_cell_plant": 50,
                "solar_plant": 50,
            },
            {},
        )
        total, used = er.compute_energy()
        assert used == _mine_draw_at_level(50)
        assert total == _mine_draw_at_level(50) + 1


class TestGc863ResearchAndAcademyCosts:
    @pytest.mark.parametrize("building", ("research_lab", "academy"))
    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_costs_strongly_increased(self, building: str, level: int):
        old_m, old_c = _legacy_power_upgrade_cost(building, level)
        new_m, new_c = power_upgrade_cost(building, level)
        assert new_m >= int(old_m * 5)
        assert new_c >= int(old_c * 5)


class TestGc863OrbitalShipyard:
    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_costs_increased(self, level: int):
        old_m, old_c = _legacy_power_upgrade_cost("orbital_shipyard", level)
        new_m, new_c = power_upgrade_cost("orbital_shipyard", level)
        assert new_m > old_m
        assert new_c > old_c

    def test_level_18_reduction_lower_than_pre_gc863(self):
        old = int(round((1 - _PRE_ORBITAL_SHIPYARD_FACTOR ** 17) * 100))
        new = _shipyard_reduction_pct(18)
        assert old >= 80
        assert new < old
        assert new <= 55


class TestGc863CommandCenter:
    def test_nanofactory_ui_bonus_is_fifteen_percent(self):
        assert COMMAND_CENTER_NANOFACTORY_BUILD_BONUS_PER_LEVEL == 15

    @pytest.mark.parametrize("level", _BENCHMARK_LEVELS)
    def test_costs_strongly_increased(self, level: int):
        old_m, old_c = _legacy_power_upgrade_cost("command_center", level)
        new_m, new_c = power_upgrade_cost("command_center", level)
        assert new_m >= int(old_m * 3)
        assert new_c >= int(old_c * 3)


class TestGc863NanofactoryCosts:
    @pytest.mark.parametrize("level", _NANOFACTORY_LEVELS)
    def test_exact_formula(self, level: int):
        metal, crystal = nanofactory_upgrade_cost(level)
        assert metal == max(1, int(math.ceil(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))
        assert crystal == max(0, int(math.ceil(NANOFACTORY_CRYSTAL_BASE * (NANOFACTORY_COST_GROWTH ** level))))
        assert power_upgrade_cost("nanofactory", level) == (metal, crystal)

    def test_benchmark_values(self):
        assert nanofactory_upgrade_cost(1) == (13300, 6650)
        assert nanofactory_upgrade_cost(10) == (173_188, 86_594)
        assert nanofactory_upgrade_cost(25) == (12_482_197, 6_241_099)
        assert nanofactory_upgrade_cost(50) == (15_580_523_595, 7_790_261_798)
