"""GC-583C — World expedition activity on command map."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_expedition_activity import (
    attach_world_expedition_activity,
    build_world_expedition_activity_map,
)
from game.planet_evolution.world_colonization import is_expedition_world_type
from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc583c_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc583c.db"
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


def _player(conn):
    ok, err, user = create_user(f"gc583c_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    conn.commit()
    return uid


def _expedition_field():
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_expedition"):
                return field
    raise AssertionError("no expedition field in sample grid")


def test_build_activity_map_for_active_expedition(gc583c_db):
    from game.fleet import add_planet_ships, send_fleet

    field = _expedition_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        pid = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()["id"]
        conn.execute(
            "UPDATE planets SET fuel_cells = 50000 WHERE player_id = ?;",
            (player_id,),
        )
        add_planet_ships(int(pid), player_id, {"solar_skiff": 1}, conn=conn)
        conn.commit()

        ok, reason, _ = send_fleet(
            player_id=player_id,
            origin_planet_id=int(pid),
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            world_key=field["world_key"],
            conn=conn,
        )
        assert ok, reason

        activity = build_world_expedition_activity_map(player_id, conn=conn)
        assert field["world_key"] in activity
        assert activity[field["world_key"]]["expedition_status"] == "expedition_active"
        assert activity[field["world_key"]]["expedition_eta_at"] > 0
    finally:
        conn.close()


def test_classic_slot_expedition_not_in_activity_map(gc583c_db):
    from game.fleet import EXPEDITION_POSITION, add_planet_ships, send_fleet

    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        origin = conn.execute(
            "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()
        pid = int(origin["id"])
        conn.execute("UPDATE planets SET fuel_cells = 50000 WHERE id = ?;", (pid,))
        add_planet_ships(pid, player_id, {"solar_skiff": 1}, conn=conn)
        conn.commit()

        ok, reason, _ = send_fleet(
            player_id=player_id,
            origin_planet_id=pid,
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            conn=conn,
        )
        assert ok, reason

        activity = build_world_expedition_activity_map(player_id, conn=conn)
        assert activity == {}
    finally:
        conn.close()


def test_command_map_payload_marks_expedition_field(gc583c_db):
    from game.fleet import add_planet_ships, send_fleet

    field = _expedition_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        pid = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()["id"]
        conn.execute("UPDATE planets SET fuel_cells = 50000 WHERE id = ?;", (pid,))
        add_planet_ships(int(pid), player_id, {"solar_skiff": 1}, conn=conn)
        conn.commit()

        ok, reason, _ = send_fleet(
            player_id=player_id,
            origin_planet_id=int(pid),
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            world_key=field["world_key"],
            conn=conn,
        )
        assert ok, reason

        nodes = [dict(field)]
        attach_world_expedition_activity(
            nodes,
            build_world_expedition_activity_map(player_id, conn=conn),
        )
        assert nodes[0]["expedition_status"] == "expedition_active"
        assert nodes[0]["expedition_eta_at"] > 0
    finally:
        conn.close()


def test_attach_sets_idle_without_activity():
    field = _expedition_field()
    nodes = [dict(field)]
    attach_world_expedition_activity(nodes, {})
    assert nodes[0]["expedition_status"] == "idle"


def test_galaxy_template_expedition_activity_fields(gc583c_db, monkeypatch):
    import importlib

    import app as app_module

    dbmod.DB_PATH = gc583c_db
    models.DB_PATH = gc583c_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
    finally:
        conn.close()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    body = client.get("/galaxy?view=command_map").get_data(as_text=True)
    assert "gc-world-inspector-modal" in body
    assert "data-world-field-inspect" in body
    assert "data-expedition-status" in body
    assert "world_expedition_badge_active" in body
