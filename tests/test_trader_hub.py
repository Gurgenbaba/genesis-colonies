"""Trader Hub game-state and planet scoping tests."""

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
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture
def trader_hub_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trader_hub_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
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
    yield db_path


def _login_client(trader_hub_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uname = f"th_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return client, uid


def test_game_state_includes_trader_panels(trader_hub_db, monkeypatch):
    client, _uid = _login_client(trader_hub_db, monkeypatch)
    res = client.get("/api/game-state?include_panel=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "exchange" in data
    assert data["exchange"].get("enabled") is True
    assert "fuel_metal_per_unit" in data["exchange"]
    assert "balances" in data["exchange"]
    assert "fuel_cells" in data["exchange"]["balances"]
    assert "fuel_exchange" not in data
    assert "scrapyard" in data
    assert data["scrapyard"].get("ready") is True


def test_game_state_exchange_limit_scales_without_hardcap(trader_hub_db, monkeypatch):
    client, uid = _login_client(trader_hub_db, monkeypatch)

    def _prod(_player_id, *, conn=None):
        return {
            "metal_per_day": 82_000_000_000,
            "crystal_per_day": 0,
            "fuel_cells_per_day": 0,
            "total_per_day": 82_000_000_000,
        }

    monkeypatch.setattr("game.empire_page.get_empire_production_aggregate", _prod)

    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO game_settings (key, value) VALUES ('exchange_daily_limit_min', '0');"
    )
    conn.commit()
    conn.close()

    res = client.get("/api/game-state?include_panel=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["exchange"]["daily_limit"] == 65_600_000_000
    assert "daily_limit_admin_cap" not in data["exchange"]
    assert "daily_limit_max" not in data["exchange"]


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
