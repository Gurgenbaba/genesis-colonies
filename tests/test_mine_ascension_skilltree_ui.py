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


def test_ascension_tree_is_visual_and_details_live_in_inspector():
    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "nodebuster_ascension.css").read_text(encoding="utf-8")

    assert "gc-ascension-node__art" in template
    assert "gc-ascension-node__name" in template
    assert "img/classes/icons/production.webp" in template
    assert "gc-ascension-tree__edge" in template
    assert "tree_rank.reconstruction >= 5" in template
    assert "tree_rank.deep_yield >= 5" in template
    assert "gc-ascension-node--{{ skill.key }}" in template
    assert "gc-ascension-node__state" not in template

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

    assert ".gc-ascension-node--utility" in css
    assert "skill.key == 'optimized_energy'" in template
    assert "skill.key == 'load_balancing'" in template
    assert "T('nodebuster_skill_' ~ skill.key)" in template

    locales_de = (ROOT / "locales" / "de.json").read_text(encoding="utf-8")
    locales_en = (ROOT / "locales" / "en.json").read_text(encoding="utf-8")
    assert "nodebuster_skill_optimized_energy" in locales_de
    assert "nodebuster_skill_optimized_energy" in locales_en
    assert "nodebuster_skill_load_balancing" in locales_de
    assert "nodebuster_skill_load_balancing" in locales_en

    assert "mine_ascension_preview_energy_draw" in template
    assert ".gc-ascension-tree__edge.is-fed" in css
    assert "grid-template-columns:repeat(6,minmax(0,1fr))" in css
    assert ".gc-ascension-node--frugal_rebuild{grid-column:2 / span 2;grid-row:3}" in css
    assert ".gc-ascension-node--rapid_rebuild{grid-column:4 / span 2;grid-row:3}" in css
    assert ".gc-ascension-node--overdrive{grid-column:3 / span 2;grid-row:4}" in css
    assert 'viewBox="0 0 600 712"' in template
    assert 'M300 138 V190 H200 V204' in template
    assert 'M200 308 V315 H300 V322' in template
    assert "gc-ascension-tree__junction" in template
    edge_block = template[template.index("gc-ascension-tree__edges"):template.index("gc-ascension-tree__nodes")]
    assert " C" not in edge_block
    assert "--asc-node-size:100px" in css
    assert "grid-template-rows:72px 104px 104px 120px 108px 120px" in css
    assert ".gc-ascension-tree__junction" in css
    assert "opacity:.52" in css
    assert ".gc-ascension-node.is-selected.is-locked" in css
    assert ".gc-ascension-node.is-selected.is-unaffordable" in css
    assert ".gc-ascension-node.is-selected.is-available" in css
    assert "animation:gc-ascension-node-pulse" in css
    assert "content:none" in css


def test_ascension_breakthroughs_are_integrated_into_the_progression_map():
    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "nodebuster_ascension.css").read_text(encoding="utf-8")

    assert "{% if not skill.breakthrough %}" not in template
    assert "gc-ascension-breakthrough-card" not in template
    assert "gc-ascension-breakthroughs__grid" not in template
    assert "gc-ascension-node--breakthrough" in template
    assert "gc-ascension-tree__breakthrough-band" in template
    assert "gc-ascension-node__keystone" in template
    assert "skill.breakthrough" in template

    for key, placement in (
        ("legacy_reconstruction", "grid-column:1 / span 2;grid-row:5"),
        ("core_resonance", "grid-column:3 / span 2;grid-row:5"),
        ("breakthrough_window", "grid-column:5 / span 2;grid-row:5"),
        ("singularity_excavation", "grid-column:3 / span 2;grid-row:6"),
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

    # The player-facing map uses concrete level / production deltas; the
    # internal q-curve is intentionally not rendered as a second mini-panel.
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
