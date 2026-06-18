"""GC-650 / GC-651 — Genesis Timeline & What's New."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.universe_news import (
    build_timeline,
    create_news,
    import_changelog_markdown,
    list_news,
    news_page_payload,
    whats_new_payload,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"
CHANGELOG = ROOT / "CHANGELOG.md"


@pytest.fixture()
def timeline_db(tmp_path, monkeypatch):
    db_file = tmp_path / "timeline.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
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


def _create_player() -> tuple[int, str]:
    uname = f"tl_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"]), uname


def _app_client(monkeypatch):
    import app as app_mod

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def test_timeline_groups_by_version(timeline_db):
    create_news(
        title="v0.8 — Alpha Polish",
        body="Major",
        version_tag="v0.8",
        category="ALPHA",
        badge="ALPHA",
        is_major_release=True,
    )
    create_news(title="Global Fleet HUD", body="Global Fleet HUD", version_tag="v0.8", category="FEATURE")
    create_news(title="Vote Center", body="Vote Center", version_tag="v0.6", category="FEATURE")

    timeline = build_timeline(list_news(limit=50))
    assert timeline
    versions = [v["version_tag"] for year in timeline for v in year["versions"]]
    assert versions.index("v0.8") < versions.index("v0.6")


def test_news_page_renders_timeline_layout(timeline_db, monkeypatch):
    create_news(title="Sidebar Fix", body="GC-641", version_tag="v0.8", category="BUGFIX", badge="NEW")
    _, uname = _create_player()
    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    html = client.get("/news").get_data(as_text=True)
    assert 'class="gc-news-timeline"' in html
    assert 'id="version-v0-8"' in html
    assert "Sidebar Fix" in html
    assert "BUGFIX" in html


def test_import_changelog_idempotent(timeline_db):
    assert CHANGELOG.exists()
    first = import_changelog_markdown()
    assert first["inserted"] > 0
    second = import_changelog_markdown()
    assert second["inserted"] == 0
    assert second["skipped_versions"]


def test_whats_new_payload_latest_version(timeline_db):
    create_news(title="v0.8 — Alpha Polish", body="Major", version_tag="v0.8", is_major_release=True, badge="ALPHA")
    create_news(title="Fleet HUD", body="Fleet HUD", version_tag="v0.8", category="FEATURE")
    create_news(title="Old", body="Old", version_tag="v0.5", category="FEATURE")

    payload = whats_new_payload()
    assert payload["show"] is True
    assert payload["version_tag"] == "v0.8"
    assert any(item["title"] == "Fleet HUD" for item in payload["highlights"])


def test_whats_new_api(timeline_db, monkeypatch):
    create_news(title="Feature X", body="Feature X", version_tag="v0.8", category="FEATURE")
    _, uname = _create_player()
    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    data = client.get("/api/news/whats-new").get_json()
    assert data["ok"] is True
    assert data.get("show") is True


def test_draft_excluded_from_public_timeline(timeline_db):
    create_news(title="Draft note", body="secret", is_draft=True, version_tag="v0.8")
    create_news(title="Public", body="Public", version_tag="v0.8", category="FEATURE")
    payload = news_page_payload()
    titles = [e["title"] for e in payload["entries"]]
    assert "Draft note" not in titles
    assert "Public" in titles
