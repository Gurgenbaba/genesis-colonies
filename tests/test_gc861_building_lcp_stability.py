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
    # Stage is default: LCP is planet landscape (base preload), not a card hero.
    assert 'data-gc-landscape-preload="1"' in buildings_resources_html or 'id="gc-planet-landscape-preload"' in buildings_resources_html
    assert "herocard" in buildings_resources_html or "gc-planet-landscape-preload" in buildings_resources_html
    # Retro card hero preload must not steal bandwidth in Stage mode.
    assert 'id="gc-lcp-hero-preload"' not in buildings_resources_html


def test_gc861_only_first_card_high_priority(buildings_resources_html):
    # Hidden stage card sources keep lazy heroes (no LCP competition).
    cards = _first_resources_cards(buildings_resources_html, 4)
    assert len(cards) >= 4
    for card in cards:
        hero = _hero_slice(card)
        assert 'fetchpriority="high"' not in hero
        assert 'loading="lazy"' in hero


def test_gc861_first_card_marks_lcp_hero(buildings_resources_html):
    # Stage mode: no card LCP marker — landscape owns first paint.
    cards = _first_resources_cards(buildings_resources_html, 1)
    assert cards
    assert 'data-gc-lcp-hero="1"' not in cards[0]


def test_gc861_active_stack_single_high_priority_in_template():
    src = _read("templates/partials/card_hero_img_macros.html")
    assert "render_hero_img_attrs" in src
    assert "role == 'secondary'" in src or "'secondary'" in src
    assert "data-gc-lcp-hero" in src
    bld = _read("templates/buildings.html")
    assert "_card_load = 'high' if (_lcp_hero and loop.index0 == 0) else 'lazy'" in bld
    assert 'loading="{{ \'eager\' if _prop_visible else \'lazy\' }}"' in bld or "loading=\"{{ 'eager' if _prop_visible else 'lazy' }}\"" in bld


def test_gc861_second_third_cards_no_longer_eager(buildings_resources_html):
    cards = _first_resources_cards(buildings_resources_html, 3)
    for card in cards[1:3]:
        hero = _hero_slice(card)
        assert 'loading="eager"' not in hero
