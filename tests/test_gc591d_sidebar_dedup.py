"""GC-591D P0 — Sidebar dedup + homeworld Verwaltung fix."""
from __future__ import annotations
import importlib
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.models import create_user, init_db, save_planet_buildings
from game.planet_evolution.service import colonize_planet, set_active_planet
from game.planet_evolution.sidebar_nav import module_display_section, module_in_section, nav_module_tier, resolve_sidebar_nav, secondary_overflow_modules, visible_sidebar_modules
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def gc591d_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc591d.db'
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
    uname = f'gc591d_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    return (int(user['id']), uname)

def _app_client(monkeypatch):
    import app as app_mod
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_mod)
    app_mod.app.config['TESTING'] = True
    app_mod.app.config['WTF_CSRF_ENABLED'] = False
    return app_mod.app.test_client()

def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding='utf-8')

def _sidebar_module_ids(html: str) -> list[str]:
    return re.findall('data-nav-module="([^"]+)"', html)

def test_homeworld_no_overflow_duplicates():
    nav = resolve_sidebar_nav(empire_role_key='homeworld', is_homeworld=True)
    assert secondary_overflow_modules(nav) == []
    visible = visible_sidebar_modules(nav)
    assert len(visible) == len(set(visible))
    assert module_display_section(nav, 'research') == 'infrastructure'
    assert module_display_section(nav, 'ranking') == 'administration'
    assert not module_in_section(nav, 'overview', 'administration')

def test_homeworld_verwaltung_only_utility_modules():
    nav = resolve_sidebar_nav(empire_role_key='homeworld', is_homeworld=True)
    admin_modules = [m for m in visible_sidebar_modules(nav) if module_in_section(nav, m, 'administration')]
    assert set(admin_modules) == {'alliance', 'ranking', 'hall_of_fame', 'referrals', 'records'}

def test_homeworld_messages_standalone_shortcut():
    nav = resolve_sidebar_nav(empire_role_key='homeworld', is_homeworld=True)
    assert module_display_section(nav, 'messages') == 'messages'
    assert module_in_section(nav, 'messages', 'messages')
    assert not module_in_section(nav, 'messages', 'command')
    assert not module_in_section(nav, 'messages', 'administration')

def test_mining_no_duplicate_visible_modules():
    nav = resolve_sidebar_nav(empire_role_key='mining', is_homeworld=False)
    visible = visible_sidebar_modules(nav)
    assert len(visible) == len(set(visible))
    assert module_display_section(nav, 'research') == 'infrastructure'
    assert module_display_section(nav, 'buildings') == 'infrastructure'
    assert secondary_overflow_modules(nav) == []

def test_research_no_duplicate_visible_modules():
    nav = resolve_sidebar_nav(empire_role_key='research', is_homeworld=False)
    visible = visible_sidebar_modules(nav)
    assert len(visible) == len(set(visible))
    assert module_display_section(nav, 'research') == 'infrastructure'
    assert module_display_section(nav, 'shipyard') == 'military'
    assert nav_module_tier(nav, 'shipyard') == 'secondary'

def _visible_module_lines(sidebar_html: str, module: str) -> list[str]:
    needle = f'data-nav-module="{module}"'
    out = []
    pos = 0
    while True:
        idx = sidebar_html.find(needle, pos)
        if idx < 0:
            break
        start = sidebar_html.rfind('<', 0, idx)
        end = sidebar_html.find('>', idx)
        if start < 0 or end < 0:
            pos = idx + 1
            continue
        tag = sidebar_html[start:end + 1]
        head = tag.lstrip().lower()
        if head.startswith(('<a', '<button')) and 'hidden' not in tag:
            out.append(tag)
        pos = idx + 1
    return out

def test_sidebar_template_uses_single_section_slots():
    sidebar = _read('templates/partials/sidebar.html')
    assert 'data-nav-placement' not in sidebar
    assert 'data-nav-overflow="1"' not in sidebar
    assert 'data-nav-module="research"' in sidebar

def test_main_js_single_placement_sync():
    src = _read('static/main.js')
    assert 'moduleDisplaySection' in src
    assert 'shouldShowSidebarNavLink' in src
    assert 'el.hidden = true' in src.split('function applyDesktopSidebarNav')[1][:800]

def test_homeworld_overview_html_has_no_admin_duplicates(gc591d_db, monkeypatch):
    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    assert client.post('/login', data={'username': uname, 'password': 'test-pass-123'}).status_code in (200, 302)
    html = client.get('/overview').get_data(as_text=True)
    sidebar_chunk = html.split('id="gc-sidebar-nav"', 1)[1].split('</nav>', 1)[0]
    visible_overview = _visible_module_lines(sidebar_chunk, 'overview')
    assert len(visible_overview) == 1
    assert len(_visible_module_lines(sidebar_chunk, 'research')) == 1
    assert len(_visible_module_lines(sidebar_chunk, 'ranking')) == 1
    assert len(_visible_module_lines(sidebar_chunk, 'hall_of_fame')) == 1

def test_mining_colony_research_once_in_infrastructure(gc591d_db, monkeypatch):
    player_id, uname = _create_player()
    ok, reason, data = colonize_planet(player_id, name='Ore Mine', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    colony_id = int(data['planet_id'])
    save_planet_buildings(colony_id, {'metal_mine': 12, 'crystal_mine': 9})
    set_active_planet(player_id, colony_id)
    client = _app_client(monkeypatch)
    assert client.post('/login', data={'username': uname, 'password': 'test-pass-123'}).status_code in (200, 302)
    html = client.get('/overview').get_data(as_text=True)
    sidebar_chunk = html.split('id="gc-sidebar-nav"', 1)[1].split('</nav>', 1)[0]
    assert len(_visible_module_lines(sidebar_chunk, 'research')) == 1
    assert 'data-nav-overflow="1"' not in sidebar_chunk
    assert 'data-nav-section="infrastructure"' in sidebar_chunk
    switch = client.post('/api/planets/active', json={'planet_id': colony_id}).get_json()
    assert switch['state']['active_planet']['sidebar_nav']['empire_role_key'] == 'mining'

def test_mobile_drawer_dedupe_contract():
    base = _read('templates/base.html')
    drawer = base.split('id="gc-nav-drawer-links"', 1)[1].split('</div>', 1)[0]
    modules = re.findall('data-nav-module="([^"]+)"', drawer)
    assert len(modules) == len(set(modules))
