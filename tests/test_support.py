"""
Support ticket + Discord forum notify tests (GC-656 / GC-656B).

Run: python -m pytest tests/test_support.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import game.db as dbmod
import game.models as models
from game.discord_support import (
    build_forum_applied_tags,
    build_forum_thread_message,
    build_forum_thread_title,
    build_webhook_embed,
    notify_discord_support_ticket,
    sync_discord_thread_tags,
)
from game.models import create_user, init_db
from game.support import change_ticket_status, create_ticket, notify_discord_new_ticket

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "support_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.delenv("DISCORD_SUPPORT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", raising=False)
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db_conn() -> None:
    try:
        models.db().close()
    except Exception:
        pass


def _create_player() -> tuple[int, str]:
    uname = f"sup_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user and user.get("id"), err
    _close_db_conn()
    return int(user["id"]), uname


@pytest.fixture()
def support_db(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db_conn()
    return temp_db


def test_create_ticket_without_discord_does_not_call_api(support_db, monkeypatch):
    player_id, _ = _create_player()
    called = {"n": 0}

    def _fake_urlopen(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("urlopen should not be called")

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fake_urlopen)

    res = create_ticket(
        player_id,
        {"subject": "Hilfe", "category": "bug", "message": "Etwas ist kaputt."},
    )
    assert res["ok"] is True
    assert int(res["data"]["ticket_id"]) > 0
    assert called["n"] == 0


def test_create_ticket_creates_forum_thread(support_db, monkeypatch):
    player_id, username = _create_player()
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token-test")
    monkeypatch.setenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", "999888777")
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_CHEATER", "111222333")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://genesis.example")

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=3):
        captured["url"] = req.full_url
        captured["method"] = req.method
        captured["timeout"] = timeout
        captured["body"] = json.loads(req.data.decode("utf-8")) if req.data else None
        captured["auth"] = req.headers.get("Authorization")
        resp = MagicMock()
        if req.method == "POST":
            resp.read.return_value = b'{"id":"444555666777888999"}'
        else:
            resp.read.return_value = b"{}"
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fake_urlopen)

    res = create_ticket(
        player_id,
        {
            "subject": "Loligerloler is cheating",
            "category": "report",
            "message": "Unfair speed hack.",
        },
    )
    assert res["ok"] is True
    ticket_id = int(res["data"]["ticket_id"])
    assert captured["url"] == "https://discord.com/api/v10/channels/999888777/threads"
    assert captured["auth"] == "Bot bot-token-test"
    body = captured["body"]
    assert body["name"] == "[CHEATER] Loligerloler is cheating"
    assert body["applied_tags"] == ["111222333"]
    assert username in body["message"]["content"]
    assert str(player_id) in body["message"]["content"]
    assert str(ticket_id) in body["message"]["content"]
    assert "Unfair speed hack." in body["message"]["content"]

    conn = models.db()
    try:
        row = conn.execute(
            "SELECT discord_thread_id FROM support_tickets WHERE id = ?;",
            (ticket_id,),
        ).fetchone()
        assert row["discord_thread_id"] == "444555666777888999"
    finally:
        conn.close()
        _close_db_conn()


def test_forum_preferred_over_webhook(support_db, monkeypatch):
    player_id, _ = _create_player()
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token-test")
    monkeypatch.setenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", "999888777")
    monkeypatch.setenv("DISCORD_SUPPORT_WEBHOOK_URL", "https://discord.com/api/webhooks/test/token")

    urls: list[str] = []

    def _fake_urlopen(req, timeout=3):
        urls.append(req.full_url)
        resp = MagicMock()
        resp.read.return_value = b"{}"
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fake_urlopen)

    create_ticket(
        player_id,
        {"subject": "Test", "category": "general", "message": "Hello."},
    )
    assert len(urls) == 1
    assert "/threads" in urls[0]


def test_create_ticket_succeeds_when_discord_fails(support_db, monkeypatch):
    player_id, _ = _create_player()
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token-test")
    monkeypatch.setenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", "999888777")

    def _fail_urlopen(*_args, **_kwargs):
        raise OSError("discord down")

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fail_urlopen)

    res = create_ticket(
        player_id,
        {"subject": "Timeout-Test", "category": "general", "message": "Bitte ignorieren."},
    )
    assert res["ok"] is True
    assert int(res["data"]["ticket_id"]) > 0


def test_webhook_fallback_when_forum_not_configured(support_db, monkeypatch):
    player_id, username = _create_player()
    webhook_url = "https://discord.com/api/webhooks/test/token"
    monkeypatch.setenv("DISCORD_SUPPORT_WEBHOOK_URL", webhook_url)

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=3):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        resp = MagicMock()
        resp.read.return_value = b""
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fake_urlopen)

    res = create_ticket(
        player_id,
        {"subject": "Account-Frage", "category": "account", "message": "Login geht nicht."},
    )
    assert res["ok"] is True
    assert captured["url"] == webhook_url
    embed = captured["body"]["embeds"][0]
    field_map = {f["name"]: f["value"] for f in embed["fields"]}
    assert field_map["Spielername"] == username
    assert field_map["Kategorie"] == "Account"


def test_build_forum_thread_title_truncates():
    long_subject = "x" * 120
    title = build_forum_thread_title("report", long_subject)
    assert title.startswith("[CHEATER]")
    assert len(title) <= 100


def test_build_forum_thread_message_includes_coords():
    body = build_forum_thread_message(
        ticket_id=1,
        player_id=2,
        player_name="Bobby",
        subject="Test",
        category="report",
        message="Details here.",
        created_at=1_718_914_200,
        coordinates="[1:1:1]",
    )
    assert "Bobby" in body
    assert "[1:1:1]" in body
    assert "Details here." in body


def test_notify_discord_noop_without_config(monkeypatch):
    monkeypatch.delenv("DISCORD_SUPPORT_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", raising=False)

    def _fail(*_args, **_kwargs):
        raise AssertionError("urlopen should not run")

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fail)
    notify_discord_new_ticket(
        ticket_id=1,
        player_id=2,
        player_name="Tester",
        subject="S",
        category="general",
        message="M",
        created_at=1_700_000_000,
    )


def test_build_forum_applied_tags_status_mapping(monkeypatch):
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_CHEATER", "111")
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_IN_PROGRESS", "222")
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_DONE", "333")

    assert build_forum_applied_tags("report", "open") == ["111"]
    assert build_forum_applied_tags("report", "in_progress") == ["111", "222"]
    assert build_forum_applied_tags("report", "closed") == ["111", "333"]


def test_change_ticket_status_syncs_discord_tags(support_db, monkeypatch):
    player_id, _ = _create_player()
    admin_id = player_id
    conn = models.db()
    conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?;", (admin_id,))
    conn.execute(
        """
        INSERT INTO support_tickets
          (player_id, subject, category, priority, status, created_at, updated_at, last_message_at, discord_thread_id)
        VALUES (?, 'Test', 'report', 'normal', 'open', 1, 1, 1, 'thread-abc');
        """,
        (player_id,),
    )
    ticket_id = int(conn.execute("SELECT last_insert_rowid();").fetchone()[0])
    conn.commit()
    conn.close()
    _close_db_conn()

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token-test")
    monkeypatch.setenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", "999888777")
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_CHEATER", "111222333")
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_IN_PROGRESS", "444555666")

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=3):
        captured["method"] = req.method
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8")) if req.data else None
        resp = MagicMock()
        resp.read.return_value = b"{}"
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fake_urlopen)

    res = change_ticket_status(admin_id, ticket_id, "in_progress")
    assert res["ok"] is True
    assert captured["method"] == "PATCH"
    assert captured["url"].endswith("/channels/thread-abc")
    assert captured["body"]["applied_tags"] == ["111222333", "444555666"]


def test_change_ticket_status_succeeds_when_discord_sync_fails(support_db, monkeypatch):
    player_id, _ = _create_player()
    admin_id = player_id
    conn = models.db()
    conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?;", (admin_id,))
    conn.execute(
        """
        INSERT INTO support_tickets
          (player_id, subject, category, priority, status, created_at, updated_at, last_message_at, discord_thread_id)
        VALUES (?, 'Test', 'general', 'normal', 'open', 1, 1, 1, 'thread-abc');
        """,
        (player_id,),
    )
    ticket_id = int(conn.execute("SELECT last_insert_rowid();").fetchone()[0])
    conn.commit()
    conn.close()
    _close_db_conn()

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token-test")
    monkeypatch.setenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", "999888777")

    def _fail(*_args, **_kwargs):
        raise OSError("discord down")

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fail)

    res = change_ticket_status(admin_id, ticket_id, "closed")
    assert res["ok"] is True
    assert res["data"]["status"] == "closed"


def test_sync_discord_thread_tags_closed_applies_done(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token-test")
    monkeypatch.setenv("DISCORD_SUPPORT_FORUM_CHANNEL_ID", "999888777")
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_ANYTHING", "100")
    monkeypatch.setenv("DISCORD_SUPPORT_TAG_DONE", "200")

    captured: dict[str, object] = {}

    def _fake_urlopen(req, timeout=3):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        resp = MagicMock()
        resp.read.return_value = b"{}"
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    monkeypatch.setattr("game.discord_support.urllib.request.urlopen", _fake_urlopen)
    sync_discord_thread_tags(thread_id="thread-xyz", category="general", status="closed")
    assert captured["body"]["applied_tags"] == ["100", "200"]


def test_build_webhook_embed_has_ticket_fields():
    embed = build_webhook_embed(
        ticket_id=10,
        player_id=20,
        player_name="Tester",
        subject="Betreff",
        category="bug",
        message="Nachricht",
        created_at=1_700_000_000,
    )
    assert embed["title"] == "🎫 Neues Support-Ticket"
    names = {f["name"] for f in embed["fields"]}
    assert "Ticket-ID" in names
    assert "Nachricht" in names
