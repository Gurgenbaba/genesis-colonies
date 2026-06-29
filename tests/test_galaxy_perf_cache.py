"""
Galaxy ring perf — PJAX memory cache, image warm pool, versioned static URLs.

Run: python -m pytest tests/test_galaxy_perf_cache.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import GC_ASSET_VERSION, GC_STATIC_IMAGE_CACHE_MAX_AGE, app

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_galaxy_perf_main_js_contract():
    src = _read("static/main.js")
    assert "GALAXY_PJAX_CACHE_MAX" in src
    assert "getGalaxyPjaxCached" in src
    assert "warmGalaxyRingImages" in src
    assert "fetchGalaxyPjaxIntoCache" in src
    assert "cacheGalaxyPjaxFromDoc" in src
    assert "isGalaxySystemPjaxUrl" in src
    nav = src.split("GC.navigateTo = async function navigateTo", 1)[1]
    nav = nav.split("function initPjax", 1)[0]
    assert "getGalaxyPjaxCached(target)" in nav
    assert 'cache: isGalaxySystemPjaxUrl(target) ? "default" : "no-store"' in nav


def test_galaxy_ring_template_versions_static_images(tmp_path, monkeypatch):
    import importlib
    import uuid

    import app as app_module
    import game.db as dbmod
    import game.models as models
    import migrate
    from game.models import create_user

    db_path = tmp_path / "galaxy_perf.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    migrate.ensure_db_exists()
    migrate.main()
    importlib.reload(app_module)
    uname = f"perf_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])
    resp = client.get("/galaxy?view=system&galaxy=1&system=1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert f"v={GC_ASSET_VERSION}" in body
    assert "img/herocards/" in body or "img/landscapes/" in body
    assert "--gc-galaxy-map-tile" in body
    assert "--gc-galaxy-debris-img" in body


@pytest.mark.parametrize(
    "path,expect_immutable",
    [
        (f"/static/img/herocards/herocard_08.png?v={GC_ASSET_VERSION}", True),
        ("/static/img/herocards/herocard_08.png", False),
    ],
)
def test_versioned_static_image_cache_headers(path, expect_immutable):
    client = app.test_client()
    resp = client.get(path)
    assert resp.status_code == 200
    cache = resp.headers.get("Cache-Control", "")
    if expect_immutable:
        assert "immutable" in cache
        assert "max-age=31536000" in cache
    else:
        assert cache == f"public, max-age={GC_STATIC_IMAGE_CACHE_MAX_AGE}"
