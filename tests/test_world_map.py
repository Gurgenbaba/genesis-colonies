"""GC-571 — Shared world map presence tests."""
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
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.world_map import MIN_CLUSTER_DISTANCE, VIEWER_HOME_X, VIEWER_HOME_Y, WORLD_HEIGHT, WORLD_WIDTH, build_empire_center_map, compute_empire_seed, list_occupied_homeworlds
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def world_map_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'world_map.db'
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
    uname = f'world_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    return (int(user['id']), uname)

def test_compute_empire_seed_is_deterministic():
    a = compute_empire_seed(1, 1, 42)
    b = compute_empire_seed(1, 1, 42)
    c = compute_empire_seed(2, 3, 42)
    assert a == b
    assert a != c

def test_single_player_payload_has_world_metadata(world_map_db):
    from game.db import db
    conn = db()
    try:
        baseline = len(list_occupied_homeworlds(conn=conn))
    finally:
        conn.close()
    player_id, _ = _create_player()
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    assert payload['world']['mode'] == 'shared'
    assert payload['world']['empire_count'] == baseline + 1
    assert payload['world']['world_width'] == WORLD_WIDTH
    assert payload['world']['world_height'] == WORLD_HEIGHT
    assert payload['world']['default_scale'] == 0.62
    hub = next((n for n in payload['nodes'] if n.get('layout_slot') == 'hub' and n.get('cluster_kind') == 'own_cluster'))
    assert hub['world_x'] == VIEWER_HOME_X
    assert hub['world_y'] == VIEWER_HOME_Y
    fields = [n for n in payload['nodes'] if n.get('node_kind') == 'world_field']
    assert len(fields) >= 1

def test_two_players_appear_on_shared_map(world_map_db):
    from game.db import db
    conn = db()
    try:
        baseline = len(list_occupied_homeworlds(conn=conn))
    finally:
        conn.close()
    player_a, user_a = _create_player()
    player_b, user_b = _create_player()
    ok, reason, _ = colonize_planet(player_a, name='Alpha Mine', galaxy=1, system=2, position=3, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    ok, reason, _ = colonize_planet(player_b, name='Beta Lab', galaxy=1, system=3, position=4, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    save_planet_buildings(int(get_homeworld(player_id=player_b)['id']), {'research_lab': 5})
    conn = db()
    try:
        homeworlds = list_occupied_homeworlds(conn=conn)
        assert len(homeworlds) == baseline + 2
        payload_a = build_command_map_payload(player_a, conn=conn)
        payload_b = build_command_map_payload(player_b, conn=conn)
    finally:
        conn.close()
    expected_total = baseline + 2
    assert payload_a['world']['empire_count'] == expected_total
    assert payload_b['world']['empire_count'] == expected_total
    foreign_a = [n for n in payload_a['nodes'] if n.get('node_kind') == 'foreign_empire']
    own_a = [n for n in payload_a['nodes'] if n.get('cluster_kind') == 'own_cluster' and n.get('node_kind') == 'colony']
    assert len(foreign_a) == expected_total - 1
    assert any((n['owner_username'] == user_b for n in foreign_a))
    assert len(own_a) >= 2
    foreign_b = [n for n in payload_b['nodes'] if n.get('node_kind') == 'foreign_empire']
    assert len(foreign_b) == expected_total - 1
    assert any((n['owner_username'] == user_a for n in foreign_b))
    own_hubs = [n for n in payload_a['nodes'] if n.get('cluster_kind') == 'own_cluster' and n.get('layout_slot') == 'hub']
    foreign_hubs = [n for n in payload_a['nodes'] if n.get('node_kind') == 'foreign_empire']
    assert len(own_hubs) == 1
    own_hub = own_hubs[0]
    assert own_hub['world_x'] == VIEWER_HOME_X
    assert own_hub['world_y'] == VIEWER_HOME_Y
    conn = db()
    try:
        centers = build_empire_center_map(list_occupied_homeworlds(conn=conn), player_a)
    finally:
        conn.close()
    center_list = list(centers.values())
    for index, (ax, ay) in enumerate(center_list):
        for bx, by in center_list[index + 1:]:
            dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
            assert dist >= MIN_CLUSTER_DISTANCE - 0.01
    for foreign in foreign_hubs:
        dist = ((own_hub['world_x'] - foreign['world_x']) ** 2 + (own_hub['world_y'] - foreign['world_y']) ** 2) ** 0.5
        assert dist >= MIN_CLUSTER_DISTANCE - 0.01

def test_galaxy_renders_foreign_empire_node(world_map_db, monkeypatch):
    import importlib
    player_a, _ = _create_player()
    _create_player()
    dbmod.DB_PATH = world_map_db
    models.DB_PATH = world_map_db
    import app as app_module
    importlib.reload(app_module)
    uname = f'world_ui_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    client = app_module.app.test_client()
    app_module.app.config['TESTING'] = True
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    body = client.get('/galaxy?view=command_map&dev=1').get_data(as_text=True)
    assert 'data-foreign-empire-inspect' in body
    assert 'galaxy-command-map-node--foreign-empire' in body
    assert 'data-world-mode="shared"' in body
    assert 'data-world-field-inspect' in body
    assert 'data-world-width="4000.0"' in body or 'data-world-width="4000"' in body
    assert 'galaxy-command-map-viewport' in body
