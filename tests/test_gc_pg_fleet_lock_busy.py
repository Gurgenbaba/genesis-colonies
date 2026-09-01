"""GC-PG-HIGHSPEED — fleet send/preview soft lock_busy (no HTTP 500)."""

from __future__ import annotations

import inspect
from unittest.mock import patch

from game.fleet import build_fleet_send_preview
from game.models import get_homeworld
from game.resources import update_planet_resources

pytest_plugins = ["tests.test_planet_registry"]


def test_fleet_preview_validate_skips_resource_persist():
    src = inspect.getsource(build_fleet_send_preview)
    assert "persist_resources=False" in src


def test_update_planet_resources_persist_false_skips_save(switcher_db):
    from tests.test_planet_registry import _create_player

    player_id, _ = _create_player()
    hw = dict(get_homeworld(player_id))
    with patch("game.resources.save_planet") as save_mock:
        planet, *_ = update_planet_resources(hw, skip_queue_finish=True, persist=False)
    assert int(planet["id"]) == int(hw["id"])
    save_mock.assert_not_called()


def test_update_planet_resources_persist_false_no_lock(switcher_db, monkeypatch):
    from tests.test_planet_registry import _create_player

    player_id, _ = _create_player()
    hw = dict(get_homeworld(player_id))
    calls = []

    def _boom(*_a, **_k):
        calls.append("lock")
        raise AssertionError("FOR UPDATE must not run on persist=False")

    monkeypatch.setattr("game.db.lock_planet_for_update", _boom)
    planet, *_ = update_planet_resources(hw, skip_queue_finish=True, persist=False)
    assert int(planet["metal"]) >= 0
    assert calls == []


def test_api_fleet_send_lock_busy_is_409(switcher_db, monkeypatch):
    from tests.test_planet_registry import _app_client, _create_player, _login

    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id)["id"])
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)

    with patch(
        "app._fleet_write_transaction",
        return_value=(False, "lock_busy", {"retry": True}),
    ):
        resp = client.post(
            "/api/fleet/send",
            json={
                "origin_planet_id": hw_id,
                "target_galaxy": 1,
                "target_system": 1,
                "target_position": 2,
                "mission_type": "transport",
                "ships": {"light_fighter": 1},
                "resources": {},
                "speed_percent": 100,
            },
        )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "lock_busy"
    assert body.get("retry") is True


def test_fleet_write_transaction_maps_lock_error(switcher_db, monkeypatch):
    import app as app_mod

    class LockExc(Exception):
        pass

    def _boom(_conn):
        raise LockExc("canceling statement due to lock timeout")

    with patch.object(app_mod, "db") as db_mock, patch.object(
        app_mod, "begin_write_transaction"
    ), patch.object(app_mod, "rollback"), patch.object(app_mod, "commit"), patch(
        "game.db.is_db_lock_error",
        return_value=True,
    ):
        conn = db_mock.return_value
        conn.close = lambda: None
        ok, reason, result = app_mod._fleet_write_transaction(_boom)
    assert ok is False
    assert reason == "lock_busy"
    assert (result or {}).get("retry") is True
