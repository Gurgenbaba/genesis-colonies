"""GC-PERF-FLEET-DEADLINE-005 — expired online fleets never wait on a fresh 60s worker heartbeat."""

from __future__ import annotations

import time
from pathlib import Path

from game.db import db
from game.fleet import process_fleet_tick, send_fleet
from game.fleet_worker import is_fleet_worker_heartbeat_fresh, record_fleet_worker_result
from game.logic import read_player_live_state_for_poll
from game.models import get_planets_by_player
from tests.test_fleet import (
    _expedition_returning_with_loot,
    _force_expedition_stay_end,
    _force_outbound_arrival,
    _fund_planet,
    _planet_coords,
    _player,
    _seed_ships,
)

pytest_plugins = ("tests.test_fleet",)


def _stamp_fresh_fleet_worker(conn) -> None:
    record_fleet_worker_result(
        {
            "ok": True,
            "processed_arrivals": 0,
            "processed_returns": 0,
            "processed_holding": 0,
            "duration_ms": 1,
            "errors": [],
        },
        source="test_fresh_worker",
        conn=conn,
    )
    conn.commit()


def test_fresh_worker_heartbeat_does_not_leave_due_expedition_return_at_zero(fleet_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        fleet_id, _rewards, _origin_before = _expedition_returning_with_loot(
            conn, uid, pid
        )
        conn.execute(
            "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
            (time.time() - 1.0, int(fleet_id)),
        )
        conn.commit()

        _stamp_fresh_fleet_worker(conn)
        assert is_fleet_worker_heartbeat_fresh(conn=conn) is True

        read_player_live_state_for_poll(uid, conn=conn)

        row = conn.execute(
            "SELECT status FROM fleet_movements WHERE id = ?;",
            (int(fleet_id),),
        ).fetchone()
        assert row is not None
        assert row["status"] == "completed"
    finally:
        conn.close()


def test_fresh_worker_heartbeat_does_not_delay_expedition_holding_report(fleet_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        g, s, _ = _planet_coords(pid, conn=conn)
        cur = conn.cursor()
        _fund_planet(cur, pid)
        _seed_ships(pid, uid, {"solar_skiff": 2}, conn=conn)
        conn.commit()

        ok, reason, result = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=g,
            target_system=s,
            target_position=16,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            conn=conn,
        )
        assert ok, reason
        fleet_id = int(result["fleet"]["id"])
        _force_outbound_arrival(conn, fleet_id)
        first = process_fleet_tick(player_id=uid, conn=conn)
        conn.commit()
        assert int(first.get("processed_arrivals") or 0) == 1

        _force_expedition_stay_end(conn, fleet_id)
        before = conn.execute(
            "SELECT COUNT(*) AS c FROM player_messages "
            "WHERE recipient_player_id = ? AND category = 'expedition';",
            (uid,),
        ).fetchone()
        before_count = int(before["c"] or 0)

        _stamp_fresh_fleet_worker(conn)
        assert is_fleet_worker_heartbeat_fresh(conn=conn) is True

        read_player_live_state_for_poll(uid, conn=conn)

        row = conn.execute(
            "SELECT status FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "returning"
        after = conn.execute(
            "SELECT COUNT(*) AS c FROM player_messages "
            "WHERE recipient_player_id = ? AND category = 'expedition';",
            (uid,),
        ).fetchone()
        assert int(after["c"] or 0) == before_count + 1
    finally:
        conn.close()


def test_deadline_safety_net_is_bounded_short_tx_and_return_first():
    src = Path("game/fleet.py").read_text(encoding="utf-8")
    helper = src.split("def process_player_due_fleets_now(", 1)[1].split(
        "\ndef mass_expedition_available_slots", 1
    )[0]
    assert "conn=None" in helper
    assert "manage_transaction=True" in helper
    assert "GC_POLL_FLEET_MAX_MOVEMENTS" in helper
    assert "GC_POLL_FLEET_MAX_MS" in helper
    assert "prioritize_returns=True" in helper

    tick = src.split("def _process_fleet_tick_short_tx(", 1)[1].split(
        "\ndef process_player_due_fleets_now", 1
    )[0]
    priority = tick.split("if prioritize_returns:", 1)[1].split("else:", 1)[0]
    assert priority.index("_run_returning()") < priority.index("_run_holding()")
    assert priority.index("_run_holding()") < priority.index("_run_outbound()")


def test_poll_source_no_longer_defers_due_fleet_on_worker_freshness():
    src = Path("game/logic.py").read_text(encoding="utf-8")
    block = src.split("def read_player_live_state_for_poll(", 1)[1].split(
        "\ndef refresh_player_live_state(", 1
    )[0]
    assert "process_player_due_fleets_now(uid, now=now)" in block
    assert "is_fleet_worker_heartbeat_fresh" not in block
    assert "if fleet_dirty:" in block