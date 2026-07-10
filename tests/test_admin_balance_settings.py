"""
Admin Balance settings API tests.

Run: python -m pytest tests/test_admin_balance_settings.py -v
"""

from __future__ import annotations

import pytest

from game.admin_balance import PRESET_B_BALANCE, get_balance_settings, save_balance_settings
from game.models import get_game_settings, save_game_settings


@pytest.fixture()
def admin_env(tmp_path, monkeypatch):
    db_file = tmp_path / "admin_balance_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    return db_file


@pytest.fixture()
def app_client(admin_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    import importlib
    import app as app_module

    importlib.reload(app_module)

    from game.models import create_user, ensure_player_and_homeworld

    ok_a, _, admin_info = create_user("admin_bal", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("normal_bal", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def _login(client, username, password):
    from game.models import verify_user

    user = verify_user(str(username), str(password))
    if user:
        with client.session_transaction() as sess:
            sess["user_id"] = int(user["id"])
        return user

    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_balance_get_requires_admin(app_client):
    client, _, _ = app_client
    r = client.get("/api/admin/balance")
    assert r.status_code == 401

    _login(client, "normal_bal", "userpass123")
    r = client.get("/api/admin/balance")
    assert r.status_code == 403
    assert r.get_json()["error"] == "forbidden"


def test_balance_get_ok_for_admin(app_client):
    client, _, _ = app_client
    _login(client, "admin_bal", "adminpass123")
    r = client.get("/api/admin/balance")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    settings = data["settings"]
    assert "start_metal" in settings
    assert "start_fuel_cells" in settings
    assert "score_weight_research" in settings
    assert "exchange_enabled" in settings


def test_balance_save_admin_only(app_client):
    client, _, _ = app_client
    _login(client, "normal_bal", "userpass123")
    r = client.post("/api/admin/balance", json={"start_metal": 1000})
    assert r.status_code == 403


def test_balance_save_valid_values(app_client):
    client, _, _ = app_client
    _login(client, "admin_bal", "adminpass123")
    payload = {
        "start_metal": 2500,
        "start_crystal": 1200,
        "build_speed": 1.05,
        "research_speed": 0.9,
        "queue_limit": 4,
        "research_queue_limit": 2,
        "score_weight_buildings": 1.0,
        "score_weight_research": 0.65,
        "exchange_enabled": 1,
        "exchange_rate_metal_to_crystal": 1.5,
        "exchange_rate_crystal_to_metal": 1,
        "exchange_daily_limit_min": 100000,
        "exchange_min_amount": 50,
        "production_speed": 1.0,
    }
    r = client.post("/api/admin/balance", json=payload)
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "settings" in data
    assert "hud" in data
    assert data["hud"]["ok"] is True
    assert "active_planet_id" in data["hud"]

    stored = get_game_settings()
    assert int(stored["start_metal"]) == 2500
    assert float(stored["score_weight_research"]) == pytest.approx(0.65)


def test_balance_save_rejects_unknown_keys(app_client):
    client, _, _ = app_client
    _login(client, "admin_bal", "adminpass123")
    r = client.post("/api/admin/balance", json={"start_metal": 1000, "evil_key": 1})
    assert r.status_code == 400
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "invalid_settings"
    assert "unknown_keys" in data["message"]


def test_balance_save_rejects_negative_values(app_client):
    client, _, _ = app_client
    _login(client, "admin_bal", "adminpass123")
    r = client.post("/api/admin/balance", json={"start_metal": -100})
    assert r.status_code == 400
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "invalid_settings"

    r2 = client.post("/api/admin/balance", json={"build_speed": 0})
    assert r2.status_code == 400
    assert r2.get_json()["ok"] is False


def test_balance_preset_b_applies_values(app_client):
    client, _, _ = app_client
    _login(client, "admin_bal", "adminpass123")

    save_game_settings({"start_metal": 99999, "build_speed": 5.0})

    r = client.post("/api/admin/balance/preset-b", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "hud" in data
    assert data["hud"]["ok"] is True

    settings = data["settings"]
    assert settings["start_metal"] == PRESET_B_BALANCE["start_metal"]
    assert settings["start_crystal"] == PRESET_B_BALANCE["start_crystal"]
    assert settings["build_speed"] == pytest.approx(PRESET_B_BALANCE["build_speed"])
    assert settings["research_speed"] == pytest.approx(PRESET_B_BALANCE["research_speed"])
    assert settings["score_weight_research"] == pytest.approx(PRESET_B_BALANCE["score_weight_research"])

    stored = get_game_settings()
    assert int(stored["research_queue_limit"]) == PRESET_B_BALANCE["research_queue_limit"]


def test_balance_save_unchanged_form_payload(app_client):
    """Simulate Balance Speichern with unchanged form values (all keys as strings)."""
    client, _, _ = app_client
    _login(client, "admin_bal", "adminpass123")
    r = client.get("/api/admin/balance")
    assert r.status_code == 200
    settings = r.get_json()["settings"]
    payload = {key: str(value) for key, value in settings.items()}
    r2 = client.post("/api/admin/balance", json=payload)
    assert r2.status_code == 200
    data = r2.get_json()
    assert data["ok"] is True
    assert "settings" in data
    assert "hud" in data
    assert data["hud"]["ok"] is True
    assert int(data["hud"]["active_planet_id"]) > 0


def test_ranking_recalculate_admin_only(app_client):
    client, _, _ = app_client
    _login(client, "normal_bal", "userpass123")
    r = client.post("/api/admin/rankings/recalculate", json={})
    assert r.status_code == 403

    _login(client, "admin_bal", "adminpass123")
    r = client.post("/api/admin/rankings/recalculate", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "players_updated" in data


def test_save_balance_settings_unit():
    _, err = save_balance_settings({"queue_limit": 0})
    assert err is not None

    settings, err = save_balance_settings({"start_metal": 100})
    assert err is None
    assert settings["start_metal"] == 100

    settings, err = save_balance_settings({
        "fuel_exchange_metal_per_unit": "2,5",
        "fuel_exchange_crystal_per_unit": "1.25",
    })
    assert err is None
    assert settings["fuel_exchange_metal_per_unit"] == pytest.approx(2.5)
    assert settings["fuel_exchange_crystal_per_unit"] == pytest.approx(1.25)


def test_score_weight_research_default_on_fresh_db(admin_env):
    import game.db as gdb
    from game.models import DEFAULT_GAME_SETTINGS, init_db

    gdb._DB_PATH = None
    init_db()

    settings = get_game_settings()
    assert float(settings["score_weight_research"]) == pytest.approx(
        float(DEFAULT_GAME_SETTINGS["score_weight_research"])
    )
    assert float(settings["score_weight_research"]) == pytest.approx(0.01)


def test_score_weight_research_admin_override_not_reset_by_init_db(admin_env):
    import game.db as gdb
    from game.models import init_db

    gdb._DB_PATH = None
    init_db()
    save_game_settings({"score_weight_research": "0.65"})
    init_db()

    settings = get_game_settings()
    assert float(settings["score_weight_research"]) == pytest.approx(0.65)
