"""GC-583 — Strategic world inspector → fleet expedition prefill."""

from __future__ import annotations

import importlib
import json
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
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import build_world_expedition_preview

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc583_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc583.db"
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
    ok, err, user = create_user(f"gc583_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    return uid


def _expedition_field():
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_expedition"):
                return field
    raise AssertionError("no expedition field in sample grid")


def _salvage_field():
    for wx in range(500, 5000, 113):
        for wy in range(500, 5000, 97):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_salvage"):
                return field
    raise AssertionError("no salvage field in sample grid")


def test_build_world_expedition_preview_for_expedition_zone(gc583_db):
    field = _expedition_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        preview = build_world_expedition_preview(player_id, field["world_key"], conn=conn)
        assert preview["can_expedition"] is True
        assert preview["presentation"]["name_key"]
        assert preview["presentation"]["type_key"]
        assert preview["target"]["target_type"] == "strategic_world"
        assert preview["target"]["strategic_world"]["world_key"] == field["world_key"]
    finally:
        conn.close()


def test_api_worlds_expedition_preview(gc583_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    field = _expedition_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    resp = client.get(f"/api/worlds/expedition-preview?world_key={field['world_key']}")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["data"]["can_expedition"] is True
    assert payload["data"]["presentation"]["promise_key"]


def test_galaxy_template_expedition_inspector_and_fleet_panel(gc583_db, monkeypatch):
    import app as app_module

    dbmod.DB_PATH = gc583_db
    models.DB_PATH = gc583_db
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

    map_body = client.get("/galaxy?view=command_map").get_data(as_text=True)
    assert "galaxy-command-map-graph--fullmap" in map_body
    assert "gc-world-inspector-modal" in map_body
    assert "data-world-field-inspect" in map_body
    assert "data-strategic-expedition" in map_body
    assert "data-strategic-expedition-prepared" in map_body
    assert "data-strategic-salvage" in map_body

    field = _expedition_field()
    fleet_body = client.get(
        f"/fleet?mission=expedition&world_key={field['world_key']}"
    ).get_data(as_text=True)
    assert "data-fleet-world-target" in fleet_body


def test_fleet_preview_includes_strategic_world_expedition_target(gc583_db):
    field = _expedition_field()
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
        add_planet_ships(origin_id, player_id, {"solar_skiff": 2}, conn=conn)

        preview = build_fleet_send_preview(
            player_id=player_id,
            origin_planet=dict(origin),
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
        assert preview["target"]["target_type"] == "strategic_world"
        assert preview["target"]["strategic_world"]["world_key"] == field["world_key"]
        assert preview["can_send"] is True
    finally:
        conn.close()


def test_strategic_field_flags_expedition_types():
    expedition = _expedition_field()
    salvage = _salvage_field()
    assert expedition["is_expedition"] is True
    assert expedition["is_expedition_prepared"] is False
    assert salvage["is_salvage"] is True
    assert salvage["is_expedition_prepared"] is False
    assert salvage["is_expedition"] is False


def test_main_js_gc583_contract():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "/api/worlds/expedition-preview" in js
    assert "data-command-map-expedition-world" in js
    assert "onExpeditionWorldClick" in js
    assert "strategicExpedition" in js


def test_gc583_locale_keys_present():
    keys = (
        "strategic_world_btn_expedition",
        "strategic_world_inspector_status_expedition",
        "strategic_world_inspector_status_prepared",
        "strategic_world_btn_salvage",
    )
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    for key in keys:
        assert key in de, f"missing de locale key {key}"
        assert key in en, f"missing en locale key {key}"
