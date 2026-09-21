from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent.parent


def test_building_card_keeps_ascension_compact():
    template = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    start = template.index("{% if b.nodebuster is defined and b.nodebuster %}")
    end = template.index("{% else %}\n          <div class=\"gc-bld-evo-block\" data-mine-evolution", start)
    block = template[start:end]

    assert "mine_ascension_title" in block
    assert "nodebuster_points_unspent" in block
    assert "data-mine-evolve" in block
    assert "nodebuster_skills" not in block
    assert "gc-nodebuster-tree" not in block
    # Best depth may be carried as hidden confirmation data, but must not be
    # rendered as another noisy building-card stat.
    assert "mine_ascension_best_depth" not in block
    assert "nodebuster_rebuild_cost_pct" not in block
    assert "nodebuster_production_bonus_pct" not in block


def test_skilltree_has_dedicated_mine_ascension_tab():
    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")

    assert "skilltree_tab_commander" in template
    assert "skilltree_tab_ascension" in template
    assert "data-ascension-skilltree" in template
    assert "data-ascension-mine-tab" in template
    assert "data-ascension-mine-panel" in template
    assert "mine.nodebuster_skills" in template
    assert "gc-ascension-tree__edges" in template
    assert "data-ascension-node-select" in template
    assert "data-ascension-detail" in template
    assert "data-nodebuster-skill" in template
    assert "data-mine-evolve" in template


def test_player_facing_ascension_title_never_says_nodebuster():
    for locale_path in sorted((ROOT / "locales").glob("*.json")):
        data = json.loads(locale_path.read_text(encoding="utf-8"))
        assert "nodebuster" not in str(data.get("nodebuster_title", "")).lower()
        assert data.get("mine_ascension_title")
        assert data.get("skilltree_tab_ascension")


def test_skilltree_route_forwards_mine_ascension_context():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    start = source.index('def skilltree_view():')
    end = source.index('@app.route("/api/commander/class/pick"', start)
    block = source[start:end]

    assert 'page.get("mine_ascension")' in block
    assert "mine_ascension=mine_ascension" in block


def test_mine_ascension_assets_are_shell_owned_for_pjax_navigation():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    skilltree = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")

    assert "js/pages/mine_nodebuster.js" in base
    assert "css/nodebuster_ascension.css" in base
    assert "js/pages/mine_nodebuster.js" not in skilltree
    assert "css/nodebuster_ascension.css" not in skilltree


def test_skilltree_ascension_uses_server_readiness_and_inspector_actions():
    source = (ROOT / "game" / "commander_classes.py").read_text(encoding="utf-8")
    assert 'row["ascension_blocked_by_queue"]' in source
    assert 'row["ascension_ready"]' in source
    assert "get_build_queue_rows" in source

    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")
    assert "mine.ascension_ready" in template
    assert "gc-ascension-cta" in template

    js = (ROOT / "static" / "js" / "pages" / "mine_nodebuster.js").read_text(encoding="utf-8")
    assert 'target.closest("[data-ascension-mine-tab]")' in js
    assert 'target.closest("[data-ascension-node-select]")' in js
    assert "selectAscensionNode" in js
    assert "activateMineTab" in js


def test_ascension_tree_is_visual_and_matches_commander_layout_language():
    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "nodebuster_ascension.css").read_text(encoding="utf-8")

    assert "gc-ascension-node__art" in template
    assert "gc-ascension-node__state" in template
    assert "gc-ascension-node__name" not in template
    assert "img/classes/icons/production.webp" in template
    assert "gc-ascension-tree__edge" in template
    assert "tree_rank.reconstruction >= 5" in template
    assert "tree_rank.deep_yield >= 5" in template
    assert "gc-ascension-node--{{ skill.key }}" in template

    for key in (
        "reconstruction",
        "deep_yield",
        "deep_storage",
        "frugal_rebuild",
        "rapid_rebuild",
        "overdrive",
        "optimized_energy",
        "load_balancing",
    ):
        assert f".gc-ascension-node--{key}" in css

    # Commander parity: same 5-column fork silhouette, ~96px square nodes,
    # horizontal overflow at narrow widths and a dock-style inspector.
    assert "grid-template-columns:repeat(5,1fr)" in css
    assert "max-width:96px" in css
    assert "min-width:540px" in css
    assert "overflow-x:auto" in css
    assert "grid-template-columns:88px minmax(0,1fr) auto" in css
    assert ".gc-ascension-node--frugal_rebuild{grid-column:2;grid-row:3}" in css
    assert ".gc-ascension-node--rapid_rebuild{grid-column:4;grid-row:3}" in css
    assert ".gc-ascension-node--overdrive{grid-column:3;grid-row:4}" in css

    assert 'viewBox="0 0 600 648"' in template
    assert 'M300 166 V208 H180 V222' in template
    assert 'M180 322 V344 H300 V356' in template
    assert "gc-ascension-tree__junction" in template
    edge_block = template[template.index("gc-ascension-tree__edges"):template.index("gc-ascension-tree__nodes")]
    assert " C" not in edge_block

    assert ".gc-ascension-node.is-locked" in css
    assert "opacity:.48" in css
    assert ".gc-ascension-node.is-selected" in css
    assert ".gc-ascension-node.is-selected.is-available" in css
    assert "animation:gc-ascension-node-pulse" in css

    locales_de = (ROOT / "locales" / "de.json").read_text(encoding="utf-8")
    locales_en = (ROOT / "locales" / "en.json").read_text(encoding="utf-8")
    assert "nodebuster_skill_optimized_energy" in locales_de
    assert "nodebuster_skill_optimized_energy" in locales_en
    assert "nodebuster_skill_load_balancing" in locales_de
    assert "nodebuster_skill_load_balancing" in locales_en
    assert "mine_ascension_preview_energy_draw" in template


def test_ascension_header_and_run_hud_are_compact_commander_grade():
    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "nodebuster_ascension.css").read_text(encoding="utf-8")

    assert "gc-ascension-hero" in template
    assert "gc-ascension-summary" in template
    assert "gc-ascension-mine-tabs" in template
    assert "gc-ascension-mine-hero" in template
    assert "gc-ascension-run-hud" in template
    assert "gc-ascension-run-hud__group--progress" in template
    assert "gc-ascension-run-hud__group--effects" in template
    assert "gc-ascension-stat-grid" not in template
    assert "gc-ascension-bonus-grid" not in template

    assert ".gc-ascension-run-hud" in css
    assert "grid-template-columns:minmax(0,1.25fr) 1px minmax(0,1fr)" in css
    assert ".gc-ascension-mine-tab.is-active::after" in css
    assert ".gc-ascension-mine-hero" in css
    assert ".gc-ascension-cta" in css


def test_ascension_breakthroughs_are_integrated_into_the_progression_map():
    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "nodebuster_ascension.css").read_text(encoding="utf-8")

    assert "{% if not skill.breakthrough %}" not in template
    assert "gc-ascension-breakthrough-card" not in template
    assert "gc-ascension-breakthroughs__grid" not in template
    assert "gc-ascension-node--breakthrough" in template
    assert "gc-ascension-tree__breakthrough-band" in template
    assert "gc-ascension-node__key" in template
    assert "skill.breakthrough" in template

    for key, placement in (
        ("legacy_reconstruction", "grid-column:1;grid-row:5"),
        ("core_resonance", "grid-column:3;grid-row:5"),
        ("breakthrough_window", "grid-column:5;grid-row:5"),
        ("singularity_excavation", "grid-column:3;grid-row:6"),
    ):
        assert f".gc-ascension-node--{key}" in css
        assert placement in css

    assert ".gc-ascension-tree__edge--breakthrough" in css
    assert ".gc-ascension-node--breakthrough" in css
    assert ".gc-ascension-node--singularity_excavation" in css
    assert ".gc-ascension-inspector__requirements" in css
    assert "skill.preview.window_before" in template
    assert "skill.preview.window_after" in template
    assert "skill.preview.levels" in template
    assert "skill.preview.production_bonus_pct" in template
    assert "mine_ascension_preview_more_production" in template
    assert "mine_ascension_preview_rebuild_production" in template
    assert "mine_ascension_preview_rebuild_surge_reach" in template
    assert "mine_ascension_preview_rebuild_reach" in template
    assert "mine_ascension_purchase_cost" in template
    assert "mine_ascension_node_gate" in template
    assert "mine_ascension_depth_gate" in template
    assert "mine_ascension_buy_breakthrough" in template
    assert "skill.requires_best_depth" in template

    assert "skill.preview.tail_from" not in template
    assert "skill.preview.tail_to" not in template

    for key in (
        "core_resonance",
        "legacy_reconstruction",
        "breakthrough_window",
        "singularity_excavation",
    ):
        assert f"nodebuster_skill_{key}" in (ROOT / "locales" / "de.json").read_text(encoding="utf-8")
        assert f"nodebuster_skill_{key}" in (ROOT / "locales" / "en.json").read_text(encoding="utf-8")
