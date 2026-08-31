"""GC-PERF-STATE-007 — keep diet nav attention read-only and de-duplicated."""

from __future__ import annotations

import time
import uuid

import pytest

from game.db import db
from game.live_state import nav_badges_for_game_state
from game.login_rewards import day_bucket, login_reward_available_for_nav
from game.models import create_user, ensure_player_and_homeworld, init_db


@pytest.fixture
def state_007_db(tmp_path, monkeypatch):
    db_path = tmp_path / "state_007.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_VOTE_SKIP_IP_CHECK", "1")
    monkeypatch.setenv("TOPG_STRICT_IP_CHECK", "0")
    monkeypatch.setenv("SECRET_KEY", "state-007-test-secret-key-not-production")

    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn) -> int:
    ok, err, user = create_user(f"state007_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="State 007", conn=conn)
    conn.commit()
    return uid


def test_new_player_login_badge_is_available_without_creating_progress(state_007_db):
    conn = db()
    try:
        uid = _player(conn)
        before = conn.execute(
            "SELECT 1 FROM login_reward_progress WHERE player_id = ? LIMIT 1;",
            (uid,),
        ).fetchone()
        assert before is None

        badges = nav_badges_for_game_state(
            uid,
            conn=conn,
            battle_pass={"ready": True, "claimable_count": 0},
        )

        assert badges["login_rewards"]["active"] is True
        assert badges["login_rewards"]["count"] == 1
        after = conn.execute(
            "SELECT 1 FROM login_reward_progress WHERE player_id = ? LIMIT 1;",
            (uid,),
        ).fetchone()
        assert after is None
    finally:
        conn.close()


def test_missed_streak_attention_does_not_reset_progress(state_007_db):
    conn = db()
    try:
        uid = _player(conn)
        now = time.time()
        old_bucket = day_bucket(now) - 2
        conn.execute(
            """
            INSERT INTO login_reward_progress (
                player_id, cycle_id, cycle_started_at, current_day,
                last_claim_day_bucket, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (uid, "state007_cycle", now - 86400 * 10, 5, old_bucket, now - 86400 * 2),
        )
        conn.commit()
        before = dict(
            conn.execute(
                "SELECT * FROM login_reward_progress WHERE player_id = ?;",
                (uid,),
            ).fetchone()
        )

        assert login_reward_available_for_nav(uid, conn=conn, now=now) is True

        after = dict(
            conn.execute(
                "SELECT * FROM login_reward_progress WHERE player_id = ?;",
                (uid,),
            ).fetchone()
        )
        assert after == before
    finally:
        conn.close()


def test_nav_liveops_sources_are_not_double_loaded_on_normal_path(state_007_db, monkeypatch):
    import game.server_events as server_events
    import game.world_boss as world_boss

    conn = db()
    try:
        uid = _player(conn)
        # Deterministic: cold factor cache must not hide a second list_active_events.
        server_events._FACTOR_CACHE = (0.0, {})
        calls = {"server": 0, "world_boss": 0}
        original_server = server_events.list_active_events
        original_world_boss = world_boss.list_active_events

        def counted_server(*args, **kwargs):
            calls["server"] += 1
            return original_server(*args, **kwargs)

        def counted_world_boss(*args, **kwargs):
            calls["world_boss"] += 1
            return original_world_boss(*args, **kwargs)

        monkeypatch.setattr(server_events, "list_active_events", counted_server)
        monkeypatch.setattr(world_boss, "list_active_events", counted_world_boss)

        nav_badges_for_game_state(
            uid,
            conn=conn,
            battle_pass={"ready": True, "claimable_count": 0},
        )

        assert calls["server"] == 1
        assert calls["world_boss"] == 1
    finally:
        conn.close()
