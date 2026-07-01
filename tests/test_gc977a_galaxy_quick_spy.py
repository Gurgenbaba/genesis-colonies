"""GC-977A — Galaxy quick spy + default probe options."""

from __future__ import annotations

import importlib
import uuid

import pytest

from game.db import commit, db
from game.fleet import add_planet_ships, get_planet_ships, resolve_galaxy_quick_spy_ships, send_fleet
from game.galaxy import get_planet_coordinates
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
from game.options import (
    DEFAULT_SPY_PROBES,
    get_options_snapshot,
    get_spy_probe_settings,
    update_spy_probe_settings,
)
from tests.test_galaxy import _foreign_planet_in_system, _galaxy_client


pytest_plugins = ("tests.test_galaxy",)


def test_spy_probe_settings_default(galaxy_db):
    ok, err, user = create_user(f"spyopt_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    pid = int(user["id"])
    ensure_player_and_homeworld(pid, player_name="SpyOpt")
    snap = get_options_snapshot(pid)
    assert snap["default_spy_probes"] == DEFAULT_SPY_PROBES
    assert get_spy_probe_settings(pid)["default_spy_probes"] == DEFAULT_SPY_PROBES


def test_spy_probe_settings_update_and_clamp(galaxy_db):
    ok, err, user = create_user(f"spyopt_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    pid = int(user["id"])
    ensure_player_and_homeworld(pid, player_name="SpyOpt")
    ok, err, data = update_spy_probe_settings(pid, default_spy_probes=10)
    assert ok is True
    assert err == "options_saved"
    assert data["default_spy_probes"] == 10
    ok, err, data = update_spy_probe_settings(pid, default_spy_probes=0)
    assert ok is True
    assert data["default_spy_probes"] == 1


def test_api_options_spy_probes(galaxy_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    client, pid = _galaxy_client(monkeypatch)
    res = client.post(
        "/api/options/spy-probes",
        json={"default_spy_probes": 25},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["data"]["default_spy_probes"] == 25
    assert get_spy_probe_settings(pid)["default_spy_probes"] == 25


def test_options_page_galaxy_settings_ui(galaxy_db, monkeypatch):
    client, _pid = _galaxy_client(monkeypatch)
    html = client.get("/options").get_data(as_text=True)
    assert 'id="options-tab-panel-galaxy"' in html
    assert 'id="options-galaxy-settings"' in html
    assert 'data-spy-probes-input' in html
    assert 'data-spy-probes-preset' not in html
    assert "options_galaxy_title" not in html or "Galaxy" in html


def test_resolve_galaxy_quick_spy_ships_partial(galaxy_db):
    ok, err, user = create_user(f"spyopt_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    pid = int(user["id"])
    ensure_player_and_homeworld(pid, player_name="SpyOpt")
    origin_pid = int(get_planets_by_player(pid)[0]["id"])
    update_spy_probe_settings(pid, default_spy_probes=5)

    conn = db()
    try:
        add_planet_ships(origin_pid, pid, {"veil_probe": 3}, conn=conn)
        commit(conn)
        ok, reason, meta = resolve_galaxy_quick_spy_ships(pid, origin_pid, conn=conn)
        assert ok is True
        assert reason == ""
        assert meta["sent_count"] == 3
        assert meta["configured_count"] == 5
        assert meta["available_count"] == 3
        assert meta["reduced"] is True
        assert meta["ships"] == {"veil_probe": 3}
    finally:
        conn.close()


def test_resolve_galaxy_quick_spy_ships_none_available(galaxy_db):
    ok, err, user = create_user(f"spyopt_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    pid = int(user["id"])
    ensure_player_and_homeworld(pid, player_name="SpyOpt")
    origin_pid = int(get_planets_by_player(pid)[0]["id"])
    update_spy_probe_settings(pid, default_spy_probes=5)

    conn = db()
    try:
        ok, reason, meta = resolve_galaxy_quick_spy_ships(pid, origin_pid, conn=conn)
        assert not ok
        assert reason == "no_spy_probes_available"
        assert meta["sent_count"] == 0
        assert meta["available_count"] == 0
    finally:
        conn.close()


def test_quick_spy_send_uses_configured_probe_count(galaxy_db, monkeypatch):
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    origin_pid = int(planet["id"])
    viewer_coords = get_planet_coordinates(planet)
    g, s = int(viewer_coords["galaxy"]), int(viewer_coords["system"])
    _foreign_uid, _foreign_pid, foreign_coords = _foreign_planet_in_system(
        g, s, avoid_position=int(viewer_coords["position"])
    )
    fp = int(foreign_coords["position"])

    ok, err, _ = update_spy_probe_settings(uid, default_spy_probes=5)
    assert ok, err

    conn = db()
    try:
        add_planet_ships(origin_pid, uid, {"veil_probe": 5}, conn=conn)
        commit(conn)
        ok, reason, result = send_fleet(
            player_id=uid,
            origin_planet_id=origin_pid,
            target_galaxy=g,
            target_system=s,
            target_position=fp,
            mission_type="spy",
            ships={"veil_probe": 5},
            conn=conn,
        )
        assert ok, reason
        commit(conn)
        assert int(get_planet_ships(origin_pid, conn=conn).get("veil_probe", 0)) == 0
        assert result and result.get("fleet")
    finally:
        conn.close()


def test_api_fleet_galaxy_quick_spy_partial(galaxy_db, monkeypatch):
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    origin_pid = int(planet["id"])
    viewer_coords = get_planet_coordinates(planet)
    g, s = int(viewer_coords["galaxy"]), int(viewer_coords["system"])
    _foreign_uid, _foreign_pid, foreign_coords = _foreign_planet_in_system(
        g, s, avoid_position=int(viewer_coords["position"])
    )
    fp = int(foreign_coords["position"])

    update_spy_probe_settings(uid, default_spy_probes=5)
    conn = db()
    try:
        add_planet_ships(origin_pid, uid, {"veil_probe": 3}, conn=conn)
        commit(conn)
    finally:
        conn.close()

    res = client.post(
        "/api/fleet/send",
        json={
            "origin_planet_id": origin_pid,
            "mission_type": "spy",
            "galaxy_quick_spy": True,
            "target_galaxy": g,
            "target_system": s,
            "target_position": fp,
            "resources": {},
            "speed_percent": 100,
        },
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    meta = body["data"]["galaxy_quick_spy"]
    assert meta["sent_count"] == 3
    assert meta["reduced"] is True

    conn = db()
    try:
        assert int(get_planet_ships(origin_pid, conn=conn).get("veil_probe", 0)) == 0
    finally:
        conn.close()


def test_api_fleet_galaxy_quick_spy_no_probes(galaxy_db, monkeypatch):
    client, uid = _galaxy_client(monkeypatch)
    planet = get_planets_by_player(uid)[0]
    origin_pid = int(planet["id"])
    viewer_coords = get_planet_coordinates(planet)
    g, s = int(viewer_coords["galaxy"]), int(viewer_coords["system"])
    _foreign_uid, _foreign_pid, foreign_coords = _foreign_planet_in_system(
        g, s, avoid_position=int(viewer_coords["position"])
    )
    fp = int(foreign_coords["position"])

    res = client.post(
        "/api/fleet/send",
        json={
            "origin_planet_id": origin_pid,
            "mission_type": "spy",
            "galaxy_quick_spy": True,
            "target_galaxy": g,
            "target_system": s,
            "target_position": fp,
            "resources": {},
            "speed_percent": 100,
        },
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body["ok"] is False
    assert body["error"] == "no_spy_probes_available"


def test_main_js_galaxy_quick_spy_contract(galaxy_db):
    from pathlib import Path

    js = Path("static/main.js").read_text(encoding="utf-8")
    assert "data-galaxy-quick-spy" in js
    assert "onQuickSpyClick" in js
    assert "galaxy_quick_spy: true" in js
    assert "galaxy_quick_spy_success_partial" in js
    assert "galaxy_quick_spy_no_probes" in js
