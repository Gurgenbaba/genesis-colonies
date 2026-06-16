"""GC-590A — World-native fleet target model (places, not coordinates)."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.fleet import build_fleet_send_preview, resolve_fleet_target
from game.fleet_target import (
    attach_world_target,
    infer_world_native_target_type,
    normalize_fleet_target_request,
    parse_fleet_target_request,
)
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import build_world_key

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc590a_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc590a.db"
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
    ok, err, user = create_user(f"gc590a_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    return uid


def _colonizable_field():
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_colonizable"):
                return field
    raise AssertionError("no colonizable field in sample grid")


def _origin_and_ships(conn, player_id):
    conn.execute(
        "UPDATE planets SET fuel_cells = 50000 WHERE player_id = ?;",
        (player_id,),
    )
    from game.fleet import add_planet_ships

    origin = conn.execute(
        "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
        (player_id,),
    ).fetchone()
    add_planet_ships(int(origin["id"]), player_id, {"seed_ark": 1}, conn=conn)
    return dict(origin)


def test_parse_fleet_target_request_accepts_world_native_fields():
    req = parse_fleet_target_request(
        {
            "target_type": "world_colony",
            "target_world_key": "field:mining:1820:2470",
            "target_world_x": 1820,
            "target_world_y": 2470,
            "target_planet_id": 42,
        }
    )
    assert req["target_type"] == "world_colony"
    assert req["world_key"] == "field:mining:1820:2470"
    assert req["target_world_x"] == pytest.approx(1820.0)
    assert req["target_planet_id"] == 42


def test_infer_world_native_target_type_mapping():
    assert (
        infer_world_native_target_type(
            legacy_target_type="strategic_world",
            world_key="field:mining:1820:2470",
            world_type="mining",
            owner_player_id=None,
            viewer_player_id=1,
            planet_id=None,
        )
        == "world_colony"
    )
    assert (
        infer_world_native_target_type(
            legacy_target_type="strategic_world",
            world_key="field:wreckage_field:100:200",
            world_type="wreckage_field",
            owner_player_id=None,
            viewer_player_id=1,
            planet_id=None,
        )
        == "wreckage"
    )
    assert (
        infer_world_native_target_type(
            legacy_target_type="own_planet",
            world_key="field:mining:1:2",
            world_type="mining",
            owner_player_id=1,
            viewer_player_id=1,
            planet_id=5,
        )
        == "world_colony"
    )


def test_colonize_preview_includes_world_target(gc590a_db):
    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        origin = _origin_and_ships(conn, player_id)
        preview = build_fleet_send_preview(
            player_id=player_id,
            origin_planet=origin,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="colonize",
            ships={"seed_ark": 1},
            resources={},
            speed_percent=100,
            conn=conn,
            world_key=field["world_key"],
            target_type="world_colony",
        )
        wt = preview["target"]["world_target"]
        assert wt["target_type"] == "world_colony"
        assert wt["target_world_key"] == field["world_key"]
        assert wt["target_world_x"] is not None
        assert wt["target_world_y"] is not None
        assert wt["target_name_key"]
        assert wt["legacy_coords"]["galaxy"] >= 1
    finally:
        conn.close()


def test_legacy_coords_preview_includes_world_target(gc590a_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        origin = _origin_and_ships(conn, player_id)
        preview = build_fleet_send_preview(
            player_id=player_id,
            origin_planet=origin,
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=int(origin["position"]),
            mission_type="transport",
            ships={"cargo_drone": 1},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        wt = preview["target"]["world_target"]
        assert wt["target_type"] in ("planet", "world_colony")
        assert wt["legacy_coords"]["galaxy"] == int(origin["galaxy"])
        assert wt["legacy_coords"]["system"] == int(origin["system"])
        assert wt["legacy_coords"]["position"] == int(origin["position"])
    finally:
        conn.close()


def test_target_planet_id_normalizes_world_target(gc590a_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        origin = _origin_and_ships(conn, player_id)
        norm = normalize_fleet_target_request(
            player_id,
            "transport",
            target_planet_id=int(origin["id"]),
            target_galaxy=1,
            target_system=1,
            target_position=1,
            origin_planet=origin,
            conn=conn,
        )
        assert norm.target_galaxy == int(origin["galaxy"])
        assert norm.world_native_type in ("planet", "world_colony")

        target = resolve_fleet_target(
            player_id,
            norm.target_galaxy,
            norm.target_system,
            norm.target_position,
            conn=conn,
        )
        attach_world_target(target, player_id=player_id, conn=conn)
        assert target["world_target"]["target_planet_id"] == int(origin["id"])
    finally:
        conn.close()


def test_world_native_allowed_missions_prepared():
    from game.fleet import _BASE_ALLOWED_MISSIONS

    assert "transport" in _BASE_ALLOWED_MISSIONS["world_colony"]
    assert "attack" in _BASE_ALLOWED_MISSIONS["enemy_colony"]
    assert "expedition" in _BASE_ALLOWED_MISSIONS["expedition_world"]
    assert "expedition" in _BASE_ALLOWED_MISSIONS["anomaly"]
    assert "recycle" in _BASE_ALLOWED_MISSIONS["wreckage"]
    assert "colonize" in _BASE_ALLOWED_MISSIONS["strategic_world"]


def test_api_resolve_target_world_key(gc590a_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    resp = client.post(
        "/api/fleet/resolve-target",
        json={"mission_type": "colonize", "world_key": field["world_key"]},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    wt = payload["data"]["target"]["world_target"]
    assert wt["target_type"] == "world_colony"
    assert wt["target_world_key"] == field["world_key"]
