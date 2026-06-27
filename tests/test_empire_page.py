"""
GC-620A — Empire context aggregator.
GC-620B — Empire route, template shell, nav link.

Run: python -m pytest tests/test_empire_page.py -v
"""
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
from game.db import db
from game.empire_page import build_empire_context
from game.models import create_user, get_homeworld, get_planet_buildings, init_db, save_planet_buildings
from game.planet_evolution.service import colonize_planet
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'
BASE_TEMPLATE = ROOT / 'templates' / 'base.html'

@pytest.fixture()
def empire_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'empire_page.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_file))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-not-default-value-32chars')
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

def _login_client(empire_db, monkeypatch):
    dbmod.DB_PATH = empire_db
    models.DB_PATH = empire_db
    import app as app_module
    importlib.reload(app_module)
    uname = f'empire_route_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    client = app_module.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    return (client, int(user['id']), app_module)

def _create_player() -> int:
    uname = f'empire_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    return int(user['id'])

def _second_planet(player_id: int) -> int:
    ok, reason, extra = colonize_planet(player_id, name=f'Colony_{uuid.uuid4().hex[:4]}', galaxy=1, system=310, position=4, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    return int(extra['planet_id'])

def test_build_empire_context_single_homeworld(empire_db):
    player_id = _create_player()
    ctx = build_empire_context(player_id)
    assert ctx['commander']['id'] == player_id
    assert ctx['colony_count'] == 1
    assert ctx['colony_limit']['current'] == 1
    assert len(ctx['colonies']) == 1
    colony = ctx['colonies'][0]
    assert colony['is_homeworld'] is True
    assert 'coordinates' in colony
    assert 'display' in colony['coordinates']
    assert 'production_per_hour' in colony
    assert 'energy' in colony
    assert 'storage' in colony
    assert 'storage_fill' in colony
    assert 'planet_score' in colony
    assert ctx['production']['metal'] == colony['production_per_hour']['metal']
    assert ctx['energy']['total'] == colony['energy']['total']
    assert ctx['rankings']['strongest_colony']['planet_id'] == colony['planet_id']

def test_build_empire_context_aggregates_multiple_colonies(empire_db):
    player_id = _create_player()
    hw = get_homeworld(player_id=player_id)
    colony_id = _second_planet(player_id)
    save_planet_buildings(int(hw['id']), {'metal_mine': 5, 'crystal_mine': 2, 'solar_plant': 4})
    save_planet_buildings(int(colony_id), {'metal_mine': 10, 'crystal_mine': 1, 'solar_plant': 6})
    ctx = build_empire_context(player_id)
    assert ctx['colony_count'] == 2
    by_id = {c['planet_id']: c for c in ctx['colonies']}
    hw_ctx = by_id[int(hw['id'])]
    col_ctx = by_id[colony_id]
    assert ctx['production']['metal'] == hw_ctx['production_per_hour']['metal'] + col_ctx['production_per_hour']['metal']
    assert ctx['production']['crystal'] == hw_ctx['production_per_hour']['crystal'] + col_ctx['production_per_hour']['crystal']
    assert ctx['energy']['total'] == hw_ctx['energy']['total'] + col_ctx['energy']['total']
    assert ctx['energy']['used'] == hw_ctx['energy']['used'] + col_ctx['energy']['used']
    assert ctx['rankings']['highest_metal_production']['planet_id'] == colony_id
    assert ctx['rankings']['highest_crystal_production']['planet_id'] == int(hw['id'])

def test_build_empire_context_only_own_colonies(empire_db):
    player_a = _create_player()
    player_b = _create_player()
    _second_planet(player_b)
    ctx_a = build_empire_context(player_a)
    ctx_b = build_empire_context(player_b)
    assert ctx_a['colony_count'] == 1
    assert ctx_b['colony_count'] == 2
    for colony in ctx_a['colonies']:
        assert colony['planet_id'] == int(get_homeworld(player_id=player_a)['id'])

def test_build_empire_context_largest_storage_ranking(empire_db):
    player_id = _create_player()
    hw = get_homeworld(player_id=player_id)
    colony_id = _second_planet(player_id)
    save_planet_buildings(int(hw['id']), {'metal_storage': 1, 'crystal_storage': 1, 'fuel_storage': 1})
    save_planet_buildings(int(colony_id), {'metal_storage': 8, 'crystal_storage': 8, 'fuel_storage': 8})
    ctx = build_empire_context(player_id)
    assert ctx['rankings']['largest_storage']['planet_id'] == colony_id

def test_build_empire_context_production_via_effect_resolver(empire_db):
    player_id = _create_player()
    hw = get_homeworld(player_id=player_id)
    save_planet_buildings(int(hw['id']), {'metal_mine': 0, 'solar_plant': 0})
    ctx_idle = build_empire_context(player_id)
    idle_metal = ctx_idle['production']['metal']
    save_planet_buildings(int(hw['id']), {'metal_mine': 8, 'solar_plant': 10})
    ctx_active = build_empire_context(player_id)
    assert ctx_active['production']['metal'] > idle_metal
    assert ctx_active['colonies'][0]['production_per_hour']['metal'] > 0

def test_build_empire_context_no_ranking_leak_fields(empire_db):
    player_id = _create_player()
    ctx = build_empire_context(player_id)
    colony = ctx['colonies'][0]
    assert 'metal_production' not in colony
    assert 'storage_total' not in colony
    assert 'matrix_data' not in colony

def test_empire_route_requires_login(empire_db, monkeypatch):
    dbmod.DB_PATH = empire_db
    models.DB_PATH = empire_db
    import app as app_module
    importlib.reload(app_module)
    client = app_module.app.test_client()
    res = client.get('/empire', follow_redirects=False)
    assert res.status_code in (302, 303)
    assert '/login' in (res.headers.get('Location') or '')

def test_empire_route_renders_single_colony(empire_db, monkeypatch):
    client, player_id, _app = _login_client(empire_db, monkeypatch)
    hw = get_homeworld(player_id=player_id)
    hw_name = str(hw.get('name') or '')
    res = client.get('/empire')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="empire-page"' in html
    assert hw_name in html
    assert 'empire-matrix-colony-head' in html
    assert 'empire-colony-card' not in html
    assert 'empire-colonies-section' not in html
    assert 'href="/empire"' in html
    assert 'active' in html

def test_empire_route_renders_multiple_colonies(empire_db, monkeypatch):
    client, player_id, _app = _login_client(empire_db, monkeypatch)
    colony_id = _second_planet(player_id)
    conn = db()
    col_name = conn.execute('SELECT name FROM planets WHERE id = ?;', (colony_id,)).fetchone()['name']
    conn.close()
    res = client.get('/empire')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert html.count('class="empire-matrix-colony-head"') == 2
    assert 'empire-colony-card' not in html
    assert str(col_name) in html

def test_empire_route_pjax_compatible(empire_db, monkeypatch):
    client, _player_id, _app = _login_client(empire_db, monkeypatch)
    res = client.get('/empire', headers={'X-PJAX': 'true', 'X-Requested-With': 'XMLHttpRequest'})
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="empire-page"' in html

def test_empire_nav_link_in_base_template():
    tpl = BASE_TEMPLATE.read_text(encoding='utf-8')
    assert "url_for('empire_view')" in tpl
    assert '{{ T("nav_empire"' in tpl

def test_build_empire_context_includes_matrix(empire_db):
    player_id = _create_player()
    ctx = build_empire_context(player_id)
    matrix = ctx.get('matrix') or {}
    assert matrix.get('sections')
    assert matrix.get('colonies')
    assert matrix.get('colony_values')
    assert len(matrix.get('colonies') or []) == 1
    assert len(matrix.get('colony_values') or []) == 1
    section_keys = {s['key'] for s in matrix['sections']}
    assert 'resources' in section_keys
    assert 'production' in section_keys
    assert 'buildings' in section_keys
    assert 'account_research' in section_keys
    assert 'defense' in section_keys
    assert 'ships' in section_keys
    colony_data = matrix['colony_values'][0]
    assert 'metal_mine' in colony_data['buildings']
    assert colony_data['production']['metal_day'] == colony_data['production']['metal'] * 24
    assert 'matrix_data' not in ctx['colonies'][0]
    assert 'energy_tech' in matrix['account_values']

def test_build_empire_context_matrix_totals_multiple_colonies(empire_db):
    player_id = _create_player()
    hw = get_homeworld(player_id=player_id)
    colony_id = _second_planet(player_id)
    save_planet_buildings(int(hw['id']), {'metal_mine': 5, 'solar_plant': 4})
    save_planet_buildings(int(colony_id), {'metal_mine': 8, 'solar_plant': 6, 'orbital_shipyard': 2})
    ctx = build_empire_context(player_id)
    matrix = ctx['matrix']
    assert len(matrix['colonies']) == 2
    prod_total = matrix['totals']['production']['metal']
    row_sum = sum((v['production']['metal'] for v in matrix['colony_values']))
    assert prod_total == row_sum
    assert matrix['colony_values'][1]['buildings']['orbital_shipyard'] == 2
    assert matrix['totals']['buildings']['metal_mine'] == matrix['colony_values'][0]['buildings']['metal_mine'] + matrix['colony_values'][1]['buildings']['metal_mine']

def test_build_empire_context_matrix_building_and_ship_rows(empire_db):
    player_id = _create_player()
    hw = get_homeworld(player_id=player_id)
    from game.fleet import add_planet_ships
    save_planet_buildings(int(hw['id']), {'metal_mine': 3, 'defense_factory': 1})
    conn = db()
    add_planet_ships(int(hw['id']), player_id, {'spark_drone': 2}, conn=conn)
    conn.commit()
    conn.close()
    matrix = build_empire_context(player_id)['matrix']
    data = matrix['colony_values'][0]
    assert data['buildings']['metal_mine'] == 3
    assert data['ships']['spark_drone'] == 2

def test_empire_template_polished_structure(empire_db, monkeypatch):
    client, _player_id, _app = _login_client(empire_db, monkeypatch)
    html = client.get('/empire').get_data(as_text=True)
    assert 'empire-prod-panel' in html
    assert 'empire-prod-card--energy' in html
    assert 'empire-colony-card' not in html
    assert 'empire-colonies-section' not in html
    assert 'Energie-Surplus' in html or 'Energy surplus' in html
    assert 'empire-matrix-panel' in html
    assert 'empire-matrix--full' in html
    assert 'empire-matrix-colony-header-row' in html
    assert 'empire-matrix-section-row' in html
    assert 'data-empire-section-toggle' in html
    assert 'empire-matrix-scroll' in html
    assert 'building_metal_mine' in html or 'Ferronit-Mine' in html
