"""GC-621C — Sidebar accordion visual alignment (CSS contract)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc621c_sidebar_genesis_glow_tokens():
    css = _read("static/style.css")
    block = css.split("/* Sidebar — GC-621C", 1)[1].split("/* Main */", 1)[0]

    assert "linear-gradient(180deg, rgba(3, 12, 22" in block
    assert "border: 1px solid rgba(70, 229, 255, 0.28)" in block
    assert ".gc-nav-section.is-expanded > .gc-nav-section-body" in block
    assert ":has(.gc-nav-sub-link.active)" not in block
    assert ".gc-nav-submenu-group.is-expanded > .gc-nav-group-body" in block
    assert "border-left: 2px solid rgba(70, 229, 255, 0.14)" in block


def test_gc806_dual_sidebar_layout_contract():
    """GC-806C: dual sidebar shell + bottom utility bar."""
    base = _read("templates/base.html")
    css = _read("static/style.css")
    src = _read("static/main.js")
    utility = _read("templates/partials/bottom_utility_bar.html")

    assert "gc-app-shell" in base
    assert "gc-layout--dual" in base
    assert "gc-layout--wide" not in base
    assert 'include "partials/sidebar_right.html"' in base
    assert 'include "partials/bottom_utility_bar.html"' in base
    assert 'include "partials/header_utility_bar.html"' not in base
    assert 'id="gc-sidebar-nav-right"' in _read("templates/partials/sidebar_right.html")
    assert "gc-layout--dual" in css
    assert "gc-layout--wide" not in css
    assert "--gc-shell-max-width" in css
    assert "var(--gc-sidebar-rail-w" in css
    assert "minmax(210px, 1fr)" in css
    assert "gc-sidebar--right" in css
    assert "gc-bottom-util-link" in css
    assert "gc-bottom-util-version" in css
    assert "gc-bottom-util-version" in utility
    assert "gc-sidebar-rail-head" not in _read("templates/partials/sidebar_right.html")
    assert "NAV_SECTION_STORAGE_KEY_RIGHT" in src
    assert "syncLayoutShellMode" not in src
    assert "WIDE_LAYOUT_PAGES" not in src
    assert "initBottomUtilityBar" in src
    assert "initSidebarRightDrawer" in src


def test_gc621c_landscape_sidebar_sub_link_glow():
    css = _read("static/style.css")
    chunk = css.split("gc-has-planet-landscape .gc-nav-sub-link.active")[1][:220]
    assert "linear-gradient(90deg" in chunk


def test_gc805_desktop_sidebar_sticky_scroll_contract():
    """GC-805: desktop sidebar stays sticky with internal scroll on long pages."""
    css = _read("static/style.css")
    src = _read("static/main.js")

    assert "--gc-sidebar-max-height" in css
    assert "--gc-sidebar-bottom-gap" in css

    desktop = css.split("@media (min-width: 981px)", 1)[1].split("/* =========================", 2)[0]
    assert ".gc-sidebar-desktop{" in desktop
    assert "position: sticky" in desktop.split(".gc-sidebar-desktop{", 1)[1].split("}", 1)[0]
    assert "max-height: var(--gc-sidebar-max-height" in desktop
    assert "overflow-y: auto" in desktop.split(".gc-sidebar-desktop{", 1)[1].split("}", 1)[0]
    assert "overscroll-behavior: contain" in desktop

    tablet = css.split("@media (max-width: 980px)", 1)[1].split("@media", 1)[0]
    assert "max-height: none" in tablet.split(".gc-sidebar-desktop", 1)[1][:200]
    assert "overflow: visible" in tablet.split(".gc-sidebar-desktop", 1)[1][:200]

    assert ".gc-sidebar-desktop{ display: none !important; }" in css

    sticky = src.split("function syncSidebarSticky()", 1)[1].split("function initSidebarSticky", 1)[0]
    assert "--gc-sidebar-max-height" in sticky
    assert "100dvh" in sticky
