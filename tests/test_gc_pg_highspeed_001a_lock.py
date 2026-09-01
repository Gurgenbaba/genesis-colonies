"""GC-PG-HIGHSPEED-001A — lock_busy on planet switch (no HTTP 500)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from game.models import get_homeworld
from game.planet_evolution.service import set_active_planet

pytest_plugins = ["tests.test_planet_registry"]


def test_set_active_planet_lock_busy_returns_reason(switcher_db):
    from tests.test_planet_registry import _create_player

    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id)["id"])

    class LockExc(Exception):
        pass

    lock_exc = LockExc("canceling statement due to lock timeout")

    with patch(
        "game.planet_evolution.service.set_active_planet_id",
        side_effect=lock_exc,
    ), patch(
        "game.planet_evolution.service.is_db_lock_error",
        return_value=True,
    ):
        ok, reason = set_active_planet(player_id, hw_id)
    assert ok is False
    assert reason == "lock_busy"


def test_api_planets_active_lock_busy_is_409(switcher_db, monkeypatch):
    from tests.test_planet_registry import _app_client, _create_player, _login

    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id)["id"])
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)

    with patch(
        "game.planet_evolution.service.set_active_planet",
        return_value=(False, "lock_busy"),
    ):
        resp = client.post("/api/planets/active", json={"planet_id": hw_id})
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["ok"] is False
    assert body["reason"] == "lock_busy"
    assert body.get("retry") is True
