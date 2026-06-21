"""GC-584 — Wreckage field salvage on world map."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.expedition_events import resolve_expedition_outcome
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import (
    SALVAGE_WORLD_TYPES,
    build_world_key,
    build_world_salvage_preview,
    is_salvage_world_type,
    validate_world_salvage_target,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc584_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc584.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _create_player(conn):
    ok, err, user = create_user(f"salv_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    return uid


def _salvage_field():
    for wx in range(500, 5000, 113):
        for wy in range(500, 5000, 97):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_salvage"):
                return field
    raise AssertionError("no salvage field in sample grid")


def _fleet_player(conn):
    from game.fleet import add_planet_ships, process_fleet_tick, send_fleet

    player_id = _create_player(conn)
    pid = int(get_planets_by_player(player_id, conn=conn)[0]["id"])
    conn.execute(
        "UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;",
        (pid,),
    )
    add_planet_ships(pid, player_id, {"solar_skiff": 2}, conn=conn)
    return player_id, pid, send_fleet, process_fleet_tick, time


def test_salvage_world_types():
    assert "wreckage_field" in SALVAGE_WORLD_TYPES
    assert is_salvage_world_type("wreckage_field")


def test_strategic_field_marks_salvage_not_prepared():
    field = _salvage_field()
    assert field["world_type"] == "wreckage_field"
    assert field["is_salvage"] is True
    assert field["is_expedition_prepared"] is False
    assert field["is_expedition"] is False


def test_validate_world_salvage_target(gc584_db):
    field = _salvage_field()
    from game.db import db

    conn = db()
    try:
        ok, reason, info = validate_world_salvage_target(field["world_key"], conn=conn)
        assert ok, reason
        assert info["allowed_missions"] == ["expedition"]
        assert info["strategic_world"]["world_type"] == "wreckage_field"
    finally:
        conn.close()


def test_build_world_salvage_preview_with_ships(gc584_db):
    field = _salvage_field()
    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        from game.fleet import add_planet_ships

        pid = int(get_planets_by_player(player_id, conn=conn)[0]["id"])
        add_planet_ships(pid, player_id, {"solar_skiff": 1}, conn=conn)
        preview = build_world_salvage_preview(player_id, field["world_key"], conn=conn)
        assert preview["can_salvage"] is True
        assert preview["has_salvage_ships"] is True
        assert preview["can_start_salvage"] is True
    finally:
        conn.close()


def test_build_world_salvage_preview_without_ships(gc584_db):
    field = _salvage_field()
    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        preview = build_world_salvage_preview(player_id, field["world_key"], conn=conn)
        assert preview["can_salvage"] is True
        assert preview["has_salvage_ships"] is False
        assert preview["can_start_salvage"] is False
        assert preview["block_reason"] == "no_expedition_ships"
    finally:
        conn.close()


def test_fleet_world_key_salvage_sends_and_reports(gc584_db):
    from game.db import db

    field = _salvage_field()
    conn = db()
    try:
        player_id, pid, send_fleet, process_fleet_tick, time_mod = _fleet_player(conn)
        conn.commit()

        ok, reason, result = send_fleet(
            player_id=player_id,
            origin_planet_id=pid,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            world_key=field["world_key"],
            conn=conn,
        )
        assert ok, reason
        fleet_id = int(result["fleet"]["id"])

        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time_mod.time() - 1, fleet_id),
        )
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()

        status = conn.execute(
            "SELECT status FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()["status"]
        assert status == "holding"

        conn.execute(
            "UPDATE fleet_movements SET holding_until = ? WHERE id = ?;",
            (time_mod.time() - 1, fleet_id),
        )
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()

        msg = conn.execute(
            """
            SELECT subject, metadata_json FROM player_messages
            WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;
            """,
            (player_id,),
        ).fetchone()
        assert msg
        meta = msg["metadata_json"]
        assert "world_salvage" in str(meta)
        assert field["world_key"] in str(meta)
    finally:
        conn.close()


def test_salvage_outcome_biased_to_salvage_events():
    keys = set()
    for movement_id in range(1, 200):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=50000,
            expedition_ship_count=2,
            flight_seconds=120,
            world_type="wreckage_field",
        )
        keys.add(outcome["event_key"])
    assert keys.issubset({"debris_salvage", "mineral_deposit", "fuel_cache", "distress_beacon"})
    assert keys  # not empty


def test_classic_expedition_slot_unchanged(gc584_db):
    from game.db import db
    from game.fleet import EXPEDITION_POSITION, build_fleet_send_preview

    conn = db()
    try:
        player_id, pid, _, _, _ = _fleet_player(conn)
        origin = conn.execute("SELECT * FROM planets WHERE id = ?;", (pid,)).fetchone()
        preview = build_fleet_send_preview(
            player_id=player_id,
            origin_planet=dict(origin),
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert preview["mission_allowed"] is True
    finally:
        conn.close()


def test_inspector_template_has_salvage_actions(gc584_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        conn.commit()
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    resp = client.get("/galaxy?view=command_map", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "gc-world-inspector-modal" in body
    assert "data-strategic-salvage" in body
    assert "data-world-field-inspect" in body
    assert "data-command-map-inspector-strategic-wreckage" not in body

    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "strategicSalvage" in js
    assert "/api/worlds/salvage-preview" in js


def test_api_worlds_salvage_preview(gc584_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    field = _salvage_field()
    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        conn.commit()
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    resp = client.get(f"/api/worlds/salvage-preview?world_key={field['world_key']}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["data"]["can_salvage"] is True
