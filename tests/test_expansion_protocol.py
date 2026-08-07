"""GC-921–GC-929 — Expansion Protocol gates, outpost, establishment."""
from __future__ import annotations
import uuid
import pytest
from game.admin_balance import save_balance_settings
from game.db import db
from game.logic import check_planet_cap_available, get_planet_limit_block
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, get_planets_by_player, init_db
from game.planet_evolution.expansion_protocol import (
    INTERSTELLAR_EXPANSION_TECH,
    build_expansion_launch_checklist,
    effective_max_worlds_for_homeworld_level,
    evaluate_expansion_gates,
    expansion_slots_unlocked,
    is_outpost_planet,
    sync_establishment_state,
)
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

def test_colony_cap_blocked_until_evolution_slot_unlocked(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert not ok
        assert reason == 'planet_evolution_colony_slot_required'
    finally:
        conn.close()

def test_colony_cap_available_after_evolution_slot_unlock(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert ok, reason
    finally:
        conn.close()

def test_hw_level_unlocks_colony_slot_without_interstellar_tech(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        hw = get_homeworld(uid, conn=conn)
        conn.execute('UPDATE planets SET planet_level = 5 WHERE id = ?;', (int(hw['id']),))
        conn.commit()
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert ok, reason
    finally:
        conn.close()

def test_high_research_without_hw_level_does_not_unlock_colony_slot(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        conn.execute(
            "\n            INSERT INTO research_levels (user_id, tech_key, level) VALUES (?, 'navigation_tech', 12)\n            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n            ",
            (int(uid),),
        )
        conn.commit()
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert not ok
        assert reason == 'planet_evolution_colony_slot_required'
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
        assert reason_cap == 'colony_limit_reached'
        assert len(get_planets_by_player(uid, conn=conn)) == 2
        block = get_planet_limit_block(uid, conn=conn)
        assert block['at_admin_ceiling']
    finally:
        conn.close()

def _set_cap(value: int) -> None:
    settings, err = save_balance_settings({'max_colonies_per_player': int(value)})
    assert err is None, err

def test_limit_block_uses_hw_cap_not_admin_default(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        block = get_planet_limit_block(uid, conn=conn)
        assert block['current'] == 0
        assert block['max'] == 1
        assert block['effective_max_worlds'] == 1
        assert block['expansion_slots_unlocked'] == 0
        assert 'homeworld_level' in block
        assert 'expansion_tech_level' in block
    finally:
        conn.close()

def test_expansion_slots_unlocked_matrix():
    assert expansion_slots_unlocked(1) == 0
    assert expansion_slots_unlocked(4) == 0
    assert expansion_slots_unlocked(5) == 1
    assert expansion_slots_unlocked(9) == 1
    assert expansion_slots_unlocked(10) == 2
    assert effective_max_worlds_for_homeworld_level(10) == 3

def test_admin_cap_blocks_new_colonies_not_existing(expansion_protocol_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        hw = get_homeworld(uid, conn=conn)
        conn.execute('UPDATE planets SET planet_level = 25 WHERE id = ?;', (int(hw['id']),))
        conn.execute(
            '\n        INSERT INTO research_levels (user_id, tech_key, level)\n        VALUES (?, ?, ?)\n        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;\n        ',
            (int(uid), INTERSTELLAR_EXPANSION_TECH, 6),
        )
        conn.commit()
        _set_cap(3)
        from tests.conftest import mature_owned_colonies

        for i in range(2):
            ok, reason, _ = colonize_planet(
                uid,
                name=f'Col_{i}',
                galaxy=1,
                system=410 + i,
                position=1 + i,
                conn=conn,
                allow_legacy_coordinates=True,
                source='test',
            )
            assert ok, reason
            mature_owned_colonies(conn, uid)
        assert len(get_planets_by_player(uid, conn=conn)) == 3
        ok_cap, reason_cap = check_planet_cap_available(uid, conn=conn)
        assert not ok_cap
        assert reason_cap == 'colony_limit_reached'
        assert len(get_planets_by_player(uid, conn=conn)) == 3
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


def test_world_key_colony_builds_all_infrastructure(expansion_protocol_db):
    from game.buildings import queue_build_for_planet
    from game.models import get_planet_buildings, save_planet_buildings

    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        binding = _colonizable_binding()
        ok, reason, extra = colonize_planet(
            uid,
            name='Frontier Colony',
            galaxy=1,
            system=302,
            position=3,
            world_binding=binding,
            conn=conn,
        )
        assert ok, reason
        pid = int(extra['planet_id'])

        save_planet_buildings(
            pid,
            {
                'metal_mine': 4,
                'crystal_mine': 2,
                'solar_plant': 1,
                'command_center': 2,
                'orbital_shipyard': 2,
            },
        )
        conn.execute(
            'UPDATE planets SET metal = 500000, crystal = 500000 WHERE id = ?;',
            (pid,),
        )
        conn.commit()
        planet = dict(conn.execute('SELECT * FROM planets WHERE id = ?;', (pid,)).fetchone())
        buildings = get_planet_buildings(pid, conn=conn)

        for building_type in ('metal_storage', 'research_lab', 'orbital_shipyard', 'defense_factory'):
            ok_build, build_reason, payload = queue_build_for_planet(
                planet,
                buildings,
                building_type,
                user_id=uid,
            )
            assert build_reason not in (
                'outpost_building_restricted',
                'outpost_building_slots_full',
            ), (building_type, build_reason, payload)
            assert ok_build, (building_type, build_reason, payload)
            assert int(payload.get('job_id') or 0) > 0
    finally:
        conn.close()


def test_legacy_colony_without_evo_data_can_build_infrastructure(expansion_protocol_db):
    """Pre-EVO colonies (no world_key / missing EVO rows) must never hit outpost gates."""
    from game.buildings import queue_build_for_planet
    from game.models import get_planet_buildings, save_planet_buildings

    uid = _player()
    conn = db()
    try:
        _unlock_first_expansion(conn, uid)
        ok, reason, extra = colonize_planet(
            uid,
            name='Pre EVO Colony',
            conn=conn,
            allow_legacy_coordinates=True,
            source='test',
        )
        assert ok, reason
        pid = int(extra['planet_id'])

        conn.execute('DELETE FROM planet_dna WHERE planet_id = ?;', (pid,))
        conn.execute('DELETE FROM planet_culture WHERE planet_id = ?;', (pid,))
        conn.execute('DELETE FROM planet_mechanics WHERE planet_id = ?;', (pid,))
        conn.execute(
            """
            UPDATE planets
            SET dna_seed = 0, planet_level = 3, dna_reveal_tier = 1, last_evolution_tick = 0
            WHERE id = ?;
            """,
            (pid,),
        )
        conn.commit()

        row = conn.execute('SELECT world_key FROM planets WHERE id = ?;', (pid,)).fetchone()
        assert not row['world_key']

        save_planet_buildings(
            pid,
            {
                'metal_mine': 4,
                'crystal_mine': 2,
                'solar_plant': 1,
                'command_center': 2,
            },
        )
        conn.execute(
            'UPDATE planets SET metal = 500000, crystal = 500000 WHERE id = ?;',
            (pid,),
        )
        conn.commit()

        planet = dict(conn.execute('SELECT * FROM planets WHERE id = ?;', (pid,)).fetchone())
        buildings = get_planet_buildings(pid, conn=conn)

        for btype in ('metal_storage', 'research_lab', 'orbital_shipyard'):
            ok_build, build_reason, payload = queue_build_for_planet(
                planet,
                buildings,
                btype,
                user_id=uid,
            )
            assert ok_build, (btype, build_reason, payload)
            assert build_reason not in (
                'outpost_building_restricted',
                'outpost_building_slots_full',
            )
            assert int(payload.get('job_id') or 0) > 0
    finally:
        conn.close()
