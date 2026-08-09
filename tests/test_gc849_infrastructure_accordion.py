"""
GC-849 — Infrastructure leftmenu accordion must not use nested max-height thrash.

Run: python -m pytest tests/test_gc849_infrastructure_accordion.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc849_infrastructure_accordion_css_uses_grid_not_nested_max_height():
    css = _read("static/style.css")
    block = css.split("GC-849")[1].split(".gc-nav-section.is-expanded > .gc-nav-section-body{", 1)[0]
    assert 'data-nav-section="infrastructure"' in block
    assert "grid-template-rows" in block
    assert "gc-nav-buildings-group" in block
    assert "transition: none" in block
    # Collapsed infra must not inherit ambiguous hit-testing from grid 0fr alone.
    collapsed = block.split(".is-expanded > .gc-nav-section-body")[0]
    assert "opacity: 0" in collapsed
    assert "pointer-events: none" in collapsed


def test_gc849_restore_leftmenu_skips_admin_path():
    src = _read("static/main.js")
    restore = src.split("GC.restoreLeftmenuState = function restoreLeftmenuState")[1].split(
        "function applyMobileBottomNav"
    )[0]
    assert "isAdminRoutePath(path)" in restore
    assert "if (isAdminRoutePath(path)) return;" in restore
    should_sync = src.split("function shouldSyncRoleSidebarFromHudData")[1].split(
        "function applyHudOnlyGameState"
    )[0]
    assert "isAdminRoutePath(window.location.pathname)" in should_sync
    assert 'r.startsWith("admin_")' in should_sync


def test_gc849_infrastructure_section_toggle_does_not_restore_leftmenu():
    src = _read("static/main.js")
    accordion = src.split("function initSidebarSectionAccordion()")[1].split("function initSidebarRightDrawer")[0]
    assert "setNavSectionExpanded(section" in accordion
    assert "restoreLeftmenuState" not in accordion.split("document.addEventListener(\"click\"")[1].split("});")[0]
    set_nav = src.split("function setNavSectionExpanded", 1)[1].split("function setNavGroupExpanded", 1)[0]
    assert "gc-nav-section--animating" in set_nav
    assert 'classList.contains("is-expanded")' in set_nav
    assert "_leftmenuRouteCtxCache" in src


def test_gc849_accordion_bound_once():
    src = _read("static/main.js")
    assert src.count("GC._sidebarSectionAccordionBound = true") == 1
