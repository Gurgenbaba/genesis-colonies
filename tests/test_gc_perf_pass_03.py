"""GC-PERF-PASS-03 — keep diet polling read-heavy, not write-heavy."""

from __future__ import annotations

pytest_plugins = ["tests.test_game_state_live"]


def test_battle_pass_serialize_synthesizes_ops_without_writes(game_client):
    from game.battle_pass import (
        DAILY_OP_KEYS,
        WEEKLY_OP_KEYS,
        get_active_season,
        serialize_for_client,
    )
    from game.db import db

    _client, uid = game_client
    conn = db()
    try:
        # Ensure player/season state exists, then deliberately remove current Ops.
        state = serialize_for_client(int(uid), conn=conn)
        assert state.get("ready") is True
        conn.commit()
        season = get_active_season(conn)
        assert season is not None
        conn.execute(
            "DELETE FROM battle_pass_ops_progress WHERE player_id = ? AND season_id = ?;",
            (int(uid), int(season["id"])),
        )
        conn.commit()

        writes = []

        def trace(statement):
            sql = str(statement or "").lstrip().upper()
            if sql.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
                writes.append(sql)

        conn.set_trace_callback(trace)
        fresh = serialize_for_client(int(uid), conn=conn)
        conn.set_trace_callback(None)

        assert writes == []
        ops = fresh.get("ops") or {}
        assert len(ops.get("daily") or []) == len(DAILY_OP_KEYS)
        assert len(ops.get("weekly") or []) == len(WEEKLY_OP_KEYS)
        assert all(int(row.get("progress") or 0) == 0 for row in ops.get("daily") or [])
    finally:
        conn.close()


def test_game_state_serializes_battle_pass_once(game_client, monkeypatch):
    import game.battle_pass as battle_pass

    client, _uid = game_client
    real = battle_pass.serialize_for_client
    calls = []

    def wrapped(player_id, *, conn, now=None, include_tracks=False):
        calls.append((int(player_id), bool(include_tracks)))
        return real(
            player_id,
            conn=conn,
            now=now,
            include_tracks=include_tracks,
        )

    monkeypatch.setattr(battle_pass, "serialize_for_client", wrapped)
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert len(calls) == 1


def test_timekeeper_read_missing_row_is_zero_without_insert(game_client):
    from game.db import db
    from game.timekeeper import credit, get_balance

    _client, uid = game_client
    conn = db()
    try:
        conn.execute("DELETE FROM timekeeper_balances WHERE player_id = ?;", (int(uid),))
        conn.commit()
        writes = []

        def trace(statement):
            sql = str(statement or "").lstrip().upper()
            if sql.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
                writes.append(sql)

        conn.set_trace_callback(trace)
        assert get_balance(int(uid), conn=conn) == 0
        conn.set_trace_callback(None)
        assert writes == []
        row = conn.execute(
            "SELECT 1 FROM timekeeper_balances WHERE player_id = ?;", (int(uid),)
        ).fetchone()
        assert row is None

        # Real mutation remains authoritative and creates the row.
        assert credit(int(uid), 60, "perf-pass-03-test", conn=conn) == 60
        assert get_balance(int(uid), conn=conn) == 60
    finally:
        conn.rollback()
        conn.close()
