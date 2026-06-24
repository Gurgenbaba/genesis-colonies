"""GC-823B — technical data 2.0 (level schedule, layouts, summary)."""

from __future__ import annotations

import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import build_building_technical_data
from game.research import build_research_technical_data
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db, save_planet_buildings
from game.technical_data import technical_preview_levels, technical_row_role


@pytest.fixture
def tech_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc823b.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    uname = f"gc823b_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return uid


def test_preview_levels_early_game():
    assert technical_preview_levels(0, 120) == [0, 1, 2, 3, 4, 5]
    assert technical_preview_levels(3, 10) == [0, 1, 2, 3, 4, 5]


def test_preview_levels_midgame_milestones():
    levels = technical_preview_levels(37, 120)
    assert levels[0] == 37
    assert 38 in levels
    assert 40 in levels
    assert 50 in levels
    assert 60 in levels
    assert all(l > 38 or l in (37, 38) for l in levels if l not in (37, 38))


def test_row_roles():
    assert technical_row_role(37, 37, max_level=120) == "current"
    assert technical_row_role(38, 37, max_level=120) == "next"
    assert technical_row_role(40, 37, max_level=120) == "milestone"


def test_mine_technical_summary_and_table_fields(tech_db):
    uid = tech_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"metal_mine": 19, "solar_plant": 10})

    conn = db()
    data, err = build_building_technical_data("metal_mine", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    assert data["table_layout"] == "production"
    assert data["summary"]["at_max_level"] is False
    assert data["summary"]["from_level"] == 19
    assert data["summary"]["to_level"] == 20
    assert data["summary"]["display"]["layout"] == "production"
    level_nums = [r["level"] for r in data["levels"]]
    assert 20 in level_nums
    assert 30 in level_nums
    row1 = next(r for r in data["levels"] if r["level"] == 20)
    assert row1["display"]["step_delta"] > 0
    assert row1["display"]["energy_at_level"] < 0


def test_energy_tech_consumption_display(tech_db):
    uid = tech_db
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, 'energy_tech', 2);",
        (uid,),
    )
    conn.commit()
    data, err = build_research_technical_data("energy_tech", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    assert data["table_layout"] == "effect_percent"
    row2 = next(r for r in data["levels"] if r["level"] == 2)
    assert row2["display"]["display_mode"] == "consumption"
    assert row2["display"]["value_at_level"] == 90
    assert data["summary"]["upgrade_roi_hours"] is not None


def test_orbital_shipyard_yard_layout(tech_db):
    uid = tech_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"orbital_shipyard": 2, "solar_plant": 1})

    conn = db()
    data, err = build_building_technical_data("orbital_shipyard", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    assert data["table_layout"] == "yard"
    row = next(r for r in data["levels"] if r["level"] == 2)
    assert row["display"]["capacity_at_level"] > 0
    assert "reduction_at_level" in row["display"]
