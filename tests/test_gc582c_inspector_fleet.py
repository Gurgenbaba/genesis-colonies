"""GC-582C — Strategic world inspector → fleet colonize prefill."""

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
from game.fleet import build_fleet_send_preview
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.strategic_worlds import (
    build_strategic_world_field,
    build_strategic_world_presentation,
    strategic_world_type_for_coords,
)
from game.planet_evolution.world_colonization import (
    build_world_colonize_preview,
    build_world_key,
    is_colonizable_world_type,
    reserve_world_claim,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc582c_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc582c.db"
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
    ok, err, user = create_user(f"gc582c_{uuid.uuid4().hex[:8]}", "test-pass-123")
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


def _non_colonizable_field():
    for wx in range(500, 5000, 113):
        for wy in range(500, 5000, 97):
            field = build_strategic_world_field(float(wx), float(wy))
            if not field.get("is_colonizable"):
                return field
    raise AssertionError("no non-colonizable field in sample grid")


def test_build_world_colonize_preview_for_colonizable_world(gc582c_db):
    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        preview = build_world_colonize_preview(player_id, field["world_key"], conn=conn)
        assert preview["can_colonize"] is True
        assert preview["presentation"]["name_key"]
        assert preview["presentation"]["type_key"]
        assert preview["target"]["target_type"] == "strategic_world"
        assert preview["target"]["strategic_world"]["world_key"] == field["world_key"]
    finally:
        conn.close()


def test_build_world_colonize_preview_blocks_claimed_world(gc582c_db):
    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        ok, reason, payload = reserve_world_claim(
            player_id,
            field["_world_x"],
            field["_world_y"],
            conn=conn,
        )
        assert ok, reason
        preview = build_world_colonize_preview(player_id, field["world_key"], conn=conn)
        assert preview["can_colonize"] is False
        assert preview["block_reason"] == "world_already_claimed"
        assert preview["presentation"]["world_key"] == field["world_key"]
    finally:
        conn.close()


def test_build_world_colonize_preview_rejects_non_colonizable(gc582c_db):
    field = _non_colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        preview = build_world_colonize_preview(player_id, field["world_key"], conn=conn)
        assert preview["can_colonize"] is False
        assert preview["block_reason"] == "world_not_colonizable"
        assert preview["presentation"]["is_colonizable"] is False
    finally:
        conn.close()


def test_api_worlds_colonize_preview(gc582c_db, monkeypatch):
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

    resp = client.get(f"/api/worlds/colonize-preview?world_key={field['world_key']}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["data"]["can_colonize"] is True
    assert payload["data"]["presentation"]["promise_key"]


def test_galaxy_template_colonize_inspector_and_fleet_panel(gc582c_db, monkeypatch):
    import app as app_module

    dbmod.DB_PATH = gc582c_db
    models.DB_PATH = gc582c_db
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

    map_body = client.get("/galaxy?view=command_map&dev=1").get_data(as_text=True)
    assert "galaxy-command-map-graph--fullmap" in map_body
    assert "gc-world-inspector-modal" in map_body
    assert "data-world-field-inspect" in map_body
    assert "data-strategic-colonizable" in map_body
    assert "data-strategic-claimed" in map_body
    assert "gc-command-center-hud" not in map_body

    field = _colonizable_field()
    fleet_body = client.get(
        f"/fleet?mission=colonize&world_key={field['world_key']}&colony_name=Helios"
    ).get_data(as_text=True)
    assert 'data-fleet-world-target' in fleet_body


def test_fleet_preview_includes_strategic_world_target(gc582c_db):
    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        conn.execute(
            "UPDATE planets SET fuel_cells = 50000 WHERE player_id = ?;",
            (player_id,),
        )
        from game.fleet import add_planet_ships

        origin = conn.execute(
            "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()
        origin_id = int(origin["id"])
        add_planet_ships(origin_id, player_id, {"seed_ark": 1}, conn=conn)

        preview = build_fleet_send_preview(
            player_id=player_id,
            origin_planet=dict(origin),
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
        assert preview["target"]["target_type"] == "strategic_world"
        assert preview["target"]["strategic_world"]["world_key"] == field["world_key"]
        assert preview["can_send"] is True
    finally:
        conn.close()


def test_main_js_gc582c_contract():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "loadFleetWorldTargetPreview" in js
    assert "/api/worlds/colonize-preview" in js
    assert "data-fleet-world-target" in js
    assert "renderFleetWorldTargetPanel" in js


def test_gc582c_locale_keys_present():
    import json

    keys = (
        "strategic_world_btn_colonize",
        "strategic_world_colony_limit",
        "strategic_world_inspector_status_claimed",
        "strategic_world_inspector_status_settled",
        "strategic_world_inspector_status_not_colonizable",
        "fleet_world_target_hint",
        "fleet_world_target_kicker",
        "fleet_target_strategic_world",
    )
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    for key in keys:
        assert key in de, f"missing de locale key {key}"
        assert key in en, f"missing en locale key {key}"
