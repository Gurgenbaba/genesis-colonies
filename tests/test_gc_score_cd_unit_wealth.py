"""
GC-SCORE-C/D — unit wealth scores and cumulative cost owners.

Run: python -m pytest tests/test_gc_score_cd_unit_wealth.py -v
"""

from __future__ import annotations

from game.combat_models import combat_stats_for_defense, combat_stats_for_ship
from game.defense_defs import defense_score_value, unit_build_cost
from game.economy_balance import cumulative_upgrade_resource_totals
from game.fleet_defs import ship_score_value
from game.research import cumulative_research_resource_totals, get_research_cost
from game.resource_score import score_from_cost_dict
from game.shipyard import _unit_build_cost


def test_ship_score_matches_build_cost_resource_score():
    key = "ironclad_frigate"
    expected = score_from_cost_dict(_unit_build_cost(key))
    assert ship_score_value(key) == expected
    assert combat_stats_for_ship(key).score_value == expected
    assert expected > 0


def test_defense_score_matches_build_cost_resource_score():
    key = "plasma_arc"
    expected = score_from_cost_dict(unit_build_cost(key))
    assert defense_score_value(key) == expected
    assert combat_stats_for_defense(key).score_value == expected
    assert expected == 2


def test_spark_drone_score_uses_floor_not_legacy_metal_plus_crystal():
    key = "spark_drone"
    cost = _unit_build_cost(key)
    assert cost["metal"] + cost["crystal"] == 875
    assert ship_score_value(key) == 0


def test_cumulative_building_totals_feed_resource_score():
    totals = cumulative_upgrade_resource_totals("metal_mine", 3)
    assert totals["metal"] > 0
    assert totals["crystal"] >= 0
    assert totals["fuel_cells"] == 0
    assert score_from_cost_dict(totals) > 0


def test_cumulative_research_totals_match_level_sum():
    totals = cumulative_research_resource_totals("energy_tech", 3)
    metal = crystal = 0
    for level in range(1, 4):
        m, c = get_research_cost("energy_tech", level)
        metal += m
        crystal += c
    assert totals == {"metal": metal, "crystal": crystal, "fuel_cells": 0}
