"""GC-832 — Nexus building level-cap matrix.

Nexuses own normal mine progression up to L200. Mine Ascension owns levels above 200.
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
        ("metal_storage", 30, 20, BASE + 40),
        ("crystal_storage", 5, 10, BASE + 20),
        ("fuel_storage", 0, 15, BASE + 30),
        ("research_lab", 50, 50, BASE),
        ("geothermal_nexus", 50, 50, BASE),
        ("metal_mine", 100, 100, 200),
        ("fuel_cell_plant", 100, 100, 200),
    ],
)
def test_nexus_cap_matrix(building: str, core: int, geo: int, expected: int):
    b = {"planet_core_nexus": core, "geothermal_nexus": geo}
    assert EffectResolver(b, {}).get_max_building_level(building) == expected


def test_storage_ignores_planet_core_but_mines_do_not():
    b = {"planet_core_nexus": 25, "geothermal_nexus": 0}
    er = EffectResolver(b, {})
    assert er.get_max_building_level("metal_storage") == BASE
    assert er.get_max_building_level("metal_mine") == BASE + 25
    assert er.get_max_building_level("solar_plant") == BASE + 25


def test_fuel_cell_matches_production_mine_nexus_cap():
    b = {"planet_core_nexus": 10, "geothermal_nexus": 5}
    er = EffectResolver(b, {})
    assert er.get_max_building_level("metal_mine") == BASE + 20
    assert er.get_max_building_level("fuel_cell_plant") == BASE + 20
