"""GC-PERF-FLEET-WRITE-001 — active Fleet HUD reads must stay write-free."""

from __future__ import annotations

import json
import re
import time
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.fleet import build_active_fleets_payload
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db

ROOT_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


@pytest.fixture()
def fleet_read_db(tmp_path, monkeypatch):
    db_file = tmp_path / "fleet_read_guard.db"
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
    username = f"fleet_read_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(username, "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="FleetReadGuard", conn=conn)
    planet = get_homeworld(uid, conn=conn)
    assert planet is not None
    return uid, dict(planet)


def _insert_movement(conn, *, player_id: int, planet: dict, status: str, now: float) -> int:
    returning = status == "returning"
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
            status,
            now - 300.0,
            now - 60.0 if returning else now + 3600.0,
            now + 3600.0 if returning else None,
            json.dumps({"mule_courier": 1}),
            "{}",
            0.0,
            100,
            1,
            3600,
            now - 300.0,
            now - 300.0,
        ),
    )
    return int(cur.lastrowid)


def test_active_fleet_hud_read_does_not_write_outbound_or_returning(fleet_read_db):
    conn = db()
    try:
        uid, planet = _create_player_with_homeworld(conn)
        now = time.time()
        outbound_id = _insert_movement(
            conn,
            player_id=uid,
            planet=planet,
            status="outbound",
            now=now,
        )
        returning_id = _insert_movement(
            conn,
            player_id=uid,
            planet=planet,
            status="returning",
            now=now,
        )
        conn.commit()

        writes: list[str] = []

        def trace(stmt: str) -> None:
            if ROOT_WRITE.match(stmt):
                writes.append(stmt.strip())

        conn.set_trace_callback(trace)
        try:
            payload = build_active_fleets_payload(uid, conn=conn)
        finally:
            conn.set_trace_callback(None)

        item_ids = {int(item.get("id") or 0) for item in payload.get("items") or []}
        assert outbound_id in item_ids
        assert returning_id in item_ids
        assert writes == [], f"active Fleet HUD read performed DB writes: {writes}"
    finally:
        conn.close()
