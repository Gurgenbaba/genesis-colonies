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


def test_trader_hub_uses_active_planet_scope(trader_hub_db, monkeypatch):
    """Trader Hub shows no duplicate resource strip; planet scope via data-planet-id."""
    client, uid = _login_client(trader_hub_db, monkeypatch)
    conn = db()
    planets = get_planets_by_player(uid, conn=conn)
    assert len(planets) >= 1
    pid = int(planets[0]["id"])
    conn.close()

    res = client.get("/trader-hub")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert f'data-planet-id="{pid}"' in html
    assert "trader-hub-resources" not in html
    assert "data-res-bar=" not in html
    assert 'data-res="metal"' not in html


def test_trader_hub_uses_genesis_window_layout(trader_hub_db, monkeypatch):
    client, _uid = _login_client(trader_hub_db, monkeypatch)
    res = client.get("/trader-hub")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "trader-hub-shell" in html
    assert "trader-hub-panels" in html
    assert "data-trader-hub-tab" in html
    assert "data-trader-hub-panel=\"exchange\"" in html
    assert "data-trader-hub-panel=\"scrapyard\"" in html
    assert "data-trader-hub-panel=\"collector\"" in html
    assert "trader-hub-subpanel" in html
    assert "trader-hub-daily-panel" in html
    assert "data-exchange-daily-used" in html
    assert "gc-exchange-panel" in html
    assert "gc-scrapyard-panel" in html
    assert "gc-scrapyard-card-grid" in html
    # Daily formula lives on exchange panel only (not above all tabs).
    exchange_idx = html.find('data-trader-hub-panel="exchange"')
    scrap_idx = html.find('data-trader-hub-panel="scrapyard"')
    daily_idx = html.find("trader-hub-daily-panel")
    assert exchange_idx != -1 and scrap_idx != -1 and daily_idx != -1
    assert exchange_idx < daily_idx < scrap_idx
    assert "trader-hub-layout" not in html
    assert "trader-hub-resources" not in html
    assert "gc-trader-panel" in html
    scrap_tpl = (ROOT / "templates" / "partials" / "scrapyard_panel.html").read_text(encoding="utf-8")
    assert "gc-scrapyard-refund" in scrap_tpl
    assert "fmt_int_compact" in scrap_tpl
    js = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "_traderHubSelectTab" in js
    assert "formatNumberCompact(minVal)" in js


def test_trader_hub_contrast_css_contract():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(encoding="utf-8")
    assert "GC-TRADER-HUB-CONTRAST" in css
    assert ".trader-hub-shell.gc-panel::before" in css
    chunk = css.split("GC-TRADER-HUB-CONTRAST")[1].split(".trader-hub-shell .trader-hub-status-panel")[0]
    assert "opacity: 1" in chunk
    assert "filter: none" in chunk
    tiles = css.split(".trader-hub-page .gc-trader-resource-tile.is-disabled")[1].split("}")[0]
    assert "opacity: 0.45" in tiles
    assert "pointer-events: none" in tiles
    active = css.split(".trader-hub-page .gc-trader-resource-tile.is-active")[1].split("}")[0]
    assert "box-shadow" in active
