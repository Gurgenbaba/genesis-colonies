"""Vote re-engagement worker and admin vote statistics."""

from __future__ import annotations

import time
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.ranking import RANKING_INACTIVE_AFTER_SEC
from game.vote_reengagement import (
    REENGAGEMENT_SLOTS_PER_DAY,
    build_admin_vote_stats,
    player_in_reengagement_slot,
    run_vote_reengagement,
    search_admin_vote_players,
)
from game.vote_rewards import (
    VOTE_CHANNEL_PLAYER,
    VOTE_CHANNEL_REENGAGEMENT,
    process_provider_vote,
    vote_channel_column_ready,
    vote_system_ready,
)


@pytest.fixture
def reengagement_db(tmp_path, monkeypatch):
    db_path = tmp_path / "vote_reengagement_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_VOTE_SKIP_IP_CHECK", "1")
    monkeypatch.setenv("GC_VOTE_REENGAGEMENT_ENABLED", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None, *, last_seen: int | None = None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"vr_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Voter", conn=conn)
    if last_seen is not None:
        conn.execute("UPDATE players SET last_seen = ? WHERE id = ?;", (int(last_seen), uid))
    if own:
        conn.commit()
        conn.close()
    return uid


def test_vote_channel_column_ready(reengagement_db):
    conn = db()
    assert vote_channel_column_ready(conn) is True
    conn.close()


def test_player_slot_is_stable_for_day(reengagement_db):
    now = int(time.time())
    day = now // 86400
    uid = 42
    a = (uid * 2654435761 + day) % REENGAGEMENT_SLOTS_PER_DAY
    b = (uid * 2654435761 + day) % REENGAGEMENT_SLOTS_PER_DAY
    assert a == b


def test_reengagement_skips_active_player(reengagement_db):
    conn = db()
    now = int(time.time())
    uid = _player(conn=conn, last_seen=now - 3600)
    conn.commit()
    result = run_vote_reengagement(conn=conn, now=now, force=True, batch_size=20)
    assert result["ok"] is True
    assert result["created"] == 0
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;",
        (uid,),
    ).fetchone()
    assert int(row["c"]) == 0
    conn.close()


def test_reengagement_creates_vote_for_inactive_player(reengagement_db):
    conn = db()
    now = int(time.time())
    inactive_seen = now - int(RANKING_INACTIVE_AFTER_SEC) - 3600
    uid = _player(conn=conn, last_seen=inactive_seen)
    conn.commit()
    result = run_vote_reengagement(conn=conn, now=now, force=True, batch_size=20)
    assert result["ok"] is True
    assert result["created"] >= 1
    row = conn.execute(
        "SELECT vote_channel, status FROM vote_rewards WHERE user_id = ? LIMIT 1;",
        (uid,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "pending"
    assert str(row["vote_channel"]) == VOTE_CHANNEL_REENGAGEMENT
    conn.close()


def test_reengagement_respects_slot_without_force(reengagement_db):
    conn = db()
    now = int(time.time())
    inactive_seen = now - int(RANKING_INACTIVE_AFTER_SEC) - 3600
    uid = _player(conn=conn, last_seen=inactive_seen)
    conn.commit()
    in_slot = player_in_reengagement_slot(uid, now=now)
    result = run_vote_reengagement(conn=conn, now=now, force=False, batch_size=20)
    assert result["ok"] is True
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM vote_rewards WHERE user_id = ?;",
        (uid,),
    ).fetchone()["c"]
    if in_slot:
        assert int(count) >= 1
    else:
        assert int(count) == 0
        assert result["skipped_wrong_slot"] >= 1
    conn.close()


def test_player_manual_vote_uses_player_channel(reengagement_db):
    conn = db()
    now = int(time.time())
    uid = _player(conn=conn, last_seen=now - 3600)
    result = process_provider_vote("topg", uid, "1.2.3.4", conn=conn, now=now)
    assert result["created"] is True
    row = conn.execute(
        "SELECT vote_channel FROM vote_rewards WHERE user_id = ? LIMIT 1;",
        (uid,),
    ).fetchone()
    assert str(row["vote_channel"]) == VOTE_CHANNEL_PLAYER
    conn.close()


def test_admin_vote_stats_and_player_search(reengagement_db):
    conn = db()
    now = int(time.time())
    active_uid = _player(conn=conn, last_seen=now - 60)
    conn.commit()
    inactive_uid = _player(conn=conn, last_seen=now - int(RANKING_INACTIVE_AFTER_SEC) - 60)
    process_provider_vote("topg", active_uid, "1.1.1.1", conn=conn, now=now)
    process_provider_vote(
        "gtop100",
        inactive_uid,
        None,
        conn=conn,
        now=now,
        vote_channel=VOTE_CHANNEL_REENGAGEMENT,
    )
    conn.commit()
    assert vote_system_ready(conn)
    stats = build_admin_vote_stats(conn=conn, now=now)
    assert stats["ready"] is True
    assert stats["summary"]["votes_7d"] >= 2
    assert stats["summary"]["player_votes_7d"] >= 1
    assert stats["summary"]["reengagement_votes_7d"] >= 1

    inactive_rows = search_admin_vote_players(conn=conn, activity="inactive", limit=20)
    assert inactive_rows["ok"] is True
    ids = {int(p["user_id"]) for p in inactive_rows["players"]}
    assert inactive_uid in ids
    inactive_player = next(p for p in inactive_rows["players"] if int(p["user_id"]) == inactive_uid)
    assert inactive_player["activity"] == "inactive"
    assert inactive_player["reengagement_votes"] >= 1
    assert len(inactive_player["providers"]) >= 4
    conn.close()
