"""Fuel Cells (Brennzellen) resource bar and game-state tests."""
from __future__ import annotations
import time
import uuid
from pathlib import Path
import pytest
import game.db as gdb
from game.db import db
from game.fleet import send_fleet
from game.fleet_defs import FLEET_FUEL_RESOURCE
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, get_planets_by_player, init_db
from game.planet_evolution.service import colonize_planet
from game.shipyard import build_ship
from game.effects import EffectResolver
from game.economy_balance import STORAGE_BASE_CAPACITY
from game.resources import get_storage_capacity, update_planet_resources

@pytest.fixture
def fuel_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'fuel_res.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_path))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
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
    ok, err, user = create_user(f'fc_{uuid.uuid4().hex[:8]}', 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, conn=conn)
    # GC-976A: colonize_planet() needs an unlocked evolution slot.
    from conftest import unlock_colony_slots
    unlock_colony_slots(conn, int(get_homeworld(player_id=uid, conn=conn)['id']), slots=1)
    if own:
        conn.commit()
        conn.close()
    return uid

def test_game_state_includes_fuel_storage_cap(fuel_db, monkeypatch):
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    uid = _player()
    from game.models import get_homeworld, save_planet_buildings
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet['id']), {'fuel_storage': 1, 'fuel_cell_plant': 2, 'solar_plant': 3})
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/game-state')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    fuel_cap = int(data['storage'].get('fuel_cells') or 0)
    assert fuel_cap > 0
    assert fuel_cap == int(data['resources']['storage']['fuel_cells'])

def test_game_state_storage_caps_match_effect_resolver(fuel_db, monkeypatch):
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    uid = _player()
    from game.models import get_research_levels, save_planet_buildings, save_research_level
    planet = get_homeworld(player_id=uid)
    levels = {
        'metal_storage': 18,
        'crystal_storage': 18,
        'fuel_storage': 18,
        'fuel_cell_plant': 4,
        'solar_plant': 8,
    }
    save_planet_buildings(int(planet['id']), levels)
    save_research_level('storage_tech', 20, uid)
    expected = EffectResolver(levels, get_research_levels(uid)).get_storage_capacity()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/game-state')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert {k: int(v) for k, v in data['storage'].items()} == expected
    assert {k: int(v) for k, v in data['resources']['storage'].items()} == expected

def test_game_state_includes_fuel_cells(fuel_db, monkeypatch):
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    uid = _player()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/game-state')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert 'fuel_cells' in data['player']
    assert 'fuel_cells' in data['resources']
    assert float(data['player']['fuel_cells']) >= 0
    assert 'fuel_cell_plant' in data.get('production_per_hour', {})

def test_fuel_cells_base_capacity_without_fuel_storage(fuel_db):
    uid = _player()
    planet = get_homeworld(player_id=uid)
    from game.models import save_planet_buildings
    save_planet_buildings(int(planet['id']), {'fuel_cell_plant': 3, 'solar_plant': 5})
    buildings = {'fuel_cell_plant': 3, 'solar_plant': 5}
    caps = get_storage_capacity(buildings)
    assert caps['fuel_cells'] == STORAGE_BASE_CAPACITY
    er = EffectResolver(buildings, {})
    assert er.get_storage_capacity()['fuel_cells'] == STORAGE_BASE_CAPACITY

def test_fuel_production_accumulates_to_base_cap_without_fuel_storage(fuel_db):
    conn = db()
    uid = _player(conn=conn)
    planet = dict(get_homeworld(player_id=uid, conn=conn))
    pid = int(planet['id'])
    cur = conn.cursor()
    cur.execute(
        'UPDATE planet_buildings SET fuel_cell_plant = 3, solar_plant = 5, fuel_storage = 0 WHERE planet_id = ?;',
        (pid,),
    )
    cur.execute('UPDATE planets SET fuel_cells = 0, last_update = ? WHERE id = ?;', (time.time() - 3600, pid))
    conn.commit()
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    planet = dict(cur.fetchone())
    update_planet_resources(planet, conn=conn, skip_queue_finish=True)
    conn.commit()
    after = int(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    conn.close()
    assert after > 0
    assert after <= STORAGE_BASE_CAPACITY

def test_game_state_includes_base_fuel_cap_without_fuel_storage(fuel_db, monkeypatch):
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    uid = _player()
    from game.models import save_planet_buildings
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet['id']), {'fuel_cell_plant': 2, 'solar_plant': 3})
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/game-state')
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    fuel_cap = int(data['storage'].get('fuel_cells') or 0)
    assert fuel_cap == STORAGE_BASE_CAPACITY
    assert fuel_cap == int(data['resources']['storage']['fuel_cells'])

def test_base_template_shows_fuel_cells_panel():
    root = Path(__file__).resolve().parent.parent
    html = (root / 'templates' / 'base.html').read_text(encoding='utf-8')
    css = (root / 'static' / 'style.css').read_text(encoding='utf-8')
    assert 'hud-res-fuel-cells' in html
    assert 'res-value fuel_cells' in html
    assert 'res-cap fuel_cells' in html
    assert "render_hud_capacity_bar('fuel_cells'" in html
    assert 'data-hud-capacity="{{ res_key }}"' in (root / 'templates' / 'partials' / 'progression_cards.html').read_text(encoding='utf-8')
    assert 'hud-res-no-storage' not in html
    assert 'fc_cap <= 0' not in html
    assert 'repeat(4, minmax(0, 1fr))' in css
    metal_block = html.split('hud-res-metal')[1].split('hud-res-crystal')[0]
    fuel_block = html.split('hud-res-fuel-cells')[1].split('hud-res-energy')[0]
    assert 'hud-res-cap-line' in metal_block
    assert 'hud-res-cap-line' in fuel_block
    assert '{% if fc_cap' not in fuel_block

def test_main_js_patches_fuel_cells():
    root = Path(__file__).resolve().parent.parent
    js = (root / 'static' / 'main.js').read_text(encoding='utf-8')
    assert 'function applyGameStateData' in js
    assert 'function patchShellHudLiveResources' in js
    assert 'bar.querySelectorAll(".res-value.fuel_cells")' in js
    assert 'bar.querySelectorAll(".res-cap.fuel_cells")' in js
    assert 'function patchHudCapacityBars' in js
    assert 'patchHudCapacityBar("metal"' in js
    assert 'prodFuelCells' in js
    assert 'buildingIconUrl' in js
    assert 'syncResourceLiveBaseline' in js
    assert 'tickLiveResourceBar' in js
    assert 'projectLiveResourceAmounts' in js
    assert 'projectLiveResourceAmount' in js
    assert 'Overflow (trader/scrapyard/rewards)' in js

def test_fuel_overflow_not_trimmed_on_production_tick(fuel_db):
    from game.resources import update_planet_resources
    conn = db()
    uid = _player(conn=conn)
    planet = dict(get_homeworld(player_id=uid, conn=conn))
    pid = int(planet['id'])
    overflow_amount = 5000000
    cur = conn.cursor()
    cur.execute('UPDATE planet_buildings SET fuel_cell_plant = 10, solar_plant = 10 WHERE planet_id = ?;', (pid,))
    cur.execute('UPDATE planets SET fuel_cells = ?, last_update = ? WHERE id = ?;', (overflow_amount, time.time() - 7200, pid))
    conn.commit()
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    planet = dict(cur.fetchone())
    update_planet_resources(planet, conn=conn)
    conn.commit()
    after = int(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    conn.close()
    assert after >= overflow_amount

def test_fuel_cell_plant_production_increases_balance(fuel_db):
    from game.resources import update_planet_resources
    conn = db()
    uid = _player(conn=conn)
    planet = dict(get_homeworld(player_id=uid, conn=conn))
    pid = int(planet['id'])
    cur = conn.cursor()
    cur.execute('UPDATE planet_buildings SET fuel_cell_plant = 2, fuel_storage = 1, metal_mine = 0, crystal_mine = 0, solar_plant = 5 WHERE planet_id = ?;', (pid,))
    cur.execute('UPDATE planets SET fuel_cells = 100, last_update = ? WHERE id = ?;', (time.time() - 3600, pid))
    conn.commit()
    before = float(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    cur.execute('SELECT * FROM planets WHERE id = ?;', (pid,))
    planet = dict(cur.fetchone())
    update_planet_resources(planet, conn=conn)
    conn.commit()
    after = float(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    conn.close()
    assert after >= before

def test_fleet_send_reduces_fuel_cells(fuel_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 50000 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;', (pid,))
    conn.commit()
    from game.fleet import add_planet_ships
    add_planet_ships(pid, uid, {'mule_courier': 5}, conn=conn)
    ok_col, _, extra = colonize_planet(uid, name='Fuel Test II', galaxy=1, system=301, position=8, conn=conn, allow_legacy_coordinates=True, source='test')
    assert ok_col, extra
    colony2 = int(extra['planet_id'])
    cur.execute('SELECT galaxy, system, position FROM planets WHERE id = ?;', (colony2,))
    row = cur.fetchone()
    tg, ts, tp = (int(row['galaxy']), int(row['system']), int(row['position']))
    before = float(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=pid, target_galaxy=tg, target_system=ts, target_position=tp, mission_type='transport', ships={'mule_courier': 1}, resources={}, speed_percent=100, conn=conn)
    assert ok, reason
    after = float(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    conn.close()
    assert FLEET_FUEL_RESOURCE == 'fuel_cells'
    assert after < before

def test_shipyard_build_reduces_fuel_cells(fuel_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    cur = conn.cursor()
    cur.execute('UPDATE planets SET metal = 200000, crystal = 200000, fuel_cells = 500 WHERE id = ?;', (pid,))
    cur.execute('UPDATE planet_buildings SET orbital_shipyard = 2 WHERE planet_id = ?;', (pid,))
    cur.executemany('INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, ?, ?);', [(uid, 'engine_tech', 3), (uid, 'navigation_tech', 3)])
    conn.commit()
    before = float(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    ok, reason, _ = build_ship(player_id=uid, planet_id=pid, ship_key='solar_skiff', amount=1, conn=conn)
    assert ok, reason
    after = float(cur.execute('SELECT fuel_cells FROM planets WHERE id = ?;', (pid,)).fetchone()['fuel_cells'])
    conn.close()
    assert after < before

def test_missing_fuel_cells_defaults_safe(fuel_db, monkeypatch):
    import importlib
    import app as app_mod
    importlib.reload(app_mod)
    uid = _player()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    r = client.get('/api/game-state')
    data = r.get_json()
    assert data['ok'] is True
    assert float(data['player'].get('fuel_cells', 0)) >= 0
    assert float(data['resources'].get('fuel_cells', 0)) >= 0
