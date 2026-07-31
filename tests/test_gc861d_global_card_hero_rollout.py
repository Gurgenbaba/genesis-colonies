"""
GC-861D — Global card hero rollout (Overview, Inventory, Fleet).

Run: python -m pytest tests/test_gc861d_global_card_hero_rollout.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _high_priority_count(html: str) -> int:
    return len(re.findall(r'fetchpriority="high"', html))


@pytest.fixture()
def overview_html(game_client):
    client, _pid = game_client
    resp = client.get("/overview")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


@pytest.fixture()
def inventory_html(game_client):
    client, _pid = game_client
    resp = client.get("/inventory")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


@pytest.fixture()
def fleet_html(game_client):
    client, pid = game_client
    from game.db import commit, db
    from game.fleet import add_planet_ships
    from game.models import get_homeworld

    planet = get_homeworld(player_id=pid)
    conn = db()
    try:
        add_planet_ships(int(planet["id"]), pid, {"mule_courier": 1}, conn=conn)
        commit(conn)
    finally:
        conn.close()
    resp = client.get("/fleet")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_gc861d_audit_doc_exists():
    doc = _read("docs/GC-861D_GLOBAL_CARD_HERO_ROLLOUT.md")
    assert "GC-861D" in doc
    assert "**Overview**" in doc
    assert "**Inventory**" in doc


def test_gc861d_macro_exports_card_hero_img():
    macro = _read("templates/partials/card_hero_img_macros.html")
    assert "render_card_hero_img" in macro
    assert "data-gc-lcp-webp-href" in macro


def test_gc861d_main_js_webp_lcp_resolution():
    block = _read("static/main.js").split("function resolveLcpHeroImageUrl(root)")[1].split("function syncLcpHeroPreload", 1)[0]
    assert "data-gc-lcp-webp-href" in block
    assert 'source[type="image/webp"]' in block


def test_gc861d_overview_lcp_hero(overview_html):
    assert 'data-gc-lcp-hero="1"' in overview_html
    assert 'data-gc-lcp-webp-href' in overview_html
    assert 'rel="preload"' in overview_html
    # Single md candidate href — not full imagesrcset (avoids unused-preload spam).
    assert "herocard_" in overview_html and "-md.webp" in overview_html
    assert 'imagesrcset=' not in overview_html.split("gc-lcp-hero-preload", 1)[1].split(">", 1)[0]
    assert ".webp" in overview_html
    hero = overview_html.split("overview-hero-bg", 1)[1].split("overview-hero-atmo", 1)[0]
    assert _high_priority_count(hero) == 1
    assert "-md.webp" in overview_html.split('data-gc-lcp-webp-href="', 1)[1].split('"', 1)[0]

def test_gc861d_inventory_first_container_lcp(inventory_html):
    assert 'rel="preload"' in inventory_html
    grid = inventory_html.split("data-inventory-container-grid", 1)[-1]
    first_card = grid.split("</article>", 1)[0]
    assert 'data-gc-lcp-hero="1"' in first_card
    assert ".webp" in first_card
    assert _high_priority_count(first_card) == 1


def test_gc861d_fleet_template_lcp_markup():
    fleet = _read("templates/fleet.html")
    ships_panel = fleet.split("data-fleet-ships-grid", 1)[1].split("</section>", 1)[0]
    assert "data-gc-lcp-hero" in ships_panel
    assert "data-gc-lcp-webp-href" in ships_panel
    assert "render_hero_img_attrs" in ships_panel


def test_gc861d_fleet_first_ship_lcp(fleet_html):
    assert 'rel="preload"' in fleet_html
    assert "img/ships/" in fleet_html and ".webp" in fleet_html
    grid = fleet_html.split("data-fleet-ships-grid", 1)[-1]
    first_article = re.search(r"<article[^>]*fleet-ship-card[^>]*>.*?</article>", grid, re.S)
    assert first_article
    card = first_article.group(0)
    assert 'data-gc-lcp-hero="1"' in card
    assert _high_priority_count(card) == 1


def test_gc861d_inventory_fleet_templates_use_macro():
    inv = _read("templates/inventory.html")
    fleet = _read("templates/fleet.html")
    assert "card_hero_img_macros.html" in inv
    assert "render_card_hero_img" in inv
    assert "card_hero_img_macros.html" in fleet
    assert "render_hero_img_attrs" in fleet


def test_gc861d_no_png_primary_inventory_template():
    inv = _read("templates/inventory.html")
    assert "render_card_hero_img" in inv
    content = inv.split("{% block content %}", 1)[1]
    assert 'src="{{ _img }}"' not in content
