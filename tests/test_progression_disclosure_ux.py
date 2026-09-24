from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_building_cards_keep_secondary_upgrade_data_behind_reveal():
    tpl = _read("templates/buildings.html")
    card = tpl.split('<article class="gc-building-card', 1)[1].split("</article>", 1)[0]
    hero = card.split('<div class="gc-bld-card-hero">', 1)[1].split(
        '<details class="gc-progression-reveal"', 1
    )[0]

    assert "gc-bld-hero-level" in hero
    assert "render_building_head_action" in hero
    assert "render_hero_time_chip" not in hero
    assert "gc-bld-card-meta--costs-only" not in hero

    reveal = card.split('<details class="gc-progression-reveal"', 1)[1]
    assert "render_hero_time_chip" in reveal
    assert "render_building_effect_bundle" in reveal
    assert "gc-bld-card-meta--costs-only" in reveal
    assert "data-building-tech-data" in card
    assert "progression_disclosure.css" in tpl


def test_research_cards_keep_secondary_upgrade_data_behind_reveal():
    tpl = _read("templates/research.html")
    card = tpl.split('<article class="gc-building-card gc-research-card', 1)[1].split(
        "</article>", 1
    )[0]
    hero = card.split('<div class="gc-bld-card-hero">', 1)[1].split(
        '<details class="gc-progression-reveal"', 1
    )[0]

    assert "tech-level-current" in hero
    assert "render_research_head_action" in hero
    assert "render_hero_time_chip" not in hero
    assert "gc-bld-card-meta--costs-only" not in hero

    reveal = card.split('<details class="gc-progression-reveal"', 1)[1]
    assert "render_hero_time_chip" in reveal
    assert "render_research_effect_bundle" in reveal
    assert "gc-bld-card-meta--costs-only" in reveal
    assert "data-research-tech-data" in card
    assert "progression_disclosure.css" in tpl


def test_reveal_uses_native_details_and_reduced_motion_contract():
    css = _read("static/css/progression_disclosure.css")
    assert ".gc-progression-reveal > summary" in css
    assert ".gc-progression-reveal[open]" in css
    assert "prefers-reduced-motion: reduce" in css
