"""
Research lab requirement resolution (empire-wide lab level vs active planet).

Run: python -m pytest tests/test_research_requirements.py -v
"""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.logic import refresh_player_live_state
from game.models import create_user, get_homeworld, init_db, save_planet_buildings
from game.planet_evolution.service import colonize_planet, set_active_planet
from game.research import (
    get_player_research_lab_level,
    get_research_status,
    queue_research,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def research_db(tmp_path, monkeypatch):
    db_file = tmp_path / "research_requirements.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
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


def _create_player() -> tuple[int, str]:
    uname = f"reslab_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    return int(user["id"]), uname


def _second_planet(player_id: int) -> int:
    ok, reason, extra = colonize_planet(
        player_id,
        name=f"Colony_{uuid.uuid4().hex[:4]}",
        galaxy=1,
        system=300,
        position=2,
    )
    assert ok, reason
    return int(extra["planet_id"])


def _tech(status: dict, key: str) -> dict:
    for tech in status.get("techs") or []:
        if tech.get("key") == key:
            return tech
    raise AssertionError(f"tech {key} not found")


def test_player_with_lab_on_homeworld_unlocks_tech_on_active_colony(research_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)

    save_planet_buildings(hw_id, {"research_lab": 1, "metal_mine": 1, "solar_plant": 1})
    save_planet_buildings(colony_id, {"metal_mine": 1, "solar_plant": 1})

    set_active_planet(player_id, colony_id)

    _, buildings, _, _, _, _ = refresh_player_live_state(player_id)
    assert int(buildings.get("research_lab", 0) or 0) == 0
    assert get_player_research_lab_level(player_id) == 1

    status = get_research_status(player_id, buildings=buildings, skip_finish=True)
    assert status["lab_level"] == 1
    assert _tech(status, "energy_tech")["requirements_met"] is True


def test_player_without_lab_anywhere_keeps_tech_locked(research_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    save_planet_buildings(hw_id, {"metal_mine": 1, "solar_plant": 1})

    status = get_research_status(player_id, skip_finish=True)
    assert status["lab_level"] == 0
    assert _tech(status, "energy_tech")["requirements_met"] is False


def test_research_page_renders_empire_lab_level_chip(research_db, monkeypatch):
    import app as app_module

    monkeypatch.setattr(dbmod, "DB_PATH", research_db)
    monkeypatch.setattr(models, "DB_PATH", research_db)
    importlib.reload(app_module)

    player_id, uname = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    colony_id = _second_planet(player_id)

    save_planet_buildings(hw_id, {"research_lab": 2, "metal_mine": 1, "solar_plant": 1})
    save_planet_buildings(colony_id, {"metal_mine": 1, "solar_plant": 1})
    set_active_planet(player_id, colony_id)

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    html = client.get("/research").get_data(as_text=True)

    assert re.search(r'class="lab-level-highlight">\s*2\s*<', html)
    assert "research_start/energy_tech" in html


def test_requirement_tooltip_uses_research_lab_building_key(research_db):
    player_id, _ = _create_player()
    hw_id = int(get_homeworld(player_id=player_id)["id"])
    save_planet_buildings(hw_id, {"research_lab": 0, "metal_mine": 1, "solar_plant": 1})

    status = get_research_status(player_id, skip_finish=True)
    items = _tech(status, "energy_tech")["requirements_items"]
    assert len(items) == 1
    assert items[0]["kind"] == "building"
    assert items[0]["key"] == "research_lab"
    assert items[0]["met"] is False

    save_planet_buildings(hw_id, {"research_lab": 1, "metal_mine": 1, "solar_plant": 1})
    status_ok = get_research_status(player_id, skip_finish=True)
    items_ok = _tech(status_ok, "energy_tech")["requirements_items"]
    assert items_ok[0]["have"] == 1
    assert items_ok[0]["met"] is True

    de = json.loads((ROOT / "locales" / "de.json").read_text(encoding="utf-8"))
    assert de["building_research_lab"] == "Forschungslabor"
    assert de["building_academy"] == "Genesis-Akademie"


def test_queue_research_uses_empire_lab_not_homeworld_only(research_db):
    player_id, _ = _create_player()
    hw = get_homeworld(player_id=player_id)
    colony_id = _second_planet(player_id)

    save_planet_buildings(int(hw["id"]), {"metal_mine": 1, "solar_plant": 1})
    save_planet_buildings(colony_id, {"research_lab": 1, "metal_mine": 1, "solar_plant": 1})

    conn = dbmod.db()
    conn.execute(
        "UPDATE planets SET metal = 50000, crystal = 50000 WHERE player_id = ?;",
        (player_id,),
    )
    conn.commit()
    conn.close()

    player = models.load_player(player_id)
    ok, reason, _ = queue_research(player, "energy_tech")
    assert ok, reason
