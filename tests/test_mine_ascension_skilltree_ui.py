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


def test_mine_ascension_handler_is_persistent_for_pjax_navigation():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "js/pages/mine_nodebuster.js" in base


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
