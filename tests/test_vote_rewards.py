"""GC-551 / GC-552 / GC-551B — Vote postback, random rewards, and claim tests."""

from __future__ import annotations

import importlib
import json
import os
import time
import uuid

import pytest

from game import db as gdb
from game.auction_house import is_event_box
from game.db import db
from game.inventory import _inventory_amount
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.vote_rewards import (
    ARENA_TOP100_PROVIDER,
    DEFAULT_VOTE_BOX_KEY,
    GAMETOOR_COOLDOWN_SEC,
    GAMETOOR_PROVIDER,
    GTOP100_COOLDOWN_SEC,
    GTOP100_PROVIDER,
    TOPG_COOLDOWN_SEC,
    TOPG_PROVIDER,
    VOTE_PROVIDERS,
    VOTE_REWARD_POOL,
    claim_all_vote_rewards,
    claim_vote_reward,
    get_provider_cooldown_status,
    get_vote_center_state,
    handle_vote_visit,
    is_allowed_vote_reward_box,
    is_topg_postback_allowed,
    list_enabled_providers,
    record_provider_vote,
    record_topg_vote,
    resolve_vote_url,
    roll_vote_reward,
    topg_strict_ip_check_enabled,
    topg_vote_url,
    vote_providers_schema_ready,
    vote_rewards_schema_ready,
    vote_reward_next_at_column_ready,
    vote_system_ready,
)

GTOP100_PINGBACK_TEST_KEY = "test-gtop100-key"
ARENA_TOP100_SECRET_TEST = "test-arena-secret"
GAMETOOR_IVN_TEST_KEY = "test-gametoor-ivn-key"
GAMETOOR_URL = "http://gametoor.com/in/3277/{user_id}"
TWELVE_H_COOLDOWN_SEC = 12 * 60 * 60

LOOTBOX_PAYLOAD = {
    "reward_type": "lootbox",
    "reward_key": "vote_supply_container",
    "box_key": "generic_supply_container",
    "amount": 1,
}
RESOURCE_PAYLOAD = {
    "reward_type": "resources",
    "reward_key": "vote_resource_pack_small",
    "metal": 2_500_000,
    "crystal": 1_000_000,
    "fuel_cells": 50_000,
}
SHIP_PAYLOAD = {
    "reward_type": "ships",
    "reward_key": "vote_ship_pack_scout",
    "ships": {"spark_drone": 5},
}
DEFENSE_PAYLOAD = {
    "reward_type": "defense",
    "reward_key": "vote_defense_pack_basic",
    "defense": {"sentinel_turret": 5},
}


@pytest.fixture
def vote_db(tmp_path, monkeypatch):
    db_path = tmp_path / "vote_rewards_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_VOTE_SKIP_IP_CHECK", "1")
    monkeypatch.setenv("TOPG_STRICT_IP_CHECK", "0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"vote_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Voter", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _gtop100_json_payload(uid: int, *, pingback_key: str = GTOP100_PINGBACK_TEST_KEY, success: int = 0, pb_id: int = 1):
    return {
        "siteid": 106142,
        "pingbackkey": pingback_key,
        "Common": [
            [
                {"pb_id": pb_id},
                {"ip": "123.123.123.123"},
                {"success": success},
                {"reason": "Vote accepted"},
                {"pb_name": str(uid)},
            ]
        ],
    }


def _login_client(vote_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    conn = db()
    ok, err, user = create_user(f"vc_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return client, uid, app_module


def _context_planet_id(uid: int, conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    planets = get_planets_by_player(uid, conn=conn)
    pid = int(planets[0]["id"])
    if own:
        conn.close()
    return pid


def test_vote_schema_ready(vote_db):
    conn = db()
    assert vote_rewards_schema_ready(conn) is True
    assert vote_providers_schema_ready(conn) is True
    assert vote_system_ready(conn) is True
    conn.close()


def test_topg_strict_ip_check_default_off(vote_db, monkeypatch):
    monkeypatch.delenv("TOPG_STRICT_IP_CHECK", raising=False)
    monkeypatch.delenv("GC_VOTE_SKIP_IP_CHECK", raising=False)
    assert topg_strict_ip_check_enabled() is False
    assert is_topg_postback_allowed("203.0.113.99") is True


def test_topg_cooldown_is_6_hours(vote_db):
    assert TOPG_COOLDOWN_SEC == 6 * 60 * 60
    assert VOTE_PROVIDERS["topg"]["cooldown_seconds"] == 6 * 60 * 60


ARENA_TOP100_URL = "https://www.arena-top100.com/index.php?a=in&u=Gurgenbaba&id={user_id}"


def _gametoor_ivn(client, uid: int, *, key: str = GAMETOOR_IVN_TEST_KEY, **extra):
    data = {
        "key": key,
        "already_voted": extra.pop("already_voted", "0"),
        "ip": extra.pop("ip", "198.51.100.10"),
        "custom": str(uid),
    }
    data.update(extra)
    return client.post("/api/vote/gametoor/ivn", data=data)


def _arena_postback(client, uid: int, *, secret: str = ARENA_TOP100_SECRET_TEST, **extra):
    now = int(time.time())
    data = {
        "secret": secret,
        "voted": "1",
        "reset": str(extra.pop("reset", now + 3600)),
        "userip": extra.pop("userip", "1.2.3.4"),
        "userid": str(uid),
    }
    data.update(extra)
    return client.post("/api/vote/arena-top100/postback", data=data)


def test_enabled_providers_include_all_vote_providers(vote_db):
    conn = db()
    providers = list_enabled_providers(conn=conn)
    keys = {p["provider_key"] for p in providers}
    assert "topg" in keys
    assert "gtop100" in keys
    assert "gametoor" in keys
    assert "arena_top100" in keys
    topg = next(p for p in providers if p["provider_key"] == "topg")
    gtop100 = next(p for p in providers if p["provider_key"] == "gtop100")
    gametoor = next(p for p in providers if p["provider_key"] == "gametoor")
    arena = next(p for p in providers if p["provider_key"] == "arena_top100")
    assert topg["cooldown_sec"] == 6 * 60 * 60
    assert topg["postback_enabled"] is True
    assert resolve_vote_url(topg["vote_url_template"], 42) == (
        f"https://topg.org/ogame-private-servers/server-683112-42#vote"
    )
    assert gtop100["cooldown_sec"] == 12 * 60 * 60
    assert gtop100["postback_enabled"] is True
    assert resolve_vote_url(gtop100["vote_url_template"], 42) == (
        "https://gtop100.com/Ogame/server-106142?vote=1&pingUsername=42"
    )
    assert gametoor["vote_url_template"] == GAMETOOR_URL
    assert resolve_vote_url(gametoor["vote_url_template"], 42) == GAMETOOR_URL.replace("{user_id}", "42")
    assert gametoor["postback_enabled"] is True
    assert gametoor["cooldown_sec"] == GAMETOOR_COOLDOWN_SEC
    assert arena["display_name"] == "Arena-Top100"
    assert arena["vote_url_template"] == ARENA_TOP100_URL
    assert resolve_vote_url(arena["vote_url_template"], 42) == ARENA_TOP100_URL.replace("{user_id}", "42")
    assert arena["postback_enabled"] is True
    conn.close()


def test_arena_top100_provider_config(vote_db):
    arena = VOTE_PROVIDERS["arena_top100"]
    assert arena["display_name"] == "Arena-Top100"
    assert arena["vote_url_template"] == ARENA_TOP100_URL
    assert arena["postback_enabled"] is True
    assert arena["cooldown_seconds"] == TWELVE_H_COOLDOWN_SEC


def test_arena_next_at_column_ready(vote_db):
    conn = db()
    assert vote_reward_next_at_column_ready(conn) is True
    conn.close()


def test_arena_top100_vote_link_contains_user_id(vote_db):
    uid = _player()
    conn = db()
    state = get_vote_center_state(uid, conn=conn)
    arena = next(p for p in state["providers"] if p["provider_key"] == "arena_top100")
    assert arena["vote_url"] == ARENA_TOP100_URL.replace("{user_id}", str(uid))
    assert arena["postback_enabled"] is True
    assert arena["reward_status_key"] == "vote_provider_arena_top100_reward_active"
    conn.close()


def test_arena_top100_valid_callback_creates_reward(vote_db, monkeypatch):
    monkeypatch.setenv("ARENA_TOP100_SECRET", ARENA_TOP100_SECRET_TEST)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    reset_at = int(time.time()) + 7200
    res = _arena_postback(client, uid, reset=reset_at)
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 1
    conn = db()
    row = conn.execute(
        "SELECT status, provider, provider_next_vote_at FROM vote_rewards WHERE user_id = ?;",
        (uid,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["provider"] == ARENA_TOP100_PROVIDER
    assert int(row["provider_next_vote_at"]) == reset_at
    conn.close()


def test_arena_top100_wrong_secret_rejected(vote_db, monkeypatch):
    monkeypatch.setenv("ARENA_TOP100_SECRET", ARENA_TOP100_SECRET_TEST)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = _arena_postback(client, uid, secret="wrong-secret")
    assert res.status_code == 403
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards;").fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_arena_top100_non_numeric_userid_no_reward(vote_db, monkeypatch):
    monkeypatch.setenv("ARENA_TOP100_SECRET", ARENA_TOP100_SECRET_TEST)
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.post(
        "/api/vote/arena-top100/postback",
        data={
            "secret": ARENA_TOP100_SECRET_TEST,
            "voted": "1",
            "reset": str(int(time.time()) + 3600),
            "userip": "1.2.3.4",
            "userid": "not-a-user",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 0
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards;").fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_arena_top100_voted_zero_no_reward(vote_db, monkeypatch):
    monkeypatch.setenv("ARENA_TOP100_SECRET", ARENA_TOP100_SECRET_TEST)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = _arena_postback(client, uid, voted="0")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 0
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_arena_top100_hard_cooldown_12h(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    providers = list_enabled_providers(conn=conn)
    arena_row = next(p for p in providers if p["provider_key"] == ARENA_TOP100_PROVIDER)
    record_provider_vote(
        ARENA_TOP100_PROVIDER,
        uid,
        "1.2.3.4",
        conn=conn,
        now=now,
        reward_payload=LOOTBOX_PAYLOAD,
    )
    cd_locked = get_provider_cooldown_status(uid, arena_row, conn=conn, now=now + 3600)
    assert cd_locked["can_vote"] is False
    assert cd_locked["cooldown_remaining_sec"] > 0
    cd_free = get_provider_cooldown_status(
        uid, arena_row, conn=conn, now=now + TWELVE_H_COOLDOWN_SEC + 1
    )
    assert cd_free["can_vote"] is True
    conn.close()


def test_gametoor_provider_config(vote_db):
    gametoor = VOTE_PROVIDERS["gametoor"]
    assert gametoor["display_name"] == "GameToor"
    assert gametoor["vote_url_template"] == GAMETOOR_URL
    assert gametoor["postback_enabled"] is True
    assert gametoor["cooldown_seconds"] == TWELVE_H_COOLDOWN_SEC


def test_gametoor_vote_link_contains_user_id(vote_db):
    uid = _player()
    conn = db()
    state = get_vote_center_state(uid, conn=conn)
    gametoor = next(p for p in state["providers"] if p["provider_key"] == GAMETOOR_PROVIDER)
    assert gametoor["vote_url"] == GAMETOOR_URL.replace("{user_id}", str(uid))
    assert gametoor["postback_enabled"] is True
    assert gametoor["reward_status_key"] == "vote_provider_gametoor_reward_active"
    conn.close()


def test_gametoor_ivn_creates_pending_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GAMETOOR_IVN_KEY", GAMETOOR_IVN_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = _gametoor_ivn(client, uid)
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 1
    conn = db()
    row = conn.execute(
        "SELECT status, provider FROM vote_rewards WHERE user_id = ?;",
        (uid,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["provider"] == GAMETOOR_PROVIDER
    conn.close()


def test_gametoor_ivn_wrong_key_rejected(vote_db, monkeypatch):
    monkeypatch.setenv("GAMETOOR_IVN_KEY", GAMETOOR_IVN_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = _gametoor_ivn(client, uid, key="wrong-key")
    assert res.status_code == 403
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards;").fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_gametoor_ivn_non_numeric_custom_no_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GAMETOOR_IVN_KEY", GAMETOOR_IVN_TEST_KEY)
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.post(
        "/api/vote/gametoor/ivn",
        data={
            "key": GAMETOOR_IVN_TEST_KEY,
            "already_voted": "0",
            "ip": "1.2.3.4",
            "custom": "not-a-user",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 0
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards;").fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_gametoor_ivn_unknown_user_no_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GAMETOOR_IVN_KEY", GAMETOOR_IVN_TEST_KEY)
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.post(
        "/api/vote/gametoor/ivn",
        data={
            "key": GAMETOOR_IVN_TEST_KEY,
            "already_voted": "0",
            "ip": "1.2.3.4",
            "custom": "999999",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 0
    assert data["reason"] == "invalid_user"


def test_gametoor_ivn_already_voted_no_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GAMETOOR_IVN_KEY", GAMETOOR_IVN_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = _gametoor_ivn(client, uid, already_voted="1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 0
    assert data["reason"] == "already_voted"
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_gametoor_ivn_already_voted_zero_creates_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GAMETOOR_IVN_KEY", GAMETOOR_IVN_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = _gametoor_ivn(client, uid, already_voted="0")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 1


def test_gametoor_duplicate_within_12h_no_second_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GAMETOOR_IVN_KEY", GAMETOOR_IVN_TEST_KEY)
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1 = record_provider_vote(
        GAMETOOR_PROVIDER,
        uid,
        "1.2.3.4",
        conn=conn,
        now=now,
        reward_payload=LOOTBOX_PAYLOAD,
    )
    _, created2 = record_provider_vote(
        GAMETOOR_PROVIDER,
        uid,
        "1.2.3.5",
        conn=conn,
        now=now + 60,
        reward_payload=LOOTBOX_PAYLOAD,
    )
    assert created1 is True
    assert created2 is False
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_valid_topg_callback_creates_pending_reward(vote_db):
    uid = _player()
    conn = db()
    processed, created = record_topg_vote(uid, "203.0.113.10", conn=conn, reward_payload=LOOTBOX_PAYLOAD)
    assert processed is True
    assert created is True
    cur = conn.cursor()
    cur.execute(
        "SELECT status, reward_key, reward_payload_json, provider FROM vote_rewards WHERE user_id = ?;",
        (uid,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["provider"] == TOPG_PROVIDER
    payload = json.loads(row["reward_payload_json"])
    assert payload["reward_type"] == "lootbox"
    assert payload["box_key"] == DEFAULT_VOTE_BOX_KEY
    conn.close()


def test_vote_visit_creates_pending_reward(vote_db):
    uid = _player()
    conn = db()
    ok, created, reason, rem = handle_vote_visit(uid, TOPG_PROVIDER, conn=conn)
    assert ok is True
    assert created is True
    assert reason == "reward_pending"
    assert rem == 0
    row = conn.execute(
        "SELECT status, provider FROM vote_rewards WHERE user_id = ?;",
        (uid,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["provider"] == TOPG_PROVIDER
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_topg_visit_blocked_within_6h(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1, _, _ = handle_vote_visit(uid, TOPG_PROVIDER, conn=conn, now=now)
    ok, created2, reason, rem = handle_vote_visit(uid, TOPG_PROVIDER, conn=conn, now=now + 120)
    assert created1 is True
    assert ok is True
    assert created2 is False
    assert reason == "cooldown_active"
    assert rem > 0
    assert rem <= TOPG_COOLDOWN_SEC
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_topg_visit_allowed_after_6h(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1, _, _ = handle_vote_visit(uid, TOPG_PROVIDER, conn=conn, now=now)
    later = now + TOPG_COOLDOWN_SEC + 1
    ok, created2, reason, _ = handle_vote_visit(uid, TOPG_PROVIDER, conn=conn, now=later)
    assert created1 is True
    assert ok is True
    assert created2 is True
    assert reason == "reward_pending"
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 2
    conn.close()


def test_gtop100_visit_blocked_within_12h(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1, _, _ = handle_vote_visit(uid, GTOP100_PROVIDER, conn=conn, now=now)
    ok, created2, reason, rem = handle_vote_visit(uid, GTOP100_PROVIDER, conn=conn, now=now + 300)
    assert created1 is True
    assert ok is True
    assert created2 is False
    assert reason == "cooldown_active"
    assert rem > 0
    assert rem <= GTOP100_COOLDOWN_SEC
    conn.close()


def test_gtop100_visit_allowed_after_12h(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1, _, _ = handle_vote_visit(uid, GTOP100_PROVIDER, conn=conn, now=now)
    later = now + GTOP100_COOLDOWN_SEC + 1
    ok, created2, reason, _ = handle_vote_visit(uid, GTOP100_PROVIDER, conn=conn, now=later)
    assert created1 is True
    assert ok is True
    assert created2 is True
    assert reason == "reward_pending"
    conn.close()


def test_gametoor_visit_blocked_within_12h(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1, _, _ = handle_vote_visit(uid, GAMETOOR_PROVIDER, conn=conn, now=now)
    ok, created2, reason, rem = handle_vote_visit(uid, GAMETOOR_PROVIDER, conn=conn, now=now + 300)
    assert created1 is True
    assert ok is True
    assert created2 is False
    assert reason == "cooldown_active"
    assert rem > 0
    conn.close()


def test_vote_visit_idempotent_request_id(vote_db, monkeypatch):
    client, login_uid, _ = _login_client(vote_db, monkeypatch)
    req_id = str(uuid.uuid4())
    res1 = client.post("/api/vote/visit", json={"provider_key": "topg", "request_id": req_id})
    res2 = client.post("/api/vote/visit", json={"provider_key": "topg", "request_id": req_id})
    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.get_json() == res2.get_json()
    conn = db()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;",
        (login_uid,),
    ).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_vote_visit_api_endpoint(vote_db, monkeypatch):
    client, login_uid, _ = _login_client(vote_db, monkeypatch)
    res = client.post(
        "/api/vote/visit",
        json={"provider_key": "topg", "request_id": str(uuid.uuid4())},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] is True
    assert data.get("vote_center") is not None
    conn = db()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ? AND status = 'pending';",
        (login_uid,),
    ).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_roll_vote_reward_single_entry(vote_db):
    rng = __import__("random").Random(7)
    reward = roll_vote_reward(rng=rng)
    assert reward["reward_type"] in {"lootbox", "resources", "ships", "defense"}
    assert reward["reward_key"]
    if reward["reward_type"] == "lootbox":
        assert is_allowed_vote_reward_box(reward.get("box_key", ""))


def test_pool_never_contains_event_box(vote_db):
    for entry in VOTE_REWARD_POOL:
        payload = entry.get("payload") or {}
        box_key = payload.get("box_key")
        if box_key:
            assert is_event_box(box_key) is False
            assert is_allowed_vote_reward_box(box_key) is True


def test_invalid_user_id_ignored(vote_db):
    conn = db()
    processed, created = record_topg_vote(999_999, "1.2.3.4", conn=conn, reward_payload=LOOTBOX_PAYLOAD)
    assert processed is True
    assert created is False
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM vote_rewards;")
    assert int(cur.fetchone()["c"]) == 0
    conn.close()


def test_non_numeric_p_resp_rejected(vote_db, monkeypatch):
    client, _uid, _app = _login_client(vote_db, monkeypatch)
    res = client.get("/api/vote/topg/postback?p_resp=abc&ip=1.2.3.4")
    assert res.status_code == 400
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM vote_rewards;")
    assert int(cur.fetchone()["c"]) == 0
    conn.close()


def test_second_callback_within_6h_no_duplicate(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    processed1, created1 = record_topg_vote(uid, "1.2.3.4", conn=conn, now=now, reward_payload=LOOTBOX_PAYLOAD)
    processed2, created2 = record_topg_vote(uid, "1.2.3.5", conn=conn, now=now + 60, reward_payload=LOOTBOX_PAYLOAD)
    assert processed1 and created1
    assert processed2 and not created2
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,))
    assert int(cur.fetchone()["c"]) == 1
    conn.close()


def test_topg_reward_after_cooldown_expires(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1 = record_topg_vote(uid, "1.1.1.1", conn=conn, now=now, reward_payload=LOOTBOX_PAYLOAD)
    later = now + TOPG_COOLDOWN_SEC + 1
    _, created2 = record_topg_vote(uid, "1.1.1.2", conn=conn, now=later, reward_payload=LOOTBOX_PAYLOAD)
    assert created1 is True
    assert created2 is True
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,))
    assert int(cur.fetchone()["c"]) == 2
    conn.close()


def test_claim_lootbox_reward(vote_db):
    uid = _player()
    conn = db()
    record_topg_vote(uid, "1.2.3.4", conn=conn, reward_payload=LOOTBOX_PAYLOAD)
    cur = conn.cursor()
    cur.execute("SELECT id FROM vote_rewards WHERE user_id = ? LIMIT 1;", (uid,))
    reward_id = int(cur.fetchone()["id"])
    pid = _context_planet_id(uid, conn=conn)
    ok, reason, result = claim_vote_reward(uid, reward_id, conn=conn, planet_id=pid)
    assert ok is True
    assert reason == "vote_reward_claimed"
    assert result["reward_type"] == "lootbox"
    assert _inventory_amount(uid, "container_basic", conn=conn) == 1
    conn.close()


def test_claim_resources_reward(vote_db):
    uid = _player()
    conn = db()
    record_topg_vote(uid, "1.2.3.4", conn=conn, reward_payload=RESOURCE_PAYLOAD)
    cur = conn.cursor()
    cur.execute("SELECT id FROM vote_rewards WHERE user_id = ? LIMIT 1;", (uid,))
    reward_id = int(cur.fetchone()["id"])
    pid = _context_planet_id(uid, conn=conn)
    conn.execute("UPDATE planets SET metal = 0, crystal = 0, fuel_cells = 0 WHERE id = ?;", (pid,))
    ok, reason, result = claim_vote_reward(uid, reward_id, conn=conn, planet_id=pid)
    assert ok is True
    assert result["reward_type"] == "resources"
    row = conn.execute("SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()
    assert float(row["metal"]) == 2_500_000
    assert float(row["crystal"]) == 1_000_000
    assert float(row["fuel_cells"]) == 50_000
    conn.close()


def test_claim_ships_reward(vote_db):
    uid = _player()
    conn = db()
    record_topg_vote(uid, "1.2.3.4", conn=conn, reward_payload=SHIP_PAYLOAD)
    cur = conn.cursor()
    cur.execute("SELECT id FROM vote_rewards WHERE user_id = ? LIMIT 1;", (uid,))
    reward_id = int(cur.fetchone()["id"])
    pid = _context_planet_id(uid, conn=conn)
    ok, reason, result = claim_vote_reward(uid, reward_id, conn=conn, planet_id=pid)
    assert ok is True
    assert result["reward_type"] == "ships"
    row = conn.execute(
        "SELECT amount FROM planet_ships WHERE planet_id = ? AND ship_key = ?;",
        (pid, "spark_drone"),
    ).fetchone()
    assert row is not None
    assert int(row["amount"]) == 5
    conn.close()


def test_claim_defense_reward(vote_db):
    uid = _player()
    conn = db()
    record_topg_vote(uid, "1.2.3.4", conn=conn, reward_payload=DEFENSE_PAYLOAD)
    cur = conn.cursor()
    cur.execute("SELECT id FROM vote_rewards WHERE user_id = ? LIMIT 1;", (uid,))
    reward_id = int(cur.fetchone()["id"])
    pid = _context_planet_id(uid, conn=conn)
    ok, reason, result = claim_vote_reward(uid, reward_id, conn=conn, planet_id=pid)
    assert ok is True
    assert result["reward_type"] == "defense"
    row = conn.execute(
        "SELECT amount FROM planet_defense WHERE planet_id = ? AND defense_key = ?;",
        (pid, "sentinel_turret"),
    ).fetchone()
    assert row is not None
    assert int(row["amount"]) == 5
    conn.close()


def test_claim_foreign_reward_blocked(vote_db):
    uid1 = _player()
    uid2 = _player()
    conn = db()
    record_topg_vote(uid1, "1.2.3.4", conn=conn, reward_payload=LOOTBOX_PAYLOAD)
    cur = conn.cursor()
    cur.execute("SELECT id FROM vote_rewards WHERE user_id = ? LIMIT 1;", (uid1,))
    reward_id = int(cur.fetchone()["id"])
    ok, reason, _ = claim_vote_reward(uid2, reward_id, conn=conn)
    assert ok is False
    assert reason == "reward_not_found"
    conn.close()


def test_vote_link_contains_user_id(vote_db):
    uid = _player()
    url = topg_vote_url(uid)
    assert url == f"https://topg.org/ogame-private-servers/server-683112-{uid}#vote"
    broken = resolve_vote_url("https://topg.org/ogame-private-servers/server-683112#vote", uid)
    assert broken == f"https://topg.org/ogame-private-servers/server-683112-{uid}#vote"
    conn = db()
    state = get_vote_center_state(uid, conn=conn)
    topg = next(p for p in state["providers"] if p["provider_key"] == "topg")
    assert topg["vote_url"] == url
    conn.close()


def test_topg_postback_api_creates_pending(vote_db, monkeypatch):
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.get(f"/api/vote/topg/postback?p_resp={uid}&ip=198.51.100.1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ? AND status = 'pending';", (uid,))
    assert int(cur.fetchone()["c"]) == 1
    conn.close()


def test_vote_center_never_voted_shows_ready(vote_db):
    uid = _player()
    conn = db()
    state = get_vote_center_state(uid, conn=conn)
    for provider in state["providers"]:
        assert provider["last_vote_at"] is None
        assert provider["next_vote_at"] is None
        assert provider["can_vote_hint"] is True
        assert provider["can_vote_now"] is True
        assert provider["cooldown_remaining_sec"] == 0
    assert state["next_vote_at"] is None
    assert state["can_vote_now"] is True
    conn.close()


def test_vote_center_state_cooldown(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    record_topg_vote(uid, "1.2.3.4", conn=conn, now=now, reward_payload=LOOTBOX_PAYLOAD)
    state = get_vote_center_state(uid, conn=conn)
    topg = next(p for p in state["providers"] if p["provider_key"] == "topg")
    assert topg["last_vote_at"] == now
    assert topg["next_vote_at"] == now + TOPG_COOLDOWN_SEC
    assert topg["can_vote_hint"] is False
    assert topg["can_vote_now"] is False
    assert topg["cooldown_remaining_sec"] > 0
    assert len(state["pending_rewards"]) == 1
    conn.close()


def test_vote_center_cooldown_expired_ready_again(vote_db):
    uid = _player()
    conn = db()
    now = int(time.time())
    record_topg_vote(uid, "1.2.3.4", conn=conn, now=now, reward_payload=LOOTBOX_PAYLOAD)
    later = now + TOPG_COOLDOWN_SEC + 5
    from game.vote_rewards import _provider_vote_stats, list_enabled_providers

    providers = list_enabled_providers(conn=conn)
    topg_row = next(p for p in providers if p["provider_key"] == TOPG_PROVIDER)
    topg = _provider_vote_stats(uid, topg_row, conn=conn, now=later)
    assert topg["last_vote_at"] == now
    assert topg["next_vote_at"] is None
    assert topg["can_vote_hint"] is True
    assert topg["can_vote_now"] is True
    assert topg["cooldown_remaining_sec"] == 0
    conn.close()


def test_dev_postback_test_endpoint(vote_db, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("FLASK_DEBUG", "1")
    client, uid, _ = _login_client(vote_db, monkeypatch)
    res = client.post("/api/dev/topg/postback-test", json={"user_id": uid, "reward_payload": LOOTBOX_PAYLOAD})
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] is True
    assert data["vote_center"]["pending_count"] == 1


def test_gtop100_json_pingback_creates_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GTOP100_PINGBACK_KEY", GTOP100_PINGBACK_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.post("/api/vote/gtop100/pingback", json=_gtop100_json_payload(uid))
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 1
    conn = db()
    row = conn.execute(
        "SELECT status, provider FROM vote_rewards WHERE user_id = ?;",
        (uid,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert row["provider"] == GTOP100_PROVIDER
    conn.close()


def test_gtop100_form_pingback_creates_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GTOP100_PINGBACK_KEY", GTOP100_PINGBACK_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.post(
        "/api/vote/gtop100/pingback",
        data={
            "VoterIP": "123.123.123.123",
            "Successful": "0",
            "Reason": "Vote accepted",
            "pingUsername": str(uid),
            "pingbackkey": GTOP100_PINGBACK_TEST_KEY,
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 1
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_gtop100_wrong_pingback_key_rejected(vote_db, monkeypatch):
    monkeypatch.setenv("GTOP100_PINGBACK_KEY", GTOP100_PINGBACK_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.post(
        "/api/vote/gtop100/pingback",
        json=_gtop100_json_payload(uid, pingback_key="wrong-key"),
    )
    assert res.status_code == 403
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards;").fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_gtop100_wrong_site_id_rejected(vote_db, monkeypatch):
    monkeypatch.setenv("GTOP100_PINGBACK_KEY", GTOP100_PINGBACK_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    payload = _gtop100_json_payload(uid)
    payload["siteid"] = 999999
    res = client.post("/api/vote/gtop100/pingback", json=payload)
    assert res.status_code == 400
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards;").fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_gtop100_success_not_zero_no_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GTOP100_PINGBACK_KEY", GTOP100_PINGBACK_TEST_KEY)
    uid = _player()
    client, _, _ = _login_client(vote_db, monkeypatch)
    res = client.post("/api/vote/gtop100/pingback", json=_gtop100_json_payload(uid, success=1))
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 0
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_gtop100_non_numeric_ping_username_no_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GTOP100_PINGBACK_KEY", GTOP100_PINGBACK_TEST_KEY)
    client, _, _ = _login_client(vote_db, monkeypatch)
    payload = _gtop100_json_payload(1)
    payload["Common"][0][4]["pb_name"] = "not-a-user"
    res = client.post("/api/vote/gtop100/pingback", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["created"] == 0
    conn = db()
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards;").fetchone()["c"]
    assert int(count) == 0
    conn.close()


def test_gtop100_duplicate_within_12h_no_second_reward(vote_db, monkeypatch):
    monkeypatch.setenv("GTOP100_PINGBACK_KEY", GTOP100_PINGBACK_TEST_KEY)
    uid = _player()
    conn = db()
    now = int(time.time())
    _, created1 = record_provider_vote(
        GTOP100_PROVIDER,
        uid,
        "1.2.3.4",
        conn=conn,
        now=now,
        reward_payload=LOOTBOX_PAYLOAD,
    )
    _, created2 = record_provider_vote(
        GTOP100_PROVIDER,
        uid,
        "1.2.3.5",
        conn=conn,
        now=now + 60,
        reward_payload=LOOTBOX_PAYLOAD,
    )
    assert created1 is True
    assert created2 is False
    count = conn.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;", (uid,)).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_gtop100_cooldown_is_12_hours(vote_db):
    assert GTOP100_COOLDOWN_SEC == 12 * 60 * 60
    assert VOTE_PROVIDERS["gtop100"]["cooldown_seconds"] == 12 * 60 * 60


def test_gtop100_vote_link_contains_user_id(vote_db):
    uid = _player()
    conn = db()
    state = get_vote_center_state(uid, conn=conn)
    gtop100 = next(p for p in state["providers"] if p["provider_key"] == "gtop100")
    assert gtop100["vote_url"] == (
        f"https://gtop100.com/Ogame/server-106142?vote=1&pingUsername={uid}"
    )
    conn.close()


def test_claim_api_endpoint(vote_db, monkeypatch):
    client, login_uid, _ = _login_client(vote_db, monkeypatch)
    conn = db()
    record_topg_vote(login_uid, "1.2.3.4", conn=conn, reward_payload=LOOTBOX_PAYLOAD)
    cur = conn.cursor()
    cur.execute("SELECT id FROM vote_rewards WHERE user_id = ? LIMIT 1;", (login_uid,))
    reward_id = int(cur.fetchone()["id"])
    conn.commit()
    conn.close()

    res = client.post(
        "/api/vote/rewards/claim",
        json={"reward_id": reward_id, "request_id": str(uuid.uuid4())},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data.get("vote_center") is not None

    conn = db()
    assert _inventory_amount(login_uid, "container_basic", conn=conn) == 1
    conn.close()
