"""GC-911A / GC-915 — Imperial Directives scaling curve tests."""

from __future__ import annotations

import pytest

from game.directives.balancing import compute_directive_target
from game.directives.scaling import (
    SCORE_ANCHOR,
    SCORE_FLOOR,
    compute_scaled_target,
    produce_metal_anchor_samples,
)


def test_anchor_score_maps_base_target_one_to_one():
    target = compute_scaled_target(
        5,
        SCORE_ANCHOR,
        scale_profile="count_light",
        cadence="daily",
    )
    assert target == 5


def test_score_floor_prevents_zero_target():
    target = compute_scaled_target(
        10,
        0,
        scale_profile="count_light",
        cadence="daily",
    )
    assert target >= 1


def test_weekly_multiplier_increases_target():
    daily = compute_scaled_target(
        5,
        50_000,
        scale_profile="count_medium",
        cadence="daily",
    )
    weekly = compute_scaled_target(
        5,
        50_000,
        scale_profile="count_medium",
        cadence="weekly",
    )
    assert weekly > daily


def test_produce_scaling_monotonic_via_balancing():
    scores = [2_000, 250_000, 50_000_000]
    targets = [
        compute_directive_target(
            {
                "key": "produce_metal",
                "objective_kind": "accumulate",
                "scale_profile": "produce",
                "base_target": 5000,
                "filters": {"resource": "metal"},
            },
            rarity="common",
            cadence="daily",
            context={
                "total_score": score,
                "daily_production": {"metal": max(12_000, score * 10)},
            },
        )
        for score in scores
    ]
    assert targets == sorted(targets)


def test_count_objectives_stay_small_at_low_score():
    target = compute_scaled_target(
        3,
        SCORE_ANCHOR,
        scale_profile="count_light",
        cadence="daily",
    )
    assert 1 <= target <= 10


def test_count_objectives_capped_at_high_score():
    target = compute_scaled_target(
        3,
        300_000_000_000,
        scale_profile="count_light",
        cadence="daily",
    )
    assert target <= 10


def test_unknown_profile_falls_back():
    target = compute_scaled_target(
        4,
        SCORE_ANCHOR,
        scale_profile="nonexistent_profile",
        cadence="daily",
    )
    assert target >= 1


def test_score_dict_input():
    target = compute_scaled_target(
        5,
        {"total": SCORE_ANCHOR},
        scale_profile="count_light",
        cadence="daily",
    )
    assert target == 5


def test_exponent_effect():
    low_exp = compute_scaled_target(
        10,
        1_000_000,
        scale_profile="count_light",
        cadence="daily",
    )
    high_exp = compute_scaled_target(
        10,
        1_000_000,
        scale_profile="count_heavy",
        cadence="daily",
    )
    assert high_exp >= low_exp


def test_produce_metal_anchor_samples_bounded():
    samples = produce_metal_anchor_samples()
    assert all(500 <= v <= 25_000_000 for v in samples.values())
    ordered = [samples[s] for s in sorted(samples)]
    assert ordered == sorted(ordered)
