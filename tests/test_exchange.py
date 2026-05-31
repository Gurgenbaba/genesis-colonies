"""Tests for instant resource exchange (Ferronit <-> Crytite)."""

from __future__ import annotations

import pytest

from game.models import create_user, db, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.exchange import (
    exchange_schema_ready,
    execute_exchange,
    get_exchange_config,
    get_exchange_status,
)


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
    assert cfg["rate_metal_to_crystal"] == 0.8
    assert cfg["rate_crystal_to_metal"] == 0.8
    assert cfg["daily_limit"] == 500000000
    assert cfg["min_amount"] == 100


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
        amount=1000,
        conn=conn,
    )
    assert ok, reason
    assert result["receive_amount"] == 800
    assert result["receive_resource"] == "crystal"

    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    row = cur.fetchone()
    assert int(row["metal"]) == 9000
    assert int(row["crystal"]) == 800

    cur.execute("SELECT COUNT(*) AS c FROM exchange_log WHERE player_id = ?;", (uid,))
    assert int(cur.fetchone()["c"]) == 1
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
    assert data["job"]["receive_amount"] == 400


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
    assert "gc-exchange-formula" in html
    assert "gc-fuel-exchange-panel" in html
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


def test_overview_includes_planet_teaser_widget(exchange_db, tmp_path, monkeypatch):
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
    assert "gc-planet-teaser" in html
