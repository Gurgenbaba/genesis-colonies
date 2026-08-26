"""GC-PE-UX-01 — player-facing actions must expose canonical gameplay impact."""
from __future__ import annotations

from game.planet_evolution.events import preview_event_choice
from game.planet_evolution.failures import failure_runtime_culture_drift
from game.planet_evolution.impact import (
    event_outcome_impact_rows,
    mechanics_impact_rows,
    policy_tradeoff_rows,
)


def test_mechanics_preview_uses_live_parser_and_ignores_uncompiled_raw_keys():
    rows = mechanics_impact_rows(
        {
            "planet_research_speed_flag": 0.15,
            "contraband_output_bonus": 0.50,  # not consumed by live compiler
        }
    )
    assert any(r["label_key"] == "pe_impact_effect_research_speed" and r["value"] == "+15%" for r in rows)
    assert not any(r.get("target") == "contraband_output_bonus" for r in rows)


def test_policy_tradeoff_preview_matches_live_culture_stats_only():
    rows = policy_tradeoff_rows(
        {"stability_drift": -2.0, "industrial_pressure_drift": 3.0, "not_live_drift": 99}
    )
    assert {(r["label_key"], r["value"]) for r in rows} == {
        ("pe_culture_stability", "-2"),
        ("pe_culture_industrial_pressure", "+3"),
    }


def test_event_preview_is_same_authoritative_outcome_payload():
    edef = {"choices": [{"key": "overload", "outcome": "overload"}]}
    preview = preview_event_choice(edef, "overload")
    assert preview is not None
    assert preview["outcome_key"] == "overload"
    assert preview["outcome"]["culture_delta"] == {"stability": -15, "industrial_pressure": 10}
    assert preview["outcome"]["add_failure"] == "reactor_degraded"


def test_event_impact_exposes_current_after_and_change():
    rows = event_outcome_impact_rows(
        {"culture_delta": {"stability": -15}, "grant_special_resource": {"refined_ferronit": 2000}},
        {"stability": 80},
    )
    culture = next(r for r in rows if r["kind"] == "culture_change")
    assert culture["current"] == 80
    assert culture["after"] == 65
    assert culture["value"] == "-15"
    reward = next(r for r in rows if r["kind"] == "resource")
    assert reward["value"] == "+2000"


def test_failure_runtime_drift_is_single_canonical_projection():
    assert failure_runtime_culture_drift({"reactor_crisis"}) == {"stability": -0.5}
    assert failure_runtime_culture_drift({"stability_collapse"}) == {"stability": -1.0}
    assert failure_runtime_culture_drift({"reactor_crisis", "stability_collapse"}) == {"stability": -1.5}
