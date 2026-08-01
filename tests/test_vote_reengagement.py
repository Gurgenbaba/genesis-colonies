"""
Vote re-engagement kill regressions.

Synthetic grants are removed. Historical ``vote_channel=reengagement`` rows may
remain for reporting but must not block real provider cooldowns.
"""

from __future__ import annotations

import importlib
import time
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.vote_rewards import (
    VOTE_CHANNEL_PLAYER,
    VOTE_CHANNEL_REENGAGEMENT,
    build_admin_vote_stats,
    can_process_provider_vote,
    get_provider_cooldown_status,
    handle_vote_visit,
    list_enabled_providers,
    process_provider_vote,
    search_admin_vote_players,
    vote_channel_column_ready,
    vote_system_ready,
)


@pytest.fixture
def vote_admin_db(tmp_path, monkeypatch):
    db_path = tmp_path / "vote_admin_stats_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_VOTE_SKIP_IP_CHECK", "1")
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


def _insert_historical_synthetic(
    conn,
    *,
    user_id: int,
    provider: str,
    voted_at: int,
    next_vote_at: int,
) -> None:
    """Insert a legacy reengagement row without going through the removed grant path."""
    assert vote_channel_column_ready(conn)
    conn.execute(
        """
        INSERT INTO vote_rewards (
            provider, user_id, vote_ip, provider_ref, status,
            reward_key, reward_payload_json, voted_at, created_at,
            provider_next_vote_at, vote_channel
        ) VALUES (?, ?, NULL, ?, 'pending', 'standard_box', '{}', ?, ?, ?, ?);
        """,
        (
            str(provider),
            int(user_id),
            f"legacy-re:{provider}:{user_id}:{voted_at}",
            int(voted_at),
            int(voted_at),
            int(next_vote_at),
            VOTE_CHANNEL_REENGAGEMENT,
        ),
    )


def test_vote_reengagement_module_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("game.vote_reengagement")


def test_run_vote_reengagement_symbol_gone():
    import game.vote_rewards as vr

    assert not hasattr(vr, "run_vote_reengagement")


def test_historical_reengagement_does_not_block_player_cooldown(vote_admin_db):
    """
    Cooldown fields: provider_next_vote_at (preferred) else voted_at + cooldown_sec.
    Scope: per user + provider (not global across providers).
    Checked on Vote Center visit/click via handle_vote_visit → process_provider_vote.
    Historical synthetic rows must not drive that cooldown.
    """
    conn = db()
    now = int(time.time())
    uid = _player(conn=conn, last_seen=now - 60)
    conn.commit()

    providers = {str(p["provider_key"]): p for p in list_enabled_providers(conn=conn)}
    topg = providers["topg"]
    gtop = providers["gtop100"]

    # Synthetic topg grant with a far-future next_vote_at — must be ignored for cooldown.
    _insert_historical_synthetic(
        conn,
        user_id=uid,
        provider="topg",
        voted_at=now - 60,
        next_vote_at=now + 7 * 86400,
    )
    conn.commit()

    assert can_process_provider_vote(uid, topg, conn=conn, now=now) is True
    cd = get_provider_cooldown_status(uid, topg, conn=conn, now=now)
    assert cd["can_vote"] is True
    assert cd["cooldown_remaining_sec"] == 0

    # Other providers unaffected either way (provider-specific).
    assert can_process_provider_vote(uid, gtop, conn=conn, now=now) is True

    ok, created, reason, remaining = handle_vote_visit(uid, "topg", conn=conn, now=now)
    assert ok is True
    assert created is True
    assert reason == "reward_pending"
    assert remaining == 0

    row = conn.execute(
        """
        SELECT vote_channel FROM vote_rewards
        WHERE user_id = ? AND provider = 'topg' AND vote_channel = ?
        ORDER BY voted_at DESC LIMIT 1;
        """,
        (uid, VOTE_CHANNEL_PLAYER),
    ).fetchone()
    assert row is not None
    assert str(row["vote_channel"]) == VOTE_CHANNEL_PLAYER

    # After a real player visit, cooldown IS active for that provider only.
    assert can_process_provider_vote(uid, topg, conn=conn, now=now + 1) is False
    assert can_process_provider_vote(uid, gtop, conn=conn, now=now + 1) is True
    conn.close()


def test_process_provider_vote_rejects_reengagement_channel_write(vote_admin_db):
    conn = db()
    now = int(time.time())
    uid = _player(conn=conn, last_seen=now - 60)
    result = process_provider_vote(
        "topg",
        uid,
        "1.2.3.4",
        conn=conn,
        now=now,
        vote_channel=VOTE_CHANNEL_REENGAGEMENT,
    )
    assert result["created"] is True
    row = conn.execute(
        "SELECT vote_channel FROM vote_rewards WHERE user_id = ? ORDER BY id DESC LIMIT 1;",
        (uid,),
    ).fetchone()
    # Reengagement channel is no longer writable — coerced to player.
    assert str(row["vote_channel"]) == VOTE_CHANNEL_PLAYER
    conn.close()


def test_admin_stats_distinguish_external_and_historical_synthetic(vote_admin_db):
    conn = db()
    now = int(time.time())
    active_uid = _player(conn=conn, last_seen=now - 60)
    conn.commit()
    inactive_uid = _player(conn=conn, last_seen=now - 10 * 86400)
    conn.commit()

    process_provider_vote("topg", active_uid, "1.1.1.1", conn=conn, now=now)
    _insert_historical_synthetic(
        conn,
        user_id=inactive_uid,
        provider="gtop100",
        voted_at=now - 120,
        next_vote_at=now + 3600,
    )
    conn.commit()

    assert vote_system_ready(conn)
    stats = build_admin_vote_stats(conn=conn, now=now)
    assert stats["ready"] is True
    assert stats["summary"]["external_votes_7d"] >= 1
    assert stats["summary"]["historical_synthetic_7d"] >= 1
    assert stats["summary"]["rewards_granted_7d"] >= 2
    assert "reengagement_enabled" not in stats
    assert "current_slot" not in stats

    inactive_rows = search_admin_vote_players(conn=conn, activity="inactive", limit=20)
    assert inactive_rows["ok"] is True
    inactive_player = next(
        p for p in inactive_rows["players"] if int(p["user_id"]) == inactive_uid
    )
    assert inactive_player["historical_synthetic_votes"] >= 1
    assert "reengagement_slot" not in inactive_player
    conn.close()
