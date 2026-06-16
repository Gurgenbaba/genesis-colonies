"""GC-583A — Strategic world expedition via world_key."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
from game.planet_evolution.world_colonization import (
    EXPEDITION_WORLD_TYPES,
    PREPARED_EXPEDITION_WORLD_TYPES,
    SALVAGE_WORLD_TYPES,
    build_world_expedition_preview,
    build_world_key,
    is_expedition_world_type,
    is_prepared_expedition_world_type,
    is_salvage_world_type,
    validate_world_expedition_target,
    validate_world_salvage_target,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def world_expedition_db(tmp_path, monkeypatch):
    db_file = tmp_path / "world_expedition.db"
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


def _create_player(conn):
    ok, err, user = create_user(f"exp_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    conn.commit()
    return uid


def _expedition_coords() -> tuple[float, float, str]:
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_expedition_world_type(wt):
                return float(wx), float(wy), wt
    raise AssertionError("no expedition coords in sample grid")


def _prepared_coords() -> tuple[float, float, str]:
    for wx in range(500, 5000, 113):
        for wy in range(500, 5000, 97):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_prepared_expedition_world_type(wt):
                return float(wx), float(wy), wt
    raise AssertionError("no prepared expedition coords in sample grid")


def _salvage_coords() -> tuple[float, float, str]:
    for wx in range(500, 5000, 113):
        for wy in range(500, 5000, 97):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_salvage_world_type(wt):
                return float(wx), float(wy), wt
    raise AssertionError("no salvage coords in sample grid")


def _fleet_player(conn):
    import time

    from game.fleet import add_planet_ships, process_fleet_tick, send_fleet

    player_id = _create_player(conn)
    pid = int(get_planets_by_player(player_id, conn=conn)[0]["id"])
    conn.execute(
        "UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;",
        (pid,),
    )
    add_planet_ships(pid, player_id, {"solar_skiff": 2}, conn=conn)
    return player_id, pid, send_fleet, process_fleet_tick, time


def test_expedition_world_types_match_spec():
    assert "expedition_zone" in EXPEDITION_WORLD_TYPES
    assert "anomaly_zone" in EXPEDITION_WORLD_TYPES
    assert "ruins_world" in EXPEDITION_WORLD_TYPES
    assert "wreckage_field" in SALVAGE_WORLD_TYPES
    assert "wreckage_field" not in EXPEDITION_WORLD_TYPES
    assert "wreckage_field" not in PREPARED_EXPEDITION_WORLD_TYPES


def test_validate_world_expedition_target_accepts_expedition_zone(world_expedition_db):
    wx, wy, wt = _expedition_coords()
    world_key = build_world_key(wx, wy, world_type=wt)
    from game.db import db

    conn = db()
    try:
        ok, reason, info = validate_world_expedition_target(world_key, conn=conn)
        assert ok, reason
        assert info["target_type"] == "strategic_world"
        assert info["allowed_missions"] == ["expedition"]
        assert info["world_key"] == world_key
    finally:
        conn.close()


def test_validate_blocks_wreckage_on_expedition_validator(world_expedition_db):
    wx, wy, wt = _salvage_coords()
    world_key = build_world_key(wx, wy, world_type=wt)
    from game.db import db

    conn = db()
    try:
        ok, reason, _ = validate_world_expedition_target(world_key, conn=conn)
        assert not ok
        assert reason == "world_not_expedition"
        ok_s, reason_s, info = validate_world_salvage_target(world_key, conn=conn)
        assert ok_s, reason_s
        assert info["world_key"] == world_key
    finally:
        conn.close()


def test_validate_rejects_colonizable_world(world_expedition_db):
    from game.planet_evolution.world_colonization import is_colonizable_world_type
    from game.db import db

    conn = db()
    try:
        for wx in range(500, 5000, 50):
            for wy in range(500, 5000, 50):
                wt = strategic_world_type_for_coords(float(wx), float(wy))
                if not is_colonizable_world_type(wt):
                    continue
                world_key = build_world_key(float(wx), float(wy), world_type=wt)
                ok, reason, _ = validate_world_expedition_target(world_key, conn=conn)
                assert not ok
                assert reason == "world_not_expedition"
                return
        pytest.skip("no colonizable coords in sample grid")
    finally:
        conn.close()


def test_build_world_expedition_preview(world_expedition_db):
    wx, wy, wt = _expedition_coords()
    world_key = build_world_key(wx, wy, world_type=wt)
    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        preview = build_world_expedition_preview(player_id, world_key, conn=conn)
        assert preview["can_expedition"] is True
        assert preview["presentation"]["world_type"] == wt
    finally:
        conn.close()


def test_fleet_world_key_expedition_sends_and_reports(world_expedition_db):
    from game.db import db

    wx, wy, wt = _expedition_coords()
    world_key = build_world_key(wx, wy, world_type=wt)

    conn = db()
    try:
        player_id, pid, send_fleet, process_fleet_tick, time = _fleet_player(conn)
        conn.commit()

        ok, reason, result = send_fleet(
            player_id=player_id,
            origin_planet_id=pid,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            world_key=world_key,
            conn=conn,
        )
        assert ok, reason
        fleet_id = int(result["fleet"]["id"])
        row = conn.execute(
            "SELECT resources_json FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()
        assert world_key in str(row["resources_json"])

        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()

        status = conn.execute(
            "SELECT status FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()["status"]
        assert status == "returning"

        msg = conn.execute(
            """
            SELECT subject, metadata_json FROM player_messages
            WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;
            """,
            (player_id,),
        ).fetchone()
        assert msg
        assert world_key in str(msg["subject"]) or world_key in str(msg["metadata_json"])
    finally:
        conn.close()


def test_fleet_world_key_expedition_rejects_mining_world(world_expedition_db):
    from game.db import db
    from game.planet_evolution.world_colonization import is_colonizable_world_type

    conn = db()
    try:
        for wx in range(500, 5000, 50):
            for wy in range(500, 5000, 50):
                wt = strategic_world_type_for_coords(float(wx), float(wy))
                if not is_colonizable_world_type(wt):
                    continue
                world_key = build_world_key(float(wx), float(wy), world_type=wt)
                player_id, pid, send_fleet, _, _ = _fleet_player(conn)
                conn.commit()
                ok, reason, _ = send_fleet(
                    player_id=player_id,
                    origin_planet_id=pid,
                    target_galaxy=1,
                    target_system=1,
                    target_position=1,
                    mission_type="expedition",
                    ships={"solar_skiff": 1},
                    world_key=world_key,
                    conn=conn,
                )
                assert not ok
                assert reason == "world_not_expedition"
                return
        pytest.skip("no colonizable coords in sample grid")
    finally:
        conn.close()


def test_classic_expedition_slot_still_works(world_expedition_db):
    from game.fleet import EXPEDITION_POSITION, build_fleet_send_preview
    from game.db import db

    conn = db()
    try:
        player_id, pid, _, _, _ = _fleet_player(conn)
        origin = conn.execute("SELECT * FROM planets WHERE id = ?;", (pid,)).fetchone()
        preview = build_fleet_send_preview(
            player_id=player_id,
            origin_planet=dict(origin),
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert preview["mission_allowed"] is True
        assert preview["can_send"] is True
    finally:
        conn.close()
