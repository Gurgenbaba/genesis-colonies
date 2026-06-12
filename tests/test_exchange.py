"""Tests for instant resource exchange (Ferronit <-> Crytite)."""

from __future__ import annotations

import pytest

from game.models import create_user, db, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.exchange import (
    exchange_schema_ready,
    execute_exchange,
    get_exchange_config,
    get_exchange_status,
    resolve_exchange_daily_limit,
)
from game.models import get_homeworld


@pytest.fixture
def exchange_db(tmp_path, monkeypatch):
    db_path = tmp_path / "exchange_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    from game import db as gdb

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
    ok, err, user = create_user(f"ex_user_{id(conn)}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Trader", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def test_exchange_schema_ready(exchange_db):
    conn = db()
    assert exchange_schema_ready(conn) is True
    conn.close()


def test_exchange_config_defaults(exchange_db):
    cfg = get_exchange_config()
    assert cfg["enabled"] is True
    assert cfg["rate_metal_to_crystal"] == 0.85
    assert cfg["rate_crystal_to_metal"] == 0.85
    assert cfg["daily_limit_admin"] == 50000000000
    assert cfg["daily_limit_pct"] == 80.0
    assert cfg["daily_limit_min"] == 25000000
    assert cfg["daily_limit_max"] == 50000000000
    assert cfg["min_amount"] == 100
    assert cfg["fuel_metal_per_unit"] == 20
    assert cfg["fuel_crystal_per_unit"] == 14


def test_exchange_metal_to_crystal(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 10000, crystal = 0 WHERE id = ?;", (pid,))
    conn.commit()

    ok, reason, result = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="metal",
        to_resource="crystal",
        amount=1000,
        conn=conn,
    )
    assert ok, reason
    assert result["receive_amount"] == 850
    assert result["receive_resource"] == "crystal"

    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    row = cur.fetchone()
    assert int(row["metal"]) == 9000
    assert int(row["crystal"]) == 850

    cur.execute("SELECT COUNT(*) AS c FROM exchange_log WHERE player_id = ?;", (uid,))
    assert int(cur.fetchone()["c"]) == 1
    conn.close()


def test_exchange_same_resource_rejected(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])

    ok, reason, _ = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="metal",
        to_resource="metal",
        amount=1000,
        conn=conn,
    )
    assert not ok
    assert reason == "invalid_resource"
    conn.close()


def test_exchange_fuel_cells_to_metal(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 0, crystal = 0, fuel_cells = 100 WHERE id = ?;", (pid,))
    conn.commit()

    ok, reason, result = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="fuel_cells",
        to_resource="metal",
        amount=10,
        conn=conn,
    )
    assert ok, reason
    assert result["receive_amount"] == 200
    assert result["receive_resource"] == "metal"

    cur.execute("SELECT metal, fuel_cells FROM planets WHERE id = ?;", (pid,))
    row = cur.fetchone()
    assert int(row["metal"]) == 200
    assert int(row["fuel_cells"]) == 90
    conn.close()


def test_fuel_production_respects_storage_cap(exchange_db):
    import time

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planet_buildings
        SET fuel_cell_plant = 5, fuel_storage = 1, solar_plant = 5
        WHERE planet_id = ?;
        """,
        (pid,),
    )
    status = get_exchange_status(
        player_id=uid,
        planet_id=pid,
        metal=0,
        crystal=0,
        fuel_cells=0,
        conn=conn,
    )
    fuel_cap = int(status["storage"].get("fuel_cells") or 0)
    assert fuel_cap > 0
    cur.execute("SELECT * FROM planets WHERE id = ?;", (pid,))
    planet = dict(cur.fetchone())
    planet["fuel_cells"] = fuel_cap
    planet["last_update"] = time.time() - 3600
    conn.commit()

    from game.resources import update_planet_resources

    update_planet_resources(planet, conn=conn, skip_queue_finish=True)
    conn.commit()
    cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,))
    assert int(cur.fetchone()["fuel_cells"]) == fuel_cap
    conn.close()


def test_exchange_metal_to_fuel_cells(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 10000, fuel_cells = 0 WHERE id = ?;", (pid,))
    conn.commit()

    ok, reason, result = execute_exchange(
        player_id=uid,
        planet_id=pid,
        direction="metal_to_fuel_cells",
        from_resource="metal",
        amount=200,
        conn=conn,
    )
    assert ok, reason
    assert result["receive_amount"] == 10
    assert result["receive_resource"] == "fuel_cells"

    cur.execute("SELECT metal, fuel_cells FROM planets WHERE id = ?;", (pid,))
    row = cur.fetchone()
    assert int(row["metal"]) == 9800
    assert int(row["fuel_cells"]) == 10
    conn.close()


def test_exchange_fuel_cells_uncapped(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET crystal = 100000, fuel_cells = 0 WHERE id = ?;", (pid,))
    conn.commit()

    ok, reason, _ = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="crystal",
        to_resource="fuel_cells",
        amount=2800,
        conn=conn,
    )
    assert ok, reason

    cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,))
    assert int(cur.fetchone()["fuel_cells"]) == 200
    conn.close()


def test_exchange_allows_storage_overflow(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    status = get_exchange_status(
        player_id=uid,
        planet_id=pid,
        metal=0,
        crystal=100000,
        fuel_cells=0,
        conn=conn,
    )
    metal_cap = int(status["storage"].get("metal") or 0)
    assert metal_cap > 0

    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = 100000 WHERE id = ?;",
        (metal_cap, pid),
    )
    conn.commit()

    ok, reason, result = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="crystal",
        to_resource="metal",
        amount=1000,
        conn=conn,
    )
    assert ok, reason
    assert result["receive_amount"] == 850

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,))
    metal_after = int(cur.fetchone()["metal"])
    assert metal_after == metal_cap + 850
    assert metal_after > metal_cap
    conn.close()


def test_exchange_insufficient_balance(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 50, crystal = 0 WHERE id = ?;", (pid,))
    conn.commit()

    ok, reason, _ = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="metal",
        amount=1000,
        conn=conn,
    )
    assert not ok
    assert reason == "insufficient_balance"
    conn.close()


def test_exchange_below_minimum(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])

    ok, reason, _ = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="metal",
        amount=50,
        conn=conn,
    )
    assert not ok
    assert reason == "below_minimum"
    conn.close()


def test_exchange_daily_limit(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('exchange_daily_limit', '50000');"
    )
    cur.execute("UPDATE planets SET metal = 200000, crystal = 0 WHERE id = ?;", (pid,))
    conn.commit()

    ok1, _, _ = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="metal",
        amount=50000,
        conn=conn,
    )
    assert ok1

    ok2, reason, _ = execute_exchange(
        player_id=uid,
        planet_id=pid,
        from_resource="metal",
        amount=100,
        conn=conn,
    )
    assert not ok2
    assert reason == "daily_limit_exceeded"
    conn.close()


def test_exchange_api_route(exchange_db, tmp_path, monkeypatch):
    import importlib
    import os

    import app as app_module

    db_path = os.environ.get("GC_DB_PATH")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as dbmod
    import game.models as models

    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert login.status_code in (200, 302)

    res = client.post(
        "/api/exchange",
        json={"direction": "metal_to_crystal", "amount": 500},
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["job"]["receive_amount"] == 425


def test_trader_hub_page_includes_exchange_panel(exchange_db, tmp_path, monkeypatch):
    import importlib
    import os

    import app as app_module

    db_path = os.environ.get("GC_DB_PATH")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as dbmod
    import game.models as models

    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    res = client.get("/trader-hub")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "trader-hub-page" in html
    assert "gc-exchange-panel" in html
    assert "trader-hub-footer" not in html
    assert "gc-exchange-formula" in html
    assert "gc-exchange-route-select" in html
    assert "gc-fuel-exchange-panel" not in html
    assert "gc-scrapyard-panel" in html


def test_overview_page_excludes_exchange_panel(exchange_db, tmp_path, monkeypatch):
    import importlib
    import os

    import app as app_module

    db_path = os.environ.get("GC_DB_PATH")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as dbmod
    import game.models as models

    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    res = client.get("/overview")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "gc-exchange-form" not in html


def test_overview_excludes_planet_teaser_widget(exchange_db, tmp_path, monkeypatch):
    import importlib
    import os

    import app as app_module

    db_path = os.environ.get("GC_DB_PATH")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as dbmod
    import game.models as models

    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    importlib.reload(app_module)

    conn = dbmod.db()
    ok, err, user = models.create_user(f"ov_pe_{os.getpid()}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    models.ensure_player_and_homeworld(uid, conn=conn)
    pid = int(models.get_planets_by_player(uid, conn=conn)[0]["id"])
    conn.execute("UPDATE planets SET planet_level = 5, planet_xp = 500 WHERE id = ?;", (pid,))
    conn.commit()
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    res = client.get("/overview")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "gc-planet-teaser" not in html
    assert "overview-res-dashboard" in html
    assert "overview-warnings-panel" not in html
    assert "overview-upgrade-section" not in html
    assert "overview-log-panel" not in html
    assert "img/res/Ferronit.png" in html


def test_exchange_daily_limit_uses_empire_production_floor(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    status = get_exchange_status(
        player_id=uid,
        planet_id=int(get_planets_by_player(uid, conn=conn)[0]["id"]),
        metal=0,
        crystal=0,
        fuel_cells=0,
        conn=conn,
    )
    conn.close()
    assert status["daily_limit"] == 25_000_000
    assert status["empire_production_day_total"] >= 0
    assert status["daily_limit_pct"] == 80.0


def test_exchange_daily_limit_scales_with_production(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    hw = get_homeworld(player_id=uid, conn=conn)
    conn.execute(
        """
        UPDATE planet_buildings
        SET metal_mine = 30, crystal_mine = 25, fuel_cell_plant = 20, solar_plant = 30
        WHERE planet_id = ?;
        """,
        (int(hw["id"]),),
    )
    conn.commit()
    block = resolve_exchange_daily_limit(uid, conn=conn)
    conn.close()
    assert block["empire_production_day_total"] > 100_000
    assert block["daily_limit_scaled"] == int(block["empire_production_day_total"] * 80 / 100)
    assert block["daily_limit"] >= 25_000_000
    assert block["daily_limit"] <= 50_000_000_000


def test_exchange_daily_limit_respects_admin_cap(exchange_db):
    conn = db()
    uid = _player(conn=conn)
    conn.execute(
        "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('exchange_daily_limit', '75000');"
    )
    conn.commit()
    block = resolve_exchange_daily_limit(uid, conn=conn)
    conn.close()
    assert block["daily_limit"] == 75_000


def test_trader_hub_shows_limit_breakdown(exchange_db, tmp_path, monkeypatch):
    import importlib
    import os

    import app as app_module

    db_path = os.environ.get("GC_DB_PATH")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as dbmod
    import game.models as models

    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    res = client.get("/trader-hub")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "trader-hub-daily-panel" in html
    assert "data-exchange-daily-used" in html
    assert "data-exchange-empire-day" in html
    assert "trader_hub_daily_formula" in html or "Empire-Produktion" in html or "empire production" in html.lower()
