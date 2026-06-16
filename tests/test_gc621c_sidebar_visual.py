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


def test_gc621c_landscape_sidebar_sub_link_glow():
    css = _read("static/style.css")
    chunk = css.split("gc-has-planet-landscape .gc-nav-sub-link.active")[1][:220]
    assert "linear-gradient(90deg" in chunk
