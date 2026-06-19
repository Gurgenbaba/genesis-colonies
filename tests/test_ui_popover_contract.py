"""Static UI contracts for popover/dropdown layering (GC-721J-FIX)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_style_exposes_popover_layer_tokens_and_utilities():
    css = _read("static/style.css")
    assert "--gc-z-dropdown:" in css
    assert "--gc-z-popover:" in css
    assert ".gc-overflow-visible" in css
    assert ".gc-popover-layer" in css
    assert ".gc-hud-select-menu.gc-popover-layer" in css


def test_hud_select_portals_menu_to_body_layer():
    js = _read("static/main.js")
    assert "function floatHudSelectMenu" in js
    assert "function positionHudSelectMenu" in js
    assert "function hudSelectParts" in js
    assert 'menu.classList.add("gc-popover-layer")' in js
    assert "document.body.appendChild(menu)" in js
    assert 'e.target.closest(".gc-hud-select-menu")' in js
    assert "gc-has-open-popover" in js
    assert "wrap._gcHudSelect = select._gcHudSelect" in js


def test_admin_diplomacy_panel_allows_overflow():
    html = _read("templates/admin_panel.html")
    assert 'data-admin-panel="diplomacy"' in html
    assert "gc-overflow-visible" in html
    assert "admin-diplomacy-personality-key" in html
