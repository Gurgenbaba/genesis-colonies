from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_planets_by_player,
    init_db,
)


@pytest.fixture()
def autoplay_v3_db(tmp_path, monkeypatch):
    db_path = tmp_path / "inactive_autoplay_gc2621.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _register_user() -> int:
    ok, err, user = create_user(f"gc2621_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    return int(user["id"])


def _seed_dormant(conn, uid: int) -> dict:
    ensure_player_and_homeworld(uid, player_name=f"Dorm{uid}", conn=conn)
    home = get_planets_by_player(uid, conn=conn)[0]
    conn.execute(
        "UPDATE players SET last_seen = ? WHERE id = ?;",
        (time.time() - 5 * 24 * 3600, uid),
    )
    conn.execute(
        """
        UPDATE planets
        SET metal = 500000, crystal = 500000, fuel_cells = 500000
        WHERE id = ?;
        """,
        (int(home["id"]),),
    )
    return {"player_id": uid, "planet_id": int(home["id"])}


def test_gc2621_personal_pace_is_deterministic_and_varied():
    from game.auto_empire import personality_for_player
    from game.inactive_autoplay import _action_domain_for_player, _next_action_delay_sec

    samples = []
    for pid in range(1, 50):
        personality = personality_for_player(pid)
        delay = _next_action_delay_sec(pid, personality, 4)
        domain = _action_domain_for_player(pid, personality, 4)
        assert delay == _next_action_delay_sec(pid, personality, 4)
        assert domain == _action_domain_for_player(pid, personality, 4)
        assert 5 * 60 <= delay <= 35 * 60
        samples.append((delay, domain))
    assert len({delay for delay, _ in samples}) > 5
    assert len({domain for _, domain in samples}) >= 2


def test_gc2621_one_progression_domain_per_decision(autoplay_v3_db):
    from game.inactive_autoplay import _run_player_economy

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        _seed_dormant(conn, uid)
        with patch("game.inactive_autoplay.plan_passive_planet_tick") as planner:
            planner.return_value = {
                "build": None,
                "research": None,
                "defense": None,
                "builds": [],
                "researches": [],
                "finished": {},
            }
            with patch("game.inactive_autoplay._maybe_join_world_boss") as boss:
                boss.return_value = {"ok": True, "joined": False}
                result = _run_player_economy(
                    conn, uid, now=time.time(), is_wake=True, action_seq=3
                )
        kwargs = planner.call_args.kwargs
        enabled = (
            int(bool(kwargs["allow_buildings"]))
            + int(bool(kwargs["allow_research"]))
            + int(bool(kwargs["allow_defense"]))
        )
        assert enabled == 1
        assert kwargs["allow_buildings"] is True
        assert kwargs["allow_ships"] is False
        assert result["action_domain"] == "building"
        assert result["action_seq"] == 4
        assert result["next_action_at"] > time.time()
        commit(conn)
    finally:
        conn.close()


def test_gc2621_personal_cooldown_finishes_due_without_enqueue(autoplay_v3_db):
    from game.inactive_autoplay import _run_player_economy

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        _seed_dormant(conn, uid)
        now = time.time()
        with patch("game.inactive_autoplay.plan_passive_planet_tick") as planner:
            planner.return_value = {"finished": {"buildings": 1}}
            with patch("game.inactive_autoplay._maybe_join_world_boss") as boss:
                boss.return_value = {"ok": True, "joined": False}
                result = _run_player_economy(
                    conn,
                    uid,
                    now=now,
                    action_seq=8,
                    next_action_at=now + 600,
                )
        kwargs = planner.call_args.kwargs
        assert kwargs["allow_buildings"] is False
        assert kwargs["allow_research"] is False
        assert kwargs["allow_defense"] is False
        assert kwargs["allow_ships"] is False
        assert result["enqueued"] is False
        assert result["finished_totals"]["buildings"] == 1
        assert result["action_seq"] == 8
        assert result["personal_cooldown"] is True
        commit(conn)
    finally:
        conn.close()


def test_gc2621_inactive_token_world_boss_participation(autoplay_v3_db):
    from game.fleet import add_planet_ships, get_planet_ships
    from game.inactive_autoplay import _maybe_join_world_boss
    from game.world_boss import list_contributions, spawn_world_boss

    uid = _register_user()
    conn = db()
    try:
        begin_write_transaction(conn)
        player = _seed_dormant(conn, uid)
        add_planet_ships(
            int(player["planet_id"]),
            uid,
            {"falcon_interceptor": 3},
            conn=conn,
        )
        before = get_planet_ships(int(player["planet_id"]), conn=conn)
        spawned = spawn_world_boss(
            "ancient_leviathan",
            conn=conn,
            galaxy=1,
            system=71,
            position=8,
            announce=False,
        )
        assert spawned["ok"], spawned
        event_id = int(spawned["event"]["id"])

        joined = _maybe_join_world_boss(conn, uid, now=time.time())
        assert joined["ok"] is True
        assert joined["joined"] is True
        assert int(joined["damage"]) > 0
        assert sum(int(v) for v in joined["ships"].values()) == 1
        assert get_planet_ships(int(player["planet_id"]), conn=conn) == before

        board = list_contributions(event_id, conn=conn, limit=20)
        mine = next(row for row in board if int(row["player_id"]) == uid)
        assert int(mine["waves"]) == 1
        assert int(mine["damage"]) > 0

        again = _maybe_join_world_boss(conn, uid, now=time.time() + 301)
        assert again["joined"] is False
        board2 = list_contributions(event_id, conn=conn, limit=20)
        mine2 = next(row for row in board2 if int(row["player_id"]) == uid)
        assert int(mine2["waves"]) == 1
        commit(conn)
    finally:
        conn.close()
