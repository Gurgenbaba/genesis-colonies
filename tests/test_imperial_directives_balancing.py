"""GC-915 — Imperial Directives balancing hard-cap tests."""

from __future__ import annotations

import pytest

from game.directives.balancing import (
    DIRECTIVE_TARGET_CAPS,
    compute_directive_target,
    directive_hard_cap,
    is_directive_target_stale,
)
from game.directives.definitions import CADENCE_DAILY, CADENCE_WEEKLY


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


@pytest.mark.parametrize(
    "key,max_daily",
    [
        ("upgrade_buildings", 15),
        ("launch_expeditions", 12),
        ("complete_expeditions", 12),
        ("send_fleet_missions", 50),
        ("complete_research", 3),
        ("win_battles", 3),
        ("defeat_pirates", 5),
        ("start_research", 2),
    ],
)
def test_hard_caps_never_exceeded_daily(key, max_daily):
    contexts = [
        {"total_score": 500, "daily_production": {"combined": 50_000}},
        {"total_score": 20_000, "daily_production": {"combined": 2_000_000}},
        {"total_score": 500_000_000, "daily_production": {"combined": 50_000_000_000}},
    ]
    for ctx in contexts:
        for rarity in ("common", "rare", "epic", "legendary"):
            target = compute_directive_target(
                _defn(key, scale_profile="count_medium" if "expedition" in key or key == "send_fleet_missions" else "count_light"),
                rarity=rarity,
                cadence=CADENCE_DAILY,
                context=ctx,
            )
            assert target <= max_daily, f"{key}/{rarity}/score={ctx['total_score']} -> {target}"


def test_fleet_missions_allowed_tiers():
    ctx = {"total_score": 50_000_000, "daily_production": {"combined": 1_000_000}}
    target = compute_directive_target(
        _defn("send_fleet_missions", scale_profile="count_light"),
        rarity="legendary",
        cadence=CADENCE_DAILY,
        context=ctx,
    )
    assert target in (10, 20, 30, 40, 50)


def test_expedition_tiers_small():
    ctx = {"total_score": 300_000_000_000, "daily_production": {"combined": 99_000_000_000}}
    target = compute_directive_target(
        _defn("launch_expeditions", scale_profile="count_medium"),
        rarity="epic",
        cadence=CADENCE_DAILY,
        context=ctx,
    )
    assert target <= 12


def test_produce_scales_with_daily_production_not_billions_floor():
    early = compute_directive_target(
        _defn("produce_metal", objective_kind="accumulate", scale_profile="produce", filters={"resource": "metal"}),
        rarity="common",
        cadence=CADENCE_DAILY,
        context={"total_score": 1_000, "daily_production": {"metal": 24_000}},
    )
    late = compute_directive_target(
        _defn("produce_metal", objective_kind="accumulate", scale_profile="produce", filters={"resource": "metal"}),
        rarity="rare",
        cadence=CADENCE_DAILY,
        context={"total_score": 500_000_000, "daily_production": {"metal": 24_000_000}},
    )
    assert 500 <= early <= 50_000
    assert late > early
    assert late <= 25_000_000


def test_stale_detection_over_cap():
    assert is_directive_target_stale("send_fleet_missions", 51, cadence=CADENCE_DAILY)
    assert is_directive_target_stale("launch_expeditions", 13, cadence=CADENCE_DAILY)
    assert not is_directive_target_stale("launch_expeditions", 12, cadence=CADENCE_DAILY)


def test_directive_hard_cap_table_complete():
    for key, (daily, weekly) in DIRECTIVE_TARGET_CAPS.items():
        assert directive_hard_cap(key, cadence=CADENCE_DAILY) == daily
        assert directive_hard_cap(key, cadence=CADENCE_WEEKLY) == weekly


def test_balancing_examples_early_mid_endgame():
    """Documented feel targets for regression."""
    early_ctx = {"total_score": 2_000, "daily_production": {"metal": 12_000, "combined": 36_000}}
    mid_ctx = {"total_score": 250_000, "daily_production": {"metal": 600_000, "combined": 1_800_000}}
    end_ctx = {"total_score": 80_000_000, "daily_production": {"metal": 120_000_000, "combined": 360_000_000}}

    early_exp = compute_directive_target(
        _defn("launch_expeditions", scale_profile="count_medium"),
        rarity="common",
        cadence=CADENCE_DAILY,
        context=early_ctx,
    )
    mid_fleet = compute_directive_target(
        _defn("send_fleet_missions"),
        rarity="rare",
        cadence=CADENCE_DAILY,
        context=mid_ctx,
    )
    end_build = compute_directive_target(
        _defn("upgrade_buildings"),
        rarity="epic",
        cadence=CADENCE_DAILY,
        context=end_ctx,
    )
    assert early_exp in (5, 8)
    assert 10 <= mid_fleet <= 50
    assert end_build <= 15
