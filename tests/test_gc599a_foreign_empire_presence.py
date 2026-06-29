"""GC-599A — Foreign Empire Presence tests."""
from __future__ import annotations
import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.influence_layer import build_foreign_influence_payloads
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.world_map import format_empire_display_name
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def presence_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc599a.db'
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
    uname = f'emp_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    return (int(user['id']), uname)

def test_format_empire_display_name():
    assert format_empire_display_name('papa-fanti', 'Papa Prime') == 'PAPA FANTI'
    assert format_empire_display_name('', 'Aurora Prime') == 'AURORA PRIME EMPIRE'

def test_foreign_empire_hub_has_presence_metadata(presence_db):
    viewer_id, _ = _create_player()
    other_id, other_name = _create_player()
    ok, reason, _ = colonize_planet(other_id, name='Aurora Mining', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    ok, reason, _ = colonize_planet(other_id, name='Aurora Research', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    ok, reason, _ = colonize_planet(other_id, name='Aurora Frontier', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(viewer_id, conn=conn)
    finally:
        conn.close()
    foreign_hubs = [n for n in payload['nodes'] if n.get('node_kind') == 'foreign_empire' and int(n.get('owner_player_id') or 0) == other_id]
    assert len(foreign_hubs) == 1
    hub = foreign_hubs[0]
    assert hub['empire_display_name'] == other_name.upper()
    assert hub['homeworld_name']
    assert hub['influence_pct'] >= 18
    assert hub['colony_count'] >= 3
    foreign_colonies = [n for n in payload['nodes'] if n.get('node_kind') == 'foreign_colony' and int(n.get('owner_player_id') or 0) == other_id]
    assert 1 <= len(foreign_colonies) <= 2
    foreign_blobs = build_foreign_influence_payloads(payload['nodes'])
    owner_blobs = [b for b in foreign_blobs if int(b.get('owner_player_id') or 0) == other_id]
    assert len(owner_blobs) == 1
    assert owner_blobs[0]['svg_path'].startswith('M ')
    assert owner_blobs[0]['fill_rgba'].startswith('rgba(')

def test_galaxy_renders_foreign_presence_layer(presence_db, monkeypatch):
    viewer_id, _ = _create_player()
    other_id, _ = _create_player()
    ok, reason, _ = colonize_planet(other_id, name='Rival Mining', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    dbmod.DB_PATH = presence_db
    models.DB_PATH = presence_db
    import app as app_module
    importlib.reload(app_module)
    uname = f'map_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    client = app_module.app.test_client()
    app_module.app.config['TESTING'] = True
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    body = client.get('/galaxy?view=command_map&dev=1').get_data(as_text=True)
    assert 'galaxy-command-map-influence-blob--foreign' in body
    assert 'data-homeworld-name=' in body
    assert 'data-empire-name=' in body
    assert 'galaxy-command-map-node-empire-label' in body
    assert 'data-foreign-colony-hover' in body
    assert 'gc-world-inspector-shell--foreign-presence' not in body
