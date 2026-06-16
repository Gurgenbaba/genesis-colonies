"""GC-560 — Empire identity layer tests."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, get_homeworld, get_planets_by_player, init_db, save_planet_buildings
from game.planet_evolution.empire_identity import (
    build_colonies_identity,
    derive_colony_role_key,
    empire_identity_for_planet,
)
from game.planet_evolution.service import colonize_planet, list_player_planets_for_switcher

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def empire_identity_db(tmp_path, monkeypatch):
    db_file = tmp_path / "empire_identity.db"
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


def _create_player() -> int:
    uname = f"emp_id_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def test_new_homeworld_default_name_is_genesis_ark(empire_identity_db):
    player_id = _create_player()
    hw = get_homeworld(player_id=player_id)
    assert hw is not None
    assert hw["name"] == "Genesis Ark"


def test_homeworld_identity_payload(empire_identity_db):
    player_id = _create_player()
    hw = dict(get_homeworld(player_id=player_id))
    from game.db import db

    conn = db()
    try:
        identity = empire_identity_for_planet(hw, conn=conn)
    finally:
        conn.close()

    assert identity["empire_role_key"] == "homeworld"
    assert identity["empire_role_icon"] == "🏛"
    assert identity["empire_subtitle_key"] == "empire_homeworld_subtitle"
    assert identity["identity_title_key"] == "empire_homeworld_subtitle"


def test_derive_mining_role_from_buildings(empire_identity_db):
    player_id = _create_player()
    ok, reason, data = colonize_planet(player_id, name="Vega Prime")
    assert ok, reason
    colony_id = int(data["planet_id"])

    save_planet_buildings(colony_id, {"metal_mine": 8, "crystal_mine": 6, "research_lab": 1})

    from game.db import db

    conn = db()
    try:
        role = derive_colony_role_key(colony_id, conn=conn)
    finally:
        conn.close()
    assert role == "mining"


def test_derive_research_role_from_buildings(empire_identity_db):
    player_id = _create_player()
    ok, reason, data = colonize_planet(player_id, name="Helios Gate")
    assert ok, reason
    colony_id = int(data["planet_id"])

    save_planet_buildings(colony_id, {"research_lab": 9, "academy": 4, "metal_mine": 1})

    from game.db import db

    conn = db()
    try:
        role = derive_colony_role_key(colony_id, conn=conn)
    finally:
        conn.close()
    assert role == "research"


def test_derive_shipyard_role_from_buildings(empire_identity_db):
    player_id = _create_player()
    ok, reason, data = colonize_planet(player_id, name="Titan Forge")
    assert ok, reason
    colony_id = int(data["planet_id"])

    save_planet_buildings(colony_id, {"orbital_shipyard": 7, "metal_mine": 1})

    from game.db import db

    conn = db()
    try:
        role = derive_colony_role_key(colony_id, conn=conn)
    finally:
        conn.close()
    assert role == "shipyard"


def test_empire_identity_prefers_planet_role_over_buildings(empire_identity_db):
    player_id = _create_player()
    ok, reason, data = colonize_planet(player_id, name="World Colony")
    assert ok, reason
    colony_id = int(data["planet_id"])

    from game.db import db

    conn = db()
    try:
        conn.execute(
            "UPDATE planets SET planet_role = ? WHERE id = ?;",
            ("fortress_world", colony_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM planets WHERE id = ?;", (colony_id,)).fetchone()
        identity = empire_identity_for_planet(dict(row), conn=conn)
    finally:
        conn.close()

    assert identity["empire_role_key"] == "fortress"
    assert identity["empire_role_label_key"] == "empire_role_fortress"


def test_switcher_payload_includes_identity_fields(empire_identity_db):
    player_id = _create_player()
    ok, reason, _ = colonize_planet(player_id, name="Outpost")
    assert ok, reason

    planets = list_player_planets_for_switcher(player_id)
    assert len(planets) >= 2

    hw = next(p for p in planets if p["is_homeworld"])
    colony = next(p for p in planets if not p["is_homeworld"])

    for key in (
        "empire_role_key",
        "empire_role_label_key",
        "empire_role_icon",
        "empire_subtitle_key",
        "identity_title_key",
    ):
        assert key in hw
        assert key in colony

    assert hw["empire_role_key"] == "homeworld"
    assert colony["empire_role_key"] in {"mining", "research", "shipyard", "fortress", "trade", "frontier", "general"}


def test_build_colonies_identity_orders_homeworld_first(empire_identity_db):
    player_id = _create_player()
    ok, reason, _ = colonize_planet(player_id, name="Beta")
    assert ok, reason
    ok, reason, _ = colonize_planet(player_id, name="Alpha")
    assert ok, reason

    from game.db import db

    conn = db()
    try:
        rows = build_colonies_identity(player_id, conn=conn)
    finally:
        conn.close()

    assert rows
    assert rows[0]["is_homeworld"] is True
    assert rows[0]["empire_role_key"] == "homeworld"


def test_galaxy_command_map_view_renders_colonies(empire_identity_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = empire_identity_db
    models.DB_PATH = empire_identity_db
    import app as app_module

    importlib.reload(app_module)

    uname = f"gal_imp_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    player_id = int(user["id"])

    ok, reason, _ = colonize_planet(player_id, name="Outpost Alpha")
    assert ok, reason

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    resp = client.get("/galaxy?view=command_map")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "galaxy-view-tab" in body
    assert "galaxy-command-map-graph" in body
    assert "galaxy-command-map-node--hub" in body
    assert "galaxy-command-map-list" not in body
    assert "data-empire-identity-switch" in body
    assert "Genesis Ark" in body
    assert "Outpost Alpha" in body
    assert "galaxy-slots" not in body

    # Legacy alias
    resp_legacy = client.get("/galaxy?view=imperium")
    assert resp_legacy.status_code == 200
    assert "galaxy-command-map-panel" in resp_legacy.get_data(as_text=True)


def test_empire_page_unchanged_without_identity_card(empire_identity_db, monkeypatch):
    import importlib

    dbmod.DB_PATH = empire_identity_db
    models.DB_PATH = empire_identity_db
    import app as app_module

    importlib.reload(app_module)

    uname = f"emp_chk_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/empire").get_data(as_text=True)
    assert "galaxy-command-map-panel" not in body
    assert "empire-prod-panel" in body
    assert "empire-identity-panel" not in body


def test_existing_homeworld_name_not_overwritten(empire_identity_db):
    player_id = _create_player()
    hw = get_homeworld(player_id=player_id)
    custom_name = "My Custom HQ"
    from game.db import db

    conn = db()
    try:
        conn.execute("UPDATE planets SET name = ? WHERE id = ?;", (custom_name, int(hw["id"])))
        conn.commit()
        identity = build_colonies_identity(player_id, conn=conn)
    finally:
        conn.close()

    hw_row = next(row for row in identity if row["is_homeworld"])
    assert hw_row["name"] == custom_name
    assert hw_row["empire_subtitle_key"] == "empire_homeworld_subtitle"
