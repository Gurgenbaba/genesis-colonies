"""Trader Hub game-state and planet scoping tests."""

from __future__ import annotations

import importlib
import os

import pytest

from game import db as gdb
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db


@pytest.fixture
def trader_hub_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trader_hub_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _login_client(trader_hub_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    conn = db()
    ok, err, user = create_user(f"th_{os.getpid()}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return client, uid


def test_game_state_includes_trader_panels(trader_hub_db, monkeypatch):
    client, _uid = _login_client(trader_hub_db, monkeypatch)
    res = client.get("/api/game-state")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "exchange" in data
    assert data["exchange"].get("enabled") is True
    assert "fuel_exchange" in data
    assert data["fuel_exchange"].get("ready") is True
    assert "scrapyard" in data
    assert data["scrapyard"].get("ready") is True


def test_trader_hub_uses_active_planet_resources(trader_hub_db, monkeypatch):
    client, uid = _login_client(trader_hub_db, monkeypatch)
    conn = db()
    planets = get_planets_by_player(uid, conn=conn)
    assert len(planets) >= 1
    pid = int(planets[0]["id"])
    conn.execute("UPDATE planets SET metal = 4242, crystal = 5353 WHERE id = ?;", (pid,))
    conn.commit()
    conn.close()

    res = client.get("/trader-hub")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "4.242" in html or "4242" in html
    assert "5.353" in html or "5353" in html
