"""Unbounded runtime arithmetic contract for Imperial Directives."""

from __future__ import annotations

from pathlib import Path

from game.directives.balancing import compute_directive_target
from game.directives.definitions import (
    CADENCE_DAILY,
    CADENCE_WEEKLY,
    effective_base_target,
)
from game.directives.scaling import SCORE_ANCHOR, compute_scaled_target
from game.exact_math import scale_ratio_power_int

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400


def _defn(key: str, **overrides):
    base = {
        "key": key,
        "objective_kind": "count",
        "base_target": 3,
        "scale_profile": "count_light",
        "filters": {},
    }
    base.update(overrides)
    return base


def test_cap_aware_power_scaler_handles_10_pow_400():
    assert scale_ratio_power_int(
        5,
        HUGE,
        SCORE_ANCHOR,
        "0.25",
        cap=10,
    ) == 10

    assert scale_ratio_power_int(
        5,
        SCORE_ANCHOR,
        SCORE_ANCHOR,
        "0.25",
        cap=10,
    ) == 5


def test_legacy_scaled_target_saturates_without_float_overflow():
    assert compute_scaled_target(
        3,
        HUGE,
        scale_profile="count_light",
        cadence="daily",
    ) == 10
    assert compute_scaled_target(
        3,
        HUGE,
        scale_profile="count_medium",
        cadence="weekly",
    ) == 50


def test_zero_exponent_profile_stays_score_independent():
    assert compute_scaled_target(
        5000,
        HUGE,
        scale_profile="produce",
        cadence="daily",
    ) == 5000
    assert compute_scaled_target(
        5000,
        HUGE,
        scale_profile="produce",
        cadence="weekly",
    ) == 25_000


def test_player_facing_directives_remain_bounded_at_10_pow_400():
    launch = compute_directive_target(
        _defn("launch_expeditions", scale_profile="count_medium"),
        rarity="legendary",
        cadence=CADENCE_DAILY,
        context={"total_score": HUGE, "daily_production": {"combined": HUGE}},
    )
    ships = compute_directive_target(
        _defn("build_ships", scale_profile="ships"),
        rarity="legendary",
        cadence=CADENCE_DAILY,
        context={"total_score": HUGE, "daily_production": {"combined": HUGE}},
    )
    produce = compute_directive_target(
        _defn(
            "produce_metal",
            objective_kind="accumulate",
            scale_profile="produce",
            base_target=5000,
            filters={"resource": "metal"},
        ),
        rarity="legendary",
        cadence=CADENCE_DAILY,
        context={"total_score": HUGE, "daily_production": {"metal": HUGE}},
    )
    weekly_produce = compute_directive_target(
        _defn(
            "produce_metal",
            objective_kind="accumulate",
            scale_profile="produce",
            base_target=5000,
            filters={"resource": "metal"},
        ),
        rarity="legendary",
        cadence=CADENCE_WEEKLY,
        context={"total_score": HUGE, "daily_production": {"metal": HUGE}},
    )

    assert launch <= 12
    assert ships <= 80
    assert produce == 25_000_000
    assert weekly_produce == 120_000_000


def test_huge_admin_base_target_rarity_scaling_is_exact():
    definition = {
        "objective_kind": "count",
        "base_target": HUGE,
    }
    assert effective_base_target(definition, "rare") == HUGE
    assert effective_base_target(definition, "epic") == (HUGE * 6) // 5


def test_directive_runtime_sources_have_no_unbounded_float_roundtrips():
    scaling = (ROOT / "game" / "directives" / "scaling.py").read_text(
        encoding="utf-8"
    )
    balancing = (ROOT / "game" / "directives" / "balancing.py").read_text(
        encoding="utf-8"
    )
    definitions = (ROOT / "game" / "directives" / "definitions.py").read_text(
        encoding="utf-8"
    )

    for forbidden in (
        "float(score)",
        "float(SCORE_FLOOR)",
        "math.pow(",
    ):
        assert forbidden not in scaling

    for forbidden in (
        "float(score)",
        "float(daily)",
        "math.pow(",
        "math.log(",
    ):
        assert forbidden not in balancing

    assert "base * mult" not in definitions
    assert "scale_int(base, mult" in definitions
