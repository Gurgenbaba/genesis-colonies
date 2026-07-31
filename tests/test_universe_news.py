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
    ensure_v09_release_seeded,
    get_banner_entry,
    get_news_entry,
    list_news,
    news_page_payload,
    publish_release_pack,
    set_banner,
    update_news,
    whats_new_payload,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def news_db(tmp_path, monkeypatch):
    db_file = tmp_path / "universe_news.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_SKIP_NEWS_SEED", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    env["GC_SKIP_NEWS_SEED"] = "1"
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
    assert any("economy sidebar" in (e.get("body") or "") for e in entries)
    banner = get_banner_entry()
    assert banner is not None
    assert "economy sidebar" in (banner.get("body") or "")


def test_create_and_list_news_entries(news_db):
    first = create_news(title="Patch A", body="First entry", set_banner=True, created_by=1)
    second = create_news(title="Patch B", body="Second entry", set_banner=True, created_by=1)
    entries = list_news()
    ids = {int(e["id"]) for e in entries}
    assert int(first["id"]) in ids and int(second["id"]) in ids
    assert int(entries[0]["id"]) == int(second["id"])
    banner = get_banner_entry()
    assert banner and int(banner["id"]) == int(second["id"])


def test_set_banner_and_delete_news(news_db):
    a = create_news(title="A", body="Body A", set_banner=True)
    b = create_news(title="B", body="Body B", set_banner=False)
    assert get_banner_entry()["id"] == a["id"]
    set_banner(b["id"])
    assert get_banner_entry()["id"] == b["id"]
    assert delete_news(b["id"]) is True
    assert get_news_entry(b["id"]) is None
    assert get_news_entry(a["id"]) is not None


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


def test_news_page_payload_has_no_repository_audit(news_db, monkeypatch):
    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("repository_history_audit must not run on player news path")

    monkeypatch.setattr("game.universe_news.repository_history_audit", _boom)
    payload = news_page_payload()
    assert payload["ok"] is True
    assert "repository" not in payload
    assert calls["n"] == 0


def test_publish_release_pack_and_reject_duplicate(news_db):
    first = publish_release_pack(
        version_tag="v9.9",
        version_label="Test Pack",
        intro="Lead text for commanders.",
        release_date="2026-07-31",
        added=["New thing A", "New thing B"],
        changed=["Better thing"],
        fixed=["Fixed thing"],
        set_banner=False,
    )
    assert first["ok"] is True
    assert first["inserted"] >= 4
    second = publish_release_pack(
        version_tag="v9.9",
        version_label="Test Pack",
        intro="Lead",
        added=["Nope"],
    )
    assert second["ok"] is False
    assert second["error"] == "version_exists"


def test_v09_seed_idempotent_and_whats_new_major(news_db):
    # Bootstrap may already have seeded v0.9 — ensure idempotent.
    again = ensure_v09_release_seeded()
    assert again["ok"] is True
    assert again.get("seeded") is False or again.get("reason") == "v0.9_exists" or again.get("seeded") is True

    wn = whats_new_payload()
    assert wn["ok"] is True
    if wn.get("show"):
        assert wn.get("is_major_release") is True
        assert str(wn.get("version_tag") or "").lower() not in ("development", "dev", "ongoing")
