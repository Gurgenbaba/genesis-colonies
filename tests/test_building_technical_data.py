"""GC-557F — building technical data API."""

from __future__ import annotations

import importlib
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import build_building_technical_data, get_build_time
from game.research import build_research_technical_data
from game.db import db
from game.effects import EffectResolver
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, get_research_levels, init_db, save_planet_buildings


@pytest.fixture
def tech_db(tmp_path, monkeypatch):
    db_file = tmp_path / "building_technical.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    yield db_file


def _create_player(*, conn=None) -> tuple[int, str]:
    own = conn is None
    if own:
        conn = db()
    uname = f"tech_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid, uname


def _reload_app(monkeypatch, db_file):
    import app as app_mod

    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod.DB_PATH = db_file
    models.DB_PATH = db_file
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod


def test_technical_data_metal_mine_levels(tech_db):
    uid, _ = _create_player()
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"metal_mine": 3, "solar_plant": 5, "crystal_mine": 1})

    conn = db()
    data, err = build_building_technical_data("metal_mine", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    assert data is not None
    assert data["building_type"] == "metal_mine"
    assert data["current_level"] == 3
    assert len(data["levels"]) == 6
    assert data["levels"][0]["is_current"] is True
    assert data["levels"][0]["level"] == 3
    assert data["levels"][1]["level"] == 4
    assert data["levels"][0]["production_metal_per_hour"] is not None
    assert data["levels"][0]["energy_use"] is not None
    assert data["levels"][0]["cost_metal"] > 0
    assert data["description_key"] == "desc_metal_mine"
    assert data["kind"] == "building"


def test_technical_data_solar_plant_energy(tech_db):
    uid, _ = _create_player()
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"solar_plant": 2})

    conn = db()
    data, err = build_building_technical_data("solar_plant", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row = data["levels"][0]
    assert row["effect_kind"] == "energy"
    assert row["energy_total"] is not None
    assert row["energy_total"] > 0


def test_technical_data_mining_tech_levels(tech_db):
    uid, _ = _create_player()
    conn = db()
    conn.execute(
        "UPDATE planet_buildings SET research_lab = 3 WHERE planet_id = (SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1);",
        (uid,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO research_levels (user_id, tech_key, level) VALUES (?, 'mining_tech', 2);",
        (uid,),
    )
    conn.commit()

    data, err = build_research_technical_data("mining_tech", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    assert data["tech_key"] == "mining_tech"
    assert data["current_level"] == 2
    assert len(data["levels"]) == 6
    assert data["levels"][0]["is_current"] is True
    assert data["levels"][0]["effect_kind"] == "bonus_percent"
    assert data["description_key"] == "desc_mining_tech"
    assert data["kind"] == "research"


def test_technical_data_orbital_shipyard_production(tech_db):
    uid, _ = _create_player()
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"orbital_shipyard": 2, "solar_plant": 1})

    conn = db()
    data, err = build_building_technical_data("orbital_shipyard", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row = data["levels"][0]
    assert row["effect_kind"] == "yard_production"
    assert row["yard_batch_capacity"] == 9
    assert row["parallel_light"] >= row["parallel_heavy"] >= 1


def test_technical_data_defense_factory_unlock(tech_db):
    uid, _ = _create_player()
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(
        int(planet["id"]),
        {"defense_factory": 2, "orbital_shipyard": 1, "solar_plant": 1},
    )

    conn = db()
    data, err = build_building_technical_data("defense_factory", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row = data["levels"][0]
    assert row["effect_kind"] == "defense_unlock"
    assert row["effect_value"] == 2
    sec = row.get("secondary_effect") or {}
    assert sec.get("effect_kind") == "yard_reference"
    assert sec.get("effect_value") == 3


def test_technical_data_api_route(tech_db, monkeypatch):
    app_mod = _reload_app(monkeypatch, tech_db)
    uid, uname = _create_player()
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"metal_storage": 1, "solar_plant": 1})

    client = app_mod.app.test_client()
    res = client.post("/login", data={"username": uname, "password": "test-pass-123"})
    assert res.status_code in (200, 302)

    r = client.get("/api/buildings/metal_storage/technical-data")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["ok"] is True
    assert payload["data"]["building_type"] == "metal_storage"
    assert payload["data"]["levels"][0]["storage_metal"] is not None

    r404 = client.get("/api/buildings/not_a_building/technical-data")
    assert r404.status_code == 404


def test_technical_data_nanofactory_flat_per_level_bonus(tech_db):
    uid, _ = _create_player()
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(
        int(planet["id"]),
        {"nanofactory": 7, "solar_plant": 1, "metal_mine": 1},
    )

    conn = db()
    data, err = build_building_technical_data("nanofactory", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row = data["levels"][0]
    assert row["effect_kind"] == "bonus_percent"
    assert row["effect_value"] == 210
    assert data["levels"][1]["effect_value"] == 240
    assert data["levels"][1]["effect_value"] - row["effect_value"] == 30
    assert row["time_seconds"] == get_build_time("nanofactory", 7, user_id=uid)


def test_technical_data_command_center_flat_per_level_bonus(tech_db):
    uid, _ = _create_player()
    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"command_center": 17, "solar_plant": 1})

    conn = db()
    data, err = build_building_technical_data("command_center", user_id=uid, conn=conn)
    conn.close()

    assert err is None
    row = data["levels"][0]
    assert row["effect_kind"] == "bonus_percent"
    assert row["effect_value"] == 425
    assert data["levels"][1]["effect_value"] == 450
    assert data["levels"][1]["effect_value"] - row["effect_value"] == 25
