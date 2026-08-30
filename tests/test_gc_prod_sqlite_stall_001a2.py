"""GC-PROD-SQLITE-STALL-001A.2 — presence write throttle (no BEGIN when fresh)."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db
from game.models import (
    ONLINE_WINDOW_SEC,
    clear_presence_local_for_tests,
    create_user,
    ensure_player_and_homeworld,
    init_db,
    touch_player_online,
)


@pytest.fixture()
def presence_db(tmp_path, monkeypatch):
    db_path = tmp_path / "presence_throttle.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_PRESENCE_TOUCH_INTERVAL_SEC", "30")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    clear_presence_local_for_tests()
    yield
    clear_presence_local_for_tests()
    gdb._DB_PATH = None


def _register() -> int:
    ok, err, user = create_user(f"pres_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name=f"Pres{uid}", conn=conn)
        commit(conn)
    finally:
        conn.close()
    return uid


def _last_seen(uid: int) -> int:
    conn = db()
    try:
        row = conn.execute(
            "SELECT last_seen FROM players WHERE id = ?;", (int(uid),)
        ).fetchone()
        return int(row["last_seen"] or 0) if row else 0
    finally:
        conn.close()


def _set_last_seen(uid: int, ts: float) -> None:
    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (int(ts), int(uid)),
        )
        commit(conn)
    finally:
        conn.close()


def _count_begins(monkeypatch) -> dict:
    from game import models as models_mod

    real = models_mod.begin_write_transaction
    state = {"n": 0}

    def wrapped(conn, *, retries=12):
        state["n"] += 1
        return real(conn, retries=retries)

    monkeypatch.setattr(models_mod, "begin_write_transaction", wrapped)
    return state


def test_first_touch_writes(presence_db, monkeypatch):
    uid = _register()
    _set_last_seen(uid, 0)
    clear_presence_local_for_tests(uid)
    begins = _count_begins(monkeypatch)

    before = _last_seen(uid)
    touch_player_online(uid)
    after = _last_seen(uid)

    assert begins["n"] == 1
    assert after > before
    assert after >= int(time.time()) - 2


def test_second_touch_within_interval_no_write(presence_db, monkeypatch):
    uid = _register()
    _set_last_seen(uid, 0)
    clear_presence_local_for_tests(uid)
    touch_player_online(uid)
    stamped = _last_seen(uid)

    begins = _count_begins(monkeypatch)
    touch_player_online(uid)
    touch_player_online(uid)

    assert begins["n"] == 0
    assert _last_seen(uid) == stamped


def test_touch_after_interval_writes_again(presence_db, monkeypatch):
    uid = _register()
    clear_presence_local_for_tests(uid)
    # Stale beyond interval, local cold.
    _set_last_seen(uid, int(time.time()) - 120)
    begins = _count_begins(monkeypatch)

    touch_player_online(uid)
    assert begins["n"] == 1
    first = _last_seen(uid)

    clear_presence_local_for_tests(uid)
    _set_last_seen(uid, int(time.time()) - 120)
    begins["n"] = 0
    touch_player_online(uid)
    assert begins["n"] == 1
    assert _last_seen(uid) >= first


def test_players_independent(presence_db, monkeypatch):
    a = _register()
    b = _register()
    _set_last_seen(a, 0)
    _set_last_seen(b, 0)
    clear_presence_local_for_tests()

    touch_player_online(a)
    stamped_a = _last_seen(a)
    assert _last_seen(b) == 0

    begins = _count_begins(monkeypatch)
    touch_player_online(b)
    assert begins["n"] == 1
    assert _last_seen(a) == stamped_a
    assert _last_seen(b) > 0

    begins["n"] = 0
    touch_player_online(a)
    assert begins["n"] == 0


def test_cache_cold_still_respects_db_freshness(presence_db, monkeypatch):
    """Restart / empty local cache: fresh DB last_seen → no BEGIN IMMEDIATE."""
    uid = _register()
    now = int(time.time())
    _set_last_seen(uid, now)
    clear_presence_local_for_tests()  # cold cache

    begins = _count_begins(monkeypatch)
    touch_player_online(uid)
    assert begins["n"] == 0
    assert _last_seen(uid) == now


def test_roster_release_even_when_last_seen_fresh(presence_db, monkeypatch):
    from game.inactive_autoplay import (
        ROSTER_KEY,
        get_roster_snapshot,
        set_inactive_autoplay_enabled,
    )
    from game.runtime_state import set_runtime_value

    uid = _register()
    now = int(time.time())
    conn = db()
    try:
        begin_write_transaction(conn)
        set_inactive_autoplay_enabled(True, conn=conn)
        conn.execute("UPDATE players SET last_seen = ? WHERE id = ?;", (now, uid))
        set_runtime_value(
            ROSTER_KEY,
            json.dumps(
                [
                    {
                        "player_id": uid,
                        "joined_at": now - 100,
                        "last_ticked_at": now - 10,
                        "builds_done": 0,
                        "research_done": 0,
                        "defense_done": 0,
                    }
                ]
            ),
            conn=conn,
        )
        commit(conn)
    finally:
        conn.close()
    clear_presence_local_for_tests(uid)

    begins = _count_begins(monkeypatch)
    touch_player_online(uid)
    assert begins["n"] == 1

    conn = db()
    try:
        ids = {int(r["player_id"]) for r in get_roster_snapshot(conn=conn)}
        assert uid not in ids
    finally:
        conn.close()


def test_online_window_not_falsely_inactive(presence_db):
    """30s presence cadence stays well inside ONLINE_WINDOW_SEC (5m)."""
    assert _presence_interval() < ONLINE_WINDOW_SEC
    assert ONLINE_WINDOW_SEC // _presence_interval() >= 5
    uid = _register()
    _set_last_seen(uid, 0)
    clear_presence_local_for_tests(uid)
    touch_player_online(uid)
    # Immediately still "online" for HUD window.
    cutoff = int(time.time()) - ONLINE_WINDOW_SEC
    assert _last_seen(uid) >= cutoff


def _presence_interval() -> int:
    from game.models import _presence_touch_interval_sec

    return int(_presence_touch_interval_sec())
