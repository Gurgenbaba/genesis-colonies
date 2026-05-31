"""Fleet system Phase 1 tests."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.fleet import (
    add_planet_ships,
    collect_resources,
    count_active_fleet_slots,
    create_preset,
    delete_preset,
    distribute_resources,
    fleet_schema_ready,
    get_fleet_slot_status,
    get_max_fleet_slots,
    get_planet_ships,
    list_presets,
    mass_expedition,
    mission_allowed_for_target,
    preview_fleet_flight,
    process_fleet_tick,
    resolve_fleet_target,
    send_fleet,
    update_preset,
    _build_spy_report_body,
    _target_planet_snapshot,
)
from game.expedition_events import expedition_event_keys, resolve_expedition_outcome
from game.fleet_calc import (
    apply_departure_deduction,
    calculate_distance,
    calculate_fleet_speed,
    calculate_flight_seconds,
    calculate_fuel_cost,
    calculate_total_cargo,
    fuel_efficiency_factor,
    normalize_ships,
    validate_departure_balances,
)
from game.fleet_defs import EXPEDITION_POSITION, FLEET_FUEL_RESOURCE
from game.messages import get_message, list_messages
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.planet_evolution.service import colonize_planet


@pytest.fixture
def fleet_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fleet_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"fleet_user_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Admiral", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _fund_planet(cur, planet_id: int, *, metal=50000, crystal=50000, fuel_cells=50000):
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (metal, crystal, fuel_cells, int(planet_id)),
    )


def _grant_ship_test_prereqs(cur, planet_id: int, user_id: int) -> None:
    cur.execute(
        """
        UPDATE planet_buildings
        SET research_lab = 10, command_center = 10, barracks = 10
        WHERE planet_id = ?;
        """,
        (int(planet_id),),
    )
    for tech in (
        "mining_tech",
        "drone_tech",
        "engine_tech",
        "navigation_tech",
        "weapon_tech",
        "armor_tech",
        "storage_tech",
        "fuel_efficiency",
        "shield_tech",
    ):
        cur.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (int(user_id), tech, 10),
        )


def _seed_ships(planet_id: int, player_id: int, ships: dict, conn=None):
    own = conn is None
    if own:
        conn = db()
        begin = True
        from game.db import begin_write_transaction, commit

        begin_write_transaction(conn)
    else:
        begin = False
    add_planet_ships(planet_id, player_id, ships, conn=conn)
    if begin:
        commit(conn)
        conn.close()


def _planet_coords(planet_id: int, conn=None) -> tuple[int, int, int]:
    own = conn is None
    if own:
        conn = db()
    cur = conn.cursor()
    cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (int(planet_id),))
    row = cur.fetchone()
    if own:
        conn.close()
    return int(row["galaxy"]), int(row["system"]), int(row["position"])


def _second_colony(uid: int, conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, reason, extra = colonize_planet(uid, name="Colony Two", galaxy=1, system=300, position=5, conn=conn)
    assert ok, reason
    if own:
        conn.commit()
        conn.close()
    return int(extra["planet_id"])


def _foreign_planet_standalone():
    """Create a second player in an isolated DB session (avoids SQLite lock with test conn)."""
    ok, err, user = create_user(f"foreign_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    from game.db import begin_write_transaction, commit

    begin_write_transaction(conn)
    ensure_player_and_homeworld(uid, player_name="Foreign", conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    coords = _planet_coords(pid, conn=conn)
    commit(conn)
    conn.close()
    return uid, pid, coords


def _allied_players_standalone():
    ok1, err1, u1 = create_user(f"ally_a_{uuid.uuid4().hex[:8]}", "test-pass-123")
    ok2, err2, u2 = create_user(f"ally_b_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok1, err1
    assert ok2, err2
    uid1 = int(u1["id"])
    uid2 = int(u2["id"])
    conn = db()
    from game.db import begin_write_transaction, commit

    begin_write_transaction(conn)
    ensure_player_and_homeworld(uid1, player_name="AllyOne", conn=conn)
    ensure_player_and_homeworld(uid2, player_name="AllyTwo", conn=conn)
    tag = f"T{uuid.uuid4().hex[:6].upper()}"
    alliance = create_alliance(tag, "Test Alliance", uid1, conn=conn)
    add_alliance_member(alliance["id"], uid2, conn=conn)
    colony2 = _second_colony(uid2, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    commit(conn)
    conn.close()
    return uid1, uid2, colony2, (g, s, p)


# --- Calculation tests ---


def test_calculate_distance_same_system():
    d = calculate_distance((1, 100, 3), (1, 100, 8))
    assert d > 0


def test_calculate_fleet_speed_slowest():
    speed = calculate_fleet_speed({"veil_probe": 1, "mule_courier": 10})
    assert speed >= 5000


def test_calculate_fuel_and_cargo():
    ships = {"mule_courier": 2}
    assert calculate_total_cargo(ships) == 10000
    assert calculate_fuel_cost(ships, 1000, 100) >= 0


def test_speed_percent_validation_range():
    sec_fast = calculate_flight_seconds(1000, 5000, 100)
    sec_slow = calculate_flight_seconds(1000, 5000, 10)
    assert sec_slow >= sec_fast


# --- Schema ---


def test_fleet_schema_ready(fleet_db):
    conn = db()
    assert fleet_schema_ready(conn) is True
    conn.close()


def test_max_fleet_slots_fallback(fleet_db):
    uid = _player()
    assert get_max_fleet_slots(uid) == 3


# --- Send fleet ---


def test_fleet_send_success(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)

    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 50000, crystal = 10000 WHERE id = ?;", (pid,))
    _seed_ships(pid, uid, {"mule_courier": 5, "falcon_interceptor": 10}, conn=conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 2},
        resources={"metal": 1000, "crystal": 0},
        speed_percent=100,
        conn=conn,
    )
    assert ok, reason
    conn.commit()
    conn.close()

    verify = db()
    try:
        assert get_planet_ships(pid, conn=verify).get("mule_courier") == 3
        row = verify.execute(
            "SELECT status FROM fleet_movements WHERE player_id = ? ORDER BY id DESC LIMIT 1;",
            (uid,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "outbound"
    finally:
        verify.close()


def test_not_enough_ships_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    _seed_ships(pid, uid, {"mule_courier": 1}, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 5},
        conn=conn,
    )
    assert not ok
    assert reason == "not_enough_ships"
    conn.close()


def test_unknown_ship_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"deathstar": 1},
        conn=conn,
    )
    assert not ok
    assert reason == "unknown_ship"
    conn.close()


def test_same_origin_target_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, p = _planet_coords(pid, conn=conn)
    _seed_ships(pid, uid, {"falcon_interceptor": 5}, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"falcon_interceptor": 1},
        conn=conn,
    )
    assert not ok
    assert reason == "same_origin_target"
    conn.close()


def test_not_enough_cargo_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 999999 WHERE id = ?;", (pid,))
    _seed_ships(pid, uid, {"mule_courier": 1}, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 99999},
        conn=conn,
    )
    assert not ok
    assert reason == "not_enough_cargo"
    conn.close()


def test_not_enough_resources_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 100, crystal = 0 WHERE id = ?;", (pid,))
    _seed_ships(pid, uid, {"mule_courier": 2}, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 5000},
        conn=conn,
    )
    assert not ok
    assert reason == "not_enough_resources"
    conn.close()


def test_not_enough_fuel_fails(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 0 WHERE id = ?;", (pid,))
    _seed_ships(pid, uid, {"falcon_interceptor": 10}, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"falcon_interceptor": 5},
        conn=conn,
    )
    assert not ok
    assert reason == "not_enough_fuel"
    conn.close()


def test_slot_limit_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(pid, uid, {"mule_courier": 100}, conn=conn)
    conn.commit()

    for _ in range(3):
        ok, reason, _ = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=g,
            target_system=s,
            target_position=p,
            mission_type="transport",
            ships={"mule_courier": 1},
            resources={"metal": 1},
            conn=conn,
        )
        assert ok, reason

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 1},
        conn=conn,
    )
    assert not ok
    assert reason == "fleet_slots_full"
    conn.close()


def test_speed_percent_validation(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    _seed_ships(pid, uid, {"veil_probe": 1}, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="spy",
        ships={"veil_probe": 1},
        speed_percent=5,
        conn=conn,
    )
    assert not ok
    assert reason == "invalid_speed_percent"
    conn.close()


# --- Presets ---


def test_create_preset_success(fleet_db):
    uid = _player()
    ok, reason, preset = create_preset(
        uid,
        name="Raid Alpha",
        preset_type="raid",
        ships_json={"falcon_interceptor": 100},
        speed_percent=100,
        mission_type="attack",
    )
    assert ok, reason
    assert preset["name"] == "Raid Alpha"


def test_list_presets(fleet_db):
    uid = _player()
    create_preset(uid, name="Farm", preset_type="farm", ships_json={"falcon_interceptor": 50})
    presets = list_presets(uid)
    assert len(presets) >= 1


def test_update_preset(fleet_db):
    uid = _player()
    ok, _, preset = create_preset(uid, name="Old", preset_type="custom", ships_json={"mule_courier": 1})
    ok2, reason, updated = update_preset(preset["id"], uid, {"name": "New Name"})
    assert ok2, reason
    assert updated["name"] == "New Name"


def test_delete_preset(fleet_db):
    uid = _player()
    ok, _, preset = create_preset(uid, name="Del", preset_type="custom", ships_json={"mule_courier": 1})
    ok2, reason = delete_preset(preset["id"], uid)
    assert ok2, reason


def test_preset_foreign_player(fleet_db):
    uid1 = _player()
    uid2 = _player()
    ok, _, preset = create_preset(uid1, name="Secret", preset_type="spy", ships_json={"veil_probe": 1})
    ok2, reason, _ = update_preset(preset["id"], uid2, {"name": "Hack"})
    assert not ok2
    assert reason == "preset_not_found"


def test_preset_unknown_ship(fleet_db):
    uid = _player()
    ok, reason, _ = create_preset(uid, name="Bad", preset_type="custom", ships_json={"invalid_ship": 1})
    assert not ok
    assert reason == "unknown_ship"


# --- Tick / movement ---


def test_transport_arrival_credits_target(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute("UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;", (pid,))
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (colony2,))
    before = dict(cur.fetchone())
    _seed_ships(pid, uid, {"mule_courier": 3}, conn=conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 2000, "crystal": 500},
        conn=conn,
    )
    assert ok, reason
    fleet_id = result["fleet"]["id"]

    cur.execute(
        "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
        (time.time() - 1, fleet_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (fleet_id,))
    mv = cur.fetchone()
    assert mv["status"] == "returning"

    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (colony2,))
    after = dict(cur.fetchone())
    assert int(after["metal"]) == int(before["metal"]) + 2000
    assert int(after["crystal"]) == int(before["crystal"]) + 500
    conn.close()


def test_returning_restores_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"mule_courier": 5}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 2},
        resources={"metal": 100},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    now = time.time()
    cur.execute(
        "UPDATE fleet_movements SET arrival_at = ?, status = 'returning', return_at = ? WHERE id = ?;",
        (now - 100, now - 1, fleet_id),
    )
    conn.commit()

    before_ships = get_planet_ships(pid, conn=conn).get("mule_courier", 0)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    after_ships = get_planet_ships(pid, conn=conn).get("mule_courier", 0)
    assert after_ships == before_ships + 2
    conn.close()


def test_deploy_stations_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"falcon_interceptor": 10}, conn=conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="deploy",
        ships={"falcon_interceptor": 4},
        resources={"metal": 50},
        conn=conn,
    )
    assert ok, reason
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    assert get_planet_ships(colony2, conn=conn).get("falcon_interceptor") == 4
    cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (fleet_id,))
    assert cur.fetchone()["status"] == "completed"
    conn.close()


def test_spy_creates_report(fleet_db):
    _foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"veil_probe": 3}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="spy",
        ships={"veil_probe": 1},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    cur = conn.cursor()
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    msgs = list_messages(uid, category="espionage")
    assert msgs["ok"]
    assert len(msgs["data"]["messages"]) >= 1
    meta = msgs["data"]["messages"][0].get("metadata") or {}
    assert meta.get("report_version") == 2
    assert meta.get("intel_tiers", {}).get("target") is True
    assert meta.get("intel_tiers", {}).get("resources") is False
    assert meta.get("resources") == {}
    conn.close()


def _spy_report_meta(
    conn,
    *,
    uid: int,
    origin_pid: int,
    target_g: int,
    target_s: int,
    target_p: int,
    probes: int,
) -> dict:
    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=origin_pid,
        target_galaxy=target_g,
        target_system=target_s,
        target_position=target_p,
        mission_type="spy",
        ships={"veil_probe": probes},
        conn=conn,
    )
    assert ok, result
    fleet_id = result["fleet"]["id"]
    cur = conn.cursor()
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    msgs = list_messages(uid, category="espionage")
    return msgs["data"]["messages"][0].get("metadata") or {}


def test_spy_report_tier2_reveals_resources(fleet_db):
    _foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _fund_planet(cur, foreign_pid, metal=12000, crystal=3400, fuel_cells=99)
    _seed_ships(pid, uid, {"veil_probe": 5}, conn=conn)
    conn.commit()

    meta = _spy_report_meta(conn, uid=uid, origin_pid=pid, target_g=g, target_s=s, target_p=p, probes=2)
    tiers = meta.get("intel_tiers") or {}
    assert tiers.get("resources") is True
    assert tiers.get("fuel") is False
    res = meta.get("resources") or {}
    assert res.get("metal") == 12000
    assert res.get("crystal") == 3400
    assert "fuel_cells" not in res
    conn.close()


def test_spy_report_tier4_reveals_fleet(fleet_db):
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"veil_probe": 6}, conn=conn)
    _seed_ships(foreign_pid, foreign_uid, {"falcon_interceptor": 3, "mule_courier": 2}, conn=conn)
    conn.commit()

    meta = _spy_report_meta(conn, uid=uid, origin_pid=pid, target_g=g, target_s=s, target_p=p, probes=4)
    tiers = meta.get("intel_tiers") or {}
    assert tiers.get("fleet") is True
    assert tiers.get("buildings") is False
    ships = meta.get("ships") or {}
    assert ships
    assert sum(int(v) for v in ships.values()) > 0
    conn.close()


def test_spy_report_tier5_reveals_buildings_and_energy(fleet_db):
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"veil_probe": 6}, conn=conn)
    cur.execute(
        """
        UPDATE planet_buildings
        SET metal_mine = 5, solar_plant = 3, orbital_shipyard = 2
        WHERE planet_id = ?;
        """,
        (int(foreign_pid),),
    )
    cur.execute(
        "UPDATE planets SET energy_total = 120, energy_used = 80 WHERE id = ?;",
        (int(foreign_pid),),
    )
    conn.commit()

    snapshot = _target_planet_snapshot(int(foreign_pid), conn=conn)
    _, meta = _build_spy_report_body(snapshot, 5)
    tiers = meta.get("intel_tiers") or {}
    assert tiers.get("buildings") is True
    assert tiers.get("activity") is False
    assert meta.get("energy", {}).get("balance") == 40
    buildings = meta.get("buildings") or {}
    assert buildings.get("metal_mine") == 5
    assert len(buildings) == 1
    conn.close()


def test_attack_placeholder_report(fleet_db):
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"falcon_interceptor": 5}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"falcon_interceptor": 2},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    msgs = list_messages(uid, category="combat")
    assert len(msgs["data"]["messages"]) >= 1
    meta = msgs["data"]["messages"][0].get("metadata") or {}
    assert meta.get("result") == "undecided"
    assert "attacking_ships" in meta
    defender_msgs = list_messages(foreign_uid, category="combat")
    assert len(defender_msgs["data"]["messages"]) >= 1
    cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (fleet_id,))
    assert cur.fetchone()["status"] == "returning"
    conn.close()


def test_expedition_event_engine_report(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 2, "mule_courier": 1}, conn=conn)
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
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    msgs = list_messages(uid, category="expedition")
    assert len(msgs["data"]["messages"]) >= 1
    msg_id = msgs["data"]["messages"][0]["id"]
    detail = get_message(uid, msg_id, mark_read=False)
    assert detail["ok"]
    meta = detail["data"]["message"].get("metadata") or {}
    assert meta.get("report_version") == 2
    assert meta.get("event_key") in expedition_event_keys()
    assert "rewards" in meta
    assert meta.get("fleet_ships", {}).get("solar_skiff") == 1
    conn.close()


def test_expedition_outcome_deterministic_and_cargo_cap():
    first = resolve_expedition_outcome(
        42,
        cargo_total=500,
        expedition_ship_count=1,
        flight_seconds=120,
    )
    second = resolve_expedition_outcome(
        42,
        cargo_total=500,
        expedition_ship_count=1,
        flight_seconds=120,
    )
    assert first == second
    assert first["event_key"] in expedition_event_keys()
    reward_total = sum(int(first["rewards"].get(k) or 0) for k in ("metal", "crystal", "fuel_cells"))
    assert reward_total <= 500


def test_expedition_outcome_more_hulls_shift_from_empty():
    empty_events = {"void_scan", "sensor_glitch"}
    empty_hits = 0
    reward_hits = 0
    for movement_id in range(1, 401):
        low = resolve_expedition_outcome(
            movement_id,
            cargo_total=50000,
            expedition_ship_count=0,
            flight_seconds=60,
        )
        high = resolve_expedition_outcome(
            movement_id,
            cargo_total=50000,
            expedition_ship_count=5,
            flight_seconds=60,
        )
        if low["event_key"] in empty_events:
            empty_hits += 1
        if high["reward_total"] > 0:
            reward_hits += 1
    assert empty_hits >= 50
    assert reward_hits >= 200


def test_tick_idempotent(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"mule_courier": 3}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 1000},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    now = time.time()
    cur.execute(
        "UPDATE fleet_movements SET arrival_at = ?, status = 'returning', return_at = ? WHERE id = ?;",
        (now - 200, now - 1, fleet_id),
    )
    conn.commit()

    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,))
    metal_once = float(cur.fetchone()["metal"])

    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,))
    metal_twice = float(cur.fetchone()["metal"])
    assert metal_once == metal_twice
    conn.close()


# --- Mass expedition ---


def test_mass_expedition_creates_batch(fleet_db):
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
    assert result["batch"]["batch_type"] == "mass_expedition"
    assert len(result["started"]) >= 1
    conn.close()


def test_mass_expedition_respects_slots(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(pid, uid, {"solar_skiff": 20}, conn=conn)
    conn.commit()

    ok, _, preset = create_preset(
        uid, name="Expo", preset_type="expedition", ships_json={"solar_skiff": 1}
    )
    assert ok

    ok2, _, result = mass_expedition(
        player_id=uid,
        origin_planet_id=pid,
        preset_id=preset["id"],
        waves=10,
        conn=conn,
    )
    assert ok2
    assert len(result["started"]) <= 3
    assert len(result["skipped"]) >= 7
    conn.close()


def test_no_max_ship_limit(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=9999999, crystal=9999999, fuel_cells=9999999)
    _seed_ships(pid, uid, {"falcon_interceptor": 50000}, conn=conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"falcon_interceptor": 10000},
        conn=conn,
    )
    assert ok, reason
    assert result["fleet"]["ships"]["falcon_interceptor"] == 10000
    conn.close()


# --- Logistics foundation ---


def test_collect_validates_ownership(fleet_db):
    uid1 = _player()
    uid2 = _player()
    conn = db()
    p1 = int(get_planets_by_player(uid1, conn=conn)[0]["id"])
    p2 = int(get_planets_by_player(uid2, conn=conn)[0]["id"])
    conn.close()

    ok, reason, payload = collect_resources(
        player_id=uid1,
        target_planet_id=p1,
        source_planet_ids=[p2],
        resources_mode="all",
    )
    assert not ok
    assert reason == "planet_not_owned"
    assert payload is None


def test_distribute_validates_ownership(fleet_db):
    uid1 = _player()
    uid2 = _player()
    conn = db()
    p1 = int(get_planets_by_player(uid1, conn=conn)[0]["id"])
    p2 = int(get_planets_by_player(uid2, conn=conn)[0]["id"])
    conn.close()

    ok, reason, payload = distribute_resources(
        player_id=uid1,
        origin_planet_id=p1,
        target_planet_ids=[p2],
        resources_mode="equal",
    )
    assert not ok
    assert reason == "planet_not_owned"


def test_logistics_scaffold_response(fleet_db):
    uid = _player()
    conn = db()
    p1 = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    p2 = _second_colony(uid, conn=conn)
    conn.close()

    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=p1,
        source_planet_ids=[p2],
        resources_mode="all",
        ships_selection_mode="manual",
    )
    assert not ok
    assert reason == "logistics_not_implemented"
    assert payload["validated"] is True


def test_normalize_ships_filters_unknown():
    ships = normalize_ships({"mule_courier": 5, "bogus": 3})
    assert ships == {"mule_courier": 5}


def test_fleet_fuel_resource_is_fuel_cells():
    assert FLEET_FUEL_RESOURCE == "fuel_cells"


def test_fuel_cells_load_and_fuel_validated_together():
    ok, reason = validate_departure_balances(
        metal_have=100000,
        crystal_have=2000,
        fuel_cells_have=5000,
        resources={"metal": 0, "crystal": 800},
        fuel_cost=300,
    )
    assert ok, reason
    ok3, reason3 = validate_departure_balances(
        metal_have=100000,
        crystal_have=1000,
        fuel_cells_have=100,
        resources={"metal": 0, "crystal": 900},
        fuel_cost=200,
    )
    assert not ok3
    assert reason3 == "not_enough_fuel"


def test_apply_departure_deducts_fuel_cells(fleet_db):
    new_m, new_c, new_f = apply_departure_deduction(
        5000, 3000, 2000, {"metal": 100, "crystal": 500}, 200
    )
    assert new_m == 4900
    assert new_c == 2500
    assert new_f == 1800


def test_preview_send_fuel_parity(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"mule_courier": 5}, conn=conn)
    conn.commit()
    cur.execute("SELECT * FROM planets WHERE id = ?;", (pid,))
    planet = dict(cur.fetchone())
    ships = {"mule_courier": 2}
    resources = {"metal": 1000, "crystal": 0}
    preview = preview_fleet_flight(
        origin_planet=planet,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        ships=ships,
        resources=resources,
        speed_percent=100,
        player_id=uid,
        conn=conn,
    )
    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships=ships,
        resources=resources,
        speed_percent=100,
        conn=conn,
    )
    assert ok, reason
    assert result["fuel_cost"] == preview["fuel_cost"]
    conn.close()


def test_completed_fleets_do_not_count_against_slots(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"falcon_interceptor": 20}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="deploy",
        ships={"falcon_interceptor": 2},
        resources={"metal": 0, "crystal": 0},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert count_active_fleet_slots(uid, conn=conn) == 0
    conn.close()


def test_deploy_idempotent_double_tick(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"falcon_interceptor": 10}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="deploy",
        ships={"falcon_interceptor": 3},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    ships_once = get_planet_ships(colony2, conn=conn).get("falcon_interceptor", 0)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    ships_twice = get_planet_ships(colony2, conn=conn).get("falcon_interceptor", 0)
    assert ships_once == ships_twice == 3
    conn.close()


def test_seed_dev_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    from game.fleet import seed_planet_ships_stack

    ok, reason, ships = seed_planet_ships_stack(pid, uid, conn=conn)
    assert ok, reason
    assert ships.get("mule_courier", 0) >= 20
    conn.close()


# --- Target resolution ---


def test_resolve_fleet_target_own_planet(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, p = _planet_coords(pid, conn=conn)
    target = resolve_fleet_target(uid, g, s, p, conn=conn)
    assert target["target_type"] == "own_planet"
    assert "transport" in target["allowed_missions"]
    assert "deploy" in target["allowed_missions"]
    assert mission_allowed_for_target("attack", target)[0] is False
    conn.close()


def test_resolve_fleet_target_foreign_planet(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    target = resolve_fleet_target(uid, g, s, p, conn=conn)
    assert target["target_type"] == "foreign_planet"
    assert "spy" in target["allowed_missions"]
    assert "attack" in target["allowed_missions"]
    assert mission_allowed_for_target("transport", target)[0] is False
    conn.close()


def test_resolve_fleet_target_ally_planet(fleet_db):
    conn = db()
    uid1, uid2, ally_pid, (g, s, p) = _allied_players_standalone()
    target = resolve_fleet_target(uid1, g, s, p, conn=conn)
    assert target["target_type"] == "ally_planet"
    assert "transport" in target["allowed_missions"]
    assert mission_allowed_for_target("deploy", target)[0] is False
    conn.close()


def test_resolve_fleet_target_empty_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    target = resolve_fleet_target(uid, 1, 499, 12, conn=conn)
    assert target["target_type"] == "empty_slot"
    assert target["allowed_missions"] == ["colonize"]
    assert mission_allowed_for_target("colonize", target)[0] is True
    assert mission_allowed_for_target("transport", target)[0] is False
    conn.close()


def test_colonize_fleet_send_to_empty_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    _seed_ships(pid, uid, {"seed_ark": 1, "mule_courier": 2}, conn=conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=1,
        target_system=499,
        target_position=12,
        mission_type="colonize",
        ships={"seed_ark": 1},
        resources={"colony_name": "New Outpost"},
        conn=conn,
    )
    assert ok, reason
    assert result["fleet"]["status"] == "outbound"
    assert result["fleet"]["mission_type"] == "colonize"
    conn.commit()
    conn.close()

    verify = db()
    try:
        row = verify.execute(
            "SELECT status FROM fleet_movements WHERE player_id = ? ORDER BY id DESC LIMIT 1;",
            (uid,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "outbound"
    finally:
        verify.close()


def test_colonize_requires_ark_on_empty_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _seed_ships(pid, uid, {"mule_courier": 5}, conn=conn)
    conn.commit()

    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=1,
        target_system=498,
        target_position=11,
        mission_type="colonize",
        ships={"mule_courier": 1},
        conn=conn,
    )
    assert not ok
    assert reason == "colonize_requires_ark"
    conn.close()


def test_colonize_arrival_completes_without_return(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    _seed_ships(pid, uid, {"seed_ark": 1}, conn=conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=1,
        target_system=497,
        target_position=10,
        mission_type="colonize",
        ships={"seed_ark": 1},
        resources={"colony_name": "Ark Colony"},
        conn=conn,
    )
    assert ok, reason
    fleet_id = result["fleet"]["id"]
    before_count = len(get_planets_by_player(uid, conn=conn))

    cur.execute(
        "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
        (time.time() - 1, fleet_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (fleet_id,))
    assert cur.fetchone()["status"] == "completed"
    assert len(get_planets_by_player(uid, conn=conn)) == before_count + 1
    conn.close()


def test_resolve_fleet_target_expedition_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    target = resolve_fleet_target(uid, 1, 100, EXPEDITION_POSITION, conn=conn)
    assert target["target_type"] == "expedition_slot"
    assert target["allowed_missions"] == ["expedition"]
    conn.close()


def test_transport_foreign_blocked(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _seed_ships(pid, uid, {"mule_courier": 5}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 100},
        conn=conn,
    )
    assert not ok
    assert reason == "mission_blocked_foreign_planet"
    conn.close()


def test_transport_ally_succeeds(fleet_db):
    conn = db()
    uid1, uid2, ally_pid, (g, s, p) = _allied_players_standalone()
    pid = int(get_planets_by_player(uid1, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid1, {"mule_courier": 3}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(
        player_id=uid1,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 500, "crystal": 100},
        conn=conn,
    )
    assert ok, reason
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid1, conn=conn)
    conn.commit()
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (ally_pid,))
    assert int(cur.fetchone()["metal"]) >= 500
    sender_msgs = list_messages(uid1, category="system")
    receiver_msgs = list_messages(uid2, category="system")
    assert len(sender_msgs["data"]["messages"]) >= 1
    assert len(receiver_msgs["data"]["messages"]) >= 1
    conn.close()


def test_deploy_foreign_blocked(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _seed_ships(pid, uid, {"falcon_interceptor": 5}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="deploy",
        ships={"falcon_interceptor": 1},
        conn=conn,
    )
    assert not ok
    assert reason == "mission_blocked_foreign_planet"
    conn.close()


def test_spy_own_planet_blocked(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    _seed_ships(pid, uid, {"veil_probe": 2}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="spy",
        ships={"veil_probe": 1},
        conn=conn,
    )
    assert not ok
    assert reason == "mission_blocked_own_planet"
    conn.close()


def test_expedition_wrong_position_blocked(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, p = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 1}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="expedition",
        ships={"solar_skiff": 1},
        conn=conn,
    )
    assert not ok
    assert reason == "mission_blocked_not_expedition_slot"
    conn.close()


def test_api_fleet_send_persists_movement(fleet_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uname = f"api_fleet_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Admiral", conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"mule_courier": 5}, conn=conn)
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    resp = client.post(
        "/api/fleet/send",
        json={
            "origin_planet_id": pid,
            "target_galaxy": g,
            "target_system": s,
            "target_position": p,
            "mission_type": "transport",
            "ships": {"mule_courier": 2},
            "resources": {"metal": 500, "crystal": 0},
            "speed_percent": 100,
        },
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True
    assert body["data"]["fleet"]["status"] == "outbound"

    verify = db()
    try:
        row = verify.execute(
            "SELECT status FROM fleet_movements WHERE player_id = ? ORDER BY id DESC LIMIT 1;",
            (uid,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "outbound"
        assert get_planet_ships(pid, conn=verify).get("mule_courier") == 3
    finally:
        verify.close()


def test_transport_report_uses_german_resource_names(fleet_db):
    from game.fleet import _format_transport_report

    body = _format_transport_report(
        coords="[1:1:1]",
        origin_name="Homeworld",
        target_name="Colony",
        resources={"metal": 2222, "crystal": 2222, "fuel_cells": 100},
        incoming=False,
    )
    assert "Transport nach" in body
    assert "Ferronit" in body
    assert "Crytite" in body
    assert "Brennzellen" in body
    assert "Metal:" not in body
    assert "Crystal:" not in body


def test_transport_can_carry_fuel_cells(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 50000, crystal = 5000, fuel_cells = 8000 WHERE id = ?;",
        (pid,),
    )
    cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (colony2,))
    before_fc = float(cur.fetchone()["fuel_cells"])
    _seed_ships(pid, uid, {"mule_courier": 3}, conn=conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 0, "crystal": 0, "fuel_cells": 500},
        conn=conn,
    )
    assert ok, reason
    fleet_id = result["fleet"]["id"]
    cur.execute(
        "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
        (time.time() - 1, fleet_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (colony2,))
    after_fc = float(cur.fetchone()["fuel_cells"])
    assert after_fc >= before_fc + 500


def test_galaxy_fleet_links_have_query_params(fleet_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    uname = f"gal_fleet_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    resp = client.get("/galaxy")
    body = resp.get_data(as_text=True)
    assert "target_galaxy=" in body
    assert "mission=transport" in body
    assert "mission=expedition" in body
    assert f"target_position={EXPEDITION_POSITION}" in body


def test_api_fleet_state_processes_due_return(fleet_db, monkeypatch):
    import importlib

    import app as app_module

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"mule_courier": 3}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="transport",
        ships={"mule_courier": 1},
        resources={"metal": 100},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    now = time.time()
    cur.execute(
        """
        UPDATE fleet_movements
        SET arrival_at = ?, status = 'returning', return_at = ?
        WHERE id = ?;
        """,
        (now - 200, now - 1, fleet_id),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get(f"/api/fleet/state?planet_id={pid}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["data"]["active_fleets"] == []

    verify = db()
    try:
        row = verify.execute(
            "SELECT status FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()
        assert row["status"] == "completed"
    finally:
        verify.close()


def test_fleet_ui_active_buttons_have_handlers():
    """Non-disabled fleet buttons must be wired in initFleet (static contract)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    tpl = (root / "templates" / "fleet.html").read_text(encoding="utf-8")
    js = (root / "static" / "main.js").read_text(encoding="utf-8")

    assert "fleet-logistics-panel" not in tpl or "fleet-dev-panel" in tpl or "data-fleet-dev-seed" in tpl

    required_bindings = [
        "bindFleetOnce",
        "applyQuickTarget",
        "[data-ship-max]",
        "[data-fleet-res-max]",
        ".fleet-colony-chip",
        "[data-fleet-save-preset]",
        "[data-preset-load]",
        "[data-preset-delete]",
        "/api/dev/fleet/seed-ships",
        "/api/shipyard/build",
        "/api/fleet/preview",
        "/api/fleet/send",
        "/api/fleet/state",
        "rt.sending",
        "data-fleet-send-btn",
        "data-preview-target-type",
        "data-fleet-mission-feedback",
        "updateMissionFeedback",
        "applyExpeditionTarget",
        "tickFleetCountdowns",
        "fleetRefreshBusy",
    ]
    for needle in required_bindings:
        assert needle in js, f"missing initFleet binding: {needle}"

    assert "GC.modules.fleet = initFleet" in js
    assert "GC.modules.shipyard = initShipyard" in js
    assert 'path.endsWith("/fleet")' in js
    assert 'path.endsWith("/shipyard")' in js
    assert 'id="shipyard-page"' in (root / "templates" / "shipyard.html").read_text(encoding="utf-8")
    assert 'data-galaxy="' in tpl
    assert 'name="target_galaxy"' in tpl


def test_quick_target_template_sets_coord_inputs():
    from pathlib import Path

    tpl = (Path(__file__).resolve().parent.parent / "templates" / "fleet.html").read_text(encoding="utf-8")
    assert 'name="target_galaxy"' in tpl
    assert 'name="target_system"' in tpl
    assert 'name="target_position"' in tpl
    assert "data-galaxy" in tpl and "fleet-colony-chip" in tpl
    assert "data-preview-target-type" in tpl
    assert "data-fleet-mission-feedback" in tpl
    assert "data-fleet-send-btn" in tpl


def test_fuel_efficiency_reduces_cost():
    base = calculate_fuel_cost({"mule_courier": 10}, 5000, 100, fuel_efficiency_level=0)
    reduced = calculate_fuel_cost({"mule_courier": 10}, 5000, 100, fuel_efficiency_level=5)
    assert reduced < base
    assert reduced >= int(base * fuel_efficiency_factor(5))


def test_fuel_cost_never_negative():
    assert calculate_fuel_cost({}, 1000, 100) == 0
    assert calculate_fuel_cost({"mule_courier": 1}, 0, 100) == 0


def test_planets_have_fuel_cells_after_migration(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,))
    row = cur.fetchone()
    assert row is not None
    assert float(row["fuel_cells"]) >= 0
    conn.close()


def test_shipyard_build_requires_level(fleet_db):
    from game.shipyard import build_ships

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=100000, crystal=100000)
    conn.commit()
    ok, reason, _ = build_ships(player_id=uid, planet_id=pid, ship_key="mule_courier", amount=1, conn=conn)
    assert not ok
    assert reason == "shipyard_required"
    conn.close()


def test_shipyard_build_adds_ships(fleet_db):
    import time

    from game.fleet import get_planet_ships
    from game.shipyard import build_ships
    from game.shipyard_queue import finish_due_shipyard_jobs_for_planet

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=100000, crystal=100000)
    cur.execute("UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;", (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, result = build_ships(player_id=uid, planet_id=pid, ship_key="mule_courier", amount=2, conn=conn)
    assert ok, reason
    assert result["shipyard_queue"]["summary"]["count"] == 1
    cur.execute(
        "UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;",
        (time.time() - 1, pid),
    )
    conn.commit()
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=time.time())
    assert get_planet_ships(pid, conn=conn).get("mule_courier", 0) >= 2
    conn.close()


def test_shipyard_build_without_resources_fails(fleet_db):
    from game.shipyard import build_ships

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=0, crystal=0, fuel_cells=500)
    cur.execute("UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;", (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, _ = build_ships(player_id=uid, planet_id=pid, ship_key="mule_courier", amount=1, conn=conn)
    assert not ok
    assert reason == "not_enough_resources"
    conn.close()
