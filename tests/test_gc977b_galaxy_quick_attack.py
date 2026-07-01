"""GC-977B — Galaxy quick attack via existing fleet presets."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path

import pytest

from game.db import commit, db
from game.fleet import (
    add_planet_ships,
    create_preset,
    filter_galaxy_attack_presets,
    get_planet_ships,
    is_galaxy_attack_preset,
    resolve_galaxy_quick_attack,
)
from game.galaxy import get_planet_coordinates
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
from tests.test_galaxy import _foreign_planet_in_system, _galaxy_client


pytest_plugins = ("tests.test_galaxy",)


def test_is_galaxy_attack_preset_filters():
    assert is_galaxy_attack_preset({"preset_type": "raid", "mission_type": None})
    assert is_galaxy_attack_preset({"preset_type": "farm", "mission_type": None})
    assert is_galaxy_attack_preset({"preset_type": "custom", "mission_type": "attack"})
    assert not is_galaxy_attack_preset({"preset_type": "spy", "mission_type": "spy"})
    assert not is_galaxy_attack_preset({"preset_type": "transport", "mission_type": "transport"})


def test_filter_galaxy_attack_presets_skips_empty_ships(galaxy_db):
    presets = [
        {"id": 1, "preset_type": "raid", "ships": {"falcon_interceptor": 5}},
        {"id": 2, "preset_type": "raid", "ships": {}},
        {"id": 3, "preset_type": "spy", "ships": {"veil_probe": 1}},
        {"id": 4, "preset_type": "custom", "mission_type": "attack", "ships": {"falcon_interceptor": 2}},
    ]
    filtered = filter_galaxy_attack_presets(presets)
    assert [p["id"] for p in filtered] == [1, 4]


def test_resolve_galaxy_quick_attack_from_raid_preset(galaxy_db):
    ok, err, user = create_user(f"qa_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    pid = int(user["id"])
    ensure_player_and_homeworld(pid, player_name="QuickAtk")
    ok, reason, preset = create_preset(
        pid,
        name="Raid Alpha",
        preset_type="raid",
        ships_json={"falcon_interceptor": 12},
        speed_percent=80,
        mission_type="attack",
    )
    assert ok, reason
    ok2, reason2, meta = resolve_galaxy_quick_attack(pid, int(preset["id"]))
    assert ok2 is True
    assert reason2 == ""
    assert meta["ships"] == {"falcon_interceptor": 12}
    assert meta["speed_percent"] == 80
    assert meta["resources"] == {}
    assert meta["preset_name"] == "Raid Alpha"


def test_resolve_galaxy_quick_attack_rejects_spy_preset(galaxy_db):
    ok, err, user = create_user(f"qa_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    pid = int(user["id"])
    ensure_player_and_homeworld(pid, player_name="QuickAtk")
    ok, reason, preset = create_preset(
        pid,
        name="Spy",
        preset_type="spy",
        ships_json={"veil_probe": 1},
        mission_type="spy",
    )
    assert ok, reason
    ok2, reason2, _meta = resolve_galaxy_quick_attack(pid, int(preset["id"]))
    assert not ok2
    assert reason2 == "invalid_preset_type"


def test_api_fleet_presets_galaxy_attack_filter(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    client, pid = _galaxy_client(monkeypatch)
    create_preset(pid, name="Raid", preset_type="raid", ships_json={"falcon_interceptor": 5})
    create_preset(pid, name="Spy", preset_type="spy", ships_json={"veil_probe": 1})
    create_preset(pid, name="Farm", preset_type="farm", ships_json={"falcon_interceptor": 3})

    res = client.get("/api/fleet/presets?galaxy_attack=1")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    names = {p["name"] for p in body["data"]["presets"]}
    assert names == {"Raid", "Farm"}


def test_api_fleet_galaxy_quick_attack_send(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    origin_pid = int(planet["id"])
    viewer_coords = get_planet_coordinates(planet)
    g, s = int(viewer_coords["galaxy"]), int(viewer_coords["system"])
    _foreign_uid, _foreign_pid, foreign_coords = _foreign_planet_in_system(
        g, s, avoid_position=int(viewer_coords["position"])
    )
    fp = int(foreign_coords["position"])

    ok, reason, preset = create_preset(
        uid,
        name="Raid Beta",
        preset_type="raid",
        ships_json={"falcon_interceptor": 4},
        speed_percent=100,
        mission_type="attack",
    )
    assert ok, reason

    conn = db()
    try:
        add_planet_ships(origin_pid, uid, {"falcon_interceptor": 10}, conn=conn)
        commit(conn)
    finally:
        conn.close()

    res = client.post(
        "/api/fleet/send",
        json={
            "origin_planet_id": origin_pid,
            "mission_type": "attack",
            "galaxy_quick_attack": True,
            "preset_id": int(preset["id"]),
            "target_galaxy": g,
            "target_system": s,
            "target_position": fp,
        },
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    meta = body["data"]["galaxy_quick_attack"]
    assert meta["preset_name"] == "Raid Beta"
    assert meta["ships"] == {"falcon_interceptor": 4}

    conn = db()
    try:
        assert int(get_planet_ships(origin_pid, conn=conn).get("falcon_interceptor", 0)) == 6
    finally:
        conn.close()


def test_api_fleet_galaxy_quick_attack_not_enough_ships(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    origin_pid = int(planet["id"])
    viewer_coords = get_planet_coordinates(planet)
    g, s = int(viewer_coords["galaxy"]), int(viewer_coords["system"])
    _foreign_uid, _foreign_pid, foreign_coords = _foreign_planet_in_system(
        g, s, avoid_position=int(viewer_coords["position"])
    )
    fp = int(foreign_coords["position"])

    ok, reason, preset = create_preset(
        uid,
        name="Raid Heavy",
        preset_type="raid",
        ships_json={"falcon_interceptor": 20},
        mission_type="attack",
    )
    assert ok, reason

    res = client.post(
        "/api/fleet/send",
        json={
            "origin_planet_id": origin_pid,
            "mission_type": "attack",
            "galaxy_quick_attack": True,
            "preset_id": int(preset["id"]),
            "target_galaxy": g,
            "target_system": s,
            "target_position": fp,
        },
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert body["error"] == "not_enough_ships"


def test_galaxy_foreign_planet_quick_attack_ui(galaxy_db, monkeypatch):
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    viewer_coords = get_planet_coordinates(planet)
    g, s = int(viewer_coords["galaxy"]), int(viewer_coords["system"])
    _foreign_uid, _foreign_pid, foreign_coords = _foreign_planet_in_system(
        g, s, avoid_position=int(viewer_coords["position"])
    )
    fp = int(foreign_coords["position"])
    resp = client.get(f"/galaxy?view=system&galaxy={g}&system={s}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "data-galaxy-quick-attack" in body
    assert "galaxy-fleet-action--quick-attack" in body
    assert "data-fleet-href=" in body
    assert f"target_position={fp}" in body
    assert "mission=attack" in body
    assert f'data-target-position="{fp}"' in body


def test_galaxy_own_planet_no_quick_attack(galaxy_db, monkeypatch):
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    coords = get_planet_coordinates(planet)
    resp = client.get(
        f"/galaxy?view=system&galaxy={coords['galaxy']}&system={coords['system']}"
    )
    body = resp.get_data(as_text=True)
    assert "data-galaxy-quick-attack" not in body


def test_main_js_galaxy_quick_attack_contract():
    js = Path("static/js/galaxy-quick-action.js").read_text(encoding="utf-8")
    assert "data-galaxy-quick-attack" in js
    assert "galaxy_quick_attack: true" in js
    assert "galaxy_attack=1" in js
    assert "galaxy_quick_attack_success" in js
    assert "galaxy_quick_attack_empty" in js


def test_main_js_galaxy_quick_attack_preview_contract():
    """GC-979 — popover renders preset preview (ships + speed) and truncation."""
    js = Path("static/js/galaxy-quick-action.js").read_text(encoding="utf-8")
    assert "galaxy-quick-attack-item-preview" in js
    assert "galaxy_quick_attack_more_ships" in js
    assert "fleet_ship_${key}" in js
    assert "entries.slice(0, 3)" in js
    assert "speed_percent" in js


def test_locales_galaxy_quick_attack_preview_keys():
    import json

    for lang in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads(Path(f"locales/{lang}.json").read_text(encoding="utf-8"))
        assert "galaxy_quick_attack_more_ships" in data, lang
        assert "galaxy_quick_attack_cargo" in data, lang
        assert "%(count)s" in data["galaxy_quick_attack_more_ships"], lang
