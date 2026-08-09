"""
GC-832 Option A — Nexus building level-cap matrix.

EPIC-29: production mines (`metal_mine`, `crystal_mine`, `fuel_cell_plant`) are
uncapped; solar/storage still use nexus formulas.

Run: python -m pytest tests/test_nexus_building_caps.py -v
"""

from __future__ import annotations

import pytest

from game.effects.effect_resolver import EffectResolver
from game.mine_evolution import UNCAPPED_BUILDING_LEVEL


BASE = EffectResolver.MAX_BUILDING_LEVEL


@pytest.mark.parametrize(
    ("building", "core", "geo", "expected"),
    [
        ("metal_mine", 0, 0, UNCAPPED_BUILDING_LEVEL),
        ("crystal_mine", 0, 0, UNCAPPED_BUILDING_LEVEL),
        ("fuel_cell_plant", 0, 0, UNCAPPED_BUILDING_LEVEL),
        ("metal_mine", 3, 2, UNCAPPED_BUILDING_LEVEL),
        ("fuel_cell_plant", 3, 2, UNCAPPED_BUILDING_LEVEL),
        ("solar_plant", 0, 0, BASE),
        ("metal_storage", 0, 0, BASE),
        ("solar_plant", 30, 20, BASE + 30 + 40),
        ("metal_storage", 30, 20, BASE + 40),
        ("crystal_storage", 5, 10, BASE + 20),
        ("fuel_storage", 0, 15, BASE + 30),
        ("research_lab", 50, 50, BASE),
        ("geothermal_nexus", 50, 50, BASE),
    ],
)
def test_nexus_cap_matrix(building: str, core: int, geo: int, expected: int):
    b = {
        "planet_core_nexus": core,
        "geothermal_nexus": geo,
    }
    er = EffectResolver(b, {})
    assert er.get_max_building_level(building) == expected


def test_storage_ignores_planet_core():
    b = {"planet_core_nexus": 25, "geothermal_nexus": 0}
    er = EffectResolver(b, {})
    assert er.get_max_building_level("metal_storage") == BASE
    # EPIC-29: mines uncapped — core no longer raises mine hardcap.
    assert er.get_max_building_level("metal_mine") == UNCAPPED_BUILDING_LEVEL
    assert er.get_max_building_level("solar_plant") == BASE + 25


def test_fuel_cell_matches_mine_uncapped():
    b = {"planet_core_nexus": 10, "geothermal_nexus": 5}
    er = EffectResolver(b, {})
    assert er.get_max_building_level("metal_mine") == UNCAPPED_BUILDING_LEVEL
    assert er.get_max_building_level("fuel_cell_plant") == UNCAPPED_BUILDING_LEVEL
