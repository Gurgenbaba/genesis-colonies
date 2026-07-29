"""GC-641B — Sidebar role-nav regression guard."""
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
from game.planet_evolution.sidebar_nav import NAV_SECTION_MODULES, _ALWAYS_PROMINENT_MODULES, nav_module_tier, resolve_sidebar_nav, sidebar_section_visible
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'
SIDEBAR_PATH = ROOT / 'templates' / 'partials' / 'sidebar.html'
MAIN_SECTIONS = ('command', 'infrastructure', 'military')
RIGHT_SIDEBAR_SECTIONS = ('messages', 'economy', 'community')
BACKEND_NAV_SECTIONS = ('command', 'infrastructure', 'military', 'economy', 'administration')

@pytest.fixture()
def gc641b_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc641b.db'
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
    uname = f'gc641b_{uuid.uuid4().hex[:8]}'
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

def _section_open_tags(sidebar_html: str, sections: tuple[str, ...]=MAIN_SECTIONS) -> dict[str, str]:
    tags: dict[str, str] = {}
    for section in sections:
        marker = f'data-nav-section="{section}"'
        idx = sidebar_html.find(marker)
        assert idx >= 0, f'missing section {section}'
        start = sidebar_html.rfind('<div', 0, idx)
        end = sidebar_html.find('>', idx)
        tags[section] = sidebar_html[start:end + 1]
    return tags

def test_section_wrappers_have_no_data_nav_group():
    sidebar = SIDEBAR_PATH.read_text(encoding='utf-8')
    for section, open_tag in _section_open_tags(sidebar).items():
        assert 'data-nav-group="' not in open_tag, section
        assert 'data-nav-group-modules=' not in open_tag, section
        assert 'data-nav-group-key=' not in open_tag, section

def test_data_nav_group_only_on_nested_submodules():
    sidebar = SIDEBAR_PATH.read_text(encoding='utf-8')
    for match in re.finditer('data-nav-group="([^"]+)"', sidebar):
        pos = match.start()
        section_idx = sidebar.rfind('data-nav-section="', 0, pos)
        section_end = sidebar.find('"', section_idx + len('data-nav-section="'))
        section_body_start = sidebar.find('>', section_end) + 1
        assert pos > section_body_start, 'data-nav-group must not sit on a section wrapper'

def test_empire_core_modules_always_prominent_for_colony_roles():
    assert _ALWAYS_PROMINENT_MODULES == frozenset({'trading', 'empire', 'ranking', 'records', 'referrals'})
    roles = ('mining', 'research', 'shipyard', 'fortress', 'frontier', 'trade')
    for role in roles:
        nav = resolve_sidebar_nav(empire_role_key=role, is_homeworld=False)
        for module in _ALWAYS_PROMINENT_MODULES:
            assert nav_module_tier(nav, module) == 'prominent', f'{role}/{module}'

def test_all_main_sections_visible_for_research_colony(gc641b_db, monkeypatch):
    player_id, uname = _create_player()
    ok, reason, data = colonize_planet(player_id, name='Lab Colony', allow_legacy_coordinates=True, source='test')
    assert ok, reason
    colony_id = int(data['planet_id'])
    save_planet_buildings(colony_id, {'research_lab': 12, 'academy': 5})
    set_active_planet(player_id, colony_id)
    nav = resolve_sidebar_nav(empire_role_key='research', is_homeworld=False)
    for section in BACKEND_NAV_SECTIONS:
        assert sidebar_section_visible(nav, section) is True
    client = _app_client(monkeypatch)
    assert client.post('/login', data={'username': uname, 'password': 'test-pass-123'}).status_code in (200, 302)
    html = client.get('/overview').get_data(as_text=True)
    sidebar_left = html.split('id="gc-sidebar-nav"', 1)[1].split('</nav>', 1)[0]
    sidebar_right = html.split('id="gc-sidebar-nav-right"', 1)[1].split('</nav>', 1)[0]
    for section in MAIN_SECTIONS:
        open_tag = _section_open_tags(sidebar_left)[section]
        assert ' hidden' not in open_tag, section
    for section in RIGHT_SIDEBAR_SECTIONS:
        open_tag = _section_open_tags(sidebar_right, RIGHT_SIDEBAR_SECTIONS)[section]
        assert ' hidden' not in open_tag, section
    assert 'data-nav-full="0"' in html
    assert 'gc-sidebar--role-nav' in html

def test_client_sidebar_config_exports_always_prominent_modules():
    from game.planet_evolution.sidebar_nav import client_sidebar_nav_config
    cfg = client_sidebar_nav_config()
    assert set(cfg['always_prominent_modules']) == set(_ALWAYS_PROMINENT_MODULES)

def test_main_sections_cover_expected_modules():
    covered = set()
    for modules in NAV_SECTION_MODULES.values():
        covered.update(modules)
    for section, modules in NAV_SECTION_MODULES.items():
        if section == 'messages':
            continue
        assert modules, section
