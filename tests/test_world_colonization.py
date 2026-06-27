"""GC-582A — World colonization persistence tests."""
from __future__ import annotations
import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
from game.planet_evolution.world_colonization import COLONIZABLE_WORLD_TYPES, WorldKeyError, build_world_key, get_claim_by_world_key, is_colonizable_world_type, is_world_claimed, parse_world_key, reserve_world_claim, validate_world_colonize_target, world_colonization_schema_ready
ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / 'migrate.py'

@pytest.fixture()
def world_colonization_db(tmp_path, monkeypatch):
    db_file = tmp_path / 'world_colonization.db'
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

def _create_player() -> int:
    uname = f"wc_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


def _unlock_expansion(conn, player_id: int, *, hw_level: int = 25, tech: int = 6) -> None:
    from game.models import get_homeworld
    from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH

    hw = get_homeworld(player_id, conn=conn)
    assert hw
    conn.execute(
        "UPDATE planets SET planet_level = ? WHERE id = ?;",
        (int(hw_level), int(hw["id"])),
    )
    conn.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (int(player_id), INTERSTELLAR_EXPANSION_TECH, int(tech)),
    )
    conn.commit()

def test_migration_idempotent(world_colonization_db, monkeypatch):
    env = os.environ.copy()
    env['GC_DB_PATH'] = str(world_colonization_db)
    monkeypatch.setenv('GC_DB_PATH', str(world_colonization_db))
    for _ in range(2):
        result = subprocess.run([sys.executable, str(MIGRATE_SCRIPT)], cwd=str(ROOT), capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr or result.stdout
    from game.db import db
    conn = db()
    try:
        assert world_colonization_schema_ready(conn=conn)
        applied = {str(row['name']) for row in conn.execute('SELECT name FROM migration_history;').fetchall()}
        assert '058_world_colonization.sql' in applied
    finally:
        conn.close()

def test_build_world_key_is_stable():
    wx, wy = (1820.7, 2140.2)
    first = build_world_key(wx, wy)
    second = build_world_key(wx, wy)
    assert first == second
    assert first.startswith('field:')
    parsed = parse_world_key(first)
    assert parsed['world_x'] == pytest.approx(1820.0)
    assert parsed['world_y'] == pytest.approx(2140.0)
    assert parsed['world_type'] == strategic_world_type_for_coords(wx, wy)

def test_parse_world_key_rejects_invalid():
    with pytest.raises(WorldKeyError):
        parse_world_key('mining_world:1820:2140')
    with pytest.raises(WorldKeyError):
        parse_world_key('field:mining_world:bad:2140')

def _colonizable_coords() -> tuple[float, float]:
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_colonizable_world_type(wt):
                return (float(wx), float(wy))
    raise AssertionError('no colonizable coords in sample grid')

def test_reserve_world_claim_uniqueness(world_colonization_db):
    player_a = _create_player()
    player_b = _create_player()
    wx, wy = _colonizable_coords()
    from game.db import db
    conn = db()
    try:
        ok, reason, payload = reserve_world_claim(player_a, wx, wy, conn=conn)
        assert ok, reason
        assert payload
        world_key = payload['world_key']
        assert is_world_claimed(world_key, conn=conn)
        ok2, reason2, _ = reserve_world_claim(player_b, wx, wy, conn=conn)
        assert not ok2
        assert reason2 == 'world_already_claimed'
        claim = get_claim_by_world_key(world_key, conn=conn)
        assert claim
        assert int(claim['player_id']) == player_a
        assert claim['status'] == 'reserved'
        assert claim['planet_id'] is None
    finally:
        conn.close()

def test_non_colonizable_world_types_cannot_be_reserved(world_colonization_db):
    from game.db import db
    conn = db()
    try:
        for wx in range(500, 5000, 113):
            for wy in range(500, 5000, 97):
                wt = strategic_world_type_for_coords(float(wx), float(wy))
                if is_colonizable_world_type(wt):
                    continue
                ok, reason, _ = reserve_world_claim(_create_player(), float(wx), float(wy), conn=conn)
                assert not ok
                assert reason == 'world_not_colonizable'
                return
        pytest.skip('no non-colonizable coords found in sample grid')
    finally:
        conn.close()

def test_colonize_planet_blocks_coordinate_only_player_flow(world_colonization_db):
    player_id = _create_player()
    from game.db import db
    conn = db()
    try:
        ok, reason, extra = colonize_planet(
            player_id, name='Blocked Colony', galaxy=1, system=220, position=3, conn=conn
        )
        assert not ok
        assert reason == 'colonize_requires_expansion_site'
        assert extra is None
    finally:
        conn.close()

def test_colonize_planet_legacy_coordinates_explicit_test_source(world_colonization_db):
    player_id = _create_player()
    from game.db import db
    conn = db()
    try:
        ok, reason, extra = colonize_planet(
            player_id,
            name='Legacy Colony',
            galaxy=1,
            system=220,
            position=3,
            allow_legacy_coordinates=True,
            source='test',
            conn=conn,
        )
        assert ok, reason
        row = conn.execute('SELECT world_key, world_x, planet_role FROM planets WHERE id = ?;', (int(extra['planet_id']),)).fetchone()
        assert row['world_key'] is None
        assert row['world_x'] is None
        assert row['planet_role'] is None
    finally:
        conn.close()

def test_colonizable_types_match_spec():
    assert 'trade_world' in COLONIZABLE_WORLD_TYPES
    assert 'ruins_world' not in COLONIZABLE_WORLD_TYPES
    assert 'expedition_zone' not in COLONIZABLE_WORLD_TYPES
    assert 'anomaly_zone' not in COLONIZABLE_WORLD_TYPES

def _non_colonizable_coords() -> tuple[float, float, str]:
    for wx in range(500, 5000, 113):
        for wy in range(500, 5000, 97):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if not is_colonizable_world_type(wt):
                return (float(wx), float(wy), wt)
    raise AssertionError('no non-colonizable coords in sample grid')

def _fleet_player(conn):
    import time
    from game.fleet import add_planet_ships, process_fleet_tick, send_fleet
    from game.models import ensure_player_and_homeworld, get_planets_by_player
    player_id = _create_player()
    ensure_player_and_homeworld(player_id, player_name='Commander', conn=conn)
    pid = int(get_planets_by_player(player_id, conn=conn)[0]['id'])
    conn.execute('UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;', (pid,))
    add_planet_ships(pid, player_id, {'seed_ark': 1}, conn=conn)
    return (player_id, pid, send_fleet, process_fleet_tick, time)

def test_fleet_world_key_colonize_creates_planet_with_world_columns(world_colonization_db):
    from game.db import db
    wx, wy = _colonizable_coords()
    world_key = build_world_key(wx, wy)
    conn = db()
    try:
        player_id, pid, send_fleet, process_fleet_tick, time = _fleet_player(conn)
        _unlock_expansion(conn, player_id)
        conn.commit()
        ok, reason, result = send_fleet(player_id=player_id, origin_planet_id=pid, target_galaxy=1, target_system=1, target_position=1, mission_type='colonize', ships={'seed_ark': 1}, resources={'colony_name': 'Map Colony'}, world_key=world_key, conn=conn)
        assert ok, reason
        fleet_id = int(result['fleet']['id'])
        conn.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()
        claim = get_claim_by_world_key(world_key, conn=conn)
        assert claim
        assert claim['status'] == 'claimed'
        assert claim['planet_id'] is not None
        planet = conn.execute('\n            SELECT world_key, world_x, world_y, sector_x, sector_y, planet_role, origin_world_key\n            FROM planets WHERE id = ?;\n            ', (int(claim['planet_id']),)).fetchone()
        assert planet['world_key'] == world_key
        assert planet['world_x'] == pytest.approx(wx, abs=1.0)
        assert planet['world_y'] == pytest.approx(wy, abs=1.0)
        assert planet['sector_x'] == claim['sector_x']
        assert planet['sector_y'] == claim['sector_y']
        assert planet['planet_role'] == claim['planet_role']
        assert planet['origin_world_key'] == world_key
    finally:
        conn.close()

def test_fleet_world_key_colonize_blocks_double_claim(world_colonization_db):
    from game.db import db
    wx, wy = _colonizable_coords()
    world_key = build_world_key(wx, wy)
    conn = db()
    try:
        player_a, pid_a, send_fleet, process_fleet_tick, time = _fleet_player(conn)
        _unlock_expansion(conn, player_a)
        conn.commit()
        ok, reason, result = send_fleet(player_id=player_a, origin_planet_id=pid_a, target_galaxy=1, target_system=1, target_position=1, mission_type='colonize', ships={'seed_ark': 1}, world_key=world_key, conn=conn)
        assert ok, reason
        fleet_id = int(result['fleet']['id'])
        conn.execute('UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;', (time.time() - 1, fleet_id))
        conn.commit()
        process_fleet_tick(player_id=player_a, conn=conn)
        conn.commit()
        player_b, pid_b, _, _, _ = _fleet_player(conn)
        conn.commit()
        ok2, reason2, _ = send_fleet(player_id=player_b, origin_planet_id=pid_b, target_galaxy=1, target_system=1, target_position=1, mission_type='colonize', ships={'seed_ark': 1}, world_key=world_key, conn=conn)
        assert not ok2
        assert reason2 == 'world_already_claimed'
    finally:
        conn.close()

def test_fleet_world_key_rejects_non_colonizable_type(world_colonization_db):
    from game.db import db
    from game.fleet import send_fleet
    wx, wy, wt = _non_colonizable_coords()
    world_key = build_world_key(wx, wy, world_type=wt)
    conn = db()
    try:
        player_id, pid, _, _, _ = _fleet_player(conn)
        conn.commit()
        ok_validate, reason_validate, _ = validate_world_colonize_target(world_key, conn=conn)
        assert not ok_validate
        assert reason_validate == 'world_not_colonizable'
        ok, reason, _ = send_fleet(player_id=player_id, origin_planet_id=pid, target_galaxy=1, target_system=1, target_position=1, mission_type='colonize', ships={'seed_ark': 1}, world_key=world_key, conn=conn)
        assert not ok
        assert reason == 'world_not_colonizable'
    finally:
        conn.close()

def test_fleet_world_key_preview_does_not_break_classic_empty_slot(world_colonization_db):
    from game.db import db
    from game.fleet import build_fleet_send_preview, resolve_fleet_target
    conn = db()
    try:
        player_id, pid, _, _, _ = _fleet_player(conn)
        origin = conn.execute('SELECT * FROM planets WHERE id = ?;', (pid,)).fetchone()
        conn.commit()
        target = resolve_fleet_target(player_id, 1, 499, 12, conn=conn)
        assert target['target_type'] == 'empty_slot'
        assert target['allowed_missions'] == []
        preview = build_fleet_send_preview(player_id=player_id, origin_planet=dict(origin), target_galaxy=1, target_system=499, target_position=12, mission_type='colonize', ships={'seed_ark': 1}, resources={}, speed_percent=100, conn=conn)
        assert preview['can_send'] is False
        assert preview.get('block_reason') == 'colonize_requires_expansion_site'
    finally:
        conn.close()
