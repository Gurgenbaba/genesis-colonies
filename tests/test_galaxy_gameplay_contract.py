"""GC-976 — Galaxy-first gameplay contract (CORE_ARCHITECTURE §18, PLANET_EVOLUTION.md)."""
from __future__ import annotations

import inspect
import uuid

import pytest

from game.db import db
from game.fleet import build_fleet_send_preview
from game.logic import check_planet_cap_available
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, get_planets_by_player, init_db
from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
from game.planet_evolution.world_colonization import (
    build_world_key,
    is_colonizable_world_type,
    parse_world_key,
    sector_coords,
)

# Reasons that must never surface in normal Galaxy build / colonize flows.
FORBIDDEN_GALAXY_BLOCK_REASONS = frozenset(
    {
        "colonize_requires_expansion_site",
        "outpost_building_restricted",
        "outpost_building_slots_full",
        "expansion_gate_homeworld_level",
        "expansion_gate_expansion_tech",
        "expansion_gate_world_type",
        "expansion_slot_cap_reached",
        "expansion_admin_ceiling_reached",
    }
)

NORMAL_INFRA_BUILDINGS = (
    "metal_storage",
    "research_lab",
    "orbital_shipyard",
    "defense_factory",
)


@pytest.fixture
def galaxy_contract_db(tmp_path, monkeypatch):
    db_path = tmp_path / "galaxy_contract.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import game.db as gdb
    import game.models as models

    gdb._DB_PATH = None
    models.DB_PATH = str(db_path)
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"gc976_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="GalaxyTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _unlock_first_colony_slot(conn, uid: int) -> None:
    hw = get_homeworld(uid, conn=conn)
    assert hw
    conn.execute(
        "UPDATE planets SET planet_level = 5 WHERE id = ?;",
        (int(hw["id"]),),
    )
    conn.commit()


def _colonizable_binding() -> dict:
    for wx in range(900, 5000, 40):
        for wy in range(900, 5000, 40):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_colonizable_world_type(wt):
                world_key = build_world_key(float(wx), float(wy), world_type=wt)
                parsed = parse_world_key(world_key)
                sx, sy = sector_coords(float(wx), float(wy))
                return {
                    "world_key": world_key,
                    "world_x": float(wx),
                    "world_y": float(wy),
                    "sector_x": int(sx),
                    "sector_y": int(sy),
                    "planet_role": parsed["planet_role"],
                    "origin_world_key": world_key,
                }
    raise AssertionError("no colonizable coords")


def _assert_not_legacy_block(reason: str) -> None:
    assert reason not in FORBIDDEN_GALAXY_BLOCK_REASONS, reason
    assert not str(reason).startswith("outpost_"), reason
    assert not str(reason).startswith("frontier_"), reason


def test_buildings_queue_has_no_outpost_gate_hook(galaxy_contract_db):
    """Static contract: queue_build_for_planet must not call outpost gate helpers."""
    from game import buildings

    source = inspect.getsource(buildings.queue_build_for_planet)
    assert "is_building_allowed_in_outpost" not in source
    assert "outpost_building" not in source


def test_galaxy_colonize_uses_evolution_slot_not_world_map_gates(galaxy_contract_db):
    uid = _player()
    conn = db()
    try:
        ok, reason, _extra = colonize_planet(
            uid,
            name="Blocked Colony",
            galaxy=1,
            system=180,
            position=2,
            conn=conn,
            allow_legacy_coordinates=True,
            source="test",
        )
        assert not ok
        _assert_not_legacy_block(reason)
        assert reason == "planet_evolution_colony_slot_required"
    finally:
        conn.close()


def test_check_planet_cap_ignores_world_map_args(galaxy_contract_db):
    uid = _player()
    conn = db()
    try:
        _unlock_first_colony_slot(conn, uid)
        binding = _colonizable_binding()
        ok_plain, reason_plain = check_planet_cap_available(uid, conn=conn)
        ok_legacy, reason_legacy = check_planet_cap_available(
            uid,
            conn=conn,
            world_key=binding["world_key"],
            world_type="mining_world",
            site_key="frontier_ix",
        )
        assert ok_plain == ok_legacy
        assert reason_plain == reason_legacy
        assert ok_plain, reason_plain
        _assert_not_legacy_block(reason_plain)
    finally:
        conn.close()


def test_world_key_colony_builds_normal_infrastructure(galaxy_contract_db):
    from game.buildings import queue_build_for_planet
    from game.models import get_planet_buildings, save_planet_buildings

    uid = _player()
    conn = db()
    try:
        _unlock_first_colony_slot(conn, uid)
        binding = _colonizable_binding()
        ok, reason, extra = colonize_planet(
            uid,
            name="World Key Colony",
            galaxy=1,
            system=181,
            position=3,
            world_binding=binding,
            conn=conn,
        )
        assert ok, reason
        _assert_not_legacy_block(reason)
        pid = int(extra["planet_id"])

        save_planet_buildings(
            pid,
            {
                "metal_mine": 4,
                "crystal_mine": 2,
                "solar_plant": 1,
                "command_center": 2,
                "orbital_shipyard": 2,
            },
        )
        conn.execute(
            "UPDATE planets SET metal = 500000, crystal = 500000 WHERE id = ?;",
            (pid,),
        )
        conn.commit()

        planet = dict(conn.execute("SELECT * FROM planets WHERE id = ?;", (pid,)).fetchone())
        assert planet["world_key"]
        buildings = get_planet_buildings(pid, conn=conn)

        for btype in NORMAL_INFRA_BUILDINGS:
            ok_build, build_reason, payload = queue_build_for_planet(
                planet,
                buildings,
                btype,
                user_id=uid,
            )
            _assert_not_legacy_block(build_reason)
            assert ok_build, (btype, build_reason, payload)
            assert int(payload.get("job_id") or 0) > 0
    finally:
        conn.close()


def test_legacy_planet_without_evo_rows_builds_normal_infrastructure(galaxy_contract_db):
    from game.buildings import queue_build_for_planet
    from game.models import get_planet_buildings, save_planet_buildings

    uid = _player()
    conn = db()
    try:
        _unlock_first_colony_slot(conn, uid)
        ok, reason, extra = colonize_planet(
            uid,
            name="Pre EVO Colony",
            conn=conn,
            allow_legacy_coordinates=True,
            source="test",
        )
        assert ok, reason
        pid = int(extra["planet_id"])

        conn.execute("DELETE FROM planet_dna WHERE planet_id = ?;", (pid,))
        conn.execute("DELETE FROM planet_culture WHERE planet_id = ?;", (pid,))
        conn.execute("DELETE FROM planet_mechanics WHERE planet_id = ?;", (pid,))
        conn.execute(
            """
            UPDATE planets
            SET dna_seed = 0, planet_level = 3, dna_reveal_tier = 1, last_evolution_tick = 0
            WHERE id = ?;
            """,
            (pid,),
        )
        conn.commit()

        row = conn.execute("SELECT world_key FROM planets WHERE id = ?;", (pid,)).fetchone()
        assert not row["world_key"]

        save_planet_buildings(
            pid,
            {
                "metal_mine": 4,
                "crystal_mine": 2,
                "solar_plant": 1,
                "command_center": 2,
            },
        )
        conn.execute(
            "UPDATE planets SET metal = 500000, crystal = 500000 WHERE id = ?;",
            (pid,),
        )
        conn.commit()

        planet = dict(conn.execute("SELECT * FROM planets WHERE id = ?;", (pid,)).fetchone())
        buildings = get_planet_buildings(pid, conn=conn)

        for btype in ("metal_storage", "research_lab", "orbital_shipyard"):
            ok_build, build_reason, payload = queue_build_for_planet(
                planet,
                buildings,
                btype,
                user_id=uid,
            )
            _assert_not_legacy_block(build_reason)
            assert ok_build, (btype, build_reason, payload)
            assert int(payload.get("job_id") or 0) > 0
    finally:
        conn.close()


def test_fleet_colonize_preview_uses_evolution_slot_cap(galaxy_contract_db):
    uid = _player()
    conn = db()
    try:
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        origin = dict(conn.execute("SELECT * FROM planets WHERE id = ?;", (pid,)).fetchone())
        conn.commit()
        preview = build_fleet_send_preview(
            player_id=uid,
            origin_planet=origin,
            target_galaxy=1,
            target_system=499,
            target_position=12,
            mission_type="colonize",
            ships={"seed_ark": 1},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert preview.get("mission_allowed") is False
        assert preview.get("can_send") is False
        reason = str(preview.get("block_reason") or "")
        _assert_not_legacy_block(reason)
        assert reason == "planet_evolution_colony_slot_required"
    finally:
        conn.close()


def test_high_research_alone_does_not_bypass_evolution_colony_cap(galaxy_contract_db):
    """World-map style tech gates must not unlock galaxy colonization."""
    uid = _player()
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (int(uid), INTERSTELLAR_EXPANSION_TECH, 6),
        )
        conn.commit()
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert not ok
        _assert_not_legacy_block(reason)
        assert reason == "planet_evolution_colony_slot_required"
    finally:
        conn.close()
