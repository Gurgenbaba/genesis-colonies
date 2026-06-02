"""Header planet switcher and Planet Evolution UI cleanup."""

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
from game.models import create_user, get_homeworld, init_db, save_planet_buildings
from game.planet_evolution.service import colonize_planet, list_player_planets_for_switcher, set_active_planet

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def switcher_db(tmp_path, monkeypatch):
    db_file = tmp_path / "header_switcher.db"
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


def _create_player() -> tuple[int, str]:
    uname = f"hdr_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"]), uname


def _second_planet(player_id: int) -> int:
    ok, reason, extra = colonize_planet(
        player_id,
        name=f"Colony_{uuid.uuid4().hex[:4]}",
        galaxy=1,
        system=301,
        position=4,
    )
    assert ok, reason
    return int(extra["planet_id"])


def _app_client(monkeypatch):
    import app as app_mod

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def test_list_player_planets_for_switcher_includes_coords(switcher_db):
    player_id, _ = _create_player()
    colony_id = _second_planet(player_id)
    planets = list_player_planets_for_switcher(player_id)
    assert len(planets) == 2
    by_id = {int(p["planet_id"]): p for p in planets}
    assert by_id[colony_id]["coordinates_formatted"]
    assert by_id[colony_id]["planet_class_label_key"]


def test_header_shows_switcher_with_all_planets(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    resp = client.get("/overview")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "gc-planet-switcher" in body
    assert "gc-planet-switcher-menu" in body
    assert f'data-planet-id="{colony_id}"' in body
    assert f'data-planet-id="{hw_id}"' in body


def test_header_single_planet_no_menu(switcher_db, monkeypatch):
    _, uname = _create_player()
    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/overview").get_data(as_text=True)
    assert "gc-planet-switcher" in body
    assert 'data-multi="0"' in body
    assert "gc-planet-switcher-menu" not in body


def test_api_set_active_updates_state_and_overview(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)

    save_planet_buildings(hw_id, {"metal_mine": 2, "solar_plant": 1})
    save_planet_buildings(colony_id, {"metal_mine": 9, "solar_plant": 1})

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    ok, reason = set_active_planet(player_id, colony_id)
    assert ok, reason

    r = client.post(
        "/api/planets/active",
        json={"planet_id": hw_id},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["state"]["active_planet_id"] == hw_id
    assert int(data["state"]["buildings"]["metal_mine"]) == 2
    assert isinstance(data.get("planets"), list)
    assert len(data["planets"]) == 2

    gs = client.get("/api/game-state").get_json()
    assert gs["active_planet_id"] == hw_id
    assert gs.get("active_planet", {}).get("name")
    assert int(data["state"]["player"]["metal"]) == int(data["state"]["resources"]["metal"])
    assert "buildings_panel" in data["state"]


def test_api_planets_active_switch_returns_fresh_colony_resources(monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)

    from game.models import db

    conn = db()
    conn.execute("UPDATE planets SET metal = 100, crystal = 50 WHERE id = ?;", (hw_id,))
    conn.execute("UPDATE planets SET metal = 9000, crystal = 8000 WHERE id = ?;", (colony_id,))
    conn.commit()
    conn.close()

    ok, reason = set_active_planet(player_id, colony_id)
    assert ok, reason

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    r = client.post(
        "/api/planets/active",
        json={"planet_id": hw_id},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    st = body["state"]
    assert st["active_planet_id"] == hw_id
    assert int(st["resources"]["metal"]) == 100
    assert int(st["player"]["metal"]) == 100


def test_planet_evolution_template_no_switch_or_colonize_ui():
    tpl = (ROOT / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    assert "pe-colony-bar" not in tpl
    assert "pe-planet-btn" not in tpl
    assert "pe-colonize-btn" not in tpl


def test_main_js_header_planet_switcher_bound():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "initHeaderPlanetSwitcher" in src
    assert "GC.updateHeaderPlanetSwitcherFromState" in src
    assert "rebuildHeaderPlanetSwitcher" in src
    assert "applyPlanetLandscapeFromState" in src
    assert "gc-has-planet-landscape" in src
    assert "reloadPageForActivePlanet" in src
    assert "getDomPlanetId" in src
    assert "trader-hub-page" in src
    assert 'force: true' in src
    assert ".pe-planet-btn" not in src


def test_trader_hub_template_scoped_to_active_planet():
    tpl = (ROOT / "templates" / "trader_hub.html").read_text(encoding="utf-8")
    assert 'id="trader-hub-page"' in tpl
    assert "data-planet-id" in tpl
    assert "HEADER_ACTIVE_PLANET" in tpl


def test_landscape_css_uses_gc_bg_layer():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "gc-has-planet-landscape" in css
    assert "gc-has-planet-landscape .gc-bg" in css
    assert '[style*="--planet-landscape"]::before' not in css


def test_base_template_landscape_class():
    tpl = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "gc-has-planet-landscape" in tpl
    assert "current_planet_landscape_url" in tpl


def test_overview_injects_planet_landscape_css_var(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw = get_homeworld(player_id=player_id)
    hw_pos = int(hw.get("position") or 1)
    from game.planet_visuals import get_landscape_for_position

    expected_fn = get_landscape_for_position(hw_pos)

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    body = client.get("/overview").get_data(as_text=True)
    assert "--planet-landscape:" in body
    assert f"img/landscapes/{expected_fn}" in body


def test_game_state_includes_planets_list(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    colony_id = _second_planet(player_id)

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    gs = client.get("/api/game-state").get_json()
    assert gs.get("ok") is True
    planets = gs.get("planets") or []
    assert len(planets) == 2
    ids = {int(p["planet_id"]) for p in planets}
    assert colony_id in ids


def test_game_state_includes_landscape_url(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    colony_id = _second_planet(player_id)

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    set_active_planet(player_id, colony_id)
    gs = client.get("/api/game-state").get_json()
    ap = gs.get("active_planet") or {}
    assert ap.get("position") == 4
    assert ap.get("landscape_url")
    assert "trockenplanet08-h.jpg" in ap["landscape_url"]


def test_trader_hub_and_shipyard_render_active_planet_id(switcher_db, monkeypatch):
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)

    client = _app_client(monkeypatch)
    client.post("/login", data={"username": uname, "password": "test-pass-123"})

    set_active_planet(player_id, colony_id)
    trader = client.get("/trader-hub", headers={"X-PJAX": "true"}).get_data(as_text=True)
    assert f'data-planet-id="{colony_id}"' in trader

    set_active_planet(player_id, hw_id)
    shipyard = client.get("/shipyard", headers={"X-PJAX": "true"}).get_data(as_text=True)
    assert f'data-planet-id="{hw_id}"' in shipyard
