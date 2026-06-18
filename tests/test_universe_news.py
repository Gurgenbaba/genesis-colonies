"""GC-642 — Universe news / changelog."""

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
from game.models import create_user, init_db, save_game_settings
from game.universe_news import (
    create_news,
    delete_news,
    ensure_legacy_motd_migrated,
    get_banner_entry,
    get_news_entry,
    list_news,
    set_banner,
    update_news,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def news_db(tmp_path, monkeypatch):
    db_file = tmp_path / "universe_news.db"
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
    uname = f"news_{uuid.uuid4().hex[:8]}"
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


def test_legacy_motd_migrates_into_news_table(news_db):
    save_game_settings({"motd_text": "Update 18.06.2026\nFix economy sidebar.", "motd_enabled": 1})
    ensure_legacy_motd_migrated()
    entries = list_news()
    assert len(entries) == 1
    assert "economy sidebar" in entries[0]["body"]
    assert entries[0]["is_banner"] is True


def test_create_and_list_news_entries(news_db):
    first = create_news(title="Patch A", body="First entry", set_banner=True, created_by=1)
    second = create_news(title="Patch B", body="Second entry", set_banner=True, created_by=1)
    entries = list_news()
    assert len(entries) == 2
    assert entries[0]["id"] == second["id"]
    assert entries[1]["id"] == first["id"]
    banner = get_banner_entry()
    assert banner and banner["id"] == second["id"]


def test_set_banner_and_delete_news(news_db):
    a = create_news(title="A", body="Body A", set_banner=True)
    b = create_news(title="B", body="Body B", set_banner=False)
    assert get_banner_entry()["id"] == a["id"]
    set_banner(b["id"])
    assert get_banner_entry()["id"] == b["id"]
    assert delete_news(b["id"]) is True
    assert len(list_news()) == 1


def test_delete_news_via_admin_api(news_db, monkeypatch):
    ok, _, admin = create_user("news_del_admin", "adminpass123", is_admin=1)
    assert ok and admin
    entry = create_news(title="Delete me", body="Body", set_banner=False)

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": "news_del_admin", "password": "adminpass123"})
    res = client.post(f"/api/admin/universe-news/{entry['id']}/delete", json={})
    data = res.get_json()
    assert res.status_code == 200
    assert data["ok"] is True
    assert data.get("deleted") is True
    assert get_news_entry(entry["id"]) is None


def test_update_news_via_admin_api(news_db, monkeypatch):
    ok, _, admin = create_user("news_admin", "adminpass123", is_admin=1)
    assert ok and admin
    entry = create_news(title="Before", body="Old body", version_tag="v0.8")

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": "news_admin", "password": "adminpass123"})
    res = client.patch(
        f"/api/admin/universe-news/{entry['id']}",
        json={"title": "After", "body": "New body", "version_tag": "development", "category": "FEATURE"},
    )
    data = res.get_json()
    assert res.status_code == 200
    assert data["ok"] is True
    assert data["entry"]["title"] == "After"
    assert data["entry"]["body"] == "New body"
    assert data["entry"]["version_tag"] == "development"


def test_news_page_renders_archive(news_db, monkeypatch):
    create_news(title="Patch 1", body="Line one\nLine two", set_banner=True)
    create_news(title="Patch 0", body="Older patch", set_banner=False)

    _, uname = _create_player()
    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    html = client.get("/news").get_data(as_text=True)
    assert 'id="news-page"' in html
    assert "Patch 1" in html
    assert "Patch 0" in html
    assert 'class="gc-news-patchnotes"' in html


def test_overview_shows_banner_with_archive_link(news_db, monkeypatch):
    create_news(title="Live Patch", body="Visible banner text", set_banner=True)
    save_game_settings({"motd_enabled": 1})

    _, uname = _create_player()
    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    html = client.get("/overview").get_data(as_text=True)
    assert 'data-motd-banner' in html
    assert "Live Patch" in html
    assert 'href="/news"' in html
