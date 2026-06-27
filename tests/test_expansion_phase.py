"""GC-920 — Expansion phase resolver (derived state, read-only)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, get_planets_by_player, init_db
from game.planet_evolution.expansion_phase import (
    EXPANSION_PHASE_CLAIM,
    EXPANSION_PHASE_COLONY,
    EXPANSION_PHASE_EN_ROUTE,
    EXPANSION_PHASE_OUTPOST,
    EXPANSION_PHASE_SITE,
    EXPANSION_PHASE_STRATEGIC,
    get_establishment_milestones,
    is_establishment_complete,
    resolve_expansion_phase,
)
from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
from game.planet_evolution.world_colonization import (
    build_world_key,
    is_colonizable_world_type,
    reserve_world_claim,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def expansion_phase_db(tmp_path, monkeypatch):
    db_file = tmp_path / "expansion_phase.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _create_player() -> int:
    uname = f"exphase_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"])


_colonizable_coord_cursor = 600


def _colonizable_coords() -> tuple[float, float]:
    global _colonizable_coord_cursor
    for wx in range(_colonizable_coord_cursor, 5000, 50):
        for wy in range(600, 5000, 50):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_colonizable_world_type(wt):
                _colonizable_coord_cursor = wx + 50
                return float(wx), float(wy)
    raise AssertionError("no colonizable coords")


def _fleet_setup(conn):
    from game.fleet import add_planet_ships, send_fleet
    from game.models import ensure_player_and_homeworld

    player_id = _create_player()
    ensure_player_and_homeworld(player_id, player_name="Commander", conn=conn)
    pid = int(get_planets_by_player(player_id, conn=conn)[0]["id"])
    conn.execute(
        "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 500000 WHERE id = ?;",
        (pid,),
    )
    add_planet_ships(pid, player_id, {"seed_ark": 1, "cargo_drone": 1}, conn=conn)
    return player_id, pid, send_fleet


def _world_binding(wx: float, wy: float) -> dict:
    from game.planet_evolution.world_colonization import parse_world_key, sector_coords

    world_key = build_world_key(wx, wy)
    parsed = parse_world_key(world_key)
    sx, sy = sector_coords(wx, wy)
    return {
        "world_key": world_key,
        "world_x": wx,
        "world_y": wy,
        "sector_x": int(sx),
        "sector_y": int(sy),
        "planet_role": parsed["planet_role"],
        "origin_world_key": world_key,
    }


def _colonize_at_world(conn, player_id: int, wx: float, wy: float, name: str) -> int:
    from game.galaxy import assign_free_coordinates
    from game.planet_evolution.service import colonize_planet

    galaxy, system, position = assign_free_coordinates(conn, galaxy=1)
    ok, reason, extra = colonize_planet(
        player_id,
        name=name,
        galaxy=galaxy,
        system=system,
        position=position,
        world_binding=_world_binding(wx, wy),
        conn=conn,
    )
    assert ok, reason
    return int(extra["planet_id"])


def _set_establishment_buildings(conn, planet_id: int, *, complete: bool) -> None:
    if complete:
        conn.execute(
            """
            UPDATE planet_buildings
            SET command_center = 1, solar_plant = 1, radar_array = 1
            WHERE planet_id = ?;
            """,
            (int(planet_id),),
        )
    else:
        conn.execute(
            """
            UPDATE planet_buildings
            SET command_center = 1, solar_plant = 0, radar_array = 0
            WHERE planet_id = ?;
            """,
            (int(planet_id),),
        )


def test_expansion_site_without_claim(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id = _create_player()
        wx, wy = _colonizable_coords()
        world_key = build_world_key(wx, wy)

        result = resolve_expansion_phase(player_id=player_id, world_key=world_key, conn=conn)
        assert result["phase"] == EXPANSION_PHASE_SITE
        assert result["source"]["has_claim"] is False
        assert result["source"]["has_planet"] is False
    finally:
        conn.close()


def test_expansion_site_key_frontier_ix(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id = _create_player()
        result = resolve_expansion_phase(player_id=player_id, world_key="frontier_ix", conn=conn)
        assert result["phase"] == EXPANSION_PHASE_SITE
    finally:
        conn.close()


def test_claim_phase(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id = _create_player()
        wx, wy = _colonizable_coords()
        ok, reason, _payload = reserve_world_claim(player_id, wx, wy, conn=conn)
        assert ok, reason
        world_key = build_world_key(wx, wy)
        conn.commit()

        result = resolve_expansion_phase(player_id=player_id, world_key=world_key, conn=conn)
        assert result["phase"] == EXPANSION_PHASE_CLAIM
        assert result["source"]["has_claim"] is True
    finally:
        conn.close()


def test_en_route_phase(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id, pid, send_fleet = _fleet_setup(conn)
        wx, wy = _colonizable_coords()
        world_key = build_world_key(wx, wy)
        conn.commit()

        ok, reason, _result = send_fleet(
            player_id=player_id,
            origin_planet_id=pid,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="colonize",
            ships={"seed_ark": 1},
            resources={"colony_name": "Outpost Alpha"},
            world_key=world_key,
            conn=conn,
        )
        assert ok, reason
        conn.commit()

        phase = resolve_expansion_phase(player_id=player_id, world_key=world_key, conn=conn)
        assert phase["phase"] == EXPANSION_PHASE_EN_ROUTE
        assert phase["source"]["has_active_seed_ark"] is True
    finally:
        conn.close()


def test_frontier_outpost_incomplete_milestones(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id = _create_player()
        wx, wy = _colonizable_coords()
        world_key = build_world_key(wx, wy)
        planet_id = _colonize_at_world(conn, player_id, wx, wy, "Map Outpost")
        _set_establishment_buildings(conn, planet_id, complete=False)
        conn.commit()

        result = resolve_expansion_phase(
            player_id=player_id,
            world_key=world_key,
            planet_id=planet_id,
            conn=conn,
        )
        assert result["phase"] == EXPANSION_PHASE_OUTPOST
        assert result["is_outpost"] is True
        assert result["is_colony"] is False
        assert is_establishment_complete(planet_id, conn=conn) is False
    finally:
        conn.close()


def test_colony_when_milestones_complete(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id = _create_player()
        wx, wy = _colonizable_coords()
        planet_id = _colonize_at_world(conn, player_id, wx, wy, "Established Colony")
        _set_establishment_buildings(conn, planet_id, complete=True)
        conn.commit()

        result = resolve_expansion_phase(player_id=player_id, planet_id=planet_id, conn=conn)
        assert result["phase"] == EXPANSION_PHASE_COLONY
        assert result["is_colony"] is True
        assert result["source"]["establishment_complete"] is True
    finally:
        conn.close()


def test_strategic_world_with_specialization(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id = _create_player()
        wx, wy = _colonizable_coords()
        planet_id = _colonize_at_world(conn, player_id, wx, wy, "Spec World")
        _set_establishment_buildings(conn, planet_id, complete=True)
        conn.execute(
            """
            UPDATE planets
            SET specialization_key = 'industrial_forge', specialization_tier = 1
            WHERE id = ?;
            """,
            (planet_id,),
        )
        conn.commit()

        result = resolve_expansion_phase(player_id=player_id, planet_id=planet_id, conn=conn)
        assert result["phase"] == EXPANSION_PHASE_STRATEGIC
        assert result["is_strategic_world"] is True
    finally:
        conn.close()


def test_resolver_is_read_only(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        player_id = _create_player()
        wx, wy = _colonizable_coords()
        world_key = build_world_key(wx, wy)
        before = conn.execute("SELECT COUNT(*) AS c FROM planets WHERE player_id = ?;", (player_id,)).fetchone()["c"]
        before_claims = conn.execute("SELECT COUNT(*) AS c FROM world_claims;").fetchone()["c"]

        resolve_expansion_phase(player_id=player_id, world_key=world_key, conn=conn)
        resolve_expansion_phase(player_id=player_id, world_key=world_key, conn=conn)

        after = conn.execute("SELECT COUNT(*) AS c FROM planets WHERE player_id = ?;", (player_id,)).fetchone()["c"]
        after_claims = conn.execute("SELECT COUNT(*) AS c FROM world_claims;").fetchone()["c"]
        assert after == before
        assert after_claims == before_claims
    finally:
        conn.close()


def test_no_expansion_phase_column(expansion_phase_db):
    from game.db import db

    conn = db()
    try:
        cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(planets);").fetchall()}
        assert "expansion_phase" not in cols
    finally:
        conn.close()


def test_establishment_milestones_structure(expansion_phase_db):
    from game.db import db
    from game.models import get_homeworld

    conn = db()
    try:
        player_id = _create_player()
        hw = get_homeworld(player_id=player_id, conn=conn)
        assert hw
        milestones = get_establishment_milestones(int(hw["id"]), conn=conn)
        keys = {m["key"] for m in milestones}
        assert keys == {"habitat", "energy", "communication", "first_population"}
        population = next(m for m in milestones if m["key"] == "first_population")
        assert population["required"] is False
        assert population["met"] is False
    finally:
        conn.close()


def test_command_center_payload_includes_expansion_phase(expansion_phase_db):
    from game.db import db
    from game.planet_evolution.command_center import build_strategic_world_command_center

    conn = db()
    try:
        player_id = _create_player()
        wx, wy = _colonizable_coords()
        world_key = build_world_key(wx, wy)
        node = {
            "node_kind": "world_field",
            "world_key": world_key,
            "name_key": "strategic_world_name_test",
            "type_key": "strategic_world_type_mining_world",
            "role_icon": "☀",
            "is_claimed": False,
            "is_colonizable": True,
        }
        cc = build_strategic_world_command_center(node, player_id, conn=conn)
        assert cc.get("expansion_phase", {}).get("phase") == EXPANSION_PHASE_SITE
    finally:
        conn.close()
