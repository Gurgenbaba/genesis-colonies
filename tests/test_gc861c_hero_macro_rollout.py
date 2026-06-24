"""
GC-861C — Hero macro rollout (Research / Shipyard / Defense).

Run: python -m pytest tests/test_gc861c_hero_macro_rollout.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _high_priority_count(fragment: str) -> int:
    return len(re.findall(r'fetchpriority="high"', fragment))


def _first_cards(html: str, grid_marker: str, data_attr: str, n: int = 4, unlocked_only: str = "") -> list[str]:
    grid = html.split(grid_marker, 1)[-1]
    if "data-shipyard-locked-list" in grid:
        grid = grid.split("data-shipyard-locked-list", 1)[0]
    if "data-defense-locked-list" in grid:
        grid = grid.split("data-defense-locked-list", 1)[0]
    pat = rf"<article[^>]*{data_attr}[^>]*"
    if unlocked_only:
        pat += rf"[^>]*{unlocked_only}[^>]*"
    pat += r">.*?</article>"
    articles = re.findall(pat, grid, re.S)
    return articles[:n]


def _hero_slice(card: str) -> str:
    return card.split("gc-bld-card-hero", 1)[1].split("gc-bld-card-meta", 1)[0]


@pytest.fixture()
def research_html(game_client):
    client, _pid = game_client
    resp = client.get("/research")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


@pytest.fixture()
def shipyard_html(game_client):
    client, _pid = game_client
    resp = client.get("/shipyard")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


@pytest.fixture()
def defense_html(game_client):
    client, _pid = game_client
    resp = client.get("/defense")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_gc861c_shared_partial_is_canonical():
    partial = _read("templates/partials/card_hero_img_macros.html")
    assert "render_hero_img_attrs" in partial
    assert "data-gc-lcp-hero" in partial
    assert "role == 'secondary'" in partial
    for tpl in ("buildings.html", "research.html", "shipyard.html", "defense.html"):
        src = _read(f"templates/{tpl}")
        assert "card_hero_img_macros.html" in src
        assert "import render_hero_img_stack" in src


def test_gc861c_research_preload_and_lcp_mark(research_html):
    assert 'rel="preload"' in research_html
    assert ".webp" in research_html
    cards = _first_cards(research_html, 'class="gc-building-grid research-prog-list', "data-research-card", 3)
    assert cards
    assert 'data-gc-lcp-hero="1"' in cards[0]
    assert _high_priority_count(_hero_slice(cards[0])) == 1
    for card in cards[1:]:
        hero = _hero_slice(card)
        assert 'fetchpriority="high"' not in hero
        assert 'loading="lazy"' in hero


def test_gc861c_shipyard_first_card_lcp(shipyard_html):
    cards = _first_cards(
        shipyard_html, "data-shipyard-buildable-list", "data-ship-card", 3, 'data-unlocked="1"'
    )
    if not cards:
        pytest.skip("no buildable ships in fixture (orbital shipyard level / unlocks)")
    assert 'rel="preload"' in shipyard_html
    assert 'data-gc-lcp-hero="1"' in cards[0]
    assert _high_priority_count(_hero_slice(cards[0])) == 1
    if len(cards) > 1:
        assert 'fetchpriority="high"' not in _hero_slice(cards[1])


def test_gc861c_defense_first_card_lcp(defense_html):
    cards = _first_cards(
        defense_html, "data-defense-buildable-list", "data-defense-card", 3, 'data-unlocked="1"'
    )
    if not cards:
        pytest.skip("no buildable defense in fixture (defense factory level / unlocks)")
    assert 'rel="preload"' in defense_html
    assert 'data-gc-lcp-hero="1"' in cards[0]
    assert _high_priority_count(_hero_slice(cards[0])) == 1


def test_gc861c_shipyard_defense_extra_head_template_contract():
    for tpl in ("shipyard.html", "defense.html"):
        src = _read(f"templates/{tpl}")
        assert 'block extra_head' in src
        assert 'rel="preload"' in src
        assert 'as="image"' in src
        assert "_lcp_preload_href" in src


def test_gc861c_templates_no_raster_picture_for_buildable_heroes():
    for tpl in ("research.html", "shipyard.html", "defense.html"):
        src = _read(f"templates/{tpl}")
        buildable_block = src.split("data-shipyard-buildable-list", 1)[0] if "shipyard" in tpl else src
        if "defense" in tpl:
            buildable_block = src.split("data-defense-buildable-list", 1)[0]
        if "research" in tpl:
            buildable_block = src.split("render_research_grid", 1)[0]
        assert "render_raster_picture" not in src.split("{% block content %}", 1)[1]
