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
    assert "nodebuster_best_depth" not in block
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
    assert "img/classes/icons/production.webp" in template
    assert "gc-ascension-tree__edge" in template
    assert "skill.rank >= 5" in template
    assert "gc-ascension-node--{{ skill.key }}" in template
    assert "gc-ascension-node__name" not in template
    assert "gc-ascension-node__state" not in template

    assert ".gc-ascension-node--reconstruction" in css
    assert ".gc-ascension-node--deep_yield" in css
    assert ".gc-ascension-node--deep_storage" in css
    assert ".gc-ascension-node--frugal_rebuild" in css
    assert ".gc-ascension-node--rapid_rebuild" in css
    assert ".gc-ascension-node--overdrive" in css
    assert ".gc-ascension-tree__edge.is-fed" in css
    assert "grid-template-columns:repeat(6,minmax(0,1fr))" in css
    assert ".gc-ascension-node--frugal_rebuild{grid-column:2 / span 2;grid-row:2}" in css
    assert ".gc-ascension-node--rapid_rebuild{grid-column:4 / span 2;grid-row:2}" in css
    assert ".gc-ascension-node--overdrive{" in css
    assert 'viewBox="0 0 600 388"' in template
    assert 'M300 108 V119 H200 V130' in template
    assert 'M400 238 V249 H300 V260' in template
    assert 'gc-ascension-tree__junction' in template
    assert ' C' not in template[template.index('gc-ascension-tree__edges'):template.index('gc-ascension-tree__nodes')]
    assert "--asc-node-size:108px" in css
    assert "grid-template-rows:108px 108px 128px" in css
    assert ".gc-ascension-tree__junction" in css
    assert "opacity:.52" in css
    assert ".gc-ascension-node.is-selected.is-locked" in css
    assert ".gc-ascension-node.is-selected.is-unaffordable" in css
    assert ".gc-ascension-node.is-selected.is-available" in css
    assert "animation:gc-ascension-node-pulse" in css
    assert "content:none" in css


def test_ascension_breakthroughs_are_separate_from_core_tree():
    template = (ROOT / "templates" / "skilltree.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "nodebuster_ascension.css").read_text(encoding="utf-8")

    assert "{% if not skill.breakthrough %}" in template
    assert "gc-ascension-breakthroughs" in template
    assert "gc-ascension-breakthrough-card" in template
    assert "mine.nodebuster_tail_power" in template
    assert "mine.nodebuster_rebuild_window_extra_levels" in template
    assert "skill.requires_best_depth" in template

    for key in (
        "core_resonance",
        "legacy_reconstruction",
        "breakthrough_window",
        "singularity_excavation",
    ):
        assert f"nodebuster_skill_{key}" in (ROOT / "locales" / "de.json").read_text(encoding="utf-8")
        assert f"nodebuster_skill_{key}" in (ROOT / "locales" / "en.json").read_text(encoding="utf-8")

    assert ".gc-ascension-breakthroughs__grid" in css
    assert "grid-template-columns:repeat(4,minmax(0,1fr))" in css
    assert ".gc-ascension-breakthrough-card.is-maxed" in css
