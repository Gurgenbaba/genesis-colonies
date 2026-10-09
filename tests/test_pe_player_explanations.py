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
    assert "pe_supply_source_locked" in html
    assert "pe_supply_source_active" in html
    assert "pe_supply_source_inactive" in html
    assert "source.unlock_steps" in html
    assert "pe_economy_help_numbers" in html
    assert "pe_economy_help_action" in html
    assert 'href="#pe-section-research"' in html
    assert "pe_research_locked_guide" in html


def test_economy_import_deficit_uses_active_local_chain_rates():
    src = (TEMPLATE.parent.parent / "game/planet_evolution/economy.py").read_text(encoding="utf-8")
    assert "def _active_local_supply_rates(" in src
    assert "local_chain_rates = _active_local_supply_rates(" in src
    assert "local_chain_rates.get(key, Decimal(0))" in src


def test_supply_unlock_steps_are_derived_from_actual_definitions():
    src = (TEMPLATE.parent.parent / "game/planet_evolution/dashboard.py").read_text(encoding="utf-8")
    assert "def _supply_source_plan(" in src
    assert "get_chains()" in src
    assert "get_research_defs()" in src
    assert "planet_research.get(tech_key, 0)" in src
    assert "pe_supply_unlock_title" in src
