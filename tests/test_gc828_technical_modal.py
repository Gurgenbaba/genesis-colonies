"""GC-828 — technical modal consistency and milestone framework."""

from __future__ import annotations

import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import build_building_technical_data
from game.defense_detail import build_defense_detail_card
from game.research import build_research_technical_data
from game.ship_detail import build_ship_detail_card
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db, save_planet_buildings
from game.technical_data import (
    build_production_milestones,
    build_research_effect_milestones,
    build_unit_technical_block,
    resolve_technical_table_layout,
)


@pytest.fixture
def gc828_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc828.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    uname = f"gc828_{uuid.uuid4().hex[:8]}"
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


def test_production_milestones_for_mine(gc828_db):
    uid = gc828_db
    planet = get_homeworld(player_id=uid)
    buildings = {"metal_mine": 37, "solar_plant": 20}
    save_planet_buildings(int(planet["id"]), buildings)
    research = {"production_tech": 5}

    milestones = build_production_milestones(
        building_type="metal_mine",
        buildings=buildings,
        research_levels=research,
        ratio=1.0,
        current=37,
        max_level=120,
    )
    assert milestones
    assert milestones[0]["level"] >= 40
    assert milestones[0]["display"].startswith("+")


def test_mine_technical_has_milestones_and_roi_column(gc828_db):
    uid = gc828_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"metal_mine": 19, "solar_plant": 10})

    conn = db()
    data, err = build_building_technical_data("metal_mine", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    assert data["milestones"]
    assert data["table_layout"] == "production"
    row20 = next(r for r in data["levels"] if r["level"] == 20)
    assert row20["display"].get("upgrade_roi_hours") is not None or row20.get("upgrade_roi_hours") is not None


def test_yard_technical_roi_and_layout(gc828_db):
    uid = gc828_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"orbital_shipyard": 1, "solar_plant": 1})

    conn = db()
    data, err = build_building_technical_data("orbital_shipyard", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    assert data["table_layout"] == "yard"
    assert data["summary"]["display"]["layout"] == "yard"
    assert data["summary"]["display"].get("batch_capacity_current") is not None
    row1 = next(r for r in data["levels"] if r["level"] == 1)
    assert row1["display"].get("upgrade_roi_hours") is not None


def test_research_technical_bonuses_and_milestones(gc828_db):
    uid = gc828_db
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"research_lab": 5, "nanofactory": 2})

    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, 'weapon_tech', 3);",
        (uid,),
    )
    conn.commit()
    data, err = build_research_technical_data("weapon_tech", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    bonuses = data["summary"].get("active_bonuses") or []
    assert any(b.get("label_key") == "building_research_lab" for b in bonuses)
    assert data.get("milestones") is not None


def test_resolve_table_layout_from_nonzero_row():
    levels = [
        {"display": {"layout": "plain", "table_layout": "standard"}},
        {"display": {"layout": "production", "table_layout": "production"}},
    ]
    assert resolve_technical_table_layout(levels) == "production"


def test_unit_technical_block_combat_bonuses():
    technical = build_unit_technical_block(
        base_attack=100,
        base_shield=50,
        base_hull=200,
        base_build_seconds=60,
        production={"cycle_seconds": 54, "yard_batch_capacity": 9},
        buildings={"orbital_shipyard": 2},
        research_levels={"weapon_tech": 4, "shield_tech": 2, "armor_tech": 3},
        next_yard_unit_seconds=48,
    )
    assert technical["combat"]["attack"] > 100
    assert technical["build_preview"]["delta_seconds"] > 0
    assert len(technical["active_bonuses"]) == 3


def test_ship_detail_includes_technical_block():
    card, err = build_ship_detail_card(
        "mule_courier",
        buildings={"orbital_shipyard": 2},
        research={"weapon_tech": 2},
    )
    assert err is None
    tech = card.get("technical") or {}
    assert tech.get("combat")
    assert tech.get("active_bonuses")


def test_defense_detail_includes_technical_block():
    card, err = build_defense_detail_card(
        "plasma_arc",
        buildings={"orbital_shipyard": 2, "defense_factory": 2},
        research={"weapon_tech": 4, "armor_tech": 2},
    )
    assert err is None
    tech = card.get("technical") or {}
    assert tech.get("combat")
    assert any(row.get("target_key") == "falcon_interceptor" for row in tech.get("rapid_fire_against") or [])


def test_ship_detail_includes_rapid_fire_matchups():
    card, err = build_ship_detail_card(
        "falcon_interceptor",
        buildings={"orbital_shipyard": 2},
        research={"weapon_tech": 2},
    )
    assert err is None
    tech = card.get("technical") or {}
    assert any(row.get("target_key") == "spark_drone" for row in tech.get("rapid_fire_against") or [])
