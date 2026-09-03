"""
GC-832 / GC-MINE-ASC-NEXUS-001 — Nexus producer level-cap matrix.

Production mines and solar share the structural Nexus cap. With both Nexuses
at level 50 this reaches level 200. Mine Ascension extends the selected mine
beyond that cap in the Buildings queue owner; storage keeps its own formula.

Run: python -m pytest tests/test_nexus_building_caps.py -v
"""

from __future__ import annotations

import pytest

from game.effects.effect_resolver import EffectResolver


BASE = EffectResolver.MAX_BUILDING_LEVEL


@pytest.mark.parametrize(
    ("building", "core", "geo", "expected"),
    [
        ("metal_mine", 0, 0, BASE),
        ("crystal_mine", 0, 0, BASE),
        ("fuel_cell_plant", 0, 0, BASE),
        ("metal_mine", 3, 2, BASE + 3 + 4),
        ("fuel_cell_plant", 3, 2, BASE + 3 + 4),
        ("solar_plant", 0, 0, BASE),
        ("metal_storage", 0, 0, BASE),
        ("solar_plant", 30, 20, BASE + 30 + 40),
        ("metal_mine", 30, 20, BASE + 30 + 40),
        ("crystal_mine", 30, 20, BASE + 30 + 40),
        ("fuel_cell_plant", 30, 20, BASE + 30 + 40),
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


def test_storage_ignores_planet_core_but_mines_do_not():
    b = {"planet_core_nexus": 25, "geothermal_nexus": 0}
    er = EffectResolver(b, {})
    assert er.get_max_building_level("metal_storage") == BASE
    assert er.get_max_building_level("metal_mine") == BASE + 25
    assert er.get_max_building_level("solar_plant") == BASE + 25


def test_fuel_cell_matches_other_producers():
    b = {"planet_core_nexus": 10, "geothermal_nexus": 5}
    er = EffectResolver(b, {})
    expected = BASE + 10 + 10
    assert er.get_max_building_level("metal_mine") == expected
    assert er.get_max_building_level("crystal_mine") == expected
    assert er.get_max_building_level("fuel_cell_plant") == expected
    assert er.get_max_building_level("solar_plant") == expected


def test_max_nexuses_reach_level_200():
    er = EffectResolver({"planet_core_nexus": 50, "geothermal_nexus": 50}, {})
    for building in ("metal_mine", "crystal_mine", "fuel_cell_plant", "solar_plant"):
        assert er.get_max_building_level(building) == 200
