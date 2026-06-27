"""GC-535 — dedicated fuel_storage building and depot capacity."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import _make_panel_row, get_buildings_panel_rows
from game.effects import EffectResolver
from game.models import (
    create_user,
    db,
    get_homeworld,
    get_planet_buildings,
    get_research_levels,
    init_db,
    save_planet_buildings,
)
from game.resources import update_planet_resources

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def fuel_storage_db(tmp_path, monkeypatch):
    db_file = tmp_path / "fuel_storage.db"
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
    uname = f"fuel_store_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    return int(user["id"])


def test_fuel_storage_base_capacity_without_building(fuel_storage_db):
    planet = get_homeworld(player_id=fuel_storage_db)
    save_planet_buildings(
        int(planet["id"]),
        {"fuel_cell_plant": 5, "fuel_storage": 0, "solar_plant": 5},
    )
    b = get_planet_buildings(int(planet["id"]))
    r = EffectResolver(b, get_research_levels(user_id=fuel_storage_db))
    assert r.fuel_storage_capacity() == EffectResolver.BASE_STORAGE
    assert r.get_storage_capacity()["fuel_cells"] == EffectResolver.BASE_STORAGE


def test_fuel_storage_capacity_scales_like_metal_storage(fuel_storage_db):
    from game.economy_balance import storage_capacity_anchor

    planet = get_homeworld(player_id=fuel_storage_db)
    save_planet_buildings(int(planet["id"]), {"fuel_storage": 2})
    b = get_planet_buildings(int(planet["id"]))
    r = EffectResolver(b, get_research_levels(user_id=fuel_storage_db))
    cap = r.fuel_storage_capacity()
    expected = EffectResolver.BASE_STORAGE + storage_capacity_anchor("fuel_cells", 2)
    assert cap == expected


def test_fuel_cell_plant_does_not_add_depot_bonus(fuel_storage_db):
    planet = get_homeworld(player_id=fuel_storage_db)
    save_planet_buildings(
        int(planet["id"]),
        {"fuel_cell_plant": 10, "fuel_storage": 0, "solar_plant": 10},
    )
    b = get_planet_buildings(int(planet["id"]))
    r = EffectResolver(b, get_research_levels(user_id=fuel_storage_db))
    assert r.fuel_cells_storage_capacity() == EffectResolver.BASE_STORAGE


def test_production_respects_fuel_storage_cap(fuel_storage_db):
    conn = db()
    planet = get_homeworld(player_id=fuel_storage_db)
    pid = int(planet["id"])
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planet_buildings
        SET fuel_cell_plant = 3, fuel_storage = 1, solar_plant = 5,
            metal_mine = 0, crystal_mine = 0
        WHERE planet_id = ?;
        """,
        (pid,),
    )
    b = get_planet_buildings(pid, conn=conn)
    r = EffectResolver(b, get_research_levels(user_id=fuel_storage_db))
    fuel_cap = r.fuel_storage_capacity()
    assert fuel_cap > 0
    cur.execute(
        "UPDATE planets SET fuel_cells = ?, last_update = ? WHERE id = ?;",
        (fuel_cap, time.time() - 3600, pid),
    )
    conn.commit()
    cur.execute("SELECT * FROM planets WHERE id = ?;", (pid,))
    row = dict(cur.fetchone())
    update_planet_resources(row, conn=conn, skip_queue_finish=True)
    conn.commit()
    after = int(cur.execute("SELECT fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()["fuel_cells"])
    assert after == fuel_cap
    conn.close()


def test_fuel_storage_panel_preview(fuel_storage_db):
    planet = get_homeworld(player_id=fuel_storage_db)
    save_planet_buildings(int(planet["id"]), {"fuel_storage": 1, "fuel_cell_plant": 4})
    b = get_planet_buildings(int(planet["id"]))
    row = _make_panel_row(
        planet,
        b,
        get_research_levels(user_id=fuel_storage_db),
        "fuel_storage",
        ratio=1.0,
    )
    assert row["effect_kind"] == "storage"
    assert row["effect_resource"] == "fuel_cells"
    assert row["effect_next"] > row["effect_current"]


def test_fuel_storage_in_resources_tab(fuel_storage_db):
    planet = get_homeworld(player_id=fuel_storage_db)
    b = get_planet_buildings(int(planet["id"]))
    rows = get_buildings_panel_rows(planet, b)
    keys = [r["key"] for r in rows["resources"]]
    assert "fuel_storage" in keys
    assert keys.index("fuel_cell_plant") < keys.index("fuel_storage")
