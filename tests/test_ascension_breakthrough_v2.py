from __future__ import annotations

from decimal import Decimal

import pytest

from game import production_formula as pf
from game.mine_evolution.nodebuster import (
    BREAKTHROUGH_WINDOW_LEVELS,
    SKILL_CATALOG,
    panel_fields,
    rebuild_window_extra_levels,
    reset_start_level,
    skill_point_cost,
    skill_prerequisites_met,
    tail_power_bonus_hundredths,
)
from scripts.sim_ascension_breakthroughs import SCENARIOS, hours_to_target, run_horizons, uni1_q4_curve


def _scenario(key: str):
    return next(row for row in SCENARIOS if row.key == key)


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


def test_legacy_reconstruction_changes_the_prestige_loop():
    skills = {
        "reconstruction": 8,
        "overdrive": 0,
        "legacy_reconstruction": 1,
    }
    assert reset_start_level(skills, 400) == 140
    assert reset_start_level(skills, 500) == 175
    assert reset_start_level(skills, 1000) == 199


def test_breakthrough_window_extends_rebuild_discount_exactly_25_levels():
    assert BREAKTHROUGH_WINDOW_LEVELS == 25
    assert rebuild_window_extra_levels({"breakthrough_window": 0}) == 0
    assert rebuild_window_extra_levels({"breakthrough_window": 1}) == 25


def test_tail_breakthroughs_are_q410_then_q420():
    assert tail_power_bonus_hundredths({"core_resonance": 0}) == 0
    assert tail_power_bonus_hundredths({"core_resonance": 1}) == 10
    assert tail_power_bonus_hundredths(
        {"core_resonance": 1, "singularity_excavation": 1}
    ) == 20


@pytest.mark.parametrize(
    ("level", "q410_pct", "q420_pct"),
    (
        (200, 3.4, 6.9),
        (300, 7.7, 15.8),
        (500, 13.5, 28.5),
        (650, 16.6, 35.6),
        (1000, 21.8, 48.1),
    ),
)
def test_fractional_q_tail_matches_breakthrough_balance_table(level, q410_pct, q420_pct):
    q4 = pf.endgame_tail_mine_output_decimal("metal", level, pivot_level=120, tail_power=4)
    q410 = pf.endgame_tail_mine_output_decimal(
        "metal", level, pivot_level=120, tail_power=Decimal("4.10")
    )
    q420 = pf.endgame_tail_mine_output_decimal(
        "metal", level, pivot_level=120, tail_power=Decimal("4.20")
    )
    assert (float(q410 / q4) - 1.0) * 100.0 == pytest.approx(q410_pct, abs=0.08)
    assert (float(q420 / q4) - 1.0) * 100.0 == pytest.approx(q420_pct, abs=0.08)


def test_personal_tail_bonus_only_changes_active_endgame_tail(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_PIVOT_LEVEL", 120)
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_TAIL_POWER", 4)

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")
    legacy_base = pf.mine_output_decimal("metal", 500)
    legacy_breakthrough = pf.mine_output_decimal(
        "metal", 500, tail_power_bonus_hundredths=20
    )
    assert legacy_breakthrough == legacy_base

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    active_base = pf.mine_output_decimal("metal", 500)
    active_breakthrough = pf.mine_output_decimal(
        "metal", 500, tail_power_bonus_hundredths=20
    )
    assert float(active_breakthrough / active_base) == pytest.approx(1.285, abs=0.001)


def test_six_and_twelve_month_simulation_stays_progressive_without_runaway():
    results = run_horizons()
    baseline = results["baseline_q4"]
    core = results["core_resonance"]
    singularity = results["singularity"]
    stacked = results["singularity_stack"]
    full = results["breakthrough_full"]

    assert core["182.5d"] >= baseline["182.5d"]
    assert singularity["182.5d"] >= core["182.5d"]
    assert stacked["365d"] > singularity["365d"]
    assert full["182.5d"] < 350
    assert full["365d"] < 500


def test_reinvestment_benchmarks_match_balance_review():
    with uni1_q4_curve():
        baseline_days = hours_to_target(_scenario("baseline_q4"), 300) / Decimal(24)
        current_days = hours_to_target(_scenario("current_stack"), 300) / Decimal(24)
        q420_days = hours_to_target(_scenario("singularity"), 300) / Decimal(24)
        q420_stack_days = hours_to_target(_scenario("singularity_stack"), 300) / Decimal(24)

    assert float(baseline_days) == pytest.approx(395.0, abs=2.0)
    assert float(current_days) == pytest.approx(282.0, abs=2.0)
    assert float(q420_days) == pytest.approx(355.0, abs=2.0)
    assert float(q420_stack_days) == pytest.approx(254.0, abs=2.0)


def test_panel_preview_uses_current_record_depth_for_legacy_reconstruction():
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
    assert fields["nodebuster_reset_level"] == 175
