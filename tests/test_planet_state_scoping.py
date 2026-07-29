"""
Planet-scoped gameplay state: build queue, resources, rename, planet switch.

Run: python -m pytest tests/test_planet_state_scoping.py -v
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.buildings import queue_build_for_planet
from game.db import db
from game.logic import get_build_queue_status, queue_build
from game.models import create_user, get_homeworld, get_planet_buildings, init_db, load_player, save_planet_buildings
from game.options import get_options_snapshot, update_active_planet_name, delete_active_planet
from game.planet_evolution.repository import set_active_planet_id
from game.planet_evolution.service import colonize_planet, set_active_planet
from game.player_display import commander_display_name, commander_lookup_name
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def scoped_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'planet_scope.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_file))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    monkeypatch.setattr(dbmod, 'DB_PATH', db_file)
    monkeypatch.setattr(models, 'DB_PATH', db_file)
    env = os.environ.copy()
    env['GC_DB_PATH'] = str(db_file)
    result = subprocess.run([sys.executable, str(MIGRATE_SCRIPT)], cwd=str(ROOT), capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()
    from game.bootstrap import bootstrap_application
    bootstrap_application(skip_migration_check=True)
    yield db_file

def _create_player() -> tuple[int, str]:
    uname = f'scope_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    uid = int(user['id'])
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from conftest import unlock_colony_slots
    conn = db()
    try:
        unlock_colony_slots(conn, int(get_homeworld(player_id=uid)['id']), slots=1)
    finally:
        conn.close()
    return (uid, uname)

def _second_planet(player_id: int) -> int:
    ok, reason, extra = colonize_planet(player_id, name=f'Colony_{uuid.uuid4().hex[:4]}', galaxy=1, system=300, position=2, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    return int(extra['planet_id'])

def test_build_queues_isolated_per_planet(scoped_db):
    player_id, _ = _create_player()
    hw = get_homeworld(player_id=player_id)
    colony_id = _second_planet(player_id)
    save_planet_buildings(int(hw['id']), {'metal_mine': 1, 'solar_plant': 1})
    save_planet_buildings(int(colony_id), {'metal_mine': 1, 'solar_plant': 1})
    conn = db()
    conn.execute('UPDATE planets SET metal = 50000, crystal = 50000 WHERE player_id = ?;', (player_id,))
    conn.commit()
    hw_row = dict(conn.execute('SELECT * FROM planets WHERE id = ?;', (int(hw['id']),)).fetchone())
    col_row = dict(conn.execute('SELECT * FROM planets WHERE id = ?;', (colony_id,)).fetchone())
    hw_buildings = get_planet_buildings(int(hw['id']), conn=conn)
    col_buildings = get_planet_buildings(colony_id, conn=conn)
    ok_hw, _, _ = queue_build_for_planet(hw_row, hw_buildings, 'metal_mine', user_id=player_id)
    assert ok_hw
    set_active_planet_id(player_id, colony_id, conn)
    conn.commit()
    conn.close()
    colony_queue = get_build_queue_status(player_id, skip_finish=True)
    assert colony_queue.get('queue') == [] or len(colony_queue.get('queue', [])) == 0
    conn = db()
    set_active_planet_id(player_id, int(hw['id']), conn)
    conn.commit()
    conn.close()
    hw_queue = get_build_queue_status(player_id, skip_finish=True)
    assert len(hw_queue.get('queue', [])) >= 1

def test_resources_isolated_per_planet(scoped_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    colony_id = _second_planet(player_id)
    conn = db()
    conn.execute('UPDATE planets SET metal = 100, crystal = 50 WHERE id = ?;', (hw_id,))
    conn.execute('UPDATE planets SET metal = 9000, crystal = 8000 WHERE id = ?;', (colony_id,))
    conn.commit()
    conn.close()
    conn = db()
    set_active_planet_id(player_id, colony_id, conn)
    conn.commit()
    row = conn.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (colony_id,)).fetchone()
    conn.close()
    assert float(row['metal']) == 9000.0
    assert float(row['crystal']) == 8000.0
    conn = db()
    set_active_planet_id(player_id, hw_id, conn)
    conn.commit()
    row = conn.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (hw_id,)).fetchone()
    conn.close()
    assert float(row['metal']) == 100.0
    assert float(row['crystal']) == 50.0

def test_planet_rename_uses_active_planet(scoped_db):
    player_id, _ = _create_player()
    hw = get_homeworld(player_id=player_id)
    colony_id = _second_planet(player_id)
    conn = db()
    set_active_planet_id(player_id, colony_id, conn)
    conn.commit()
    conn.close()
    new_name = f'Active_{uuid.uuid4().hex[:6]}'
    ok, err, data = update_active_planet_name(player_id, new_name)
    assert ok, err
    assert data['planet_id'] == colony_id
    assert data['active_planet_name'] == new_name
    conn = db()
    hw_name = conn.execute('SELECT name FROM planets WHERE id = ?;', (int(hw['id']),)).fetchone()[0]
    col_name = conn.execute('SELECT name FROM planets WHERE id = ?;', (colony_id,)).fetchone()[0]
    conn.close()
    assert col_name == new_name
    assert hw_name != new_name

def test_commander_label_does_not_mutate_player_name(scoped_db):
    raw = 'StellarNova'
    player_id, _ = _create_player()
    conn = db()
    conn.execute('UPDATE players SET name = ? WHERE id = ?;', (raw, player_id))
    conn.commit()
    conn.close()
    assert commander_display_name(raw) == raw
    assert commander_lookup_name(raw) == raw
    assert commander_display_name('Commander StellarNova') == 'Commander StellarNova'

def test_game_state_follows_active_planet_switch(scoped_db, monkeypatch):
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.app.config['TESTING'] = True
    app_mod.app.config['WTF_CSRF_ENABLED'] = False
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    colony_id = _second_planet(player_id)
    save_planet_buildings(hw_id, {'metal_mine': 3, 'solar_plant': 2})
    save_planet_buildings(colony_id, {'metal_mine': 8, 'solar_plant': 2})
    client = app_mod.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    ok, reason = set_active_planet(player_id, colony_id)
    assert ok, reason
    r_colony = client.get('/api/game-state')
    assert r_colony.status_code == 200
    body_colony = r_colony.get_json()
    assert body_colony['active_planet_id'] == colony_id
    assert int(body_colony['buildings']['metal_mine']) == 8
    set_active_planet(player_id, hw_id)
    r_hw = client.get('/api/game-state')
    body_hw = r_hw.get_json()
    assert body_hw['active_planet_id'] == hw_id
    assert int(body_hw['buildings']['metal_mine']) == 3

def test_game_state_build_queue_follows_active_planet(scoped_db, monkeypatch):
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    app_mod.app.config['TESTING'] = True
    app_mod.app.config['WTF_CSRF_ENABLED'] = False
    player_id, uname = _create_player()
    hw = get_homeworld(player_id=player_id)
    hw_id = int(hw['id'])
    colony_id = _second_planet(player_id)
    save_planet_buildings(hw_id, {'metal_mine': 1, 'solar_plant': 1})
    save_planet_buildings(colony_id, {'metal_mine': 1, 'solar_plant': 1})
    conn = db()
    conn.execute('UPDATE planets SET metal = 99999, crystal = 99999 WHERE player_id = ?;', (player_id,))
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    set_active_planet(player_id, colony_id)
    player = load_player(player_id)
    buildings = get_planet_buildings(colony_id)
    ok, reason, _ = queue_build(player, buildings, 'metal_mine')
    assert ok, reason
    r_colony = client.get('/api/game-state')
    body_colony = r_colony.get_json()
    assert body_colony['active_planet_id'] == colony_id
    assert int(body_colony['build_queue']['planet_id']) == colony_id
    assert len(body_colony['build_queue']['queue']) >= 1
    set_active_planet(player_id, hw_id)
    r_hw = client.get('/api/game-state')
    body_hw = r_hw.get_json()
    assert body_hw['active_planet_id'] == hw_id
    assert int(body_hw['build_queue']['planet_id']) == hw_id
    assert body_hw['build_queue']['queue'] == []

def test_queue_build_targets_active_planet(scoped_db):
    player_id, _ = _create_player()
    hw = get_homeworld(player_id=player_id)
    colony_id = _second_planet(player_id)
    save_planet_buildings(colony_id, {'metal_mine': 1, 'solar_plant': 1, 'crystal_mine': 0})
    conn = db()
    conn.execute('UPDATE planets SET metal = 99999, crystal = 99999 WHERE id = ?;', (colony_id,))
    set_active_planet_id(player_id, colony_id, conn)
    conn.commit()
    conn.close()
    player = load_player(player_id)
    buildings = get_planet_buildings(colony_id)
    ok, reason, _ = queue_build(player, buildings, 'metal_mine')
    assert ok, reason
    conn = db()
    cur = conn.cursor()
    cur.execute('SELECT planet_id FROM build_queue WHERE planet_id IN (?, ?);', (int(hw['id']), colony_id))
    rows = cur.fetchall()
    conn.close()
    planet_ids = {int(r['planet_id']) for r in rows}
    assert colony_id in planet_ids
    assert int(hw['id']) not in planet_ids

def test_delete_active_colony_switches_to_homeworld(scoped_db):
    player_id, _ = _create_player()
    hw = get_homeworld(player_id=player_id)
    hw_id = int(hw['id'])
    colony_id = _second_planet(player_id)
    conn = db()
    set_active_planet_id(player_id, colony_id, conn)
    conn.commit()
    conn.close()
    ok, err, data = delete_active_planet(player_id)
    assert ok, err
    assert data['active_planet_id'] == hw_id
    conn = db()
    cur = conn.cursor()
    cur.execute('SELECT id FROM planets WHERE id = ?;', (colony_id,))
    assert cur.fetchone() is None
    conn.close()

def test_delete_homeworld_rejected(scoped_db):
    player_id, _ = _create_player()
    ok, err, _ = delete_active_planet(player_id)
    assert not ok
    assert err == 'planet_error_cannot_delete_homeworld'
