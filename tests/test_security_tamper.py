"""
GC-553 — Client tamper audit: manipulated POST bodies must not affect game state.

Run: python -m pytest tests/test_security_tamper.py -v
"""
from __future__ import annotations
import importlib
import os
import time
import uuid
import pytest
import game.db as dbmod
import game.models as models
from game.buildings import get_upgrade_cost
from game.db import db
from game.fleet import add_planet_ships, fleet_schema_ready
from game.fleet_defs import get_ship
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, get_planets_by_player, init_db, save_planet_buildings
from game.exchange import _preview_receive, get_exchange_config
from game.planet_evolution.service import colonize_planet
from game.research import get_research_cost

@pytest.fixture()
def security_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'security_tamper.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_file))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-not-default-value-32chars')
    monkeypatch.setattr(dbmod, 'DB_PATH', db_file)
    monkeypatch.setattr(models, 'DB_PATH', db_file)
    init_db()
    import migrate
    migrate.main()
    yield db_file

def _reload_app(monkeypatch, db_file):
    import app as app_mod
    monkeypatch.setenv('GC_DB_PATH', str(db_file))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-not-default-value-32chars')
    dbmod.DB_PATH = db_file
    models.DB_PATH = db_file
    importlib.reload(app_mod)
    app_mod.app.config['TESTING'] = True
    app_mod.app.config['WTF_CSRF_ENABLED'] = False
    return app_mod

def _create_player(*, conn=None) -> tuple[int, str]:
    own = conn is None
    if own:
        conn = db()
    uname = f'sec_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Auditor', conn=conn)
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from conftest import unlock_colony_slots
    unlock_colony_slots(conn, int(get_homeworld(player_id=uid, conn=conn)['id']), slots=1)
    if own:
        conn.commit()
        conn.close()
    return (uid, uname)

def _login_client(app_mod, uname: str):
    client = app_mod.app.test_client()
    res = client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    assert res.status_code in (200, 302)
    return client

def _planet_row(planet_id: int, *, conn=None) -> dict:
    own = conn is None
    if own:
        conn = db()
    row = conn.execute('SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;', (int(planet_id),)).fetchone()
    if own:
        conn.close()
    return dict(row)

def _grant_ship_prereqs(cur, planet_id: int, user_id: int) -> None:
    cur.execute('\n        UPDATE planet_buildings\n        SET research_lab = 10, command_center = 10, barracks = 10, orbital_shipyard = 2\n        WHERE planet_id = ?;\n        ', (int(planet_id),))
    for tech in ('energy_tech', 'mining_tech', 'drone_tech', 'engine_tech', 'navigation_tech', 'weapon_tech', 'armor_tech', 'storage_tech', 'fuel_efficiency', 'shield_tech'):
        cur.execute('\n            INSERT INTO research_levels (user_id, tech_key, level)\n            VALUES (?, ?, ?)\n            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n            ', (int(user_id), tech, 10))

def _second_colony(uid: int, *, conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    ok, reason, extra = colonize_planet(uid, name=f'Colony_{uuid.uuid4().hex[:4]}', galaxy=1, system=400, position=3, conn=conn, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    if own:
        conn.commit()
        conn.close()
    return int(extra['planet_id'])

def test_building_upgrade_ignores_client_cost_and_uses_server_deduction(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_homeworld(player_id=uid)['id'])
    cost_m, cost_c = get_upgrade_cost('metal_mine', 0)
    conn = db()
    conn.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (cost_m + 500, cost_c + 500, pid))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    before = _planet_row(pid)
    res = client.post('/api/buildings/upgrade', json={'building_type': 'metal_mine', 'cost_metal': 0, 'cost_crystal': 0, 'finish_time': 1, 'current_level': 99, 'queue_position': 1})
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    after = _planet_row(pid)
    assert int(before['metal']) - int(after['metal']) == cost_m
    assert int(before['crystal']) - int(after['crystal']) == cost_c
    conn = db()
    job = conn.execute('SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY id DESC LIMIT 1;', (pid,)).fetchone()
    conn.close()
    assert float(job['finish_time']) > time.time() + 30

def test_building_upgrade_rejects_tampered_zero_cost_when_poor(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    _uid, uname = _create_player()
    pid = int(get_homeworld(player_id=_uid)['id'])
    conn = db()
    conn.execute('UPDATE planets SET metal = 0, crystal = 0 WHERE id = ?;', (pid,))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    res = client.post('/api/buildings/upgrade', json={'building_type': 'metal_mine', 'cost_metal': 0, 'cost_crystal': 0})
    body = res.get_json()
    assert body['ok'] is False
    assert body['reason'] == 'not_enough_resources'

def test_building_queue_limit_enforced_despite_client_queue_position(security_db, monkeypatch):
    from game.models import get_game_settings
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_homeworld(player_id=uid)['id'])
    queue_limit = max(1, int(get_game_settings().get('queue_limit', 5)))
    conn = db()
    conn.execute('UPDATE planets SET metal = 5000000, crystal = 5000000 WHERE id = ?;', (pid,))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    for _ in range(queue_limit):
        ok_res = client.post('/api/buildings/upgrade', json={'building_type': 'metal_mine'})
        assert ok_res.get_json()['ok'] is True
    blocked = client.post('/api/buildings/upgrade', json={'building_type': 'metal_mine', 'queue_position': 1, 'finish_time': 1})
    body = blocked.get_json()
    assert body['ok'] is False
    assert body['reason'] == 'queue_full'

def test_building_cancel_rejects_foreign_job_id(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid_a, uname_a = _create_player()
    uid_b, uname_b = _create_player()
    pid_a = int(get_homeworld(player_id=uid_a)['id'])
    cost_m, cost_c = get_upgrade_cost('metal_mine', 0)
    conn = db()
    conn.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (cost_m + 1000, cost_c + 1000, pid_a))
    conn.commit()
    conn.close()
    client_a = _login_client(app_mod, uname_a)
    queued = client_a.post('/api/buildings/upgrade', json={'building_type': 'metal_mine'})
    job_id = int(queued.get_json()['job']['job_id'])
    client_b = _login_client(app_mod, uname_b)
    cancelled = client_b.post('/api/buildings/cancel', json={'job_id': job_id, 'refund_ratio': 1.0})
    body = cancelled.get_json()
    assert body['ok'] is False
    assert body['reason'] == 'not_found'

def test_research_start_ignores_client_cost_and_enforces_requirements(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_homeworld(player_id=uid)['id'])
    save_planet_buildings(pid, {'research_lab': 1})
    cost_m, cost_c = get_research_cost('energy_tech', 1)
    conn = db()
    conn.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (cost_m + 1000, cost_c + 1000, pid))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    before = _planet_row(pid)
    res = client.post('/api/research/start', json={'tech_key': 'energy_tech', 'cost_metal': 0, 'cost_crystal': 0, 'finish_time': 1, 'level': 99})
    body = res.get_json()
    assert body['ok'] is True
    after = _planet_row(pid)
    assert int(before['metal']) - int(after['metal']) == cost_m
    assert int(before['crystal']) - int(after['crystal']) == cost_c

def test_research_start_rejects_spoofed_level_without_lab(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_homeworld(player_id=uid)['id'])
    conn = db()
    conn.execute('UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;', (pid,))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    res = client.post('/api/research/start', json={'tech_key': 'energy_tech', 'current_level': 99, 'level': 99})
    body = res.get_json()
    assert body['ok'] is False
    assert body['reason'] in ('requirements', 'no_research_lab')

def test_research_cancel_rejects_foreign_job_id(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid_a, uname_a = _create_player()
    _uid_b, uname_b = _create_player()
    pid_a = int(get_homeworld(player_id=uid_a)['id'])
    save_planet_buildings(pid_a, {'research_lab': 1})
    cost_m, cost_c = get_research_cost('energy_tech', 1)
    conn = db()
    conn.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (cost_m + 5000, cost_c + 5000, pid_a))
    conn.commit()
    conn.close()
    client_a = _login_client(app_mod, uname_a)
    started = client_a.post('/api/research/start', json={'tech_key': 'energy_tech'})
    job_id = int(started.get_json()['job']['job_id'])
    client_b = _login_client(app_mod, uname_b)
    cancelled = client_b.post('/api/research/cancel', json={'job_id': job_id})
    assert cancelled.get_json()['ok'] is False

def test_shipyard_build_ignores_client_cost(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_planets_by_player(uid)[0]['id'])
    ship_key = 'spark_drone'
    cost = (get_ship(ship_key) or {}).get('build_cost') or {}
    cost_m = int(cost.get('metal') or 0)
    cost_c = int(cost.get('crystal') or 0)
    conn = db()
    cur = conn.cursor()
    _grant_ship_prereqs(cur, pid, uid)
    cur.execute('UPDATE planets SET metal = ?, crystal = ?, fuel_cells = 5000 WHERE id = ?;', (cost_m + 5000, cost_c + 5000, pid))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    before = _planet_row(pid)
    res = client.post('/api/shipyard/build', json={'ship_key': ship_key, 'amount': 1, 'planet_id': pid, 'cost_metal': 0, 'cost_crystal': 0, 'finish_time': 1})
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    after = _planet_row(pid)
    assert int(before['metal']) - int(after['metal']) == cost_m
    assert int(before['crystal']) - int(after['crystal']) == cost_c

def test_shipyard_build_rejects_tampered_bulk_without_resources(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_planets_by_player(uid)[0]['id'])
    conn = db()
    cur = conn.cursor()
    _grant_ship_prereqs(cur, pid, uid)
    cur.execute('UPDATE planets SET metal = 0, crystal = 0, fuel_cells = 0 WHERE id = ?;', (pid,))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    res = client.post('/api/shipyard/build', json={'ship_key': 'spark_drone', 'amount': 50, 'cost_metal': 0})
    body = res.get_json()
    assert body['ok'] is False
    assert body['error'] == 'not_enough_resources'

def test_exchange_ignores_client_receive_amount_and_rate(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_homeworld(player_id=uid)['id'])
    conn = db()
    conn.execute('UPDATE planets SET metal = 50000, crystal = 0 WHERE id = ?;', (pid,))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    before = _planet_row(pid)
    res = client.post('/api/exchange', json={'direction': 'metal_to_crystal', 'amount': 1000, 'receive_amount': 9999999, 'rate': 99.0})
    body = res.get_json()
    assert body['ok'] is True
    # Score-neutral exchange (GC-SCORE-F) uses rate_metal_to_crystal=1.5, not the
    # old flat 0.85; derive expectation from the canonical preview helper instead
    # of a hardcoded rate (GC-STABILIZE-002). The point of this test — the
    # server ignores the spoofed receive_amount/rate — still holds.
    expected_receive = _preview_receive('metal', 'crystal', 1000, get_exchange_config())
    assert body['job']['receive_amount'] == expected_receive
    after = _planet_row(pid)
    assert int(before['metal']) - int(after['metal']) == 1000
    assert int(after['crystal']) == expected_receive

def test_exchange_rejects_negative_amount_even_with_spoofed_receive(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    _uid, uname = _create_player()
    client = _login_client(app_mod, uname)
    res = client.post('/api/exchange', json={'direction': 'metal_to_crystal', 'amount': -1000, 'receive_amount': 5000})
    body = res.get_json()
    assert body['ok'] is False
    assert body['reason'] == 'invalid_amount'

def test_fleet_send_ignores_client_fuel_cost_and_negative_cargo(security_db, monkeypatch):
    if not fleet_schema_ready(db()):
        pytest.skip('fleet schema not ready')
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_planets_by_player(uid)[0]['id'])
    colony_id = _second_colony(uid)
    conn = db()
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;', (pid,))
    add_planet_ships(pid, uid, {'mule_courier': 5}, conn=conn)
    target = conn.execute('SELECT galaxy, system, position FROM planets WHERE id = ?;', (colony_id,)).fetchone()
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    before = _planet_row(pid)
    res = client.post('/api/fleet/send', json={'mission_type': 'transport', 'origin_planet_id': pid, 'target_galaxy': int(target['galaxy']), 'target_system': int(target['system']), 'target_position': int(target['position']), 'ships': {'mule_courier': 1}, 'resources': {'metal': -5000, 'crystal': -1000, 'fuel_cells': -50}, 'fuel_cost': 0, 'flight_seconds': 1, 'speed_percent': 100})
    body = res.get_json()
    assert body['ok'] is True
    after = _planet_row(pid)
    assert int(after['metal']) >= int(before['metal'])
    assert int(body.get('data', {}).get('fuel_cost') or body.get('fuel_cost') or 0) >= 0
    reported_fuel = body.get('data', {}).get('fuel_cost')
    if reported_fuel is None:
        reported_fuel = body.get('fuel_cost')
    if reported_fuel and int(reported_fuel) > 0:
        assert int(before['fuel_cells']) - int(after['fuel_cells']) >= int(reported_fuel)

def test_fleet_send_rejects_foreign_origin_planet(security_db, monkeypatch):
    if not fleet_schema_ready(db()):
        pytest.skip('fleet schema not ready')
    app_mod = _reload_app(monkeypatch, security_db)
    uid_a, uname_a = _create_player()
    uid_b, _uname_b = _create_player()
    pid_b = int(get_homeworld(player_id=uid_b)['id'])
    colony_a = _second_colony(uid_a)
    conn = db()
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;', (pid_b,))
    add_planet_ships(pid_b, uid_b, {'mule_courier': 3}, conn=conn)
    target = conn.execute('SELECT galaxy, system, position FROM planets WHERE id = ?;', (colony_a,)).fetchone()
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname_a)
    res = client.post('/api/fleet/send', json={'mission_type': 'transport', 'origin_planet_id': pid_b, 'target_galaxy': int(target['galaxy']), 'target_system': int(target['system']), 'target_position': int(target['position']), 'ships': {'mule_courier': 1}, 'resources': {}, 'fuel_cost': 0})
    body = res.get_json()
    assert body['ok'] is False
    assert body.get('error') in ('origin_not_found', 'not_enough_ships', 'generic')

def test_planet_switch_rejects_foreign_planet(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    _uid_a, uname_a = _create_player()
    uid_b, _uname_b = _create_player()
    foreign_pid = int(get_homeworld(player_id=uid_b)['id'])
    client = _login_client(app_mod, uname_a)
    res = client.post('/api/planets/active', json={'planet_id': foreign_pid})
    body = res.get_json()
    assert body['ok'] is False
    assert body['reason'] == 'planet_not_owned'

def test_request_id_does_not_bypass_resource_validation(security_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, security_db)
    uid, uname = _create_player()
    pid = int(get_homeworld(player_id=uid)['id'])
    cost_m, cost_c = get_upgrade_cost('metal_mine', 0)
    conn = db()
    conn.execute('UPDATE planets SET metal = 0, crystal = 0 WHERE id = ?;', (pid,))
    conn.commit()
    conn.close()
    client = _login_client(app_mod, uname)
    payload = {'building_type': 'metal_mine', 'cost_metal': 0, 'request_id': 'tamper-idempotent-1'}
    first = client.post('/api/buildings/upgrade', json=payload)
    assert first.get_json()['ok'] is False
    conn = db()
    conn.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (cost_m + 5000, cost_c + 5000, pid))
    conn.commit()
    conn.close()
    cached = client.post('/api/buildings/upgrade', json=payload)
    assert cached.get_json()['ok'] is False
    fresh = client.post('/api/buildings/upgrade', json={'building_type': 'metal_mine', 'request_id': 'tamper-idempotent-2'})
    assert fresh.get_json()['ok'] is True
