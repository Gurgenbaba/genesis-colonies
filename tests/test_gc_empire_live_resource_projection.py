"""Regression coverage for live Empire resources after shipless relay collection."""

from __future__ import annotations

import time
import uuid

import pytest

import game.db as gdb
from game.db import db
from game.empire_page import build_empire_context
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_homeworld,
    init_db,
    save_planet_buildings,
)


@pytest.fixture()
def empire_live_db(tmp_path, monkeypatch):
    db_path = tmp_path / "empire_live_resources.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player_with_productive_homeworld() -> tuple[int, int]:
    ok, err, user = create_user(f"emp_live_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])

    conn = db()
    ensure_player_and_homeworld(uid, conn=conn)
    conn.commit()
    planet = get_homeworld(player_id=uid, conn=conn)
    pid = int(planet["id"])
    conn.close()

    save_planet_buildings(
        pid,
        {
            "metal_mine": 8,
            "crystal_mine": 7,
            "fuel_cell_plant": 6,
            "solar_plant": 20,
        },
    )
    return uid, pid


def test_readonly_empire_projects_production_after_colony_was_emptied(empire_live_db):
    uid, pid = _player_with_productive_homeworld()
    relay_tick = time.time() - 120.0

    conn = db()
    conn.execute(
        "UPDATE planets SET metal = 0, crystal = 0, fuel_cells = 0, last_update = ? WHERE id = ?;",
        (relay_tick, pid),
    )
    conn.commit()

    before = conn.execute(
        "SELECT metal, crystal, fuel_cells, last_update FROM planets WHERE id = ?;",
        (pid,),
    ).fetchone()
    ctx = build_empire_context(uid, conn=conn, sync_resources=False)

    colony = next(c for c in ctx["colonies"] if int(c["planet_id"]) == pid)
    assert int(colony["resources"]["metal"]) > 0
    assert int(colony["resources"]["crystal"]) > 0
    assert int(colony["resources"]["fuel_cells"]) > 0

    matrix_idx = next(
        i for i, c in enumerate(ctx["matrix"]["colonies"]) if int(c["planet_id"]) == pid
    )
    matrix_resources = ctx["matrix"]["colony_values"][matrix_idx]["resources"]
    assert int(matrix_resources["metal"]) == int(colony["resources"]["metal"])
    assert int(matrix_resources["crystal"]) == int(colony["resources"]["crystal"])
    assert int(matrix_resources["fuel_cells"]) == int(colony["resources"]["fuel_cells"])

    after = conn.execute(
        "SELECT metal, crystal, fuel_cells, last_update FROM planets WHERE id = ?;",
        (pid,),
    ).fetchone()
    assert int(after["metal"]) == int(before["metal"]) == 0
    assert int(after["crystal"]) == int(before["crystal"]) == 0
    assert int(after["fuel_cells"]) == int(before["fuel_cells"]) == 0
    assert float(after["last_update"]) == pytest.approx(float(before["last_update"]))
    conn.close()
