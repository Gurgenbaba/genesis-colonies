"""GC-PERF-PASS-04 — expansion limit reads must not self-heal/persist."""
from __future__ import annotations

from unittest.mock import patch

pytest_plugins = ["tests.test_game_state_live"]


def test_read_only_mandate_state_virtualizes_legacy_without_persisting(game_client):
    from game.db import db
    from game.models import get_homeworld
    from game.planet_evolution.imperial_mandates import ensure_player_mandate_state

    _client, uid = game_client
    conn = db()
    try:
        hw = get_homeworld(int(uid), conn=conn)
        assert hw
        conn.execute("UPDATE planets SET planet_level = 40 WHERE id = ?;", (int(hw["id"]),))
        conn.execute(
            "UPDATE players SET expansion_legacy_slots = 0, expansion_legacy_migrated = 0 WHERE id = ?;",
            (int(uid),),
        )
        conn.execute("DELETE FROM player_imperial_mandates WHERE player_id = ?;", (int(uid),))
        conn.commit()

        state = ensure_player_mandate_state(int(uid), conn=conn, persist=False)
        assert state["legacy_slots"] == 2
        assert state["late_slots"] == 2
        assert state["earned_mandates"][:2] == ["survey", "presence"]

        row = conn.execute(
            "SELECT expansion_legacy_slots, expansion_legacy_migrated FROM players WHERE id = ?;",
            (int(uid),),
        ).fetchone()
        assert int(row["expansion_legacy_slots"] or 0) == 0
        assert int(row["expansion_legacy_migrated"] or 0) == 0
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM player_imperial_mandates WHERE player_id = ?;",
            (int(uid),),
        ).fetchone()
        assert int(count["n"] or 0) == 0

        persisted = ensure_player_mandate_state(int(uid), conn=conn, persist=True)
        assert persisted["legacy_slots"] == state["legacy_slots"]
        assert persisted["late_slots"] == state["late_slots"]
        row2 = conn.execute(
            "SELECT expansion_legacy_slots, expansion_legacy_migrated FROM players WHERE id = ?;",
            (int(uid),),
        ).fetchone()
        assert int(row2["expansion_legacy_slots"] or 0) == 2
        assert int(row2["expansion_legacy_migrated"] or 0) == 1
    finally:
        conn.rollback()
        conn.close()


def test_game_state_has_no_expansion_self_heal_write(game_client):
    import game.live_state as live_state
    from game.db import db

    client, uid = game_client
    conn = db()
    try:
        conn.execute(
            "UPDATE players SET expansion_legacy_slots = 0, expansion_legacy_migrated = 0 WHERE id = ?;",
            (int(uid),),
        )
        conn.commit()
    finally:
        conn.close()

    writes = []
    def callback(statement):
        sql = " ".join(str(statement or "").strip().split())
        upper = sql.upper()
        if upper.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            writes.append(upper)

    def attach(conn):
        try:
            conn.set_trace_callback(callback)
        except Exception:
            pass

    with patch.object(live_state, "attach_request_perf_sql_trace", side_effect=attach):
        resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert not any("EXPANSION_LEGACY" in sql for sql in writes)
