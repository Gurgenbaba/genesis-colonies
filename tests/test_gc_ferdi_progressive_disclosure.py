"""GC-FERDI-DISCLOSURE-001 — progression cards show only acute data up front."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _first_card(template: str, marker: str) -> str:
    start = template.index(marker)
    end = template.index("</article>", start)
    return template[start:end]


def test_building_card_hides_secondary_upgrade_data_behind_one_reveal():
    source = _read("templates/buildings.html")
    card = _first_card(source, '<article class="gc-building-card')

    reveal = card.index('<details class="gc-progression-reveal"')
    assert card.index("render_building_head_action") < reveal
    assert card.index("gc-bld-hero-level") < reveal
    assert card.index("render_hero_time_chip", reveal) > reveal
    assert card.index("render_building_effect_bundle", reveal) > reveal
    assert card.index("gc-bld-card-meta--costs-only", reveal) > reveal

    # Technical Data stays the deeper power-user layer on the title.
    assert "data-building-tech-data" in card


def test_research_card_hides_secondary_upgrade_data_behind_one_reveal():
    source = _read("templates/research.html")
    card = _first_card(source, '<article class="gc-building-card gc-research-card')

    reveal = card.index('<details class="gc-progression-reveal"')
    assert card.index("render_research_head_action") < reveal
    assert card.index("tech-level-current") < reveal
    assert card.index("render_hero_time_chip", reveal) > reveal
    assert card.index("render_research_effect_bundle", reveal) > reveal
    assert card.index("gc-bld-card-meta--costs-only", reveal) > reveal
    assert "data-research-tech-data" in card


def test_progression_reveal_is_native_accessible_and_motion_safe():
    css = _read("static/css/progression_disclosure.css")
    assert ".gc-progression-reveal > summary" in css
    assert "list-style: none" in css
    assert ":focus-visible" in css
    assert "@media (prefers-reduced-motion: reduce)" in css

    buildings = _read("templates/buildings.html")
    research = _read("templates/research.html")
    assert "css/progression_disclosure.css" in buildings
    assert "css/progression_disclosure.css" in research
