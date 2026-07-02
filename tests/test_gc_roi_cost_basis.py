"""
ROI / amortisation — full upgrade cost basis (metal + crystal + fuel_cells).

Run: python -m pytest tests/test_gc_roi_cost_basis.py -v
"""

from __future__ import annotations

import math
import uuid

import pytest

from game.buildings import _make_panel_row
from game.economy_balance import (
    mine_upgrade_roi_hours,
    power_upgrade_cost,
    production_delta_per_hour,
    upgrade_roi_cost_basis,
    upgrade_roi_hours,
)
from game.models import create_user, get_homeworld, get_research_levels, save_planet_buildings


class TestUpgradeRoiCostBasis:
    def test_crystal_mine_roi_uses_metal_and_crystal(self):
        level = 39
        metal, crystal = power_upgrade_cost("crystal_mine", level)
        delta = production_delta_per_hour("crystal", level)
        roi = mine_upgrade_roi_hours("crystal_mine", level)
        expected = (metal + crystal) / delta
        assert roi == pytest.approx(expected)
        assert roi > (crystal / delta) * 1.4

    def test_metal_mine_roi_uses_metal_and_crystal(self):
        level = 40
        metal, crystal = power_upgrade_cost("metal_mine", level)
        delta = production_delta_per_hour("metal", level)
        roi = mine_upgrade_roi_hours("metal_mine", level)
        assert roi == pytest.approx((metal + crystal) / delta)
        assert crystal > 0

    def test_fuel_cell_plant_roi_includes_all_cost_parts(self):
        level = 25
        metal, crystal = power_upgrade_cost("fuel_cell_plant", level)
        fuel_extra = 12_000
        delta = production_delta_per_hour("fuel_cells", level)
        roi = mine_upgrade_roi_hours(
            "fuel_cell_plant",
            level,
            fuel_cells_cost=fuel_extra,
        )
        assert roi == pytest.approx((metal + crystal + fuel_extra) / delta)

    def test_roi_inf_when_delta_zero(self):
        assert upgrade_roi_hours(metal_cost=1000, crystal_cost=500, delta_per_hour=0) == float("inf")
        assert mine_upgrade_roi_hours("metal_mine", 1, delta_per_hour=0) == float("inf")

    def test_upgrade_roi_cost_basis_sums_all_parts(self):
        assert upgrade_roi_cost_basis(metal_cost=100, crystal_cost=50, fuel_cells_cost=25) == 175.0
        assert upgrade_roi_cost_basis(metal_cost=100, crystal_cost=50) == 150.0


class TestPanelRoiLiveDelta:
    @pytest.fixture()
    def roi_db(self, tmp_path, monkeypatch):
        import subprocess
        import sys
        from pathlib import Path

        import game.db as dbmod
        import game.models as models

        root = Path(__file__).resolve().parent.parent
        db_file = tmp_path / "roi_panel.db"
        monkeypatch.setenv("GC_DB_PATH", str(db_file))
        monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
        monkeypatch.setattr(dbmod, "DB_PATH", db_file)
        monkeypatch.setattr(models, "DB_PATH", db_file)
        subprocess.run(
            [sys.executable, str(root / "migrate.py")],
            cwd=str(root),
            check=True,
            capture_output=True,
            env={**dict(__import__("os").environ), "GC_DB_PATH": str(db_file)},
        )
        models.init_db()
        uname = f"roi_{uuid.uuid4().hex[:8]}"
        ok, _, user = create_user(uname, "test-pass-123")
        assert ok and user
        return int(user["id"])

    def test_panel_row_roi_uses_live_effect_delta(self, roi_db):
        planet = get_homeworld(player_id=roi_db)
        buildings = {"crystal_mine": 38, "metal_mine": 20, "solar_plant": 15}
        save_planet_buildings(int(planet["id"]), buildings)
        planet = dict(planet)
        planet["player_id"] = roi_db
        research = get_research_levels(user_id=roi_db)
        row = _make_panel_row(planet, buildings, research, "crystal_mine", ratio=1.0)
        delta = float(row["effect_delta"])
        cost = float(row["cost_metal"]) + float(row["cost_crystal"])
        assert row["upgrade_roi_hours"] == pytest.approx(round(cost / delta, 1), abs=0.2)
        assert delta > 0

    def test_panel_roi_updates_with_queued_level(self, roi_db):
        planet = get_homeworld(player_id=roi_db)
        buildings = {"crystal_mine": 10, "solar_plant": 8}
        save_planet_buildings(int(planet["id"]), buildings)
        planet = dict(planet)
        planet["player_id"] = roi_db
        research = get_research_levels(user_id=roi_db)
        row_one = _make_panel_row(planet, buildings, research, "crystal_mine", queue_count=0, ratio=1.0)
        row_two = _make_panel_row(planet, buildings, research, "crystal_mine", queue_count=1, ratio=1.0)
        assert row_two["target_level"] == row_one["target_level"] + 1
        assert row_two["cost_metal"] != row_one["cost_metal"] or row_two["cost_crystal"] != row_one["cost_crystal"]
        assert row_two["upgrade_roi_hours"] != row_one["upgrade_roi_hours"]


class TestTechnicalDataRoi:
    def test_technical_crystal_mine_full_cost_basis(self, tech_db):
        from game.buildings import build_building_technical_data
        from game.db import db
        from game.models import get_homeworld, save_planet_buildings

        planet = get_homeworld(player_id=tech_db)
        save_planet_buildings(int(planet["id"]), {"crystal_mine": 38, "solar_plant": 10})

        conn = db()
        data, err = build_building_technical_data("crystal_mine", user_id=tech_db, conn=conn)
        conn.close()
        assert err is None
        row39 = next(r for r in data["levels"] if r["level"] == 39)
        metal = int(row39["cost_metal"])
        crystal = int(row39["cost_crystal"])
        delta = float(row39["production_delta_per_hour"])
        roi = float(row39["upgrade_roi_hours"])
        assert roi == pytest.approx((metal + crystal) / delta, rel=0.02)
        assert not math.isinf(roi)


@pytest.fixture
def tech_db(tmp_path, monkeypatch):
    import subprocess
    import sys
    from pathlib import Path

    import game.db as dbmod
    import game.models as models
    from game.db import db
    from game.models import ensure_player_and_homeworld, init_db

    root = Path(__file__).resolve().parent.parent
    db_file = tmp_path / "roi_tech.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    subprocess.run(
        [sys.executable, str(root / "migrate.py")],
        cwd=str(root),
        check=True,
        capture_output=True,
        env={**dict(__import__("os").environ), "GC_DB_PATH": str(db_file)},
    )
    uname = f"roi_tech_{uuid.uuid4().hex[:8]}"
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
