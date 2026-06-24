"""GC-829 — fresh account progression sim smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fresh_account_progression_sim as sim  # noqa: E402
from game.economy_balance import NEUTRAL_BALANCE_SLOT, reference_production_per_hour  # noqa: E402


def test_early_mine_reference_table():
    assert reference_production_per_hour("metal", 1, slot=NEUTRAL_BALANCE_SLOT) == 24.0
    l2 = reference_production_per_hour("metal", 2, slot=NEUTRAL_BALANCE_SLOT)
    assert 69.0 <= l2 <= 71.0
    l3 = reference_production_per_hour("metal", 3, slot=NEUTRAL_BALANCE_SLOT)
    assert 130.0 <= l3 <= 135.0


def test_alpha_current_defaults_under_one_research_speed():
    preset = sim.PRESETS["alpha_current"]
    assert preset["production_speed"] == 1.0
    assert preset["research_speed"] < 1.0


def test_sim_checkpoints_monotonic_time():
    _, cps = sim.run_simulation(sim.PRESETS["alpha_current"], horizon_sec=86400 * 3)
    assert cps["1h"]["metal_mine"] >= 6
    assert cps["1h"]["research_lab"] >= 1
    assert cps["1h"]["build_completions"] >= 8
    assert cps["24h"]["prod_metal_h"] >= cps["1h"]["prod_metal_h"]
    assert cps["24h"]["build_completions"] > cps["1h"]["build_completions"]


def test_build_speed_changes_timer_not_early_mine_level():
    """With GC-836 starter resources, early levels are no longer resource-gated at 24h."""
    _, slow = sim.run_simulation(sim.PRESETS["alpha_current"], horizon_sec=86400)
    _, fast = sim.run_simulation(sim.PRESETS["alpha_proposed_ferdi"], horizon_sec=86400)
    assert slow["24h"]["metal_mine"] >= 10
    assert fast["24h"]["research_completions"] >= slow["24h"]["research_completions"]
