"""GC-900B — multi-colony collect logistics (batch + mission collect)."""
from __future__ import annotations
import json
import time
import uuid
import pytest
from game import db as gdb
from game.db import db
from game.fleet import collect_resources, count_active_fleet_slots, distribute_resources, get_fleet_slot_status, process_fleet_tick, send_fleet
from game.resources import get_storage_capacity
from game.models import get_planet_buildings, get_research_levels
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.planet_evolution.service import colonize_planet
from tests.test_fleet import _extra_colonies, _fund_planet, _planet_coords, _player, _second_colony, _seed_ships, _unlock_expansion_for_colonize, fleet_db
from game.fleet import build_distribute_route
from game.fleet_calc import build_collect_route, calculate_total_cargo

@pytest.fixture
def logistics_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'logistics_test.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_path))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    gdb._DB_PATH = None
    init_db()
    import migrate
    migrate.main()
    yield
    gdb._DB_PATH = None

def _hub_and_sources(uid: int, conn, *, sources: int=2):
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    colony_ids = []
    # Expansion Protocol gate: ensure colony slots are unlocked before colonizing.
    # Reuse the canonical helper from test_fleet (it unlocks then colonizes).
    # Unlock enough slots up-front for "Colony Two" (_second_colony) plus every
    # additional source/target colonized in the loop below (GC-STABILIZE-002).
    _unlock_expansion_for_colonize(conn, uid, slots=1 + sources)
    _second_colony(uid, conn=conn)
    for i in range(sources):
        # Avoid coordinate collision with _second_colony (uses position=5).
        pos = 6 + i
        ok, reason, extra = colonize_planet(uid, name=f'Colony {pos}', galaxy=1, system=300, position=pos, conn=conn, allow_legacy_coordinates=True, source='test')
        assert ok, reason
        cid = int(extra['planet_id'])
        _fund_planet(conn.cursor(), cid, metal=20000 + i * 1000, crystal=1000, fuel_cells=50000)
        colony_ids.append(cid)
    return (hub, colony_ids)

def _seed_collect_ships(uid: int, sources, ships_per_source, conn):
    for cid in sources:
        _seed_ships(cid, uid, dict(ships_per_source), conn=conn)

def _count_batches_and_movements(conn, player_id: int, *, batch_type: str='collect_resources', mission_type: str='transport') -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS c FROM fleet_batches WHERE player_id = ? AND batch_type = ?;', (int(player_id), batch_type))
    batches = int(cur.fetchone()['c'])
    cur.execute("\n        SELECT COUNT(*) AS c FROM fleet_movements\n        WHERE player_id = ? AND mission_type = ? AND status IN ('outbound', 'returning', 'holding');\n        ", (int(player_id), mission_type))
    active_mv = int(cur.fetchone()['c'])
    return (batches, active_mv)

def test_qa_happy_path_three_sources_batch_and_return(logistics_db):
    """Manual QA Fall 1 — N movements, batch, slots, resources on hub after return."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    for cid in sources:
        _fund_planet(conn.cursor(), cid, metal=25000, crystal=3000, fuel_cells=50000)
    _seed_collect_ships(uid, sources, {'mule_courier': 4}, conn)
    slots_before = get_fleet_slot_status(uid, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 4}, conn=conn)
    assert ok, reason
    assert len(payload['started']) == 3
    assert payload['batch']['batch_type'] == 'collect_resources'
    assert payload['batch']['total_fleets'] == 3
    batch_id = int(payload['batch']['id'])
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS c FROM fleet_movements WHERE parent_batch_id = ?;', (batch_id,))
    assert int(cur.fetchone()['c']) == 3
    for item in payload['started']:
        cur.execute('SELECT mission_type, origin_planet_id, target_planet_id, status, resources_json FROM fleet_movements WHERE id = ?;', (int(item['fleet_id']),))
        row = dict(cur.fetchone())
        assert row['mission_type'] == 'transport'
        assert int(row['origin_planet_id']) == int(item['source_planet_id'])
        assert int(row['target_planet_id']) == hub
        assert row['status'] == 'outbound'
        assert json.loads(row['resources_json']).get('metal', 0) > 0
    slots_after_send = get_fleet_slot_status(uid, conn=conn)
    assert slots_after_send['active'] == slots_before['active'] + 3
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before = int(cur.fetchone()['metal'])
    now = time.time()
    for item in payload['started']:
        fid = int(item['fleet_id'])
        cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (now - 1, fid))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    for item in payload['started']:
        fid = int(item['fleet_id'])
        cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fid))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    assert int(cur.fetchone()['metal']) > hub_before
    conn.close()

def test_qa_fleet_slots_full_no_partial_batch(logistics_db):
    """Manual QA Fall 2 — 3 sources, 0 free slots: no movements, no collect batch."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    g, s, p = _planet_coords(sources[0], conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(hub, uid, {'mule_courier': 30}, conn=conn)
    _seed_collect_ships(uid, sources, {'mule_courier': 2}, conn)
    max_slots = get_fleet_slot_status(uid, conn=conn)['max']
    for _ in range(max_slots):
        ok, _, _ = send_fleet(player_id=uid, origin_planet_id=hub, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1}, conn=conn)
        assert ok
    batches_before, mv_before = _count_batches_and_movements(conn, uid)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 6}, conn=conn)
    assert not ok
    assert reason == 'fleet_slots_full'
    assert payload is None
    batches_after, mv_after = _count_batches_and_movements(conn, uid)
    assert batches_after == batches_before
    assert mv_after == mv_before
    assert count_active_fleet_slots(uid, conn=conn) == max_slots
    conn.close()

def test_logistics_collect_caps_to_free_slots(logistics_db):
    """More selected colonies than free slots → launch only up to free (deterministic order)."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=4)
    cur = conn.cursor()
    for sid in sources:
        _fund_planet(cur, sid, metal=5000, crystal=500, fuel_cells=50000)
    _seed_collect_ships(uid, sources, {'mule_courier': 2}, conn)
    conn.commit()
    free = int(get_fleet_slot_status(uid, conn=conn)['free'])
    assert free >= 1
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 8}, conn=conn)
    assert ok, reason
    assert payload is not None
    assert len(payload['started']) == min(len(sources), free)
    cur.execute("SELECT COUNT(*) AS c FROM fleet_movements WHERE player_id = ? AND mission_type = 'transport' AND parent_batch_id IS NOT NULL;", (uid,))
    assert int(cur.fetchone()['c']) == min(len(sources), free)
    conn.close()

def test_qa_no_cargo_ships_no_batch(logistics_db):
    """Manual QA Fall 3 — combat-only selection leaves DB unchanged."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    _seed_collect_ships(uid, sources, {'falcon_interceptor': 5}, conn)
    batches_before, mv_before = _count_batches_and_movements(conn, uid)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'falcon_interceptor': 2}, conn=conn)
    assert not ok
    assert reason == 'no_cargo_ships'
    assert payload is None
    batches_after, mv_after = _count_batches_and_movements(conn, uid)
    assert batches_after == batches_before
    assert mv_after == mv_before
    conn.close()

def test_qa_hub_in_source_list_filtered(logistics_db):
    """Manual QA Fall 4 — hub in source_planet_ids is ignored, never collect hub→hub."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    _seed_collect_ships(uid, sources, {'mule_courier': 2}, conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[hub, sources[0], sources[1], hub], ships={'mule_courier': 2}, conn=conn)
    assert ok, reason
    assert len(payload['started']) == 2
    cur = conn.cursor()
    for item in payload['started']:
        cur.execute('SELECT origin_planet_id, target_planet_id FROM fleet_movements WHERE id = ?;', (int(item['fleet_id']),))
        row = dict(cur.fetchone())
        assert int(row['origin_planet_id']) != hub
        assert int(row['target_planet_id']) == hub
    ok2, reason2, _ = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[hub], ships={'mule_courier': 1}, conn=conn)
    assert not ok2
    assert reason2 == 'no_planets'
    conn.close()

def test_collect_logistics_requires_cargo_ships(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    _seed_collect_ships(uid, sources, {'falcon_interceptor': 5}, conn)
    conn.commit()
    ok, reason, _ = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'falcon_interceptor': 2}, conn=conn)
    assert not ok
    assert reason == 'no_cargo_ships'
    conn.close()

def test_collect_logistics_ship_split(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    _seed_collect_ships(uid, sources, {'mule_courier': 10}, conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=sources, ships={'mule_courier': 10}, conn=conn)
    assert ok, reason
    assert len(payload['started']) == 3
    cur = conn.cursor()
    for item in payload['started']:
        cur.execute('SELECT ships_json FROM fleet_movements WHERE id = ?;', (int(item['fleet_id']),))
        ships = json.loads(cur.fetchone()['ships_json'])
        assert ships.get('mule_courier') == 10
    conn.close()

def test_collect_logistics_respects_fleet_slots(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = sources[0]
    g, s, p = _planet_coords(source, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(hub, uid, {'mule_courier': 20}, conn=conn)
    _seed_ships(source, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    for _ in range(3):
        ok, reason, _ = send_fleet(player_id=uid, origin_planet_id=hub, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1}, conn=conn)
        assert ok, reason
    conn.commit()
    ok, reason, _ = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 2}, conn=conn)
    assert not ok
    assert reason == 'fleet_slots_full'
    conn.close()

def test_collect_logistics_pickup_and_return(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = sources[0]
    _seed_ships(source, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(player_id=uid, target_planet_id=hub, source_planet_ids=[source], ships={'mule_courier': 1}, conn=conn)
    assert ok, reason
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur = conn.cursor()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before = int(cur.fetchone()['metal'])
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (source,))
    source_after_send = int(cur.fetchone()['metal'])
    assert source_after_send < 20000  # resources debited at send
    now = time.time()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_after_arrival = int(cur.fetchone()['metal'])
    assert hub_after_arrival > hub_before
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    ships_back = __import__('game.fleet', fromlist=['get_planet_ships']).get_planet_ships(source, conn=conn)
    assert int(ships_back.get('mule_courier') or 0) >= 1
    conn.close()

def test_logistics_page_renders_collect_form(logistics_db, monkeypatch):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    _second_colony(uid, conn=conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.get('/logistics', follow_redirects=False)
    assert res.status_code == 302
    assert '/fleet' in (res.location or '')
    assert 'mode=collect' in (res.location or '')
    res = client.get('/logistics', follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'fleet-page' in html
    assert 'logistics-page' in html
    assert 'logistics-collect-form' in html
    assert 'logistics-tab-distribute' in html
    assert 'data-logistics-hub' in html
    assert 'data-logistics-select-all="collect"' in html
    assert 'logistics-auto-cargo-hint' in html
    assert 'logistics-help-btn' in html
    assert 'logistics-help-modal' in html
    assert 'data-logistics-hub-stock' in html
    assert 'data-logistics-colony-res="metal"' in html
    assert 'data-logistics-ship-input' not in html


def test_logistics_page_context_shows_funded_colony_resources(logistics_db):
    """Collect cards must expose live colony stock (not blank/zero for funded planets)."""
    from game.fleet import build_logistics_page_context

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    planets = get_planets_by_player(uid, conn=conn)
    hub_row = next(p for p in planets if int(p['id']) == hub)
    ctx = build_logistics_page_context(
        player_id=uid,
        planet_id=hub,
        planet=dict(hub_row),
        conn=conn,
    )
    conn.close()
    assert ctx.get('ready') is True
    by_id = {int(c['planet_id']): c for c in (ctx.get('colonies') or [])}
    assert sources[0] in by_id
    assert int(by_id[sources[0]]['resources']['metal']) >= 20000
    assert 'metal' in (ctx.get('hub_resources') or {})


def test_collect_logistics_api_returns_colony_resources(logistics_db):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    _seed_ships(sources[0], uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post(
        '/api/fleet/logistics/collect',
        json={
            'target_planet_id': hub,
            'source_planet_ids': sources,
            'ships': {'mule_courier': 2},
            'resources_mode': 'all',
            'request_id': str(uuid.uuid4()),
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    colony_resources = (body.get('data') or {}).get('colony_resources') or {}
    assert str(sources[0]) in colony_resources or sources[0] in colony_resources
    source_stock = colony_resources.get(str(sources[0])) or colony_resources.get(sources[0])
    assert int(source_stock['metal']) < 20000

def test_collect_logistics_api_returns_state(logistics_db):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    _seed_ships(sources[0], uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post('/api/fleet/logistics/collect', json={'target_planet_id': hub, 'source_planet_ids': sources, 'ships': {'mule_courier': 2}, 'resources_mode': 'all', 'request_id': str(uuid.uuid4())})
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    assert body.get('state', {}).get('ok') is True
    assert body.get('data', {}).get('batch', {}).get('batch_type') == 'collect_resources'

def test_logistics_preview_api_collect(logistics_db):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    _seed_collect_ships(uid, sources, {'mule_courier': 2}, conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post('/api/fleet/logistics/preview', json={'mode': 'collect', 'target_planet_id': hub, 'source_planet_ids': sources, 'ships': {'mule_courier': 2}, 'resources_mode': 'all', 'ships_selection_mode': 'manual'})
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    preview = body.get('data', {}).get('preview') or {}
    assert preview.get('mode') == 'collect'
    assert len(preview.get('legs') or []) == 2
    assert preview.get('can_launch') is True
    assert (preview.get('legs') or [])[0].get('resources') is not None
    assert int((preview.get('legs') or [])[0].get('cargo_used') or 0) > 0


def test_logistics_preview_collect_full_cargo_storage_cap(logistics_db):
    """700 mules + storage-capped stock must not false not_enough_resources (screenshot)."""
    import app as app_mod

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = int(sources[0])
    _seed_ships(source, uid, {'mule_courier': 700}, conn=conn)
    # Exact stock like storage-capped UI (2.4M each) — cargo 3.5M fills metal then crystal.
    _fund_planet(conn.cursor(), source, metal=2_400_000, crystal=2_400_000, fuel_cells=2_400_000)
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post(
        '/api/fleet/logistics/preview',
        json={
            'mode': 'collect',
            'target_planet_id': hub,
            'source_planet_ids': [source],
            'ships': {},
            'resources_mode': 'all',
            'ships_selection_mode': 'auto_cargo',
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    preview = body.get('data', {}).get('preview') or {}
    assert preview.get('block_reason') != 'not_enough_resources', preview
    assert preview.get('can_launch') is True, preview
    assert int(preview.get('cargo_used') or 0) == 3_500_000
    for leg in preview.get('legs') or []:
        assert leg.get('block_reason') != 'not_enough_resources'
        assert leg.get('can_send') is True
        res_map = leg.get('resources') or {}
        assert int(res_map.get('metal') or 0) == 2_400_000
        assert int(res_map.get('crystal') or 0) == 1_100_000


def test_update_planet_resources_matches_db_after_trade_debit(logistics_db):
    """Evolution trade debit after save_planet must not leave a stale-high planet dict."""
    from game.planet_evolution.service import create_trade_route
    from game.resources import update_planet_resources

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = int(sources[0])
    _fund_planet(conn.cursor(), source, metal=2_400_000, crystal=2_400_000, fuel_cells=2_400_000)
    ok_tr, reason_tr, _ = create_trade_route(
        uid, source, hub, 'metal', 100_000.0, conn=conn
    )
    assert ok_tr, reason_tr
    # Force evolution window so process_trade_routes runs inside update_planet_resources.
    stale_evo = time.time() - 7200.0
    conn.execute(
        "UPDATE planets SET last_evolution_tick = ?, last_update = ? WHERE id = ?;",
        (stale_evo, time.time(), source),
    )
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT * FROM planets WHERE id = ?;", (source,))
    row = dict(cur.fetchone())
    planet_live, *_rest = update_planet_resources(row, conn=conn, skip_queue_finish=True)
    cur.execute("SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;", (source,))
    db_row = dict(cur.fetchone())
    conn.close()

    assert int(float(planet_live['metal'])) == int(float(db_row['metal']))
    assert int(float(planet_live['crystal'])) == int(float(db_row['crystal']))
    # Trade moved metal off the source — returned dict must reflect the debit.
    assert int(float(planet_live['metal'])) < 2_400_000


def test_logistics_preview_collect_ticks_stale_source_stock(logistics_db):
    """SSR cards accrue production; preview must tick the same way or false no_resources_on_sources."""
    import app as app_mod
    from game.models import save_planet_buildings

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = int(sources[0])
    _seed_ships(source, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    conn.close()

    save_planet_buildings(source, {'metal_mine': 12, 'solar_plant': 8})

    conn = db()
    stale_at = time.time() - 7200.0
    conn.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ?, last_update = ? WHERE id = ?;",
        (200, 0, 50000, stale_at, source),
    )
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post(
        '/api/fleet/logistics/preview',
        json={
            'mode': 'collect',
            'target_planet_id': hub,
            'source_planet_ids': [source],
            'ships': {},
            'resources_mode': 'all',
            'ships_selection_mode': 'auto_cargo',
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    preview = body.get('data', {}).get('preview') or {}
    assert preview.get('block_reason') != 'no_resources_on_sources'
    assert preview.get('block_reason') != 'not_enough_resources'
    assert preview.get('can_launch') is True
    assert int(preview.get('cargo_used') or 0) > 200
    for leg in preview.get('legs') or []:
        assert leg.get('block_reason') != 'not_enough_resources'
        assert leg.get('can_send') is True

    # Collect must debit accrued stock (tick inside write txn), not only the stale 200 metal.
    res2 = client.post(
        '/api/fleet/logistics/collect',
        json={
            'target_planet_id': hub,
            'source_planet_ids': [source],
            'ships': {},
            'resources_mode': 'all',
            'ships_selection_mode': 'auto_cargo',
            'request_id': str(uuid.uuid4()),
        },
    )
    assert res2.status_code == 200
    body2 = res2.get_json()
    assert body2['ok'] is True, body2
    route = (body2.get('data') or {}).get('route') or []
    assert route
    loaded_metal = int((route[0].get('resources') or {}).get('metal') or 0)
    assert loaded_metal > 200


def test_logistics_preview_collect_after_trade_route_not_enough_false_positive(logistics_db):
    """Trade debit during tick must not plan cargo above remaining stock (false not_enough_resources)."""
    import app as app_mod
    from game.planet_evolution.service import create_trade_route

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = int(sources[0])
    _seed_ships(source, uid, {'mule_courier': 700}, conn=conn)
    _fund_planet(conn.cursor(), source, metal=2_400_000, crystal=2_400_000, fuel_cells=2_400_000)
    ok_tr, reason_tr, _ = create_trade_route(
        uid, source, hub, 'metal', 50_000.0, conn=conn
    )
    assert ok_tr, reason_tr
    stale_evo = time.time() - 3600.0
    conn.execute(
        "UPDATE planets SET last_evolution_tick = ?, last_update = ? WHERE id = ?;",
        (stale_evo, time.time(), source),
    )
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post(
        '/api/fleet/logistics/preview',
        json={
            'mode': 'collect',
            'target_planet_id': hub,
            'source_planet_ids': [source],
            'ships': {},
            'resources_mode': 'all',
            'ships_selection_mode': 'auto_cargo',
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    preview = body.get('data', {}).get('preview') or {}
    assert preview.get('block_reason') != 'not_enough_resources', preview
    assert preview.get('can_launch') is True, preview
    for leg in preview.get('legs') or []:
        assert leg.get('block_reason') != 'not_enough_resources', leg
        assert leg.get('can_send') is True


def test_logistics_preview_distribute_ships_only_shows_cargo_capacity(logistics_db):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    _seed_ships(hub, uid, {'mule_courier': 4}, conn=conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post(
        '/api/fleet/logistics/preview',
        json={
            'mode': 'distribute',
            'origin_planet_id': hub,
            'target_planet_ids': [target],
            'ships': {'mule_courier': 4},
            'resources_mode': 'equal',
            'resources': {'metal': 0, 'crystal': 0, 'fuel_cells': 0},
            'ships_selection_mode': 'manual',
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    preview = body.get('data', {}).get('preview') or {}
    assert preview.get('mode') == 'distribute'
    assert preview.get('cargo_total') == 20000
    assert preview.get('cargo_used') == 0
    assert preview.get('can_launch') is False
    assert preview.get('block_reason') == 'no_resources'
    assert len(preview.get('legs') or []) == 1

def test_logistics_preview_distribute_cargo_sums_requested_resources(logistics_db):
    """Preview cargo_used sums all requested resource types."""
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    target = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    buildings = get_planet_buildings(target, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    caps = get_storage_capacity(buildings, research=research, conn=conn)
    _fund_planet(cur, target, metal=int(caps['metal']), crystal=int(caps['crystal']), fuel_cells=0)
    _seed_ships(hub, uid, {'mule_courier': 10}, conn=conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post(
        '/api/fleet/logistics/preview',
        json={
            'mode': 'distribute',
            'origin_planet_id': hub,
            'target_planet_ids': [target],
            'ships': {'mule_courier': 10},
            'resources_mode': 'equal',
            'resources': {'metal': 50000, 'crystal': 50000, 'fuel_cells': 50000},
            'ships_selection_mode': 'manual',
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    preview = body.get('data', {}).get('preview') or {}
    assert preview.get('cargo_used') == 150000
    assert preview.get('cargo_total') == 50000
    leg = (preview.get('legs') or [])[0]
    assert leg.get('resources') == {'metal': 50000, 'crystal': 50000, 'fuel_cells': 50000}
    assert leg.get('resources_requested') == {'metal': 50000, 'crystal': 50000, 'fuel_cells': 50000}

def test_logistics_collect_credits_hub_despite_full_storage(logistics_db):
    """Collect logistics ignores hub storage caps — cargo always reaches the hub."""
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]['id'])
    source = _second_colony(uid, conn=conn)
    cur = conn.cursor()
    buildings = get_planet_buildings(hub, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    caps = get_storage_capacity(buildings, research=research, conn=conn)
    _fund_planet(cur, hub, metal=int(caps['metal']), crystal=int(caps['crystal']), fuel_cells=50000)
    _fund_planet(cur, source, metal=8000, crystal=0, fuel_cells=50000)
    _seed_ships(source, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[source],
        ships={'mule_courier': 1},
        conn=conn,
    )
    assert ok, reason
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before_arrival = int(cur.fetchone()['metal'])
    now = time.time()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    assert int(cur.fetchone()['metal']) > hub_before_arrival
    conn.close()

def test_distribute_happy_path_three_targets(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=3)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=100000, crystal=50000, fuel_cells=50000)
    _seed_ships(hub, uid, {'mule_courier': 12}, conn=conn)
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before = float(cur.fetchone()['metal'])
    conn.commit()
    ok, reason, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=targets, ships={'mule_courier': 9}, resources_mode='equal', resources={'metal': 9000, 'crystal': 3000, 'fuel_cells': 0}, conn=conn)
    assert ok, reason
    assert len(payload['started']) == 3
    assert payload['batch']['batch_type'] == 'distribute_resources'
    batch_id = int(payload['batch']['id'])
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS c FROM fleet_movements WHERE parent_batch_id = ?;', (batch_id,))
    assert int(cur.fetchone()['c']) == 3
    for item in payload['started']:
        cur.execute('SELECT mission_type, origin_planet_id, resources_json, status FROM fleet_movements WHERE id = ?;', (int(item['fleet_id']),))
        row = dict(cur.fetchone())
        assert row['mission_type'] == 'transport'
        assert int(row['origin_planet_id']) == hub
        assert json.loads(row['resources_json'])['metal'] > 0
        assert row['status'] == 'outbound'
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_after_send = float(cur.fetchone()['metal'])
    assert hub_after_send < hub_before
    conn.close()

def test_distribute_arrival_credits_target_empty_return(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=1)
    target = targets[0]
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=20000, fuel_cells=20000)
    _fund_planet(cur, target, metal=100, crystal=50)
    _seed_ships(hub, uid, {'mule_courier': 2}, conn=conn)
    conn.commit()
    ok, _, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 1}, resources_mode='equal', resources={'metal': 5000, 'crystal': 0, 'fuel_cells': 0}, conn=conn)
    assert ok
    fleet_id = int(payload['started'][0]['fleet_id'])
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (target,))
    target_before = int(cur.fetchone()['metal'])
    now = time.time()
    cur.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status, resources_json FROM fleet_movements WHERE id = ?;', (fleet_id,))
    mv = dict(cur.fetchone())
    assert mv['status'] == 'returning'
    assert json.loads(mv['resources_json']) in ({}, {'metal': 0, 'crystal': 0, 'fuel_cells': 0})
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (target,))
    assert int(cur.fetchone()['metal']) > target_before
    cur.execute('UPDATE fleet_movements SET return_at = ? WHERE id = ?;', (now - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute('SELECT status FROM fleet_movements WHERE id = ?;', (fleet_id,))
    assert cur.fetchone()['status'] == 'completed'
    conn.close()

def test_distribute_fleet_slots_full_no_batch(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=3)
    g, s, p = _planet_coords(targets[0], conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(hub, uid, {'mule_courier': 30}, conn=conn)
    max_slots = get_fleet_slot_status(uid, conn=conn)['max']
    for _ in range(max_slots):
        send_fleet(player_id=uid, origin_planet_id=hub, target_galaxy=g, target_system=s, target_position=p, mission_type='transport', ships={'mule_courier': 1}, resources={'metal': 1}, conn=conn)
    batches_before, mv_before = _count_batches_and_movements(conn, uid, batch_type='distribute_resources', mission_type='transport')
    conn.commit()
    ok, reason, _ = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=targets, ships={'mule_courier': 6}, resources_mode='equal', resources={'metal': 6000}, conn=conn)
    assert not ok
    assert reason == 'fleet_slots_full'
    batches_after, mv_after = _count_batches_and_movements(conn, uid, batch_type='distribute_resources', mission_type='transport')
    assert batches_after == batches_before
    assert mv_after == mv_before
    conn.close()

def test_distribute_no_cargo_no_batch(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=2)
    _seed_ships(hub, uid, {'falcon_interceptor': 5}, conn=conn)
    batches_before, mv_before = _count_batches_and_movements(conn, uid, batch_type='distribute_resources', mission_type='transport')
    conn.commit()
    ok, reason, _ = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=targets, ships={'falcon_interceptor': 2}, resources_mode='equal', resources={'metal': 1000}, conn=conn)
    assert not ok
    assert reason == 'no_cargo_ships'
    batches_after, mv_after = _count_batches_and_movements(conn, uid, batch_type='distribute_resources', mission_type='transport')
    assert batches_after == batches_before
    assert mv_after == mv_before
    conn.close()

def test_distribute_hub_in_targets_filtered(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=2)
    _fund_planet(conn.cursor(), hub, metal=50000, crystal=10000, fuel_cells=20000)
    _seed_ships(hub, uid, {'mule_courier': 6}, conn=conn)
    conn.commit()
    ok, reason, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[hub, targets[0], targets[1]], ships={'mule_courier': 4}, resources_mode='equal', resources={'metal': 4000}, conn=conn)
    assert ok, reason
    assert len(payload['started']) == 2
    cur = conn.cursor()
    for item in payload['started']:
        cur.execute('SELECT origin_planet_id, target_planet_id FROM fleet_movements WHERE id = ?;', (int(item['fleet_id']),))
        row = dict(cur.fetchone())
        assert int(row['origin_planet_id']) == hub
        assert int(row['target_planet_id']) != hub
    conn.close()

def test_distribute_ignores_storage_cap_and_debits_full_amount(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=2)
    target = targets[0]
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=100000, crystal=10000, fuel_cells=50000)
    buildings = get_planet_buildings(target, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    caps = get_storage_capacity(buildings, research=research)
    cur.execute('UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;', (max(0, int(caps['metal']) - 500), max(0, int(caps['crystal']) - 100), target))
    _seed_ships(hub, uid, {'mule_courier': 6}, conn=conn)
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_before = float(cur.fetchone()['metal'])
    conn.commit()
    ok, reason, payload = distribute_resources(player_id=uid, origin_planet_id=hub, target_planet_ids=[target], ships={'mule_courier': 5}, resources_mode='equal', resources={'metal': 20000, 'crystal': 2000, 'fuel_cells': 0}, conn=conn)
    assert ok, reason
    delivered = payload['delivered_total']
    assert delivered['metal'] == 20000
    assert delivered['crystal'] == 2000
    cur.execute('SELECT metal FROM planets WHERE id = ?;', (hub,))
    hub_after = float(cur.fetchone()['metal'])
    assert hub_before - hub_after == pytest.approx(delivered['metal'], rel=0, abs=1)
    conn.close()

def test_distribute_api_returns_state(logistics_db):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=1)
    _fund_planet(conn.cursor(), hub, metal=50000, crystal=10000, fuel_cells=20000)
    _seed_ships(hub, uid, {'mule_courier': 3}, conn=conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    res = client.post('/api/fleet/logistics/distribute', json={'origin_planet_id': hub, 'target_planet_ids': targets, 'ships': {'mule_courier': 2}, 'resources': {'metal': 2000, 'crystal': 500}, 'resources_mode': 'equal', 'request_id': str(uuid.uuid4())})
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    assert body.get('state', {}).get('ok') is True
    assert body.get('data', {}).get('batch', {}).get('batch_type') == 'distribute_resources'

def test_collect_auto_cargo_happy_path(logistics_db):
    """auto_cargo picks freighters from each source stock without client ships map."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    for cid in sources:
        _fund_planet(conn.cursor(), cid, metal=8000, crystal=1000, fuel_cells=50000)
    _seed_collect_ships(uid, sources, {'mule_courier': 3}, conn)
    conn.commit()
    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={},
        ships_selection_mode='auto_cargo',
        conn=conn,
    )
    assert ok, reason
    assert len(payload['started']) == 2
    assert payload['ships_selection_mode'] == 'auto_cargo'
    assert payload['ships_used'].get('mule_courier', 0) > 0
    assert payload['skipped'] == []
    conn.close()


def test_collect_auto_cargo_partial_when_few_freighters(logistics_db):
    """Sources without freighters are skipped; others still launch."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    for cid in sources:
        _fund_planet(conn.cursor(), cid, metal=20000, crystal=2000, fuel_cells=50000)
    _seed_ships(sources[0], uid, {'mule_courier': 2}, conn=conn)
    _seed_ships(sources[1], uid, {'mule_courier': 2}, conn=conn)
    # sources[2] has no freighters → skipped
    conn.commit()
    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={},
        ships_selection_mode='auto_cargo',
        conn=conn,
    )
    assert ok, reason
    assert len(payload['started']) == 2
    assert len(payload['skipped']) == 1
    assert sum(payload['ships_used'].values()) >= 2
    conn.close()


def test_collect_auto_cargo_no_ships(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    _fund_planet(conn.cursor(), sources[0], metal=5000, crystal=500, fuel_cells=50000)
    _seed_ships(sources[0], uid, {'falcon_interceptor': 5}, conn=conn)
    conn.commit()
    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={},
        ships_selection_mode='auto_cargo',
        conn=conn,
    )
    assert ok is False
    assert reason == 'no_ships_on_sources'
    assert payload is None
    conn.close()


def test_distribute_auto_cargo_happy_path(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=2)
    _fund_planet(conn.cursor(), hub, metal=100000, crystal=20000, fuel_cells=20000)
    _seed_ships(hub, uid, {'mule_courier': 8}, conn=conn)
    conn.commit()
    ok, reason, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        ships={},
        resources={'metal': 10000, 'crystal': 2000},
        resources_mode='equal',
        ships_selection_mode='auto_cargo',
        conn=conn,
    )
    assert ok, reason
    assert len(payload['started']) == 2
    assert payload['ships_selection_mode'] == 'auto_cargo'
    assert payload['delivered_total']['metal'] == 10000
    assert payload['delivered_total']['crystal'] == 2000
    conn.close()


def test_distribute_auto_cargo_clamps_when_not_enough_cargo(logistics_db):
    """Requested resources exceed freighter cargo → clamp and still launch."""
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=1)
    _fund_planet(conn.cursor(), hub, metal=500000, crystal=50000, fuel_cells=20000)
    _seed_ships(hub, uid, {'mule_courier': 1}, conn=conn)
    conn.commit()
    ok, reason, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        ships={},
        resources={'metal': 100000, 'crystal': 0, 'fuel_cells': 0},
        resources_mode='equal',
        ships_selection_mode='auto_cargo',
        conn=conn,
    )
    assert ok, reason
    assert payload['delivered_total']['metal'] == 5000
    assert payload['delivered_total']['crystal'] == 0
    conn.close()


def test_collect_auto_cargo_api_preview_and_submit(logistics_db):
    import app as app_mod
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    for cid in sources:
        _fund_planet(conn.cursor(), cid, metal=6000, crystal=500, fuel_cells=50000)
    _seed_collect_ships(uid, sources, {'mule_courier': 2}, conn)
    conn.commit()
    conn.close()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = uid
    preview = client.post(
        '/api/fleet/logistics/preview',
        json={
            'mode': 'collect',
            'target_planet_id': hub,
            'source_planet_ids': sources,
            'resources_mode': 'all',
            'ships_selection_mode': 'auto_cargo',
        },
    )
    assert preview.status_code == 200
    pbody = preview.get_json()
    assert pbody['ok'] is True
    prev = pbody['data']['preview']
    assert prev['can_launch'] is True
    assert prev['ships_used'].get('mule_courier', 0) > 0
    res = client.post(
        '/api/fleet/logistics/collect',
        json={
            'target_planet_id': hub,
            'source_planet_ids': sources,
            'resources_mode': 'all',
            'ships_selection_mode': 'auto_cargo',
            'request_id': str(uuid.uuid4()),
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body['ok'] is True
    assert body.get('data', {}).get('batch', {}).get('batch_type') == 'collect_resources'

def test_distribute_uses_all_free_slots_no_mass_expo_reserve(logistics_db):
    """Logistics must use every free slot — never MASS_EXPEDITION_SLOT_RESERVE."""
    from game.fleet_defs import MASS_EXPEDITION_SLOT_RESERVE
    from tests.test_fleet import _set_research_level

    conn = db()
    uid = _player(conn=conn)
    hub, _ = _hub_and_sources(uid, conn, sources=3)
    # nav 8 → 6 fleet slots; mass-expo would only use free-3=3
    cur = conn.cursor()
    _set_research_level(cur, uid, 'navigation_tech', 8)
    _fund_planet(cur, hub, metal=500000, crystal=50000, fuel_cells=50000)
    _seed_ships(hub, uid, {'mule_courier': 40}, conn=conn)
    conn.commit()

    targets = [int(p['id']) for p in get_planets_by_player(uid, conn=conn) if int(p['id']) != hub]
    assert len(targets) >= 4
    slots = get_fleet_slot_status(uid, conn=conn)
    free = int(slots['free'])
    assert free == 6
    assert free > MASS_EXPEDITION_SLOT_RESERVE

    ok, reason, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        ships={},
        resources={'metal': 12000, 'crystal': 0},
        resources_mode='equal',
        ships_selection_mode='auto_cargo',
        conn=conn,
    )
    assert ok, reason
    started = len(payload['started'])
    # Must launch min(targets, free) — not free - MASS_EXPEDITION_SLOT_RESERVE
    assert started == min(len(targets), free)
    assert started > max(0, free - MASS_EXPEDITION_SLOT_RESERVE)
    conn.close()


def test_logistics_slots_capped_status_uses_tf_for_repeated_placeholders():
    """Locale repeats launching; String.replace only fills the first occurrence."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "main.js").read_text(encoding="utf-8")
    de = json.loads((root / "locales" / "de.json").read_text(encoding="utf-8"))
    en = json.loads((root / "locales" / "en.json").read_text(encoding="utf-8"))
    for loc in (de, en):
        tpl = loc["logistics_preview_slots_capped"]
        assert tpl.count("%(launching)s") >= 2
        assert "%(selected)s" in tpl and "%(skipped)s" in tpl
    idx = js.index("logistics_preview_slots_capped")
    chunk = js[idx - 80 : idx + 280]
    assert "tf(" in chunk
    assert '.replace("%(launching)s"' not in chunk


def test_logistics_bind_once_does_not_reset_on_cleanup():
    """PJAX cleanup must not re-arm document listeners (nav lag / duplicate submits)."""
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "main.js").read_text(encoding="utf-8")
    bind_idx = js.index("function bindLogisticsOnce()")
    bind_chunk = js[bind_idx : bind_idx + 900]
    assert "GC._logisticsEventsBound" in bind_chunk
    assert "_logisticsBound = false" not in bind_chunk
    assert "registerCleanup" not in bind_chunk
    assert "body.gc-fleet-sheet-open .gc-bottom-nav" in (
        Path(__file__).resolve().parent.parent / "static" / "style.css"
    ).read_text(encoding="utf-8")


def _set_galaxy_directive(galaxy: int, primary: str) -> None:
    """Grants +50% cargo_multiplier via the 'logistics' galactic directive (see EffectResolver)."""
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO gd_galaxy_state (
                galaxy, primary_directive, secondary_directive,
                consecutive_primary_wins, updated_at
            ) VALUES (?, ?, NULL, 0, 0)
            ON CONFLICT(galaxy) DO UPDATE SET
                primary_directive = excluded.primary_directive,
                updated_at = excluded.updated_at;
            """,
            (int(galaxy), str(primary)),
        )
        conn.commit()
    finally:
        conn.close()


def test_build_collect_route_applies_cargo_multiplier(fleet_db):
    """GC-CARGO-FIX-001 — collect route must not silently drop the player's cargo bonus (bug: 'zusammenziehen' loaded ~3x less than transport)."""
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    source = _second_colony(uid, conn=conn)
    _fund_planet(conn.cursor(), source, metal=10_000_000, crystal=0, fuel_cells=1_000_000)
    conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT * FROM planets WHERE id IN (?, ?);", (hub, source))
    rows = {int(r["id"]): dict(r) for r in cur.fetchall()}
    galaxy = int(rows[source]["galaxy"])
    conn.close()

    route_kwargs = dict(
        origin_planet_id=hub,
        source_planet_ids=[source],
        planet_rows_by_id=rows,
        ships_stock_by_source={source: {"mule_courier": 10}},
        free_fleet_slots=5,
        player_id=uid,
        ships_selection_mode="manual",
        manual_ships={"mule_courier": 10},
    )

    ok_base, reason_base, legs_base = build_collect_route(**route_kwargs)
    assert ok_base, reason_base
    base_total = sum(int(v) for v in legs_base[0]["resources"].values())

    ok_boosted, reason_boosted, legs_boosted = build_collect_route(
        **route_kwargs, cargo_multiplier_by_galaxy={galaxy: 2.0}
    )
    assert ok_boosted, reason_boosted
    boosted_total = sum(int(v) for v in legs_boosted[0]["resources"].values())

    # Stock (10M) vastly exceeds base cargo cap (10 ships x 5000 = 50000), so both
    # legs are cargo-capped, not stock-capped — the 2x multiplier must show up directly.
    assert boosted_total == pytest.approx(base_total * 2, rel=0.01)
    assert boosted_total == calculate_total_cargo({"mule_courier": 10}, cargo_multiplier=2.0)


def test_build_distribute_route_applies_cargo_multiplier(fleet_db):
    """GC-CARGO-FIX-001 — distribute route must apply the same cargo bonus as collect/transport."""
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    target = _second_colony(uid, conn=conn)
    conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT * FROM planets WHERE id IN (?, ?);", (hub, target))
    rows = {int(r["id"]): dict(r) for r in cur.fetchall()}
    conn.close()

    route_kwargs = dict(
        origin_planet_id=hub,
        target_planet_ids=[target],
        planet_rows_by_id=rows,
        ships={"mule_courier": 10},
        resources={"metal": 10_000_000, "crystal": 0, "fuel_cells": 0},
        resources_mode="equal",
        free_fleet_slots=5,
        player_id=uid,
        conn=None,
        clamp_to_cargo=True,
    )

    ok_base, reason_base, legs_base, _ = build_distribute_route(**route_kwargs)
    assert ok_base, reason_base
    base_total = sum(int(v) for v in legs_base[0]["resources"].values())

    ok_boosted, reason_boosted, legs_boosted, _ = build_distribute_route(
        **route_kwargs, cargo_multiplier=2.0
    )
    assert ok_boosted, reason_boosted
    boosted_total = sum(int(v) for v in legs_boosted[0]["resources"].values())

    assert boosted_total == pytest.approx(base_total * 2, rel=0.01)
    assert boosted_total == calculate_total_cargo({"mule_courier": 10}, cargo_multiplier=2.0)


def test_collect_resources_applies_galaxy_directive_cargo_bonus(logistics_db):
    """End-to-end: 'logistics' directive (+50% cargo) must reach the real collect send, not just preview."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = sources[0]
    _fund_planet(conn.cursor(), source, metal=10_000_000, crystal=0, fuel_cells=1_000_000)
    _seed_collect_ships(uid, [source], {"mule_courier": 10}, conn)
    galaxy = _planet_coords(source, conn=conn)[0]
    conn.commit()
    conn.close()

    conn = db()
    ok, reason, payload = collect_resources(
        player_id=uid, target_planet_id=hub, source_planet_ids=[source],
        ships={"mule_courier": 10}, ships_selection_mode="manual", conn=conn,
    )
    assert ok, reason
    unboosted_total = sum(int(v or 0) for v in json.loads(
        conn.execute("SELECT resources_json FROM fleet_movements WHERE id = ?;", (int(payload["started"][0]["fleet_id"]),)).fetchone()["resources_json"]
    ).values())
    conn.commit()
    conn.close()

    _set_galaxy_directive(galaxy, "logistics")

    conn = db()
    _fund_planet(conn.cursor(), source, metal=10_000_000, crystal=0, fuel_cells=1_000_000)
    _seed_collect_ships(uid, [source], {"mule_courier": 10}, conn)
    conn.commit()
    ok2, reason2, payload2 = collect_resources(
        player_id=uid, target_planet_id=hub, source_planet_ids=[source],
        ships={"mule_courier": 10}, ships_selection_mode="manual", conn=conn,
    )
    assert ok2, reason2
    boosted_total = sum(int(v or 0) for v in json.loads(
        conn.execute("SELECT resources_json FROM fleet_movements WHERE id = ?;", (int(payload2["started"][0]["fleet_id"]),)).fetchone()["resources_json"]
    ).values())
    conn.commit()
    conn.close()

    assert boosted_total == pytest.approx(unboosted_total * 1.5, rel=0.02)


def test_distribute_resources_applies_galaxy_directive_cargo_bonus(logistics_db):
    """End-to-end: 'logistics' directive (+50% cargo) must reach the real distribute send.

    Manual mode has no clamp_to_cargo — 'equal' requests a fixed amount that must
    fit under cargo cap or the send is rejected. Request an amount between the
    unboosted cap (10 ships x 5000 = 50000) and the boosted cap (x1.5 = 75000) so
    the fix is proven by unboosted failing and boosted succeeding, not just a ratio.
    """
    conn = db()
    uid = _player(conn=conn)
    hub = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _unlock_expansion_for_colonize(conn, uid, slots=1)
    target = _second_colony(uid, conn=conn)
    _fund_planet(conn.cursor(), hub, metal=60_000, crystal=0, fuel_cells=1_000_000)
    _seed_ships(hub, uid, {"mule_courier": 10}, conn=conn)
    galaxy = _planet_coords(hub, conn=conn)[0]
    conn.commit()
    conn.close()

    conn = db()
    ok, reason, payload = distribute_resources(
        player_id=uid, origin_planet_id=hub, target_planet_ids=[target],
        ships={"mule_courier": 10}, resources={"metal": 60_000, "crystal": 0, "fuel_cells": 0},
        resources_mode="equal", ships_selection_mode="manual", conn=conn,
    )
    assert not ok
    assert reason == "not_enough_cargo"
    conn.close()

    _set_galaxy_directive(galaxy, "logistics")

    conn = db()
    ok2, reason2, payload2 = distribute_resources(
        player_id=uid, origin_planet_id=hub, target_planet_ids=[target],
        ships={"mule_courier": 10}, resources={"metal": 60_000, "crystal": 0, "fuel_cells": 0},
        resources_mode="equal", ships_selection_mode="manual", conn=conn,
    )
    assert ok2, reason2
    delivered_total = sum(int(v or 0) for v in json.loads(
        conn.execute("SELECT resources_json FROM fleet_movements WHERE id = ?;", (int(payload2["started"][0]["fleet_id"]),)).fetchone()["resources_json"]
    ).values())
    conn.commit()
    conn.close()

    assert delivered_total == pytest.approx(60_000, rel=0.02)
