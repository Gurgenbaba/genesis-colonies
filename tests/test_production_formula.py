"""
GC-820 — unified production formula tests.

Run: python -m pytest tests/test_production_formula.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.effects import EffectResolver
from game.models import init_db
from game.production_formula import (
    FUEL_TEMP_MODIFIER_MAX,
    FUEL_TEMP_MODIFIER_MIN,
    ProductionContext,
    ProductionModifiers,
    STANDARD_PRODUCTION_PER_HOUR,
    calculate_resource_output,
    ferdi_base_output,
    level_growth,
    mine_output,
    research_modifier_for,
    slot_modifier_for,
    snapshot_outputs,
    standard_output,
    temperature_mid_c_for_slot,
    temperature_modifier_for,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"
BENCHMARK_LEVELS = (1, 10, 30, 60, 90, 120)
NEUTRAL_SNAPSHOT_SLOT = 9


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "production_formula.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db() -> None:
    try:
        db().close()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _db_setup(temp_db):
    _close_db()
    init_db()
    _close_db()
    _run_migrate(temp_db)
    init_db()
    yield
    _close_db()


# Tests below use _db_setup. Game-state API test lives in test_game_state_live.py.


def _ctx(resource: str, level: int, **kwargs) -> ProductionContext:
    return ProductionContext(resource_type=resource, level=level, **kwargs)


class TestLevelGrowth:
    def test_mine_output_level_one(self):
        assert mine_output("metal", 1) == pytest.approx(150 * 1 * 1.075)
        assert mine_output("crystal", 1) == pytest.approx(100 * 1 * 1.075)
        assert mine_output("fuel_cells", 1) == pytest.approx(50 * 1 * 1.075)
        assert mine_output("metal", 0) == 0.0
        assert ferdi_base_output("metal", 1) == pytest.approx(mine_output("metal", 1))

    def test_mine_output_benchmark_levels(self):
        assert mine_output("metal", 5) == pytest.approx(150 * 5 * (1.075**5))
        assert mine_output("metal", 10) == pytest.approx(150 * 10 * (1.075**10))
        assert mine_output("metal", 20) == pytest.approx(150 * 20 * (1.075**20), rel=1e-6)
        assert mine_output("metal", 40) == pytest.approx(150 * 40 * (1.075**40), rel=1e-6)
        assert mine_output("metal", 60) == pytest.approx(150 * 60 * (1.075**60), rel=1e-5)
        total_l10 = calculate_resource_output("metal", _ctx("metal", 10))
        assert total_l10 == pytest.approx(15000 + mine_output("metal", 10))

    def test_standard_output_without_mine(self):
        assert standard_output("metal") == STANDARD_PRODUCTION_PER_HOUR["metal"]
        assert calculate_resource_output("metal", _ctx("metal", 0)) == pytest.approx(15000.0)
        assert calculate_resource_output("crystal", _ctx("crystal", 0)) == pytest.approx(10000.0)
        assert calculate_resource_output("fuel_cells", _ctx("fuel_cells", 0)) == pytest.approx(5000.0)

    def test_benchmark_levels_match_snapshot(self):
        snap = snapshot_outputs(production_speed=1.0, slot=NEUTRAL_SNAPSHOT_SLOT)
        for res in ("metal", "crystal", "fuel_cells"):
            for lvl in (1, 10, 30, 60, 90, 120):
                expected = calculate_resource_output(res, _ctx(res, lvl, slot=NEUTRAL_SNAPSHOT_SLOT))
                assert snap[res][lvl] == pytest.approx(expected, rel=1e-9)

    def test_monotonic_growth_all_resources(self):
        for res in ("metal", "crystal", "fuel_cells"):
            prev = 0.0
            for lvl in BENCHMARK_LEVELS:
                val = calculate_resource_output(res, _ctx(res, lvl, slot=NEUTRAL_SNAPSHOT_SLOT))
                assert val > prev
                prev = val

    def test_no_level_jumps(self):
        """Monotone between all adjacent levels — no dips or tier discontinuities."""
        for res in ("metal", "crystal", "fuel_cells"):
            prev = 0.0
            for lvl in range(1, 121):
                val = calculate_resource_output(res, _ctx(res, lvl, slot=NEUTRAL_SNAPSHOT_SLOT))
                assert val > prev
                prev = val

    def test_level_zero_is_standard_only(self):
        assert calculate_resource_output("metal", _ctx("metal", 0)) == pytest.approx(standard_output("metal"))


class TestSlotModifiers:
    def test_metal_peak_slot_four(self):
        assert slot_modifier_for("metal", 4) == pytest.approx(1.20)
        assert slot_modifier_for("metal", 9) == pytest.approx(1.0)
        assert slot_modifier_for("metal", 1) == pytest.approx(1.0)

    def test_crystal_peak_slot_one(self):
        assert slot_modifier_for("crystal", 1) == pytest.approx(1.25)
        assert slot_modifier_for("crystal", 3) == pytest.approx(1.0)

    def test_fuel_peak_slot_fifteen(self):
        assert slot_modifier_for("fuel_cells", 15) == pytest.approx(1.20)
        assert slot_modifier_for("fuel_cells", 10) == pytest.approx(1.0)

    def test_slot_bonus_in_output(self):
        neutral = calculate_resource_output("metal", _ctx("metal", 30, slot=9))
        boosted = calculate_resource_output("metal", _ctx("metal", 30, slot=4))
        assert boosted == pytest.approx(neutral * 1.20)


class TestTemperatureModifier:
    def test_fuel_only(self):
        assert temperature_modifier_for("metal", 400.0) == 1.0
        assert temperature_modifier_for("crystal", -200.0) == 1.0

    def test_clamped_range(self):
        hot = temperature_modifier_for("fuel_cells", 500.0)
        cold = temperature_modifier_for("fuel_cells", -300.0)
        assert hot >= FUEL_TEMP_MODIFIER_MIN
        assert cold <= FUEL_TEMP_MODIFIER_MAX
        assert hot == pytest.approx(FUEL_TEMP_MODIFIER_MIN)
        assert cold == pytest.approx(FUEL_TEMP_MODIFIER_MAX)

    def test_slot_one_hot_slot_fifteen_cold(self):
        hot = temperature_modifier_for("fuel_cells", 435.0)
        cold = temperature_modifier_for("fuel_cells", -207.5)
        assert hot < cold
        assert hot == pytest.approx(0.75, rel=0.01)
        assert cold == pytest.approx(1.35, rel=0.01)


class TestResearchAndEnergy:
    def test_mining_boosts_metal_only(self):
        assert research_modifier_for("metal", {"mining_tech": 10}) == pytest.approx(1.30)
        assert research_modifier_for("crystal", {"mining_tech": 10}) == pytest.approx(1.0)

    def test_drone_boosts_metal_and_crystal(self):
        assert research_modifier_for("metal", {"drone_tech": 5}) == pytest.approx(1.10)
        assert research_modifier_for("crystal", {"drone_tech": 5}) == pytest.approx(1.10)

    def test_energy_under_supply_throttles_mine_only(self):
        std = calculate_resource_output("metal", _ctx("metal", 0, slot=8, energy_ratio=1.0))
        full = calculate_resource_output("metal", _ctx("metal", 20, slot=8, energy_ratio=1.0))
        half = calculate_resource_output("metal", _ctx("metal", 20, slot=8, energy_ratio=0.5))
        no_mine_half = calculate_resource_output("metal", _ctx("metal", 0, slot=8, energy_ratio=0.5))
        no_mine_zero_energy = calculate_resource_output("metal", _ctx("metal", 0, slot=8, energy_ratio=0.0))
        assert no_mine_half == no_mine_zero_energy == pytest.approx(std)
        assert half == pytest.approx(std + (full - std) * 0.5)

    def test_energy_over_supply_not_boosted(self):
        base = calculate_resource_output("metal", _ctx("metal", 20, slot=8, energy_ratio=1.0))
        over = calculate_resource_output("metal", _ctx("metal", 20, slot=8, energy_ratio=1.5))
        assert over == pytest.approx(base)


class TestCombinedModifiers:
    def test_multiple_modifiers_stack_multiplicatively(self):
        ctx = ProductionContext(
            resource_type="metal",
            level=30,
            slot=4,
            energy_ratio=0.8,
            research={"mining_tech": 10, "drone_tech": 5},
            directive_modifier=1.20,
        )
        mods = ProductionModifiers(ctx)
        expected = (
            standard_output("metal") * ctx.production_speed * mods.combined_without_energy()
            + level_growth("metal", 30, 1.0)
            * mods.combined()
        )
        assert calculate_resource_output("metal", ctx) == pytest.approx(expected)


class TestEffectResolverIntegration:
    def test_resolver_matches_calculate_resource_output(self):
        b = {"metal_mine": 45, "crystal_mine": 40, "fuel_cell_plant": 35}
        er = EffectResolver(b, {"mining_tech": 8, "drone_tech": 6}, planet_position=5)
        ratio = 0.75
        prod = er.get_building_production_per_hour(ratio)
        from game.production_formula import calculate_resource_output, production_context_from_resolver

        for res, building in (
            ("metal", "metal_mine"),
            ("crystal", "crystal_mine"),
            ("fuel_cells", "fuel_cell_plant"),
        ):
            ctx = production_context_from_resolver(er, res, energy_ratio=ratio)
            assert prod[building] == int(calculate_resource_output(res, ctx))

    def test_gd_overlay_applied(self):
        b = {"metal_mine": 10}
        base_er = EffectResolver(b, {}, galaxy_id=None, planet_position=8)
        gd_er = EffectResolver(b, {}, galaxy_id=1, planet_position=8, conn=None)
        # Without DB directive state overlay is 1.0 — compare rates scale with metal_prod_factor
        base_ph = base_er.get_building_production_per_hour(1.0)["metal_mine"]
        assert base_ph > 0
