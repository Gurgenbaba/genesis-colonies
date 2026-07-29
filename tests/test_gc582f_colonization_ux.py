"""GC-582F — Colonization UX polish (reports, badges, inspector)."""
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
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import build_world_colonize_report, complete_world_claim, is_newly_colonized_world, reserve_world_claim
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def gc582f_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc582f.db'
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
    ok, err, user = create_user(f'gc582f_{uuid.uuid4().hex[:8]}', 'test-pass-123')
    assert ok and user, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Commander', conn=conn)
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from game.models import get_homeworld
    from conftest import unlock_colony_slots
    unlock_colony_slots(conn, int(get_homeworld(player_id=uid, conn=conn)['id']), slots=1)
    conn.commit()
    return uid

def _colonizable_field():
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get('is_colonizable'):
                return field
    raise AssertionError('no colonizable field in sample grid')

def test_build_world_colonize_report_failure_localized():
    subject, body, meta = build_world_colonize_report('field:mining_world:1520:2480', 'Helios', locale='de', success=False, fail_reason='world_already_claimed')
    assert meta['success'] is False
    assert 'world_already_claimed' not in body
    assert '1520:2480' in body
    assert 'field:mining_world' not in body
    assert 'Kolonie konnte nicht gegründet werden' in body
    assert 'anderen Imperium' in body
    assert 'Kolonisierung fehlgeschlagen' in subject

def test_build_world_colonize_report_contains_strategic_name():
    field = _colonizable_field()
    subject, body, meta = build_world_colonize_report(field['world_key'], 'Helios Prime', locale='en', success=True)
    assert meta['report_kind'] == 'world_colonize'
    assert meta['world_name_key'] == field['name_key']
    assert 'New colony founded' in body
    assert 'field:' not in body
    assert 'New colony founded' in subject

def test_classic_colonize_report_unchanged_without_world_key():
    subject, body, meta = build_world_colonize_report('field:mining_world:100:200', 'Classic', locale='en', success=True)
    assert meta['world_key']
    assert 'Location:' in body

def test_is_newly_colonized_window():
    now = time.time()
    assert is_newly_colonized_world(now - 3600, now=now)
    assert not is_newly_colonized_world(now - 8 * 86400, now=now)

def test_command_map_world_colony_has_newly_colonized_flag(gc582f_db):
    field = _colonizable_field()
    from game.db import db
    conn = db()
    try:
        player_id = _player(conn)
        ok, reason, payload = reserve_world_claim(player_id, field['_world_x'], field['_world_y'], conn=conn)
        assert ok, reason
        ok_col, col_reason, extra = colonize_planet(player_id, name='Map Colony', galaxy=1, system=None, position=None, world_binding={'world_key': payload['world_key'], 'world_x': payload['world_x'], 'world_y': payload['world_y'], 'sector_x': payload['sector_x'], 'sector_y': payload['sector_y'], 'planet_role': payload['planet_role'], 'origin_world_key': payload['world_key']}, conn=conn)
        assert ok_col, col_reason
        complete_world_claim(field['world_key'], player_id, int(extra['planet_id']), conn=conn)
        conn.commit()
        map_payload = build_command_map_payload(player_id, conn=conn)
        world_nodes = [n for n in map_payload['nodes'] if n.get('world_map_bound') and int(n.get('planet_id') or 0) == int(extra['planet_id'])]
        assert len(world_nodes) == 1
        node = world_nodes[0]
        assert node.get('is_newly_colonized') is True
        assert node.get('origin_world_name_key')
    finally:
        conn.close()

def test_fleet_world_colonize_report_metadata(gc582f_db):
    import importlib
    import app as app_module
    from game.fleet import add_planet_ships, process_fleet_tick, send_fleet
    field = _colonizable_field()
    from game.db import db
    conn = db()
    try:
        player_id = _player(conn)
        pid = conn.execute('SELECT id FROM planets WHERE player_id = ? ORDER BY is_homeworld DESC LIMIT 1;', (player_id,)).fetchone()['id']
        conn.execute('UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE player_id = ?;', (player_id,))
        add_planet_ships(int(pid), player_id, {'seed_ark': 1}, conn=conn)
        conn.commit()
        ok, reason, result = send_fleet(player_id=player_id, origin_planet_id=int(pid), target_galaxy=1, target_system=1, target_position=1, mission_type='colonize', ships={'seed_ark': 1}, world_key=field['world_key'], conn=conn)
        assert ok, reason
        fleet_id = int(result['fleet']['id'])
        conn.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()
        msg = conn.execute('\n            SELECT subject, body, metadata_json FROM player_messages\n            WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;\n            ', (player_id,)).fetchone()
        assert msg
        meta = json.loads(msg['metadata_json'])
        assert meta.get('report_kind') == 'world_colonize'
        assert meta.get('world_name_key') == field['name_key']
        assert 'field:' not in msg['body']
    finally:
        conn.close()

def test_galaxy_template_gc582f_contract():
    html = (ROOT / 'templates' / 'partials' / 'galaxy_command_map_panel.html').read_text(encoding='utf-8')
    assert 'data-colony-location-inspect' in html
    assert 'command_map_badge_newly_colonized' in html
    assert 'data-foreign-world-colony-inspect' in html
    assert 'data-expedition-status' in html
    assert 'gc-world-inspector-modal' in html
    js = (ROOT / 'static' / 'main.js').read_text(encoding='utf-8')
    assert 'openWorldInspectorFromNode' in js
    assert 'world_inspector_open_colony' in js
