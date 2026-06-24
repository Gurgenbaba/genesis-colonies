"""
GC-859 — Building hero image LCP loading contract.

Run: python -m pytest tests/test_gc859_building_hero_lcp.py -v
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
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


@pytest.fixture()
def buildings_resources_html(game_client):
    client, _pid = game_client
    resp = client.get("/buildings?tab=resources")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_gc859_first_hero_uses_webp_with_png_fallback(buildings_resources_html):
    cards = _first_resources_cards(buildings_resources_html, 1)
    assert cards
    card = cards[0]
    assert ".webp" in card
    assert "onerror=" in card
    assert "metal_mine" in card or "buildings/" in card


def test_gc859_first_card_high_priority_eager(buildings_resources_html):
    card = _first_resources_cards(buildings_resources_html, 1)[0]
    hero = card.split("gc-bld-card-hero", 1)[1].split("gc-bld-card-meta", 1)[0]
    assert hero.count('fetchpriority="high"') == 1
    assert 'loading="eager"' in hero
    assert 'loading="lazy"' not in hero.split('data-gc-lcp-hero', 1)[0]


def test_gc859_second_third_cards_lazy_low_priority(buildings_resources_html):
    cards = _first_resources_cards(buildings_resources_html, 3)
    assert len(cards) >= 3
    for card in cards[1:3]:
        hero = card.split("gc-bld-card-hero", 1)[1].split("gc-bld-card-meta", 1)[0]
        assert 'loading="lazy"' in hero
        assert 'fetchpriority="low"' in hero
        assert 'fetchpriority="high"' not in hero


def test_gc859_fourth_card_lazy_low_priority(buildings_resources_html):
    cards = _first_resources_cards(buildings_resources_html, 4)
    assert len(cards) >= 4
    hero = cards[3].split("gc-bld-card-hero", 1)[1].split("</div>", 1)[0]
    assert 'loading="lazy"' in hero
    assert 'fetchpriority="low"' in hero


def test_gc859_hero_images_have_width_height(buildings_resources_html):
    imgs = re.findall(r'class="gc-bld-card-hero-img[^"]*"[^>]*>', buildings_resources_html)
    assert imgs
    for tag in imgs[:6]:
        assert 'width="320"' in tag
        assert 'height="180"' in tag


def test_gc859_active_queue_branch_respects_load_mode_in_template():
    src = _read("templates/buildings.html")
    assert "render_hero_img_attrs" in src
    assert "'secondary'" in src


def test_gc859_audit_script_lists_building_assets():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_building_hero_images.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    rows = json.loads(result.stdout)
    assert len(rows) >= 40
    png_heavy = [r for r in rows if r["format"] == "png" and r["bytes"] > 300_000]
    webp_mine = next(r for r in rows if r["building"] == "metal_mine" and r["format"] == "webp")
    assert len(png_heavy) >= 15
    assert webp_mine["bytes"] < 100_000


def test_gc859_audit_doc_exists():
    text = _read("docs/GC-859_BUILDING_HERO_LCP_AUDIT.md")
    assert "GC-854" in text
    assert "webp" in text.lower()
    assert "fetchpriority" in text
