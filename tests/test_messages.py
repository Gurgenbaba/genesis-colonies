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
    bulk_update_messages,
    create_message,
    delete_message,
    dispatch_combat_reports,
    get_message,
    list_messages,
    mark_all_messages_read,
    mark_message_read,
    normalize_combat_metadata,
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


def test_bulk_update_messages_read_archive_delete(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("bulk_msg")
    for i in range(3):
        notify_player(pid, f"Msg {i}", f"Body {i}", category="system")
    _close_db()

    listed = list_messages(pid)
    ids = [m["id"] for m in listed["data"]["messages"]]
    assert len(ids) == 3

    read_res = bulk_update_messages(pid, ids[:2], action="read")
    assert read_res["ok"]
    assert read_res["data"]["updated"] == 2
    assert unread_count(pid) == 1

    arch_res = bulk_update_messages(pid, [ids[0]], action="archive")
    assert arch_res["ok"]
    archived = list_messages(pid, category="archive", include_archived=True)
    assert any(m["id"] == ids[0] for m in archived["data"]["messages"])

    del_res = bulk_update_messages(pid, [ids[2]], action="delete")
    assert del_res["ok"]
    listed_after = list_messages(pid)
    assert len(listed_after["data"]["messages"]) == 1


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


def test_list_messages_omits_body_and_metadata_for_inbox(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("list_light")
    notify_player(
        pid,
        "Spy subject",
        "Full report body text",
        category="espionage",
        metadata={"report_version": 2, "intel_tiers": {"fleet": True}},
    )
    _close_db()

    listed = list_messages(pid)
    assert listed["ok"] is True
    assert len(listed["data"]["messages"]) == 1
    item = listed["data"]["messages"][0]
    assert item["subject"] == "Spy subject"
    assert "body" not in item
    assert "metadata" not in item


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
    detail = get_message(pid, msg["id"], mark_read=False)
    assert "<script>" in detail["data"]["message"]["body"]


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


def test_message_to_zero_score_player(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    sender = _create_player("sender_z")
    target = _create_player("target_z")
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (target,))
    conn.execute("UPDATE players SET name = ? WHERE id = ?", ("Commander ZeroTarget", target))
    conn.commit()
    conn.close()
    _close_db()

    res = send_player_message(sender, "ZeroTarget", "Hello there", "Body text for zero score")
    assert res["ok"], res

    listed = list_messages(target)
    assert listed["ok"]
    assert any(m["subject"] == "Hello there" for m in listed["data"]["messages"])


def test_send_message_ambiguous_recipient(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    sender = _create_player("sender_amb")
    cmd_alpha = _create_player("cmd_alpha")
    plain_alpha = _create_player("plain_alpha")
    conn = db()
    conn.execute("UPDATE players SET name = ? WHERE id = ?", ("Commander Alpha", cmd_alpha))
    conn.execute("UPDATE players SET name = ? WHERE id = ?", ("Alpha", plain_alpha))
    conn.commit()
    conn.close()
    _close_db()

    res = send_player_message(sender, "Alpha", "Hello", "Ambiguous name test body")
    assert not res["ok"]
    assert res["error"] == "recipient_ambiguous"


def test_unread_count_matches_visible_unread_in_list(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("unread_sync")
    notify_player(pid, "Unread A", "Body A", category="system")
    notify_player(pid, "Unread B", "Body B", category="system")
    read_msg = notify_player(pid, "Read C", "Body C", category="system")
    _close_db()

    mid = read_msg["data"]["message_id"]
    assert mark_message_read(pid, mid)["ok"]

    listed = list_messages(pid)
    assert listed["ok"]
    visible_unread = [m for m in listed["data"]["messages"] if not m["is_read"]]
    assert unread_count(pid) == len(visible_unread)
    assert listed["data"]["unread_count"] == unread_count(pid)


def test_archived_and_deleted_unread_not_counted(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("unread_filter")
    notify_player(pid, "Still unread", "Counts in badge", category="system")
    res_arch = notify_player(pid, "Archive me", "Gone from badge", category="system")
    res_del = notify_player(pid, "Delete me", "Gone from badge", category="system")
    listed = list_messages(pid)
    arch_id = next(m["id"] for m in listed["data"]["messages"] if m["subject"] == "Archive me")
    del_id = res_del["data"]["message_id"]
    assert archive_message(pid, arch_id)["ok"]
    assert delete_message(pid, del_id)["ok"]
    _close_db()

    assert unread_count(pid) == 1
    listed = list_messages(pid)
    assert listed["data"]["unread_count"] == 1


def test_api_messages_lists_unread(temp_db, app_client):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("api_msg")
    notify_player(pid, "API ping", "Hello from API test", category="system")
    _close_db()

    with app_client.session_transaction() as sess:
        sess["user_id"] = pid

    r = app_client.get("/api/messages")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["data"]["unread_count"] >= 1
    assert any(m["subject"] == "API ping" for m in data["data"]["messages"])


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


def _set_player_name(player_id: int, name: str) -> None:
    conn = db()
    try:
        conn.execute("UPDATE players SET name = ? WHERE id = ?;", (name, int(player_id)))
        conn.commit()
    finally:
        conn.close()
    _close_db()


def _api_inbox(client, user_id: int, *, category: str | None = None):
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
    qs = f"?category={category}" if category else ""
    return client.get(f"/api/messages{qs}")


def _api_unread_via_list(client, user_id: int) -> int:
    data = _api_inbox(client, user_id).get_json()
    assert data["ok"]
    return int(data["data"]["unread_count"])


def _api_send(client, sender_id: int, recipient: str, subject: str, body: str):
    with client.session_transaction() as sess:
        sess["user_id"] = int(sender_id)
    return client.post(
        "/api/messages/send",
        json={"recipient": recipient, "subject": subject, "body": body},
    )


def test_alice_to_bob_inbox_isolation_api(app_client, temp_db):
    """A: Alice sends to Bob — only Bob's inbox and unread change."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    alice = _create_player("alice")
    bob = _create_player("bob")
    _set_player_name(bob, "Commander Bobby")
    _close_db()

    client = app_client
    alice_unread_before = _api_unread_via_list(client, alice)

    send = _api_send(client, alice, "Bobby", "Hello Bob", "Private note for Bobby")
    assert send.status_code == 200
    send_data = send.get_json()
    assert send_data["ok"]
    assert send_data["data"]["recipient_player_id"] == bob
    assert send_data["data"]["message_id"] > 0

    conn = db()
    try:
        row = conn.execute(
            """
            SELECT recipient_player_id, sender_player_id, category
            FROM player_messages WHERE id = ?;
            """,
            (int(send_data["data"]["message_id"]),),
        ).fetchone()
        assert int(row["recipient_player_id"]) == bob
        assert int(row["sender_player_id"]) == alice
        assert row["category"] == "player"
    finally:
        conn.close()
    _close_db()

    alice_inbox = _api_inbox(client, alice).get_json()
    assert not any(m["subject"] == "Hello Bob" for m in alice_inbox["data"]["messages"])
    assert alice_inbox["data"]["unread_count"] == alice_unread_before

    bob_inbox = _api_inbox(client, bob).get_json()
    bob_msgs = [m for m in bob_inbox["data"]["messages"] if m["subject"] == "Hello Bob"]
    assert len(bob_msgs) == 1
    assert bob_msgs[0]["sender_player_id"] == alice
    assert bob_inbox["data"]["unread_count"] == 1


def test_bob_read_clears_unread_alice_unchanged_api(app_client, temp_db):
    """B: Bob opens message — his unread drops; Alice unchanged."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    alice = _create_player("alice_read")
    bob = _create_player("bob_read")
    _set_player_name(bob, "Commander Bobby")
    _close_db()

    client = app_client
    send = _api_send(client, alice, "Bobby", "Read me", "Please open this message")
    mid = int(send.get_json()["data"]["message_id"])

    alice_unread = _api_unread_via_list(client, alice)

    with client.session_transaction() as sess:
        sess["user_id"] = bob
    detail = client.get(f"/api/messages/{mid}")
    assert detail.status_code == 200
    assert detail.get_json()["data"]["message"]["is_read"] is True
    assert detail.get_json()["data"]["message"]["reply_to_player_id"] == alice

    assert _api_unread_via_list(client, bob) == 0
    assert _api_unread_via_list(client, alice) == alice_unread


def test_bob_archive_and_delete_api(app_client, temp_db):
    """C: Bob archive/delete — list and badge stay consistent."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    alice = _create_player("alice_arch")
    bob = _create_player("bob_arch")
    _set_player_name(bob, "Bobby")
    _close_db()

    client = app_client
    send = _api_send(client, alice, "Bobby", "Archive test", "Archive this player mail")
    mid = int(send.get_json()["data"]["message_id"])

    with client.session_transaction() as sess:
        sess["user_id"] = bob
    arch = client.post(f"/api/messages/{mid}/archive")
    assert arch.get_json()["ok"]
    assert arch.get_json()["data"]["unread_count"] == 0

    active = _api_inbox(client, bob).get_json()
    assert not any(m["id"] == mid for m in active["data"]["messages"])

    archived = _api_inbox(client, bob, category="archive").get_json()
    assert any(m["id"] == mid for m in archived["data"]["messages"])

    with client.session_transaction() as sess:
        sess["user_id"] = bob
    deleted = client.post(f"/api/messages/{mid}/delete")
    assert deleted.get_json()["ok"]

    archived_after = _api_inbox(client, bob, category="archive").get_json()
    assert not any(m["id"] == mid for m in archived_after["data"]["messages"])


def test_api_messages_bulk_read_archive_delete(app_client, temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("bulk_api")
    notify_player(pid, "One", "Body one", category="system")
    notify_player(pid, "Two", "Body two", category="system")
    _close_db()

    client = app_client
    with client.session_transaction() as sess:
        sess["user_id"] = pid
    inbox = client.get("/api/messages").get_json()
    ids = [m["id"] for m in inbox["data"]["messages"]]

    bulk_read = client.post("/api/messages/bulk", json={"ids": ids, "action": "read"})
    assert bulk_read.get_json()["ok"]
    assert bulk_read.get_json()["data"]["updated"] == 2
    assert bulk_read.get_json()["data"]["unread_count"] == 0

    bulk_arch = client.post("/api/messages/bulk", json={"ids": [ids[0]], "action": "archive"})
    assert bulk_arch.get_json()["ok"]

    archived = client.get("/api/messages?category=archive").get_json()
    assert any(m["id"] == ids[0] for m in archived["data"]["messages"])

    bulk_del = client.post("/api/messages/bulk", json={"ids": [ids[1]], "action": "delete"})
    assert bulk_del.get_json()["ok"]
    active = client.get("/api/messages").get_json()
    assert active["data"]["messages"] == []


def test_send_lookup_exact_stored_name_api(app_client, temp_db):
    """Recipient lookup uses the exact stored player name only."""
    lookup_name = "Commander Bobby"
    _run_migrate(temp_db)
    init_db()
    _close_db()

    sender = _create_player(f"sender_{lookup_name.replace(' ', '_')}")
    target = _create_player(f"target_{lookup_name.replace(' ', '_')}")
    _set_player_name(target, "Commander Bobby")
    _close_db()

    client = app_client
    subject = f"To {lookup_name}"
    send = _api_send(client, sender, lookup_name, subject, "Lookup variant body text")
    assert send.get_json()["ok"]
    assert send.get_json()["data"]["recipient_player_id"] == target

    bob_inbox = _api_inbox(client, target).get_json()
    assert any(m["subject"] == subject for m in bob_inbox["data"]["messages"])


def test_send_lookup_ambiguous_api(app_client, temp_db):
    """D: Ambiguous recipient name is rejected."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    sender = _create_player("sender_amb_api")
    cmd = _create_player("cmd_amb")
    plain = _create_player("plain_amb")
    _set_player_name(cmd, "Commander Alpha")
    _set_player_name(plain, "Alpha")
    _close_db()

    client = app_client
    send = _api_send(client, sender, "Alpha", "Blocked", "Should not be delivered")
    assert send.status_code == 400
    assert send.get_json()["error"] == "recipient_ambiguous"


def test_alice_cannot_read_or_mutate_bob_message_api(app_client, temp_db):
    """E: Cross-player access and admin separation."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    alice = _create_player("sec_alice")
    bob = _create_player("sec_bob")
    admin_id = _create_player("sec_admin")
    _set_player_name(bob, "Bobby")
    conn = db()
    try:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?;", (admin_id,))
        conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?;", (admin_id,))
        conn.commit()
    finally:
        conn.close()
    _close_db()

    client = app_client
    send = _api_send(client, alice, "Bobby", "Secret", "Bob only content here")
    mid = int(send.get_json()["data"]["message_id"])

    with client.session_transaction() as sess:
        sess["user_id"] = alice
    assert client.get(f"/api/messages/{mid}").status_code == 404
    assert client.post(f"/api/messages/{mid}/archive").status_code == 404
    assert client.post(f"/api/messages/{mid}/delete").status_code == 404

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
    admin_list = client.get("/api/admin/messages").get_json()
    assert admin_list["ok"]
    assert any(m["id"] == mid for m in admin_list["data"]["messages"])

    alice_inbox = _api_inbox(client, alice).get_json()
    assert not any(m["id"] == mid for m in alice_inbox["data"]["messages"])


def test_legacy_deleted_at_zero_repaired_on_list(temp_db):
    """Legacy deleted_at=0 rows are repaired when the inbox is loaded."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("legacy_deleted")
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO player_messages (
                recipient_player_id, sender_player_id, sender_name,
                category, subject, body, is_read, is_archived,
                metadata_json, created_at, deleted_at
            ) VALUES (?, ?, ?, 'player', 'Hidden legacy row', 'Body text', 0, 0, NULL, ?, 0);
            """,
            (pid, None, "System", int(__import__("time").time())),
        )
        conn.commit()
    finally:
        conn.close()
    _close_db()

    listed = list_messages(pid)
    assert len(listed["data"]["messages"]) == 1
    assert listed["data"]["unread_count"] == 1
    assert mark_all_messages_read(pid)["ok"]
    assert unread_count(pid) == 0


def test_api_messages_returns_json_not_redirect_when_logged_out(app_client, temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    r = app_client.get("/api/messages")
    assert r.status_code == 401
    assert r.is_json
    assert r.get_json()["error"] == "not_logged_in"


def test_migration_021_normalizes_zero_deleted_at(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    pid = _create_player("m021")
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO player_messages (
                recipient_player_id, sender_player_id, sender_name,
                category, subject, body, is_read, is_archived,
                metadata_json, created_at, deleted_at
            ) VALUES (?, ?, ?, 'system', 'Was zero deleted', 'Body', 0, 0, NULL, ?, 0);
            """,
            (pid, None, "System", int(__import__("time").time())),
        )
        conn.commit()
    finally:
        conn.close()
    _close_db()

    listed = list_messages(pid)
    assert any(m["subject"] == "Was zero deleted" for m in listed["data"]["messages"])


def test_api_messages_repeat_get_returns_same_inbox(app_client, temp_db):
    """PJAX re-entry must be safe to call GET /api/messages again (no stale contract)."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    alice = _create_player("repeat_alice")
    bob = _create_player("repeat_bob")
    _set_player_name(bob, "RepeatBob")
    _close_db()

    client = app_client
    send = _api_send(client, alice, "RepeatBob", "Repeat subject", "Repeat body text")
    assert send.get_json()["ok"]

    first = _api_inbox(client, bob).get_json()
    second = _api_inbox(client, bob).get_json()

    assert first["ok"] and second["ok"]
    assert first["data"]["unread_count"] == second["data"]["unread_count"] == 1
    assert len(first["data"]["messages"]) == len(second["data"]["messages"]) == 1
    assert first["data"]["messages"][0]["subject"] == second["data"]["messages"][0]["subject"]


def test_api_messages_empty_only_after_ok_list(app_client, temp_db):
    """Empty inbox is valid only when API ok with zero items."""
    _run_migrate(temp_db)
    init_db()
    _close_db()

    player = _create_player("empty_inbox")
    payload = _api_inbox(client := app_client, player).get_json()
    assert payload["ok"] is True
    assert payload["data"]["messages"] == []
    assert payload["data"]["unread_count"] == 0


def test_fleet_ship_summary_no_raw_ship_keys():
    """Logistics/fleet report bodies must show display names, not internal ship keys."""
    from game.fleet import _format_fleet_ship_summary

    de_txt = _format_fleet_ship_summary({"atlas_hauler": 2, "mule_courier": 1}, locale="de")
    assert "atlas_hauler" not in de_txt
    assert "mule_courier" not in de_txt
    assert "Atlas-Frachter" in de_txt
    assert "Nomad" in de_txt

    unknown_txt = _format_fleet_ship_summary({"custom_hauler": 1}, locale="de")
    assert "custom_hauler" not in unknown_txt
    assert "Custom Hauler" in unknown_txt


def test_dispatch_combat_reports_persists_for_both_players(temp_db):
    from game.combat import COMBAT_REPORT_VERSION, build_combat_report
    from game.combat_models import CombatResult, CombatRound

    _run_migrate(temp_db)
    init_db()
    _close_db()

    attacker_id = _create_player("combat_atk")
    defender_id = _create_player("combat_def")
    combat_result = CombatResult(
        winner="attacker",
        rounds=(
            CombatRound(1, {}, {"sentinel_turret": 2}),
            CombatRound(2, {"falcon_interceptor": 1}, {}),
        ),
        attacker_losses={"falcon_interceptor": 1},
        defender_losses={"sentinel_turret": 2},
    )
    body, meta = build_combat_report(
        attacker_id=attacker_id,
        attacker_name="Attacker",
        defender_id=defender_id,
        defender_name="Defender",
        coords="2:3:4",
        attacking_ships={"falcon_interceptor": 5},
        defending_ships={},
        defending_defense={"sentinel_turret": 4},
        combat_result=combat_result,
        return_ships={"falcon_interceptor": 4},
        origin_coords="1:2:3",
        origin_planet_name="Alpha",
        target_planet_name="Beta",
    )
    meta = normalize_combat_metadata(meta)
    assert meta["report_version"] == COMBAT_REPORT_VERSION
    assert meta["origin_coords"] == "1:2:3"
    assert meta["target_planet_name"] == "Beta"
    assert len(meta["rounds"]) == 2
    assert meta["result"] == "attacker"
    assert "attacker_combat_research" in meta
    assert "weapon_tech" in meta["attacker_combat_research"]
    assert "═══" in body or "Combat report" in body

    sent = dispatch_combat_reports(
        attacker_id=attacker_id,
        defender_id=defender_id,
        coords="2:3:4",
        body=body,
        metadata=meta,
    )
    assert sent["attacker"]["ok"]
    assert sent["defender"]["ok"]

    _close_db()
    atk_inbox = list_messages(attacker_id, category="combat")
    def_inbox = list_messages(defender_id, category="combat")
    assert len(atk_inbox["data"]["messages"]) == 1
    assert len(def_inbox["data"]["messages"]) == 1

    atk_detail = get_message(attacker_id, atk_inbox["data"]["messages"][0]["id"], mark_read=False)
    def_detail = get_message(defender_id, def_inbox["data"]["messages"][0]["id"], mark_read=False)
    atk_msg = atk_detail["data"]["message"]
    def_msg = def_detail["data"]["message"]
    assert atk_msg["category"] == "combat"
    assert def_msg["category"] == "combat"
    assert atk_msg["metadata"]["perspective"] == "attacker"
    assert def_msg["metadata"]["perspective"] == "defender"
    assert atk_msg["metadata"]["rounds_fought"] == 2
    assert atk_msg["metadata"]["defender_losses"]["sentinel_turret"] == 2
    assert atk_msg["body"] == body

    conn = db()
    try:
        rows = conn.execute(
            "SELECT recipient_player_id, category, metadata_json FROM player_messages WHERE category = 'combat';"
        ).fetchall()
        assert len(rows) == 2
        recipients = {int(r["recipient_player_id"]) for r in rows}
        assert recipients == {attacker_id, defender_id}
    finally:
        conn.close()
