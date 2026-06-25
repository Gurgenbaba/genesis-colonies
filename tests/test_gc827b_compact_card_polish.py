"""GC-827B — compact card polish (Ferdi freeze)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_card_order_effect_before_costs():
    bld = _read("templates/buildings.html")
    chunk = bld.split("render_building_table")[1].split("{% endmacro %}")[0]
    assert chunk.index("render_building_effect_bundle") < chunk.index("gc-bld-card-meta--costs-only")

    research = _read("templates/research.html")
    assert research.index("render_research_effect_bundle(tech)") < research.index("gc-bld-card-meta--costs-only")


def test_lr_layout_and_cost_stack():
    prog = _read("templates/partials/progression_cards.html")
    assert "gc-card-lr-row" in prog
    assert "gc-cost-stack" in prog
    assert "gc-card-section-label" in prog
    assert "progression_costs_heading" in prog


def test_unified_requirements_on_warn_hover():
    bld = _read("templates/buildings.html")
    assert "gc-req-hover-trigger" in bld
    assert "render_req_hover_attrs" in bld
    assert "render_card_requirements_block" not in bld

    research = _read("templates/research.html")
    assert "gc-req-hover-trigger" in research
    assert "render_card_requirements_block" not in research


def test_energy_footer_has_consumption_label():
    strip = _read("templates/partials/building_effect_strip.html")
    assert "buildings_effect_energy_use" in strip
    footer = strip.split("render_building_card_footer")[1].split("{% endmacro %}")[0]
    assert "gc-card-lr-label" in footer
    assert "effect_current" in footer

    js = _read("static/main.js")
    footer_fn = js.split("function renderBuildingCardFooterHtml")[1].split("function serializeReqHoverItems")[0]
    assert "buildings_effect_energy_use" in footer_fn
    assert "effect_current" in footer_fn


def test_ship_cards_attack_only_speed_in_footer():
    ship = _read("templates/partials/progression_cards.html")
    macro = ship.split("render_compact_unit_stat_chips")[1].split("{% endmacro %}")[0]
    assert "ship_stat_attack" in macro
    assert "gc-bld-effect-bundle" in macro
    assert "data-unit-build-time" not in macro

    time_macro = ship.split("render_unit_build_time_footer")[1].split("{% endmacro %}")[0]
    assert "unit_technical_build_time" in time_macro
    assert "gc-card-lr-row" in time_macro
    assert "gc-card-footer-row--time" in time_macro

    shipyard = _read("templates/shipyard.html")
    assert "render_compact_unit_stat_chips(ship.attack" in shipyard
    assert "render_unit_build_time_footer(ship.build_seconds)" in shipyard
    assert "'ship'" in shipyard
    assert "data-shipyard-blockers" not in shipyard
    assert "render_shipyard_resource_blocker" not in shipyard
    assert "gc-req-hover-trigger" in shipyard


def test_defense_cards_match_compact_layout():
    defense = _read("templates/defense.html")
    assert "render_unit_build_time_footer(unit.build_seconds)" in defense
    assert "data-defense-blockers" not in defense
    assert "render_shipyard_resource_blocker" not in defense
    assert "gc-req-hover-trigger" in defense
    chunk = defense.split("data-defense-buildable-list")[1].split("data-defense-locked-list")[0]
    assert chunk.index("render_compact_unit_stat_chips") < chunk.index("render_card_costs_block")
    assert chunk.index("render_card_costs_block") < chunk.index("render_unit_build_time_footer")


def test_canonical_resource_icons_in_cost_chip():
    prog = _read("templates/partials/progression_cards.html")
    assert "img/res/Ferronit.webp" in prog
    assert "metal.png" not in prog
    assert "crystal.png" not in prog


def test_main_js_lr_rows_and_cost_stack():
    js = _read("static/main.js")
    assert "function renderCardLrRow" in js
    assert "gc-cost-stack" in js
    assert "renderCardRequirementsBlockHtml" not in js
    assert "initCardRequirementsHoverOnce" in js
    patch = js.split("function patchCompactUnitStatChips")[1].split("function patchProductionStatChips")[0]
    assert "renderUnitBuildTimeFooterHtml" in patch
    time_footer = js.split("function renderUnitBuildTimeFooterHtml")[1].split("function shipyardReqItemVisible")[0]
    assert "gc-card-footer-row--time" in time_footer
    assert "gc-card-lr-row" in time_footer
    assert "gc-compact-chip--defense" not in patch
    assert "renderShipCostStackHtml" in js
