"""
GC-827 — unified compact Genesis card layout.

Run: python -m pytest tests/test_gc827_compact_cards.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_compact_strip_template_has_no_current_next_labels():
    strip = _read("templates/partials/building_effect_strip.html")
    assert "buildings_prod_current" not in strip
    assert "buildings_prod_after" not in strip
    assert "gc-card-benefit-block" in strip
    assert "gc-compact-chip" not in strip or "render_compact_effect_chip" in strip


def test_buildings_template_uses_compact_layout():
    tpl = _read("templates/buildings.html")
    assert "render_building_effect_bundle" in tpl
    assert "gc-bld-card-meta--costs-only" in tpl
    card_chunk = tpl.split("render_building_table")[1].split("{% endmacro %}")[0]
    assert card_chunk.index("render_building_effect_bundle") < card_chunk.index("gc-bld-card-meta--costs-only")
    assert "buildings_prod_current" not in tpl
    assert "render_card_requirements_block" not in tpl


def test_research_template_uses_compact_layout():
    tpl = _read("templates/research.html")
    assert "render_compact_effect_row" in tpl
    assert "gc-card-benefit-block" in tpl
    assert "buildings_prod_current" not in tpl
    assert 'class="gc-bld-prod-line"' not in tpl


def test_shipyard_template_compact_unit_stats():
    tpl = _read("templates/shipyard.html")
    assert "render_compact_unit_stat_chips" in tpl
    assert "ship.attack" in tpl
    assert "'ship'" in tpl
    assert "render_card_costs_block" in tpl
    assert "data-production-stats" not in tpl
    assert "render_ship_card_subhead" not in tpl.split("buildable_ships")[1].split("{% else %}")[0]


def test_defense_template_compact_unit_stats():
    tpl = _read("templates/defense.html")
    assert "render_compact_unit_stat_chips" in tpl
    assert "unit.attack" in tpl
    assert "data-production-stats" not in tpl


def test_shipyard_api_includes_combat_stats():
    shipyard = _read("game/shipyard.py")
    assert '"attack": int(spec.get("attack"' in shipyard


def test_defense_api_includes_combat_stats():
    defense = _read("game/defense.py")
    assert '"attack": int(stats.attack' in defense


def test_main_js_compact_card_patches():
    js = _read("static/main.js")
    assert "function renderCompactEffectChipHtml" in js
    assert "function patchCompactUnitStatChips" in js
    chunk = js.split("function renderCompactEffectChipHtml")[1].split("function patchBuildingProduction")[0]
    assert "buildings_prod_current" not in chunk
