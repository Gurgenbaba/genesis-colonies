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


def test_gc861b_main_js_pjax_preload_after_swap():
    # commit faf8ea5 ("... fixing LCP preload") intentionally moved the LCP
    # hero preload from syncLcpHeroPreloadFromPjaxDoc(doc) (run on the parsed
    # PJAX response *before* the DOM swap) to syncLcpHeroPreload(resolveLcp
    # HeroImageUrl(main)) run on the *live* #main-content element right after
    # `main.innerHTML = payload.mainHtml` — preloading against the actually
    # rendered DOM instead of the detached parsed doc (GC-STABILIZE-002).
    # syncLcpHeroPreloadFromPjaxDoc became dead code after that fix (no
    # remaining call sites) and was removed from static/main.js in the same
    # ticket per the no-dead-code rule.
    nav = _read("static/main.js").split("async function applyPjaxPayload(url, payload, doc, opts = {})", 1)[1]
    nav = nav.split("GC.navigateTo = async function navigateTo", 1)[0]
    assert "main.innerHTML = payload.mainHtml" in nav
    assert "syncLcpHeroPreload(resolveLcpHeroImageUrl(main))" in nav
    assert nav.index("main.innerHTML = payload.mainHtml") < nav.index(
        "syncLcpHeroPreload(resolveLcpHeroImageUrl(main))"
    )


def test_gc861b_main_js_lcp_preload_contract():
    src = _read("static/main.js")
    block = src.split("// GC-861B — PJAX LCP hero preload", 1)[1].split("GC.navigateTo = async function navigateTo", 1)[0]
    assert 'querySelector(\'[data-gc-lcp-hero="1"]\')' in block
    assert "data-gc-lcp-webp-href" in block
    assert 'link[data-gc-lcp-preload]' in block
    assert 'GC_LCP_HERO_PRELOAD_ID = "gc-lcp-hero-preload"' in block
    assert 'link.rel = "preload"' in block
    assert 'link.as = "image"' in block
    # "no hero on this page" reset used to be an explicit syncLcpHeroPreload("")
    # call inside the now-removed syncLcpHeroPreloadFromPjaxDoc fallback; that
    # behavior lives directly in resolveLcpHeroImageUrl (returns "" when no
    # [data-gc-lcp-hero] is found) feeding syncLcpHeroPreload's own falsy-href
    # removeLcpHeroPreloadLinks() branch (GC-STABILIZE-002).
    assert 'if (!root) return "";' in block
    assert "removeLcpHeroPreloadLinks()" in block


@pytest.mark.parametrize(
    "path,expect_cached,expect_immutable",
    [
        ("/static/img/buildings/metal_mine.webp", True, False),
        ("/static/img/herocards/herocard_08.png", True, False),
        ("/static/main.js", False, False),
        ("/static/style.css", False, False),
    ],
)
def test_gc861b_static_image_cache_headers(path, expect_cached, expect_immutable):
    client = app.test_client()
    resp = client.get(path)
    assert resp.status_code == 200
    cache = resp.headers.get("Cache-Control", "")
    if expect_cached:
        assert cache == f"public, max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}"
        assert "immutable" not in cache
    else:
        assert f"max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}" not in cache
        assert "immutable" not in cache


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
