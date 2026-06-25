"""GC-603 — upgrade reward feedback (effect preview + energy draw)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import (
    BUILDING_ENERGY_CONSUMERS,
    _make_panel_row,
    get_buildings_panel_delta,
    get_overview_building_rows,
)
from game.effects import EffectResolver
from game.models import (
    create_user,
    get_homeworld,
    get_planet_buildings,
    get_research_levels,
    init_db,
    save_planet_buildings,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def preview_db(tmp_path, monkeypatch):
    db_file = tmp_path / "building_preview.db"
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
    uname = f"preview_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    return int(user["id"])


def _panel_row(player_id: int, building_type: str, buildings: dict) -> dict:
    planet = get_homeworld(player_id=player_id)
    save_planet_buildings(int(planet["id"]), buildings)
    b = get_planet_buildings(int(planet["id"]))
    research = get_research_levels(user_id=player_id)
    return _make_panel_row(planet, b, research, building_type, ratio=1.0)


class TestUpgradeEffectPreview:
    def test_metal_mine_production_preview_increases_with_level(self, preview_db):
        row = _panel_row(preview_db, "metal_mine", {"metal_mine": 5, "solar_plant": 3})
        assert row["effect_kind"] == "production"
        assert row["effect_current"] > 0
        assert row["effect_next"] > row["effect_current"]
        assert row["effect_delta"] == row["effect_next"] - row["effect_current"]
        assert row["production_per_hour"] == row["effect_current"]

    def test_metal_mine_secondary_energy_draw(self, preview_db):
        row = _panel_row(preview_db, "metal_mine", {"metal_mine": 4, "solar_plant": 2})
        sec = row.get("secondary_effect")
        assert sec is not None
        assert sec["effect_kind"] == "energy_use"
        assert sec["effect_next"] > sec["effect_current"]
        assert sec["effect_delta"] > 0
        assert sec["effect_current"] > sec["effect_delta"]

    def test_metal_mine_delta_payload_keeps_energy_current(self, preview_db):
        planet = get_homeworld(player_id=preview_db)
        buildings = {"metal_mine": 47, "crystal_mine": 43, "solar_plant": 34, "fuel_cell_plant": 39}
        save_planet_buildings(int(planet["id"]), buildings)
        b = get_planet_buildings(int(planet["id"]))
        research = get_research_levels(user_id=preview_db)
        planet = dict(planet)
        planet["player_id"] = preview_db
        delta = get_buildings_panel_delta(planet, b, building_keys=["metal_mine"])
        row = delta["resources"][0]
        sec = row["secondary_effect"]
        assert sec["effect_kind"] == "energy_use"
        assert sec["effect_current"] > 100
        assert sec["effect_current"] > sec["effect_delta"]

    def test_solar_plant_energy_output_no_secondary(self, preview_db):
        row = _panel_row(preview_db, "solar_plant", {"solar_plant": 3})
        assert row["effect_kind"] == "energy"
        assert "secondary_effect" not in row

    def test_fuel_cell_has_production_and_energy_secondary(self, preview_db):
        row = _panel_row(
            preview_db,
            "fuel_cell_plant",
            {"fuel_cell_plant": 2, "solar_plant": 3, "crystal_mine": 2},
        )
        assert row["effect_kind"] == "production"
        sec = row.get("secondary_effect")
        assert sec is not None
        assert sec["effect_kind"] == "energy_use"

    def test_building_energy_draw_matches_resolver(self, preview_db):
        buildings = {"metal_mine": 6, "crystal_mine": 0, "solar_plant": 1}
        planet = get_homeworld(player_id=preview_db)
        save_planet_buildings(int(planet["id"]), buildings)
        b = get_planet_buildings(int(planet["id"]))
        r = EffectResolver(b, get_research_levels(user_id=preview_db))
        draw = r.building_energy_draw("metal_mine")
        assert draw == int(10 * (6 ** 1.25))
        assert "metal_mine" in BUILDING_ENERGY_CONSUMERS

    def test_overview_building_rows_keys(self, preview_db):
        planet = get_homeworld(player_id=preview_db)
        buildings = get_planet_buildings(int(planet["id"]))
        rows = get_overview_building_rows(planet, buildings)
        keys = [r["key"] for r in rows]
        assert keys == ["metal_mine", "crystal_mine", "solar_plant"]
        for row in rows:
            assert "effect_current" in row
            assert "effect_next" in row
            assert "effect_delta" in row
