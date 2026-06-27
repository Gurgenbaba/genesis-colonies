"""Orbital Shipyard and Genesis Colonies hull registry tests."""
from __future__ import annotations
import time
import uuid
import pytest
from game import db as gdb
from game.db import db
from game.fleet_defs import ACTIVE_SHIP_KEYS, LEGACY_SHIP_KEYS, SHIPS, canonical_ship_key, get_ship
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db

@pytest.fixture
def shipyard_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'shipyard_test.db'
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
    ok, err, user = create_user(f'sy_user_{uuid.uuid4().hex[:10]}', 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Shipwright', conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid

def _fund_planet(cur, planet_id: int, *, metal: int, crystal: int, fuel_cells: float=500000):
    cur.execute('UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;', (metal, crystal, fuel_cells, planet_id))

def _grant_ship_test_prereqs(cur, planet_id: int, user_id: int) -> None:
    """Buildings + research so hull requirement gates do not block shipyard tests."""
    cur.execute('\n        UPDATE planet_buildings\n        SET research_lab = 10, command_center = 10, barracks = 10\n        WHERE planet_id = ?;\n        ', (int(planet_id),))
    for tech in ('energy_tech', 'mining_tech', 'drone_tech', 'engine_tech', 'navigation_tech', 'weapon_tech', 'armor_tech', 'storage_tech', 'fuel_efficiency', 'shield_tech'):
        cur.execute('\n            INSERT INTO research_levels (user_id, tech_key, level)\n            VALUES (?, ?, ?)\n            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n            ', (int(user_id), tech, 10))

def test_all_nine_active_ship_types_exist():
    assert len(ACTIVE_SHIP_KEYS) == 9
    for key in ACTIVE_SHIP_KEYS:
        assert key in SHIPS
        spec = SHIPS[key]
        for field in ('name_key', 'description_key', 'role', 'required_shipyard_level', 'build_cost', 'build_seconds', 'speed', 'cargo', 'fuel', 'attack', 'shield', 'hull'):
            assert field in spec, f'{key} missing {field}'

def test_legacy_keys_not_primary_hull_names():
    for legacy in LEGACY_SHIP_KEYS:
        assert legacy not in ACTIVE_SHIP_KEYS
        assert legacy not in SHIPS

def test_legacy_mapping_resolves():
    assert canonical_ship_key('small_cargo') == 'mule_courier'
    assert get_ship('spy_probe')['role'] == 'spy'

def test_orbital_shipyard_building_in_catalog():
    from game.buildings import ALL_BUILDINGS, BUILDING_ORDER
    assert 'orbital_shipyard' in BUILDING_ORDER
    assert 'orbital_shipyard' in ALL_BUILDINGS

def test_buildable_ships_by_level(shipyard_db):
    from game.shipyard import list_buildable_ships, list_locked_ships
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    buildable = list_buildable_ships(uid, pid, conn=conn)
    keys = {s['ship_key'] for s in buildable}
    assert 'mule_courier' in keys
    assert 'veil_probe' in keys
    assert 'spark_drone' in keys
    assert 'ironclad_frigate' not in keys
    locked = list_locked_ships(uid, pid, conn=conn)
    locked_keys = {s['ship_key'] for s in locked}
    assert 'ironclad_frigate' in locked_keys
    conn.close()

def test_build_without_shipyard_fails(shipyard_db):
    from game.shipyard import build_ship
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _fund_planet(conn.cursor(), pid, metal=100000, crystal=100000)
    conn.commit()
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=1, conn=conn)
    assert not ok
    assert reason == 'shipyard_required'
    conn.close()

def test_build_level_one_hulls(shipyard_db):
    import time
    from game.fleet import get_planet_ships
    from game.shipyard import build_ship
    from game.shipyard_queue import finish_due_shipyard_jobs_for_planet
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=100000, crystal=100000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    for hull in ('mule_courier', 'veil_probe', 'spark_drone'):
        ok, reason, result = build_ship(player_id=uid, planet_id=pid, ship_key=hull, amount=1, conn=conn)
        assert ok, reason
        assert result['shipyard_queue']['summary']['count'] >= 1
    cur.execute('UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;', (time.time() - 1, pid))
    conn.commit()
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=time.time())
    ships = get_planet_ships(pid, conn=conn)
    for hull in ('mule_courier', 'veil_probe', 'spark_drone'):
        assert ships.get(hull, 0) >= 1
    conn.close()

def test_build_level_too_low_fails(shipyard_db):
    from game.shipyard import build_ship
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='ironclad_frigate', amount=1, conn=conn)
    assert not ok
    assert reason == 'shipyard_level_too_low'
    conn.close()

def test_build_not_enough_resources(shipyard_db):
    from game.shipyard import build_ship
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=0, crystal=0)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=1, conn=conn)
    assert not ok
    assert reason == 'not_enough_resources'
    conn.close()

def test_build_deducts_resources_and_adds_ships(shipyard_db):
    import time
    from game.fleet import get_planet_ships
    from game.shipyard import build_ship, max_build_amount_for_planet
    from game.shipyard_queue import finish_due_shipyard_jobs_for_planet
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=10000, crystal=10000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    max_qty = max_build_amount_for_planet(10000, 10000, 500, 'mule_courier', 1, player_id=uid, planet_id=pid, conn=conn)
    assert max_qty >= 2
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    before = cur.fetchone()
    ok, _, result = build_ship(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=2, conn=conn)
    assert ok
    assert result['shipyard_queue']['summary']['count'] == 1
    cur.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (pid,))
    after = cur.fetchone()
    assert float(after['metal']) < float(before['metal'])
    cur.execute('UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;', (time.time() - 1, pid))
    conn.commit()
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=time.time())
    assert get_planet_ships(pid, conn=conn).get('mule_courier', 0) >= 2
    conn.close()

def test_preset_legacy_keys_normalize(shipyard_db):
    from game.fleet import create_preset, get_preset
    conn = db()
    uid = _player(conn=conn)
    ok, _, preset = create_preset(uid, name='Legacy', preset_type='custom', ships_json={'small_cargo': 3, 'spy_probe': 1}, conn=conn)
    assert ok
    loaded = get_preset(preset['id'], uid, conn=conn)
    ships = loaded['ships']
    assert ships.get('mule_courier') == 3
    assert ships.get('veil_probe') == 1
    conn.close()

def test_ships_isolated_per_planet(shipyard_db):
    import time
    from game.fleet import add_planet_ships, get_planet_ships
    from game.planet_evolution.service import colonize_planet
    from game.shipyard import build_ship, get_ship_inventory
    conn = db()
    uid = _player(conn=conn)
    home = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, home, metal=200000, crystal=200000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (home,))
    _grant_ship_test_prereqs(cur, home, uid)
    conn.commit()
    ok_col, _, extra = colonize_planet(uid, name='Shipyard Colony II', galaxy=1, system=401, position=9, conn=conn, allow_legacy_coordinates=True, source='test')
    assert ok_col, extra
    colony = int(extra['planet_id'])
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (colony,))
    _grant_ship_test_prereqs(cur, colony, uid)
    _fund_planet(cur, colony, metal=200000, crystal=200000)
    conn.commit()
    ok, reason, _ = build_ship(player_id=uid, planet_id=home, ship_key='mule_courier', amount=3, conn=conn)
    assert ok, reason
    cur.execute('UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;', (time.time() - 1, home))
    conn.commit()
    from game.shipyard_queue import finish_due_shipyard_jobs_for_planet
    finish_due_shipyard_jobs_for_planet(conn, home, uid, now=time.time())
    add_planet_ships(colony, uid, {'veil_probe': 7}, conn=conn)
    home_ships = get_ship_inventory(uid, home, conn=conn)
    colony_ships = get_ship_inventory(uid, colony, conn=conn)
    conn.close()
    assert home_ships.get('mule_courier', 0) >= 3
    assert home_ships.get('veil_probe', 0) == 0
    assert colony_ships.get('veil_probe', 0) == 7
    assert colony_ships.get('mule_courier', 0) == 0

def test_api_shipyard_rejects_foreign_planet(shipyard_db, monkeypatch):
    import app as app_mod
    uid_a = _player()
    uid_b = _player()
    conn = db()
    pid_b = int(get_planets_by_player(uid_b, conn=conn)[0]['id'])
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid_a
    rv = client.get(f'/api/shipyard?planet_id={pid_b}')
    assert rv.status_code == 404
    data = rv.get_json()
    assert data['ok'] is False
    assert data['error'] == 'planet_not_found'

def test_api_shipyard_get_and_build(shipyard_db, monkeypatch):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=200000, crystal=200000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 2 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    rv = client.get('/api/shipyard')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['ok'] is True
    assert data['data']['orbital_shipyard_level'] == 2
    assert any((s['ship_key'] == 'falcon_interceptor' for s in data['data']['buildable_ships']))
    rv2 = client.post('/api/shipyard/build', json={'ship_key': 'falcon_interceptor', 'amount': 1, 'planet_id': pid})
    assert rv2.status_code == 200
    built = rv2.get_json()
    assert built['ok'] is True
    rv3 = client.post('/api/shipyard/build', json={'ship_key': 'seed_ark', 'amount': 1, 'planet_id': pid})
    err = rv3.get_json()
    assert err['ok'] is False
    assert err['error'] == 'shipyard_level_too_low'

def test_progressive_shipyard_delivery(shipyard_db):
    """Multi-ship orders deliver in orbital-shipyard batches (L1 capacity = 3)."""
    from game.fleet import get_planet_ships
    from game.shipyard import build_ship, unit_batch_capacity, base_unit_seconds_for_ship, unit_build_seconds
    from game.shipyard_queue import finish_due_shipyard_jobs_for_planet, list_shipyard_queue_rows, queue_count, shipyard_queue_for_client
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    qty = 10
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=qty, conn=conn)
    assert ok, reason
    cur.execute('SELECT started_at, finish_at, amount FROM shipyard_queue WHERE planet_id = ?;', (pid,))
    job = cur.fetchone()
    started = float(job['started_at'])
    finish = float(job['finish_at'])
    unit = unit_build_seconds('mule_courier', 1, conn=conn, planet_id=pid)
    cap = unit_batch_capacity(1, base_unit_seconds_for_ship('mule_courier'))
    batches = (qty + cap - 1) // cap
    assert int(job['amount']) == qty
    assert int(finish - started) == unit * batches
    q_before = shipyard_queue_for_client(uid, pid, 1, conn=conn, now=started + unit - 0.5)
    assert q_before['queue'][0]['units_delivered'] == 0
    assert q_before['queue'][0]['order_total_seconds'] == unit * batches
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=started + unit - 0.5)
    assert get_planet_ships(pid, conn=conn).get('mule_courier', 0) == 0
    assert queue_count(pid, conn=conn) == 1
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=started + unit + 0.01)
    assert get_planet_ships(pid, conn=conn).get('mule_courier', 0) == cap
    q_after = shipyard_queue_for_client(uid, pid, 1, conn=conn, now=started + unit + 0.01)
    assert q_after['queue'][0]['units_delivered'] == cap
    assert q_after['queue'][0]['remaining'] == q_after['queue'][0]['order_remaining']
    rows = list_shipyard_queue_rows(pid, conn=conn)
    assert len(rows) == 1
    assert int(rows[0]['amount']) == qty - cap
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=started + 2 * unit + 0.01)
    assert get_planet_ships(pid, conn=conn).get('mule_courier', 0) == cap * 2
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=finish + 1)
    assert get_planet_ships(pid, conn=conn).get('mule_courier', 0) == qty
    assert queue_count(pid, conn=conn) == 0
    conn.close()

def test_progressive_ships_available_for_fleet_preview(shipyard_db, monkeypatch):
    """Ships credited mid-order are visible in fleet state without waiting for job completion."""
    import app as app_mod
    from game.shipyard import build_ship, unit_build_seconds
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=3, conn=conn)
    assert ok, reason
    cur.execute('SELECT started_at FROM shipyard_queue WHERE planet_id = ?;', (pid,))
    started = float(cur.fetchone()['started_at'])
    unit = unit_build_seconds('mule_courier', 1, conn=conn, planet_id=pid)
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    import time
    monkeypatch.setattr(time, 'time', lambda: started + unit + 0.01)
    rv = client.get(f'/api/fleet/state?planet_id={pid}')
    assert rv.status_code == 200
    data = rv.get_json()
    assert data['ok'] is True
    assert data['data']['ships'].get('mule_courier', 0) == 1
    assert data['data']['has_ships'] is True

def test_shipyard_queue_client_includes_countdown_at(shipyard_db):
    from game.shipyard import build_ship
    from game.shipyard_queue import shipyard_queue_for_client
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=1, conn=conn)
    assert ok, reason
    q = shipyard_queue_for_client(uid, pid, 1, conn=conn)
    assert q['queue']
    head = q['queue'][0]
    assert head.get('countdown_at') == int(head['finish_at'])
    assert head.get('finish_time') == int(head['finish_at'])
    assert int(head.get('remaining_seconds') or 0) > 0
    assert head.get('next_countdown_at') >= 0
    conn.close()

def test_weighted_unit_batch_capacity_differs_by_ship(shipyard_db):
    """GC-633: faster/cheaper ships get higher effective parallel capacity."""
    from game.shipyard import base_unit_seconds_for_ship, orbital_production_batch_capacity, unit_batch_capacity
    lvl = 5
    base = orbital_production_batch_capacity(lvl)
    fast = unit_batch_capacity(lvl, base_unit_seconds_for_ship('veil_probe'))
    slow = unit_batch_capacity(lvl, base_unit_seconds_for_ship('atlas_hauler'))
    assert fast > slow
    assert slow >= 1
    assert fast <= base

def test_shipyard_job_force_completes_at_finish_at(shipyard_db):
    """GC-633: jobs past finish_at deliver remaining units and leave the queue."""
    from game.fleet import get_planet_ships
    from game.shipyard import build_ship
    from game.shipyard_queue import finish_due_shipyard_jobs_for_planet, queue_count
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=500000, crystal=500000)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='mule_courier', amount=1, conn=conn)
    assert ok, reason
    cur.execute('UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;', (time.time() - 1, pid))
    conn.commit()
    finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=time.time())
    assert queue_count(pid, conn=conn) == 0
    assert get_planet_ships(pid, conn=conn).get('mule_courier', 0) >= 1
    conn.close()

def test_max_build_ignores_zero_cost_resources(shipyard_db):
    """Non-zero fuel cost must participate in max-build without a 999999 placeholder cap."""
    from game.shipyard import max_build_amount_for_planet, _unit_build_cost
    cost = _unit_build_cost('mule_courier')
    target = 1110929
    max_qty = max_build_amount_for_planet(cost['metal'] * target, cost['crystal'] * target, cost['fuel_cells'] * target, 'mule_courier', 1)
    assert max_qty == target
    assert max_qty > 999999
    broken_cap = min(cost['metal'] * target // cost['metal'], cost['crystal'] * target // cost['crystal'], 999999)
    assert max_qty > broken_cap
