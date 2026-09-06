"""GC-PERF-DEFENSE-SSR-006 — mode-specific Defense SSR + shared catalog snapshots."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _route_block() -> str:
    src = _read("app.py")
    return src.split("def defense_view():", 1)[1].split(
        '@app.route("/combat-simulator")', 1
    )[0]


def test_defense_route_resolves_tab_before_heavy_context_and_profiles_it():
    block = _route_block()

    assert 'request.args.get("tab", "structures")' in block
    assert 'defense_tab = requested_tab if requested_tab in {"structures", "troops"}' in block
    assert 'with perf_span("page_context.defense"):' in block
    assert "tab=defense_tab" in block
    assert block.count("conn = db()") == 1


def test_defense_page_builder_has_mutually_exclusive_heavy_modes():
    src = _read("game/defense_page.py")
    block = src.split("def build_defense_page_context(", 1)[1]

    assert 'tab: str = "structures"' in block
    assert 'if mode == "troops":' in block

    troop_branch, structures_branch = block.split('    from .models import get_planet_buildings, get_planet_defense', 1)

    assert "build_troops_state(" in troop_branch
    assert "build_vault_panel_state(" in troop_branch
    assert "build_defense_api_payload(" not in troop_branch
    assert "_locked_defense_catalog(" not in troop_branch

    assert "build_defense_api_payload(" in structures_branch
    assert "_locked_defense_catalog(" in structures_branch
    assert '"troops": None' in structures_branch
    assert '"vault": None' in structures_branch


def test_structures_ssr_shares_one_catalog_snapshot():
    page = _read("game/defense_page.py")
    block = page.split("def build_defense_page_context(", 1)[1]

    assert "stock_snapshot = get_planet_defense(pid, conn=conn)" in block
    assert "buildings=buildings" in block
    assert "research=research" in block
    assert "stock=stock_snapshot" in block

    defense = _read("game/defense.py")
    payload = defense.split("def build_defense_api_payload(", 1)[1].split(
        "def _attach_queue_jobs_to_defense_rows(", 1
    )[0]

    assert payload.count("get_planet_buildings(") == 1
    assert payload.count("get_research_levels(") == 1
    assert payload.count("get_planet_defense(") == 1
    assert "buildings=building_levels" in payload
    assert "research=research_levels" in payload
    assert '"current_defense": defense_stock' in payload


def test_locked_catalog_reuses_shared_requirements_snapshots():
    src = _read("game/defense_page.py")
    block = src.split("def _locked_defense_catalog(", 1)[1].split(
        "def build_defense_page_context(", 1
    )[0]

    assert "buildings: Mapping[str, Any] | None = None" in block
    assert "research: Mapping[str, Any] | None = None" in block
    assert "stock: Mapping[str, Any] | None = None" in block
    assert "buildings=building_levels" in block
    assert "research=research_levels" in block
    assert "requirements_summary_for_client(" in block


def test_defense_template_emits_only_active_heavy_tab_and_navigable_links():
    src = _read("templates/defense.html")

    assert "{% if defense_tab == 'structures' %}" in src
    assert "{% if defense_tab == 'troops' %}" in src
    assert "url_for('defense_view', tab='structures'" in src
    assert "url_for('defense_view', tab='troops'" in src
    assert 'data-defense-tab-panel="structures"' in src
    assert 'data-defense-tab-panel="troops"' in src
    assert 'data-defense-tab-panel="structures"{% if' not in src
    assert 'data-defense-tab-panel="troops"{% if' not in src


def test_defense_tabs_fall_back_to_pjax_when_sibling_panel_is_not_rendered():
    src = _read("static/js/pages/defense.js")
    tabs = src.split("function bindDefenseTabs(page)", 1)[1].split(
        "function bindBarracksTroops(page)", 1
    )[0]

    assert "var targetPanel = page.querySelector" in tabs
    assert "if (!targetPanel) return;" in tabs
    assert tabs.index("if (!targetPanel) return;") < tabs.index("e.preventDefault();")

    init = src.split("function initDefense()", 1)[1].split(
        "GC.pages.defense =", 1
    )[0]
    assert "var structuresPanel" in init
    assert "if (structuresPanel)" in init
    assert "var troopsPanel" in init
    assert "if (troopsPanel && data.troops)" in init


def test_defense_page_context_is_visible_in_perf_intelligence():
    perf = _read("game/perf_intel.py")
    live = _read("game/live_state.py")

    assert '"page_context.defense": "page_context_defense_ms"' in perf
    assert '"page_context_defense_ms": "page_context.defense"' in perf
    assert '"page_context_defense_ms"' in live
