"""Landing media manifest + showcase contract tests."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.landing_media import resolve_landing_media
from game.models import init_db

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def landing_db(tmp_path, monkeypatch):
    db_file = tmp_path / "landing_media.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _client(landing_db, monkeypatch):
    dbmod.DB_PATH = landing_db
    models.DB_PATH = landing_db
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_resolve_landing_media_empty_dir(tmp_path):
    media = resolve_landing_media(tmp_path / "missing")
    assert media["hero"]["has_video"] is False
    assert media["has_shots"] is False
    assert media["has_moments"] is False
    assert media["trailer"]["has_video"] is False


def test_resolve_landing_media_detects_files(tmp_path):
    base = tmp_path / "landing"
    shots = base / "shots"
    moments = base / "moments"
    shots.mkdir(parents=True)
    moments.mkdir(parents=True)
    (base / "hero.mp4").write_bytes(b"\x00\x00")
    (base / "hero-poster.webp").write_bytes(b"RIFF")
    (shots / "shot-01-overview.webp").write_bytes(b"WEBP")
    (moments / "moment-01-resources.webm").write_bytes(b"\x1aE\xdf\xa3")

    media = resolve_landing_media(base)
    assert media["hero"]["has_video"] is True
    assert media["hero"]["poster"] and media["hero"]["poster"].endswith("hero-poster.webp")
    assert media["has_shots"] is True
    assert media["shots"][0]["stem"] == "shot-01-overview"
    assert media["shot_by_stem"]["shot-01-overview"]["src"].endswith("shot-01-overview.webp")
    assert media["has_moments"] is True
    assert media["moments"][0]["sources"]


def test_landing_renders_systems_without_media(landing_db, monkeypatch, tmp_path):
    empty = tmp_path / "empty_landing"
    empty.mkdir()
    monkeypatch.setattr("game.landing_media.LANDING_DIR", empty)
    client = _client(landing_db, monkeypatch)
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'data-landing-showcase' in html
    assert 'data-landing-systems' in html
    assert 'data-landing-hero' in html
    assert 'data-landing-gallery' not in html
    assert 'data-landing-online-value' in html
    assert 'landing-metric-grid' in html


def test_landing_renders_gallery_when_shots_present(landing_db, monkeypatch, tmp_path):
    base = tmp_path / "landing_with_shots"
    shots = base / "shots"
    shots.mkdir(parents=True)
    (shots / "shot-01-overview.webp").write_bytes(b"WEBP")
    monkeypatch.setattr("game.landing_media.LANDING_DIR", base)
    client = _client(landing_db, monkeypatch)
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'data-landing-gallery' in html
    assert "shot-01-overview.webp" in html
    assert "landing-system-thumb" in html
    assert "landing-system-card--shot" in html


def test_landing_locale_keys_present_all_locales():
    required = [
        "landing_hero_endline",
        "landing_systems_heading",
        "landing_gallery_heading",
        "landing_moments_heading",
        "landing_final_heading",
        "landing_sys_overview_title",
        "landing_shot_overview",
        "landing_shot_titans",
        "landing_shot_auctions",
        "landing_shot_research",
        "landing_shot_commander",
        "landing_moment_resources",
    ]
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for key in required:
            assert key in data, f"missing {key} in {loc}.json"
