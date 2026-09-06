"""No-max runtime contract for Shipyard / Defense / Troop production curves."""

from __future__ import annotations

import math
from pathlib import Path

import game.defense as defense
from game.shipyard import (
    BUILD_TIME_LEVEL_FACTOR,
    _effective_build_seconds,
    orbital_production_batch_capacity,
    production_level_cycle_seconds,
    production_level_reduction_pct,
)
from game.troops import unit_train_seconds

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400


def test_orbital_capacity_handles_10_pow_400_level_exactly():
    expected_base = 10**920 + 5 * HUGE + 1

    assert orbital_production_batch_capacity(HUGE) == expected_base
    assert orbital_production_batch_capacity(HUGE, forge_rank=2) == expected_base * 4


def test_orbital_capacity_handles_huge_level_and_huge_forge_rank_together():
    expected_base = 10**920 + 5 * HUGE + 1
    numerator = 2 + 3 * HUGE
    expected = (expected_base * numerator) // 2

    assert orbital_production_batch_capacity(HUGE, forge_rank=HUGE) == expected


def test_unit_cycle_decay_saturates_at_existing_one_second_floor():
    assert production_level_cycle_seconds(120, HUGE) == 1
    assert production_level_cycle_seconds(120, HUGE, level_factor=0.90) == 1
    assert production_level_reduction_pct(HUGE) == 100
    assert production_level_reduction_pct(HUGE, level_factor=0.90) == 100


def test_normal_shipyard_curve_stays_legacy_compatible():
    for level in (1, 2, 5, 10, 50):
        legacy_seconds = max(
            1,
            int(math.ceil(120 * (BUILD_TIME_LEVEL_FACTOR ** (level - 1)))),
        )
        legacy_reduction = (
            int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (level - 1)) * 100))
            if level > 1
            else 0
        )
        assert production_level_cycle_seconds(120, level) == legacy_seconds
        assert production_level_reduction_pct(level) == legacy_reduction

    assert orbital_production_batch_capacity(1) == 7
    assert orbital_production_batch_capacity(2) == 15
    assert orbital_production_batch_capacity(5) == 66
    assert orbital_production_batch_capacity(10) == 250


def test_ship_defense_and_troop_consumers_share_no_max_floor(monkeypatch):
    assert _effective_build_seconds(
        "mule_courier",
        HUGE,
        build_time_speed=1.0,
    ) == 1

    monkeypatch.setattr(defense, "_defense_speed_multiplier", lambda conn=None: 1.0)
    assert defense.unit_build_seconds("sentinel_turret", HUGE) == 1

    assert unit_train_seconds("militia", HUGE) == 1


def test_unit_production_sources_do_not_reintroduce_huge_level_float_pow():
    shipyard = (ROOT / "game" / "shipyard.py").read_text(encoding="utf-8")
    defense_src = (ROOT / "game" / "defense.py").read_text(encoding="utf-8")
    troops = (ROOT / "game" / "troops.py").read_text(encoding="utf-8")
    buildings = (ROOT / "game" / "buildings.py").read_text(encoding="utf-8")
    technical = (ROOT / "game" / "technical_data.py").read_text(encoding="utf-8")
    forge = (ROOT / "game" / "stellar_forge" / "formulas.py").read_text(encoding="utf-8")

    assert "base = _orbital_capacity_base(lvl)" in shipyard
    assert "ctx.power(dec_lvl, Decimal(\"2.3\"))" in shipyard
    assert "production_level_cycle_seconds(base, lvl)" in shipyard

    assert "BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)" not in defense_src
    assert "BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)" not in troops
    assert "BUILD_TIME_LEVEL_FACTOR **" not in buildings
    assert "BUILD_TIME_LEVEL_FACTOR **" not in technical

    assert "production_level_reduction_pct" in buildings
    assert "production_level_reduction_pct" in technical
    assert "base_digits + numerator_digits + 64" in forge
