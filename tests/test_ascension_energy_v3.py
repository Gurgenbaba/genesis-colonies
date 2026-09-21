from __future__ import annotations

import pytest

from game.mine_evolution.nodebuster import (
    SKILL_CATALOG,
    effective_shortage_ratio_bps,
    energy_draw_bps,
    panel_fields,
    shortage_recovery_bps,
    skill_point_cost,
    skill_prerequisites_met,
)
from scripts.sim_energy_v2 import (
    candidate_geothermal_output,
    candidate_orbital_output_per_unit,
    candidate_ratio,
    legacy_ratio,
    required_solar_level,
)


def test_energy_utility_nodes_are_small_progression_nodes():
    assert SKILL_CATALOG["optimized_energy"]["utility"] is True
    assert SKILL_CATALOG["load_balancing"]["utility"] is True
    assert SKILL_CATALOG["optimized_energy"]["max_rank"] == 10
    assert SKILL_CATALOG["load_balancing"]["max_rank"] == 10
    assert skill_point_cost("optimized_energy", 0) == 1
    assert skill_point_cost("load_balancing", 0) == 1


def test_load_balancing_requires_three_energy_efficiency_ranks():
    assert skill_prerequisites_met(
        "load_balancing",
        {"optimized_energy": 2},
        {"best_depth": 0},
    ) is False
    assert skill_prerequisites_met(
        "load_balancing",
        {"optimized_energy": 3},
        {"best_depth": 0},
    ) is True


def test_optimized_energy_caps_at_twenty_percent_less_draw():
    assert energy_draw_bps({}) == 10000
    assert energy_draw_bps({"optimized_energy": 1}) == 9800
    assert energy_draw_bps({"optimized_energy": 10}) == 8000
    assert energy_draw_bps({"optimized_energy": 999}) == 8000


def test_load_balancing_recovers_part_of_missing_grid_not_flat_output():
    assert shortage_recovery_bps({}) == 0
    assert shortage_recovery_bps({"load_balancing": 1}) == 250
    assert shortage_recovery_bps({"load_balancing": 10}) == 2500

    # Grid is at 60%; rank 10 recovers 25% of the missing 40 points = +10.
    assert effective_shortage_ratio_bps(6000, {"load_balancing": 10}) == 7000
    # It can never create output above a fully powered grid.
    assert effective_shortage_ratio_bps(10000, {"load_balancing": 10}) == 10000


def test_panel_explains_energy_nodes_with_before_after_values():
    profiles = {
        "metal_mine": {
            "state": {
                "ascension_count": 2,
                "points_earned": 30,
                "points_unspent": 30,
                "best_depth": 400,
                "last_depth": 400,
            },
            "skills": {
                "optimized_energy": 0,
                "load_balancing": 0,
            },
        }
    }
    fields = panel_fields(1, "metal_mine", 400, profiles=profiles)
    rows = {row["key"]: row for row in fields["nodebuster_skills"]}

    assert rows["optimized_energy"]["preview"] == {
        "draw_reduction_now_pct": 0.0,
        "draw_reduction_next_pct": 2.0,
    }
    assert rows["load_balancing"]["preview"]["grid_example_pct"] == 60
    assert rows["load_balancing"]["preview"]["effective_now_pct"] == 60.0
    assert rows["load_balancing"]["preview"]["effective_next_pct"] == 61.0


def test_breakthrough_panel_contains_player_readable_concrete_numbers():
    profiles = {
        "metal_mine": {
            "state": {
                "ascension_count": 3,
                "points_earned": 120,
                "points_unspent": 120,
                "best_depth": 500,
                "last_depth": 500,
            },
            "skills": {
                "deep_yield": 8,
                "reconstruction": 8,
                "frugal_rebuild": 8,
                "rapid_rebuild": 8,
                "overdrive": 3,
            },
        }
    }
    fields = panel_fields(1, "metal_mine", 500, profiles=profiles)
    rows = {row["key"]: row for row in fields["nodebuster_skills"]}

    core = rows["core_resonance"]["preview"]
    assert [point["level"] for point in core["levels"]] == [300, 500, 1000]
    assert core["levels"][1]["pct"] > 10

    legacy = rows["legacy_reconstruction"]["preview"]
    assert legacy["restart_before"] == 110
    assert legacy["restart_after"] == 175

    window = rows["breakthrough_window"]["preview"]
    assert window["window_before"] == 500
    assert window["window_after"] == 525
    assert window["cost_reduction_pct"] > 0
    assert window["time_reduction_pct"] > 0


def test_energy_v2_candidate_stops_solar_from_auto_solving_equal_level_grid():
    for level in (50, 100, 200, 500, 1000):
        ratio = candidate_ratio(level, solar_level=level)
        assert ratio == pytest.approx(0.75, abs=0.01)
        needed = required_solar_level(level)
        assert needed > level
        assert needed < int(level * 1.35) + 2


def test_energy_v2_gives_energy_tech_a_secondary_source_role():
    low = candidate_geothermal_output(50, 0)
    mid = candidate_geothermal_output(50, 20)
    high = candidate_geothermal_output(50, 50)
    assert low < mid < high


def test_energy_v2_orbital_source_is_temperature_sensitive():
    assert candidate_orbital_output_per_unit(1) > candidate_orbital_output_per_unit(8)
    assert candidate_orbital_output_per_unit(8) > candidate_orbital_output_per_unit(15)


def test_simulator_exposes_current_energy_tech_erasure_problem():
    # Current Genesis Energy Tech reduces demand globally, so the same matched
    # setup becomes materially easier as tech rises.
    low = legacy_ratio(100, energy_tech=0, slot=8)
    high = legacy_ratio(100, energy_tech=50, slot=8)
    assert high > low
    assert high == pytest.approx(1.0)


def test_optimized_energy_applies_after_legacy_energy_floor():
    from game.effects import EffectResolver

    er = EffectResolver(
        {"metal_mine": 100},
        {"energy_tech": 100},
    )
    # Isolate ordering without a DB-backed Ascension profile.
    er._nodebuster_energy_draw_bps = lambda _building: 8000

    raw = int(10 * (100 ** 1.25))
    legacy = EffectResolver.apply_mine_energy_draw(
        raw,
        EffectResolver.mine_energy_factor_for_level(100),
    )
    expected = max(1, (legacy * 8000) // 10000)

    assert legacy > 1
    assert er.building_energy_draw("metal_mine") == expected
    assert expected < legacy


def test_building_preview_paths_do_not_fall_back_to_planetless_energy_ratio():
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "game" / "buildings.py").read_text(
        encoding="utf-8"
    )

    tech_start = source.index("def build_building_technical_data(")
    tech_end = source.index("\ndef _mine_bulk_upgrade_meta(", tech_start)
    tech_block = source[tech_start:tech_end]
    assert "_panel_energy_ratio(" not in tech_block
    assert "panel_ctx.resolver.compute_energy()" in tech_block

    overview_start = source.index("def get_overview_building_rows(")
    overview_end = source.index("\n\n# ", overview_start)
    overview_block = source[overview_start:overview_end]
    assert "_panel_energy_ratio(" not in overview_block
    assert "panel_ctx.resolver.compute_energy()" in overview_block
