
"""GC-FLT-UX-02 — selected saved fleets launch with partial success."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from game.db import db
from game.fleet import create_preset, get_planet_ships
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
from tests.test_fleet import (
    _fund_planet,
    _planet_coords,
    _policy_safe_username,
    _second_colony,
    _seed_ships,
)

pytest_plugins = ("tests.test_fleet",)
ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _client_and_presets(monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uname = _policy_safe_username("fbulk")
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Bulk Admiral", conn=conn)
    origin = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony = _second_colony(uid, conn=conn)
    galaxy, system, position = _planet_coords(colony, conn=conn)
    _fund_planet(conn.cursor(), origin)
    _seed_ships(origin, uid, {"mule_courier": 3}, conn=conn)
    conn.commit()
    conn.close()

    ok1, reason1, p1 = create_preset(
        uid,
        name="Supply Alpha",
        preset_type="transport",
        ships_json={"mule_courier": 2},
        resources_json={},
        speed_percent=100,
        mission_type="transport",
        target_galaxy=galaxy,
        target_system=system,
        target_position=position,
    )
    assert ok1, reason1
    ok2, reason2, p2 = create_preset(
        uid,
        name="Supply Heavy",
        preset_type="transport",
        ships_json={"mule_courier": 99},
        resources_json={},
        speed_percent=100,
        mission_type="transport",
        target_galaxy=galaxy,
        target_system=system,
        target_position=position,
    )
    assert ok2, reason2
    ok3, reason3, p3 = create_preset(
        uid,
        name="Incomplete",
        preset_type="transport",
        ships_json={"mule_courier": 1},
        resources_json={},
        speed_percent=100,
        mission_type="transport",
    )
    assert ok3, reason3

    client = app_module.app.test_client()
    login = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert login.status_code in (200, 302)
    return app_module, client, uid, origin, [int(p1["id"]), int(p2["id"]), int(p3["id"])]


def test_bulk_launch_partial_success_and_skip_reasons(fleet_db, monkeypatch):
    _app, client, uid, origin, preset_ids = _client_and_presets(monkeypatch)
    request_id = "gc-fleet-bulk-partial-1"
    resp = client.post(
        "/api/fleet/bulk-launch-presets",
        json={"origin_planet_id": origin, "preset_ids": preset_ids, "request_id": request_id},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["started_count"] == 1
    assert data["skipped_count"] == 2
    reasons = {row["reason"] for row in data["skipped"]}
    assert "not_enough_ships" in reasons
    assert "bulk_preset_incomplete" in reasons
    assert data["batch_id"]
    assert body.get("state")

    verify = db()
    try:
        assert int(get_planet_ships(origin, conn=verify).get("mule_courier", 0)) == 1
        count = verify.execute(
            "SELECT COUNT(*) AS n FROM fleet_movements WHERE player_id = ?;", (uid,)
        ).fetchone()["n"]
        assert int(count) == 1
        batch = verify.execute(
            "SELECT status, total_fleets FROM fleet_batches WHERE id = ?;", (data["batch_id"],)
        ).fetchone()
        assert batch["status"] == "completed"
        assert int(batch["total_fleets"]) == 1
    finally:
        verify.close()

    again = client.post(
        "/api/fleet/bulk-launch-presets",
        json={"origin_planet_id": origin, "preset_ids": preset_ids, "request_id": request_id},
        headers={"Content-Type": "application/json"},
    )
    assert again.status_code == 200
    assert again.get_json()["data"]["started_count"] == 1
    verify = db()
    try:
        count = verify.execute(
            "SELECT COUNT(*) AS n FROM fleet_movements WHERE player_id = ?;", (uid,)
        ).fetchone()["n"]
        assert int(count) == 1
    finally:
        verify.close()


def test_bulk_launch_unknown_owned_preset_is_skipped(fleet_db, monkeypatch):
    _app, client, _uid, origin, preset_ids = _client_and_presets(monkeypatch)
    resp = client.post(
        "/api/fleet/bulk-launch-presets",
        json={"origin_planet_id": origin, "preset_ids": [preset_ids[0], 999999999]},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["started_count"] == 1
    assert data["skipped_count"] == 1
    assert data["skipped"][0]["reason"] == "bulk_preset_not_found"


def test_bulk_launch_contract_reuses_reason_mapper_and_slim_state():
    app = _src("app.py")
    main = _src("static/main.js")
    tpl = _src("templates/fleet.html")
    js = _src("static/js/fleet-bulk-launch.js")
    module = _src("game/fleet_bulk.py")

    assert '@app.route("/api/fleet/bulk-launch-presets", methods=["POST"])' in app
    assert app.count('"api_fleet_bulk_launch_presets"') >= 3
    assert 'GC.fleetReasonText = reasonText;' in main
    assert 'data-fleet-bulk-launch' in tpl
    assert 'data-fleet-bulk-preset' in tpl
    assert 'fleet-bulk-launch.js' in tpl
    assert 'GC.fleetReasonText' in js
    assert 'item.textContent = `${name} — ${reasonText' in js
    assert "send_fleet(" in module
    assert "fleet_movements" not in module.replace("existing ``fleet_movements`` state", "")
    assert "calculate_flight" not in module


def test_bulk_launch_locale_parity():
    keys = {
        "fleet_bulk_launch_select", "fleet_bulk_launch_select_hint",
        "fleet_bulk_launch_select_all", "fleet_bulk_launch_start",
        "fleet_bulk_launch_hint", "fleet_bulk_launch_none_selected",
        "fleet_bulk_launch_summary", "fleet_bulk_launch_skipped_title",
        "fleet_bulk_launch_success", "fleet_error_bulk_preset_incomplete",
        "fleet_error_bulk_preset_not_found", "fleet_error_bulk_no_selection",
        "fleet_error_bulk_too_many_presets",
    }
    for loc in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        data = json.loads((ROOT / f"locales/{loc}.json").read_text(encoding="utf-8"))
        missing = keys - set(data)
        assert not missing, f"{loc} missing {sorted(missing)}"
        assert all(str(data[k]).strip() for k in keys)
