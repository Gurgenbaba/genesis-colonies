from __future__ import annotations

from decimal import Decimal

import pytest

from game import production_formula as pf
from game.mine_evolution.nodebuster import (
    BREAKTHROUGH_WINDOW_LEVELS,
    LEGACY_RECONSTRUCTION_REBUILD_PRODUCTION_BPS,
    SKILL_CATALOG,
    effective_shortage_ratio_bps,
    energy_draw_bps,
    panel_fields,
    rebuild_production_bonus_bps,
    rebuild_production_multiplier_for,
    rebuild_window_extra_levels,
    reset_start_level,
    skill_point_cost,
    shortage_recovery_bps,
    skill_prerequisites_met,
    tail_power_bonus_hundredths,
)
from scripts.sim_ascension_breakthroughs import (
    SCENARIOS,
    hours_to_target,
    pooled_empire_level_after_days,
    queue_floor_level_after_days,
    run_horizons,
    uni1_q4_curve,
)


def _scenario(key: str):
    return next(row for row in SCENARIOS if row.key == key)


def test_energy_utility_nodes_are_bounded_and_progressive():
    assert energy_draw_bps({}) == 10000
    assert energy_draw_bps({"optimized_energy": 1}) == 9800
    assert energy_draw_bps({"optimized_energy": 10}) == 8000
    assert energy_draw_bps({"optimized_energy": 999}) == 8000

    assert shortage_recovery_bps({}) == 0
    assert shortage_recovery_bps({"load_balancing": 1}) == 250
    assert shortage_recovery_bps({"load_balancing": 10}) == 2500
    assert shortage_recovery_bps({"load_balancing": 999}) == 2500

    # At 60% grid power rank 10 recovers 25% of the missing 40pp => 70%.
    assert effective_shortage_ratio_bps(6000, {"load_balancing": 10}) == 7000
    assert effective_shortage_ratio_bps(10000, {"load_balancing": 10}) == 10000


def test_load_balancing_requires_energy_optimization_rank_three():
    state = {"best_depth": 500}
    assert skill_prerequisites_met("load_balancing", {"optimized_energy": 2}, state) is False
    assert skill_prerequisites_met("load_balancing", {"optimized_energy": 3}, state) is True


def test_breakthrough_catalog_has_expensive_keystones():
    assert skill_point_cost("core_resonance", 0) == 15
    assert skill_point_cost("legacy_reconstruction", 0) == 20
    assert skill_point_cost("breakthrough_window", 0) == 24
    assert skill_point_cost("singularity_excavation", 0) == 36
    assert all(
        SKILL_CATALOG[key].get("breakthrough") is True
        for key in (
            "core_resonance",
            "legacy_reconstruction",
            "breakthrough_window",
            "singularity_excavation",
        )
    )


def test_breakthrough_depth_and_tree_requirements():
    core_skills = {"deep_yield": 8}
    assert skill_prerequisites_met(
        "core_resonance", core_skills, {"best_depth": 299}
    ) is False
    assert skill_prerequisites_met(
        "core_resonance", core_skills, {"best_depth": 300}
    ) is True

    singularity_skills = {"core_resonance": 1, "overdrive": 3}
    assert skill_prerequisites_met(
        "singularity_excavation", singularity_skills, {"best_depth": 499}
    ) is False
    assert skill_prerequisites_met(
        "singularity_excavation", singularity_skills, {"best_depth": 500}
    ) is True


def test_reconstruction_surge_is_strong_without_duplicating_restart_level():
    base = {"reconstruction": 8, "overdrive": 3}
    with_surge = {**base, "legacy_reconstruction": 1}

    assert LEGACY_RECONSTRUCTION_REBUILD_PRODUCTION_BPS == 10000
    assert rebuild_production_bonus_bps(base) == 0
    assert rebuild_production_bonus_bps(with_surge) == 10000
    assert reset_start_level(base, 1000) == 132
    assert reset_start_level(with_surge, 1000) == 132


def test_reconstruction_surge_runs_to_record_and_window_extends_it():
    profiles = {
        "metal_mine": {
            "state": {
                "ascension_count": 2,
                "points_earned": 80,
                "points_unspent": 0,
                "best_depth": 500,
                "last_depth": 500,
            },
            "skills": {
                "legacy_reconstruction": 1,
                "breakthrough_window": 0,
            },
        }
    }
    assert rebuild_production_multiplier_for(
        1, "metal_mine", 500, profiles=profiles
    ) == pytest.approx(2.00)
    assert rebuild_production_multiplier_for(
        1, "metal_mine", 501, profiles=profiles
    ) == pytest.approx(1.0)

    profiles["metal_mine"]["skills"]["breakthrough_window"] = 1
    assert rebuild_production_multiplier_for(
        1, "metal_mine", 550, profiles=profiles
    ) == pytest.approx(2.00)
    assert rebuild_production_multiplier_for(
        1, "metal_mine", 551, profiles=profiles
    ) == pytest.approx(1.0)


def test_rebuild_surge_boosts_mine_output_not_standard_income():
    base = pf.ProductionContext(resource_type="metal", level=50)
    surged = pf.ProductionContext(
        resource_type="metal",
        level=50,
        mine_rebuild_modifier=2.00,
    )
    base_total = pf.calculate_resource_output("metal", base)
    surged_total = pf.calculate_resource_output("metal", surged)
    standard = pf.standard_output("metal")
    mine = pf.mine_output("metal", 50)

    assert base_total == pytest.approx(standard + mine)
    assert surged_total == pytest.approx(standard + mine * 2.00)


def test_breakthrough_window_extends_rebuild_discount_exactly_25_levels():
    assert BREAKTHROUGH_WINDOW_LEVELS == 50
    assert rebuild_window_extra_levels({"breakthrough_window": 0}) == 0
    assert rebuild_window_extra_levels({"breakthrough_window": 1}) == 50


def test_tail_breakthroughs_are_q315_then_q330():
    assert tail_power_bonus_hundredths({"core_resonance": 0}) == 0
    assert tail_power_bonus_hundredths({"core_resonance": 1}) == 15
    assert tail_power_bonus_hundredths(
        {"core_resonance": 1, "singularity_excavation": 1}
    ) == 30


@pytest.mark.parametrize(
    ("level", "q315_pct", "q330_pct"),
    (
        (200, 7.0, 14.2),
        (300, 14.8, 31.1),
        (500, 25.0, 55.3),
        (650, 30.4, 68.9),
        (1000, 39.6, 93.6),
    ),
)
def test_fractional_q_tail_matches_breakthrough_balance_table(level, q315_pct, q330_pct):
    q3 = pf.endgame_tail_mine_output_decimal("metal", level, pivot_level=120, tail_power=3)
    q315 = pf.endgame_tail_mine_output_decimal(
        "metal", level, pivot_level=120, tail_power=Decimal("3.15")
    )
    q330 = pf.endgame_tail_mine_output_decimal(
        "metal", level, pivot_level=120, tail_power=Decimal("3.30")
    )
    assert (float(q315 / q3) - 1.0) * 100.0 == pytest.approx(q315_pct, abs=0.08)
    assert (float(q330 / q3) - 1.0) * 100.0 == pytest.approx(q330_pct, abs=0.08)


def test_personal_tail_bonus_only_changes_active_endgame_tail(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_PIVOT_LEVEL", 120)
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_TAIL_POWER", 3)

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")
    legacy_base = pf.mine_output_decimal("metal", 500)
    legacy_breakthrough = pf.mine_output_decimal(
        "metal", 500, tail_power_bonus_hundredths=30
    )
    assert legacy_breakthrough == legacy_base

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    active_base = pf.mine_output_decimal("metal", 500)
    active_breakthrough = pf.mine_output_decimal(
        "metal", 500, tail_power_bonus_hundredths=30
    )
    assert float(active_breakthrough / active_base) == pytest.approx(1.553, abs=0.001)


def test_six_and_twelve_month_simulation_stays_progressive_without_runaway():
    results = run_horizons()
    baseline = results["baseline_q3"]
    core = results["core_resonance"]
    singularity = results["singularity"]
    stacked = results["singularity_stack"]
    full = results["breakthrough_full"]

    assert core["182.5d"] >= baseline["182.5d"]
    assert singularity["182.5d"] >= core["182.5d"]
    assert stacked["365d"] > singularity["365d"]
    assert full["182.5d"] < 350
    assert full["365d"] < 500


def test_eleven_world_pooling_cannot_turn_one_year_into_l2000():
    stress = _scenario("singularity_stack")
    with uni1_q4_curve():
        six_month_pool = pooled_empire_level_after_days(
            stress, Decimal("182.5"), feeder_worlds=11
        )
        twelve_month_pool = pooled_empire_level_after_days(
            stress, Decimal("365"), feeder_worlds=11
        )

    six_month_ceiling = queue_floor_level_after_days(Decimal("182.5"))
    twelve_month_ceiling = queue_floor_level_after_days(Decimal("365"))

    assert six_month_pool <= six_month_ceiling < 775
    assert twelve_month_pool <= twelve_month_ceiling < 850
    assert twelve_month_pool < 1000


def test_reinvestment_benchmarks_match_balance_review():
    with uni1_q4_curve():
        baseline_days = hours_to_target(_scenario("baseline_q4"), 300) / Decimal(24)
        current_days = hours_to_target(_scenario("current_stack"), 300) / Decimal(24)
        q420_days = hours_to_target(_scenario("singularity"), 300) / Decimal(24)
        q420_stack_days = hours_to_target(_scenario("singularity_stack"), 300) / Decimal(24)

    assert float(baseline_days) == pytest.approx(886.6, abs=4.0)
    assert float(current_days) == pytest.approx(633.3, abs=4.0)
    assert float(q420_days) == pytest.approx(719.3, abs=4.0)
    assert float(q420_stack_days) == pytest.approx(513.8, abs=4.0)


def test_panel_fields_expose_concrete_energy_and_breakthrough_previews():
    profiles = {
        "metal_mine": {
            "state": {
                "ascension_count": 3,
                "points_earned": 200,
                "points_unspent": 100,
                "best_depth": 500,
                "last_depth": 500,
            },
            "skills": {
                "optimized_energy": 3,
                "load_balancing": 2,
                "deep_yield": 8,
                "reconstruction": 8,
                "frugal_rebuild": 8,
                "rapid_rebuild": 8,
                "overdrive": 3,
                "core_resonance": 0,
                "legacy_reconstruction": 0,
                "breakthrough_window": 0,
                "singularity_excavation": 0,
            },
        }
    }
    fields = panel_fields(1, "metal_mine", 500, profiles=profiles)
    rows = {row["key"]: row for row in fields["nodebuster_skills"]}

    assert fields["nodebuster_energy_draw_reduction_pct"] == pytest.approx(6.0)
    assert fields["nodebuster_shortage_recovery_pct"] == pytest.approx(5.0)

    energy = rows["optimized_energy"]["preview"]
    assert energy["draw_reduction_now_pct"] == pytest.approx(6.0)
    assert energy["draw_reduction_next_pct"] == pytest.approx(8.0)

    load = rows["load_balancing"]["preview"]
    assert load["grid_example_pct"] == 60
    assert load["effective_next_pct"] > load["effective_now_pct"]

    core = rows["core_resonance"]["preview"]
    assert core["tail_to"] > core["tail_from"]
    assert [point["level"] for point in core["levels"]] == [300, 500, 1000]
    assert core["levels"][1]["pct"] > 0

    legacy = rows["legacy_reconstruction"]["preview"]
    assert legacy["production_bonus_pct"] == pytest.approx(100.0)
    assert legacy["rebuild_reach"] == 500

    window = rows["breakthrough_window"]["preview"]
    assert window["window_after"] - window["window_before"] == 50


def test_panel_legacy_keystone_keeps_restart_baseline_and_reports_surge():
    profiles = {
        "metal_mine": {
            "state": {
                "ascension_count": 2,
                "points_earned": 80,
                "points_unspent": 0,
                "best_depth": 400,
                "last_depth": 400,
            },
            "skills": {
                "reconstruction": 8,
                "legacy_reconstruction": 1,
            },
        }
    }
    fields = panel_fields(
        1,
        "metal_mine",
        500,
        profiles=profiles,
    )
    assert fields["nodebuster_best_depth"] == 400
    assert fields["nodebuster_reset_level"] == 80
    assert fields["nodebuster_rebuild_production_bonus_pct"] == pytest.approx(100.0)
    assert fields["nodebuster_rebuild_production_active"] is False
    assert fields["nodebuster_rebuild_production_reach"] == 400
