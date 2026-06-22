"""GC-621G — Admin fleet list and force-advance."""

from __future__ import annotations

pytest_plugins = ["tests.test_admin_control_center"]

import json
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.expedition_events import calculate_expedition_loot_cap
from game.fleet import (
    EXPEDITION_POSITION,
    admin_advance_fleet_movement,
    list_admin_fleet_movements,
    send_fleet,
)
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db


@pytest.fixture()
def fleet_db(tmp_path, monkeypatch):
    db_path = tmp_path / "admin_fleet_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield db_path
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"admin_fleet_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Admiral", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _fund_planet(cur, planet_id):
    cur.execute(
        "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 500000 WHERE id = ?;",
        (int(planet_id),),
    )


def _seed_ships(planet_id, player_id, ships, conn):
    from game.fleet import add_planet_ships

    add_planet_ships(int(planet_id), int(player_id), ships, conn=conn)


def _planet_coords(planet_id, conn):
    cur = conn.cursor()
    cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (int(planet_id),))
    row = cur.fetchone()
    return int(row["galaxy"]), int(row["system"]), int(row["position"])


def test_list_admin_fleet_movements_includes_active_expedition(fleet_db):
    conn = db()
    uid = _player(conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, _ = _planet_coords(pid, conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 2}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=EXPEDITION_POSITION,
        mission_type="expedition",
        ships={"solar_skiff": 1},
        conn=conn,
    )
    assert ok
    fleet_id = int(result["fleet"]["id"])
    conn.commit()

    rows = list_admin_fleet_movements(conn=conn)
    match = [r for r in rows if int(r["id"]) == fleet_id]
    assert len(match) == 1
    assert match[0]["status"] == "outbound"
    assert match[0]["mission_type"] == "expedition"
    conn.close()


def test_admin_advance_completes_expedition_and_credits_loot(fleet_db):
    conn = db()
    uid = _player(conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, _ = _planet_coords(pid, conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 2}, conn=conn)
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    before = dict(cur.fetchone())
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=EXPEDITION_POSITION,
        mission_type="expedition",
        ships={"solar_skiff": 1},
        conn=conn,
    )
    assert ok
    fleet_id = int(result["fleet"]["id"])

    advance = admin_advance_fleet_movement(fleet_id, conn=conn, complete=True)
    conn.commit()
    assert advance["ok"] is True
    assert advance["status_before"] == "outbound"
    assert advance["status_after"] == "completed"
    assert int(advance["steps"]) >= 3

    cur.execute("SELECT status, resources_json FROM fleet_movements WHERE id = ?;", (fleet_id,))
    row = dict(cur.fetchone())
    assert row["status"] == "completed"
    rewards = json.loads(row["resources_json"] or "{}")
    loot_metal = int(rewards.get("metal") or 0)
    loot_crystal = int(rewards.get("crystal") or 0)

    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    after = dict(cur.fetchone())
    assert int(after["metal"]) == int(before["metal"]) + loot_metal
    assert int(after["crystal"]) == int(before["crystal"]) + loot_crystal
    assert calculate_expedition_loot_cap({"solar_skiff": 1}) > 0
    conn.close()


def test_admin_fleet_api_requires_admin(app_client):
    from tests.test_admin_control_center import _as_user

    client, admin_id, user_id = app_client
    _as_user(client, user_id)
    res = client.get("/api/admin/fleets")
    assert res.status_code in (401, 403)

    _as_user(client, admin_id)
    res = client.get("/api/admin/fleets")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "movements" in data
