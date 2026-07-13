"""Fleet system Phase 1 tests."""
from __future__ import annotations
import json
import time
import uuid
import pytest
from game import db as gdb
from game.db import db
from game.fleet import add_planet_ships, build_distribute_route, build_fleet_incoming_attack_alerts, build_fleet_send_preview, check_attack_limit, get_attack_limit_status, collect_resources, count_active_fleet_slots, create_preset, delete_preset, distribute_resources, fleet_schema_ready, get_fleet_slot_status, get_max_fleet_slots, get_planet_ships, list_presets, mass_expedition, mass_expedition_available_slots, mission_allowed_for_target, preview_fleet_flight, process_fleet_tick, evaluate_fleet_mission_target, resolve_fleet_target, send_fleet, validate_fleet_send, update_preset, _build_spy_report_body, _target_planet_snapshot
from game.expedition_events import calculate_expedition_loot_cap, expedition_event_keys, resolve_expedition_outcome
from game.fleet_calc import apply_departure_deduction, build_collect_route, calculate_distance, calculate_fleet_speed, calculate_flight_seconds, calculate_fuel_cost, calculate_total_cargo, enrich_movement_timing, fleet_ships_are_cargo_only, fuel_efficiency_factor, normalize_collect_source_planet_ids, normalize_ships, split_resources_evenly, split_ships_across_targets, validate_departure_balances
from game.alliance import add_alliance_member, create_alliance
from game.fleet_defs import EXPEDITION_POSITION, FLEET_FUEL_RESOURCE
from game.messages import get_message, list_messages
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, get_research_levels, init_db
from game.planet_evolution.service import colonize_planet

_username_seq = 0


def _policy_safe_username(prefix: str = "flot") -> str:
    """GC-735 — random hex suffixes can contain blocked tokens (e.g. 1488)."""
    from game.name_policy import validate_player_name

    global _username_seq
    for _ in range(128):
        _username_seq += 1
        candidate = f"{prefix}{_username_seq:06d}"
        ok, _ = validate_player_name(candidate)
        if ok:
            return candidate
    raise AssertionError("could not allocate policy-safe username")


@pytest.fixture
def fleet_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'fleet_test.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_path))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
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
    ok, err, user = create_user(_policy_safe_username("flot"), 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Admiral', conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid

def _colonizable_world_field():
    from game.planet_evolution.strategic_worlds import build_strategic_world_field
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get('is_colonizable'):
                return field
    raise AssertionError('no colonizable strategic world in sample grid')

def _unlock_expansion_for_colonize(conn, uid: int) -> None:
    from game.models import get_homeworld
    from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH
    hw = get_homeworld(uid, conn=conn)
    assert hw
    conn.execute('UPDATE planets SET planet_level = 25 WHERE id = ?;', (int(hw['id']),))
    conn.execute('\n        INSERT INTO research_levels (user_id, tech_key, level)\n        VALUES (?, ?, ?)\n        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n        ', (int(uid), INTERSTELLAR_EXPANSION_TECH, 6))
    conn.commit()

def _send_world_colonize(conn, uid: int, pid: int, field: dict, *, colony_name: str='Test Colony', ships: dict | None=None):
    _unlock_expansion_for_colonize(conn, uid)
    ship_payload = ships or {'seed_ark': 1}
    _seed_ships(pid, uid, ship_payload, conn=conn)
    conn.commit()
    return send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=1, target_system=1, target_position=1, mission_type='colonize', ships=ship_payload, colony_name=colony_name, world_key=str(field['world_key']), conn=conn)

def _fund_planet(cur, planet_id: int, *, metal=50000, crystal=50000, fuel_cells=50000):
    cur.execute('UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;', (metal, crystal, fuel_cells, int(planet_id)))

def _grant_ship_test_prereqs(cur, planet_id: int, user_id: int) -> None:
    cur.execute('\n        UPDATE planet_buildings\n        SET research_lab = 10, command_center = 10, barracks = 10\n        WHERE planet_id = ?;\n        ', (int(planet_id),))
    for tech in ('mining_tech', 'drone_tech', 'engine_tech', 'navigation_tech', 'weapon_tech', 'armor_tech', 'storage_tech', 'fuel_efficiency', 'shield_tech'):
        cur.execute('\n            INSERT INTO research_levels (user_id, tech_key, level)\n            VALUES (?, ?, ?)\n            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n            ', (int(user_id), tech, 10))

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
    cur.execute('SELECT galaxy, system, position FROM planets WHERE id = ?;', (int(planet_id),))
    row = cur.fetchone()
    if own:
        conn.close()
    return (int(row['galaxy']), int(row['system']), int(row['position']))

def _second_colony(uid: int, conn=None):
    own = conn is None
    if own:
        conn = db()
    _unlock_expansion_for_colonize(conn, uid)
    ok, reason, extra = colonize_planet(uid, name='Colony Two', galaxy=1, system=300, position=5, conn=conn, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    if own:
        conn.commit()
        conn.close()
    return int(extra['planet_id'])

def _foreign_planet_standalone():
    """Create a second player in an isolated DB session (avoids SQLite lock with test conn)."""
    ok, err, user = create_user(_policy_safe_username("frgn"), 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    conn = db()
    from game.db import begin_write_transaction, commit
    begin_write_transaction(conn)
    ensure_player_and_homeworld(uid, player_name='Foreign', conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    coords = _planet_coords(pid, conn=conn)
    commit(conn)
    conn.close()
    return (uid, pid, coords)

def _allied_players_standalone():
    ok1, err1, u1 = create_user(_policy_safe_username("allya"), 'test-pass-123')
    ok2, err2, u2 = create_user(_policy_safe_username("allyb"), 'test-pass-123')
    assert ok1, err1
    assert ok2, err2
    uid1 = int(u1['id'])
    uid2 = int(u2['id'])
    conn = db()
    from game.db import begin_write_transaction, commit
    begin_write_transaction(conn)
    ensure_player_and_homeworld(uid1, player_name='AllyOne', conn=conn)
    ensure_player_and_homeworld(uid2, player_name='AllyTwo', conn=conn)
    tag = f'T{uuid.uuid4().hex[:6].upper()}'
    alliance = create_alliance(tag, 'Test Alliance', uid1, conn=conn)
    add_alliance_member(alliance['id'], uid2, conn=conn)
    colony2 = _second_colony(uid2, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    commit(conn)
    conn.close()
    return (uid1, uid2, colony2, (g, s, p))

def _count_fleet_messages(uid: int, fleet_id: int, *, category: str | None=None, report_phase: str | None=None) -> int:
    msgs = list_messages(uid, category=category or 'all')
    count = 0
    for item in msgs['data']['messages']:
        detail = get_message(uid, item['id'], mark_read=False)
        meta = detail['data']['message'].get('metadata') or {}
        if int(meta.get('fleet_id') or 0) != int(fleet_id):
            continue
        if report_phase is not None and str(meta.get('report_phase') or '') != str(report_phase):
            continue
        count += 1
    return count

def _fleet_report_metadata(uid: int, fleet_id: int, *, report_phase: str) -> dict:
    msgs = list_messages(uid, category='all')
    for item in msgs['data']['messages']:
        detail = get_message(uid, item['id'], mark_read=False)
        meta = detail['data']['message'].get('metadata') or {}
        if int(meta.get('fleet_id') or 0) == int(fleet_id) and meta.get('report_phase') == report_phase:
            return meta
    return {}

def _force_outbound_arrival(conn, fleet_id: int) -> None:
    cur = conn.cursor()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, int(fleet_id)))
    conn.commit()

def _force_expedition_stay_end(conn, fleet_id: int) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE fleet_movements SET holding_until = ? WHERE id = ? AND status = 'holding';", (time.time() - 1, int(fleet_id)))
    conn.commit()

def _complete_expedition_to_returning(conn, fleet_id: int, *, player_id: int) -> None:
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=player_id, conn=conn)
    conn.commit()
    _force_expedition_stay_end(conn, fleet_id)
    process_fleet_tick(player_id=player_id, conn=conn)
    conn.commit()

def test_calculate_distance_same_system():
    d = calculate_distance((1, 100, 3), (1, 100, 8))
    assert d > 0

def test_calculate_fleet_speed_slowest():
    speed = calculate_fleet_speed({'veil_probe': 1, 'mule_courier': 10})
    assert speed >= 5000

def test_calculate_fuel_and_cargo():
    ships = {'mule_courier': 2}
    assert calculate_total_cargo(ships) == 10000
    assert calculate_fuel_cost(ships, 1000, 100) >= 0

def test_speed_percent_validation_range():
    sec_fast = calculate_flight_seconds(1000, 5000, 100)
    sec_slow = calculate_flight_seconds(1000, 5000, 10)
    assert sec_slow >= sec_fast

def test_calculate_flight_seconds_admin_speed_multiplier():
    base = calculate_flight_seconds(1000, 5000, 100)
    fast = calculate_flight_seconds(1000, 5000, 100, admin_speed_multiplier=10.0)
    assert fast < base
    assert fast >= 1

def test_admin_fleet_speed_peaceful_applied_in_preview(fleet_db, monkeypatch):
    from game.models import save_game_settings
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, p = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    origin = dict(cur.fetchone())
    conn.commit()
    conn.close()
    save_game_settings({'fleet_speed_peaceful': 1.0})
    conn = db()
    slow = preview_fleet_flight(origin_planet=origin, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, ships={'solar_skiff': 1}, resources={}, speed_percent=100, player_id=uid, mission_type='expedition', conn=conn)
    conn.close()
    save_game_settings({'fleet_speed_peaceful': 10.0})
    conn = db()
    fast = preview_fleet_flight(origin_planet=origin, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, ships={'solar_skiff': 1}, resources={}, speed_percent=100, player_id=uid, mission_type='expedition', conn=conn)
    assert int(fast['flight_seconds']) < int(slow['flight_seconds'])
    conn.close()
    save_game_settings({'fleet_speed_peaceful': 1.0})

def test_expedition_holding_duration_from_hours(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='expedition', ships={'solar_skiff': 1}, expedition_hours=3, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    before = time.time()
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, holding_until FROM fleet_movements WHERE id = ?;', (fleet_id,))
    row = dict(cur.fetchone())
    assert row['status'] == 'holding'
    assert int(row['holding_until']) >= int(before) + 3 * 3600 - 5
    conn.close()

def test_calculate_flight_seconds_ogame_scale():
    same_system = calculate_flight_seconds(20, 5000, 100)
    cross_system = calculate_flight_seconds(3815, 5000, 100)
    assert same_system >= 1
    assert cross_system > same_system
    assert cross_system >= 60

def test_enrich_movement_timing_outbound_returning_and_holding():
    now = 1700000000.0
    outbound = enrich_movement_timing({'status': 'outbound', 'departure_at': int(now), 'arrival_at': int(now) + 300, 'flight_seconds': 300}, now=now)
    assert outbound['countdown_at'] == int(now) + 300
    assert outbound['remaining_seconds'] == 300
    assert outbound['duration_seconds'] == 300
    assert outbound['leg_phase'] == 'outbound'
    assert outbound['leg_label_key'] == 'fleet_leg_outbound'
    assert outbound['phase'] == 'outbound'
    assert outbound['status_label'] == 'fleet_leg_outbound'
    assert outbound['home_at'] == int(now) + 600
    returning = enrich_movement_timing({'status': 'returning', 'departure_at': int(now), 'arrival_at': int(now) + 300, 'return_at': int(now) + 500, 'flight_seconds': 200}, now=now + 350)
    assert returning['countdown_at'] == int(now) + 500
    assert returning['return_arrival_at'] == int(now) + 500
    assert returning['return_started_at'] == int(now) + 300
    assert returning['remaining_seconds'] == 150
    assert returning['leg_phase'] == 'returning'
    assert returning['leg_label_key'] == 'fleet_leg_returning'
    assert returning['phase'] == 'returning'
    assert returning['status_label'] == 'fleet_leg_returning'
    assert returning['home_at'] == int(now) + 500
    assert returning['home_remaining_seconds'] == 150
    holding = enrich_movement_timing({'status': 'holding', 'departure_at': int(now), 'arrival_at': int(now) + 120, 'holding_until': int(now) + 3720, 'flight_seconds': 120}, now=now + 200)
    assert holding['countdown_at'] == int(now) + 3720
    assert holding['remaining_seconds'] == 3520
    assert holding['phase'] == 'holding'
    assert holding['status_label'] == 'fleet_leg_holding'
    assert holding['home_at'] == int(now) + 3720 + 120
    assert holding['home_remaining_seconds'] == 3640

def test_movement_home_at_outbound_hold_and_expedition():
    from game.fleet_calc import movement_home_at
    now = 1700000000
    transport = movement_home_at({'mission_type': 'transport', 'status': 'outbound', 'arrival_at': now + 300, 'flight_seconds': 300})
    assert transport == now + 600
    hold = movement_home_at({'mission_type': 'hold', 'status': 'outbound', 'arrival_at': now + 120, 'flight_seconds': 120})
    assert hold == now + 120 + 3600 + 120
    deploy = movement_home_at({'mission_type': 'deploy', 'status': 'outbound', 'arrival_at': now + 60})
    assert deploy == 0

def test_preview_send_flight_timing_parity(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    origin = dict(cur.fetchone())
    conn.commit()
    preview = build_fleet_send_preview(player_id=uid, origin_planet=origin, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 0}, speed_percent=100, conn=conn)
    assert preview['can_send']
    preview_dur = int(preview['duration_seconds'])
    assert preview_dur == int(preview['flight_seconds'])
    assert int(preview['arrival_at']) - int(preview['departure_at']) == preview_dur
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 0}, speed_percent=100, conn=conn)
    assert ok, reason
    fleet = result['fleet']
    assert int(fleet['flight_seconds']) == preview_dur
    assert int(fleet['arrival_at']) - int(fleet['departure_at']) == preview_dur
    assert abs(int(fleet['arrival_at']) - int(preview['arrival_at'])) <= 2
    conn.close()

def test_transport_return_timing_after_arrival(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 100}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('SELECT flight_seconds FROM fleet_movements WHERE id = ?;', (fleet_id,))
    leg = int(cur.fetchone()['flight_seconds'])
    now = time.time()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, return_at FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = dict(cur.fetchone())
    assert mv['status'] == 'returning'
    assert int(mv['return_at']) >= int(now) + leg - 2
    assert int(mv['return_at']) <= int(now) + leg + 2
    conn.close()

def test_overview_activities_exclude_fleet_movements(fleet_db):
    from game.fleet import list_active_movements, send_fleet
    from game.overview_page import build_activity_lines
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, conn=conn)
    assert ok
    movements = list_active_movements(uid, conn=conn)
    assert movements
    lines = build_activity_lines({}, {})
    fleet_rows = [row for row in lines if str(row.get('key') or '').startswith('fleet')]
    assert fleet_rows == []
    conn.close()

def test_fleet_schema_ready(fleet_db):
    conn = db()
    assert fleet_schema_ready(conn) is True
    conn.close()

def _set_research_level(cur, user_id: int, tech_key: str, level: int) -> None:
    cur.execute('\n        INSERT INTO research_levels (user_id, tech_key, level)\n        VALUES (?, ?, ?)\n        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n        ', (int(user_id), str(tech_key), int(level)))

def test_max_fleet_slots_fallback(fleet_db):
    uid = _player()
    assert get_max_fleet_slots(uid) == 3

def test_max_fleet_slots_navigation_tiers(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    cur = conn.cursor()
    cases = [(0, 3), (2, 3), (3, 4), (4, 4), (5, 5), (7, 5), (8, 6), (9, 6), (10, 7), (12, 7), (13, 8), (16, 9), (25, 12)]
    for level, expected in cases:
        _set_research_level(cur, uid, 'navigation_tech', level)
        conn.commit()
        assert get_max_fleet_slots(uid, conn=conn) == expected, f'nav {level}'
    conn.close()

def test_navigation_unlocks_fourth_fleet_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    _set_research_level(cur, uid, 'navigation_tech', 3)
    _seed_ships(pid, uid, {'mule_courier': 100}, conn=conn)
    conn.commit()
    for wave in range(4):
        ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1}, conn=conn)
        assert ok, f'wave {wave + 1}: {reason}'
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1}, conn=conn)
    assert not ok
    assert reason == 'fleet_slots_full'
    conn.close()

def test_fleet_send_success(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 10000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 5, 'falcon_interceptor': 10}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 2}, resources={'metal': 1000, 'crystal': 0}, speed_percent=100, conn=conn)
    assert ok, reason
    conn.commit()
    conn.close()
    verify = db()
    try:
        assert get_planet_ships(pid, conn=verify).get('mule_courier') == 3
        row = verify.execute('SELECT status FROM fleet_movements WHERE player_id = ? ORDER BY id DESC LIMIT 1;', (uid,)).fetchone()
        assert row is not None
        assert row['status'] == 'outbound'
    finally:
        verify.close()

def test_not_enough_ships_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    _seed_ships(pid, uid, {'mule_courier': 1}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 5}, conn=conn)
    assert not ok
    assert reason == 'not_enough_ships'
    conn.close()

def test_unknown_ship_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships={'deathstar': 1}, conn=conn)
    assert not ok
    assert reason == 'unknown_ship'
    conn.close()

def test_same_origin_target_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, p = _planet_coords(pid, conn=conn)
    _seed_ships(pid, uid, {'falcon_interceptor': 5}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships={'falcon_interceptor': 1}, conn=conn)
    assert not ok
    assert reason == 'same_origin_target'
    conn.close()

def test_not_enough_cargo_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 999999 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 1}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 99999}, conn=conn)
    assert not ok
    assert reason == 'not_enough_cargo'
    conn.close()

def test_not_enough_resources_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 100, crystal = 0 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 5000}, conn=conn)
    assert not ok
    assert reason == 'not_enough_resources'
    conn.close()

def test_not_enough_fuel_fails(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 0 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'falcon_interceptor': 10}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships={'falcon_interceptor': 5}, conn=conn)
    assert not ok
    assert reason == 'not_enough_fuel'
    conn.close()

def test_slot_limit_fails(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(pid, uid, {'mule_courier': 100}, conn=conn)
    conn.commit()
    for _ in range(3):
        ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1}, conn=conn)
        assert ok, reason
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1}, conn=conn)
    assert not ok
    assert reason == 'fleet_slots_full'
    conn.close()

def test_speed_percent_validation(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    _seed_ships(pid, uid, {'veil_probe': 1}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='spy', ships={'veil_probe': 1}, speed_percent=5, conn=conn)
    assert not ok
    assert reason == 'invalid_speed_percent'
    conn.close()

def test_create_preset_success(fleet_db):
    uid = _player()
    ok, reason, preset = create_preset(uid, name='Raid Alpha', preset_type='raid', ships_json={'falcon_interceptor': 100}, speed_percent=100, mission_type='attack')
    assert ok, reason
    assert preset['name'] == 'Raid Alpha'
    assert preset.get('resources') == {} or json.loads(preset.get('resources_json') or '{}') == {}

def test_create_preset_default_resources_json_not_null(fleet_db):
    """Migration 043: resources_json is NOT NULL — inserts must use '{}'."""
    uid = _player()
    ok, reason, preset = create_preset(uid, name='Empty cargo', preset_type='custom', ships_json={'mule_courier': 1})
    assert ok, reason
    conn = db()
    try:
        row = conn.execute('SELECT resources_json FROM fleet_presets WHERE id = ?;', (int(preset['id']),)).fetchone()
        assert row is not None
        assert row['resources_json'] is not None
        assert json.loads(row['resources_json']) == {}
    finally:
        conn.close()

def test_list_presets(fleet_db):
    uid = _player()
    create_preset(uid, name='Farm', preset_type='farm', ships_json={'falcon_interceptor': 50})
    presets = list_presets(uid)
    assert len(presets) >= 1

def test_update_preset(fleet_db):
    uid = _player()
    ok, _, preset = create_preset(uid, name='Old', preset_type='custom', ships_json={'mule_courier': 1})
    ok2, reason, updated = update_preset(preset['id'], uid, {'name': 'New Name'})
    assert ok2, reason
    assert updated['name'] == 'New Name'

def test_delete_preset(fleet_db):
    uid = _player()
    ok, _, preset = create_preset(uid, name='Del', preset_type='custom', ships_json={'mule_courier': 1})
    ok2, reason = delete_preset(preset['id'], uid)
    assert ok2, reason

def test_preset_foreign_player(fleet_db):
    uid1 = _player()
    uid2 = _player()
    ok, _, preset = create_preset(uid1, name='Secret', preset_type='spy', ships_json={'veil_probe': 1})
    ok2, reason, _ = update_preset(preset['id'], uid2, {'name': 'Hack'})
    assert not ok2
    assert reason == 'preset_not_found'

def test_preset_unknown_ship(fleet_db):
    uid = _player()
    ok, reason, _ = create_preset(uid, name='Bad', preset_type='custom', ships_json={'invalid_ship': 1})
    assert not ok
    assert reason == 'unknown_ship'

def test_collect_arrival_debits_target_and_returns(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planets SET metal = 12000, crystal = 3000, fuel_cells = 500 WHERE id = ?;', (colony2,))
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (colony2,))
    before = dict(cur.fetchone())
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = cur.fetchone()
    assert mv['status'] == 'returning'
    resources = json.loads(mv['resources_json'])
    assert resources['metal'] == 5000
    assert resources['crystal'] == 0
    assert resources['fuel_cells'] == 0
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (colony2,))
    after = dict(cur.fetchone())
    assert int(after['metal']) == int(before['metal']) - 5000
    assert int(after['crystal']) == int(before['crystal'])
    conn.close()

def test_collect_return_credits_origin(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planets SET metal = 8000, crystal = 2000 WHERE id = ?;', (colony2,))
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_before = dict(cur.fetchone())
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    now = time.time()
    cur.execute("UPDATE fleet_movements SET arrival_at = ?, status = 'returning', return_at = ?, resources_json = ? WHERE id = ?;", (now - 200, now - 1, json.dumps({'metal': 3000, 'crystal': 500, 'fuel_cells': 0}), fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_after = dict(cur.fetchone())
    assert int(origin_after['metal']) == int(origin_before['metal']) + 3000
    assert int(origin_after['crystal']) == int(origin_before['crystal']) + 500
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'completed'
    conn.close()

def test_collect_with_departure_cargo(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planets SET metal = 20000, crystal = 0 WHERE id = ?;', (colony2,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, resources={'metal': 1000, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    resources = json.loads(cur.fetchone()['resources_json'])
    assert resources['metal'] == 5000
    conn.close()

def test_collect_fills_max_cargo_capacity(fleet_db):
    from game.fleet_calc import loaded_resource_total
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planets SET metal = 8000, crystal = 10000, fuel_cells = 5000 WHERE id = ?;', (colony2,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 2}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    resources = json.loads(cur.fetchone()['resources_json'])
    assert loaded_resource_total(resources) == 10000
    assert resources['metal'] == 8000
    assert resources['crystal'] == 2000
    assert resources['fuel_cells'] == 0
    conn.close()

def test_collect_foreign_blocked(fleet_db):
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, conn=conn)
    assert not ok
    assert reason == 'mission_blocked_foreign_planet'
    conn.close()

def test_collect_requires_cargo_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    _seed_ships(pid, uid, {'veil_probe': 5}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'veil_probe': 1}, conn=conn)
    assert not ok
    assert reason == 'cargo_required_for_collect'
    conn.close()

def test_collect_creates_report(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planets SET metal = 4000, crystal = 0 WHERE id = ?;', (colony2,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    msgs = list_messages(uid, category='system')
    messages = msgs['data']['messages']
    assert len(messages) >= 1
    meta = _fleet_report_metadata(uid, fleet_id, report_phase='logistics_collect_arrival')
    assert meta.get('mission_type') == 'collect'
    assert meta.get('report_phase') == 'logistics_collect_arrival'
    assert meta.get('collected', {}).get('metal') == 4000
    assert meta.get('origin_planet_id') == pid
    assert meta.get('target_planet_id') == colony2
    assert meta.get('timestamp')
    assert meta.get('ships')
    conn.close()

def test_transport_creates_report_on_arrival(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1500, 'crystal': 0}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, category='system') == 1
    detail = get_message(uid, list_messages(uid, category='system')['data']['messages'][0]['id'], mark_read=False)
    meta = detail['data']['message'].get('metadata') or {}
    assert meta.get('direction') == 'outbound'
    assert meta.get('resources', {}).get('metal') == 1500
    conn.close()

def test_deploy_creates_report_on_arrival(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'falcon_interceptor': 8}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships={'falcon_interceptor': 3}, resources={'metal': 100}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, category='system') == 1
    detail = get_message(uid, list_messages(uid, category='system')['data']['messages'][0]['id'], mark_read=False)
    meta = detail['data']['message'].get('metadata') or {}
    assert meta.get('mission_type') == 'deploy'
    assert meta.get('ships', {}).get('falcon_interceptor') == 3
    conn.close()

def test_hold_creates_report_on_arrival(fleet_db):
    conn = db()
    uid1, _uid2, _ally_pid, (g, s, p) = _allied_players_standalone()
    pid = int(get_planets_by_player(uid1, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid1, {'falcon_interceptor': 5}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid1, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='hold', ships={'falcon_interceptor': 2}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid1, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid1, fleet_id, category='system') == 1
    detail = get_message(uid1, list_messages(uid1, category='system')['data']['messages'][0]['id'], mark_read=False)
    meta = detail['data']['message'].get('metadata') or {}
    assert meta.get('mission_type') == 'hold'
    assert int(meta.get('holding_until') or 0) > int(time.time())
    conn.close()

def test_colonize_creates_success_report_on_arrival(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    field = _colonizable_world_field()
    conn.commit()
    ok, _, result = _send_world_colonize(conn, uid, pid, field, colony_name='Report Colony')
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, category='combat') == 1
    detail = get_message(uid, list_messages(uid, category='combat')['data']['messages'][0]['id'], mark_read=False)
    meta = detail['data']['message'].get('metadata') or {}
    assert meta.get('mission_type') == 'colonize'
    assert meta.get('colony_name') == 'Report Colony'
    conn.close()

def test_colonize_creates_failure_report_on_arrival(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    field = _colonizable_world_field()
    conn.commit()
    ok1, _, result1 = _send_world_colonize(conn, uid, pid, field, colony_name='First Colony', ships={'seed_ark': 2})
    assert ok1
    ok2, _, result2 = _send_world_colonize(conn, uid, pid, field, colony_name='Second Colony', ships={'seed_ark': 1})
    assert ok2
    fleet_id = result2['fleet']['id']
    _force_outbound_arrival(conn, result1['fleet']['id'])
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, category='combat') == 1
    failure_detail = None
    for item in list_messages(uid, category='combat')['data']['messages']:
        detail = get_message(uid, item['id'], mark_read=False)
        meta = detail['data']['message'].get('metadata') or {}
        if int(meta.get('fleet_id') or 0) == fleet_id:
            failure_detail = detail
            break
    assert failure_detail is not None
    meta = failure_detail['data']['message'].get('metadata') or {}
    assert meta.get('reason') == 'world_already_claimed'
    conn.close()

def test_fleet_arrival_messages_idempotent_on_double_tick(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'mule_courier': 3, 'falcon_interceptor': 6}, conn=conn)
    conn.commit()
    ok_t, _, transport = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 50}, conn=conn)
    ok_d, _, deploy = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships={'falcon_interceptor': 1}, conn=conn)
    assert ok_t and ok_d
    transport_id = transport['fleet']['id']
    deploy_id = deploy['fleet']['id']
    _force_outbound_arrival(conn, transport_id)
    _force_outbound_arrival(conn, deploy_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    transport_once = _count_fleet_messages(uid, transport_id, category='system')
    deploy_once = _count_fleet_messages(uid, deploy_id, category='system')
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, transport_id, category='system') == transport_once
    assert _count_fleet_messages(uid, deploy_id, category='system') == deploy_once
    assert transport_once == 1
    assert deploy_once == 1
    conn.close()

def test_return_tick_does_not_create_arrival_report(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 100}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    now = time.time()
    cur.execute("UPDATE fleet_movements SET arrival_at = ?, status = 'returning', return_at = ? WHERE id = ?;", (now - 200, now - 1, fleet_id))
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, category='system') == 0
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, category='system') == 0
    conn.close()

def test_transport_arrival_credits_target(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (colony2,))
    before = dict(cur.fetchone())
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 2000, 'crystal': 500}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = cur.fetchone()
    assert mv['status'] == 'returning'
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (colony2,))
    after = dict(cur.fetchone())
    assert int(after['metal']) == int(before['metal']) + 2000
    assert int(after['crystal']) == int(before['crystal']) + 500
    conn.close()

def test_transport_arrival_double_tick_idempotent_resources(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 10000, crystal = 1000 WHERE id = ?;', (colony2,))
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 3000, 'crystal': 200}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    tick1 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (colony2,))
    after_once = dict(cur.fetchone())
    tick2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (colony2,))
    after_twice = dict(cur.fetchone())
    assert int(tick1.get('processed_arrivals') or 0) == 1
    assert int(tick2.get('processed_arrivals') or 0) == 0
    assert after_once == after_twice
    assert int(after_twice['metal']) == 13000
    assert int(after_twice['crystal']) == 1200
    conn.close()

def test_colonize_arrival_double_tick_single_colony(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    field = _colonizable_world_field()
    cur.execute('SELECT COUNT(*) AS n FROM planets WHERE player_id = ?;', (uid,))
    planets_before = int(cur.fetchone()['n'])
    conn.commit()
    ok, _, result = _send_world_colonize(conn, uid, pid, field, colony_name='Idempotent Colony')
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    tick1 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT COUNT(*) AS n FROM planets WHERE player_id = ?;', (uid,))
    planets_once = int(cur.fetchone()['n'])
    tick2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT COUNT(*) AS n FROM planets WHERE player_id = ?;', (uid,))
    planets_twice = int(cur.fetchone()['n'])
    assert int(tick1.get('processed_arrivals') or 0) == 1
    assert int(tick2.get('processed_arrivals') or 0) == 0
    assert planets_once == planets_before + 1
    assert planets_twice == planets_once
    conn.close()

def test_expedition_arrival_and_return_double_tick_idempotent_loot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 2}, conn=conn)
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_before = dict(cur.fetchone())
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='expedition', ships={'solar_skiff': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    tick_arr1 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    row_holding = dict(cur.fetchone())
    assert row_holding['status'] == 'holding'
    _force_expedition_stay_end(conn, fleet_id)
    tick_arr2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    row_once = dict(cur.fetchone())
    rewards_once = json.loads(row_once['resources_json'] or '{}')
    tick_arr3 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    rewards_twice = json.loads(dict(cur.fetchone())['resources_json'] or '{}')
    assert int(tick_arr1.get('processed_arrivals') or 0) == 1
    assert int(tick_arr2.get('processed_holding') or 0) == 1
    assert int(tick_arr3.get('processed_holding') or 0) == 0
    assert row_once['status'] == 'returning'
    assert rewards_twice == rewards_once
    now = time.time()
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    tick_ret1 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_after_once = dict(cur.fetchone())
    tick_ret2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_after_twice = dict(cur.fetchone())
    assert int(tick_ret1.get('processed_returns') or 0) == 1
    assert int(tick_ret2.get('processed_returns') or 0) == 0
    assert origin_after_once == origin_after_twice
    loot_metal = int(rewards_once.get('metal') or 0)
    loot_crystal = int(rewards_once.get('crystal') or 0)
    assert int(origin_after_twice['metal']) == int(origin_before['metal']) + loot_metal
    assert int(origin_after_twice['crystal']) == int(origin_before['crystal']) + loot_crystal
    conn.close()

def _expedition_returning_with_loot(conn, uid, pid):
    """Send expedition, resolve holding, return movement id + loot + origin snapshot."""
    from game.fleet import process_fleet_tick, send_fleet
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='expedition', ships={'solar_skiff': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    _force_expedition_stay_end(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    row = dict(cur.fetchone())
    assert row['status'] == 'returning'
    rewards = json.loads(row['resources_json'] or '{}')
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (pid,))
    origin_before = dict(cur.fetchone())
    return (fleet_id, rewards, origin_before)

def test_expedition_return_credit_survives_live_state_poll(fleet_db):
    """GC-620K: poll refresh must not overwrite fleet return credits."""
    from game.logic import read_player_live_state_for_poll
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    fleet_id, rewards, origin_before = _expedition_returning_with_loot(conn, uid, pid)
    now = time.time()
    conn.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    read_player_live_state_for_poll(uid, conn=conn)
    conn.commit()
    cur = conn.cursor()
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'completed'
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_after = dict(cur.fetchone())
    loot_metal = int(rewards.get('metal') or 0)
    loot_crystal = int(rewards.get('crystal') or 0)
    assert int(origin_after['metal']) == int(origin_before['metal']) + loot_metal
    assert int(origin_after['crystal']) == int(origin_before['crystal']) + loot_crystal
    conn.close()

def test_expedition_return_credit_poll_idempotent(fleet_db):
    from game.logic import read_player_live_state_for_poll
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    fleet_id, rewards, origin_before = _expedition_returning_with_loot(conn, uid, pid)
    loot_metal = int(rewards.get('metal') or 0)
    loot_crystal = int(rewards.get('crystal') or 0)
    if loot_metal <= 0 and loot_crystal <= 0:
        rewards = {'metal': 500, 'crystal': 200, 'fuel_cells': 0, 'expedition_hours': 1}
        loot_metal = 500
        loot_crystal = 200
        conn.execute('UPDATE fleet_movements SET resources_json = ? WHERE id = ?;', (json.dumps(rewards), fleet_id))
        conn.commit()
    now = time.time()
    conn.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    read_player_live_state_for_poll(uid, conn=conn)
    conn.commit()
    read_player_live_state_for_poll(uid, conn=conn)
    conn.commit()
    cur = conn.cursor()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_after = dict(cur.fetchone())
    assert int(origin_after['metal']) == int(origin_before['metal']) + loot_metal
    assert int(origin_after['crystal']) == int(origin_before['crystal']) + loot_crystal
    conn.close()

def test_expedition_return_credit_admin_advance_phases(fleet_db):
    from game.fleet import admin_advance_fleet_movement, process_fleet_tick, send_fleet
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='expedition', ships={'solar_skiff': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_before = dict(cur.fetchone())
    adv_holding = admin_advance_fleet_movement(fleet_id, conn=conn, complete=False)
    conn.commit()
    assert adv_holding['ok'] is True
    assert adv_holding['status_after'] == 'returning'
    cur.execute('SELECT resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    rewards = json.loads(dict(cur.fetchone())['resources_json'] or '{}')
    loot_metal = int(rewards.get('metal') or 0)
    loot_crystal = int(rewards.get('crystal') or 0)
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    mid = dict(cur.fetchone())
    assert int(mid['metal']) == int(origin_before['metal'])
    assert int(mid['crystal']) == int(origin_before['crystal'])
    adv_complete = admin_advance_fleet_movement(fleet_id, conn=conn, complete=True)
    conn.commit()
    assert adv_complete['ok'] is True
    assert adv_complete['status_after'] == 'completed'
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    origin_after = dict(cur.fetchone())
    assert int(origin_after['metal']) == int(origin_before['metal']) + loot_metal
    assert int(origin_after['crystal']) == int(origin_before['crystal']) + loot_crystal
    conn.close()

def _planet_stock(conn, planet_id: int) -> dict:
    cur = conn.cursor()
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (int(planet_id),))
    row = dict(cur.fetchone())
    return {'metal': int(float(row['metal'])), 'crystal': int(float(row['crystal'])), 'fuel_cells': int(float(row['fuel_cells'] or 0))}

def _pin_planet_last_update(conn, planet_id: int, ts: float | None=None) -> float:
    pinned = float(ts if ts is not None else time.time())
    conn.execute('UPDATE planets SET last_update = ? WHERE id = ?;', (pinned, int(planet_id)))
    conn.commit()
    return pinned

def _loaded_fleet_credit(resources: dict) -> dict:
    from game.fleet_calc import calculate_loaded_resources
    return calculate_loaded_resources(resources)

def _assert_stock_before_plus_credit(before: dict, after: dict, credit: dict) -> None:
    for key in ('metal', 'crystal', 'fuel_cells'):
        expected = before[key] + int(credit.get(key) or 0)
        assert after[key] == expected, f'{key}: expected {expected} (= {before[key]} + {credit.get(key) or 0}), got {after[key]}'

def _complete_return_via_live_refresh(conn, uid: int, *, mode: str) -> None:
    if mode == 'poll':
        from game.logic import read_player_live_state_for_poll
        read_player_live_state_for_poll(uid, conn=conn)
    elif mode == 'refresh':
        from game.logic import refresh_player_live_state
        refresh_player_live_state(uid, conn=conn, finish_source='test_gc620k_contract')
    else:
        raise ValueError(f'unknown live refresh mode: {mode}')
    conn.commit()

@pytest.mark.parametrize('live_refresh', ('poll', 'refresh'))
def test_gc620k_contract_expedition_return_credit_invariant(fleet_db, live_refresh):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    fleet_id, rewards, _origin_before = _expedition_returning_with_loot(conn, uid, pid)
    credit = _loaded_fleet_credit(rewards)
    if credit['metal'] <= 0 and credit['crystal'] <= 0 and (credit['fuel_cells'] <= 0):
        rewards = {'metal': 500, 'crystal': 200, 'fuel_cells': 0, 'expedition_hours': 1}
        credit = _loaded_fleet_credit(rewards)
        conn.execute('UPDATE fleet_movements SET resources_json = ? WHERE id = ?;', (json.dumps(rewards), fleet_id))
        conn.commit()
    _pin_planet_last_update(conn, pid)
    before = _planet_stock(conn, pid)
    conn.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    _complete_return_via_live_refresh(conn, uid, mode=live_refresh)
    after = _planet_stock(conn, pid)
    _assert_stock_before_plus_credit(before, after, credit)
    conn.close()

@pytest.mark.parametrize('live_refresh', ('poll', 'refresh'))
def test_gc620k_contract_collect_return_credit_invariant(fleet_db, live_refresh):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    cur.execute('UPDATE planets SET metal = 8000, crystal = 2000 WHERE id = ?;', (colony2,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    credit = {'metal': 3000, 'crystal': 500, 'fuel_cells': 0}
    now = time.time()
    cur.execute("\n        UPDATE fleet_movements\n        SET arrival_at = ?, status = 'returning', return_at = ?, resources_json = ?\n        WHERE id = ?;\n        ", (now - 200, now - 1, json.dumps(credit), fleet_id))
    conn.commit()
    _pin_planet_last_update(conn, pid)
    before = _planet_stock(conn, pid)
    _complete_return_via_live_refresh(conn, uid, mode=live_refresh)
    after = _planet_stock(conn, pid)
    _assert_stock_before_plus_credit(before, after, credit)
    row = conn.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()
    assert row['status'] == 'completed'
    conn.close()

@pytest.mark.parametrize('live_refresh', ('poll', 'refresh'))
def test_gc620k_contract_attack_return_credit_invariant(fleet_db, live_refresh):
    from game.fleet_calc import loaded_resource_total
    from game.models import add_planet_defense
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _fund_planet(cur, foreign_pid, metal=80000, crystal=40000, fuel_cells=20000)
    attack_ships = {'ironclad_frigate': 12, 'mule_courier': 1}
    _seed_ships(pid, uid, attack_ships, conn=conn)
    add_planet_defense(foreign_pid, {'sentinel_turret': 8}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships=attack_ships, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    row = dict(cur.fetchone())
    assert row['status'] == 'returning'
    credit = _loaded_fleet_credit(json.loads(row['resources_json'] or '{}'))
    assert loaded_resource_total(credit) > 0
    _pin_planet_last_update(conn, pid)
    before = _planet_stock(conn, pid)
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    _complete_return_via_live_refresh(conn, uid, mode=live_refresh)
    after = _planet_stock(conn, pid)
    _assert_stock_before_plus_credit(before, after, credit)
    conn.close()

def test_gc620k_contract_admin_complete_expedition_credit_invariant(fleet_db):
    from game.fleet import admin_advance_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    fleet_id, rewards, _ = _expedition_returning_with_loot(conn, uid, pid)
    credit = _loaded_fleet_credit(rewards)
    if credit['metal'] <= 0 and credit['crystal'] <= 0 and (credit['fuel_cells'] <= 0):
        rewards = {'metal': 500, 'crystal': 200, 'fuel_cells': 0, 'expedition_hours': 1}
        credit = _loaded_fleet_credit(rewards)
        conn.execute('UPDATE fleet_movements SET resources_json = ? WHERE id = ?;', (json.dumps(rewards), fleet_id))
        conn.commit()
    _pin_planet_last_update(conn, pid)
    before = _planet_stock(conn, pid)
    result = admin_advance_fleet_movement(fleet_id, conn=conn, complete=True)
    conn.commit()
    assert result['ok'] is True
    assert result['status_after'] == 'completed'
    after = _planet_stock(conn, pid)
    _assert_stock_before_plus_credit(before, after, credit)
    conn.close()

def test_gc620k_live_refresh_never_drops_stock_without_spend(fleet_db):
    """Repeated poll/refresh after return must not erase fleet credits."""
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    fleet_id, rewards, _ = _expedition_returning_with_loot(conn, uid, pid)
    credit = _loaded_fleet_credit(rewards)
    if credit['metal'] <= 0 and credit['crystal'] <= 0 and (credit['fuel_cells'] <= 0):
        rewards = {'metal': 500, 'crystal': 200, 'fuel_cells': 0, 'expedition_hours': 1}
        credit = _loaded_fleet_credit(rewards)
        conn.execute('UPDATE fleet_movements SET resources_json = ? WHERE id = ?;', (json.dumps(rewards), fleet_id))
        conn.commit()
    _pin_planet_last_update(conn, pid)
    before = _planet_stock(conn, pid)
    conn.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    _complete_return_via_live_refresh(conn, uid, mode='poll')
    credited_floor = _planet_stock(conn, pid)
    _assert_stock_before_plus_credit(before, credited_floor, credit)
    for mode in ('refresh', 'poll', 'refresh'):
        _complete_return_via_live_refresh(conn, uid, mode=mode)
        current = _planet_stock(conn, pid)
        for key in ('metal', 'crystal', 'fuel_cells'):
            assert current[key] >= credited_floor[key]
    conn.close()

def test_returning_restores_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'mule_courier': 5}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 2}, resources={'metal': 100}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    now = time.time()
    cur.execute("UPDATE fleet_movements SET arrival_at = ?, status = 'returning', return_at = ? WHERE id = ?;", (now - 100, now - 1, fleet_id))
    conn.commit()
    before_ships = get_planet_ships(pid, conn=conn).get('mule_courier', 0)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    after_ships = get_planet_ships(pid, conn=conn).get('mule_courier', 0)
    assert after_ships == before_ships + 2
    conn.close()

def test_deploy_stations_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'falcon_interceptor': 10}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships={'falcon_interceptor': 4}, resources={'metal': 50}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert get_planet_ships(colony2, conn=conn).get('falcon_interceptor') == 4
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'completed'
    conn.close()

def test_spy_creates_report(fleet_db):
    _foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'veil_probe': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='spy', ships={'veil_probe': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur = conn.cursor()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    msgs = list_messages(uid, category='espionage')
    assert msgs['ok']
    messages = msgs['data']['messages']
    assert len(messages) >= 1
    detail = get_message(uid, messages[0]['id'], mark_read=False)
    meta = detail['data']['message'].get('metadata') or {}
    assert meta.get('report_version') == 2
    assert meta.get('intel_tiers', {}).get('target') is True
    assert meta.get('intel_tiers', {}).get('resources') is False
    assert meta.get('resources') == {}
    conn.close()

def _spy_report_meta(conn, *, uid: int, origin_pid: int, target_g: int, target_s: int, target_p: int, probes: int) -> dict:
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=origin_pid, target_galaxy=target_g, target_system=target_s, target_position=target_p, mission_type='spy', ships={'veil_probe': probes}, conn=conn)
    assert ok, result
    fleet_id = result['fleet']['id']
    cur = conn.cursor()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    msgs = list_messages(uid, category='espionage')
    messages = msgs['data']['messages']
    assert messages
    detail = get_message(uid, messages[0]['id'], mark_read=False)
    return detail['data']['message'].get('metadata') or {}

def test_spy_report_tier2_reveals_resources(fleet_db):
    _foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _fund_planet(cur, foreign_pid, metal=12000, crystal=3400, fuel_cells=99)
    _seed_ships(pid, uid, {'veil_probe': 5}, conn=conn)
    conn.commit()
    meta = _spy_report_meta(conn, uid=uid, origin_pid=pid, target_g=g, target_s=s, target_p=p, probes=2)
    tiers = meta.get('intel_tiers') or {}
    assert tiers.get('resources') is True
    assert tiers.get('fuel') is False
    res = meta.get('resources') or {}
    assert res.get('metal') == 12000
    assert res.get('crystal') == 3400
    assert 'fuel_cells' not in res
    conn.close()

def test_spy_report_tier4_reveals_fleet(fleet_db):
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'veil_probe': 6}, conn=conn)
    _seed_ships(foreign_pid, foreign_uid, {'falcon_interceptor': 3, 'mule_courier': 2}, conn=conn)
    conn.commit()
    meta = _spy_report_meta(conn, uid=uid, origin_pid=pid, target_g=g, target_s=s, target_p=p, probes=4)
    tiers = meta.get('intel_tiers') or {}
    assert tiers.get('fleet') is True
    assert tiers.get('buildings') is False
    ships = meta.get('ships') or {}
    assert ships
    assert sum((int(v) for v in ships.values())) > 0
    conn.close()

def test_spy_report_tier5_reveals_buildings_and_energy(fleet_db):
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'veil_probe': 6}, conn=conn)
    cur.execute('\n        UPDATE planet_buildings\n        SET metal_mine = 5, solar_plant = 3, orbital_shipyard = 2\n        WHERE planet_id = ?;\n        ', (int(foreign_pid),))
    cur.execute('UPDATE planets SET energy_total = 120, energy_used = 80 WHERE id = ?;', (int(foreign_pid),))
    conn.commit()
    snapshot = _target_planet_snapshot(int(foreign_pid), conn=conn)
    _, meta = _build_spy_report_body(snapshot, 5)
    tiers = meta.get('intel_tiers') or {}
    assert tiers.get('buildings') is True
    assert tiers.get('activity') is False
    assert meta.get('energy', {}).get('balance') == 40
    buildings = meta.get('buildings') or {}
    assert buildings.get('metal_mine') == 5
    assert len(buildings) == 1
    conn.close()

def test_attack_resolves_combat_and_saves_losses(fleet_db):
    from game.models import add_planet_defense, get_planet_defense
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    attack_sent = 12
    _seed_ships(pid, uid, {'ironclad_frigate': attack_sent}, conn=conn)
    add_planet_defense(foreign_pid, {'sentinel_turret': 8}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships={'ironclad_frigate': attack_sent}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    msgs = list_messages(uid, category='combat')
    messages = msgs['data']['messages']
    assert len(messages) >= 1
    detail = get_message(uid, messages[0]['id'], mark_read=False)
    meta = detail['data']['message'].get('metadata') or {}
    assert meta.get('report_version') == 2
    assert meta.get('result') in ('attacker', 'defender', 'draw')
    assert meta.get('result') != 'undecided'
    assert int(meta.get('rounds_fought') or 0) >= 1
    assert 'attacking_ships' in meta
    assert 'defending_defense' in meta
    assert 'return_ships' in meta
    assert sum((meta.get('defender_losses') or {}).values()) > 0
    defender_msgs = list_messages(foreign_uid, category='combat')
    assert len(defender_msgs['data']['messages']) >= 1
    cur.execute('SELECT status, ships_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    row = cur.fetchone()
    assert row['status'] == 'returning'
    returning = json.loads(row['ships_json'])
    assert sum(returning.values()) <= attack_sent
    assert sum(returning.values()) > 0
    def_def = get_planet_defense(foreign_pid, conn=conn)
    assert sum(def_def.values()) < 8
    conn.close()

def test_attack_loot_loaded_on_return_and_credited_at_home(fleet_db):
    from game.fleet_calc import calculate_total_cargo, loaded_resource_total
    from game.messages import get_message, list_messages
    from game.models import add_planet_defense
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _fund_planet(cur, foreign_pid, metal=80000, crystal=40000, fuel_cells=20000)
    attack_ships = {'ironclad_frigate': 12, 'mule_courier': 1}
    _seed_ships(pid, uid, attack_ships, conn=conn)
    add_planet_defense(foreign_pid, {'sentinel_turret': 8}, conn=conn)
    conn.commit()
    cargo_cap = calculate_total_cargo(attack_ships)
    assert cargo_cap > 0
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships=attack_ships, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (foreign_pid,))
    before = dict(cur.fetchone())
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    row = cur.fetchone()
    assert row['status'] == 'returning'
    loaded = json.loads(row['resources_json'])
    loot_total = loaded_resource_total(loaded)
    assert loot_total > 0
    assert loot_total <= cargo_cap
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (foreign_pid,))
    after = dict(cur.fetchone())
    assert float(after['metal']) < float(before['metal'])
    detail = get_message(uid, list_messages(uid, category='combat')['data']['messages'][0]['id'], mark_read=False)
    assert sum((detail['data']['message'].get('metadata') or {}).get('loot', {}).values()) == loot_total
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (pid,))
    home_before = dict(cur.fetchone())
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (pid,))
    home_after = dict(cur.fetchone())
    assert float(home_after['metal']) >= float(home_before['metal']) + float(loaded.get('metal') or 0)
    conn.close()

def test_attack_spawns_debris_at_target_coords(fleet_db):
    from game.models import add_planet_defense
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'ironclad_frigate': 12}, conn=conn)
    add_planet_defense(foreign_pid, {'sentinel_turret': 8}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships={'ironclad_frigate': 12}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM debris_fields WHERE galaxy = ? AND system = ? AND position = ?;', (g, s, p))
    row = cur.fetchone()
    assert row is not None
    assert float(row['metal']) > 0 or float(row['crystal']) > 0
    conn.close()

def test_attack_loot_with_conn_skips_nested_resources_queue_finish(fleet_db, monkeypatch):
    """Regression GC-511: loot read must not call finish_due_work(source=resources) inside fleet tick."""
    from game.models import add_planet_defense
    from game import resources as resources_mod
    resource_finish_calls: list[str] = []
    real_finish = resources_mod.finish_due_work_once

    def track_finish(*args, **kwargs):
        resource_finish_calls.append(str(kwargs.get('source') or args[4] if len(args) > 4 else ''))
        return real_finish(*args, **kwargs)
    monkeypatch.setattr(resources_mod, 'finish_due_work_once', track_finish)
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _fund_planet(cur, foreign_pid, metal=50000, crystal=20000, fuel_cells=5000)
    attack_ships = {'ironclad_frigate': 12, 'mule_courier': 1}
    _seed_ships(pid, uid, attack_ships, conn=conn)
    add_planet_defense(foreign_pid, {'sentinel_turret': 8}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships=attack_ships, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert 'resources' not in resource_finish_calls
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'returning'
    conn.close()

def test_attack_arrival_exception_marks_failed_not_stuck_outbound(fleet_db, monkeypatch):
    from game.models import add_planet_defense

    def boom(**_kwargs):
        raise RuntimeError('loot failed for test')
    monkeypatch.setattr('game.combat.apply_combat_loot', boom)
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _fund_planet(cur, foreign_pid, metal=40000, crystal=10000)
    _seed_ships(pid, uid, {'ironclad_frigate': 12}, conn=conn)
    add_planet_defense(foreign_pid, {'sentinel_turret': 8}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships={'ironclad_frigate': 12}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'failed'
    tick2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert int(tick2.get('processed_arrivals') or 0) == 0
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'failed'
    conn.close()

def test_expedition_preview_slot_requires_expedition_mission(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 2}, conn=conn)
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    origin = dict(cur.fetchone())
    conn.commit()
    blocked = build_fleet_send_preview(player_id=uid, origin_planet=origin, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='transport', ships={'solar_skiff': 1}, resources={}, speed_percent=100, conn=conn)
    assert blocked['can_send'] is False
    assert blocked['block_reason'] == 'mission_blocked_expedition_slot'
    allowed = build_fleet_send_preview(player_id=uid, origin_planet=origin, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='expedition', ships={'solar_skiff': 1}, resources={}, speed_percent=100, conn=conn)
    assert allowed['can_send'] is True
    assert allowed['target']['target_type'] == 'expedition_slot'
    daily = allowed.get('expedition_daily') or {}
    assert daily.get('daily_efficiency_pct') == 100
    assert int(daily.get('reset_at') or 0) > 0
    assert int(allowed['cargo_total']) == calculate_expedition_loot_cap({'solar_skiff': 1})
    assert int(allowed['cargo_total']) != calculate_total_cargo({'solar_skiff': 1, 'falcon_interceptor': 5})
    conn.close()

def test_expedition_preview_uses_loot_cap_not_transport_cargo(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 1, 'falcon_interceptor': 5}, conn=conn)
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    origin = dict(cur.fetchone())
    conn.commit()
    ships = {'solar_skiff': 1, 'falcon_interceptor': 5}
    preview = build_fleet_send_preview(player_id=uid, origin_planet=origin, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='expedition', ships=ships, resources={}, speed_percent=100, conn=conn)
    assert int(preview['cargo_total']) == calculate_expedition_loot_cap(ships)
    assert int(preview['cargo_total']) == calculate_expedition_loot_cap({'solar_skiff': 1})
    rating = preview.get('expedition_rating') or {}
    assert rating.get('escort_combat_value') == 5 * 4000
    assert rating.get('expedition_hull_value') == 7000
    assert float(rating.get('escort_ratio') or 0) > 0.5
    conn.close()

def test_expedition_event_engine_report(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 2, 'mule_courier': 1}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=EXPEDITION_POSITION, mission_type='expedition', ships={'solar_skiff': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _complete_expedition_to_returning(conn, fleet_id, player_id=uid)
    msgs = list_messages(uid, category='expedition')
    assert len(msgs['data']['messages']) >= 1
    msg_id = msgs['data']['messages'][0]['id']
    detail = get_message(uid, msg_id, mark_read=False)
    assert detail['ok']
    meta = detail['data']['message'].get('metadata') or {}
    assert meta.get('report_version') == 2
    assert meta.get('event_key') in expedition_event_keys()
    assert 'rewards' in meta
    assert meta.get('fleet_ships', {}).get('solar_skiff') == 1
    cur.execute('SELECT resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    stored = json.loads(cur.fetchone()['resources_json'] or '{}')
    for key in ('metal', 'crystal', 'fuel_cells'):
        assert int(meta['rewards'].get(key) or 0) == int(stored.get(key) or 0)
    assert int(meta.get('cargo_jackpot_mult') or 1) >= 1
    assert 'cargo_total' in meta
    conn.close()

def test_expedition_loot_cap_uses_expedition_and_hauler_cargo_only():
    cap = calculate_expedition_loot_cap({'solar_skiff': 1, 'falcon_interceptor': 5})
    assert cap == 2000
    assert calculate_expedition_loot_cap({'solar_skiff': 2}) == 4000
    assert calculate_expedition_loot_cap({'solar_skiff': 1, 'atlas_hauler': 1}) == 2000 + 25000

def test_expedition_outcome_deterministic_and_cargo_cap():
    first = resolve_expedition_outcome(42, cargo_total=500, expedition_ship_count=1, flight_seconds=120)
    second = resolve_expedition_outcome(42, cargo_total=500, expedition_ship_count=1, flight_seconds=120)
    assert first == second
    assert first['event_key'] in expedition_event_keys()
    reward_total = sum((int(first['rewards'].get(k) or 0) for k in ('metal', 'crystal', 'fuel_cells')))
    assert reward_total <= 500

def test_expedition_outcome_more_hulls_shift_from_empty():
    empty_events = {'void_scan', 'sensor_glitch'}
    empty_hits = 0
    reward_hits = 0
    for movement_id in range(1, 401):
        low = resolve_expedition_outcome(movement_id, cargo_total=50000, expedition_ship_count=0, flight_seconds=60)
        high = resolve_expedition_outcome(movement_id, cargo_total=50000, expedition_ship_count=5, flight_seconds=60)
        if low['event_key'] in empty_events:
            empty_hits += 1
        if high['reward_total'] > 0:
            reward_hits += 1
    assert empty_hits >= 40
    assert reward_hits >= 200

def test_tick_idempotent(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1000}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    now = time.time()
    cur.execute("UPDATE fleet_movements SET arrival_at = ?, status = 'returning', return_at = ? WHERE id = ?;", (now - 200, now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (pid,))
    metal_once = float(cur.fetchone()['metal'])
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (pid,))
    metal_twice = float(cur.fetchone()['metal'])
    assert metal_once == metal_twice
    conn.close()

def test_mass_expedition_creates_batch(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(pid, uid, {'solar_skiff': 10}, conn=conn)
    conn.commit()
    ok, _, preset = create_preset(uid, name='Expo', preset_type='expedition', ships_json={'solar_skiff': 1})
    assert ok
    ok2, reason, result = mass_expedition(player_id=uid, origin_planet_id=pid, preset_id=preset['id'], waves=2, conn=conn)
    assert ok2, reason
    assert result['batch']['batch_type'] == 'mass_expedition'
    assert len(result['started']) >= 1
    conn.close()

def test_mass_expedition_staggers_departures_one_second(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(pid, uid, {'solar_skiff': 10}, conn=conn)
    conn.commit()
    ok, _, preset = create_preset(uid, name='Expo', preset_type='expedition', ships_json={'solar_skiff': 1})
    assert ok
    ok2, reason, result = mass_expedition(player_id=uid, origin_planet_id=pid, preset_id=preset['id'], waves=3, conn=conn)
    assert ok2, reason
    assert len(result['started']) == 3
    batch_id = int(result['batch']['id'])
    cur.execute('\n        SELECT departure_at, arrival_at\n        FROM fleet_movements\n        WHERE parent_batch_id = ?\n        ORDER BY departure_at ASC, id ASC;\n        ', (batch_id,))
    rows = [dict(r) for r in cur.fetchall()]
    assert len(rows) == 3
    for i in range(1, len(rows)):
        assert rows[i]['departure_at'] - rows[i - 1]['departure_at'] == 1
        assert rows[i]['arrival_at'] - rows[i - 1]['arrival_at'] == 1
    conn.close()

def test_mass_expedition_respects_slots(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000, fuel_cells=500000)
    cur.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, 'navigation_tech', 8)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (uid,),
    )
    _seed_ships(pid, uid, {'solar_skiff': 20}, conn=conn)
    conn.commit()
    ok, _, preset = create_preset(uid, name='Expo', preset_type='expedition', ships_json={'solar_skiff': 1})
    assert ok
    usable = mass_expedition_available_slots(uid, conn=conn)
    ok2, _, result = mass_expedition(player_id=uid, origin_planet_id=pid, preset_id=preset['id'], waves=10, conn=conn)
    assert ok2
    assert len(result['started']) == usable
    assert len(result['skipped']) >= 10 - usable
    conn.close()

def test_no_max_ship_limit(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=9999999, crystal=9999999, fuel_cells=9999999)
    _seed_ships(pid, uid, {'falcon_interceptor': 50000}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='attack', ships={'falcon_interceptor': 10000}, conn=conn)
    assert ok, reason
    assert result['fleet']['ships']['falcon_interceptor'] == 10000
    conn.close()

def test_collect_validates_ownership(fleet_db):
    uid1 = _player()
    uid2 = _player()
    conn = db()
    p1 = int(get_planets_by_player(uid1, conn=conn)[0]['id'])
    p2 = int(get_planets_by_player(uid2, conn=conn)[0]['id'])
    conn.close()
    ok, reason, payload = collect_resources(player_id=uid1, target_planet_id=p1, source_planet_ids=[p2], ships={'mule_courier': 1}, resources_mode='all')
    assert not ok
    assert reason == 'planet_not_owned'
    assert payload is None

def test_distribute_route_three_targets_three_movements(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    targets = _extra_colonies(uid, conn, [5, 6, 7])
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=200000, crystal=50000, fuel_cells=50000)
    _seed_ships(hub, uid, {'mule_courier': 9}, conn=conn)
    conn.commit()
    ok, reason, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=targets, ships={'mule_courier': 9}, resources_mode='equal', resources={'metal': 9000, 'crystal': 300, 'fuel_cells': 0}, conn=conn)
    assert ok, reason
    assert len(payload['started']) == 3
    assert len(payload['route']) == 3
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS c FROM fleet_movements WHERE parent_batch_id = ?;', (int(payload['batch']['id']),))
    assert int(cur.fetchone()['c']) == 3
    conn.close()

def test_distribute_route_equal_split_per_target(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    targets = _extra_colonies(uid, conn, [5, 6])
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=100000, crystal=10000, fuel_cells=10000)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=targets, ships={'mule_courier': 4}, resources_mode='equal', resources={'metal': 10000, 'crystal': 100, 'fuel_cells': 0}, conn=conn)
    assert ok
    metals = [leg['resources']['metal'] for leg in payload['route']]
    assert metals == [5000, 5000]
    conn.close()

def test_distribute_route_debits_origin_on_start(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=10000, fuel_cells=10000)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before = float(cur.fetchone()['metal'])
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 2}, resources_mode='equal', resources={'metal': 8000, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok
    delivered = payload['delivered_total']['metal']
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_after = float(cur.fetchone()['metal'])
    assert hub_before - hub_after == pytest.approx(delivered, rel=0, abs=1)
    assert delivered == 8000
    conn.close()

def test_distribute_route_delivers_full_amount_despite_full_storage(fleet_db):
    from game.models import get_planet_buildings
    from game.resources import get_storage_capacity
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=100000, crystal=10000, fuel_cells=50000)
    buildings = get_planet_buildings(target, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    caps = get_storage_capacity(buildings, research=research)
    cur.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (max(0, int(caps['metal']) - 400), max(0, int(caps['crystal']) - 50), target))
    _seed_ships(hub, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 2}, resources_mode='equal', resources={'metal': 8000, 'crystal': 500, 'fuel_cells': 0}, conn=conn)
    assert ok
    assert payload['delivered_total']['metal'] == 8000
    assert payload['delivered_total']['crystal'] == 500
    conn.close()

def test_distribute_route_fuel_cells_uncapped_at_target(fleet_db):
    from game.models import get_planet_buildings
    from game.resources import get_storage_capacity
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=50000, fuel_cells=50000)
    buildings = get_planet_buildings(target, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    caps = get_storage_capacity(buildings, research=research)
    cur.execute('UPDATE planets SET fuel_cells = ? WHERE id = ?;', (max(0, int(caps.get('fuel_cells', 0) or 0)), target))
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (target,))
    fuel_before = int(cur.fetchone()['fuel_cells'])
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 0, 'crystal': 0, 'fuel_cells': 1500}, conn=conn)
    assert ok
    assert payload['delivered_total']['fuel_cells'] == 1500
    fleet_id = int(payload['started'][0]['fleet_id'])
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (target,))
    assert int(cur.fetchone()['fuel_cells']) == fuel_before + 1500
    conn.close()

def test_distribute_route_custom_target_resources(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    t1, t2 = _extra_colonies(uid, conn, [5, 6])
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=100000, crystal=10000, fuel_cells=10000)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[t1, t2], ships={'mule_courier': 4}, resources_mode='custom', target_resources={str(t1): {'metal': 3000, 'crystal': 0, 'fuel_cells': 0}, str(t2): {'metal': 7000, 'crystal': 100, 'fuel_cells': 50}}, conn=conn)
    assert ok
    by_target = {leg['planet_id']: leg['resources'] for leg in payload['route']}
    assert by_target[t1]['metal'] == 3000
    assert by_target[t2]['metal'] == 7000
    assert by_target[t2]['fuel_cells'] == 50
    conn.close()

def test_distribute_route_return_empty_no_resource_dup(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=10000, fuel_cells=10000)
    _fund_planet(cur, target, metal=100, crystal=50)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 4000, 'crystal': 200, 'fuel_cells': 0}, conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    before = dict(cur.fetchone())
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    after_arrival = dict(cur.fetchone())
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = dict(cur.fetchone())
    assert mv['status'] == 'returning'
    assert json.loads(mv['resources_json']) in ({}, {'metal': 0, 'crystal': 0, 'fuel_cells': 0})
    now = time.time()
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    after_return = dict(cur.fetchone())
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_metal = int(cur.fetchone()['metal'])
    assert int(after_arrival['metal']) == int(before['metal']) + 4000
    assert after_return == after_arrival
    assert hub_metal < 50000
    conn.close()

def test_distribute_route_excludes_origin(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[hub, target], ships={'mule_courier': 2}, resources_mode='equal', resources={'metal': 2000, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok
    assert len(payload['started']) == 1
    assert payload['started'][0]['target_planet_id'] == target
    conn.close()

def test_distribute_validates_ownership(fleet_db):
    uid1 = _player()
    uid2 = _player()
    conn = db()
    p1 = int(get_planets_by_player(uid1, conn=conn)[0]['id'])
    p2 = int(get_planets_by_player(uid2, conn=conn)[0]['id'])
    conn.close()
    ok, reason, payload = distribute_resources(player_id=uid1, origin_planet_id=p1, target_planet_ids=[p2], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 100})
    assert not ok
    assert reason == 'planet_not_owned'

def _extra_colonies(uid: int, conn, positions: list[int]) -> list[int]:
    _unlock_expansion_for_colonize(conn, uid)
    ids: list[int] = []
    for pos in positions:
        ok, reason, extra = colonize_planet(uid, name=f'Colony {pos}', galaxy=1, system=300, position=int(pos), conn=conn, allow_legacy_coordinates=True, source='test')
        assert ok, reason
        ids.append(int(extra['planet_id']))
    return ids

def test_collect_route_three_colonies_three_movements(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    sources = _extra_colonies(uid, conn, [5, 6, 7])
    for cid in sources:
        _fund_planet(conn.cursor(), cid, metal=10000, crystal=1000)
    _seed_ships(hub, uid, {'mule_courier': 12}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 12}, resources_mode='all', conn=conn)
    assert ok, reason
    assert len(payload['started']) == 3
    assert len(payload['route']) == 3
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS c FROM fleet_movements WHERE parent_batch_id = ?;', (int(payload['batch']['id']),))
    assert int(cur.fetchone()['c']) == 3
    conn.close()

def test_collect_route_ship_split_remainder(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    sources = _extra_colonies(uid, conn, [5, 6, 7])
    _seed_ships(hub, uid, {'mule_courier': 30}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 5}, resources_mode='all', conn=conn)
    assert ok, reason
    counts = [leg['ships']['mule_courier'] for leg in payload['route']]
    assert counts == [1, 1, 3]
    assert sum(counts) == 5
    conn.close()

def test_collect_route_excludes_origin_as_target(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    assert normalize_collect_source_planet_ids(hub, [hub, source]) == [source]
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[hub, source], ships={'mule_courier': 2}, resources_mode='all', conn=conn)
    assert ok, reason
    assert len(payload['started']) == 1
    assert payload['started'][0]['source_planet_id'] == source
    conn.close()

def test_collect_route_origin_only_sources_rejected(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[hub], ships={'mule_courier': 1}, resources_mode='all', conn=conn)
    assert not ok
    assert reason == 'no_planets'
    assert payload is None
    conn.close()

def test_collect_route_deterministic_galaxy_sort(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    c5, c7, c8 = _extra_colonies(uid, conn, [5, 7, 8])
    _seed_ships(hub, uid, {'mule_courier': 6}, conn=conn)
    conn.commit()
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[c8, c5, c7], ships={'mule_courier': 6}, resources_mode='all', conn=conn)
    assert ok
    route_positions = [leg['position'] for leg in payload['route']]
    assert route_positions == [5, 7, 8]
    assert [leg['planet_id'] for leg in payload['route']] == [c5, c7, c8]
    conn.close()

def test_collect_route_return_credits_origin(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=5000, crystal=5000, fuel_cells=50000)
    _fund_planet(cur, source, metal=9000, crystal=0, fuel_cells=0)
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before = int(cur.fetchone()['metal'])
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 1}, resources_mode='all', conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    now = time.time()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_after = int(cur.fetchone()['metal'])
    assert hub_after > hub_before
    conn.close()

def test_collect_route_not_enough_ships_for_all_targets(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    sources = _extra_colonies(uid, conn, [5, 6, 7])
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 2}, resources_mode='all', conn=conn)
    assert not ok
    assert reason == 'not_enough_ships'
    assert payload is None
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM fleet_movements WHERE player_id = ? AND mission_type = 'collect';", (uid,))
    assert int(cur.fetchone()['c']) == 0
    conn.close()

def test_build_collect_route_pure_validation(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    cur.execute('SELECT * FROM planets WHERE id IN (?, ?);', (hub, source))
    rows = {int(r['id']): dict(r) for r in cur.fetchall()}
    conn.close()
    ok, reason, legs = build_collect_route(origin_planet_id=hub, source_planet_ids=[source], planet_rows_by_id=rows, ships={'mule_courier': 2}, free_fleet_slots=5, player_id=uid)
    assert ok, reason
    assert len(legs) == 1
    assert legs[0]['ships']['mule_courier'] == 2

def test_logistics_collect_starts_batch(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    _fund_planet(conn.cursor(), source, metal=15000, crystal=2000)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 2}, resources_mode='all', ships_selection_mode='manual', conn=conn)
    assert ok, reason
    assert payload['batch']['batch_type'] == 'collect_resources'
    assert len(payload['started']) == 1
    fleet_id = payload['started'][0]['fleet_id']
    cur = conn.cursor()
    cur.execute('SELECT mission_type, origin_planet_id, target_planet_id, parent_batch_id FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = dict(cur.fetchone())
    assert mv['mission_type'] == 'collect'
    assert int(mv['origin_planet_id']) == hub
    assert int(mv['target_planet_id']) == source
    assert int(mv['parent_batch_id']) == payload['batch']['id']
    conn.close()

def test_logistics_collect_rejects_non_cargo_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    _seed_ships(hub, uid, {'falcon_interceptor': 5}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'falcon_interceptor': 1}, resources_mode='all', conn=conn)
    assert not ok
    assert reason == 'no_cargo_ships'
    assert payload is None
    conn.close()

def test_logistics_distribute_starts_transport_movements(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=20000, fuel_cells=20000)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    ok, reason, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 2}, resources_mode='equal', resources={'metal': 4000, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok, reason
    assert payload['batch']['batch_type'] == 'distribute_resources'
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur = conn.cursor()
    cur.execute('SELECT mission_type, origin_planet_id, target_planet_id, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = dict(cur.fetchone())
    assert mv['mission_type'] == 'transport'
    assert int(mv['origin_planet_id']) == hub
    assert int(mv['target_planet_id']) == target
    assert int(json.loads(mv['resources_json'])['metal']) == 4000
    conn.close()

def test_logistics_distribute_arrival_message_idempotent(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=10000, fuel_cells=10000)
    _fund_planet(cur, target, metal=100, crystal=50)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 3000, 'crystal': 500, 'fuel_cells': 0}, conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    before = dict(cur.fetchone())
    _force_outbound_arrival(conn, fleet_id)
    tick1 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    msgs_once = _count_fleet_messages(uid, fleet_id)
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    after_once = dict(cur.fetchone())
    tick2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    msgs_twice = _count_fleet_messages(uid, fleet_id)
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    after_twice = dict(cur.fetchone())
    assert int(tick1.get('processed_arrivals') or 0) == 1
    assert int(tick2.get('processed_arrivals') or 0) == 0
    assert msgs_once == msgs_twice == 1
    assert after_once == after_twice
    assert int(after_twice['metal']) == int(before['metal']) + 3000
    assert int(after_twice['crystal']) == int(before['crystal']) + 500
    meta = _fleet_report_metadata(uid, fleet_id, report_phase='logistics_distribute_arrival')
    assert meta.get('mission_type') == 'distribute'
    assert meta.get('resources', {}).get('metal') == 3000
    assert meta.get('origin_planet_id') == hub
    assert meta.get('target_planet_id') == target
    assert meta.get('timestamp')
    conn.close()

def test_logistics_collect_arrival_report_idempotent(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=5000, fuel_cells=50000)
    _fund_planet(cur, source, metal=12000, crystal=3000, fuel_cells=500)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 1}, resources_mode='all', conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    once = _count_fleet_messages(uid, fleet_id, report_phase='logistics_collect_arrival')
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    twice = _count_fleet_messages(uid, fleet_id, report_phase='logistics_collect_arrival')
    assert once == twice == 1
    conn.close()

def test_logistics_collect_return_report(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(source, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=5000)
    _fund_planet(cur, source, metal=8000, crystal=0)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=hub, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_collect_arrival') == 1
    now = time.time()
    cur.execute("UPDATE fleet_movements SET status = 'returning', return_at = ? WHERE id = ?;", (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_collect_return') == 1
    return_meta = _fleet_report_metadata(uid, fleet_id, report_phase='logistics_collect_return')
    assert return_meta.get('mission_type') == 'collect'
    assert return_meta.get('origin_planet_id') == hub
    assert return_meta.get('resources', {}).get('metal', 0) > 0
    assert _count_fleet_messages(uid, fleet_id) == 2
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert _count_fleet_messages(uid, fleet_id) == 2
    conn.close()

def test_logistics_distribute_return_no_delivery_report(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=10000)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 2000, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    arrival_meta = _fleet_report_metadata(uid, fleet_id, report_phase='logistics_distribute_arrival')
    assert arrival_meta.get('resources', {}).get('metal') == 2000
    now = time.time()
    cur.execute("UPDATE fleet_movements SET status = 'returning', return_at = ? WHERE id = ?;", (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    return_meta = _fleet_report_metadata(uid, fleet_id, report_phase='logistics_distribute_return')
    assert return_meta.get('mission_type') == 'distribute'
    assert int(return_meta.get('resources', {}).get('metal') or 0) == 0
    assert return_meta.get('ships')
    assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_distribute_arrival') == 1
    conn.close()

def test_logistics_collect_arrival_double_tick_idempotent(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=5000, fuel_cells=50000)
    _fund_planet(cur, source, metal=12000, crystal=3000, fuel_cells=500)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 1}, resources_mode='all', conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (source,))
    before = dict(cur.fetchone())
    _force_outbound_arrival(conn, fleet_id)
    tick1 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (source,))
    after_once = dict(cur.fetchone())
    tick2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (source,))
    after_twice = dict(cur.fetchone())
    assert int(tick1.get('processed_arrivals') or 0) == 1
    assert int(tick2.get('processed_arrivals') or 0) == 0
    assert after_once == after_twice
    assert int(after_twice['metal']) < int(before['metal'])
    conn.close()


def test_logistics_collect_dual_arrival_same_source_no_dup(fleet_db):
    """Two collect fleets arriving together must not load more than the source holds."""
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(source, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=5000, fuel_cells=50000)
    _fund_planet(cur, source, metal=12000, crystal=3000, fuel_cells=500)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()

    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (source,))
    source_before = dict(cur.fetchone())
    source_total_before = (
        int(source_before['metal']) + int(source_before['crystal']) + int(source_before['fuel_cells'])
    )

    ok1, _, r1 = send_fleet(
        player_id=uid,
        origin_planet_id=hub,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type='collect',
        ships={'mule_courier': 2},
        conn=conn,
    )
    ok2, _, r2 = send_fleet(
        player_id=uid,
        origin_planet_id=hub,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type='collect',
        ships={'mule_courier': 2},
        conn=conn,
    )
    assert ok1 and ok2
    fleet_ids = [int(r1['fleet']['id']), int(r2['fleet']['id'])]
    for fid in fleet_ids:
        _force_outbound_arrival(conn, fid)
    conn.commit()

    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (source,))
    source_after = dict(cur.fetchone())
    source_total_after = (
        int(source_after['metal']) + int(source_after['crystal']) + int(source_after['fuel_cells'])
    )
    removed = source_total_before - source_total_after

    cargo_total = 0
    for fid in fleet_ids:
        cur.execute('SELECT resources_json, status FROM fleet_movements WHERE id = ?;', (fid,))
        row = cur.fetchone()
        assert row['status'] == 'returning'
        res = json.loads(row['resources_json'])
        cargo_total += int(res.get('metal') or 0) + int(res.get('crystal') or 0) + int(res.get('fuel_cells') or 0)

    assert removed > 0
    assert cargo_total == removed
    assert source_total_after >= 0

    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (hub,))
    hub_before_return = dict(cur.fetchone())
    now = time.time()
    for fid in fleet_ids:
        cur.execute(
            "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
            (now - 1, fid),
        )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (hub,))
    hub_after_return = dict(cur.fetchone())
    hub_gain = (
        (int(hub_after_return['metal']) - int(hub_before_return['metal']))
        + (int(hub_after_return['crystal']) - int(hub_before_return['crystal']))
        + (int(hub_after_return['fuel_cells']) - int(hub_before_return['fuel_cells']))
    )
    assert hub_gain == removed
    conn.close()


def test_logistics_distribute_hub_target_conservation(fleet_db):
    """Distribute: hub debit at send equals target credit at arrival; cargo json cleared."""
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=10000, fuel_cells=50000)
    _fund_planet(cur, target, metal=100, crystal=50)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()

    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (hub,))
    hub_before = dict(cur.fetchone())
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (target,))
    target_before = dict(cur.fetchone())
    hub_total_before = sum(int(hub_before[k]) for k in ('metal', 'crystal', 'fuel_cells'))
    target_total_before = sum(int(target_before[k]) for k in ('metal', 'crystal', 'fuel_cells'))

    ok, _, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=[target],
        ships={'mule_courier': 1},
        resources_mode='equal',
        resources={'metal': 2500, 'crystal': 400, 'fuel_cells': 0},
        conn=conn,
    )
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (hub,))
    hub_after_send = dict(cur.fetchone())
    hub_removed_at_send = hub_total_before - sum(
        int(hub_after_send[k]) for k in ('metal', 'crystal', 'fuel_cells')
    )
    assert hub_removed_at_send > 0

    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute('SELECT resources_json, status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = cur.fetchone()
    assert mv['status'] == 'returning'
    from game.fleet_calc import loaded_resource_total
    assert loaded_resource_total(json.loads(mv['resources_json'])) == 0

    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (target,))
    target_after = dict(cur.fetchone())
    target_gained = sum(int(target_after[k]) for k in ('metal', 'crystal', 'fuel_cells')) - target_total_before
    delivered = payload['started'][0]['resources']
    delivered_total = sum(int(delivered.get(k) or 0) for k in ('metal', 'crystal', 'fuel_cells'))
    assert target_gained == delivered_total
    assert delivered_total > 0

    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (target,))
    target_twice = dict(cur.fetchone())
    assert target_twice == target_after
    conn.close()


def test_logistics_distribute_rejects_over_cargo(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(hub, uid, {'mule_courier': 1}, conn=conn)
    conn.commit()
    ok, reason, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 50000, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert not ok
    assert reason == 'not_enough_cargo'
    assert payload is None
    conn.close()

def test_logistics_split_helpers_even_remainder():
    parts = split_ships_across_targets({'mule_courier': 5}, 2)
    assert parts[0] == {'mule_courier': 2}
    assert parts[1] == {'mule_courier': 3}
    shares = split_resources_evenly({'metal': 10, 'crystal': 1, 'fuel_cells': 0}, 3)
    assert shares[0]['metal'] == 3
    assert shares[2]['metal'] == 4
    assert sum((s['crystal'] for s in shares)) == 1

def test_fleet_ships_are_cargo_only_rejects_combat():
    ok, reason = fleet_ships_are_cargo_only({'falcon_interceptor': 1})
    assert not ok
    assert reason == 'no_cargo_ships'
    ok2, _ = fleet_ships_are_cargo_only({'mule_courier': 1})
    assert ok2

def test_normalize_ships_filters_unknown():
    ships = normalize_ships({'mule_courier': 5, 'bogus': 3})
    assert ships == {'mule_courier': 5}

def test_fleet_fuel_resource_is_fuel_cells():
    assert FLEET_FUEL_RESOURCE == 'fuel_cells'

def test_fuel_cells_load_and_fuel_validated_together():
    ok, reason = validate_departure_balances(metal_have=100000, crystal_have=2000, fuel_cells_have=5000, resources={'metal': 0, 'crystal': 800}, fuel_cost=300)
    assert ok, reason
    ok3, reason3 = validate_departure_balances(metal_have=100000, crystal_have=1000, fuel_cells_have=100, resources={'metal': 0, 'crystal': 900}, fuel_cost=200)
    assert not ok3
    assert reason3 == 'not_enough_fuel'

def test_apply_departure_deducts_fuel_cells(fleet_db):
    new_m, new_c, new_f = apply_departure_deduction(5000, 3000, 2000, {'metal': 100, 'crystal': 500}, 200)
    assert new_m == 4900
    assert new_c == 2500
    assert new_f == 1800

def test_preview_send_fuel_parity(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'mule_courier': 5}, conn=conn)
    conn.commit()
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    planet = dict(cur.fetchone())
    ships = {'mule_courier': 2}
    resources = {'metal': 1000, 'crystal': 0}
    preview = preview_fleet_flight(origin_planet=planet, target_galaxy=g, target_system=s, target_position=p, ships=ships, resources=resources, speed_percent=100, player_id=uid, conn=conn)
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships=ships, resources=resources, speed_percent=100, conn=conn)
    assert ok, reason
    assert result['fuel_cost'] == preview['fuel_cost']
    conn.close()

def test_completed_fleets_do_not_count_against_slots(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'falcon_interceptor': 20}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships={'falcon_interceptor': 2}, resources={'metal': 0, 'crystal': 0}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    assert count_active_fleet_slots(uid, conn=conn) == 0
    conn.close()

def test_deploy_idempotent_double_tick(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'falcon_interceptor': 10}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships={'falcon_interceptor': 3}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    ships_once = get_planet_ships(colony2, conn=conn).get('falcon_interceptor', 0)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    ships_twice = get_planet_ships(colony2, conn=conn).get('falcon_interceptor', 0)
    assert ships_once == ships_twice == 3
    conn.close()

def test_seed_dev_ships(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    from game.fleet import seed_planet_ships_stack
    ok, reason, ships = seed_planet_ships_stack(pid, uid, conn=conn)
    assert ok, reason
    assert ships.get('mule_courier', 0) >= 20
    conn.close()

def test_resolve_fleet_target_own_planet(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, p = _planet_coords(pid, conn=conn)
    target = resolve_fleet_target(uid, g, s, p, conn=conn)
    assert target['target_type'] == 'own_planet'
    assert 'transport' in target['allowed_missions']
    assert 'collect' in target['allowed_missions']
    assert 'deploy' in target['allowed_missions']
    assert 'spy' in target['allowed_missions']
    assert mission_allowed_for_target('attack', target)[0] is False
    conn.close()

def test_resolve_fleet_target_foreign_planet(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    target = resolve_fleet_target(uid, g, s, p, conn=conn)
    assert target['target_type'] == 'foreign_planet'
    assert 'spy' in target['allowed_missions']
    assert 'attack' in target['allowed_missions']
    assert mission_allowed_for_target('transport', target)[0] is False
    conn.close()

def test_resolve_fleet_target_ally_planet(fleet_db):
    conn = db()
    uid1, uid2, ally_pid, (g, s, p) = _allied_players_standalone()
    target = resolve_fleet_target(uid1, g, s, p, conn=conn)
    assert target['target_type'] == 'ally_planet'
    assert 'transport' in target['allowed_missions']
    assert 'spy' in target['allowed_missions']
    assert mission_allowed_for_target('deploy', target)[0] is False
    assert mission_allowed_for_target('attack', target)[0] is False
    conn.close()

def test_resolve_fleet_target_empty_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    target = resolve_fleet_target(uid, 1, 499, 12, conn=conn)
    assert target['target_type'] == 'empty_slot'
    assert target['allowed_missions'] == ['colonize']
    assert mission_allowed_for_target('colonize', target)[0] is True
    assert mission_allowed_for_target('transport', target)[0] is False
    conn.close()

def test_colonize_fleet_send_preview_classic_empty_slot_ok(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _unlock_expansion_for_colonize(conn, uid)
    _seed_ships(pid, uid, {'seed_ark': 1}, conn=conn)
    origin = conn.cursor().execute('SELECT * FROM planets WHERE id = ?;', (pid,)).fetchone()
    conn.commit()
    preview = build_fleet_send_preview(player_id=uid, origin_planet=dict(origin), target_galaxy=1, target_system=499, target_position=12, mission_type='colonize', ships={'seed_ark': 1}, resources={}, speed_percent=100, conn=conn)
    assert preview['can_send'] is True
    assert preview['block_reason'] in ('', None)
    conn.close()

def _colonize_preview_to_empty_slot(uid: int, pid: int, origin, conn):
    return build_fleet_send_preview(player_id=uid, origin_planet=dict(origin), target_galaxy=1, target_system=499, target_position=12, mission_type='colonize', ships={'seed_ark': 1}, resources={}, speed_percent=100, conn=conn)

def test_colonize_fleet_preview_classic_empty_slot_blocked_without_evolution_slot(fleet_db):
    """Classic galaxy colonize requires a free Planet Evolution colony slot."""
    uid = _player()
    conn = db()
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _seed_ships(pid, uid, {'seed_ark': 1}, conn=conn)
    origin = conn.cursor().execute('SELECT * FROM planets WHERE id = ?;', (pid,)).fetchone()
    conn.commit()
    preview = _colonize_preview_to_empty_slot(uid, pid, origin, conn)
    assert preview['mission_allowed'] is False
    assert preview['block_reason'] == 'planet_evolution_colony_slot_required'
    assert preview['can_send'] is False
    conn.close()


def test_colonize_fleet_preview_classic_empty_slot_allowed_with_evolution_slot(fleet_db):
    uid = _player()
    conn = db()
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _unlock_expansion_for_colonize(conn, uid)
    _seed_ships(pid, uid, {'seed_ark': 1}, conn=conn)
    origin = conn.cursor().execute('SELECT * FROM planets WHERE id = ?;', (pid,)).fetchone()
    conn.commit()
    preview = _colonize_preview_to_empty_slot(uid, pid, origin, conn)
    assert preview['mission_allowed'] is True
    assert preview['block_reason'] in (None, '')
    assert preview['can_send'] is True
    conn.close()

def test_colonize_fleet_send_to_empty_slot_ok(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    _unlock_expansion_for_colonize(conn, uid)
    _seed_ships(pid, uid, {'seed_ark': 1, 'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=1, target_system=499, target_position=12, mission_type='colonize', ships={'seed_ark': 1}, resources={'colony_name': 'New Outpost'}, conn=conn)
    assert ok, reason
    assert result['fleet']['target_coords'] == '[1:499:12]'
    conn.close()

def test_colonize_requires_ark_on_empty_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _unlock_expansion_for_colonize(conn, uid)
    _seed_ships(pid, uid, {'mule_courier': 5}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=1, target_system=498, target_position=11, mission_type='colonize', ships={'mule_courier': 1}, conn=conn)
    assert not ok
    assert reason == 'colonize_requires_ark'
    conn.close()

def test_colonize_classic_arrival_creates_planet_at_coords(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    _unlock_expansion_for_colonize(conn, uid)
    _seed_ships(pid, uid, {'seed_ark': 1}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=1, target_system=499, target_position=12, mission_type='colonize', ships={'seed_ark': 1}, resources={'colony_name': 'Classic Outpost'}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    before_count = len(get_planets_by_player(uid, conn=conn))
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'completed'
    assert len(get_planets_by_player(uid, conn=conn)) == before_count + 1
    row = conn.execute('SELECT galaxy, system, position, name FROM planets WHERE player_id = ? AND system = 499 AND position = 12;', (uid,)).fetchone()
    assert row is not None
    assert int(row['galaxy']) == 1
    assert row['name']
    conn.close()

def test_colonize_arrival_completes_without_return(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, fuel_cells=50000)
    field = _colonizable_world_field()
    conn.commit()
    ok, reason, result = _send_world_colonize(conn, uid, pid, field, colony_name='Ark Colony')
    assert ok, reason
    fleet_id = result['fleet']['id']
    before_count = len(get_planets_by_player(uid, conn=conn))
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'completed'
    assert len(get_planets_by_player(uid, conn=conn)) == before_count + 1
    conn.close()

def test_resolve_fleet_target_expedition_slot(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    target = resolve_fleet_target(uid, 1, 100, EXPEDITION_POSITION, conn=conn)
    assert target['target_type'] == 'expedition_slot'
    assert target['allowed_missions'] == ['expedition']
    conn.close()

def test_transport_foreign_blocked(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _seed_ships(pid, uid, {'mule_courier': 5}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 100}, conn=conn)
    assert not ok
    assert reason == 'mission_blocked_foreign_planet'
    conn.close()

def test_transport_ally_succeeds(fleet_db):
    conn = db()
    uid1, uid2, ally_pid, (g, s, p) = _allied_players_standalone()
    pid = int(get_planets_by_player(uid1, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid1, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid1, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 500, 'crystal': 100}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid1, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (ally_pid,))
    assert int(cur.fetchone()['metal']) >= 500
    sender_msgs = list_messages(uid1, category='system')
    receiver_msgs = list_messages(uid2, category='system')
    assert len(sender_msgs['data']['messages']) >= 1
    assert len(receiver_msgs['data']['messages']) >= 1
    conn.close()

def test_deploy_foreign_blocked(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _seed_ships(pid, uid, {'falcon_interceptor': 5}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships={'falcon_interceptor': 1}, conn=conn)
    assert not ok
    assert reason == 'mission_blocked_foreign_planet'
    conn.close()

def test_spy_own_planet_allowed(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'veil_probe': 2}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='spy', ships={'veil_probe': 1}, conn=conn)
    assert ok, reason
    conn.close()

def test_colonize_occupied_slot_blocked(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, p = _planet_coords(pid, conn=conn)
    _unlock_expansion_for_colonize(conn, uid)
    _seed_ships(pid, uid, {'seed_ark': 1}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='colonize', ships={'seed_ark': 1}, conn=conn)
    assert not ok
    assert reason == 'coordinate_occupied'
    conn.close()

def test_colonize_coordinate_only_prefill_ok_when_unlocked(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _unlock_expansion_for_colonize(conn, uid)
    _seed_ships(pid, uid, {'seed_ark': 1}, conn=conn)
    origin = conn.cursor().execute('SELECT * FROM planets WHERE id = ?;', (pid,)).fetchone()
    conn.commit()
    preview = build_fleet_send_preview(player_id=uid, origin_planet=dict(origin), target_galaxy=1, target_system=42, target_position=7, mission_type='colonize', ships={'seed_ark': 1}, resources={}, speed_percent=100, conn=conn)
    assert preview['can_send'] is True
    conn.close()

def test_mission_target_matrix_blocks(fleet_db):
    from game.fleet_api import fleet_mission_target_payload, fleet_resolve_target_payload
    _foreign_uid, _foreign_pid, (fg, fs, fp) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, p = _planet_coords(pid, conn=conn)
    resolve_own = fleet_resolve_target_payload(uid, g, s, p, conn=conn)
    assert resolve_own['ok']
    assert 'deploy' in resolve_own['data']['target']['allowed_missions']
    blocked_deploy = fleet_mission_target_payload(uid, 'deploy', fg, fs, fp, conn=conn)
    assert not blocked_deploy['ok']
    assert blocked_deploy['error'] == 'mission_blocked_foreign_planet'
    blocked_expo = fleet_mission_target_payload(uid, 'expedition', g, s, p, conn=conn)
    assert not blocked_expo['ok']
    assert blocked_expo['error'] == 'mission_blocked_not_expedition_slot'
    ok_eval, reason, target = evaluate_fleet_mission_target(uid, 'spy', fg, fs, fp, conn=conn)
    assert ok_eval, reason
    assert target['target_type'] == 'foreign_planet'
    conn.close()

def test_preview_and_send_mission_block_parity(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'falcon_interceptor': 5}, conn=conn)
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    origin = dict(cur.fetchone())
    conn.commit()
    ships = {'falcon_interceptor': 2}
    preview = build_fleet_send_preview(player_id=uid, origin_planet=origin, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships=ships, resources={}, speed_percent=100, conn=conn)
    ok_send, send_reason, _ = validate_fleet_send(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='deploy', ships=ships, resources={}, speed_percent=100, conn=conn)
    assert preview['can_send'] is False
    assert ok_send is False
    assert preview['block_reason'] == send_reason == 'mission_blocked_foreign_planet'
    assert preview['mission_allowed'] is False
    conn.close()

def test_expedition_wrong_position_blocked(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, p = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'solar_skiff': 1}, conn=conn)
    conn.commit()
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='expedition', ships={'solar_skiff': 1}, conn=conn)
    assert not ok
    assert reason == 'mission_blocked_not_expedition_slot'
    conn.close()

def test_api_fleet_send_persists_movement(fleet_db, monkeypatch):
    import importlib
    import app as app_module
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_module)
    app_module.app.config['TESTING'] = True
    app_module.app.config['WTF_CSRF_ENABLED'] = False
    conn = db()
    uname = _policy_safe_username("apif")
    ok, _, user = create_user(uname, 'test-pass-123')
    assert ok
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Admiral', conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'mule_courier': 5}, conn=conn)
    conn.commit()
    conn.close()
    client = app_module.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    resp = client.post('/api/fleet/send', json={'origin_planet_id': pid, 'target_galaxy': g, 'target_system': s, 'target_position': p, 'mission_type': 'transport', 'ships': {'mule_courier': 2}, 'resources': {'metal': 500, 'crystal': 0}, 'speed_percent': 100}, headers={'Content-Type': 'application/json'})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['ok'] is True
    assert body['data']['fleet']['status'] == 'outbound'
    assert body.get('state') and body['state'].get('ok') is True
    verify = db()
    try:
        row = verify.execute('SELECT status FROM fleet_movements WHERE player_id = ? ORDER BY id DESC LIMIT 1;', (uid,)).fetchone()
        assert row is not None
        assert row['status'] == 'outbound'
        assert get_planet_ships(pid, conn=verify).get('mule_courier') == 3
    finally:
        verify.close()

def test_transport_report_uses_german_resource_names(fleet_db):
    from game.fleet import _format_transport_report
    body = _format_transport_report(coords='[1:1:1]', origin_name='Homeworld', target_name='Colony', resources={'metal': 2222, 'crystal': 2222, 'fuel_cells': 100}, incoming=False, locale='de')
    assert 'Transport nach' in body
    assert 'Ferronit' in body
    assert 'Crytite' in body
    assert 'Brennzellen' in body
    assert 'Metal:' not in body
    assert 'Crystal:' not in body

def test_transport_report_uses_english_for_en_locale(fleet_db):
    from game.fleet import _format_transport_report
    body = _format_transport_report(coords='[1:1:1]', origin_name='Homeworld', target_name='Colony', resources={'metal': 100, 'crystal': 0, 'fuel_cells': 0}, incoming=True, locale='en')
    assert 'Incoming transport at' in body
    assert 'Ferronit' in body
    assert 'Transport nach' not in body

def test_transport_can_carry_fuel_cells(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000, fuel_cells = 8000 WHERE id = ?;', (pid,))
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (colony2,))
    before_fc = float(cur.fetchone()['fuel_cells'])
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 0, 'crystal': 0, 'fuel_cells': 500}, conn=conn)
    assert ok, reason
    fleet_id = result['fleet']['id']
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (colony2,))
    after_fc = float(cur.fetchone()['fuel_cells'])
    assert after_fc >= before_fc + 500

def test_galaxy_fleet_links_have_query_params(fleet_db, monkeypatch):
    import importlib
    import app as app_module
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_module)
    uname = _policy_safe_username("galf")
    ok, _, user = create_user(uname, 'test-pass-123')
    assert ok
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = int(user['id'])
    resp = client.get('/galaxy?view=system')
    body = resp.get_data(as_text=True)
    assert 'target_galaxy=' in body
    assert 'mission=transport' in body
    assert 'mission=expedition' in body
    assert f'target_position={EXPEDITION_POSITION}' in body

def test_api_fleet_state_processes_due_return(fleet_db, monkeypatch):
    import importlib
    import app as app_module
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 100}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    now = time.time()
    cur.execute("\n        UPDATE fleet_movements\n        SET arrival_at = ?, status = 'returning', return_at = ?\n        WHERE id = ?;\n        ", (now - 200, now - 1, fleet_id))
    conn.commit()
    conn.close()
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get(f'/api/fleet/state?planet_id={pid}')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    active = data['data']['active_fleets']
    assert active == [] or active.get('count') == 0
    verify = db()
    try:
        row = verify.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()
        assert row['status'] == 'completed'
    finally:
        verify.close()

def test_api_game_state_completes_due_fleet_return(fleet_db, monkeypatch):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='collect', ships={'mule_courier': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    now = time.time()
    cur.execute("\n        UPDATE fleet_movements\n        SET arrival_at = ?, status = 'returning', return_at = ?, resources_json = ?\n        WHERE id = ?;\n        ", (now - 200, now - 1, json.dumps({'metal': 1000, 'crystal': 0, 'fuel_cells': 0}), fleet_id))
    conn.commit()
    conn.close()
    import importlib
    import app as app_module
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/game-state')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    overview_status = (data.get('overview') or {}).get('status')
    if overview_status and isinstance(overview_status.get('activities'), list):
        fleet_rows = [a for a in overview_status['activities'] if str(a.get('key', '')).startswith('fleet')]
        assert fleet_rows == []
    verify = db()
    try:
        row = verify.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()
        assert row['status'] == 'completed'
    finally:
        verify.close()

def test_calculate_distance_near_vs_far_same_galaxy():
    """[1:1:1]→[1:1:2] must be much shorter than [1:1:1]→[1:450:12]."""
    near = calculate_distance((1, 1, 1), (1, 1, 2))
    far = calculate_distance((1, 1, 1), (1, 450, 12))
    assert near > 0
    assert far > near
    assert far >= 1000

def test_preview_flight_seconds_reflects_coordinate_distance(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    origin = dict(cur.fetchone())
    og, os, op = (int(origin['galaxy']), int(origin['system']), int(origin['position']))
    ships = {'mule_courier': 1}
    near = preview_fleet_flight(origin_planet=origin, target_galaxy=og, target_system=os, target_position=op + 1 if op < 15 else op - 1, ships=ships, resources={}, speed_percent=100, player_id=uid, conn=conn)
    far = preview_fleet_flight(origin_planet=origin, target_galaxy=og, target_system=os + 200 if os < 400 else os - 200, target_position=12, ships=ships, resources={}, speed_percent=100, player_id=uid, conn=conn)
    assert int(far['distance']) > int(near['distance'])
    assert int(far['flight_seconds']) > int(near['flight_seconds'])
    conn.close()

def test_api_fleet_state_five_calls_outbound_arrival_idempotent(fleet_db, monkeypatch):
    import importlib
    import app as app_module
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=5000, fuel_cells=50000)
    _fund_planet(cur, source, metal=15000, crystal=2000, fuel_cells=500)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 1}, resources_mode='all', conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    _force_outbound_arrival(conn, fleet_id)
    conn.close()
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    for _ in range(5):
        r = client.get(f'/api/fleet/state?planet_id={hub}')
        assert r.status_code == 200
        assert r.get_json()['ok'] is True
    verify = db()
    try:
        cur = verify.cursor()
        cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
        assert cur.fetchone()['status'] == 'returning'
        cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (source,))
        source_after = dict(cur.fetchone())
        assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_collect_arrival') == 1
        msgs = _count_fleet_messages(uid, fleet_id)
        assert msgs == 1
    finally:
        verify.close()

def test_logistics_multi_collect_conserves_ship_total(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    sources = [_second_colony(uid, conn=conn)]
    sources.append(_extra_colonies(uid, conn, [9])[0])
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, fuel_cells=50000)
    for sid in sources:
        _fund_planet(cur, sid, metal=8000, crystal=1000)
    _seed_ships(hub, uid, {'mule_courier': 6}, conn=conn)
    conn.commit()
    hub_before = int(get_planet_ships(hub, conn=conn).get('mule_courier', 0))
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 6}, resources_mode='all', conn=conn)
    assert ok
    assert len(payload['started']) == 2
    hub_after_send = int(get_planet_ships(hub, conn=conn).get('mule_courier', 0))
    assert hub_after_send == 0
    assert hub_before == 6
    in_flight = 0
    for leg in payload['started']:
        cur.execute('SELECT ships_json FROM fleet_movements WHERE id = ?;', (int(leg['fleet_id']),))
        ships = json.loads(cur.fetchone()['ships_json'])
        in_flight += int(ships.get('mule_courier', 0))
    assert in_flight == 6
    conn.close()

def test_logistics_collect_return_double_tick_no_hub_dup(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=5000, crystal=5000, fuel_cells=50000)
    _fund_planet(cur, source, metal=12000, crystal=0, fuel_cells=0)
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before = int(cur.fetchone()['metal'])
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 1}, resources_mode='all', conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    now = time.time()
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    tick1 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_once = int(cur.fetchone()['metal'])
    msgs_once = _count_fleet_messages(uid, fleet_id)
    tick2 = process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_twice = int(cur.fetchone()['metal'])
    msgs_twice = _count_fleet_messages(uid, fleet_id)
    assert int(tick1.get('processed_returns') or 0) == 1
    assert int(tick2.get('processed_returns') or 0) == 0
    assert hub_once == hub_twice
    assert hub_once > hub_before
    assert msgs_once == msgs_twice == 2
    assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_collect_arrival') == 1
    assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_collect_return') == 1
    conn.close()

def test_logistics_distribute_return_double_tick_no_second_delivery(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=10000)
    _fund_planet(cur, target, metal=100, crystal=50)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 2500, 'crystal': 400, 'fuel_cells': 0}, conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    target_after_arrival = dict(cur.fetchone())
    now = time.time()
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (target,))
    target_after_return_ticks = dict(cur.fetchone())
    assert target_after_arrival == target_after_return_ticks
    assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_distribute_arrival') == 1
    assert _count_fleet_messages(uid, fleet_id, report_phase='logistics_distribute_return') == 1
    conn.close()

def test_spy_arrival_double_tick_one_report(fleet_db):
    _foreign_uid, _foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {'veil_probe': 3}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='spy', ships={'veil_probe': 1}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    once = _count_fleet_messages(uid, fleet_id, category='espionage')
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    twice = _count_fleet_messages(uid, fleet_id, category='espionage')
    assert once == twice == 1
    conn.close()

def test_hold_arrival_double_tick_one_report(fleet_db):
    uid1, uid2, colony2, (g, s, p) = _allied_players_standalone()
    conn = db()
    cur = conn.cursor()
    pid = int(get_planets_by_player(uid1, conn=conn)[0]['id'])
    _fund_planet(cur, pid)
    _seed_ships(pid, uid1, {'falcon_interceptor': 4}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid1, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='hold', ships={'falcon_interceptor': 2}, conn=conn)
    assert ok
    fleet_id = result['fleet']['id']
    _force_outbound_arrival(conn, fleet_id)
    process_fleet_tick(player_id=uid1, conn=conn)
    conn.commit()
    once = _count_fleet_messages(uid1, fleet_id, category='system')
    process_fleet_tick(player_id=uid1, conn=conn)
    conn.commit()
    twice = _count_fleet_messages(uid1, fleet_id, category='system')
    assert once == twice == 1
    conn.close()

def test_get_fleet_live_state_non_active_planet_still_ticks(fleet_db):
    from game.fleet import get_fleet_live_state
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, fuel_cells=50000)
    _fund_planet(cur, source, metal=9000, crystal=0, fuel_cells=0)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 1}, resources_mode='all', conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    now = time.time()
    cur.execute("\n        UPDATE fleet_movements\n        SET arrival_at = ?, status = 'returning', return_at = ?, resources_json = ?\n        WHERE id = ?;\n        ", (now - 200, now - 1, json.dumps({'metal': 2000, 'crystal': 0, 'fuel_cells': 0}), fleet_id))
    conn.commit()
    state = get_fleet_live_state(player_id=uid, planet_id=source, conn=conn)
    assert state['ready'] is True
    assert 'server_now' in state
    assert int(state['server_now']) > 0
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'completed'
    assert state['fleet_slots']['active'] == 0
    conn.close()

def test_evaluate_mission_position_16_non_expedition_blocked(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    g, s, _ = _planet_coords(pid, conn=conn)
    ok, reason, target = evaluate_fleet_mission_target(uid, 'transport', g, s, EXPEDITION_POSITION, conn=conn)
    assert not ok
    assert reason == 'mission_blocked_expedition_slot'
    assert target.get('target_type') == 'expedition_slot'
    conn.close()

def test_collect_multi_leg_fuel_deducted_once_per_movement(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    sources = _extra_colonies(uid, conn, [4, 6])
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, fuel_cells=100000)
    for sid in sources:
        _fund_planet(cur, sid, metal=5000, crystal=500)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (hub,))
    fuel_before = float(cur.fetchone()['fuel_cells'])
    ok, _, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 4}, resources_mode='all', conn=conn)
    assert ok
    assert len(payload['started']) == 2
    conn.commit()
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (hub,))
    fuel_after_send = float(cur.fetchone()['fuel_cells'])
    fuel_sum_legs = 0
    for leg in payload['started']:
        cur.execute('SELECT fuel_cost FROM fleet_movements WHERE id = ?;', (int(leg['fleet_id']),))
        fuel_sum_legs += int(cur.fetchone()['fuel_cost'] or 0)
    assert fuel_after_send == fuel_before - fuel_sum_legs
    assert fuel_sum_legs > 0
    for leg in payload['started']:
        _force_outbound_arrival(conn, int(leg['fleet_id']))
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (hub,))
    fuel_after_tick = float(cur.fetchone()['fuel_cells'])
    assert fuel_after_tick == fuel_after_send
    conn.close()

def test_fleet_ui_active_buttons_have_handlers():
    """Non-disabled fleet buttons must be wired in initFleet (static contract)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    tpl = (root / 'templates' / 'fleet.html').read_text(encoding='utf-8')
    js = (root / 'static' / 'main.js').read_text(encoding='utf-8')
    assert 'fleet-dev-panel' not in tpl
    assert 'data-fleet-dev-seed' not in tpl
    required_bindings = ['bindFleetOnce', 'applyQuickTarget', '[data-ship-max]', '[data-ship-max-image]', '[data-fleet-res-max]', '[data-fleet-expedition-shortcut]', '[data-fleet-quick-target-select]', '[data-fleet-save-preset]', '[data-preset-load]', '[data-preset-delete]', '/api/shipyard/build', '/api/fleet/preview', '/api/fleet/send', '/api/fleet/mass-expedition', '/api/fleet/state', 'rt.sending', 'data-fleet-send-btn', 'data-preview-target-type', 'data-fleet-mission-feedback', 'updateMissionFeedback', 'applyExpeditionTarget', 'applyFleetUrlPrefill', 'syncExpeditionMissionTarget', 'updateFleetFormMode', 'shouldShowExpeditionHours', 'data-preview-mission-badge', 'data-fleet-expedition-shortcut', 'submitMassExpedition', 'data-fleet-mass-expo-submit', 'syncExpeditionDailyEfficiencyUi', 'data-preview-expedition-daily-row', 'initHudSelects', 'data-gc-hud-select', 'tickFleetCountdowns', 'fleetRefreshBusy']
    for needle in required_bindings:
        assert needle in js, f'missing initFleet binding: {needle}'
    assert 'GC.modules.fleet = initFleet' in js
    assert 'GC.modules.shipyard = initShipyard' in js
    assert 'path.endsWith("/fleet")' in js
    assert 'path.endsWith("/shipyard")' in js
    assert 'id="shipyard-page"' in (root / 'templates' / 'shipyard.html').read_text(encoding='utf-8')
    assert 'data-galaxy="' in tpl
    assert 'name="target_galaxy"' in tpl

def test_quick_target_template_sets_coord_inputs():
    from pathlib import Path
    tpl = (Path(__file__).resolve().parent.parent / 'templates' / 'fleet.html').read_text(encoding='utf-8')
    assert 'name="target_galaxy"' in tpl
    assert 'name="target_system"' in tpl
    assert 'name="target_position"' in tpl
    assert 'data-galaxy' in tpl and 'data-fleet-quick-target-select' in tpl
    assert 'data-fleet-expedition-shortcut' in tpl
    assert 'id="fleet-mass-expo-form"' in tpl
    assert '<form id="fleet-mass-expo-form"' not in tpl
    send_close = tpl.index('</form>', tpl.index('id="fleet-send-form"'))
    footer_idx = tpl.index('fleet-ogame-footer')
    assert send_close < footer_idx
    mission_idx = tpl.index('data-fleet-mission')
    expo_idx = tpl.index('data-fleet-expedition-hours-row')
    speed_idx = tpl.index('data-fleet-speed')
    assert mission_idx < expo_idx < speed_idx
    assert 'fleet-colony-chip' not in tpl
    assert 'render_fleet_slots_badge' in tpl
    assert "'strip'" in tpl
    assert 'fleet-quick-row-head' in tpl
    assert 'fleet-ogame-ships-head' in tpl
    assert 'fleet-command-head' not in tpl
    slots_partial = (Path(__file__).resolve().parent.parent / 'templates' / 'partials' / 'fleet_slots_badge.html').read_text(encoding='utf-8')
    assert "modifier == 'strip'" in slots_partial or 'fleet-slots-line' in slots_partial
    assert 'fleet-coords-strip' in tpl
    assert 'fleet-coords-line' in tpl
    assert 'fleet-expedition-shortcut-wrap' not in tpl
    coords_strip_idx = tpl.index('data-fleet-coords-strip')
    coords_line_idx = tpl.index('fleet-coords-line')
    expo_idx = tpl.index('data-fleet-expedition-shortcut')
    mission_idx = tpl.index('id="fleet-mission"')
    assert coords_line_idx < coords_strip_idx < expo_idx < mission_idx
    assert 'fleet-expedition-shortcut-coords' not in tpl
    assert 'fleet-preview-hud' in tpl
    assert 'fleet-send-compact-grid' in tpl
    assert 'fleet-send-actions' in tpl
    assert 'data-preview-mission-badge' in tpl
    assert 'data-fleet-send-btn' in tpl
    assert 'data-gc-hud-select' in tpl
    assert 'data-ship-max-image' in tpl
    assert 'data-fleet-ship-pick-tooltip' in tpl
    assert 'data-fleet-ship-pick-trigger' in tpl
    assert 'fleet-ship-pick-value' in tpl
    assert 'gc-fleet-drawer-tooltip' in tpl
    assert 'shipyard_role_' in tpl
    assert 'fleet-ship-card-stock' in tpl
    assert 'data-fleet-ship-stock' in tpl

def test_fuel_efficiency_reduces_cost():
    base = calculate_fuel_cost({'mule_courier': 10}, 5000, 100, fuel_efficiency_level=0)
    reduced = calculate_fuel_cost({'mule_courier': 10}, 5000, 100, fuel_efficiency_level=5)
    assert reduced < base
    assert reduced >= int(base * fuel_efficiency_factor(5))

def test_fuel_cost_never_negative():
    assert calculate_fuel_cost({}, 1000, 100) == 0
    assert calculate_fuel_cost({'mule_courier': 1}, 0, 100) == 0

def test_planets_have_fuel_cells_after_migration(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,))
    row = cur.fetchone()
    assert row is not None
    assert float(row['fuel_cells']) >= 0
    conn.close()

def test_shipyard_build_requires_level(fleet_db):
    from game.shipyard import build_ships
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=100000, crystal=100000)
    conn.commit()
    ok, reason, _ = build_ships(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=1, conn=conn)
    assert not ok
    assert reason == 'shipyard_required'
    conn.close()

def test_shipyard_build_adds_ships(fleet_db):
    import time
    from game.fleet import get_planet_ships
    from game.shipyard import build_ships
    from game.shipyard_queue import finish_due_shipyard_jobs_for_planet
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=100000, crystal=100000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, result = build_ships(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=2, conn=conn)
    assert ok, reason
    assert result['shipyard_queue']['summary']['count'] == 1
    cur.execute('UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;', (time.time() - 1, pid))
    conn.commit()
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=time.time())
    assert get_planet_ships(pid, conn=conn).get('mule_courier', 0) >= 2
    conn.close()

def test_shipyard_build_without_resources_fails(fleet_db):
    from game.shipyard import build_ships
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=0, crystal=0, fuel_cells=500)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, _ = build_ships(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=1, conn=conn)
    assert not ok
    assert reason == 'not_enough_resources'
    conn.close()

def test_recall_fleet_movement_outbound(fleet_db):
    from game.fleet import build_active_fleets_payload, recall_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, conn=conn)
    assert ok
    fleet_id = int(result['fleet']['id'])
    ok_recall, reason, _payload = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert ok_recall, reason
    row = cur.execute('SELECT status, return_at FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()
    assert row['status'] == 'returning'
    assert int(row['return_at'] or 0) > int(time.time())
    payload = build_active_fleets_payload(uid, conn=conn)
    assert payload['count'] == 1
    item = payload['items'][0]
    assert item['movement_id'] == fleet_id
    assert item['can_recall'] is False
    assert item['status'] == 'returning'
    assert payload.get('fleets_confirmed_empty') is False
    assert payload.get('active_fleet_count') == 1
    conn.close()


def test_build_active_fleets_payload_confirmed_empty_flags(fleet_db):
    from game.fleet import build_active_fleets_payload

    conn = db()
    uid = _player(conn=conn)
    empty = build_active_fleets_payload(uid, conn=conn)
    assert empty['count'] == 0
    assert empty['active_fleet_count'] == 0
    assert empty['fleets_confirmed_empty'] is True
    conn.close()

def test_recall_fleet_movement_before_overdue_arrival_tick(fleet_db):
    """Cancel must win over a not-yet-ticked overdue arrival (transport/spy/attack)."""
    from game.fleet import recall_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    target_id = int(colony2)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planets SET metal = 1000 WHERE id = ?;', (target_id,))
    metal_before = int(cur.execute('SELECT metal FROM planets WHERE id = ?;', (target_id,)).fetchone()['metal'])
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 500, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok
    fleet_id = int(result['fleet']['id'])
    past = int(time.time()) - 5
    cur.execute('UPDATE fleet_movements SET arrival_at = ?, departure_at = ? WHERE id = ?;', (past, past - 120, fleet_id))
    conn.commit()
    ok_recall, reason, _payload = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert ok_recall, reason
    row = cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()
    assert row['status'] == 'returning'
    metal_after = int(cur.execute('SELECT metal FROM planets WHERE id = ?;', (target_id,)).fetchone()['metal'])
    assert metal_after == metal_before
    conn.close()

def _send_transport_fleet(conn, uid: int) -> tuple[int, int, int]:
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000, fuel_cells = 50000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 500, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok, reason
    return (uid, pid, int(result['fleet']['id']))

def test_recall_return_uses_elapsed_outbound_not_full_flight(fleet_db):
    from game.fleet import recall_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    uid, _pid, fleet_id = _send_transport_fleet(conn, uid)
    now = time.time()
    elapsed = 120
    total = 600
    dep = now - elapsed
    conn.execute('UPDATE fleet_movements SET departure_at = ?, arrival_at = ?, flight_seconds = ? WHERE id = ?;', (dep, dep + total, total, fleet_id))
    conn.commit()
    ok_recall, reason, _ = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert ok_recall, reason
    row = conn.execute('SELECT status, return_at, departure_at FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()
    assert row['status'] == 'returning'
    return_at = int(row['return_at'])
    assert abs(return_at - (int(now) + elapsed)) <= 2
    assert return_at < int(now) + total
    conn.close()

def test_recall_return_minimum_one_second(fleet_db):
    from game.fleet import recall_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    uid, _pid, fleet_id = _send_transport_fleet(conn, uid)
    now = time.time()
    dep = now - 0.5
    conn.execute('UPDATE fleet_movements SET departure_at = ?, arrival_at = ?, flight_seconds = 600 WHERE id = ?;', (dep, dep + 600, fleet_id))
    conn.commit()
    ok_recall, reason, _ = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert ok_recall, reason
    return_at = int(conn.execute('SELECT return_at FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()['return_at'])
    assert return_at >= int(now) + 1
    assert return_at <= int(now) + 3
    conn.close()

def test_recall_return_near_arrival_uses_elapsed_not_remaining(fleet_db):
    from game.fleet import recall_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    uid, _pid, fleet_id = _send_transport_fleet(conn, uid)
    now = time.time()
    total = 600
    elapsed = 590
    dep = now - elapsed
    conn.execute('UPDATE fleet_movements SET departure_at = ?, arrival_at = ?, flight_seconds = ? WHERE id = ?;', (dep, dep + total, total, fleet_id))
    conn.commit()
    ok_recall, reason, _ = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert ok_recall, reason
    return_at = int(conn.execute('SELECT return_at FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()['return_at'])
    assert abs(return_at - (int(now) + elapsed)) <= 2
    assert return_at > int(now) + 60
    conn.close()

def test_recall_returning_fleet_cannot_recall_again(fleet_db):
    from game.fleet import recall_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    uid, _pid, fleet_id = _send_transport_fleet(conn, uid)
    ok1, reason1, _ = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert ok1, reason1
    ok2, reason2, _ = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert not ok2
    assert reason2 == 'fleet_recall_not_allowed'
    conn.close()

def test_recall_foreign_fleet_denied(fleet_db):
    from game.fleet import recall_fleet_movement
    uid = _player()
    other_uid = _player()
    conn = db()
    _, _pid, fleet_id = _send_transport_fleet(conn, uid)
    ok, reason, _ = recall_fleet_movement(other_uid, fleet_id, conn=conn)
    assert not ok
    assert reason == 'fleet_not_found'
    conn.close()

def test_recall_completes_with_ships_and_cargo_on_origin_without_mission(fleet_db):
    from game.fleet import process_fleet_tick, recall_fleet_movement
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    target_id = int(colony2)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000, fuel_cells = 50000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planets SET metal = 1000 WHERE id = ?;', (target_id,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    ships_before = int(get_planet_ships(pid, conn=conn).get('mule_courier') or 0)
    metal_origin_before = int(cur.execute('SELECT metal FROM planets WHERE id = ?;', (pid,)).fetchone()['metal'])
    metal_target_before = int(cur.execute('SELECT metal FROM planets WHERE id = ?;', (target_id,)).fetchone()['metal'])
    conn.commit()
    ok, reason, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 500, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok, reason
    fleet_id = int(result['fleet']['id'])
    ships_after_send = int(get_planet_ships(pid, conn=conn).get('mule_courier') or 0)
    metal_after_send = int(cur.execute('SELECT metal FROM planets WHERE id = ?;', (pid,)).fetchone()['metal'])
    assert ships_after_send == ships_before - 1
    now = time.time()
    conn.execute('UPDATE fleet_movements SET departure_at = ?, arrival_at = ?, flight_seconds = 600 WHERE id = ?;', (now - 120, now + 480, fleet_id))
    conn.commit()
    ok_recall, recall_reason, _ = recall_fleet_movement(uid, fleet_id, conn=conn)
    assert ok_recall, recall_reason
    conn.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    status = conn.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,)).fetchone()['status']
    assert status == 'completed'
    ships_final = int(get_planet_ships(pid, conn=conn).get('mule_courier') or 0)
    assert ships_final == ships_before
    metal_origin_after = int(conn.execute('SELECT metal FROM planets WHERE id = ?;', (pid,)).fetchone()['metal'])
    metal_target_after = int(conn.execute('SELECT metal FROM planets WHERE id = ?;', (target_id,)).fetchone()['metal'])
    assert metal_target_after == metal_target_before
    assert metal_origin_after >= metal_after_send
    assert metal_origin_after <= metal_origin_before
    conn.close()

def test_api_fleet_recall_returns_state(fleet_db, monkeypatch):
    import importlib
    import app as app_module
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 5000 WHERE id = ?;', (pid,))
    _seed_ships(pid, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, result = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, conn=conn)
    assert ok
    fleet_id = int(result['fleet']['id'])
    now = time.time()
    cur.execute('UPDATE fleet_movements SET departure_at = ?, arrival_at = ?, flight_seconds = 600 WHERE id = ?;', (now - 120, now + 480, fleet_id))
    conn.commit()
    conn.close()
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.post('/api/fleet/recall', json={'movement_id': fleet_id, 'request_id': uuid.uuid4().hex}, headers={'Content-Type': 'application/json'})
    assert r.status_code == 200
    body = r.get_json()
    assert body.get('ok') is True
    assert isinstance(body.get('state'), dict)
    active = body['state'].get('active_fleets') or {}
    assert isinstance(active, dict)
    assert active.get('count') == 1
    assert active['items'][0]['status'] == 'returning'

def test_vacation_mode_blocks_attack_send_and_arrival(fleet_db):
    conn = db()
    attacker_id = _player(conn=conn)
    att_pid = int(get_planets_by_player(attacker_id, conn=conn)[0]['id'])
    _seed_ships(att_pid, attacker_id, {'falcon_interceptor': 5}, conn=conn)
    conn.commit()
    conn.close()
    defender_id, def_pid, (dg, ds, dp) = _foreign_planet_standalone()
    conn = db()
    cur = conn.cursor()
    cur.execute('UPDATE players SET vacation_mode_active = 1, vacation_locked_until = ? WHERE id = ?;', (int(time.time()) + 86400, defender_id))
    conn.commit()
    ok, reason, _ = send_fleet(player_id=attacker_id, origin_planet_id=att_pid, target_galaxy=dg, target_system=ds, target_position=dp, mission_type='attack', ships={'falcon_interceptor': 1}, conn=conn)
    assert not ok
    assert reason == 'vacation_target_protected'
    now = int(time.time())
    cur.execute("\n        INSERT INTO fleet_movements (\n            player_id, origin_planet_id, target_planet_id,\n            target_galaxy, target_system, target_position,\n            mission_type, status, ships_json, resources_json,\n            fuel_cost, speed_percent, distance, flight_seconds,\n            departure_at, arrival_at, return_at, created_at, updated_at\n        ) VALUES (?, ?, ?, ?, ?, ?, 'attack', 'outbound', ?, '{}', 0, 100, 1, 100, ?, ?, NULL, ?, ?);\n        ", (attacker_id, att_pid, def_pid, dg, ds, dp, json.dumps({'falcon_interceptor': 1}), now - 200, now - 1, now, now))
    fleet_id = int(cur.lastrowid)
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (def_pid,))
    metal_before = int(cur.fetchone()['metal'])
    conn.commit()
    process_fleet_tick(player_id=attacker_id, conn=conn)
    conn.commit()
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'returning'
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (def_pid,))
    assert int(cur.fetchone()['metal']) == metal_before
    conn.close()

def _insert_inbound_movement(conn, *, attacker_id: int, target_planet_id: int, origin_planet_id: int | None=None, mission_type: str='attack', status: str='outbound', arrival_at: float | None=None, created_at: float | None=None) -> int:
    now = time.time()
    created = float(created_at if created_at is not None else now)
    arrival = float(arrival_at if arrival_at is not None else created + 3600)
    origin_id = int(origin_planet_id if origin_planet_id is not None else get_planets_by_player(attacker_id, conn=conn)[0]['id'])
    g, s, p = _planet_coords(int(target_planet_id), conn=conn)
    cur = conn.cursor()
    cur.execute("\n        INSERT INTO fleet_movements (\n            player_id, origin_planet_id, target_planet_id,\n            target_galaxy, target_system, target_position,\n            mission_type, status, departure_at, arrival_at, return_at, holding_until,\n            ships_json, resources_json, fuel_cost, speed_percent, distance, flight_seconds,\n            preset_id, parent_batch_id, created_at, updated_at\n        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, '{}', '{}', 0, 100, 1, 60, NULL, NULL, ?, ?);\n        ", (int(attacker_id), origin_id, int(target_planet_id), g, s, p, mission_type, status, now - 60, arrival, created, created))
    return int(cur.lastrowid)

def test_incoming_attack_alert_counts_enemy_attack(fleet_db):
    attacker_id = _player()
    defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid)
    alerts = build_fleet_incoming_attack_alerts(defender_id, conn=conn)
    assert alerts['has_incoming_attack'] is True
    assert alerts['incoming_attack_count'] == 1
    assert alerts['alert_key'].startswith('m:')
    assert int(alerts['next_attack_arrival']) > int(time.time())
    conn.close()

def test_incoming_attack_alert_attacker_no_alarm(fleet_db):
    attacker_id = _player()
    defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid)
    alerts = build_fleet_incoming_attack_alerts(attacker_id, conn=conn)
    assert alerts['has_incoming_attack'] is False
    assert alerts['incoming_attack_count'] == 0
    conn.close()

def test_incoming_attack_alert_spy_no_alarm(fleet_db):
    attacker_id = _player()
    defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, mission_type='spy')
    alerts = build_fleet_incoming_attack_alerts(defender_id, conn=conn)
    assert alerts['has_incoming_attack'] is False
    conn.close()

def test_incoming_attack_alert_returning_no_alarm(fleet_db):
    attacker_id = _player()
    defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, status='returning')
    alerts = build_fleet_incoming_attack_alerts(defender_id, conn=conn)
    assert alerts['has_incoming_attack'] is False
    conn.close()

def test_incoming_attack_alert_multiple_and_earliest_arrival(fleet_db):
    attacker_id = _player()
    defender_id, def_pid, _coords = _foreign_planet_standalone()
    now = time.time()
    conn = db()
    _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, arrival_at=now + 7200)
    _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, arrival_at=now + 1800)
    alerts = build_fleet_incoming_attack_alerts(defender_id, conn=conn, now=now)
    assert alerts['incoming_attack_count'] == 2
    assert int(alerts['next_attack_arrival']) == int(now + 1800)
    assert alerts['alert_key'].count(',') == 1
    conn.close()

def test_attack_limit_allows_five_attacks_on_same_target(fleet_db):
    attacker_id = _player()
    _defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    for i in range(4):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, created_at=time.time() - i)
    ok, info = check_attack_limit(attacker_id, def_pid, conn=conn)
    assert ok is True
    assert info['used'] == 4
    assert info['remaining'] == 1
    conn.close()

def test_attack_limit_blocks_sixth_attack(fleet_db):
    attacker_id = _player()
    _defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid)
    ok, info = check_attack_limit(attacker_id, def_pid, conn=conn)
    assert ok is False
    assert info['used'] == 5
    conn.close()

def test_attack_limit_other_target_planet_has_separate_budget(fleet_db):
    attacker_id = _player()
    defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    colony2 = _second_colony(defender_id, conn=conn)
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid)
    ok_planet_a, info_a = check_attack_limit(attacker_id, def_pid, conn=conn)
    ok_planet_b, info_b = check_attack_limit(attacker_id, colony2, conn=conn)
    assert ok_planet_a is False
    assert info_a['used'] == 5
    assert ok_planet_b is True
    assert info_b['used'] == 0
    conn.close()

def test_attack_limit_two_targets_allow_ten_attacks_total(fleet_db):
    attacker_id = _player()
    defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    colony2 = _second_colony(defender_id, conn=conn)
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid)
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=colony2)
    ok_a, info_a = check_attack_limit(attacker_id, def_pid, conn=conn)
    ok_b, info_b = check_attack_limit(attacker_id, colony2, conn=conn)
    assert ok_a is False and info_a['used'] == 5
    assert ok_b is False and info_b['used'] == 5
    conn.close()

def test_attack_limit_account_wide_blocks_colony_bypass(fleet_db):
    attacker_id = _player()
    conn = db()
    colony1 = int(get_planets_by_player(attacker_id, conn=conn)[0]['id'])
    colony2 = _second_colony(attacker_id, conn=conn)
    _defender_id, def_pid, (dg, ds, dp) = _foreign_planet_standalone()
    for _ in range(3):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, origin_planet_id=colony1)
    for _ in range(2):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, origin_planet_id=colony2)
    ok, info = check_attack_limit(attacker_id, def_pid, conn=conn)
    assert ok is False
    assert info['used'] == 5
    assert info['remaining'] == 0
    cur = conn.cursor()
    _fund_planet(cur, colony2)
    _seed_ships(colony2, attacker_id, {'falcon_interceptor': 5}, conn=conn)
    conn.commit()
    ok, reason, extra = send_fleet(player_id=attacker_id, origin_planet_id=colony2, target_galaxy=dg, target_system=ds, target_position=dp, mission_type='attack', ships={'falcon_interceptor': 1}, conn=conn)
    assert ok is False
    assert reason == 'attack_limit_reached'
    assert extra and extra.get('attack_limit', {}).get('used') == 5
    conn.close()

def test_attack_limit_other_attacker_has_own_budget(fleet_db):
    attacker_a = _player()
    attacker_b = _player()
    _defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_a, target_planet_id=def_pid)
    ok_a, _ = check_attack_limit(attacker_a, def_pid, conn=conn)
    ok_b, info_b = check_attack_limit(attacker_b, def_pid, conn=conn)
    assert ok_a is False
    assert ok_b is True
    assert info_b['used'] == 0
    conn.close()

def test_attack_limit_spy_does_not_count(fleet_db):
    attacker_id = _player()
    _defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, mission_type='spy')
    ok, info = check_attack_limit(attacker_id, def_pid, conn=conn)
    assert ok is True
    assert info['used'] == 0
    conn.close()

def test_attack_limit_ignores_attacks_outside_window(fleet_db):
    attacker_id = _player()
    _defender_id, def_pid, _coords = _foreign_planet_standalone()
    conn = db()
    now = time.time()
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid, created_at=now - 25 * 3600)
    ok, info = check_attack_limit(attacker_id, def_pid, conn=conn, now=now)
    assert ok is True
    assert info['used'] == 0
    conn.close()

def test_attack_limit_preview_blocks_at_limit(fleet_db):
    attacker_id = _player()
    _defender_id, def_pid, (dg, ds, dp) = _foreign_planet_standalone()
    conn = db()
    att_pid = int(get_planets_by_player(attacker_id, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, att_pid)
    _seed_ships(att_pid, attacker_id, {'falcon_interceptor': 5}, conn=conn)
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid)
    origin = dict(conn.execute('SELECT * FROM planets WHERE id = ?;', (att_pid,)).fetchone())
    preview = build_fleet_send_preview(player_id=attacker_id, origin_planet=origin, target_galaxy=dg, target_system=ds, target_position=dp, mission_type='attack', ships={'falcon_interceptor': 1}, resources={}, speed_percent=100, conn=conn)
    assert preview['can_send'] is False
    assert preview['block_reason'] == 'attack_limit_reached'
    assert preview['attack_limit']['used'] == 5
    assert preview['attack_limit']['remaining'] == 0
    conn.close()

def test_attack_limit_send_blocks_without_ship_deduction(fleet_db):
    attacker_id = _player()
    _defender_id, def_pid, (dg, ds, dp) = _foreign_planet_standalone()
    conn = db()
    att_pid = int(get_planets_by_player(attacker_id, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, att_pid)
    _seed_ships(att_pid, attacker_id, {'falcon_interceptor': 10}, conn=conn)
    for _ in range(5):
        _insert_inbound_movement(conn, attacker_id=attacker_id, target_planet_id=def_pid)
    before = int(get_planet_ships(att_pid, conn=conn).get('falcon_interceptor') or 0)
    conn.commit()
    ok, reason, extra = send_fleet(player_id=attacker_id, origin_planet_id=att_pid, target_galaxy=dg, target_system=ds, target_position=dp, mission_type='attack', ships={'falcon_interceptor': 5}, conn=conn)
    assert ok is False
    assert reason == 'attack_limit_reached'
    assert extra and extra.get('attack_limit', {}).get('used') == 5
    after = int(get_planet_ships(att_pid, conn=conn).get('falcon_interceptor') or 0)
    assert after == before
    conn.close()
