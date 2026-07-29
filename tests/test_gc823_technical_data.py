"""GC-823 — unified technical data display payloads."""

from __future__ import annotations

import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import build_building_technical_data
from game.research import build_research_technical_data
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db, save_planet_buildings


@pytest.fixture
def tech_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc823.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    uname = f"gc823_{uuid.uuid4().hex[:8]}"
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


def test_metal_mine_display_production_block(tech_db):
    uid = tech_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(
        int(planet["id"]),
        {"metal_mine": 19, "solar_plant": 10, "crystal_mine": 5},
    )

    conn = db()
    data, err = build_building_technical_data("metal_mine", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row20 = next(r for r in data["levels"] if r["level"] == 20)
    display = row20["display"]
    assert display["layout"] == "production"
    assert display["current_per_hour"] >= 0
    assert display["next_per_hour"] > display["current_per_hour"]
    assert display["delta_per_hour"] == display["next_per_hour"] - display["current_per_hour"]
    assert display["delta_per_day"] == display["delta_per_hour"] * 24
    assert display["upgrade_roi_hours"] is not None
    assert display["upgrade_roi_hours"] > 0
    assert isinstance(display["active_bonuses"], list)
    assert len(display["formula"]["steps"]) >= 2
    assert display["formula"]["steps"][-1]["is_total"] is True


def test_mining_tech_display_effect_percent(tech_db):
    uid = tech_db
    conn = db()
    data, err = build_research_technical_data("mining_tech", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row = data["levels"][1]
    display = row["display"]
    assert display["layout"] == "effect_percent"
    assert display["next"] > display["current"]
    assert display["delta"] == display["next"] - display["current"]
    assert row["effect_current"] == display["current"]
    assert row["effect_next"] == display["next"]


def test_solar_plant_energy_display(tech_db):
    uid = tech_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"solar_plant": 4})

    conn = db()
    data, err = build_building_technical_data("solar_plant", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row = next(r for r in data["levels"] if r["level"] == 5)
    assert row["display"]["layout"] == "energy"
    assert row["display"]["delta"] >= 0


def test_nanofactory_no_plus_on_absolute_effect(tech_db):
    uid = tech_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"nanofactory": 2, "solar_plant": 5})

    conn = db()
    data, err = build_building_technical_data("nanofactory", user_id=uid, conn=conn)
    conn.close()

    row = next(r for r in data["levels"] if r["level"] == 3)
    d = row["display"]
    # Nanofactory now gets its own richer display block (build_nanofactory_time_display:
    # build-time savings estimate, reference building, modifiers) instead of the
    # generic effect_percent layout; table_layout stays "effect_percent" for
    # column-rendering compatibility (GC-STABILIZE-002; game/technical_data.py).
    assert d["layout"] == "nanofactory_build_time"
    assert d["table_layout"] == "effect_percent"
    assert d["current"] >= 0
    assert d["next"] > d["current"]