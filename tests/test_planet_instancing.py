"""
Planet instancing: isolation, ownership, active-colony scoping.

Run: python -m pytest tests/test_planet_instancing.py -v
"""
from __future__ import annotations
import importlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.db import db
from game.exchange import execute_exchange
from game.models import create_user, get_homeworld, get_planet_buildings, init_db, save_planet_buildings
from game.planet_evolution.bootstrap import backfill_all_planets_evolution, ensure_planet_evolution
from game.planet_evolution.definitions import reload_definitions
from game.planet_evolution.planet_research import get_planet_research_status, queue_planet_research
from game.planet_evolution.repository import set_active_planet_id
from game.planet_evolution.service import colonize_planet, create_trade_route, set_active_planet
from game.ranking import get_sorted_ranking_entries
from game.resources import update_planet_resources
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def instancing_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'planet_instancing.db'
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
    conn = db()
    reload_definitions(conn)
    backfill_all_planets_evolution(conn)
    conn.commit()
    conn.close()
    yield db_file

def _create_player() -> tuple[int, str]:
    uname = f'inst_{uuid.uuid4().hex[:8]}'
    ok, err, user = create_user(uname, 'test-pass-123')
    assert ok and user, err
    return (int(user['id']), uname)

def _second_planet(player_id: int) -> int:
    last_reason = 'unknown'
    for attempt in range(16):
        try:
            ok, reason, extra = colonize_planet(player_id, name=f'Colony_{uuid.uuid4().hex[:4]}', galaxy=1, system=250 + attempt, position=2 + attempt % 6, allow_legacy_coordinates=True, source='test')
        except OverflowError:
            continue
        if ok:
            pid = int(extra['planet_id'])
            conn = db()
            ensure_planet_evolution(pid, conn)
            conn.commit()
            conn.close()
            return pid
        last_reason = reason
    pytest.fail(f'colonize_planet failed: {last_reason}')

def _reload_app(monkeypatch, db_file):
    import app as app_mod
    monkeypatch.setenv('GC_DB_PATH', str(db_file))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-not-default-value-32chars')
    dbmod.DB_PATH = db_file
    models.DB_PATH = db_file
    importlib.reload(app_mod)
    app_mod.app.config['TESTING'] = True
    app_mod.app.config['WTF_CSRF_ENABLED'] = False
    return app_mod

def test_player_cannot_manipulate_foreign_planet_api(instancing_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, instancing_db)
    player_a, user_a = _create_player()
    player_b, _user_b = _create_player()
    foreign_planet = int(get_homeworld(player_id=player_b)['id'])
    client = app_mod.app.test_client()
    client.post('/login', data={'username': user_a, 'password': 'test-pass-123'})
    r = client.post(f'/api/planets/{foreign_planet}/research/start', json={'tech_key': 'industry_t1_automation'}, headers={'Content-Type': 'application/json'})
    assert r.status_code == 403
    assert r.get_json()['reason'] == 'forbidden'
    r_state = client.get(f'/api/planets/{foreign_planet}/state')
    assert r_state.status_code == 403

def test_exchange_on_active_planet_does_not_touch_other_planet(instancing_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    colony_id = _second_planet(player_id)
    conn = db()
    conn.execute('UPDATE planets SET metal = 50000, crystal = 0 WHERE id = ?;', (hw_id,))
    conn.execute('UPDATE planets SET metal = 7777, crystal = 3333 WHERE id = ?;', (colony_id,))
    set_active_planet_id(player_id, hw_id, conn)
    conn.commit()
    conn.close()
    conn = db()
    ok, reason, _ = execute_exchange(player_id=player_id, planet_id=hw_id, from_resource='metal', amount=1000, conn=conn)
    assert ok, reason
    hw_row = conn.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (hw_id,)).fetchone()
    col_row = conn.execute('SELECT metal, crystal FROM planets WHERE id = ?;', (colony_id,)).fetchone()
    conn.close()
    assert int(hw_row['metal']) == 49000
    assert int(col_row['metal']) == 7777
    assert int(col_row['crystal']) == 3333

def test_update_planet_resources_does_not_finish_other_planet_builds(instancing_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    colony_id = _second_planet(player_id)
    save_planet_buildings(hw_id, {'metal_mine': 1})
    save_planet_buildings(colony_id, {'metal_mine': 1})
    conn = db()
    now = time.time()
    conn.execute("\n        INSERT INTO build_queue (planet_id, building_type, start_time, finish_time)\n        VALUES (?, 'metal_mine', ?, ?);\n        ", (colony_id, now - 120, now - 60))
    hw_row = dict(conn.execute('SELECT * FROM planets WHERE id = ?;', (hw_id,)).fetchone())
    conn.commit()
    update_planet_resources(hw_row, conn=conn, skip_queue_finish=False)
    conn.commit()
    pending = conn.execute('SELECT COUNT(*) AS c FROM build_queue WHERE planet_id = ?;', (colony_id,)).fetchone()['c']
    hw_level = conn.execute('SELECT metal_mine FROM planet_buildings WHERE planet_id = ?;', (colony_id,)).fetchone()['metal_mine']
    conn.close()
    assert int(pending) == 1
    assert int(hw_level) == 1

def test_planet_evolution_research_isolated_per_planet(instancing_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    colony_id = _second_planet(player_id)
    conn = db()
    for pid in (hw_id, colony_id):
        conn.execute('UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;', (pid,))
        conn.execute('UPDATE planet_buildings SET research_lab = 5 WHERE planet_id = ?;', (pid,))
    conn.commit()
    conn.close()
    conn = db()
    ok, reason, _ = queue_planet_research(hw_id, 'industry_t1_automation', player_id=player_id, conn=conn)
    assert ok, reason
    hw_status = get_planet_research_status(hw_id, conn=conn)
    col_status = get_planet_research_status(colony_id, conn=conn)
    conn.close()
    assert len(hw_status.get('queue') or []) >= 1
    assert (col_status.get('queue') or []) == []

def test_queue_planet_research_rejects_foreign_owner(instancing_db):
    owner_a, _ = _create_player()
    owner_b, _ = _create_player()
    planet_b = int(get_homeworld(player_id=owner_b)['id'])
    conn = db()
    conn.execute('UPDATE planets SET metal = 999999, crystal = 999999 WHERE id = ?;', (planet_b,))
    conn.execute('UPDATE planet_buildings SET research_lab = 5 WHERE planet_id = ?;', (planet_b,))
    ensure_planet_evolution(planet_b, conn)
    conn.commit()
    conn.close()
    ok, reason, extra = queue_planet_research(planet_b, 'industry_t1_automation', player_id=owner_a)
    assert not ok
    assert reason == 'not_owner'
    assert extra is None
    conn = db()
    count = conn.execute('SELECT COUNT(*) AS c FROM planet_research_queue WHERE planet_id = ?;', (planet_b,)).fetchone()['c']
    conn.close()
    assert int(count) == 0

def test_trade_routes_reject_foreign_planets(instancing_db):
    owner_a, _ = _create_player()
    owner_b, _ = _create_player()
    planet_a = int(get_homeworld(player_id=owner_a)['id'])
    planet_b = int(get_homeworld(player_id=owner_b)['id'])
    colony_a = _second_planet(owner_a)
    ok, reason, _ = create_trade_route(owner_a, source_planet_id=colony_a, target_planet_id=planet_b, resource_key='metal', amount_per_hour=100.0)
    assert not ok
    assert reason == 'not_owner'
    ok2, reason2, _ = create_trade_route(owner_a, source_planet_id=planet_a, target_planet_id=colony_a, resource_key='metal', amount_per_hour=50.0)
    assert ok2, reason2

def test_ranking_read_does_not_mutate_planet_resources(instancing_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    colony_id = _second_planet(player_id)
    conn = db()
    conn.execute('UPDATE planets SET metal = 111, crystal = 222 WHERE id = ?;', (hw_id,))
    conn.execute('UPDATE planets SET metal = 333, crystal = 444 WHERE id = ?;', (colony_id,))
    conn.commit()
    before = {int(r['id']): (float(r['metal']), float(r['crystal'])) for r in conn.execute('SELECT id, metal, crystal FROM planets WHERE id IN (?, ?);', (hw_id, colony_id)).fetchall()}
    conn.close()
    entries = get_sorted_ranking_entries(limit=50)
    assert isinstance(entries, list)
    conn = db()
    after = {int(r['id']): (float(r['metal']), float(r['crystal'])) for r in conn.execute('SELECT id, metal, crystal FROM planets WHERE id IN (?, ?);', (hw_id, colony_id)).fetchall()}
    conn.close()
    assert before == after

def test_game_state_resources_follow_planet_switch(instancing_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, instancing_db)
    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)['id'])
    colony_id = _second_planet(player_id)
    conn = db()
    conn.execute('UPDATE planets SET metal = 100, crystal = 50 WHERE id = ?;', (hw_id,))
    conn.execute('UPDATE planets SET metal = 9000, crystal = 8000 WHERE id = ?;', (colony_id,))
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    set_active_planet(player_id, colony_id)
    r_colony = client.get('/api/game-state')
    body_colony = r_colony.get_json()
    assert body_colony['active_planet_id'] == colony_id
    assert int(body_colony['resources']['metal']) == 9000
    assert int(body_colony['resources']['crystal']) == 8000
    set_active_planet(player_id, hw_id)
    r_hw = client.get('/api/game-state')
    body_hw = r_hw.get_json()
    assert body_hw['active_planet_id'] == hw_id
    assert int(body_hw['resources']['metal']) == 100
    assert int(body_hw['resources']['crystal']) == 50
