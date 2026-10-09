"""Planet Evolution must explain future research and economy blockers in-place."""
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates/planet_evolution.html"


def test_locked_planet_tech_has_same_info_explanation_as_available_tech():
    html = TEMPLATE.read_text(encoding="utf-8")
    card = html.split("{% macro pe_research_tech_card(")[1].split("{% macro pe_card_queue_block(")[0]
    assert 'class="pe-tech-info-btn pe-info-trigger"' in card
    assert "{{ pe_tech_info_source(tech) }}" in card
    assert "variant != 'locked'" not in card


def test_economy_step_explains_supply_and_next_action():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "pe_economy_help_intro" in html
    assert "pe_economy_help_numbers" in html
    assert "pe_economy_help_action" in html
    assert 'href="/empire"' in html
    assert "pe_research_locked_guide" in html
