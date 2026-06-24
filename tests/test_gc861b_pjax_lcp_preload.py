"""
GC-861B — PJAX LCP preload + static image cache.

Run: python -m pytest tests/test_gc861b_pjax_lcp_preload.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import GC_STATIC_IMAGE_CACHE_MAX_AGE, app

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc861b_main_js_pjax_preload_before_swap():
    nav = _read("static/main.js").split("GC.navigateTo = async function navigateTo", 1)[1]
    nav = nav.split("function initPjax", 1)[0]
    assert "syncLcpHeroPreloadFromPjaxDoc(doc)" in nav
    assert "main.innerHTML = newMain.innerHTML" in nav
    assert nav.index("syncLcpHeroPreloadFromPjaxDoc(doc)") < nav.index("main.innerHTML = newMain.innerHTML")


def test_gc861b_main_js_lcp_preload_contract():
    src = _read("static/main.js")
    block = src.split("// GC-861B — PJAX LCP hero preload", 1)[1].split("GC.navigateTo = async function navigateTo", 1)[0]
    assert 'querySelector(\'[data-gc-lcp-hero="1"]\')' in block
    assert "data-gc-lcp-webp-href" in block
    assert 'link[data-gc-lcp-preload]' in block
    assert 'GC_LCP_HERO_PRELOAD_ID = "gc-lcp-hero-preload"' in block
    assert 'link.rel = "preload"' in block
    assert 'link.as = "image"' in block
    assert "syncLcpHeroPreload(\"\")" in block or 'syncLcpHeroPreload("")' in block


@pytest.mark.parametrize(
    "path,expect_cached",
    [
        ("/static/img/buildings/metal_mine.webp", True),
        ("/static/img/herocards/herocard_08.png", True),
        ("/static/main.js", False),
        ("/static/style.css", False),
    ],
)
def test_gc861b_static_image_cache_headers(path, expect_cached):
    client = app.test_client()
    resp = client.get(path)
    assert resp.status_code == 200
    cache = resp.headers.get("Cache-Control", "")
    if expect_cached:
        assert cache == f"public, max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}"
    else:
        assert f"max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}" not in cache


def test_gc861b_html_routes_not_image_cached():
    client = app.test_client()
    resp = client.get("/login")
    assert resp.status_code == 200
    assert f"max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}" not in (resp.headers.get("Cache-Control") or "")


def test_gc861b_app_helpers():
    from app import _is_static_image_path

    assert _is_static_image_path("/static/img/buildings/metal_mine.webp")
    assert _is_static_image_path("/static/img/res/Energie.webp?v=1")
    assert not _is_static_image_path("/static/main.js")
    assert not _is_static_image_path("/api/game-state")
