"""GC-981 — Mass expedition slot split UX."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from game.db import db
from game.fleet import (
    compute_mass_expedition_slot_split,
    get_fleet_slot_status,
    get_planet_ships,
    mass_expedition,
    mass_expedition_from_ships,
    preview_mass_expedition_slot_split,
    send_fleet,
)
from game.fleet_defs import EXPEDITION_POSITION
from game.models import get_planets_by_player
from tests.test_fleet import _fund_planet, _player, _seed_ships


pytest_plugins = ("tests.test_fleet",)


def test_compute_mass_expedition_slot_split_floor_and_leftover():
    per_slot, leftover, slots = compute_mass_expedition_slot_split(
        {"solar_skiff": 70003, "mule_courier": 7000},
        7,
    )
    assert slots == 7
    assert per_slot == {"solar_skiff": 10000, "mule_courier": 1000}
    assert leftover == {"solar_skiff": 3}


def test_preview_mass_expedition_slot_split_success(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 70000, "mule_courier": 7000}, conn=conn)
    conn.commit()

    ok, reason, preview = preview_mass_expedition_slot_split(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": 70000, "mule_courier": 7000},
        conn=conn,
    )
    assert ok is True, reason
    assert preview["free_slots"] >= 1
    assert preview["per_fleet_ships"]["solar_skiff"] == 70000 // preview["free_slots"]
    assert preview["started_count"] == preview["free_slots"]
    conn.close()


def test_mass_expedition_from_ships_starts_split_fleets(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=5000000, crystal=5000000, fuel_cells=5000000)
    free_before = get_fleet_slot_status(uid, conn=conn)["free"]
    total_skiff = free_before * 10000
    _seed_ships(pid, uid, {"solar_skiff": total_skiff, "mule_courier": free_before * 1000}, conn=conn)
    conn.commit()

    ok, reason, result = mass_expedition_from_ships(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": total_skiff, "mule_courier": free_before * 1000},
        conn=conn,
    )
    assert ok is True, reason
    assert result["started_count"] == free_before
    assert result["per_fleet_ships"]["solar_skiff"] == 10000
    assert result["per_fleet_ships"]["mule_courier"] == 1000
    assert result["leftover_ships"] == {}

    cur.execute(
        """
        SELECT ships_json FROM fleet_movements
        WHERE player_id = ? AND mission_type = 'expedition' AND parent_batch_id = ?;
        """,
        (uid, int(result["batch"]["id"])),
    )
    rows = cur.fetchall()
    assert len(rows) == free_before
    for row in rows:
        ships = __import__("json").loads(row["ships_json"])
        assert ships["solar_skiff"] == 10000
        assert ships["mule_courier"] == 1000

    remaining = get_planet_ships(pid, conn=conn)
    assert int(remaining.get("solar_skiff", 0)) == 0
    assert int(remaining.get("mule_courier", 0)) == 0
    conn.close()


def test_mass_expedition_from_ships_keeps_leftover_on_planet(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=5000000, crystal=5000000, fuel_cells=5000000)
    free_before = get_fleet_slot_status(uid, conn=conn)["free"]
    total_skiff = free_before * 10000 + 5
    _seed_ships(pid, uid, {"solar_skiff": total_skiff}, conn=conn)
    conn.commit()
    _per, expected_leftover, _slots = compute_mass_expedition_slot_split(
        {"solar_skiff": total_skiff}, free_before
    )

    ok, reason, result = mass_expedition_from_ships(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": total_skiff},
        conn=conn,
    )
    assert ok is True, reason
    assert result["leftover_ships"] == expected_leftover
    assert int(get_planet_ships(pid, conn=conn).get("solar_skiff", 0)) == int(
        expected_leftover.get("solar_skiff", 0)
    )
    conn.close()


def test_mass_expedition_from_ships_blocks_without_free_slots(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=5000000, crystal=5000000, fuel_cells=5000000)
    _seed_ships(pid, uid, {"solar_skiff": 50}, conn=conn)
    conn.commit()

    slots = get_fleet_slot_status(uid, conn=conn)
    for _ in range(slots["free"]):
        send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=1,
            target_system=1,
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            conn=conn,
        )
    conn.commit()

    ok, reason, preview = preview_mass_expedition_slot_split(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": 10},
        conn=conn,
    )
    assert not ok
    assert reason == "fleet_slots_full"
    assert preview["free_slots"] == 0
    conn.close()


def test_mass_expedition_from_ships_blocks_without_expedition_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    free_before = get_fleet_slot_status(uid, conn=conn)["free"]
    _seed_ships(pid, uid, {"mule_courier": free_before * 10}, conn=conn)
    conn.commit()

    ok, reason, _preview = preview_mass_expedition_slot_split(
        player_id=uid,
        origin_planet_id=pid,
        ships={"mule_courier": free_before * 10},
        conn=conn,
    )
    assert not ok
    assert reason == "mass_expo_no_expedition_ships"
    conn.close()


def test_mass_expedition_from_ships_blocks_when_split_too_small(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    free_before = get_fleet_slot_status(uid, conn=conn)["free"]
    assert free_before >= 2
    _seed_ships(pid, uid, {"solar_skiff": free_before - 1}, conn=conn)
    conn.commit()

    ok, reason, _preview = preview_mass_expedition_slot_split(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": free_before - 1},
        conn=conn,
    )
    assert not ok
    assert reason == "mass_expo_split_too_small"
    conn.close()


def test_mass_expedition_single_free_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=5000000, crystal=5000000, fuel_cells=5000000)
    _seed_ships(pid, uid, {"solar_skiff": 100, "mule_courier": 1000}, conn=conn)
    conn.commit()
    slots = get_fleet_slot_status(uid, conn=conn)
    free_start = int(slots["free"])
    for _ in range(max(0, free_start - 1)):
        send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=1,
            target_system=1,
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            conn=conn,
        )
    conn.commit()
    assert get_fleet_slot_status(uid, conn=conn)["free"] == 1

    _seed_ships(pid, uid, {"solar_skiff": 5000, "mule_courier": 800}, conn=conn)
    conn.commit()

    ok_prev, reason_prev, preview = preview_mass_expedition_slot_split(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": 5000, "mule_courier": 800},
        conn=conn,
    )
    assert ok_prev is True, reason_prev
    assert preview["free_slots"] == 1
    assert preview["per_fleet_ships"] == {"solar_skiff": 5000, "mule_courier": 800}
    assert preview["leftover_ships"] == {}

    ok, reason, result = mass_expedition_from_ships(
        player_id=uid,
        origin_planet_id=pid,
        ships={"solar_skiff": 5000, "mule_courier": 800},
        conn=conn,
    )
    assert ok is True, reason
    assert result["started_count"] == 1
    assert result["per_fleet_ships"] == preview["per_fleet_ships"]
    assert result["leftover_ships"] == preview["leftover_ships"]
    conn.close()


def test_legacy_mass_expedition_preset_still_works(fleet_db):
    from game.fleet import create_preset

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(pid, uid, {"solar_skiff": 10}, conn=conn)
    conn.commit()
    ok, _, preset = create_preset(
        uid, name="Expo", preset_type="expedition", ships_json={"solar_skiff": 1}
    )
    assert ok
    ok2, reason, result = mass_expedition(
        player_id=uid,
        origin_planet_id=pid,
        preset_id=preset["id"],
        waves=2,
        conn=conn,
    )
    assert ok2, reason
    assert len(result["started"]) >= 1
    conn.close()


def test_api_mass_expedition_split(fleet_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=5000000, crystal=5000000, fuel_cells=5000000)
    free_before = get_fleet_slot_status(uid, conn=conn)["free"]
    _seed_ships(pid, uid, {"solar_skiff": free_before * 10000}, conn=conn)
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    preview = client.post(
        "/api/fleet/mass-expedition/preview",
        json={"origin_planet_id": pid, "ships": {"solar_skiff": free_before * 10000}},
        headers={"Content-Type": "application/json"},
    )
    assert preview.status_code == 200
    body = preview.get_json()
    assert body["ok"] is True
    assert body["data"]["per_fleet_ships"]["solar_skiff"] == 10000

    res = client.post(
        "/api/fleet/mass-expedition",
        json={
            "origin_planet_id": pid,
            "ships": {"solar_skiff": free_before * 10000},
            "request_id": "gc981-mass-expo-test",
        },
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200
    send_body = res.get_json()
    assert send_body["ok"] is True
    assert send_body["data"]["started_count"] == free_before


def test_fleet_page_mass_expo_split_ui_contract(fleet_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 5}, conn=conn)
    conn.commit()
    conn.close()
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    html = client.get("/fleet").get_data(as_text=True)
    assert "data-fleet-mass-expo-split" in html
    assert "data-fleet-mass-expo-split-submit" in html
    assert "data-fleet-mass-expo-legacy" in html


def test_main_js_mass_expo_split_contract():
    js = Path("static/main.js").read_text(encoding="utf-8")
    assert "mass-expedition/preview" in js
    assert "submitMassExpeditionSplit" in js
    assert "data-fleet-mass-expo-split-submit" in js


def test_main_js_ship_max_selection_triggers_mass_expo_preview():
    """GC-981 — MAX / image pick must emit input events so mass expo reads ship inputs."""
    js = Path("static/main.js").read_text(encoding="utf-8")
    assert "setFleetShipInputValue" in js
    assert "emitFleetShipInputChange" in js
    assert "scheduleMassExpoSplitPreview" in js
    max_image_idx = js.index('closest("[data-ship-max-image]")')
    max_image_chunk = js[max_image_idx : max_image_idx + 550]
    assert "setFleetShipInputValue" in max_image_chunk
    max_btn_idx = js.index('closest("[data-ship-max]")')
    max_btn_chunk = js[max_btn_idx : max_btn_idx + 550]
    assert "setFleetShipInputValue" in max_btn_chunk
    emit_chunk = js[js.index("emitFleetShipInputChange") : js.index("emitFleetShipInputChange") + 400]
    assert 'new Event("input"' in emit_chunk
    assert 'new Event("change"' in emit_chunk
