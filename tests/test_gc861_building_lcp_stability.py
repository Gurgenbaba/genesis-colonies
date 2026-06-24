"""
GC-861 — Buildings LCP discovery / priority stability.

Run: python -m pytest tests/test_gc861_building_lcp_stability.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _first_resources_cards(html: str, n: int = 4) -> list[str]:
    grid = html.split('class="gc-building-grid buildings-prog-list"', 1)[-1]
    articles = re.findall(r"<article[^>]*data-building-card[^>]*>.*?</article>", grid, re.S)
    return articles[:n]


def _hero_slice(card: str) -> str:
    return card.split("gc-bld-card-hero", 1)[1].split("gc-bld-card-meta", 1)[0]


def _high_priority_count(fragment: str) -> int:
    return len(re.findall(r'fetchpriority="high"', fragment))


@pytest.fixture()
def buildings_resources_html(game_client):
    client, _pid = game_client
    resp = client.get("/buildings?tab=resources")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_gc861_preloads_first_tab_hero_webp(buildings_resources_html):
    assert 'rel="preload"' in buildings_resources_html
    assert 'as="image"' in buildings_resources_html
    assert "metal_mine.webp" in buildings_resources_html or "buildings/metal_mine.webp" in buildings_resources_html


def test_gc861_only_first_card_high_priority(buildings_resources_html):
    cards = _first_resources_cards(buildings_resources_html, 4)
    assert len(cards) >= 4
    assert _high_priority_count(_hero_slice(cards[0])) == 1
    for card in cards[1:]:
        hero = _hero_slice(card)
        assert 'fetchpriority="high"' not in hero
        assert 'loading="lazy"' in hero
        assert 'fetchpriority="low"' in hero


def test_gc861_first_card_marks_lcp_hero(buildings_resources_html):
    card = _first_resources_cards(buildings_resources_html, 1)[0]
    assert 'data-gc-lcp-hero="1"' in card


def test_gc861_active_stack_single_high_priority_in_template():
    src = _read("templates/partials/card_hero_img_macros.html")
    assert "render_hero_img_attrs" in src
    assert "role == 'secondary'" in src or "'secondary'" in src
    assert "data-gc-lcp-hero" in src
    bld = _read("templates/buildings.html")
    assert "_card_load = 'high' if loop.index0 == 0 else 'lazy'" in bld


def test_gc861_second_third_cards_no_longer_eager(buildings_resources_html):
    cards = _first_resources_cards(buildings_resources_html, 3)
    for card in cards[1:3]:
        hero = _hero_slice(card)
        assert 'loading="eager"' not in hero
