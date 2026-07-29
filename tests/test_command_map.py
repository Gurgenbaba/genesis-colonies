"""GC-563 — Command Map graph tests."""
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
from game.planet_evolution.service import colonize_planet, create_trade_route
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def command_map_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'command_map.db'
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
    uname = f'cmdmap_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    return int(user['id'])


def _unlock_colony_slots(player_id: int, slots: int) -> None:
    """GC-976A: colonize_planet() needs an unlocked evolution slot. Applied
    per-test (not in `_create_player`) since `test_homeworld_is_hub_center`
    relies on a fresh, un-leveled homeworld to assert `frontier_ix` is
    still locked."""
    from conftest import unlock_colony_slots
    conn = dbmod.db()
    try:
        unlock_colony_slots(conn, int(get_homeworld(player_id=player_id)['id']), slots=slots)
    finally:
        conn.close()

def test_homeworld_is_hub_center(command_map_db):
    player_id = _create_player()
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    nodes = payload['nodes']
    colonies = [n for n in nodes if n.get('node_kind', 'colony') == 'colony']
    expansion = [n for n in nodes if n.get('node_kind') == 'expansion_site']
    assert len(colonies) == 1
    assert len(expansion) == 5
    hub = next((n for n in colonies if n.get('empire_role_key') == 'homeworld'))
    assert hub['layout_slot'] == 'hub'
    assert hub['cluster_kind'] == 'own_cluster'
    assert hub['region_key'] == 'genesis_core'
    assert hub['empire_role_key'] == 'homeworld'
    assert 'world_x' in hub and 'world_y' in hub
    assert payload['world']['mode'] == 'shared'
    frontier = next((n for n in expansion if n['site_key'] == 'frontier_ix'))
    assert frontier['region_key'] == 'outer_rim'
    assert frontier['is_locked'] is True
    assert len(payload['regions']) == 4

def test_colony_roles_get_spoke_slots(command_map_db):
    player_id = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    _unlock_colony_slots(player_id, slots=2)
    ok, reason, mining = colonize_planet(player_id, name='Vega Prime', galaxy=1, system=2, position=3, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    ok, reason, research = colonize_planet(player_id, name='Helios Gate', galaxy=1, system=3, position=4, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    save_planet_buildings(int(mining['planet_id']), {'metal_mine': 8, 'crystal_mine': 6})
    save_planet_buildings(int(research['planet_id']), {'research_lab': 9, 'academy': 3})
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    by_id = {int(n['planet_id']): n for n in payload['nodes'] if n.get('node_kind', 'colony') == 'colony'}
    hub = by_id[hw_id]
    mining_node = by_id[int(mining['planet_id'])]
    research_node = by_id[int(research['planet_id'])]
    assert hub['layout_slot'] == 'hub'
    assert hub['region_key'] == 'genesis_core'
    assert mining_node['layout_slot'] == 'mining'
    assert research_node['layout_slot'] == 'research'
    assert mining_node['layout_radius_world'] >= 250
    assert research_node['layout_radius_world'] >= 250

    def dist_from_hub(node):
        return ((float(node['world_x']) - float(hub['world_x'])) ** 2 + (float(node['world_y']) - float(hub['world_y'])) ** 2) ** 0.5
    assert dist_from_hub(mining_node) >= 250
    assert dist_from_hub(research_node) >= 250
    frontier = next((n for n in payload['nodes'] if n.get('site_key') == 'frontier_ix'))
    assert dist_from_hub(frontier) >= 600
    assert dist_from_hub(frontier) > dist_from_hub(mining_node) + 200

def test_trade_route_creates_edge(command_map_db):
    player_id = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    _unlock_colony_slots(player_id, slots=1)
    ok, reason, mining = colonize_planet(player_id, name='Titan Forge', galaxy=1, system=4, position=5, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    colony_id = int(mining['planet_id'])
    save_planet_buildings(colony_id, {'orbital_shipyard': 6})
    ok, reason, _ = create_trade_route(player_id, hw_id, colony_id, 'metal', 10.0)
    assert ok, reason
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    trade_edges = [e for e in payload['edges'] if e['edge_type'] == 'trade_route']
    assert len(trade_edges) >= 1
    edge = trade_edges[0]
    assert {edge['source_planet_id'], edge['target_planet_id']} == {hw_id, colony_id}
    assert edge['resource_key'] == 'metal'
    assert 'source_x_pct' in edge and 'target_y_pct' in edge

def test_hub_link_for_unconnected_colony(command_map_db):
    player_id = _create_player()
    _unlock_colony_slots(player_id, slots=1)
    ok, reason, _ = colonize_planet(player_id, name='Outpost', galaxy=1, system=5, position=6, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    from game.db import db
    conn = db()
    try:
        payload = build_command_map_payload(player_id, conn=conn)
    finally:
        conn.close()
    hub_links = [e for e in payload['edges'] if e['edge_type'] == 'hub_link']
    assert len(hub_links) >= 1

def test_galaxy_command_map_renders_graph_not_list(command_map_db, monkeypatch):
    import importlib
    dbmod.DB_PATH = command_map_db
    models.DB_PATH = command_map_db
    import app as app_module
    importlib.reload(app_module)
    app_module.app.config['TESTING'] = True
    uname = f'cmdmap_ui_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    player_id = int(user['id'])
    _unlock_colony_slots(player_id, slots=1)
    ok, reason, _ = colonize_planet(player_id, name='Spoke', galaxy=1, system=6, position=7, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    client = app_module.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    body = client.get('/galaxy?view=command_map&dev=1').get_data(as_text=True)
    assert 'galaxy-command-map-graph' in body
    assert 'galaxy-command-map-edges' in body
    assert 'galaxy-command-map-node--hub' in body
    assert 'data-command-map-viewport' in body
    assert 'data-command-map-canvas' in body
    assert 'data-command-map-reset' in body
    assert 'galaxy-command-map-viewport' in body
    assert 'galaxy-command-map-sector-layer' in body
    assert 'galaxy-command-map-region-panel' not in body
    assert 'galaxy-command-map-list' not in body
    assert 'galaxy-slots' not in body
