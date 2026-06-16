"""Fuel Cells (Brennzellen) resource bar and game-state tests."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

import game.db as gdb
from game.db import db
from game.fleet import send_fleet
from game.fleet_defs import FLEET_FUEL_RESOURCE
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, get_planets_by_player, init_db
from game.planet_evolution.service import colonize_planet
from game.shipyard import build_ship


@pytest.fixture
def fuel_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fuel_res.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"fc_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def test_game_state_includes_fuel_cells(fuel_db, monkeypatch):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    uid = _player()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get("/api/game-state")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "fuel_cells" in data["player"]
    assert "fuel_cells" in data["resources"]
    assert float(data["player"]["fuel_cells"]) >= 0
    assert "fuel_cell_plant" in data.get("production_per_hour", {})


def test_base_template_shows_fuel_cells_panel():
    root = Path(__file__).resolve().parent.parent
    html = (root / "templates" / "base.html").read_text(encoding="utf-8")
    css = (root / "static" / "style.css").read_text(encoding="utf-8")
    assert "hud-res-fuel-cells" in html
    assert "res-value fuel_cells" in html
    assert "res-cap fuel_cells" in html
    assert "hud-res-no-storage" not in html
    assert "repeat(4, minmax(0, 1fr))" in css


def test_main_js_patches_fuel_cells():
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "main.js").read_text(encoding="utf-8")
    assert "function applyGameStateData" in js
    assert "function patchShellHudLiveResources" in js
    assert 'bar.querySelectorAll(".res-value.fuel_cells")' in js
    assert 'bar.querySelectorAll(".res-cap.fuel_cells")' in js
    assert "prodFuelCells" in js
    assert "buildingIconUrl" in js
    assert "syncResourceLiveBaseline" in js
    assert "tickLiveResourceBar" in js
    assert "projectLiveResourceAmounts" in js
    assert "projectLiveResourceAmount" in js
    assert "Overflow (trader/scrapyard/rewards)" in js


def test_fuel_overflow_not_trimmed_on_production_tick(fuel_db):
    from game.resources import update_planet_resources

    conn = db()
    uid = _player(conn=conn)
    planet = dict(get_homeworld(player_id=uid, conn=conn))
    pid = int(planet["id"])
    overflow_amount = 5_000_000
    cur = conn.cursor()
    cur.execute(
        "UPDATE planet_buildings SET fuel_cell_plant = 10, solar_plant = 10 WHERE planet_id = ?;",
        (pid,),
    )
    cur.execute(
        "UPDATE planets SET fuel_cells = ?, last_update = ? WHERE id = ?;",
        (overflow_amount, time.time() - 7200, pid),
    )
    conn.commit()
    cur.execute("SELECT * FROM planets WHERE id = ?;", (pid,))
    planet = dict(cur.fetchone())
    update_planet_resources(planet, conn=conn)
    conn.commit()
    after = int(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    conn.close()
    assert after >= overflow_amount


def test_fuel_cell_plant_production_increases_balance(fuel_db):
    from game.resources import update_planet_resources

    conn = db()
    uid = _player(conn=conn)
    planet = dict(get_homeworld(player_id=uid, conn=conn))
    pid = int(planet["id"])
    cur = conn.cursor()
    cur.execute(
        "UPDATE planet_buildings SET fuel_cell_plant = 2, fuel_storage = 1, metal_mine = 0, crystal_mine = 0, solar_plant = 5 WHERE planet_id = ?;",
        (pid,),
    )
    cur.execute("UPDATE planets SET fuel_cells = 100, last_update = ? WHERE id = ?;", (time.time() - 3600, pid))
    conn.commit()
    before = float(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    cur.execute("SELECT * FROM planets WHERE id = ?;", (pid,))
    planet = dict(cur.fetchone())
    update_planet_resources(planet, conn=conn)
    conn.commit()
    after = float(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    conn.close()
    assert after >= before


def test_fleet_send_reduces_fuel_cells(fuel_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 50000 WHERE id = ?;",
        (pid,),
    )
    cur.execute("UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;", (pid,))
    conn.commit()
    from game.fleet import add_planet_ships

    add_planet_ships(pid, uid, {"mule_courier": 5}, conn=conn)
    ok_col, _, extra = colonize_planet(uid, name="Fuel Test II", galaxy=1, system=301, position=8, conn=conn)
    assert ok_col, extra
    colony2 = int(extra["planet_id"])
    cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (colony2,))
    row = cur.fetchone()
    tg, ts, tp = int(row["galaxy"]), int(row["system"]), int(row["position"])
    before = float(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=tg,
        target_system=ts,
        target_position=tp,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert ok, reason
    after = float(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    conn.close()
    assert FLEET_FUEL_RESOURCE == "fuel_cells"
    assert after < before


def test_shipyard_build_reduces_fuel_cells(fuel_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 200000, crystal = 200000, fuel_cells = 500 WHERE id = ?;",
        (pid,),
    )
    cur.execute("UPDATE planet_buildings SET orbital_shipyard = 2 WHERE planet_id = ?;", (pid,))
    cur.executemany(
        "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, ?, ?);",
        [(uid, "engine_tech", 3), (uid, "navigation_tech", 3)],
    )
    conn.commit()
    before = float(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    ok, reason, _ = build_ship(
        player_id=uid, planet_id=pid, ship_key="solar_skiff", amount=1, conn=conn
    )
    assert ok, reason
    after = float(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    conn.close()
    assert after < before


def test_missing_fuel_cells_defaults_safe(fuel_db, monkeypatch):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    uid = _player()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get("/api/game-state")
    data = r.get_json()
    assert data["ok"] is True
    assert float(data["player"].get("fuel_cells", 0)) >= 0
    assert float(data["resources"].get("fuel_cells", 0)) >= 0
