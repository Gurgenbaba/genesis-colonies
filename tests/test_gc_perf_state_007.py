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



def test_nav_badges_reuse_supplied_live_events_snapshot(state_007_db, monkeypatch):
    import game.overview_page as overview_page

    conn = db()
    try:
        uid = _player(conn)

        def unexpected_rebuild(*args, **kwargs):
            raise AssertionError("LiveOps snapshot must not be rebuilt for nav badges")

        monkeypatch.setattr(
            overview_page,
            "build_overview_live_events",
            unexpected_rebuild,
        )

        badges = nav_badges_for_game_state(
            uid,
            conn=conn,
            battle_pass={"ready": True, "claimable_count": 0},
            live_events=[
                {"kind": "world_boss", "id": 1},
                {"kind": "server_event", "id": 2},
            ],
        )

        assert badges["world_boss"]["active"] is True
        assert badges["world_boss"]["count"] == 1
        assert badges["live_events"]["active"] is True
        assert badges["live_events"]["count"] == 2
    finally:
        conn.close()


def test_game_state_builds_live_events_once_and_shares_snapshot_with_nav():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    block = src.split("def _payload_from_live_context(", 1)[1].split(
        "\ndef _build_game_state_payload(",
        1,
    )[0]

    assert block.count("build_overview_live_events(") == 1
    assert "live_events_snapshot = build_overview_live_events(" in block
    assert "payload[\"live_events\"] = live_events_snapshot" in block
    assert "live_events=live_events_snapshot" in block



def test_server_event_serializers_reuse_preloaded_active_rows(monkeypatch):
    import game.server_events as server_events

    rows = [
        {
            "id": 91,
            "slug": "shared_rows",
            "title": "Shared Rows",
            "title_key": "",
            "starts_at": 100,
            "ends_at": 300,
            "effects": [{"kind": "production_mult", "mult": 2.0}],
        }
    ]

    def unexpected_reload(*args, **kwargs):
        raise AssertionError("preloaded Server Event rows must not be reloaded")

    monkeypatch.setattr(server_events, "list_active_events", unexpected_reload)

    state = server_events.serialize_active_events(
        now=150.0,
        conn=object(),
        active_events=rows,
    )
    banner = server_events.active_events_banner(
        now=150.0,
        conn=object(),
        locale="de",
        active_events=rows,
    )

    assert state["production_mult"] == pytest.approx(2.0)
    assert len(state["events"]) == 1
    assert len(banner) == 1
    assert banner[0]["slug"] == "shared_rows"


def test_game_state_shares_active_server_event_rows_across_liveops_serializers():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app.py").read_text(
        encoding="utf-8"
    )
    block = src.split("def _payload_from_live_context(", 1)[1].split(
        "\ndef _build_game_state_payload(",
        1,
    )[0]

    assert block.count("server_event_rows = list_server_events(conn=conn)") == 1
    assert "server_events=server_event_rows" in block
    assert "active_events=server_event_rows" in block


def test_battle_pass_nav_count_matches_full_serializer(state_007_db):
    from game.battle_pass import (
        apply_op_progress,
        claim_battle_pass_reward,
        claimable_count_for_nav,
        credit_xp,
        get_active_season,
        serialize_for_client,
        unlock_premium,
    )

    conn = db()
    try:
        uid = _player(conn)
        season = get_active_season(conn)
        assert season is not None

        # Reach several levels, unlock premium, claim one track reward, and
        # complete a daily Op so all claimable sources participate.
        credited = credit_xp(uid, int(season["xp_per_level"]) * 3, conn=conn)
        assert credited["granted"] is True
        ok, reason, _ = unlock_premium(uid, conn=conn, source="state007")
        assert ok, reason
        ok, reason, _ = claim_battle_pass_reward(uid, 1, "free", conn=conn)
        assert ok, reason
        for _ in range(3):
            apply_op_progress(uid, "building_finish", conn=conn)

        full = serialize_for_client(uid, conn=conn, include_tracks=False)
        fast = claimable_count_for_nav(uid, conn=conn)
        assert fast == int(full["claimable_count"])
        assert fast > 0

        badges = nav_badges_for_game_state(uid, conn=conn, live_events=[])
        assert badges["premium"]["count"] == fast
    finally:
        conn.close()


def test_battle_pass_nav_probe_is_read_only_for_new_player(state_007_db):
    from game.battle_pass import claimable_count_for_nav, ensure_default_season

    conn = db()
    try:
        uid = _player(conn)
        # Seed the canonical season once outside the probe. The probe itself must
        # not create player_battle_pass progress rows.
        sid = ensure_default_season(conn)
        assert sid is not None
        conn.commit()
        before = conn.execute(
            "SELECT 1 FROM player_battle_pass WHERE player_id = ? LIMIT 1;",
            (uid,),
        ).fetchone()
        assert before is None

        assert claimable_count_for_nav(uid, conn=conn) == 0

        after = conn.execute(
            "SELECT 1 FROM player_battle_pass WHERE player_id = ? LIMIT 1;",
            (uid,),
        ).fetchone()
        assert after is None
    finally:
        conn.close()


def test_nav_probe_does_not_serialize_full_battle_pass():
    import inspect
    import game.live_state as live_state

    source = inspect.getsource(live_state.nav_badges_for_game_state)
    assert "claimable_count_for_nav" in source
    assert "serialize_for_client as bp_serialize" not in source
