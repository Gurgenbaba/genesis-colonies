"""
Player messages inbox tests.

Run: python -m pytest tests/test_messages.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db, table_exists
from game.messages import (
    archive_message,
    create_message,
    delete_message,
    get_message,
    list_messages,
    mark_all_messages_read,
    mark_message_read,
    notify_admin,
    notify_combat,
    notify_espionage,
    notify_expedition,
    notify_player,
    notify_system,
    send_player_message,
    unread_count,
)
import json
from game.models import create_user, init_db, load_player

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "messages_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
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


def _close_db() -> None:
    try:
        db().close()
    except Exception:
        pass


def _create_player(username: str) -> int:
    import uuid

    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    _close_db()
    player = load_player(int(user["id"]))
    assert player
    return int(player["id"])


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_migration_table(temp_db):
    init_db()
    _close_db()
    _run_migrate(temp_db)

    conn = db()
    try:
        assert table_exists(conn, "player_messages")
    finally:
        conn.close()


def test_create_list_unread_and_read(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("msg_a")
    notify_player(pid, "Willkommen", "Deine Kolonie ist bereit.", category="system")
    _close_db()

    listed = list_messages(pid)
    assert listed["ok"]
    msgs = listed["data"]["messages"]
    assert len(msgs) == 1
    assert msgs[0]["is_read"] is False
    assert unread_count(pid) == 1

    mid = msgs[0]["id"]
    got = get_message(pid, mid)
    assert got["ok"]
    assert got["data"]["message"]["is_read"] is True
    assert got["data"]["message"]["read_at"] is not None
    assert unread_count(pid) == 0


def test_player_isolation_and_archive_delete(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    a = _create_player("msg_owner")
    b = _create_player("msg_other")
    create_message(a, "Geheim", "Nur für A", category="system")
    _close_db()

    listed_b = list_messages(b)
    assert listed_b["ok"]
    assert listed_b["data"]["messages"] == []

    listed_a = list_messages(a)
    mid = listed_a["data"]["messages"][0]["id"]

    foreign = get_message(b, mid)
    assert not foreign["ok"]
    assert foreign["error"] == "not_found"

    assert archive_message(a, mid)["ok"]
    archived = list_messages(a, category="archive")
    assert len(archived["data"]["messages"]) == 1

    assert delete_message(a, mid)["ok"]
    assert list_messages(a)["data"]["messages"] == []


def test_mark_all_read(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("msg_read_all")
    notify_player(pid, "Eins", "Body 1")
    notify_player(pid, "Zwei", "Body 2")
    _close_db()

    assert unread_count(pid) == 2
    result = mark_all_messages_read(pid)
    assert result["ok"]
    assert unread_count(pid) == 0


def test_send_player_message_validation(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    sender = _create_player("msg_sender")
    recipient = _create_player("msg_recipient")

    conn = db()
    try:
        conn.execute("UPDATE players SET name = ? WHERE id = ?;", ("UniqueRecipient", recipient))
        conn.commit()
    finally:
        conn.close()
    _close_db()

    bad = send_player_message(sender, "UnknownPlayerXYZ", "Hello", "Hello there friend")
    assert not bad["ok"]
    assert bad["error"] == "recipient_not_found"

    short = send_player_message(sender, "UniqueRecipient", "Hi", "x")
    assert not short["ok"]
    assert short["error"] == "validation"

    ok = send_player_message(sender, "UniqueRecipient", "Hallo", "Wie geht es dir?")
    assert ok["ok"]
    _close_db()

    inbox = list_messages(recipient, category="player")
    assert len(inbox["data"]["messages"]) == 1
    assert inbox["data"]["messages"][0]["sender_player_id"] == sender


def test_api_messages_flow(app_client, temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    a = _create_player("api_a")
    b = _create_player("api_b")

    conn = db()
    try:
        conn.execute("UPDATE players SET name = ? WHERE id = ?;", ("ApiTarget", b))
        conn.commit()
    finally:
        conn.close()
    _close_db()

    notify_player(a, "System Info", "Test body", category="system")

    client = app_client
    with client.session_transaction() as sess:
        sess["user_id"] = a

    r = client.get("/api/messages")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"]
    assert len(data["data"]["messages"]) >= 1
    mid = data["data"]["messages"][0]["id"]

    r2 = client.get(f"/api/messages/{mid}")
    assert r2.status_code == 200
    assert r2.get_json()["data"]["message"]["is_read"] is True

    with client.session_transaction() as sess:
        sess["user_id"] = b

    r_forbidden = client.get(f"/api/messages/{mid}")
    assert r_forbidden.status_code == 404

    with client.session_transaction() as sess:
        sess["user_id"] = a

    r_send = client.post(
        "/api/messages/send",
        json={"recipient": "ApiTarget", "subject": "Ping", "body": "Hello from API"},
    )
    assert r_send.status_code == 200
    assert r_send.get_json()["ok"]

    with client.session_transaction() as sess:
        sess["user_id"] = b

    r_state = client.get("/api/game-state")
    assert r_state.status_code == 200
    state = r_state.get_json()
    assert "unread_messages_count" in state
    assert state["unread_messages_count"] >= 1


def test_archived_and_deleted_excluded_from_unread(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("unread_edge")
    notify_player(pid, "Keep unread", "Body", category="system")
    notify_player(pid, "Archive me", "Body", category="system")
    notify_player(pid, "Delete me", "Body", category="system")
    _close_db()
    listed = list_messages(pid)
    by_subject = {m["subject"]: m["id"] for m in listed["data"]["messages"]}
    assert unread_count(pid) == 3
    archive_message(pid, by_subject["Archive me"])
    assert unread_count(pid) == 2
    delete_message(pid, by_subject["Delete me"])
    assert unread_count(pid) == 1


def test_mark_all_read_respects_reports_category(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("reports_read")
    create_message(pid, "Fight", "Report", category="combat")
    notify_player(pid, "System", "Sys body", category="system")
    _close_db()
    assert unread_count(pid) == 2
    mark_all_messages_read(pid, category="reports")
    _close_db()
    assert unread_count(pid) == 1
    listed = list_messages(pid, category="system")
    assert listed["data"]["messages"][0]["is_read"] is False


def test_reports_filter_lists_only_report_categories(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("reports_filter")
    create_message(pid, "Fight", "x", category="combat")
    create_message(pid, "Spy", "x", category="espionage")
    notify_player(pid, "Sys", "x", category="system")
    _close_db()

    reports = list_messages(pid, category="reports")
    cats = {m["category"] for m in reports["data"]["messages"]}
    assert cats <= {"combat", "espionage", "expedition"}
    assert "system" not in cats
    assert len(reports["data"]["messages"]) == 2


def test_self_send_blocked(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("self_send")
    conn = db()
    try:
        conn.execute("UPDATE players SET name = ? WHERE id = ?;", ("SelfSender", pid))
        conn.commit()
    finally:
        conn.close()
    _close_db()

    res = send_player_message(pid, "SelfSender", "Hello", "Message to myself")
    assert not res["ok"]
    assert res["error"] == "validation"


def test_cooldown_enforced(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    sender = _create_player("cooldown_sender")
    recipient = _create_player("cooldown_recipient")
    conn = db()
    try:
        conn.execute("UPDATE players SET name = ? WHERE id = ?;", ("CooldownTarget", recipient))
        conn.commit()
    finally:
        conn.close()
    _close_db()

    first = send_player_message(sender, "CooldownTarget", "One", "First message")
    second = send_player_message(sender, "CooldownTarget", "Two", "Second message")
    assert first["ok"]
    assert not second["ok"]
    assert second["error"] == "cooldown"


def test_xss_stored_as_plain_text(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("xss_target")
    payload = '<script>alert("xss")</script>'
    notify_player(pid, payload, payload, category="system")
    _close_db()

    listed = list_messages(pid)
    msg = listed["data"]["messages"][0]
    assert "<script>" in msg["subject"]
    assert "<script>" in msg["body"]


def test_api_returns_unread_after_mutations(app_client, temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("unread_api")
    notify_player(pid, "A", "body")
    _close_db()

    client = app_client
    with client.session_transaction() as sess:
        sess["user_id"] = pid

    listed = client.get("/api/messages").get_json()
    mid = listed["data"]["messages"][0]["id"]

    r_archive = client.post(f"/api/messages/{mid}/archive")
    assert r_archive.get_json()["data"]["unread_count"] == 0

    notify_player(pid, "B", "body2")
    _close_db()
    with client.session_transaction() as sess:
        sess["user_id"] = pid
    r_read_all = client.post("/api/messages/read-all", json={"category": "system"})
    assert r_read_all.get_json()["data"]["unread_count"] == 0


def test_admin_messages_api(app_client, temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    admin_id = _create_player("msg_admin")
    target_id = _create_player("msg_target")
    conn = db()
    try:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?;", (admin_id,))
        conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?;", (admin_id,))
        conn.execute("UPDATE players SET name = ? WHERE id = ?;", ("MsgTarget", target_id))
        conn.commit()
    finally:
        conn.close()
    notify_player(target_id, "Player mail", "secret", category="player")
    _close_db()

    client = app_client
    with client.session_transaction() as sess:
        sess["user_id"] = admin_id

    listing = client.get("/api/admin/messages")
    assert listing.status_code == 200
    data = listing.get_json()
    assert data["ok"]
    assert any(m["recipient_player_id"] == target_id for m in data["data"]["messages"])

    send = client.post(
        "/api/admin/messages/send",
        json={"recipient": "MsgTarget", "subject": "Admin ping", "body": "From admin panel"},
    )
    assert send.status_code == 200
    assert send.get_json()["ok"]

    with client.session_transaction() as sess:
        sess["user_id"] = target_id
    inbox = client.get("/api/messages?category=admin").get_json()
    assert any(m["category"] == "admin" for m in inbox["data"]["messages"])


def test_notify_helpers_category_and_metadata(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("notify_helpers")
    meta = {"battle_id": 42, "coords": "1:2:3"}

    cases = [
        (notify_system, "system", "System"),
        (notify_admin, "admin", "Administration"),
        (notify_combat, "combat", "Kampfbericht"),
        (notify_espionage, "espionage", "Spionagebericht"),
        (notify_expedition, "expedition", "Expeditionsbericht"),
    ]

    for fn, cat, sender in cases:
        res = fn(pid, f"Subject {cat}", f"Body for {cat}", metadata=meta)
        assert res["ok"], fn.__name__

    _close_db()
    assert unread_count(pid) == len(cases)

    conn = db()
    try:
        rows = conn.execute(
            "SELECT category, metadata_json FROM player_messages WHERE recipient_player_id = ?;",
            (pid,),
        ).fetchall()
        assert len(rows) == len(cases)
        for row in rows:
            assert row["category"] in {c[1] for c in cases}
            parsed = json.loads(row["metadata_json"])
            assert parsed["battle_id"] == 42
    finally:
        conn.close()


def test_notify_invalid_player_id(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    res = notify_system(0, "Hi", "Body text here")
    assert not res["ok"]
    assert res["error"] == "recipient_not_found"
    assert unread_count(999999) == 0


def test_messages_page_loads(app_client, temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("page_user")
    client = app_client
    with client.session_transaction() as sess:
        sess["user_id"] = pid

    r = client.get("/messages")
    assert r.status_code == 200
    assert b"messages-page" in r.data or b"gc-messages-page" in r.data
