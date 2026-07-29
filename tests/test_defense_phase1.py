"""GC-600 — Defense System Phase 1 (build queue, planet scope, GC-000 envelope)."""
from __future__ import annotations
import importlib
import os
import time
import uuid
import pytest
from game import db as gdb
from game.db import db
from game.defense import build_defense, defense_queue_table_ready, finish_due_defense_jobs_for_planet, list_defense_queue_rows
from game.defense_api import cancel_defense_job
from game.models import create_user, defense_schema_ready, ensure_player_and_homeworld, get_planet_defense, get_planets_by_player, init_db
from game.planet_evolution.service import colonize_planet

@pytest.fixture
def defense_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'defense_phase1.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_path))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key-not-default-value-32chars')
    gdb._DB_PATH = None
    init_db()
    import migrate
    migrate.main()
    yield
    gdb._DB_PATH = None

def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f'def_{uuid.uuid4().hex[:10]}', 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='Defender', conn=conn)
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from game.models import get_homeworld
    from conftest import unlock_colony_slots
    unlock_colony_slots(conn, int(get_homeworld(player_id=uid, conn=conn)['id']), slots=1)
    if own:
        conn.commit()
        conn.close()
    return uid

def _fund_planet(cur, planet_id: int, *, metal=500000, crystal=500000):
    cur.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (metal, crystal, int(planet_id)))

def _grant_defense_prereqs(cur, planet_id: int, user_id: int, *, factory_level: int=1) -> None:
    cur.execute('UPDATE planet_buildings SET defense_factory = ? WHERE planet_id = ?;', (int(factory_level), int(planet_id)))
    cur.execute("\n        INSERT INTO research_levels (user_id, tech_key, level)\n        VALUES (?, 'weapon_tech', 2)\n        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n        ", (int(user_id),))

def _login_client(defense_db, monkeypatch):
    import game.db as dbmod
    import game.models as models
    db_path = os.environ.get('GC_DB_PATH')
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module
    importlib.reload(app_module)
    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute('SELECT username FROM users WHERE id = ?;', (uid,)).fetchone()['username']
    conn.close()
    client = app_module.app.test_client()
    client.post('/login', data={'username': uname, 'password': 'test-pass-123'})
    return (client, uid, app_module)

def test_defense_schema_and_queue_ready(defense_db):
    conn = db()
    assert defense_schema_ready(conn)
    assert defense_queue_table_ready(conn)
    conn.close()

def test_build_defense_requires_factory(defense_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    _fund_planet(conn.cursor(), pid)
    conn.commit()
    ok, reason, _ = build_defense(player_id=uid, planet_id=pid, defense_key='sentinel_turret', amount=1, conn=conn)
    assert not ok
    assert reason == 'defense_factory_required'
    conn.close()

def test_build_defense_delivers_to_planet_stock(defense_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _grant_defense_prereqs(cur, pid, uid)
    conn.commit()
    ok, reason, result = build_defense(player_id=uid, planet_id=pid, defense_key='sentinel_turret', amount=2, conn=conn)
    assert ok, reason
    assert result['defense_queue']['summary']['count'] == 1
    cur.execute('UPDATE defense_queue SET finish_at = ? WHERE planet_id = ?;', (time.time() - 1, pid))
    conn.commit()
    finish_due_defense_jobs_for_planet(conn, pid, uid, now=time.time())
    stock = get_planet_defense(pid, conn=conn)
    assert stock.get('sentinel_turret', 0) >= 2
    conn.close()


def test_defense_order_duration_uses_batch_capacity(defense_db):
    """GC-SHIPYARD-TIME-1: defense duration is ceil(amount/cap)×unit, not amount×unit."""
    from game.defense import defense_queue_for_client, unit_build_seconds
    from game.shipyard import orbital_production_batch_capacity, production_job_duration_seconds

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid, metal=5_000_000, crystal=5_000_000)
    _grant_defense_prereqs(cur, pid, uid, factory_level=1)
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    conn.commit()
    qty = 20
    ok, reason, _ = build_defense(
        player_id=uid, planet_id=pid, defense_key='sentinel_turret', amount=qty, conn=conn
    )
    assert ok, reason
    row = list_defense_queue_rows(pid, conn=conn)[0]
    started = float(row['started_at'])
    finish = float(row['finish_at'])
    unit = unit_build_seconds('sentinel_turret', 1, conn=conn, planet_id=pid)
    cap = orbital_production_batch_capacity(1)
    expected = production_job_duration_seconds(
        unit_seconds=unit, amount=qty, batch_capacity=cap
    )
    assert int(finish - started) == expected
    assert expected < qty * unit
    q = defense_queue_for_client(uid, pid, conn=conn, now=started)
    # Client remaining must stay on the batch curve (never serial amount×unit).
    assert q['queue'][0]['order_remaining'] < qty * unit
    assert abs(int(q['queue'][0]['order_remaining']) - expected) <= max(1, unit)
    conn.close()

def test_defense_stock_is_planet_scoped(defense_db):
    conn = db()
    uid = _player(conn=conn)
    home = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    ok, reason, extra = colonize_planet(uid, name='Outpost', galaxy=1, system=301, position=8, conn=conn, allow_legacy_coordinates=True, source='test')
    assert ok, reason
    colony = int(extra['planet_id'])
    cur = conn.cursor()
    _fund_planet(cur, home)
    _fund_planet(cur, colony)
    _grant_defense_prereqs(cur, home, uid)
    _grant_defense_prereqs(cur, colony, uid)
    conn.commit()
    ok, reason, _ = build_defense(player_id=uid, planet_id=home, defense_key='sentinel_turret', amount=1, conn=conn)
    assert ok, reason
    cur.execute('UPDATE defense_queue SET finish_at = ? WHERE planet_id = ?;', (time.time() - 1, home))
    conn.commit()
    finish_due_defense_jobs_for_planet(conn, home, uid, now=time.time())
    assert get_planet_defense(home, conn=conn).get('sentinel_turret', 0) >= 1
    assert get_planet_defense(colony, conn=conn).get('sentinel_turret', 0) == 0
    conn.close()

def test_cancel_first_job_reschedules_follower(defense_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _grant_defense_prereqs(cur, pid, uid)
    conn.commit()
    now = time.time()
    ok1, _, _ = build_defense(player_id=uid, planet_id=pid, defense_key='sentinel_turret', amount=1, conn=conn)
    ok2, _, _ = build_defense(player_id=uid, planet_id=pid, defense_key='sentinel_turret', amount=1, conn=conn)
    assert ok1 and ok2
    rows_before = list_defense_queue_rows(pid, conn=conn)
    assert len(rows_before) == 2
    follower_id = int(rows_before[1]['id'])
    follower_finish_before = float(rows_before[1]['finish_at'])
    ok_cancel, reason_cancel = cancel_defense_job(player_id=uid, planet_id=pid, job_id=int(rows_before[0]['id']), conn=conn)
    assert ok_cancel, reason_cancel
    conn.commit()
    rows_after = list_defense_queue_rows(pid, conn=conn)
    assert len(rows_after) == 1
    assert int(rows_after[0]['id']) == follower_id
    assert float(rows_after[0]['started_at']) <= now + 2
    assert float(rows_after[0]['finish_at']) <= follower_finish_before + 2
    conn.close()

def test_api_defense_build_returns_state(defense_db, monkeypatch):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _grant_defense_prereqs(cur, pid, uid)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post('/api/defense/build', json={'defense_key': 'sentinel_turret', 'amount': 1, 'planet_id': pid}, headers={'Content-Type': 'application/json'})
    assert res.status_code == 200
    data = res.get_json()
    assert data['ok'] is True
    assert 'state' in data
    assert data['state']['ok'] is True
    assert 'queue' in data
    assert 'defenses' in data
    assert data['queue']['summary']['count'] >= 1

def test_main_js_defense_uses_apply_action_state_and_cleanup():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / 'static' / 'main.js').read_text(encoding='utf-8')
    assert 'GC.registerCleanup(stopDefenseTimers)' in src
    assert '"/api/defense/build"' in src
    assert '"/api/defense/cancel"' in src
    assert 'applyActionState(res, "defense_build")' in src
    assert 'applyActionState(res, "defense_cancel")' in src
    assert 'GC.modules.defense = initDefense' in src

def test_locked_defense_catalog_exposes_requirements_items(defense_db):
    from game.defense_page import _locked_defense_catalog
    from game.models import get_homeworld
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_homeworld(uid, conn=conn)['id'])
    cur = conn.cursor()
    cur.execute('UPDATE planet_buildings SET defense_factory = 1 WHERE planet_id = ?;', (pid,))
    cur.execute('DELETE FROM research_levels WHERE user_id = ?;', (uid,))
    conn.commit()
    locked = _locked_defense_catalog(uid, pid, 1, conn=conn)
    sentinel = next((row for row in locked if row['defense_key'] == 'sentinel_turret'), None)
    assert sentinel is not None
    items = sentinel.get('requirements_items') or []
    assert any((item.get('key') == 'weapon_tech' and (not item.get('met')) for item in items))
    conn.close()


def test_slug_launcher_costs_ferronite_only():
    from game.defense_defs import DEFENSE_ORDER, get_defense, unit_build_cost

    assert DEFENSE_ORDER[0] == "slug_launcher"
    cost = unit_build_cost("slug_launcher")
    assert int(cost.get("metal") or 0) == 2000
    assert int(cost.get("crystal") or 0) == 0
    assert int(cost.get("fuel_cells") or 0) == 0
    spec = get_defense("slug_launcher") or {}
    assert spec.get("requirements", {}).get("research") == {}


def test_slug_launcher_builds_without_weapon_tech(defense_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    cur.execute("UPDATE planet_buildings SET defense_factory = 1 WHERE planet_id = ?;", (pid,))
    cur.execute("DELETE FROM research_levels WHERE user_id = ?;", (uid,))
    conn.commit()
    ok, reason, result = build_defense(
        player_id=uid, planet_id=pid, defense_key="slug_launcher", amount=3, conn=conn
    )
    assert ok, reason
    assert result["defense_queue"]["summary"]["count"] == 1
    cur.execute("UPDATE defense_queue SET finish_at = ? WHERE planet_id = ?;", (time.time() - 1, pid))
    conn.commit()
    finish_due_defense_jobs_for_planet(conn, pid, uid, now=time.time())
    stock = get_planet_defense(pid, conn=conn)
    assert stock.get("slug_launcher", 0) >= 3
    conn.close()


def test_slug_launcher_rapid_fire_vs_light_ships():
    from game.defense_defs import defense_rapid_fire_multiplier

    assert defense_rapid_fire_multiplier("slug_launcher", "spark_drone") == 3
    assert defense_rapid_fire_multiplier("slug_launcher", "veil_probe") == 4
    assert defense_rapid_fire_multiplier("slug_launcher", "falcon_interceptor") == 1
