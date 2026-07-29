"""GC-590B — Fleet UI world-native target panel and payload."""

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

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc590b_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc590b.db"
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
    ok, err, user = create_user(f"gc590b_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    # GC-976A: colonize_planet()/send_fleet(mission_type="colonize") need an
    # unlocked evolution slot.
    from game.models import get_homeworld
    from conftest import unlock_colony_slots
    homeworld_id = int(get_homeworld(player_id=uid, conn=conn)["id"])
    unlock_colony_slots(conn, homeworld_id, slots=1)
    # The fleet-send form (coords row / world-target panel) only renders when
    # the player has at least one ship (game/fleet.py has_ships gate) — seed a
    # starter hull so page-render tests exercise the real send form.
    from game.fleet import add_planet_ships
    add_planet_ships(homeworld_id, uid, {"mule_courier": 1}, conn=conn)
    return uid


def _colonizable_field():
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_colonizable"):
                return field
    raise AssertionError("no colonizable field in sample grid")


def test_fleet_template_world_native_panel_markers():
    tpl = (ROOT / "templates" / "fleet.html").read_text(encoding="utf-8")
    for needle in (
        "data-fleet-target-block",
        "data-fleet-coords-row",
        "data-fleet-world-target",
        "data-fleet-world-target-name",
        "data-fleet-world-target-mission",
        "data-fleet-world-target-flight",
        "data-preview-target-name",
        "data-preview-target-native-type",
        "data-preview-target-coords",
    ):
        assert needle in tpl, f"missing fleet template marker: {needle}"


def test_fleet_page_world_key_prefill_shows_named_panel(gc590b_db, monkeypatch):
    import app as app_module

    dbmod.DB_PATH = gc590b_db
    models.DB_PATH = gc590b_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        conn.commit()
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    body = client.get(
        f"/fleet?mission=colonize&world_key={field['world_key']}&target_type=world_colony"
    ).get_data(as_text=True)
    assert "data-fleet-world-target" in body
    assert "data-fleet-coords-row" in body
    assert "data-fleet-world-target-mission" in body
    assert "data-fleet-world-target-flight" in body


def test_classic_fleet_without_world_key_keeps_coords_row(gc590b_db, monkeypatch):
    import app as app_module

    dbmod.DB_PATH = gc590b_db
    models.DB_PATH = gc590b_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        conn.commit()
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    body = client.get("/fleet").get_data(as_text=True)
    assert 'name="target_galaxy"' in body
    assert 'name="target_system"' in body
    assert 'name="target_position"' in body
    assert "data-fleet-coords-row" in body


def test_main_js_gc590b_world_native_contract():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    fleet = js.split("const getFleetUrlParams = ()", 1)[1]
    fleet = fleet.split("let _shipyardRefreshTimer", 1)[0]
    for needle in (
        "buildFleetTargetPayload",
        "resolveFleetWorldTargetPresentation",
        "formatFleetNamedTarget",
        "applyFleetPreviewNamedTarget",
        "renderFleetActiveTargetBlock",
        "syncFleetMissionLockUi",
        "data-fleet-target-block",
        "data-fleet-coords-row",
        "data-fleet-world-target-mission",
        "data-fleet-world-target-flight",
        "data-preview-target-name",
        "data-preview-target-native-type",
        "target_type",
        "is-mission-locked",
    ):
        assert needle in fleet, f"missing js contract: {needle}"
    payload_fn = fleet.split("const buildFleetTargetPayload = (page) => {", 1)[1]
    payload_fn = payload_fn.split("const syncFleetMissionLockUi", 1)[0]
    assert "world_key: wk" in payload_fn
    assert "target_type" in payload_fn


def test_gc590b_css_hides_coords_for_world_target():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".fleet-target-block.is-world-target .fleet-coords-row" in css
    assert ".fleet-preview-target-hero" in css
    assert ".fleet-active-coords-secondary" in css


def test_preview_includes_world_target_name_and_type(gc590b_db):
    field = _colonizable_field()
    from game.db import db
    from game.fleet import add_planet_ships

    conn = db()
    try:
        player_id = _player(conn)
        conn.execute(
            "UPDATE planets SET fuel_cells = 50000 WHERE player_id = ?;",
            (player_id,),
        )
        origin = conn.execute(
            "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()
        add_planet_ships(int(origin["id"]), player_id, {"seed_ark": 1}, conn=conn)
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
            target_type="world_colony",
        )
        wt = preview["target"]["world_target"]
        assert wt["target_world_key"] == field["world_key"]
        assert wt["target_name_key"]
        assert preview["target"].get("strategic_world", {}).get("name_key")
    finally:
        conn.close()


def test_gc590b_locale_keys_present():
    keys = (
        "fleet_world_target_mission",
        "fleet_world_target_flight",
        "fleet_preview_target_coords",
        "fleet_target_world_colony",
        "fleet_target_wreckage",
        "fleet_target_expedition_world",
    )
    for path in ("locales/en.json", "locales/de.json"):
        data = json.loads((ROOT / path).read_text(encoding="utf-8"))
        for key in keys:
            assert key in data, f"missing {key} in {path}"


def test_active_movements_include_world_target(gc590b_db):
    from game.db import db
    from game.fleet import add_planet_ships, list_active_movements, send_fleet

    field = _colonizable_field()
    conn = db()
    try:
        player_id = _player(conn)
        conn.execute(
            "UPDATE planets SET fuel_cells = 50000, metal = 50000 WHERE player_id = ?;",
            (player_id,),
        )
        origin = conn.execute(
            "SELECT * FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;",
            (player_id,),
        ).fetchone()
        add_planet_ships(int(origin["id"]), player_id, {"seed_ark": 1}, conn=conn)
        ok, reason, _result = send_fleet(
            player_id=player_id,
            origin_planet_id=int(origin["id"]),
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=int(origin["position"]),
            mission_type="colonize",
            ships={"seed_ark": 1},
            resources={},
            speed_percent=100,
            conn=conn,
            world_key=field["world_key"],
            target_type="world_colony",
        )
        assert ok, reason
        movements = list_active_movements(player_id, conn=conn)
        assert len(movements) == 1
        wt = movements[0].get("world_target") or {}
        assert wt.get("target_world_key") == field["world_key"]
        assert wt.get("target_name_key") or wt.get("target_name")
        assert wt.get("target_type") == "world_colony"
        assert wt.get("legacy_coords")
    finally:
        conn.close()
