"""GC-582D — Claimed strategic worlds become map colonies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.strategic_worlds import (
    STRATEGIC_WORLD_TYPE_DEFS,
    build_strategic_world_field,
    empire_role_key_for_planet_role,
)
from game.planet_evolution.world_colonization import (
    COLONIZABLE_WORLD_TYPES,
    complete_world_claim,
    reserve_world_claim,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

GC582D_LOCALE_KEYS = (
    "command_map_world_colony_hint",
    "fleet_world_target_hint",
    "fleet_world_target_kicker",
    "fleet_target_strategic_world",
    "strategic_world_btn_colonize",
    "strategic_world_colony_limit",
    "strategic_world_type_trade_world",
    "strategic_world_promise_trade_world",
    "strategic_world_reward_trade_world",
    "strategic_world_future_trade_world",
)


@pytest.fixture()
def gc582d_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc582d.db"
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
    ok, err, user = create_user(f"gc582d_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    conn.commit()
    return uid


def _colonizable_field():
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_colonizable"):
                return field
    raise AssertionError("no colonizable field in sample grid")


def _claim_world_colony(conn, player_id, field, *, name="Map Colony", system=403, position=4):
    ok, reason, payload = reserve_world_claim(
        player_id,
        field["_world_x"],
        field["_world_y"],
        conn=conn,
    )
    assert ok, reason
    ok_col, col_reason, extra = colonize_planet(
        player_id,
        name=name,
        galaxy=1,
        system=system,
        position=position,
        world_binding={
            "world_key": payload["world_key"],
            "world_x": payload["world_x"],
            "world_y": payload["world_y"],
            "sector_x": payload["sector_x"],
            "sector_y": payload["sector_y"],
            "planet_role": payload["planet_role"],
            "origin_world_key": payload["world_key"],
        },
        conn=conn,
    )
    assert ok_col, col_reason
    complete_world_claim(field["world_key"], player_id, int(extra["planet_id"]), conn=conn)
    conn.commit()
    return extra["planet_id"]


def test_empire_role_mapping_for_planet_roles():
    assert empire_role_key_for_planet_role("mining_world") == "mining"
    assert empire_role_key_for_planet_role("industrial_world") == "shipyard"
    assert empire_role_key_for_planet_role("research_world") == "research"
    assert empire_role_key_for_planet_role("fortress_world") == "fortress"
    assert empire_role_key_for_planet_role("trade_world") == "trade"
    assert empire_role_key_for_planet_role("ruins_world") == "frontier"
    assert empire_role_key_for_planet_role("unknown") == "general"


def test_colonizable_world_types_have_strategic_metadata():
    for world_type in COLONIZABLE_WORLD_TYPES:
        meta = STRATEGIC_WORLD_TYPE_DEFS.get(world_type)
        assert meta, f"{world_type} missing STRATEGIC_WORLD_TYPE_DEFS"
        assert meta.get("type_key"), world_type


def test_gc582d_locale_keys_present():
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    for key in GC582D_LOCALE_KEYS:
        assert key in de, f"missing de locale key {key}"
        assert key in en, f"missing en locale key {key}"


def test_gc582d_stylesheet_and_js_contract():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert ".galaxy-command-map-node--world-colony" in css
    assert ".galaxy-command-map-node--foreign-world-colony" in css
    assert "renderCommandCenterPanel" in js
    assert "data-command-center" in js
    tpl = (ROOT / "templates" / "partials" / "galaxy_command_map_panel.html").read_text(encoding="utf-8")
    assert 'data-world-colony="1"' in tpl


def test_claimed_world_field_removed_and_colony_placed(gc582d_db):
    field = _colonizable_field()
    world_key = field["world_key"]
    wx = float(field["_world_x"])
    wy = float(field["_world_y"])

    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        ok, reason, payload = reserve_world_claim(player_id, wx, wy, conn=conn)
        assert ok, reason
        binding = {
            "world_key": payload["world_key"],
            "world_x": payload["world_x"],
            "world_y": payload["world_y"],
            "sector_x": payload["sector_x"],
            "sector_y": payload["sector_y"],
            "planet_role": payload["planet_role"],
            "origin_world_key": payload["world_key"],
        }
        ok_col, col_reason, extra = colonize_planet(
            player_id,
            name="Helios Outpost",
            galaxy=1,
            system=401,
            position=2,
            world_binding=binding,
            conn=conn,
        )
        assert ok_col, col_reason
        complete_world_claim(world_key, player_id, int(extra["planet_id"]), conn=conn)
        conn.commit()

        before_fields = [
            n
            for n in build_command_map_payload(player_id, conn=conn)["nodes"]
            if n.get("node_kind") == "world_field" and n.get("world_key") == world_key
        ]
        assert before_fields == []

        colony_nodes = [
            n
            for n in build_command_map_payload(player_id, conn=conn)["nodes"]
            if n.get("node_kind") == "colony" and n.get("world_key") == world_key
        ]
        assert len(colony_nodes) == 1
        node = colony_nodes[0]
        assert node.get("world_map_bound") is True
        assert node["world_x"] == pytest.approx(wx, abs=1.0)
        assert node["world_y"] == pytest.approx(wy, abs=1.0)
        assert node["planet_role"] == field["world_type"]
        assert node["empire_role_key"] == empire_role_key_for_planet_role(field["world_type"])
        assert node.get("strategic_type_key")
        assert node.get("is_own") is True
        assert node.get("actions")
        assert len(node["actions"]) >= 1
    finally:
        conn.close()


def test_own_world_colony_not_duplicated_in_cluster_orbit(gc582d_db):
    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        planet_id = _claim_world_colony(conn, player_id, field)
        nodes = build_command_map_payload(player_id, conn=conn)["nodes"]
        world_nodes = [
            n
            for n in nodes
            if n.get("node_kind") == "colony"
            and int(n.get("planet_id") or 0) == int(planet_id)
        ]
        assert len(world_nodes) == 1
        assert world_nodes[0].get("world_map_bound") is True
        assert world_nodes[0].get("layout_slot") == "world_colony"
    finally:
        conn.close()


def test_foreign_claim_not_shown_as_free_field(gc582d_db):
    field = _colonizable_field()
    world_key = field["world_key"]
    from game.db import db

    conn = db()
    try:
        viewer_id = _player(conn)
        owner_id = _player(conn)
        _claim_world_colony(conn, owner_id, field, name="Rival Outpost", system=404, position=5)
        payload = build_command_map_payload(viewer_id, conn=conn)
        fields = [
            n
            for n in payload["nodes"]
            if n.get("node_kind") == "world_field" and n.get("world_key") == world_key
        ]
        foreign = [
            n
            for n in payload["nodes"]
            if n.get("node_kind") == "foreign_world_colony" and n.get("world_key") == world_key
        ]
        assert fields == []
        assert len(foreign) == 1
        assert foreign[0].get("owner_player_id") == owner_id
        assert foreign[0].get("world_x") == pytest.approx(float(field["_world_x"]), abs=1.0)
        assert foreign[0].get("world_y") == pytest.approx(float(field["_world_y"]), abs=1.0)
    finally:
        conn.close()


def test_legacy_colony_stays_in_cluster_orbit(gc582d_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        ok, reason, extra = colonize_planet(
            player_id,
            name="Legacy Outpost",
            galaxy=1,
            system=402,
            position=3,
            conn=conn,
        )
        assert ok, reason
        conn.commit()

        nodes = build_command_map_payload(player_id, conn=conn)["nodes"]
        legacy = next(n for n in nodes if int(n.get("planet_id") or 0) == int(extra["planet_id"]))
        assert not legacy.get("world_map_bound")
        assert legacy.get("world_key") in (None, "")
    finally:
        conn.close()


def test_galaxy_template_renders_world_colony_marker(gc582d_db, monkeypatch):
    import importlib

    import app as app_module

    field = _colonizable_field()
    from game.db import db

    conn = db()
    planet_id = None
    try:
        player_id = _player(conn)
        planet_id = _claim_world_colony(conn, player_id, field, name="Map Colony")
    finally:
        conn.close()

    dbmod.DB_PATH = gc582d_db
    models.DB_PATH = gc582d_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    body = client.get("/galaxy?view=command_map").get_data(as_text=True)
    assert "galaxy-command-map-node--world-colony" in body
    assert f'data-world-key="{field["world_key"]}"' in body
    assert 'data-world-colony="1"' in body
    assert "data-command-center-resources" in body
    assert f'data-colony-actions-source="{planet_id}"' in body
    assert field["world_type"] in body or "Bergbauwelt" in body or "Mining world" in body


def test_galaxy_template_renders_foreign_world_colony(gc582d_db, monkeypatch):
    import importlib

    import app as app_module

    field = _colonizable_field()
    from game.db import db

    conn = db()
    try:
        viewer_id = _player(conn)
        owner_id = _player(conn)
        _claim_world_colony(conn, owner_id, field, name="Rival Outpost", system=405, position=6)
    finally:
        conn.close()

    dbmod.DB_PATH = gc582d_db
    models.DB_PATH = gc582d_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = viewer_id

    body = client.get("/galaxy?view=command_map").get_data(as_text=True)
    assert "galaxy-command-map-node--foreign-world-colony" in body
    assert "Rival Outpost" in body
    assert "data-foreign-world-colony-inspect" in body
    assert f'data-strategic-world-key="{field["world_key"]}"' not in body
