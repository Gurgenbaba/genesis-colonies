"""GC-PERF-FLEET-IDLE-001/002 — keep idle Fleet polling cheap."""

from __future__ import annotations

import json
import time
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db
from game.queue_poll import player_fleet_is_dirty, player_has_due_queue_work


@pytest.fixture()
def fleet_idle_db(tmp_path, monkeypatch):
    db_file = tmp_path / "fleet_idle.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()

    import migrate

    migrate.main()
    return db_file


def _create_player_with_homeworld(conn) -> tuple[int, dict]:
    username = f"fleet_idle_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(username, "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="FleetIdleGuard", conn=conn)
    planet = get_homeworld(uid, conn=conn)
    assert planet is not None
    return uid, dict(planet)


def _insert_due_outbound(conn, *, player_id: int, planet: dict, now: float) -> int:
    cur = conn.execute(
        """
        INSERT INTO fleet_movements (
            player_id, origin_planet_id, target_planet_id,
            target_galaxy, target_system, target_position,
            mission_type, status, departure_at, arrival_at, return_at,
            ships_json, resources_json, fuel_cost, speed_percent,
            distance, flight_seconds, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(player_id),
            int(planet["id"]),
            int(planet["id"]),
            int(planet.get("galaxy") or 1),
            int(planet.get("system") or 1),
            int(planet.get("position") or 1),
            "transport",
            "outbound",
            now - 300.0,
            now - 1.0,
            None,
            json.dumps({"mule_courier": 1}),
            "{}",
            0.0,
            100,
            1,
            300,
            now - 300.0,
            now - 300.0,
        ),
    )
    return int(cur.lastrowid)


def _set_due_phase(conn, movement_id: int, *, phase: str, now: float) -> None:
    if phase == "outbound":
        conn.execute(
            """
            UPDATE fleet_movements
            SET status = 'outbound', arrival_at = ?, holding_until = NULL, return_at = NULL
            WHERE id = ?;
            """,
            (now - 1.0, int(movement_id)),
        )
        return
    if phase == "holding":
        conn.execute(
            """
            UPDATE fleet_movements
            SET status = 'holding', arrival_at = ?, holding_until = ?, return_at = NULL
            WHERE id = ?;
            """,
            (now - 60.0, now - 1.0, int(movement_id)),
        )
        return
    if phase == "returning":
        conn.execute(
            """
            UPDATE fleet_movements
            SET status = 'returning', holding_until = NULL, return_at = ?
            WHERE id = ?;
            """,
            (now - 1.0, int(movement_id)),
        )
        return
    raise AssertionError(f"unsupported phase: {phase}")


def test_queue_due_probe_does_not_query_fleet_movements(fleet_idle_db):
    conn = db()
    try:
        uid, planet = _create_player_with_homeworld(conn)
        now = time.time()
        _insert_due_outbound(conn, player_id=uid, planet=planet, now=now)
        conn.commit()

        selects: list[str] = []

        def trace(stmt: str) -> None:
            normalized = stmt.strip().lower()
            if normalized.startswith("select"):
                selects.append(normalized)

        conn.set_trace_callback(trace)
        try:
            queue_due = player_has_due_queue_work(uid, conn=conn, now=now)
        finally:
            conn.set_trace_callback(None)

        assert queue_due is False
        assert not any("fleet_movements" in stmt for stmt in selects), selects
        assert player_fleet_is_dirty(uid, conn=conn, now=now) is True
    finally:
        conn.close()


@pytest.mark.parametrize("phase", ["outbound", "holding", "returning"])
def test_fleet_dirty_probe_detects_each_due_phase(fleet_idle_db, phase):
    conn = db()
    try:
        uid, planet = _create_player_with_homeworld(conn)
        now = time.time()
        movement_id = _insert_due_outbound(conn, player_id=uid, planet=planet, now=now)
        _set_due_phase(conn, movement_id, phase=phase, now=now)
        conn.commit()

        assert player_fleet_is_dirty(uid, conn=conn, now=now) is True
    finally:
        conn.close()


def test_fleet_deadline_indexes_are_migrated(fleet_idle_db):
    conn = db()
    try:
        rows = conn.execute("PRAGMA index_list('fleet_movements');").fetchall()
        names = {str(row["name"]) for row in rows}
        assert "idx_fleet_movements_player_arrival" in names
        assert "idx_fleet_movements_player_holding" in names
        assert "idx_fleet_movements_player_return" in names
        assert "idx_fleet_movements_holding" in names
    finally:
        conn.close()
