"""GC-591B — Mobile role-based navigation sync."""
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
from game.models import create_user, init_db, save_planet_buildings
from game.planet_evolution.service import colonize_planet, set_active_planet
from game.planet_evolution.sidebar_nav import mobile_bottom_modules, mobile_drawer_shows_module, module_display_section, resolve_sidebar_nav
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def gc591b_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc591b.db'
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
    uname = f'gc591b_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    uid = int(user['id'])
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from game.models import get_homeworld
    from conftest import unlock_colony_slots
    conn = dbmod.db()
    try:
        unlock_colony_slots(conn, int(get_homeworld(player_id=uid)['id']), slots=1)
    finally:
        conn.close()
    return (uid, uname)

def _app_client(monkeypatch):
    import app as app_mod
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_mod)
    app_mod.app.config['TESTING'] = True
    app_mod.app.config['WTF_CSRF_ENABLED'] = False
    return app_mod.app.test_client()

def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')

def test_mobile_nav_contains_data_nav_module():
    base = _read('templates/base.html')
    sidebar = _read('templates/partials/sidebar.html')
    assert 'id="gc-bottom-nav"' in base
    assert 'id="gc-nav-drawer"' in base
    assert 'data-nav-module="overview"' in base
    assert 'data-nav-module="fleet"' in base
    assert 'data-nav-always-visible' not in base.split('id="gc-bottom-nav"', 1)[1].split('id="gc-nav-drawer"', 1)[0]
    assert 'data-nav-module="research"' in sidebar

def test_role_sync_targets_mobile_drawer():
    src = _read('static/main.js')
    assert 'applyMobileBottomNav' in src
    assert 'syncMobileDrawerSidebars' in src
    assert 'applyDesktopSidebarNav' in src
    assert 'getElementById("gc-bottom-nav")' in src
    assert 'getElementById("gc-nav-drawer")' in src

def test_homeworld_mobile_full_nav():
    nav = resolve_sidebar_nav(empire_role_key='homeworld', is_homeworld=True)
    bottom = mobile_bottom_modules(nav)
    assert bottom == ['overview', 'buildings', 'research', 'fleet']
    assert mobile_drawer_shows_module(nav, 'techtree', bottom_modules=bottom)
    assert not mobile_drawer_shows_module(nav, 'overview', bottom_modules=bottom)
    assert not mobile_drawer_shows_module(nav, 'fleet', bottom_modules=bottom)

def test_mining_role_mobile_filter():
    nav = resolve_sidebar_nav(empire_role_key='mining', is_homeworld=False)
    bottom = mobile_bottom_modules(nav)
    assert bottom == ['overview', 'buildings', 'defense', 'logistics']
    assert module_display_section(nav, 'research') == 'infrastructure'
    assert module_display_section(nav, 'buildings') == 'infrastructure'

def test_unknown_role_mobile_fallback():
    nav = resolve_sidebar_nav(empire_role_key='mystery', is_homeworld=False)
    bottom = mobile_bottom_modules(nav)
    assert bottom == ['overview', 'buildings', 'research', 'fleet']

def test_planet_switch_updates_mobile_nav_markup(gc591b_db, monkeypatch):
    player_id, uname = _create_player()
    ok, reason, data = colonize_planet(player_id, name='Ore Station', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    colony_id = int(data['planet_id'])
    save_planet_buildings(colony_id, {'metal_mine': 12, 'crystal_mine': 9})
    client = _app_client(monkeypatch)
    assert client.post('/login', data={'username': uname, 'password': 'test-pass-123'}).status_code in (200, 302)
    hw_html = client.get('/overview').get_data(as_text=True)
    assert 'id="gc-bottom-nav"' in hw_html
    assert 'data-nav-module="research"' in hw_html
    assert 'data-nav-full="1"' in hw_html
    set_active_planet(player_id, colony_id)
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    mining_html = client.get('/overview').get_data(as_text=True)
    assert 'data-nav-full="0"' in mining_html
    assert 'gc-bottom-nav--role-nav' in mining_html
    assert 'gc-nav-drawer--role-nav' in mining_html
    assert 'data-nav-module="defense"' in mining_html
    assert 'data-nav-module="logistics"' in mining_html
    switch = client.post('/api/planets/active', json={'planet_id': colony_id}).get_json()
    assert switch['ok'] is True
    assert switch['state']['active_planet']['sidebar_nav']['empire_role_key'] == 'mining'
