"""GC-570 — World map role-based location actions."""
from __future__ import annotations
import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.models import create_user, get_homeworld, init_db, save_planet_buildings
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.location_actions import ROLE_LOCATION_ACTIONS, build_location_actions
from game.planet_evolution.service import colonize_planet
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def location_actions_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'location_actions.db'
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

def _create_player() -> int:
    uname = f'loc_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    return int(user['id'])

def test_build_location_actions_mining_colony():
    actions = build_location_actions('mining')
    keys = [a['action_key'] for a in actions]
    assert keys == ['mines', 'storage', 'defense', 'trade']
    assert actions[0]['href'] == '/buildings'
    assert actions[0]['label_key'] == 'location_action_mines'

def test_build_location_actions_homeworld():
    actions = build_location_actions('homeworld')
    keys = [a['action_key'] for a in actions]
    assert 'overview' in keys
    assert 'evolution' in keys
    assert 'shipyard' in keys
    assert 'fleet' in keys
    assert 'defense' in keys
    assert 'trade' in keys
    assert 'logistics' in keys
    assert any((a['href'] == '/planet-evolution' for a in actions))
    assert any((a['href'] == '/logistics' for a in actions))

def test_build_location_actions_homeworld_overrides_colony_role():
    actions = build_location_actions('mining', is_homeworld=True)
    keys = [a['action_key'] for a in actions]
    assert keys[0] == 'overview'
    assert 'mines' not in keys
    assert 'shipyard' in keys

def test_build_location_actions_shipyard_colony():
    actions = build_location_actions('shipyard')
    keys = [a['action_key'] for a in actions]
    assert keys[:3] == ['shipyard', 'fleet', 'defense']

def test_all_roles_have_actions():
    for role in ('homeworld', 'mining', 'research', 'shipyard', 'fortress', 'trade', 'frontier', 'general'):
        assert role in ROLE_LOCATION_ACTIONS
        assert len(build_location_actions(role)) >= 2

def test_command_map_colony_nodes_include_actions(location_actions_db):
    player_id = _create_player()
    ok, reason, mining = colonize_planet(player_id, name='Ore World', galaxy=1, system=2, position=3, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    save_planet_buildings(int(mining['planet_id']), {'metal_mine': 8, 'crystal_mine': 6})
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    colonies = [n for n in payload['nodes'] if n.get('node_kind') == 'colony']
    assert len(colonies) >= 2
    mining_node = next((n for n in colonies if int(n.get('planet_id') or 0) == int(mining['planet_id'])))
    assert mining_node.get('actions')
    assert mining_node['actions'][0]['action_key'] == 'mines'
    hw = next((n for n in colonies if n.get('empire_role_key') == 'homeworld'))
    assert any((a['action_key'] == 'evolution' for a in hw['actions']))

def test_galaxy_default_is_system_view(location_actions_db, monkeypatch):
    import importlib
    dbmod.DB_PATH = location_actions_db
    models.DB_PATH = location_actions_db
    import app as app_module
    importlib.reload(app_module)
    uname = f'loc_ui_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = int(user['id'])
    body = client.get('/galaxy').get_data(as_text=True)
    assert 'galaxy-slot-card' in body
    assert 'galaxy-view-tabs' not in body
    assert 'galaxy-view-tab--classic' not in body
    assert 'data-command-map-graph' not in body
    assert 'galaxy-view-tab--world' not in body

def test_classic_galaxy_still_reachable(location_actions_db, monkeypatch):
    import importlib
    dbmod.DB_PATH = location_actions_db
    models.DB_PATH = location_actions_db
    import app as app_module
    importlib.reload(app_module)
    uname = f'loc_cls_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    client = app_module.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    body = client.get('/galaxy?view=system').get_data(as_text=True)
    assert 'galaxy-slot-card' in body
    assert 'galaxy-view-tabs' not in body
    assert 'galaxy-view-tab--classic' not in body
    assert 'data-command-map-graph' not in body
