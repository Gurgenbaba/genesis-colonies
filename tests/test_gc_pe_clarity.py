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

def test_planet_evolution_template_exposes_impact_before_actions():
    from pathlib import Path
    src=(Path(__file__).resolve().parents[1]/'templates'/'planet_evolution.html').read_text(encoding='utf-8')
    assert 'macro pe_impact_contract' in src
    assert 'pe-tech-impact-inline' in src
    assert 'pe-policy-option-card' in src
    assert 'pe-event-choice-card' in src
    assert 'pe_impact_contract(card.impact, true)' in src
    assert 'pe-crisis-clarity' in src
    assert 'pe_hero_current_research_xp' not in src
    assert 'pe_activity_xp_expedition_progress' not in src



def test_planet_evolution_decision_first_layout_is_shell_owned():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    css = (root / "static" / "css" / "planet_evolution_clarity.css").read_text(encoding="utf-8")

    assert "pe-core-row--research-idle" in template
    assert "css/planet_evolution_clarity.css" in base
    assert 'grid-template-areas: "goal tech"' in css
    assert ".pe-core-row--research-idle" in css
    assert "grid-template-columns: minmax(0, 1.58fr)" in css
    assert 'grid-template-areas:\n      "goal"\n      "tech"' in css
    assert ".pe-goal-cta" in css


def test_impact_locale_contract_has_exact_parity():
    from pathlib import Path
    import json
    root=Path(__file__).resolve().parents[1]/'locales'
    langs=('de','en','fr','es','pl','tr','ru','pt')
    payloads={lang:json.loads((root/f'{lang}.json').read_text(encoding='utf-8')) for lang in langs}
    keys={k for k in payloads['en'] if k.startswith('pe_impact_') or k.startswith('pe_crisis_clarity_') or k.startswith('pe_failure_')}
    assert keys
    for lang in langs:
        assert keys.issubset(payloads[lang])
        assert all(str(payloads[lang][k]).strip() for k in keys)
