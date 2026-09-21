"""GC-PERF-IMG-001 — bundled image requests are persistent and canonical."""

from __future__ import annotations

from pathlib import Path

from app import GC_ASSET_VERSION, app


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_template_static_images_are_automatically_versioned():
    with app.test_request_context("/"):
        rendered = app.jinja_env.from_string(
            "{{ url_for('static', filename='img/res/Energie.webp') }}"
        ).render()
        assert rendered.endswith(f"/static/img/res/Energie.webp?v={GC_ASSET_VERSION}")

        avatar = app.jinja_env.from_string(
            "{{ url_for('static', filename='uploads/avatars/avatar_1.webp') }}"
        ).render()
        assert "?v=" not in avatar


def test_image_worker_is_root_scoped_and_revalidated():
    client = app.test_client()
    response = client.get(f"/gc-image-cache-sw.js?v={GC_ASSET_VERSION}")
    assert response.status_code == 200
    assert response.headers.get("Service-Worker-Allowed") == "/"
    cache = response.headers.get("Cache-Control", "")
    assert "no-cache" in cache
    assert "must-revalidate" in cache


def test_worker_only_intercepts_bundled_images_and_dedupes_query_versions():
    worker = _read("static/js/gc_image_cache_sw.js")
    assert 'url.pathname.startsWith("/static/img/")' in worker
    assert "GC_IMAGE_SUFFIX_RE" in worker
    assert "mp4" not in worker
    assert "mp3" not in worker
    assert 'url.origin + url.pathname' in worker
    assert 'GC_IMAGE_CACHE_PREFIX' in worker
    assert 'caches.delete(name)' in worker
    assert 'request.headers.has("range")' in worker
    assert "/static/uploads/" not in worker


def test_shell_registers_worker_without_blocking_game_boot():
    base = _read("templates/base.html")
    assert "serviceWorker.register" in base
    assert "gc_image_cache_worker" in base
    assert 'scope: "/"' in base
    assert 'updateViaCache: "none"' in base
    assert ".catch(function ()" in base
