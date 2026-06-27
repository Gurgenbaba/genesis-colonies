"""GC-921–GC-929 — Expansion Protocol gates, outpost, establishment."""
from __future__ import annotations
import uuid
import pytest
from game.admin_balance import save_balance_settings
from game.db import db
from game.logic import check_planet_cap_available, get_planet_limit_block
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, get_planets_by_player, init_db
from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH, build_expansion_launch_checklist, evaluate_expansion_gates, is_outpost_planet, sync_establishment_state
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.world_colonization import build_world_key, parse_world_key, sector_coords
from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
from game.planet_evolution.world_colonization import is_colonizable_world_type

@pytest.fixture
def expansion_protocol_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'expansion_protocol.db'
    monkeypatch.setenv('GC_DB_PATH', str(db_path))
    monkeypatch.setenv('GC_SKIP_MIGRATION_CHECK', '1')
    import game.db as gdb
    import game.models as models
    gdb._DB_PATH = None
    models.DB_PATH = str(db_path)
    init_db()
    import migrate
    migrate.main()
    yield
    gdb._DB_PATH = None

def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f'exproto_{uuid.uuid4().hex[:8]}', 'test-pass-123')
    assert ok, err
    uid = int(user['id'])
    ensure_player_and_homeworld(uid, player_name='ProtoTester', conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid

def _unlock_first_expansion(conn, uid: int) -> None:
    hw = get_homeworld(uid, conn=conn)
    assert hw
    conn.execute('UPDATE planets SET planet_level = 5 WHERE id = ?;', (int(hw['id']),))
    conn.execute('\n        INSERT INTO research_levels (user_id, tech_key, level)\n        VALUES (?, ?, ?)\n        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n        ', (int(uid), INTERSTELLAR_EXPANSION_TECH, 1))
    conn.commit()
_coord = 700

def _colonizable_binding():
    global _coord
    for wx in range(_coord, 5000, 40):
        for wy in range(700, 5000, 40):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_colonizable_world_type(wt):
                _coord = wx + 40
                world_key = build_world_key(float(wx), float(wy), world_type=wt)
                parsed = parse_world_key(world_key)
                sx, sy = sector_coords(float(wx), float(wy))
                return {'world_key': world_key, 'world_x': float(wx), 'world_y': float(wy), 'sector_x': int(sx), 'sector_y': int(sy), 'planet_role': parsed['planet_role'], 'origin_world_key': world_key}
    raise AssertionError('no colonizable coords')

def test_expansion_blocked_without_gates(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert not ok
        assert reason == 'expansion_gate_homeworld_level'
    finally:
        conn.close()

def test_expansion_allowed_with_dual_gate(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert ok, reason
    finally:
        conn.close()

def test_interstellar_tech_gate_blocks_when_hw_ready(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        hw = get_homeworld(uid, conn=conn)
        conn.execute('UPDATE planets SET planet_level = 5 WHERE id = ?;', (int(hw['id']),))
        conn.commit()
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert not ok
        assert reason == 'expansion_gate_interstellar_tech'
    finally:
        conn.close()

def test_world_binding_starts_at_development_stage_zero(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        binding = _colonizable_binding()
        ok, reason, extra = colonize_planet(uid, name='Frontier Alpha', galaxy=1, system=300, position=1, world_binding=binding, conn=conn)
        assert ok, reason
        pid = int(extra['planet_id'])
        row = conn.execute('SELECT planet_level, dna_reveal_tier, world_key FROM planets WHERE id = ?;', (pid,)).fetchone()
        assert int(row['planet_level']) == 0
        assert int(row['dna_reveal_tier']) == 0
        assert row['world_key']
        assert is_outpost_planet(pid, conn=conn)
    finally:
        conn.close()

def test_establishment_reveals_dna_and_promotes_level(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        binding = _colonizable_binding()
        ok, reason, extra = colonize_planet(uid, name='Frontier Beta', galaxy=1, system=301, position=2, world_binding=binding, conn=conn)
        assert ok, reason
        pid = int(extra['planet_id'])
        conn.execute('\n            UPDATE planet_buildings\n            SET command_center = 1, solar_plant = 1, radar_array = 1\n            WHERE planet_id = ?;\n            ', (pid,))
        conn.commit()
        assert sync_establishment_state(pid, conn=conn)
        conn.commit()
        row = conn.execute('SELECT planet_level, dna_reveal_tier FROM planets WHERE id = ?;', (pid,)).fetchone()
        assert int(row['dna_reveal_tier']) >= 1
        assert int(row['planet_level']) >= 1
        assert not is_outpost_planet(pid, conn=conn)
    finally:
        conn.close()

def test_launch_checklist_requires_seed_ark(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        checklist = build_expansion_launch_checklist(uid, conn=conn)
        assert checklist['items']
        assert not checklist['can_launch']
        seed_item = next((i for i in checklist['items'] if i['key'] == 'seed_ark'))
        assert seed_item['met'] is False
    finally:
        conn.close()

def test_admin_ceiling_grandfathering(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        conn.execute('UPDATE planets SET planet_level = 25 WHERE player_id = ? AND is_homeworld = 1;', (uid,))
        conn.execute('\n            INSERT INTO research_levels (user_id, tech_key, level)\n            VALUES (?, ?, 6)\n            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n            ', (int(uid), INTERSTELLAR_EXPANSION_TECH))
        conn.commit()
        _set_cap(2)
        ok, reason, _ = colonize_planet(uid, name='Legacy_0', galaxy=1, system=400, position=1, conn=conn, allow_legacy_coordinates=True, source='test')
        assert ok, reason
        assert len(get_planets_by_player(uid, conn=conn)) == 2
        _set_cap(1)
        ok_cap, reason_cap = check_planet_cap_available(uid, conn=conn)
        assert not ok_cap
        assert reason_cap == 'expansion_admin_ceiling_reached'
        assert len(get_planets_by_player(uid, conn=conn)) == 2
        block = get_planet_limit_block(uid, conn=conn)
        assert block['at_admin_ceiling']
    finally:
        conn.close()

def _set_cap(value: int) -> None:
    settings, err = save_balance_settings({'max_colonies_per_player': int(value)})
    assert err is None, err

def test_limit_block_uses_gate_not_slot_counter(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        block = get_planet_limit_block(uid, conn=conn)
        assert block['current'] == 0
        assert block['max'] is None
        assert 'homeworld_level' in block
        assert 'expansion_tech_level' in block
    finally:
        conn.close()

def test_evaluate_gates_meta(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        ok, reason, meta = evaluate_expansion_gates(uid, conn=conn)
        assert not ok
        assert reason == 'expansion_gate_homeworld_level'
        assert meta['required_homeworld_level'] == 5
        assert meta['required_expansion_tech'] == 1
    finally:
        conn.close()
