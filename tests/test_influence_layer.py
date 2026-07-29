"""GC-566 — Influence territory layer on Command Map."""
from __future__ import annotations
import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.models import create_user, get_homeworld, init_db
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.influence_layer import build_influence_payload, select_influence_nodes
from game.planet_evolution.service import colonize_planet
from game.models import save_planet_buildings
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def influence_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'influence.db'
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
    uname = f'infl_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    uid = int(user['id'])
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from conftest import unlock_colony_slots
    conn = dbmod.db()
    try:
        unlock_colony_slots(conn, int(get_homeworld(player_id=uid)['id']), slots=2)
    finally:
        conn.close()
    return uid

def test_influence_homeworld_only_blob(influence_db):
    player_id = _create_player()
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    influence = payload['influence']
    assert influence['visible'] is True
    assert influence['svg_path'].startswith('M ')
    assert influence['svg_path'].endswith('Z')
    assert len(influence['node_keys']) == 1
    assert len(influence['points']) == 1
    assert influence['points'][0]['is_homeworld'] is True

def test_influence_includes_colonies_not_gates_or_sites(influence_db):
    player_id = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    ok, reason, mining = colonize_planet(player_id, name='Ore Belt', galaxy=1, system=2, position=3, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    ok, reason, research = colonize_planet(player_id, name='Lab Prime', galaxy=1, system=3, position=4, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    save_planet_buildings(int(mining['planet_id']), {'metal_mine': 8, 'crystal_mine': 6})
    save_planet_buildings(int(research['planet_id']), {'research_lab': 9})
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    influence = payload['influence']
    colony_nodes = [n for n in payload['nodes'] if n.get('node_kind') == 'colony']
    assert len(colony_nodes) == 3
    assert len(influence['node_keys']) == 3
    assert all((key.startswith('planet:') for key in influence['node_keys']))
    assert f'planet:{hw_id}' in influence['node_keys']
    selected = select_influence_nodes(payload['nodes'])
    kinds = {n.get('node_kind') for n in payload['nodes'] if n.get('node_key') in influence['node_keys']}
    assert kinds == {'colony'}
    assert not any((n.get('node_kind') == 'expansion_site' for n in payload['nodes'] if n.get('node_key') in influence['node_keys']))
    assert not any((n.get('node_kind') == 'chokepoint' for n in payload['nodes'] if n.get('node_key') in influence['node_keys']))
    assert len(selected) == 3
    assert all((row.get('is_own') for row in influence['points']))

def test_build_influence_payload_empty_nodes():
    payload = build_influence_payload([])
    assert payload['visible'] is False
    assert payload['svg_path'] == ''
    assert payload['node_keys'] == []

def test_galaxy_command_map_renders_influence_layer(influence_db, monkeypatch):
    import importlib
    dbmod.DB_PATH = influence_db
    models.DB_PATH = influence_db
    import app as app_module
    importlib.reload(app_module)
    uname = f'infl_ui_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    player_id = int(user['id'])
    from conftest import unlock_colony_slots
    conn = dbmod.db()
    try:
        unlock_colony_slots(conn, int(get_homeworld(player_id=player_id)['id']), slots=1)
    finally:
        conn.close()
    ok, reason, _ = colonize_planet(player_id, name='Rim Outpost', galaxy=1, system=4, position=5, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    client = app_module.app.test_client()
    app_module.app.config['TESTING'] = True
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    body = client.get('/galaxy?view=command_map&dev=1').get_data(as_text=True)
    assert 'galaxy-command-map-influence' in body
    assert 'galaxy-command-map-influence-blob' in body
    assert 'galaxy-command-map-sector-layer' in body
    assert 'galaxy-command-map-node--chokepoint' in body
