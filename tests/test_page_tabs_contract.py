"""Canonical page tabs (.gc-page-tabs) — Identity Shell reactive contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_page_tabs_css_uses_identity_tokens():
    css = _read("static/style.css")
    assert ".gc-page-tabs{" in css
    assert ".gc-page-tab.is-active," in css
    block = css.split(".gc-page-tab.is-active,")[1].split(".gc-page-tab--rich")[0]
    assert "var(--gc-neon-cyan)" in block
    assert "inset 0 -3px 0 var(--gc-neon-cyan)" in block
    assert "color-mix(in srgb, var(--gc-neon-cyan)" in block
    # No hardcoded cyan RGBA in the shared active rule
    assert "rgba(70, 229, 255" not in block
    assert '.gc-body-ingame[data-identity-theme="cyan"] { --gc-id-rgb: 70, 229, 255; }' in css


def test_page_tabs_migrated_surfaces_markup():
    surfaces = [
        ("templates/records.html", "gc-page-tabs--cols-6"),
        ("templates/hall_of_fame.html", "gc-page-tab"),
        ("templates/chronicles.html", "gc-page-tabs--cols-5"),
        ("templates/ranking.html", "gc-page-tabs--auto"),
        ("templates/shop.html", "gc-page-tab shop-tab"),
        ("templates/inventory.html", "gc-page-tab inventory-tab"),
        ("templates/trader_hub.html", "gc-page-tab trader-hub-tab"),
        ("templates/fleet.html", "gc-page-tab fleet-mode-tab"),
        ("templates/techtree.html", "gc-page-tab techtree-filter-btn"),
        ("templates/admin_panel.html", "gc-page-tab admin-tab-btn"),
    ]
    for rel, needle in surfaces:
        html = _read(rel)
        assert "gc-page-tabs" in html, rel
        assert needle in html, f"{rel} missing {needle}"


def test_payment_shop_docs_mention_page_tabs():
    doc = _read("docs/PAYMENT_SHOP.md")
    assert "Page Tabs" in doc or "gc-page-tabs" in doc


def test_admin_online_panel_markup():
    html = _read("templates/admin_panel.html")
    assert 'id="admin-online-output"' in html
    assert "admin_online_players_title" in html
    assert 'data-admin-action="refresh-online"' in html
    js = _read("static/admin.js")
    assert "loadAdminOnlinePlayers" in js
    assert "/api/admin/players?online=1" in js


def test_admin_dual_tab_rails_share_page_tabs():
    """Group + detail admin rails must both use gc-page-tabs (no solid-fill clash)."""
    html = _read("templates/admin_panel.html")
    css = _read("static/admin.css")
    assert 'gc-page-tabs gc-page-tabs--auto gc-page-tabs--sm admin-group-rail' in html
    assert 'gc-page-tabs gc-page-tabs--auto admin-tabs' in html
    assert "gc-page-tab admin-group-btn" in html
    assert "gc-page-tab admin-tab-btn" in html
    assert ".admin-group-btn.is-active" not in css
    assert "background: var(--admin-warn)" not in css
