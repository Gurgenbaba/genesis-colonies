"""GC-598 — World Inspector mission actions (fleet prefill MVP)."""
from __future__ import annotations
import importlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pytest
import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.command_center import build_colony_command_center, build_expedition_site_command_center, build_foreign_colony_command_center, build_strategic_world_command_center
from game.planet_evolution.command_map import build_command_map_payload
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import complete_world_claim, reserve_world_claim
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def gc598_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'gc598.db'
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

def _field_with(predicate):
    for wx in range(600, 5000, 47):
        for wy in range(600, 5000, 53):
            field = build_strategic_world_field(float(wx), float(wy))
            if predicate(field):
                return field
    raise AssertionError('no matching strategic world field')

def _colonizable_field():
    return _field_with(lambda f: f.get('is_colonizable') and (not f.get('is_expedition')))

def _expedition_field():
    return _field_with(lambda f: f.get('world_type') == 'expedition_zone')

def _salvage_field():
    return _field_with(lambda f: f.get('world_type') == 'wreckage_field' or f.get('is_salvage'))

def _player(conn):
    ok, err, user = create_user(f'gc598_{uuid.uuid4().hex[:8]}', 'test-pass-123')
    assert ok and user, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Commander', conn=conn)
    conn.commit()
    return uid

def _claim_world_colony(conn, owner_id, field, *, name='Rival Outpost', system=407, position=5):
    ok, reason, payload = reserve_world_claim(owner_id, field['_world_x'], field['_world_y'], conn=conn)
    assert ok, reason
    ok_col, col_reason, extra = colonize_planet(owner_id, name=name, galaxy=1, system=system, position=position, world_binding={'world_key': payload['world_key'], 'world_x': payload['world_x'], 'world_y': payload['world_y'], 'sector_x': payload['sector_x'], 'sector_y': payload['sector_y'], 'planet_role': payload['planet_role'], 'origin_world_key': payload['world_key']}, conn=conn)
    assert ok_col, col_reason
    complete_world_claim(field['world_key'], owner_id, int(extra['planet_id']), conn=conn)
    conn.commit()
    return (int(extra['planet_id']), str(field['world_key']))

def _mission_keys(actions):
    return [str(row.get('mission') or row.get('action_key') or '') for row in actions]

def _parse_fleet_href(href: str) -> dict[str, list[str]]:
    parsed = urlparse(href)
    return parse_qs(parsed.query, keep_blank_values=True)

def test_gc598_template_js_css_contract():
    js = (ROOT / 'static/main.js').read_text(encoding='utf-8')
    css = (ROOT / 'static/style.css').read_text(encoding='utf-8')
    for needle in ('function appendMissionActions(', 'function navigateMissionAction(', 'function renderForeignMissionModal(', 'gc-world-inspector-actions--missions', 'gc-world-inspector-shell--foreign-mission'):
        assert needle in js, f'missing js marker: {needle}'
    for needle in ('.gc-world-inspector-actions--missions', '.gc-world-inspector-mission-btn--blocked', '.gc-world-inspector-shell--foreign-mission'):
        assert needle in css, f'missing css rule: {needle}'

def test_own_colony_mission_actions_transport_deploy_collect(gc598_db):
    from game.db import db
    conn = db()
    try:
        player_id = _player(conn)
        ok, reason, payload = colonize_planet(player_id, name='Outpost Alpha', conn=conn, allow_legacy_coordinates=True, source='test')
        assert ok, reason
        planet_id = int(payload['planet_id'])
        cc = build_colony_command_center(planet_id, player_id, conn=conn)
    finally:
        conn.close()
    actions = cc.get('mission_actions') or []
    assert _mission_keys(actions) == ['transport', 'deploy', 'collect']
    for row in actions:
        assert row.get('enabled') is True
        assert str(row.get('href') or '').startswith('/fleet?')
        qs = _parse_fleet_href(row['href'])
        assert qs['target_planet_id'] == [str(planet_id)]

def test_foreign_colony_mission_actions_spy_attack(gc598_db):
    from game.db import db
    field = _colonizable_field()
    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        planet_id, world_key = _claim_world_colony(conn, owner_id, field)
        node = {'node_kind': 'foreign_world_colony', 'owner_player_id': owner_id, 'owner_username': 'Rival', 'planet_id': planet_id, 'world_key': world_key, 'name': 'Rival Outpost'}
        cc = build_foreign_colony_command_center(node, viewer_id, conn=conn)
    finally:
        conn.close()
    actions = cc.get('mission_actions') or []
    assert _mission_keys(actions) == ['spy', 'attack']
    for row in actions:
        assert row.get('enabled') is True
        qs = _parse_fleet_href(row['href'])
        assert qs['mission'] == [row['mission']]
        assert qs['target_type'] == ['enemy_colony']
        assert qs['world_key'] == [world_key]
        assert qs['target_planet_id'] == [str(planet_id)]

def test_foreign_empire_mission_actions_spy_attack(gc598_db):
    from game.db import db
    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        ok, reason, payload = colonize_planet(owner_id, name='Papa Prime', conn=conn, allow_legacy_coordinates=True, source='test')
        assert ok, reason
        homeworld_id = int(payload['planet_id'])
        node = {'node_kind': 'foreign_empire', 'owner_player_id': owner_id, 'owner_username': 'papa-fanti', 'planet_id': homeworld_id, 'name': 'Papa Prime', 'homeworld_name': 'Papa Prime', 'colony_count': 1}
        cc = build_foreign_colony_command_center(node, viewer_id, conn=conn)
    finally:
        conn.close()
    actions = cc.get('mission_actions') or []
    assert _mission_keys(actions) == ['spy', 'attack']
    assert all((row.get('enabled') for row in actions))

def test_expedition_world_mission_action(gc598_db):
    from game.db import db
    field = _expedition_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_expedition_site_command_center(field, player_id, conn=conn)
    finally:
        conn.close()
    actions = cc.get('mission_actions') or []
    assert _mission_keys(actions) == ['expedition']
    qs = _parse_fleet_href(actions[0]['href'])
    assert qs['mission'] == ['expedition']
    assert qs['world_key'] == [field['world_key']]
    assert qs['target_type'] == ['expedition_world']

def test_wreckage_mission_action_salvage(gc598_db):
    from game.db import db
    field = _salvage_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_expedition_site_command_center(field, player_id, conn=conn)
    finally:
        conn.close()
    actions = cc.get('mission_actions') or []
    assert len(actions) == 1
    row = actions[0]
    assert row.get('action_key') == 'salvage'
    assert row.get('mission') == 'expedition'
    qs = _parse_fleet_href(row['href'])
    assert qs['mission'] == ['expedition']
    assert qs['target_type'] == ['wreckage']
    assert row.get('enabled') is False
    assert row.get('blocked_reason_key') == 'no_expedition_ships'

def test_colonizable_world_mission_action(gc598_db):
    from game.db import db
    field = _colonizable_field()
    conn = db()
    try:
        player_id = _player(conn)
        cc = build_strategic_world_command_center(field, player_id, conn=conn)
    finally:
        conn.close()
    actions = cc.get('mission_actions') or []
    assert _mission_keys(actions) == ['colonize']
    qs = _parse_fleet_href(actions[0]['href'])
    assert qs['mission'] == ['colonize']
    assert qs['world_key'] == [field['world_key']]
    assert actions[0].get('enabled') is True

def test_command_map_foreign_node_includes_mission_actions(gc598_db):
    from game.db import db
    field = _colonizable_field()
    conn = db()
    try:
        owner_id = _player(conn)
        viewer_id = _player(conn)
        _claim_world_colony(conn, owner_id, field)
        payload = build_command_map_payload(viewer_id, conn=conn)
        foreign = [n for n in payload['nodes'] if n.get('node_kind') == 'foreign_world_colony' and n.get('world_key') == field['world_key']]
        assert len(foreign) == 1
        cc = foreign[0].get('command_center') or {}
        assert _mission_keys(cc.get('mission_actions') or []) == ['spy', 'attack']
    finally:
        conn.close()

def test_galaxy_command_map_serializes_mission_actions(gc598_db, monkeypatch):
    import app as app_module
    dbmod.DB_PATH = gc598_db
    models.DB_PATH = gc598_db
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    importlib.reload(app_module)
    uname = f'gc598_ui_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    user_id = int(user['id'])
    ensure_player_and_homeworld(user_id, player_name='Commander')
    client = app_module.app.test_client()
    app_module.app.config['TESTING'] = True
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
    body = client.get('/galaxy?view=command_map').get_data(as_text=True)
    assert 'data-command-center' in body
    assert 'mission=spy' in body or 'mission_actions' in body or 'fleet_mission_spy' in body
