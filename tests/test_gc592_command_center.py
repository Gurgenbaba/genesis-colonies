"""GC-592A — Command Center panel for own colonies on the World Map."""

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
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.command_center import (
    attach_command_centers_to_nodes,
    build_colony_command_center,
    build_expedition_site_command_center,
    build_foreign_colony_command_center,
    build_strategic_world_command_center,
    expedition_site_kind,
    is_expedition_site_node,
)
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import complete_world_claim, reserve_world_claim

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"

GC592_LOCALE_KEYS = (
    "command_center_aria",
    "command_center_empty_title",
    "command_center_empty_hint",
    "command_center_section_resources",
    "command_center_section_fleets",
    "command_center_section_status",
    "command_center_colony_level",
    "command_center_colony_xp_remaining",
    "command_center_queue_idle",
    "command_center_section_actions",
    "command_center_section_news",
    "command_center_section_details",
    "command_center_section_progress",
    "command_center_section_action",
    "command_center_section_hints",
    "command_center_fleet_ready",
    "command_center_news_empty",
    "command_center_progress_empty",
    "command_center_hints_empty",
    "command_center_section_intel",
    "command_center_foreign_status_empire",
    "command_center_foreign_observe",
    "command_center_foreign_public_hint",
    "command_center_expedition_status_expedition_zone",
    "command_center_expedition_status_anomaly_zone",
    "command_center_expedition_status_ruins_world",
    "command_center_expedition_status_wreckage_field",
    "command_center_expedition_count",
    "command_center_expedition_unavailable_hint",
)

_FOREIGN_FORBIDDEN = frozenset(
    {
        "resources",
        "fleets",
        "quick_actions",
        "news",
        "production",
        "defense",
        "ships",
    }
)


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


def _anomaly_field():
    return _field_with(lambda f: f.get("world_type") == "anomaly_zone")


def _ruins_field():
    return _field_with(lambda f: f.get("world_type") == "ruins_world")


def _salvage_field():
    return _field_with(lambda f: f.get("world_type") == "wreckage_field" or f.get("is_salvage"))


@pytest.fixture()
def gc592_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc592.db"
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
    ok, err, user = create_user(f"gc592_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    conn.commit()
    return uid


def test_gc592_locale_keys_present():
    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    for key in GC592_LOCALE_KEYS:
        assert key in de, f"missing de locale key {key}"
        assert key in en, f"missing en locale key {key}"


def test_gc592_stylesheet_and_js_contract():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert ".gc-command-center-action-grid" in css
    assert ".gc-command-center-resource-row" in css
    assert ".gc-command-center-detail-list" in css
    assert "renderCommandCenterPanel" in js
    assert "renderColonyQueueRow" in js
    assert "renderSidebarHud" in js
    assert "command_center_hud_idle" in js
    assert "data-command-center-coord" in js
    assert "formatCcFleetLabel" in js
    assert "showCommandMapStrategicWorldPanel" in js
    assert "renderExpeditionSiteCommandCenter" in js or "expedition_site" in js


def test_build_colony_command_center_own_homeworld(gc592_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    try:
        player_id = _player(conn)
        hw = get_homeworld(player_id, conn=conn)
        assert hw
        planet_id = int(hw["id"])
        cc = build_colony_command_center(planet_id, player_id, conn=conn, role_key="homeworld", is_homeworld=True)
    finally:
        conn.close()

    assert cc.get("planet_id") == planet_id
    assert cc.get("panel_kind") == "colony"
    assert cc.get("is_own") is True
    assert cc.get("name")
    assert cc.get("role_label_key")
    assert cc.get("role_icon")
    assert cc.get("coordinates_formatted")
    progress = cc.get("progress") or {}
    assert progress.get("level", 0) >= 1
    assert isinstance(cc.get("queues"), list)
    assert len(cc.get("queues") or []) == 3
    action = cc.get("primary_action") or {}
    assert action.get("action_key") == "open_colony"
    assert action.get("planet_id") == planet_id
    resources = cc.get("resources") or []
    assert len(resources) == 3
    assert {row["short"] for row in resources} == {"Fe", "Cr", "Fuel"}
    for row in resources:
        assert "amount" in row
        assert row["rate"].endswith("/h")

    fleets = cc.get("fleets") or []
    assert fleets
    assert fleets[0].get("icon")

    actions = cc.get("quick_actions") or []
    assert len(actions) >= 4
    slots = {row["action_key"] for row in actions}
    assert "buildings" in slots
    assert "fleet" in slots
    assert "research" in slots
    assert "evolution" in slots

    assert isinstance(cc.get("news"), list)


def test_build_colony_command_center_rejects_foreign_planet(gc592_db):
    from game.db import db

    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        from game.models import get_homeworld

        hw = get_homeworld(owner_id, conn=conn)
        assert hw
        planet_id = int(hw["id"])
        cc = build_colony_command_center(planet_id, viewer_id, conn=conn)
        assert cc == {}
    finally:
        conn.close()


def test_command_map_payload_includes_command_center(gc592_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        payload = build_command_map_payload(player_id, conn=conn)
        own = [
            n
            for n in payload["nodes"]
            if n.get("node_kind", "colony") == "colony" and n.get("is_own", True)
        ]
        assert own
        cc = own[0].get("command_center") or {}
        assert cc.get("resources")
        assert cc.get("quick_actions")
    finally:
        conn.close()


def test_attach_command_centers_skips_foreign_colonies(gc592_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        nodes = [
            {"node_kind": "colony", "is_own": True, "planet_id": 1, "empire_role_key": "general", "actions": []},
            {"node_kind": "colony", "is_own": False, "planet_id": 2, "empire_role_key": "general"},
            {"node_kind": "world_field", "world_key": ""},
        ]
        attach_command_centers_to_nodes(nodes, player_id, conn=conn)
        assert "command_center" in nodes[0]
        assert "command_center" not in nodes[1]
        assert "command_center" not in nodes[2]
    finally:
        conn.close()


def test_galaxy_template_renders_command_center_shell(gc592_db, monkeypatch):
    import app as app_module

    dbmod.DB_PATH = gc592_db
    models.DB_PATH = gc592_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    uname = f"gc592_ui_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map").get_data(as_text=True)

    assert "galaxy-command-map-graph--fullmap" in body
    assert "gc-world-inspector-modal" in body
    assert "data-colony-location-inspect" in body
    assert "data-command-center" in body
    assert "galaxy-command-map-legacy-shell" in body
    assert "gc-command-center-hud" not in body


def test_build_strategic_world_command_center_colonize(gc592_db):
    from game.db import db

    field = _colonizable_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_strategic_world_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("panel_kind") == "strategic_world"
    assert cc.get("world_key") == field["world_key"]
    assert cc.get("details")
    action = cc.get("primary_action") or {}
    assert action.get("action_key") == "colonize"
    assert action.get("label_key") == "strategic_world_btn_colonize"
    assert action.get("enabled") is True


def test_build_strategic_world_command_center_expedition_familiarity(gc592_db):
    from game.db import db

    field = _expedition_field()
    field["expedition_count"] = 3
    field["familiarity_status"] = "mapped"
    field["familiarity_label_key"] = "world_familiarity_mapped"
    field["next_milestone"] = 5
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_strategic_world_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("primary_action", {}).get("action_key") == "expedition"
    assert cc.get("panel_kind") == "expedition_site"
    assert cc.get("site_kind") == expedition_site_kind(field)
    fam = cc.get("familiarity") or {}
    assert fam.get("expedition_count") == 3
    assert fam.get("next_milestone") == 5
    assert cc.get("status_key") == f"command_center_expedition_status_{expedition_site_kind(field)}"


def test_build_expedition_site_anomaly_payload(gc592_db):
    from game.db import db

    field = _anomaly_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_expedition_site_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("panel_kind") == "expedition_site"
    assert cc.get("site_kind") == "anomaly_zone"
    assert cc.get("risk_key")
    assert cc.get("primary_action", {}).get("action_key") == "expedition"


def test_build_expedition_site_ruins_progress(gc592_db):
    from game.db import db

    field = _ruins_field()
    field["expedition_count"] = 7
    field["familiarity_status"] = "stabilized"
    field["familiarity_label_key"] = "world_familiarity_stabilized"
    field["next_milestone"] = 10
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_expedition_site_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("site_kind") == "ruins_world"
    fam = cc.get("familiarity") or {}
    assert fam.get("expedition_count") == 7
    assert fam.get("next_milestone") == 10


def test_build_expedition_site_wreckage_salvage(gc592_db):
    from game.db import db

    field = _salvage_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_expedition_site_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("site_kind") == "wreckage_field"
    assert cc.get("primary_action", {}).get("action_key") == "salvage"
    hint_keys = [row.get("label_key") for row in (cc.get("hints") or [])]
    assert "strategic_world_inspector_salvage_prepare" in hint_keys
    assert cc.get("familiarity") is None


def test_build_strategic_world_command_center_unavailable(gc592_db):
    from game.db import db

    field = build_strategic_world_field(2400.0, 2600.0)
    field["is_colonizable"] = False
    field["is_expedition"] = False
    field["is_salvage"] = False
    field["is_expedition_prepared"] = False
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_strategic_world_command_center(field, player_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("primary_action", {}).get("action_key") == "none"
    hint_keys = [row.get("label_key") for row in (cc.get("hints") or [])]
    assert "strategic_world_inspector_noncolonizable_hint" in hint_keys


def test_command_map_payload_includes_world_field_command_center(gc592_db):
    from game.db import db

    conn = db()
    try:
        player_id = _player(conn)
        payload = build_command_map_payload(player_id, conn=conn)
        fields = [n for n in payload["nodes"] if n.get("node_kind") == "world_field"]
        assert fields
        with_cc = [n for n in fields if n.get("command_center")]
        assert with_cc
        kinds = {n["command_center"].get("panel_kind") for n in with_cc}
        assert "strategic_world" in kinds or "expedition_site" in kinds
    finally:
        conn.close()


def test_galaxy_template_renders_world_field_command_center_source(gc592_db, monkeypatch):
    import app as app_module

    dbmod.DB_PATH = gc592_db
    models.DB_PATH = gc592_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    uname = f"gc592b_ui_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/galaxy?view=command_map").get_data(as_text=True)

    assert "data-world-field-source" in body
    assert "data-world-field-inspect" in body
    assert "data-command-center" in body


def _claim_world_colony(conn, player_id, field, *, name="Rival Outpost", system=407, position=5):
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
    return int(extra["planet_id"]), str(field["world_key"])


def test_build_foreign_command_center_public_only(gc592_db):
    from game.db import db

    field = _colonizable_field()
    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        planet_id, world_key = _claim_world_colony(conn, owner_id, field)
        node = {
            "node_kind": "foreign_world_colony",
            "node_key": f"foreign_world:{world_key}",
            "owner_player_id": owner_id,
            "owner_username": "Rival",
            "planet_id": planet_id,
            "world_key": world_key,
            "name": "Rival Outpost",
            "coordinates_formatted": "1:407:5",
            "strategic_type_key": field.get("type_key") or "",
            "empire_role_label_key": "empire_role_mining",
            "empire_role_icon": "⛏",
        }
        cc = build_foreign_colony_command_center(node, viewer_id, conn=conn)
    finally:
        conn.close()

    assert cc.get("panel_kind") == "foreign_colony"
    assert cc.get("world_key") == world_key
    for key in _FOREIGN_FORBIDDEN:
        assert key not in cc
    assert cc.get("details")
    assert "owner_player_id" not in cc


def test_foreign_command_center_spy_and_attack_actions(gc592_db):
    from game.db import db

    field = _colonizable_field()
    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        planet_id, world_key = _claim_world_colony(conn, owner_id, field)
        node = {
            "node_kind": "foreign_world_colony",
            "node_key": f"foreign_world:{world_key}",
            "owner_player_id": owner_id,
            "owner_username": "Rival",
            "planet_id": planet_id,
            "world_key": world_key,
            "name": "Rival Outpost",
        }
        cc = build_foreign_colony_command_center(node, viewer_id, conn=conn)
    finally:
        conn.close()

    actions = {row["action_key"]: row for row in (cc.get("actions") or [])}
    spy = actions.get("spy") or {}
    attack = actions.get("attack") or {}
    assert spy.get("target_type") == "enemy_colony"
    assert attack.get("target_type") == "enemy_colony"
    assert spy.get("world_key") == world_key
    assert attack.get("world_key") == world_key
    assert spy.get("enabled") is True
    assert actions.get("observe", {}).get("enabled") is False


def test_foreign_command_center_rejects_own_and_viewer(gc592_db):
    from game.db import db

    conn = db()
    try:
        viewer_id = _player(conn)
        node = {
            "node_kind": "foreign_world_colony",
            "owner_player_id": viewer_id,
            "planet_id": 1,
            "world_key": "field:mining_world:100:200",
        }
        assert build_foreign_colony_command_center(node, viewer_id, conn=conn) == {}
    finally:
        conn.close()


def test_command_map_foreign_world_colony_has_command_center(gc592_db):
    from game.db import db

    field = _colonizable_field()
    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        _claim_world_colony(conn, owner_id, field)
        payload = build_command_map_payload(viewer_id, conn=conn)
        foreign = [
            n
            for n in payload["nodes"]
            if n.get("node_kind") == "foreign_world_colony"
            and n.get("world_key") == field["world_key"]
        ]
        assert len(foreign) == 1
        cc = foreign[0].get("command_center") or {}
        assert cc.get("panel_kind") == "foreign_colony"
        assert not any(k in cc for k in _FOREIGN_FORBIDDEN)
    finally:
        conn.close()


def test_galaxy_template_renders_foreign_command_center_source(gc592_db, monkeypatch):
    import app as app_module

    field = _colonizable_field()
    from game.db import db

    conn = db()
    owner_id = None
    viewer_id = None
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        _claim_world_colony(conn, owner_id, field)
    finally:
        conn.close()

    dbmod.DB_PATH = gc592_db
    models.DB_PATH = gc592_db
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = viewer_id

    body = client.get("/galaxy?view=command_map").get_data(as_text=True)
    assert "data-foreign-colony-source" in body
    assert f'foreign_world:{field["world_key"]}' in body or field["world_key"] in body
