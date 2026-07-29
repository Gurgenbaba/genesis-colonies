"""GC-591 — Role-based sidebar navigation (presentation only)."""
from __future__ import annotations
import importlib
import json
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
from game.planet_evolution.sidebar_nav import ALL_NAV_MODULES, client_sidebar_nav_config, module_display_section, module_in_section, nav_module_tier, resolve_sidebar_nav
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def gc591_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc591.db'
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
    uname = f'gc591_{uuid.uuid4().hex[:8]}'
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

def test_homeworld_full_nav():
    nav = resolve_sidebar_nav(empire_role_key='homeworld', is_homeworld=True)
    assert nav['full_nav'] is True
    assert nav['show_more_section'] is False
    assert all((nav['modules'][key] == 'prominent' for key in ALL_NAV_MODULES))

def test_mining_role_nav_filter():
    nav = resolve_sidebar_nav(empire_role_key='mining', is_homeworld=False)
    assert nav_module_tier(nav, 'buildings') == 'prominent'
    assert module_display_section(nav, 'buildings') == 'infrastructure'
    assert module_display_section(nav, 'research') == 'infrastructure'
    assert module_in_section(nav, 'research', 'infrastructure')
    assert not module_in_section(nav, 'research', 'administration')

def test_research_role_nav_filter():
    nav = resolve_sidebar_nav(empire_role_key='research', is_homeworld=False)
    assert nav_module_tier(nav, 'research') == 'prominent'
    assert nav_module_tier(nav, 'techtree') == 'prominent'
    assert nav_module_tier(nav, 'planet_evolution') == 'prominent'
    assert nav_module_tier(nav, 'trading') == 'prominent'
    assert nav_module_tier(nav, 'empire') == 'prominent'
    assert nav_module_tier(nav, 'shipyard') == 'secondary'

def test_shipyard_role_nav_filter():
    nav = resolve_sidebar_nav(empire_role_key='shipyard', is_homeworld=False)
    assert nav_module_tier(nav, 'shipyard') == 'prominent'
    assert nav_module_tier(nav, 'fleet') == 'prominent'
    assert nav_module_tier(nav, 'defense') == 'prominent'
    assert nav_module_tier(nav, 'research') == 'secondary'
    assert nav_module_tier(nav, 'techtree') == 'secondary'

def test_unknown_role_fallback_full_nav():
    nav = resolve_sidebar_nav(empire_role_key='mystery_role', is_homeworld=False)
    assert nav['full_nav'] is True
    assert all((nav['modules'][key] == 'prominent' for key in ALL_NAV_MODULES))

def test_client_sidebar_nav_config_matches_roles():
    cfg = client_sidebar_nav_config()
    assert 'mining' in cfg['prominent_by_role']
    assert 'research' in cfg['prominent_by_role']
    assert set(cfg['all_modules']) == set(ALL_NAV_MODULES)

def test_sidebar_template_role_markers():
    sidebar = _read('templates/partials/sidebar.html')
    assert 'id="{{ _nav_id }}"' in sidebar
    assert 'data-nav-module="overview"' in sidebar
    assert 'data-nav-module="research"' in sidebar
    assert 'data-nav-module="shipyard"' in sidebar
    assert 'data-nav-module="defense"' in sidebar
    assert 'gc-nav-section-toggle' in sidebar
    assert 'data-nav-section="command"' in sidebar
    assert 'id="gc-nav-more-toggle"' not in sidebar
    assert 'nav_module_tier(_sn,' in sidebar
    assert 'gc-sidebar--full-nav' in sidebar
    assert 'gc-sidebar--role-nav' in sidebar

def test_main_js_planet_switch_updates_sidebar(gc591_db, monkeypatch):
    src = _read('static/main.js')
    base = _read('templates/base.html')
    css = _read('static/style.css')
    assert 'GC.syncRoleBasedSidebar' in src
    assert 'resolveSidebarNavFromState' in src
    assert 'applyDesktopSidebarNav' in src
    assert 'syncMobileDrawerSidebars' in src
    assert 'initRoleBasedSidebar' in src
    assert 'GC.syncRoleBasedSidebar(data)' in src
    assert src.index('function applyHudOnlyGameState') < src.index('GC.syncRoleBasedSidebar(data)')
    assert 'gc-sidebar-nav-config' in base
    assert 'GC_SIDEBAR_NAV_CONFIG' in base
    assert 'gc-sidebar--role-nav' in css
    assert 'gc-nav-link--more' in css

def test_game_state_active_planet_includes_sidebar_nav(gc591_db, monkeypatch):
    player_id, uname = _create_player()
    ok, reason, data = colonize_planet(player_id, name='Mining Outpost', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    colony_id = int(data['planet_id'])
    save_planet_buildings(colony_id, {'metal_mine': 10, 'crystal_mine': 8})
    client = _app_client(monkeypatch)
    assert client.post('/login', data={'username': uname, 'password': 'test-pass-123'}).status_code in (200, 302)
    gs = client.get('/api/game-state').get_json()
    assert gs['ok'] is True
    hw_nav = gs['active_planet']['sidebar_nav']
    assert hw_nav['full_nav'] is True
    ok, err = set_active_planet(player_id, colony_id)
    assert ok, err
    switch = client.post('/api/planets/active', json={'planet_id': colony_id}).get_json()
    assert switch['ok'] is True
    nav = switch['state']['active_planet']['sidebar_nav']
    assert nav['full_nav'] is False
    assert nav['empire_role_key'] == 'mining'
    assert nav['modules']['research'] == 'secondary'
    assert nav['modules']['buildings'] == 'prominent'
    gs2 = client.get('/api/game-state').get_json()
    assert gs2['active_planet']['sidebar_nav']['empire_role_key'] == 'mining'
    switch_back = client.post('/api/planets/active', json={'planet_id': gs['active_planet_id']}).get_json()
    assert switch_back['state']['active_planet']['sidebar_nav']['full_nav'] is True

def test_overview_renders_role_sidebar_attrs(gc591_db, monkeypatch):
    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    assert client.post('/login', data={'username': uname, 'password': 'test-pass-123'}).status_code in (200, 302)
    html = client.get('/overview').get_data(as_text=True)
    assert 'id="gc-sidebar-nav"' in html
    assert 'data-nav-full="1"' in html
    assert 'gc-sidebar--full-nav' in html
    ok, reason, data = colonize_planet(player_id, name='Research Node', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    colony_id = int(data['planet_id'])
    save_planet_buildings(colony_id, {'research_lab': 12, 'academy': 5})
    set_active_planet(player_id, colony_id)
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    html2 = client.get('/overview').get_data(as_text=True)
    assert 'data-nav-full="0"' in html2
    assert 'gc-sidebar--role-nav' in html2
    assert 'data-nav-module="research"' in html2
    assert 'gc-nav-module--prominent' in html2
    assert 'gc-nav-module--secondary' in html2
    cfg_el = 'id="gc-sidebar-nav-config"'
    assert cfg_el in html2
    raw = html2.split(cfg_el, 1)[1].split('</script>', 1)[0]
    cfg = json.loads(raw.split('>', 1)[1].strip())
    assert cfg['prominent_by_role']['research']
