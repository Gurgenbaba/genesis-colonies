"""Unified Planet Evolution inline-help contract."""
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates/planet_evolution.html"


def test_guides_explain_four_player_questions():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "{% macro pe_player_guide(topic, benefit, requirement, next_step) %}" in html
    for title in ("pe_tech_info_summary_label", "pe_tech_info_effect_label", "pe_research_missing", "pe_next_step"):
        assert title in html
    for domain in ("pe_planet_research", "pe_tab_policies", "pe_card_ascension_title", "pe_spec",
                   "pe_planet_bonuses_title", "pe_development_stage", "pe_card_next_step"):
        assert domain in html


def test_research_and_economy_use_existing_live_data():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "tech.missing_human" in html
    assert "tech.impact.rows" in html
    assert "action.deficit.supply_source" in html
    assert "source.unlock_steps" in html


def test_locked_policies_explain_existing_server_gate():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "data-pe-policy-locked" in html
    assert "opt.locked_reason_key" in html
    assert "rejectattr('eligible')" in html
    assert "pe_impact_contract(opt.impact, true)" in html
