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
    AUDIENCE_DEV,
    AUDIENCE_PLAYER,
    _changelog_release_dates,
    _format_published,
    _is_player_visible_entry,
    _sanitize_player_text,
    build_player_timeline,
    build_timeline,
    create_news,
    import_changelog_markdown,
    import_git_history,
    list_news,
    news_page_payload,
    reclassify_news_audience,
    repository_history_audit,
    sidebar_release_nav,
    sync_release_dates,
    update_news,
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
    assert 'class="gc-news-patchnotes"' in html
    assert 'id="version-v0-8"' in html
    assert "Sidebar Fix" in html or "Sidebar" in html


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


def test_update_existing_news(timeline_db):
    entry = create_news(title="Original", body="Body v1", version_tag="v0.8", category="FEATURE")
    updated = update_news(
        entry["id"],
        title="Updated title",
        body="Body v2",
        category="BUGFIX",
        publish=False,
    )
    assert updated
    assert updated["title"] == "Updated title"
    assert updated["body"] == "Body v2"
    assert updated["category"] == "BUGFIX"


def test_import_git_history_idempotent(timeline_db):
    commits = [
        {"hash": "abc123", "date": "2026-06-18", "subject": "GC-650 Timeline System"},
        {"hash": "def456", "date": "2026-06-17", "subject": "GC-641 Sidebar Fix"},
    ]
    first = import_git_history(commits=commits, after_version="v0.8", created_by=1)
    assert first["inserted"] == 2
    assert first["version_tag"] == "development"

    second = import_git_history(commits=commits, after_version="v0.8", created_by=1)
    assert second["inserted"] == 0
    assert second["skipped"] == 2

    dev_entries = [e for e in list_news(limit=50) if e.get("version_tag") == "development"]
    assert len(dev_entries) == 2
    assert dev_entries[0]["source_ref"].startswith("git:")


def test_development_stream_timeline_label(timeline_db):
    create_news(
        title="GC-650 Timeline",
        body="Timeline work",
        version_tag="development",
        category="FEATURE",
        badge="DEV",
        published_at=1750204800,
    )
    create_news(title="v0.8 — Alpha", body="Major", version_tag="v0.8", is_major_release=True)

    timeline = build_timeline(list_news(limit=50))
    dev_block = next(
        (v for year in timeline for v in year["versions"] if v["version_tag"] == "development"),
        None,
    )
    assert dev_block is not None
    assert dev_block["version_label"] == "Ongoing Development"


def test_sidebar_release_nav_major_and_dev(timeline_db):
    create_news(title="v0.8 — Alpha", body="Major", version_tag="v0.8", is_major_release=True)
    create_news(title="GC-650", body="Timeline", version_tag="development", category="FEATURE")

    nav = sidebar_release_nav()
    assert nav["label"] == "v0.8"
    assert nav["href"] == "/news#version-v0-8"
    assert nav["has_dev_stream"] is False


def test_player_timeline_excludes_dev_and_git(timeline_db):
    create_news(title="v0.8 — Alpha Polish", body="Intro", version_tag="v0.8", is_major_release=True)
    create_news(
        title="Global Fleet HUD",
        body="Global Fleet HUD",
        version_tag="v0.8",
        category="FEATURE",
        source_ref="changelog:v0.8:fleet",
    )
    create_news(
        title="tests/test_combat.py (36+ tests)",
        body="tests/test_combat.py",
        version_tag="development",
        category="DEVBLOG",
        source_ref="git:abc123",
    )
    reclassify_news_audience()

    payload = news_page_payload()
    titles = [
        e.get("display_title") or e.get("title")
        for year in payload["timeline"]
        for version in year["versions"]
        for section in version.get("sections") or []
        for e in section.get("entries") or []
    ]
    assert any("Fleet" in t for t in titles)
    assert not any("tests/" in t for t in titles)
    assert not any(v.get("version_tag") == "development" for year in payload["timeline"] for v in year["versions"])


def test_sanitize_player_text_strips_tickets():
    raw = "**Wirtschaft/Trader Hub** — Sidebar-Section (GC-641/641B)"
    clean = _sanitize_player_text(raw)
    assert "GC-641" not in clean
    assert "Trader Hub" in clean


def test_dev_content_hidden_from_players(timeline_db):
    entry = {
        "title": "docs/ROADMAP.md update",
        "body": "docs/ROADMAP.md",
        "audience": AUDIENCE_PLAYER,
        "is_draft": False,
        "version_tag": "v0.8",
        "category": "FEATURE",
    }
    assert _is_player_visible_entry(entry) is False


def test_changelog_release_dates_monotonic(timeline_db):
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    dates = _changelog_release_dates(text)

    assert dates["v0.1"] < dates["v0.8"]
    assert _format_published(dates["v0.1"]) == "25.05.2026"
    assert _format_published(dates["v0.8"]) == "10.06.2026"


def test_sync_release_dates_updates_rows(timeline_db):
    create_news(
        title="v0.8 — Alpha",
        body="Intro",
        version_tag="v0.8",
        is_major_release=True,
        published_at=1,
    )
    result = sync_release_dates()
    assert result["updated"] >= 1
    entry = list_news(limit=5)[0]
    assert entry["published_label"] == "10.06.2026"


def test_repository_history_audit(timeline_db):
    audit = repository_history_audit()
    assert audit["ok"] is True
    assert audit["commit_count"] > 0
    assert audit["first_commit_date"] == "2026-05-25"
    nav = sidebar_release_nav()
    assert nav["label"].startswith("v")
    assert nav["url"] == "/news"


def test_import_full_history_commits_and_releases_lock(timeline_db):
    from game.admin_audit import write_admin_audit
    from game.universe_news import import_full_history

    result = import_full_history(created_by=1)
    assert result["ok"] is True
    write_admin_audit(1, "test_after_import", payload={"inserted": result.get("inserted")})
    assert list_news(limit=500)
