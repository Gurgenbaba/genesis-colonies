"""Maintenance script — legacy planet evolution backfill."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.bootstrap import ensure_planet_evolution
from game.planet_evolution.expansion_protocol import is_outpost_planet
from game.planet_evolution.service import colonize_planet

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "scripts" / "backfill_planet_evolution_legacy.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("backfill_planet_evolution_legacy", SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def backfill_db(tmp_path, monkeypatch):
    db_file = tmp_path / "backfill_legacy.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    dbmod._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield
    dbmod._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"backfill_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="BackfillTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _unlock_expansion(conn, uid: int) -> None:
    from game.models import get_homeworld
    from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH

    hw = get_homeworld(uid, conn=conn)
    assert hw
    conn.execute("UPDATE planets SET planet_level = 5 WHERE id = ?;", (int(hw["id"]),))
    conn.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (int(uid), INTERSTELLAR_EXPANSION_TECH, 1),
    )
    conn.commit()


def _colonizable_binding():
    from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
    from game.planet_evolution.world_colonization import (
        build_world_key,
        is_colonizable_world_type,
        parse_world_key,
        sector_coords,
    )

    for wx in range(1200, 5000, 40):
        for wy in range(1200, 5000, 40):
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


def test_dry_run_does_not_mutate(backfill_db):
    mod = _load_script_module()
    uid = _player()
    conn = db()
    try:
        _unlock_expansion(conn, uid)
        binding = _colonizable_binding()
        ok, reason, extra = colonize_planet(
            uid,
            name="Dry Run Colony",
            world_binding=binding,
            conn=conn,
        )
        assert ok, reason
        pid = int(extra["planet_id"])
        conn.execute(
            """
            UPDATE planet_buildings
            SET metal_mine = 4, crystal_mine = 2, research_lab = 1, solar_plant = 1
            WHERE planet_id = ?;
            """,
            (pid,),
        )
        conn.commit()

        before = mod.snapshot_planet_state(pid, conn)
        summary = mod.run_backfill(conn, [pid], dry_run=True)
        after = mod.snapshot_planet_state(pid, conn)

        assert before == after
        assert summary["dry_run"] is True
        assert summary["updated"] >= 1
    finally:
        conn.close()


def test_apply_grandfathers_mature_world_bound_colony(backfill_db):
    mod = _load_script_module()
    uid = _player()
    conn = db()
    try:
        _unlock_expansion(conn, uid)
        binding = _colonizable_binding()
        ok, reason, extra = colonize_planet(
            uid,
            name="Grandfather Target",
            world_binding=binding,
            conn=conn,
        )
        assert ok, reason
        pid = int(extra["planet_id"])
        assert is_outpost_planet(pid, conn=conn)

        conn.execute(
            """
            UPDATE planet_buildings
            SET metal_mine = 4, crystal_mine = 2, research_lab = 1, solar_plant = 1
            WHERE planet_id = ?;
            """,
            (pid,),
        )
        conn.commit()

        preview = mod.preview_planet_backfill(pid, conn)
        assert preview["would_grandfather"] is True

        result = mod.apply_planet_backfill(pid, conn)
        assert result["action"] == "updated"
        assert result["grandfathered"] is True
        assert not is_outpost_planet(pid, conn=conn)
    finally:
        conn.close()


def test_apply_is_idempotent(backfill_db):
    mod = _load_script_module()
    uid = _player()
    conn = db()
    try:
        pid = int(
            conn.execute(
                "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
                (uid,),
            ).fetchone()["id"]
        )
        first = mod.apply_planet_backfill(pid, conn)
        second = mod.apply_planet_backfill(pid, conn)
        assert first["action"] in ("updated", "skip")
        assert second["action"] == "skip"
    finally:
        conn.close()


def test_fetch_planet_ids_filters(backfill_db):
    mod = _load_script_module()
    uid = _player()
    conn = db()
    try:
        hw_id = int(
            conn.execute(
                "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
                (uid,),
            ).fetchone()["id"]
        )
        all_ids = mod.fetch_planet_ids(conn, player_id=uid)
        assert hw_id in all_ids
        assert mod.fetch_planet_ids(conn, planet_id=hw_id) == [hw_id]
        assert mod.fetch_planet_ids(conn, player_id=uid, limit=1) == [min(all_ids)]
    finally:
        conn.close()
