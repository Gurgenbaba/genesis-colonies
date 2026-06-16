"""GC-592G — Command Center open-colony action visibility."""

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
from game.planet_evolution.command_center import (
    build_colony_command_center,
    build_expedition_site_command_center,
    build_foreign_colony_command_center,
    build_strategic_world_command_center,
)
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.strategic_worlds import build_strategic_world_field

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


def _field_with(predicate):
    for wx in range(600, 5000, 47):
        for wy in range(600, 5000, 53):
            field = build_strategic_world_field(float(wx), float(wy))
            if predicate(field):
                return field
    raise AssertionError("no matching strategic world field")


def _colonizable_field():
    return _field_with(lambda f: f.get("is_colonizable") and not f.get("is_expedition"))


def _expedition_field():
    return _field_with(lambda f: f.get("world_type") == "expedition_zone")


@pytest.fixture()
def gc592g_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc592g.db"
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
    ok, err, user = create_user(f"gc592g_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    conn.commit()
    return uid


def _primary_action_key(cc: dict) -> str:
    action = cc.get("primary_action") or {}
    return str(action.get("action_key") or "")


def test_own_colony_has_open_colony_action(gc592g_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    try:
        player_id = _player(conn)
        hw = get_homeworld(player_id, conn=conn)
        assert hw
        cc = build_colony_command_center(
            int(hw["id"]),
            player_id,
            conn=conn,
            role_key="homeworld",
            is_homeworld=True,
        )
    finally:
        conn.close()

    assert cc.get("is_own") is True
    assert cc.get("planet_id") == int(hw["id"])
    action = cc.get("primary_action") or {}
    assert action.get("action_key") == "open_colony"
    assert action.get("planet_id") == int(hw["id"])
    assert action.get("enabled") is True


def test_landmark_has_no_open_colony_action(gc592g_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        payload = build_command_map_payload(player_id, conn=conn)
        landmarks = [n for n in payload["nodes"] if n.get("node_kind") == "landmark"]
        assert landmarks
        for node in landmarks:
            cc = node.get("command_center") or {}
            assert _primary_action_key(cc) != "open_colony"
            assert cc.get("primary_action", {}).get("action_key") != "open_colony"
    finally:
        conn.close()


def test_strategic_world_has_no_open_colony_action(gc592g_db):
    from game.db import db

    field = _colonizable_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_strategic_world_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("panel_kind") == "strategic_world"
    assert _primary_action_key(cc) != "open_colony"
    assert cc.get("primary_action", {}).get("action_key") in ("colonize", "none")


def test_expedition_site_has_no_open_colony_action(gc592g_db):
    from game.db import db

    field = _expedition_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_expedition_site_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("panel_kind") == "expedition_site"
    assert _primary_action_key(cc) != "open_colony"
    assert cc.get("primary_action", {}).get("action_key") in ("expedition", "salvage", "none")


def test_foreign_colony_has_no_open_colony_action(gc592g_db):
    from game.db import db

    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        node = {
            "node_kind": "foreign_world_colony",
            "node_key": "foreign_world:field:test:100:200",
            "owner_player_id": owner_id,
            "owner_username": "Rival",
            "planet_id": 999,
            "world_key": "field:mining_world:100:200",
            "name": "Rival Outpost",
        }
        cc = build_foreign_colony_command_center(node, viewer_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("panel_kind") == "foreign_colony"
    assert "primary_action" not in cc
    assert _primary_action_key(cc) != "open_colony"


def test_js_render_does_not_fallback_to_open_colony():
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "function ccOpenColonyAction" in js
    assert "function syncOpenColonyButton" in js

    render_colony = js.split("function renderColonyCommandCenter")[1].split("async function refreshCcSalvageState")[0]
    assert "openColonyBtn.hidden = false" not in render_colony

    show_colony = js.split("GC.showCommandMapColonyPanel = function showCommandMapColonyPanel")[1].split(
        "GC.showCommandMapStrategicWorldPanel = function"
    )[0]
    assert "openColonyBtn.hidden = false" not in show_colony

    render_panel = js.split("function renderCommandCenterPanel")[1].split("function hideSiteInspector")[0]
    assert 'panelKind === "colony"' in render_panel
    assert 'cc.panel_kind || "colony"' not in render_panel
    assert "syncOpenColonyButton(cc)" in render_panel

    open_click = js.split("async function onOpenColonyClick")[1].split("openColonyBtn?.addEventListener")[0]
    assert "openColonyBtn.hidden" in open_click
    assert "action_key" in js.split("function ccOpenColonyAction")[1].split("function syncOpenColonyButton")[0]
