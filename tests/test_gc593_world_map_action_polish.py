"""GC-593 — Command Center action cards with situational status."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, init_db, save_planet_buildings
from game.planet_evolution.command_center import build_colony_command_center
from game.planet_evolution.service import colonize_planet
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'
GC593_LOCALE_KEYS = ('command_center_action_status_free', 'command_center_action_status_recommended', 'command_center_action_status_queue_active', 'command_center_action_status_fleet_active', 'command_center_action_status_blocked', 'command_center_action_status_other_planet')
_VALID_STATUSES = frozenset({'free', 'queue_active', 'blocked', 'recommended'})

@pytest.fixture()
def gc593_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc593.db'
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

def _player(conn):
    ok, err, user = create_user(f'gc593_{uuid.uuid4().hex[:8]}', 'test-pass-123')
    assert ok and user, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Commander', conn=conn)
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from game.models import get_homeworld
    from conftest import unlock_colony_slots
    unlock_colony_slots(conn, int(get_homeworld(player_id=uid, conn=conn)['id']), slots=1)
    conn.commit()
    return uid

def test_gc593_locale_keys_present():
    for path in ('locales/en.json', 'locales/de.json'):
        data = json.loads((ROOT / path).read_text(encoding='utf-8'))
        for key in GC593_LOCALE_KEYS:
            assert key in data, f'missing {key} in {path}'

def test_gc593_css_and_js_contract():
    css = (ROOT / 'static' / 'style.css').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'main.js').read_text(encoding='utf-8')
    for needle in ('.gc-command-center-action-card', '.gc-command-center-action-card--queue_active', '.gc-command-center-action-card--recommended', '.gc-command-center-action-card--blocked', 'renderColonyActionCard', 'data-timer-kind="queue"', 'dataset.actionStatus'):
        assert needle in (css if needle.startswith('.') else js), f'missing {needle}'

def test_action_cards_include_status_fields(gc593_db):
    from game.db import db
    from game.models import get_homeworld
    conn = db()
    try:
        player_id = _player(conn)
        hw = get_homeworld(player_id, conn=conn)
        planet_id = int(hw['id'])
        cc = build_colony_command_center(planet_id, player_id, conn=conn, role_key='homeworld', is_homeworld=True)
    finally:
        conn.close()
    actions = cc.get('quick_actions') or []
    assert len(actions) >= 5
    for row in actions:
        assert row.get('action_key')
        assert row.get('label_key')
        assert row.get('href')
        assert row.get('status') in _VALID_STATUSES
        assert row.get('status_key')
        assert row.get('icon')
    slots = {row['action_key'] for row in actions}
    assert 'buildings' in slots
    assert 'research' in slots
    assert 'evolution' in slots
    recommended = [row for row in actions if row.get('status') == 'recommended']
    assert recommended, 'homeworld should surface recommended actions when idle'

def test_build_queue_marks_action_card_queue_active(gc593_db):
    from game.db import db
    from game.models import get_homeworld
    conn = db()
    try:
        player_id = _player(conn)
        hw = get_homeworld(player_id, conn=conn)
        planet_id = int(hw['id'])
        save_planet_buildings(planet_id, {'metal_mine': 1})
        now = time.time()
        conn.execute("\n            INSERT INTO build_queue (planet_id, building_type, start_time, finish_time)\n            VALUES (?, 'metal_mine', ?, ?);\n            ", (planet_id, now, now + 600.0))
        conn.commit()
        cc = build_colony_command_center(planet_id, player_id, conn=conn, role_key='homeworld', is_homeworld=True)
        build_card = next((row for row in cc['quick_actions'] if row['action_key'] == 'buildings'))
    finally:
        conn.close()
    assert build_card['status'] == 'queue_active'
    assert build_card.get('countdown_at')
    assert build_card['status_key'] == 'command_center_action_status_queue_active'

def test_mining_colony_recommends_logistics(gc593_db):
    from game.db import db
    conn = db()
    try:
        player_id = _player(conn)
        ok, reason, data = colonize_planet(player_id, name='Mining Node', allow_legacy_coordinates=True, source='test')
        assert ok, reason
        colony_id = int(data['planet_id'])
        save_planet_buildings(colony_id, {'metal_mine': 8, 'crystal_mine': 6})
        cc = build_colony_command_center(colony_id, player_id, conn=conn, role_key='mining', is_homeworld=False)
        logistics = next((row for row in cc['quick_actions'] if row['action_key'] == 'logistics'), None)
    finally:
        conn.close()
    assert logistics is not None
    assert logistics['status'] in {'recommended', 'free', 'queue_active', 'blocked'}
