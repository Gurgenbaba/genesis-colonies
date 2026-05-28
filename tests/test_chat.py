"""
Genesis TChat tests.

Run: python -m pytest tests/test_chat.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.alliance import add_alliance_member, create_alliance
from game.chat import (
    admin_chat_ban_player,
    admin_chat_unban_player,
    admin_delete_message,
    admin_search_messages,
    admin_system_notice,
    clamp_ui_state_values,
    fetch_messages,
    mute_player,
    open_dm_room,
    render_message_body,
    reset_rate_limits,
    save_user_state,
    send_chat_message,
)
from game.db import db, table_exists
from game.models import create_user, init_db, load_player

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "chat_test.db"
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
    return int(user["id"])


def _make_admin(player_id: int) -> None:
    conn = db()
    try:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?;", (int(player_id),))
        conn.execute("UPDATE players SET is_admin = 1 WHERE id = ?;", (int(player_id),))
        conn.commit()
    finally:
        conn.close()
    _close_db()


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    _close_db()
    reset_rate_limits()

    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_migration_tables(temp_db):
    init_db()
    _close_db()
    _run_migrate(temp_db)

    conn = db()
    try:
        for tbl in (
            "chat_rooms",
            "chat_messages",
            "chat_room_members",
            "chat_mutes",
            "chat_bans",
            "chat_user_state",
            "alliances",
            "alliance_members",
        ):
            assert table_exists(conn, tbl), tbl
    finally:
        conn.close()


def test_xss_escaped_in_render():
    raw = '<script>alert(1)</script> @Commander'
    html_out = render_message_body(raw, viewer_name="Other")
    assert "<script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "gc-chat-mention" in html_out


def test_global_and_whisper(app_client):
    reset_rate_limits()
    a = _create_player("chat_a")
    b = _create_player("chat_b")

    with app_client.session_transaction() as sess:
        sess["user_id"] = a
    r = app_client.post("/api/chat/send", json={"body": "/g Hello Galaxy"})
    assert r.status_code == 200
    assert r.get_json()["ok"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = b
    r2 = app_client.get("/api/chat/bootstrap")
    data = r2.get_json()["data"]
    global_room = next(x for x in data["rooms"] if x["room_type"] == "global")
    msgs = app_client.get(f"/api/chat/messages?room_id={global_room['id']}&after_id=0")
    bodies = [m["message"] for m in msgs.get_json()["data"]["messages"]]
    assert "Hello Galaxy" in bodies

    with app_client.session_transaction() as sess:
        sess["user_id"] = a
    pb = load_player(b)
    r3 = app_client.post("/api/chat/send", json={"body": f"/w {pb['name']} Secret ping"})
    assert r3.get_json()["ok"]
    dm_room_id = r3.get_json()["data"]["room_id"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = b
    dm_msgs = app_client.get(f"/api/chat/messages?room_id={dm_room_id}&after_id=0")
    assert any("Secret ping" in m["message"] for m in dm_msgs.get_json()["data"]["messages"])

    c = _create_player("chat_c")
    with app_client.session_transaction() as sess:
        sess["user_id"] = c
    denied = app_client.get(f"/api/chat/messages?room_id={dm_room_id}&after_id=0")
    assert denied.get_json()["ok"] is False


def test_open_dm_api(app_client):
    reset_rate_limits()
    a = _create_player("dm_a")
    b = _create_player("dm_b")
    with app_client.session_transaction() as sess:
        sess["user_id"] = a
    r = app_client.post("/api/chat/open-dm", json={"target_player_id": b})
    assert r.get_json()["ok"]
    assert r.get_json()["data"]["room_id"] > 0


def test_alliance_isolation(app_client):
    reset_rate_limits()
    p1 = _create_player("ally1")
    p2 = _create_player("ally2")
    outsider = _create_player("ally_out")

    conn = db()
    try:
        ally = create_alliance("TST", "Test Alliance", p1, conn=conn)
        add_alliance_member(int(ally["id"]), p2, conn=conn)
        conn.commit()
    finally:
        conn.close()
    _close_db()

    with app_client.session_transaction() as sess:
        sess["user_id"] = p1
    r = app_client.post("/api/chat/send", json={"body": "/a Alliance secret"})
    assert r.get_json()["ok"]
    room_id = r.get_json()["data"]["room_id"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = p2
    assert app_client.get(f"/api/chat/messages?room_id={room_id}&after_id=0").get_json()["ok"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = outsider
    assert app_client.get(f"/api/chat/messages?room_id={room_id}&after_id=0").get_json()["ok"] is False


def test_rate_limit(app_client):
    reset_rate_limits()
    uid = _create_player("spam")
    with app_client.session_transaction() as sess:
        sess["user_id"] = uid

    for i in range(5):
        assert app_client.post("/api/chat/send", json={"body": f"/g msg {i}"}).get_json()["ok"]

    r6 = app_client.post("/api/chat/send", json={"body": "/g blocked"})
    assert r6.get_json()["ok"] is False
    assert r6.get_json()["error"] == "rate_limited"


def test_slash_reply(app_client):
    reset_rate_limits()
    a = _create_player("reply_a")
    b = _create_player("reply_b")
    pb = load_player(b)

    with app_client.session_transaction() as sess:
        sess["user_id"] = a
    app_client.post("/api/chat/send", json={"body": f"/w {pb['name']} first"})
    r = app_client.post("/api/chat/send", json={"body": "/r second line"})
    assert r.get_json()["ok"]
    room_id = r.get_json()["data"]["room_id"]
    msgs, err = fetch_messages(a, room_id, after_id=0)
    assert not err
    texts = [m["message"] for m in msgs]
    assert "first" in texts and "second line" in texts


def test_ui_state_clamp():
    out = clamp_ui_state_values({"width": 9999, "height": 50, "pos_x": -5, "pos_y": 99999})
    assert out["width"] == 720
    assert out["height"] == 320
    assert out["pos_x"] == 0
    assert out["pos_y"] == 4096


def test_ui_state_api_clamp(app_client):
    uid = _create_player("ui_clamp")
    with app_client.session_transaction() as sess:
        sess["user_id"] = uid
    r = app_client.post(
        "/api/chat/state",
        json={"width": 9000, "height": 100, "pos_x": -10, "pos_y": 50000, "is_open": False},
    )
    assert r.get_json()["ok"]
    ui = r.get_json()["data"]["ui_state"]
    assert ui["width"] <= 720
    assert ui["height"] >= 320
    assert ui["pos_x"] >= 0


def test_mute_blocks_send(app_client):
    reset_rate_limits()
    admin = _create_player("chat_admin")
    victim = _create_player("chat_victim")
    _make_admin(admin)

    until = int(time.time()) + 3600
    mute_player(victim, admin, "global", until)
    _close_db()

    with app_client.session_transaction() as sess:
        sess["user_id"] = victim
    r = app_client.post("/api/chat/send", json={"body": "/g hello"})
    assert r.get_json()["ok"] is False
    assert r.get_json()["error"] == "muted"


def test_admin_notice_and_permissions(app_client):
    reset_rate_limits()
    admin = _create_player("adm_n")
    user = _create_player("adm_u")
    _make_admin(admin)

    with app_client.session_transaction() as sess:
        sess["user_id"] = user
    denied = app_client.post("/api/chat/admin/system-notice", json={"body": "hack"})
    assert denied.get_json()["ok"] is False

    with app_client.session_transaction() as sess:
        sess["user_id"] = admin
    ok = app_client.post("/api/chat/admin/system-notice", json={"body": "Server maintenance"})
    assert ok.get_json()["ok"]


def test_admin_delete_message_hidden(app_client):
    reset_rate_limits()
    admin = _create_player("del_adm")
    _make_admin(admin)
    author = _create_player("del_auth")

    with app_client.session_transaction() as sess:
        sess["user_id"] = author
    sent = app_client.post("/api/chat/send", json={"body": "/g delete me please"})
    assert sent.get_json()["ok"]
    msg_id = sent.get_json()["data"]["message"]["id"]
    room_id = sent.get_json()["data"]["room_id"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = admin
    assert app_client.post("/api/chat/admin/delete-message", json={"message_id": msg_id}).get_json()["ok"]

    msgs, err = fetch_messages(author, room_id, after_id=0)
    assert not err
    target = next(m for m in msgs if int(m["id"]) == int(msg_id))
    assert target["is_deleted"]
    assert target["message"] == ""


def test_slash_clear_client_only(app_client):
    uid = _create_player("clear_u")
    with app_client.session_transaction() as sess:
        sess["user_id"] = uid
    r = app_client.post("/api/chat/send", json={"body": "/clear"})
    assert r.get_json()["ok"]
    assert r.get_json()["data"].get("client_only") is True


def test_slash_help_client_or_local(app_client):
    uid = _create_player("help_u")
    with app_client.session_transaction() as sess:
        sess["user_id"] = uid
    r = app_client.post("/api/chat/send", json={"body": "/help"})
    data = r.get_json()
    assert data["ok"]
    if data["data"].get("client_only"):
        assert data["data"]["action"] == "help"


def test_playercard_has_whisper_button(app_client):
    viewer = _create_player("pc_view")
    target = _create_player("pc_tgt")
    with app_client.session_transaction() as sess:
        sess["user_id"] = viewer
    html = app_client.get(f"/api/player-card/{target}").get_data(as_text=True)
    assert "data-chat-whisper" in html
    assert 'data-player-id="' + str(target) in html or f"data-player-id=\"{target}\"" in html


def test_admin_search_non_admin_denied(app_client):
    user = _create_player("search_u")
    with app_client.session_transaction() as sess:
        sess["user_id"] = user
    r = app_client.get("/api/chat/admin/search?q=test")
    assert r.get_json()["ok"] is False


def test_custom_room_create_invite_remove(app_client):
    owner = _create_player("room_owner")
    other = _create_player("room_other")
    outsider = _create_player("room_out")

    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "Ops Team"})
    assert create_res.get_json()["ok"]
    room_id = int(create_res.get_json()["data"]["room_id"])

    invite_res = app_client.post("/api/chat/rooms/invite", json={"room_id": room_id, "player_id": other})
    assert invite_res.get_json()["ok"]
    members_res = app_client.get(f"/api/chat/rooms/members?room_id={room_id}")
    assert members_res.get_json()["ok"]
    assert any(int(m["player_id"]) == int(other) for m in members_res.get_json()["data"]["members"])

    with app_client.session_transaction() as sess:
        sess["user_id"] = other
    r_ok = app_client.get(f"/api/chat/messages?room_id={room_id}&after_id=0")
    assert r_ok.get_json()["ok"] is True

    with app_client.session_transaction() as sess:
        sess["user_id"] = outsider
    r_no = app_client.get(f"/api/chat/messages?room_id={room_id}&after_id=0")
    assert r_no.get_json()["ok"] is False

    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    rem_res = app_client.post("/api/chat/rooms/remove", json={"room_id": room_id, "player_id": other})
    assert rem_res.get_json()["ok"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = other
    r_no2 = app_client.get(f"/api/chat/messages?room_id={room_id}&after_id=0")
    assert r_no2.get_json()["ok"] is False


def test_chat_ban_blocks_chat_and_unban_restores(app_client):
    admin = _create_player("ban_admin")
    victim = _create_player("ban_victim")
    _make_admin(admin)

    assert admin_chat_ban_player(admin, victim).get("ok") is True
    _close_db()

    with app_client.session_transaction() as sess:
        sess["user_id"] = victim
    denied = app_client.post("/api/chat/send", json={"body": "/g should fail"})
    assert denied.get_json()["ok"] is False
    assert denied.get_json()["error"] == "chat_banned"

    assert admin_chat_unban_player(admin, victim).get("ok") is True
    _close_db()

    allowed = app_client.post("/api/chat/send", json={"body": "/g works again"})
    assert allowed.get_json()["ok"] is True


def test_custom_room_delete(app_client):
    owner = _create_player("del_room_owner")
    guest = _create_player("del_room_guest")
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "Delete Me"})
    assert create_res.get_json()["ok"]
    room_id = int(create_res.get_json()["data"]["room_id"])
    invite_res = app_client.post("/api/chat/rooms/invite", json={"room_id": room_id, "player_id": guest})
    assert invite_res.get_json()["ok"]
    del_res = app_client.post("/api/chat/rooms/delete", json={"room_id": room_id})
    assert del_res.get_json()["ok"]
    del_res2 = app_client.post("/api/chat/rooms/delete", json={"room_id": room_id})
    assert del_res2.get_json()["ok"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = guest
    denied = app_client.get(f"/api/chat/messages?room_id={room_id}&after_id=0")
    assert denied.get_json()["ok"] is False


def test_delete_room_as_admin(app_client):
    owner = _create_player("room_admin_owner")
    admin = _create_player("room_admin_actor")
    _make_admin(admin)
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "AdminDelete"})
    room_id = int(create_res.get_json()["data"]["room_id"])
    with app_client.session_transaction() as sess:
        sess["user_id"] = admin
    res = app_client.post("/api/chat/rooms/delete", json={"room_id": room_id})
    assert res.get_json()["ok"] is True


def test_delete_room_as_non_owner_forbidden(app_client):
    owner = _create_player("room_non_owner_owner")
    other = _create_player("room_non_owner_other")
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "NoDelete"})
    room_id = int(create_res.get_json()["data"]["room_id"])
    with app_client.session_transaction() as sess:
        sess["user_id"] = other
    res = app_client.post("/api/chat/rooms/delete", json={"room_id": room_id})
    assert res.get_json()["ok"] is False
    assert res.get_json()["error"] == "no_permission"


def test_deleted_room_not_returned_in_bootstrap(app_client):
    owner = _create_player("room_boot_owner")
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "GoneRoom"})
    room_id = int(create_res.get_json()["data"]["room_id"])
    assert app_client.post("/api/chat/rooms/delete", json={"room_id": room_id}).get_json()["ok"] is True
    boot = app_client.get("/api/chat/bootstrap").get_json()["data"]
    ids = {int(r["id"]) for r in boot["rooms"] if r.get("id")}
    assert room_id not in ids


def test_deleting_active_room_bootstrap_fallback(app_client):
    owner = _create_player("room_fb_owner")
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "FallbackRoom"})
    room_id = int(create_res.get_json()["data"]["room_id"])
    assert app_client.post("/api/chat/state", json={"active_room_id": room_id, "is_open": True}).get_json()["ok"]
    assert app_client.post("/api/chat/rooms/delete", json={"room_id": room_id}).get_json()["ok"]
    boot = app_client.get("/api/chat/bootstrap").get_json()["data"]
    global_room = next(r for r in boot["rooms"] if r["room_type"] == "global")
    assert int(boot["active_room_id"]) == int(global_room["id"])


def test_room_members_permission_checks(app_client):
    owner = _create_player("room_mem_owner")
    outsider = _create_player("room_mem_out")
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "MembersCheck"})
    room_id = int(create_res.get_json()["data"]["room_id"])
    with app_client.session_transaction() as sess:
        sess["user_id"] = outsider
    res = app_client.get(f"/api/chat/rooms/members?room_id={room_id}")
    assert res.get_json()["ok"] is False
    assert res.get_json()["error"] == "no_permission"


def test_owner_member_leave_rules(app_client):
    owner = _create_player("room_leave_owner")
    member = _create_player("room_leave_member")
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    create_res = app_client.post("/api/chat/rooms/create", json={"title": "LeaveRules"})
    room_id = int(create_res.get_json()["data"]["room_id"])
    assert app_client.post("/api/chat/rooms/invite", json={"room_id": room_id, "player_id": member}).get_json()["ok"]

    # Owner cannot leave while member exists
    owner_leave = app_client.post("/api/chat/rooms/leave", json={"room_id": room_id})
    assert owner_leave.get_json()["ok"] is False
    assert owner_leave.get_json()["error"] == "owner_cannot_leave_room"

    # Member can leave
    with app_client.session_transaction() as sess:
        sess["user_id"] = member
    member_leave = app_client.post("/api/chat/rooms/leave", json={"room_id": room_id})
    assert member_leave.get_json()["ok"] is True

    # Owner can now leave (room deactivates)
    with app_client.session_transaction() as sess:
        sess["user_id"] = owner
    owner_leave2 = app_client.post("/api/chat/rooms/leave", json={"room_id": room_id})
    assert owner_leave2.get_json()["ok"] is True


def test_bootstrap_unread_increases_after_global_message(app_client):
    """Chat badge sync: bootstrap unread rises when another player posts in global room."""
    reset_rate_limits()
    sender = _create_player("chat_unread_sender")
    recipient = _create_player("chat_unread_recipient")

    with app_client.session_transaction() as sess:
        sess["user_id"] = recipient
    boot_before = app_client.get("/api/chat/bootstrap").get_json()["data"]
    global_room = next(x for x in boot_before["rooms"] if x["room_type"] == "global")
    rid = str(global_room["id"])
    unread_before = int(boot_before.get("unread", {}).get(rid, 0))

    with app_client.session_transaction() as sess:
        sess["user_id"] = sender
    send = app_client.post("/api/chat/send", json={"body": "/g Unread badge regression ping"})
    assert send.get_json()["ok"]

    with app_client.session_transaction() as sess:
        sess["user_id"] = recipient
    boot_after = app_client.get("/api/chat/bootstrap").get_json()["data"]
    unread_after = int(boot_after.get("unread", {}).get(rid, 0))
    assert unread_after > unread_before

    poll = app_client.get(f"/api/chat/messages?room_id={global_room['id']}&after_id=0")
    assert poll.get_json()["ok"]
    assert any("Unread badge regression ping" in m["message"] for m in poll.get_json()["data"]["messages"])
