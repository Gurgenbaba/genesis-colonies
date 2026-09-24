from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _face(card: str, marker: str, end_marker: str) -> str:
    return card.split(marker, 1)[1].split(end_marker, 1)[0]


def test_building_cards_flip_secondary_upgrade_data_behind_artwork():
    tpl = _read("templates/buildings.html")
    card = tpl.split('<article class="gc-building-card', 1)[1].split("</article>", 1)[0]
    front = _face(card, "data-card-flip-front", "data-card-flip-back")
    back = card.split("data-card-flip-back", 1)[1]

    assert "data-card-flip" in card
    assert "gc-bld-hero-level" in front
    assert "render_building_head_action" in front
    assert "render_hero_time_chip" not in front
    assert "gc-bld-card-meta--costs-only" not in front

    assert "render_hero_time_chip" in back
    assert "render_building_effect_bundle" in back
    assert "gc-bld-card-meta--costs-only" in back
    assert "data-building-tech-data" in front
    assert "<details" not in card
    assert "js/card_flip.js" in tpl


def test_research_cards_flip_secondary_upgrade_data_behind_artwork():
    tpl = _read("templates/research.html")
    card = tpl.split('<article class="gc-building-card gc-research-card', 1)[1].split(
        "</article>", 1
    )[0]
    front = _face(card, "data-card-flip-front", "data-card-flip-back")
    back = card.split("data-card-flip-back", 1)[1]

    assert "data-card-flip" in card
    assert "tech-level-current" in front
    assert "render_research_head_action" in front
    assert "render_hero_time_chip" not in front
    assert "gc-bld-card-meta--costs-only" not in front

    assert "render_hero_time_chip" in back
    assert "render_research_effect_bundle" in back
    assert "gc-bld-card-meta--costs-only" in back
    assert "render_research_blockers" in back
    assert "data-research-tech-data" in front
    assert "<details" not in card
    assert "js/card_flip.js" in tpl


def test_defense_cards_keep_build_action_front_and_stats_costs_on_back():
    tpl = _read("templates/defense.html")
    card = tpl.split('<article class="gc-ship-card', 1)[1].split("</article>", 1)[0]
    front = _face(card, "data-card-flip-front", "data-card-flip-back")
    back = card.split("data-card-flip-back", 1)[1]

    assert "data-defense-build" in front
    assert "data-defense-max" in front
    assert "render_compact_unit_stat_chips" not in front
    assert "data-defense-cost" not in front
    assert "render_compact_unit_stat_chips" in back
    assert "data-defense-cost" in back
    assert "render_unit_build_time_footer" in back
    assert "js/card_flip.js" in tpl
    assert "progression_disclosure.css" in tpl


def test_troop_cards_keep_train_action_front_and_cost_time_on_back():
    tpl = _read("templates/partials/barracks_troops_panel.html")
    card = tpl.split('<article class="gc-ship-card', 1)[1].split("</article>", 1)[0]
    front = _face(card, "data-card-flip-front", "data-card-flip-back")
    back = card.split("data-card-flip-back", 1)[1]

    assert "data-troop-train" in front
    assert "data-troop-max" in front
    assert "data-troop-cost" not in front
    assert "data-troop-cost" in back
    assert "render_unit_build_time_footer" in back


def test_shared_flip_contract_uses_artwork_only_and_is_accessible():
    macro = _read("templates/partials/card_hero_img_macros.html")
    js = _read("static/js/card_flip.js")
    css = _read("static/css/progression_disclosure.css")

    assert "data-card-flip-trigger" in macro
    assert 'role="button"' in macro
    assert 'tabindex="0"' in macro
    assert "data-card-flip-back-trigger" in js
    assert "front.inert = on" in js
    assert "back.inert = !on" in js
    assert 'closest("[data-card-flip-trigger]")' in js

    assert "perspective: 1200px" in css
    assert "transform: rotateY(180deg)" in css
    assert "backface-visibility: hidden" in css
    assert "prefers-reduced-motion: reduce" in css
