"""
GC-821E — production display fields & long-term mine ROI rebalance.

Run: python -m pytest tests/test_gc821e_production_display_roi.py -v
"""

from __future__ import annotations

import math

import pytest

from game.buildings import build_building_technical_data
from game.economy_balance import (
    MINE_UPGRADE_ROI_TARGET_HOURS,
    ROI_BENCHMARK_LEVELS,
    balance_snapshot_table,
    mine_upgrade_roi_hours,
    power_upgrade_cost,
    production_delta_per_hour,
)
from game.production_formula import calculate_resource_output, ProductionContext


class TestGc821eMineRoiCurve:
    def test_mine_cost_monotone(self):
        prev = 0
        for lvl in range(4, 121):
            metal, _ = power_upgrade_cost("metal_mine", lvl)
            assert metal > prev
            prev = metal

    @pytest.mark.parametrize("level", ROI_BENCHMARK_LEVELS)
    def test_metal_mine_roi_within_target_band(self, level):
        roi = mine_upgrade_roi_hours("metal_mine", level)
        target = MINE_UPGRADE_ROI_TARGET_HOURS[level]
        assert target * 0.65 <= roi <= target * 1.35, f"L{level} ROI {roi:.1f}h vs {target}h"

    def test_roi_uses_production_delta_not_total(self):
        lvl = 60
        metal_cost, crystal_cost = power_upgrade_cost("metal_mine", lvl)
        delta = production_delta_per_hour("metal", lvl)
        total = calculate_resource_output("metal", ProductionContext("metal", lvl - 1, slot=9))
        assert delta < total
        roi_delta = (metal_cost + crystal_cost) / delta
        roi_total = (metal_cost + crystal_cost) / total
        assert mine_upgrade_roi_hours("metal_mine", lvl) == pytest.approx(roi_delta)
        assert roi_delta > roi_total * 5

    def test_balance_snapshot_includes_roi_benchmarks(self):
        table = balance_snapshot_table()
        for lvl in ROI_BENCHMARK_LEVELS:
            assert lvl in table["metal_upgrade_roi_hours"]
            assert lvl in table["production_delta_per_hour"]
            assert table["production_delta_per_hour"][lvl]["metal"] > 0


class TestGc821eTechnicalDataFields:
    def test_metal_mine_technical_row_has_delta_and_roi(self, tech_db):
        from game.db import db
        from game.models import ensure_player_and_homeworld, get_homeworld, save_planet_buildings

        uid = tech_db
        planet = get_homeworld(player_id=uid)
        save_planet_buildings(int(planet["id"]), {"metal_mine": 19, "solar_plant": 5})

        conn = db()
        data, err = build_building_technical_data("metal_mine", user_id=uid, conn=conn)
        conn.close()

        assert err is None
        row20 = next(r for r in data["levels"] if r["level"] == 20)
        assert row20["production_delta_per_hour"] > 0
        assert row20["upgrade_roi_hours"] is not None
        assert row20["upgrade_roi_hours"] > 0
        assert row20["effect_value"] == row20["production_metal_per_hour"]
        assert not math.isinf(row20["upgrade_roi_hours"])


@pytest.fixture
def tech_db(tmp_path, monkeypatch):
    import uuid

    import game.db as dbmod
    import game.models as models
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld, init_db

    db_file = tmp_path / "gc821e.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    import migrate

    migrate.main()
    uname = f"gc821e_{uuid.uuid4().hex[:8]}"
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
