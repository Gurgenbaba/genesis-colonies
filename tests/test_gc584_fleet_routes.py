"""GC-584 — Own fleet routes on the shared command map."""

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
from game.planet_evolution.fleet_routes import build_fleet_routes_payload
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import parse_world_key

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc584_routes_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc584_routes.db"
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
    ok, err, user = create_user(f"gc584r_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    conn.commit()
    return uid


def _colonizable_field():
    for wx in range(600, 5000, 60):
        for wy in range(600, 5000, 60):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_colonizable"):
                return field
    raise AssertionError("no colonizable field found")


def _expedition_field():
    for wx in range(600, 5000, 60):
        for wy in range(600, 5000, 60):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_expedition"):
                return field
    raise AssertionError("no expedition field found")


def test_command_map_payload_includes_fleet_routes(gc584_routes_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        payload = build_command_map_payload(player_id, conn=conn)
        assert "fleet_routes" in payload
        assert isinstance(payload["fleet_routes"], list)
    finally:
        conn.close()


def test_colonize_fleet_route_to_strategic_world(gc584_routes_db):
    from game.db import db
    from game.fleet import add_planet_ships, send_fleet

    field = _colonizable_field()
    conn = db()
    try:
        player_id = _player(conn)
        origin = conn.execute(
            "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()
        origin_id = int(origin["id"])
        conn.execute("UPDATE planets SET fuel_cells = 50000 WHERE id = ?;", (origin_id,))
        add_planet_ships(origin_id, player_id, {"seed_ark": 1}, conn=conn)
        conn.commit()

        ok, reason, _ = send_fleet(
            player_id=player_id,
            origin_planet_id=origin_id,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="colonize",
            ships={"seed_ark": 1},
            resources={},
            speed_percent=100,
            conn=conn,
            world_key=field["world_key"],
        )
        assert ok, reason

        payload = build_command_map_payload(player_id, conn=conn)
        routes = payload["fleet_routes"]
        assert len(routes) == 1
        route = routes[0]
        assert route["mission"] == "colonize"
        assert route["phase"] == "outbound"
        assert route["world_key"] == field["world_key"]
        parsed = parse_world_key(field["world_key"])
        assert route["to_world_x"] == pytest.approx(parsed["world_x"], abs=0.01)
        assert route["to_world_y"] == pytest.approx(parsed["world_y"], abs=0.01)
        assert 0 <= route["progress_pct"] <= 100
        assert route["remaining_seconds"] >= 0
    finally:
        conn.close()


def test_expedition_fleet_route_to_world_field(gc584_routes_db):
    from game.db import db
    from game.fleet import add_planet_ships, send_fleet

    field = _expedition_field()
    conn = db()
    try:
        player_id = _player(conn)
        origin = conn.execute(
            "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()
        origin_id = int(origin["id"])
        conn.execute("UPDATE planets SET fuel_cells = 50000 WHERE id = ?;", (origin_id,))
        add_planet_ships(origin_id, player_id, {"solar_skiff": 1}, conn=conn)
        conn.commit()

        ok, reason, _ = send_fleet(
            player_id=player_id,
            origin_planet_id=origin_id,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            resources={},
            speed_percent=100,
            conn=conn,
            world_key=field["world_key"],
        )
        assert ok, reason

        payload = build_command_map_payload(player_id, conn=conn)
        routes = [r for r in payload["fleet_routes"] if r["mission"] == "expedition"]
        assert len(routes) == 1
        assert routes[0]["world_key"] == field["world_key"]
        assert routes[0]["phase"] == "outbound"
    finally:
        conn.close()


def test_foreign_fleet_routes_are_excluded(gc584_routes_db):
    from game.db import db

    conn = db()
    try:
        viewer_id = _player(conn)
        ok, err, other_user = create_user(f"gc584o_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok and other_user, err
        other_id = int(other_user["id"])
        ensure_player_and_homeworld(other_id, player_name="Rival", conn=conn)
        other_origin = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (other_id,),
        ).fetchone()["id"]
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO fleet_movements (
                player_id, origin_planet_id, target_planet_id,
                target_galaxy, target_system, target_position,
                mission_type, status, ships_json, resources_json,
                fuel_cost, speed_percent, distance, flight_seconds,
                departure_at, arrival_at, return_at, created_at, updated_at
            ) VALUES (?, ?, NULL, 1, 1, 3, 'transport', 'outbound', '{}', '{}', 0, 100, 1, 100, ?, ?, NULL, ?, ?);
            """,
            (other_id, int(other_origin), now - 10, now + 90, now, now),
        )
        conn.commit()

        payload = build_command_map_payload(viewer_id, conn=conn)
        assert payload["fleet_routes"] == []
    finally:
        conn.close()


def test_galaxy_command_map_template_fleet_routes_markup():
    tpl = (ROOT / "templates/partials/galaxy_command_map_panel.html").read_text(encoding="utf-8")
    assert "cm_fleet_routes" in tpl
    assert "galaxy-command-map-fleet-routes" in tpl
    assert "data-command-map-fleet-routes" in tpl
    assert "galaxy-command-map-fleet-route-group" in tpl
    assert "animateMotion" in tpl
    assert 'keyPoints="1;0"' not in tpl


def test_galaxy_command_map_style_fleet_routes_contract():
    css = (ROOT / "static/style.css").read_text(encoding="utf-8")
    assert ".galaxy-command-map-fleet-routes" in css
    assert ".galaxy-command-map-fleet-route-flow--colonize" in css
    assert ".galaxy-command-map-fleet-route-group--returning" in css


def test_build_fleet_routes_progress_from_timing(gc584_routes_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        payload = build_command_map_payload(player_id, conn=conn)
        nodes = payload["nodes"]
        now = time.time()
        routes = build_fleet_routes_payload(player_id, nodes, conn=conn, now=now)
        assert routes == []

        conn.execute(
            """
            INSERT INTO fleet_movements (
                player_id, origin_planet_id, target_planet_id,
                target_galaxy, target_system, target_position,
                mission_type, status, ships_json, resources_json,
                fuel_cost, speed_percent, distance, flight_seconds,
                departure_at, arrival_at, return_at, created_at, updated_at
            ) VALUES (?, ?, NULL, 1, 1, 2, 'transport', 'outbound', '{}', '{}', 0, 100, 1, 100, ?, ?, NULL, ?, ?);
            """,
            (
                player_id,
                conn.execute(
                    "SELECT id FROM planets WHERE player_id = ? LIMIT 1;",
                    (player_id,),
                ).fetchone()["id"],
                int(now) - 50,
                int(now) + 50,
                int(now),
                int(now),
            ),
        )
        conn.commit()
        routes = build_fleet_routes_payload(player_id, nodes, conn=conn, now=now)
        assert len(routes) == 1
        assert routes[0]["progress_pct"] == pytest.approx(50.0, abs=2.0)
        assert routes[0]["mission"] == "transport"
    finally:
        conn.close()


def test_returning_fleet_route_runs_target_to_origin(gc584_routes_db):
    from game.db import db

    field = _colonizable_field()
    conn = db()
    try:
        player_id = _player(conn)
        origin = conn.execute(
            "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()
        origin_id = int(origin["id"])
        now = int(time.time())
        conn.execute(
            """
            INSERT INTO fleet_movements (
                player_id, origin_planet_id, target_planet_id,
                target_galaxy, target_system, target_position,
                mission_type, status, ships_json, resources_json,
                fuel_cost, speed_percent, distance, flight_seconds,
                departure_at, arrival_at, return_at,
                created_at, updated_at
            ) VALUES (?, ?, NULL, 1, 1, 1, 'colonize', 'returning', '{}', ?, 0, 100, 1, 100, ?, ?, ?, ?, ?);
            """,
            (
                player_id,
                origin_id,
                json.dumps({"world_key": field["world_key"]}),
                now - 200,
                now - 100,
                now + 50,
                now,
                now,
            ),
        )
        conn.commit()
        payload = build_command_map_payload(player_id, conn=conn)
        routes = [r for r in payload["fleet_routes"] if r["phase"] == "returning"]
        assert len(routes) == 1
        route = routes[0]
        parsed = parse_world_key(field["world_key"])
        assert route["from_world_x"] == pytest.approx(parsed["world_x"], abs=0.01)
        assert route["from_world_y"] == pytest.approx(parsed["world_y"], abs=0.01)
        assert route["to_world_x"] != route["from_world_x"]
    finally:
        conn.close()
