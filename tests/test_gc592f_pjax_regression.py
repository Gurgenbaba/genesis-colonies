"""GC-592F: PJAX reload regression guards after Command Center / sidebar changes."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pjax_nav_link_covers_sidebar_and_command_center():
    src = _read("static/main.js")
    assert "#gc-sidebar-nav a[href]" in src
    assert "#gc-sidebar-nav-right a[href]" in src
    assert "a.gc-command-center-action-btn" in src
    assert "a.gc-command-center-fleet-link" in src
    assert "a.galaxy-view-tab" in src
    assert "a[data-gc-nav]" in src


def test_command_center_js_links_use_gc_nav_link():
    src = _read("static/main.js")
    cc_section = src.split("function renderColonyCommandCenter")[1].split("function renderStrategicCommandCenter")[0]
    feed_section = src.split("function renderActivityFeed")[1].split("function renderColonyActionCard")[0]
    assert 'link.className = "gc-nav-link gc-command-center-fleet-link"' in cc_section
    assert 'link.className = "gc-nav-link gc-command-center-action-card gc-command-center-action-btn' in cc_section or 'renderColonyActionCard' in cc_section
    assert 'link.className = "gc-nav-link gc-command-center-activity-link gc-command-center-news-link"' in feed_section
    assert "link.dataset.gcNav = \"1\"" in feed_section


def test_command_center_primary_and_colony_open_use_navigate_to():
    src = _read("static/main.js")
    open_colony = src.split("async function onOpenColonyClick")[1].split("openColonyBtn?.addEventListener")[0]
    assert "applyActionState(res, \"planet_switch\")" in open_colony
    assert 'GC.navigateTo("/overview"' in open_colony
    assert "location.reload" not in open_colony
    assert "location.href" not in open_colony

    primary = src.split("function onPrimaryActionClick")[1].split("async function onOpenColonyClick")[0]
    assert "GC.navigateTo(`/fleet?" in primary
    assert "location.reload" not in primary


def test_galaxy_view_tabs_marked_for_pjax():
    tpl = _read("templates/galaxy.html")
    assert 'class="gc-nav-link galaxy-view-tab galaxy-view-tab--classic' in tpl
    assert "galaxy-view-tab--world is-active" in tpl
    assert "galaxy_view_classic" not in tpl


def test_fleet_internal_links_marked_for_pjax():
    tpl = _read("templates/fleet.html")
    assert 'href="{{ url_for(\'shipyard_view\') }}" class="fleet-shipyard-head-link gc-nav-link"' in tpl


def test_sidebar_module_links_are_pjax_eligible_markup():
    tpl = _read("templates/partials/sidebar.html")
    href_links = re.findall(r"<a\s+[^>]*href=\"[^\"]+\"[^>]*>", tpl)
    assert href_links, "sidebar should contain module links"
    for tag in href_links:
        assert "gc-nav-sub-link" in tag or "gc-nav-link" in tag, f"missing PJAX nav class: {tag}"


def test_gc804_leftmenu_state_restored_after_pjax_init():
    """GC-804: sidebar accordion persists via localStorage + restoreLeftmenuState after PJAX."""
    src = _read("static/main.js")
    navigate = src.split("GC.navigateTo = async function navigateTo", 1)[1].split("function initPjax", 1)[0]
    assert "_syncNavActive(url)" not in navigate
    assert "GC.restoreLeftmenuState(url)" not in navigate
    assert "await GC.initPage(" in navigate
    init_pjax = src.split("function initPjax", 1)[1].split("// =========================", 2)[0]
    assert "tryHandleSubnavParentClick(link, e)" not in init_pjax
    assert "pathFromMenuUrl" in src
    assert "linkPathMatchesRoute" in src
    assert "resolveNavSectionExpanded" in src
    assert 'path.endsWith("/fleet")' in src.split("function applyLeftmenuPathRouteHints", 1)[1].split("function resolveLeftmenuRouteContext", 1)[0]


def test_no_new_location_href_assignments_in_main_js():
    violations: list[str] = []
    for i, line in enumerate(_read("static/main.js").splitlines(), start=1):
        if re.search(r"\b(?:window\.)?location\.href\s*=", line):
            if "history.replaceState" in line:
                continue
            violations.append(f"static/main.js:{i}: {line.strip()}")
    assert not violations, "location.href = in main.js:\n" + "\n".join(violations)


def test_reload_fallback_is_allowlisted_only():
    src = _read("static/main.js")
    reload_lines = [
        (i, line.strip())
        for i, line in enumerate(src.splitlines(), start=1)
        if re.search(r"\b(?:window\.)?location\.reload\s*\(", line)
    ]
    allowed = {
        (1379, "window.location.reload();"),  # reloadCurrentPage fullDocument
        (1386, "window.location.reload();"),  # reloadCurrentPage navigateTo fallback
        (16668, "window.location.reload();"),  # locale switch fallback
    }
    assert reload_lines, "expected allowlisted location.reload() sites"
    assert set(reload_lines) == allowed, (
        "unexpected location.reload() in main.js:\n"
        + "\n".join(f"  {ln}:{txt}" for ln, txt in reload_lines if (ln, txt) not in allowed)
    )
