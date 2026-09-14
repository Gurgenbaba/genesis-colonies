"""GC-ENDGAME-ECO-REBASE-002 — coordinated Production/Cost/Research/Score V2."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import game.production_formula as pf
from game.economy_balance import cumulative_upgrade_resource_totals, mine_roi_anchor_hours
from game.progression_valuation import (
    V2_PIVOT_LEVEL,
    building_progression_resources_v2,
    building_progression_value_v2,
    reference_investment_horizon_hours_v2,
    reference_mine_output_v2,
    research_progression_resources_v2,
)
from game.research import cumulative_research_resource_totals


@pytest.fixture(autouse=True)
def _restore_rollout(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_PIVOT_LEVEL", 120)
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_TAIL_POWER", 2)
    yield


def test_final_candidate_defaults_to_l120_q2():
    assert V2_PIVOT_LEVEL == 120
    assert pf.ENDGAME_PRODUCTION_PIVOT_LEVEL == 120
    assert pf.ENDGAME_PRODUCTION_TAIL_POWER == 2


def test_v2_tail_matches_approved_relative_shape():
    base = reference_mine_output_v2("metal", 120)
    expected = {
        120: 1.0,
        150: 4.88,
        200: 17.86,
        300: 68.21,
        500: 266.5,
        650: 500.6,
        1000: 1331.0,
    }
    for level, ratio in expected.items():
        actual = float(reference_mine_output_v2("metal", level) / base)
        assert actual == pytest.approx(ratio, rel=0.006)


def test_v2_investment_horizon_matches_approved_days():
    expected_days = {120: 83.33, 200: 119, 300: 158, 650: 272, 1000: 368}
    for level, days in expected_days.items():
        actual = float(reference_investment_horizon_hours_v2(level)) / 24.0
        assert actual == pytest.approx(days, rel=0.035)


def test_metal_mine_l650_progression_value_is_about_203_billion():
    value = building_progression_value_v2("metal_mine", 650)
    assert value == pytest.approx(203_000_000_000, rel=0.02)


def test_v2_building_valuation_preserves_historical_range_through_l120():
    for level in (1, 20, 60, 100, 120):
        old = cumulative_upgrade_resource_totals("metal_mine", level)
        m, c, f = building_progression_resources_v2("metal_mine", level)
        assert (m, c, f) == (old["metal"], old["crystal"], old["fuel_cells"])


def test_v2_research_valuation_preserves_historical_range_through_l120():
    for level in (1, 10, 40, 80, 120):
        old = cumulative_research_resource_totals("mining_tech", level)
        m, c, f = research_progression_resources_v2("mining_tech", level)
        assert (m, c, f) == (old["metal"], old["crystal"], old["fuel_cells"])


def test_active_mine_cost_horizon_rises_after_l120(monkeypatch):
    assert mine_roi_anchor_hours(120) == pytest.approx(2000.0)
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    assert mine_roi_anchor_hours(120) == pytest.approx(2000.0)
    assert mine_roi_anchor_hours(650) / 24.0 == pytest.approx(272, rel=0.035)
    assert mine_roi_anchor_hours(1000) / 24.0 == pytest.approx(368, rel=0.035)


def test_research_effect_tail_is_active_only_and_diminishing(monkeypatch):
    assert pf.research_effective_level(650) == 650.0
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "shadow")
    assert pf.research_effective_level(650) == 650.0
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    assert pf.research_effective_level(120) == 120.0
    assert 120.0 < pf.research_effective_level(650) < 650.0
    assert pf.research_effective_level(1000) > pf.research_effective_level(650)


def _sanitize_total_in_cold_start_mode(mode: str) -> dict:
    payload = {
        "resource_score": 10_000,
        "building_score": 100,
        "research_score": 50,
        "fleet_score": 20,
        "defense_score": 10,
        "evolution_score": 5,
    }
    env = os.environ.copy()
    env.update(
        {
            "GC_ENDGAME_ECONOMY_MODE": str(mode),
            "GC_ENDGAME_PRODUCTION_PIVOT": "120",
            "GC_ENDGAME_PRODUCTION_TAIL_POWER": "2",
        }
    )
    code = (
        "import inspect, json; "
        "from game.production_formula import ENDGAME_ECONOMY_MODE, endgame_economy_mode; "
        "from game.ranking_core import _sanitize_scores; "
        f"print(json.dumps({{'requested': {mode!r}, 'constant': ENDGAME_ECONOMY_MODE, 'resolved': endgame_economy_mode(), 'scores': _sanitize_scores({payload!r}), 'source': inspect.getsource(_sanitize_scores)}}, sort_keys=True))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_liquid_wealth_leaves_progression_total_only_at_atomic_active_cutover():
    legacy = _sanitize_total_in_cold_start_mode("legacy")
    shadow = _sanitize_total_in_cold_start_mode("shadow")
    active = _sanitize_total_in_cold_start_mode("active")
    assert legacy["resolved"] == "legacy", legacy
    assert shadow["resolved"] == "shadow", shadow
    assert active["resolved"] == "active", active
    assert legacy["scores"]["total_score"] == 10_185, legacy
    assert shadow["scores"]["total_score"] == 10_185, shadow
    assert active["scores"]["resource_score"] == 10_000, active
    assert active["scores"]["total_score"] == 185, active
