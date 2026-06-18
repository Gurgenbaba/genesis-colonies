"""GC-702 — Navigation action badges in /api/game-state."""

from __future__ import annotations

import importlib
import os
import time
import uuid

import pytest

from game.db import db
from game.galactic_directives.state import count_pending_government_votes
from game.live_state import nav_badges_for_game_state
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.vote_rewards import (
    count_voteable_providers,
    list_enabled_providers,
    record_provider_vote,
    vote_system_ready,
)


@pytest.fixture
def nav_badges_db(tmp_path, monkeypatch):
    db_path = tmp_path / "nav_badges_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_VOTE_SKIP_IP_CHECK", "1")
    monkeypatch.setenv("TOPG_STRICT_IP_CHECK", "0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")

    import game.db as gdb

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
    ok, err, user = create_user(f"nav_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Navigator", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _player_galaxy(uid: int, conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    planets = get_planets_by_player(uid, conn=conn)
    galaxy = int(planets[0]["galaxy"])
    if own:
        conn.close()
    return galaxy


def _seed_open_cycle(conn, *, galaxy: int, player_id: int) -> int:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO gd_cycles (
            galaxy, year, month, vote_start_at, vote_end_at,
            effect_start_at, effect_end_at, status, created_at, updated_at
        ) VALUES (?, 2026, 6, ?, ?, ?, ?, 'vote_open', ?, ?);
        """,
        (galaxy, now - 3600, now + 3600, now + 7200, now + 86400 * 30, now, now),
    )
    conn.commit()
    return int(
        conn.execute(
            "SELECT id FROM gd_cycles WHERE galaxy = ? ORDER BY id DESC LIMIT 1;",
            (galaxy,),
        ).fetchone()["id"]
    )


def test_vote_center_badge_active_when_providers_voteable(nav_badges_db):
    uid = _player()
    conn = db()
    try:
        assert vote_system_ready(conn)
        expected = count_voteable_providers(uid, conn=conn)
        assert expected >= 1
        badges = nav_badges_for_game_state(uid, conn=conn)
        assert badges["vote_center"]["active"] is True
        assert badges["vote_center"]["count"] == expected
        assert badges["vote_center"]["label"] == str(expected)
    finally:
        conn.close()


def test_vote_center_badge_clears_after_vote(nav_badges_db):
    uid = _player()
    conn = db()
    try:
        providers = list_enabled_providers(conn=conn)
        assert providers
        before = count_voteable_providers(uid, conn=conn)
        assert before >= 1
        record_provider_vote(
            str(providers[0]["provider_key"]),
            uid,
            "127.0.0.1",
            conn=conn,
        )
        conn.commit()
        after = count_voteable_providers(uid, conn=conn)
        badges = nav_badges_for_game_state(uid, conn=conn)
        if after == 0:
            assert badges["vote_center"]["active"] is False
            assert badges["vote_center"]["count"] == 0
        else:
            assert badges["vote_center"]["active"] is True
            assert badges["vote_center"]["count"] == after
            assert badges["vote_center"]["count"] < before
    finally:
        conn.close()


def test_government_badge_open_cycle_without_vote(nav_badges_db):
    uid = _player()
    conn = db()
    try:
        galaxy = _player_galaxy(uid, conn=conn)
        _seed_open_cycle(conn, galaxy=galaxy, player_id=uid)
        assert count_pending_government_votes(uid, conn=conn) == 1
        badges = nav_badges_for_game_state(uid, conn=conn)
        assert badges["government"]["active"] is True
        assert badges["government"]["count"] == 1
        assert badges["government"]["label"] == "!"
    finally:
        conn.close()


def test_government_badge_hidden_after_vote(nav_badges_db):
    uid = _player()
    conn = db()
    try:
        galaxy = _player_galaxy(uid, conn=conn)
        cycle_id = _seed_open_cycle(conn, galaxy=galaxy, player_id=uid)
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO gd_votes (cycle_id, galaxy, player_id, directive_key, created_at, updated_at)
            VALUES (?, ?, ?, 'industrial', ?, ?);
            """,
            (cycle_id, galaxy, uid, now, now),
        )
        conn.commit()
        badges = nav_badges_for_game_state(uid, conn=conn)
        assert badges["government"]["active"] is False
        assert badges["government"]["count"] == 0
    finally:
        conn.close()


def test_api_game_state_includes_nav_badges(nav_badges_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    uid = _player()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get("/api/game-state")
    assert r.status_code == 200
    state = r.get_json()
    assert state["ok"] is True
    assert "nav_badges" in state
    assert "vote_center" in state["nav_badges"]
    assert "government" in state["nav_badges"]
    assert "referrals" in state["nav_badges"]
    assert isinstance(state["nav_badges"]["vote_center"]["active"], bool)
    assert isinstance(state["nav_badges"]["government"]["active"], bool)
    assert isinstance(state["nav_badges"]["referrals"]["active"], bool)
