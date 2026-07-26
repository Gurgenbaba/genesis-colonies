"""GC-621 / GC-621B — Sidebar restoration & navigation logic."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_sidebar_flat_buildings_group_without_nested_box():
    sidebar = _read("templates/partials/sidebar.html")
    assert '{{ _id_p }}nav-buildings-toggle' in sidebar
    assert 'id="gc-nav-buildings-parent"' not in sidebar
    assert "gc-nav-sub--buildings" not in sidebar
    assert 'data-nav-group-key="buildings"' in sidebar
    assert 'data-building-tab="military"' in sidebar
    assert "buildings_nav_tab_resources" in sidebar
    assert "buildings_nav_tab_research" in sidebar
    assert sidebar.count('class="gc-nav-group-body"') >= 1


def test_sidebar_economy_has_trading_subnav():
    sidebar = _read("templates/partials/sidebar_right.html")
    assert 'data-nav-module="trading"' in sidebar
    assert 'data-trading-nav="inventory"' in sidebar
    assert 'data-trading-nav="auction_house"' in sidebar
    assert 'data-nav-section="economy"' in sidebar
    assert 'id="gc-nav-trading-parent"' not in sidebar


def test_sidebar_section_bodies_use_css_collapse_not_hidden():
    sidebar = _read("templates/partials/sidebar.html")
    assert "gc-nav-section-body gc-nav-sub" not in sidebar
    assert '{{ _id_p }}nav-section-infrastructure' in sidebar
    assert '{{ _id_p }}nav-section-infrastructure" hidden' not in sidebar


def test_sidebar_verwaltung_has_no_support_or_overflow():
    sidebar = _read("templates/partials/sidebar_right.html")
    bottom = _read("templates/partials/bottom_utility_bar.html")
    assert "secondary_overflow_modules" not in sidebar
    assert 'data-nav-overflow="1"' not in sidebar
    assert 'data-nav-module="support"' not in sidebar
    assert 'data-special-open-window="support"' not in sidebar
    community = sidebar.split('data-nav-section="community"', 1)[1]
    for module in ("alliance", "hall_of_fame"):
        assert f'data-nav-module="{module}"' in community
    # Ranking / Records / Chronicles are bottom-utility links (declutter right rail).
    assert 'data-nav-module="ranking"' not in community
    assert 'data-nav-module="records"' not in community
    assert "url_for('ranking_view')" in bottom
    assert "url_for('records_view')" in bottom
    assert "url_for('chronicles_view')" in bottom
    assert 'data-nav-section="system"' not in sidebar


def test_sidebar_options_in_bottom_utility_bar():
    utility = _read("templates/partials/bottom_utility_bar.html")
    assert 'url_for(\'options_view\')' in utility
    assert 'data-nav-module="options"' not in utility


def test_sidebar_messages_standalone_shortcut():
    sidebar = _read("templates/partials/sidebar_right.html")
    assert 'data-nav-section="messages"' in sidebar
    assert 'class="gc-nav-link gc-nav-module--' in sidebar
    assert "gc-nav-icon--mail" not in sidebar
    assert "gc-nav-messages-toggle" not in sidebar
    assert "gc-nav-section-messages-body" not in sidebar
    assert "gc-nav-section--messages" not in sidebar
    economy = sidebar.split('data-nav-section="economy"', 1)[1].split('data-nav-section="community"', 1)[0]
    assert 'data-nav-module="messages"' not in economy
    messages_block = sidebar.split('data-nav-section="messages"', 1)[1].split('data-nav-section="economy"', 1)[0]
    assert 'data-nav-module="messages"' in messages_block
    assert "data-messages-unread-badge" in messages_block


def test_sidebar_buildings_tabs_distinct_from_research_module():
    sidebar = _read("templates/partials/sidebar.html")
    sidebar_right = _read("templates/partials/sidebar_right.html")
    infra = sidebar.split('data-nav-section="infrastructure"', 1)[1].split('data-nav-section="military"', 1)[0]
    assert infra.count('data-nav-module="research"') == 1
    assert 'data-building-tab="research"' in infra
    assert 'data-nav-module="techtree"' not in infra
    eco = sidebar_right.split('data-nav-section="economy"', 1)[1].split('data-nav-section="community"', 1)[0]
    assert 'data-nav-module="techtree"' in eco


def test_german_buildings_nav_tab_labels():
    de = _read("locales/de.json")
    assert '"buildings_nav_tab_resources": "Ressourcen"' in de
    assert '"buildings_nav_tab_research": "Forschung"' in de
    assert '"buildings_nav_tab_military": "Militär"' in de
    assert '"buildings_nav_tab_infrastructure": "Infrastruktur"' in de


def test_style_sidebar_command_interface_tokens():
    css = _read("static/style.css")
    block = css.split("/* Sidebar — GC-621C", 1)[1].split("/* Main */", 1)[0]
    assert "GC-621C accordion + Genesis cyan glow" in css
    assert "border-left: 3px solid transparent;" in block
    assert "text-transform: uppercase;" in block
    assert "0.8125rem" in block
    assert "rgba(0, 234, 255, 0.16)" in block
    assert ".gc-nav-section.is-expanded > .gc-nav-section-body" in block
    assert ":has(.gc-nav-sub-link.active)" not in block
    assert "border-left-color: transparent;" not in block.split(".gc-nav-sub-link:hover")[1].split(".gc-nav-sub-link.active")[0]


def test_main_js_persists_sidebar_state_in_local_storage():
    src = _read("static/main.js")
    assert 'const NAV_SECTION_STORAGE_KEY = "gc_sidebar_state"' in src
    assert 'const NAV_SECTION_STORAGE_KEY_RIGHT = "gc_sidebar_right_state"' in src
    assert "readNavSectionState(" in src
    assert "writeNavSectionState(" in src
    assert "resolveNavGroupExpanded" in src
    assert "setNavGroupExpanded" in src
    assert "GC.restoreLeftmenuState" in src
    assert "restoreSidebarMenuState" in src
    assert "resolveLeftmenuRouteContext" in src
    assert "applyLeftmenuPathRouteHints" in src
    assert "markLeftmenuActiveLinks" in src
    assert "syncBuildingsSubnavFromState" in src
    assert "_clearSidebarNavActive" in src
    assert "syncBuildingSidebarTab(null)" in src
    assert "buildingSubnavRoots" in src
    assert 'id$="nav-buildings-sub"' in src
    assert "resolveBuildingsActiveTab" in src
    assert "gc-nav-group-toggle" in src
    accordion = src.split("function syncNavSectionAccordionState", 1)[1].split("function applyDesktopSidebarNav", 1)[0]
    assert "hasActive" not in accordion
    resolve_group = src.split("function resolveNavGroupExpanded", 1)[1].split("function setNavSectionExpanded", 1)[0]
    assert 'key === "buildings"' in resolve_group
    apply_desktop = src.split("function applyDesktopSidebarNav", 1)[1].split("function markLeftmenuActiveLinks", 1)[0]
    assert "syncNavSectionAccordionState" not in apply_desktop
    assert "el.hidden = true;" not in apply_desktop
    sync_role = src.split("GC.syncRoleBasedSidebar = function syncRoleBasedSidebar", 1)[1].split("function initRoleBasedSidebar", 1)[0]
    assert "GC.restoreLeftmenuState" in sync_role
    assert "markLeftmenuActiveLinks" in sync_role
    assert "_lastSidebarNavSig" in sync_role
    assert "syncNavSectionAccordionState(sidebar)" not in sync_role
    init_page = src.split("GC.initPage = function initPage", 1)[1].split("GC.cleanupPage", 1)[0]
    assert "GC.restoreLeftmenuState(window.location.href)" in init_page
    assert "syncLayoutShellMode" not in init_page
    assert "initBottomUtilityBar" in src
    init_shell = src.split("function initShellOnce", 1)[1].split("function initPage", 1)[0]
    shell_chrome = src.split("function initShellChrome", 1)[1].split("function initShellOnce", 1)[0]
    assert "initShellChrome();" in init_shell
    assert "initSpecialPanel();" in shell_chrome
    early_return = init_shell.find("if (!shouldRunGameLoop())")
    assert early_return != -1
    assert init_shell.index("initShellChrome();") < early_return
    assert shell_chrome.index("initSpecialPanel();") < shell_chrome.index("initRoleBasedSidebar();")
    open_special = src.split("function openSpecialWindow", 1)[1].split("GC.openSpecialWindow = openSpecialWindow", 1)[0]
    assert "btn.click()" not in open_special
    route_ctx = src.split("function resolveLeftmenuRouteContext", 1)[1].split("function resolveNavSectionExpanded", 1)[0]
    assert 'path.endsWith("/buildings")' in route_ctx
    assert 'search.get("tab")' in route_ctx
    assert 'groups.add("buildings")' in route_ctx
    assert "registerCleanup(hideBuildingsSubnav)" not in src.split("function initBuildings", 1)[1].split("const BUILDING_TECH", 1)[0]
