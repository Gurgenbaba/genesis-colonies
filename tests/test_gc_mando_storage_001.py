"""GC-MANDO-STORAGE-001 — late-game depots keep a real L450+ production buffer."""

from game.economy_balance import (
    STORAGE_ENDGAME_FULL_LEVEL,
    STORAGE_ENDGAME_MAX_HOURS,
    STORAGE_ENDGAME_START_LEVEL,
    STORAGE_REFERENCE_HOURS,
    STORAGE_REFERENCE_MINE_LEVEL_FACTOR,
    STORAGE_REFERENCE_RESOURCE,
    storage_capacity_at_depot_level,
    storage_reference_hours_at_depot_level,
)
from game.production_formula import mine_output_decimal


def test_early_storage_anchor_is_unchanged():
    assert storage_reference_hours_at_depot_level(1) == STORAGE_REFERENCE_HOURS == 24
    assert storage_reference_hours_at_depot_level(STORAGE_ENDGAME_START_LEVEL) == 24


def test_endgame_storage_horizon_keeps_growing_after_three_day_anchor():
    assert STORAGE_ENDGAME_START_LEVEL == 50
    assert storage_reference_hours_at_depot_level(100) == 48
    assert STORAGE_ENDGAME_FULL_LEVEL == 150
    assert storage_reference_hours_at_depot_level(150) == STORAGE_ENDGAME_MAX_HOURS == 72
    assert storage_reference_hours_at_depot_level(200) == 96
    assert storage_reference_hours_at_depot_level(300) == 144
    assert storage_reference_hours_at_depot_level(450) == 216
    assert storage_reference_hours_at_depot_level(999) > 216


def test_l150_depot_buffers_three_days_of_l450_reference_mine():
    depot_level = 150
    mine_level = depot_level * STORAGE_REFERENCE_MINE_LEVEL_FACTOR
    assert mine_level == 450
    production_per_hour = mine_output_decimal(STORAGE_REFERENCE_RESOURCE, mine_level)
    cap = storage_capacity_at_depot_level(depot_level)
    assert cap >= int(production_per_hour * 72)


def test_endgame_storage_capacity_stays_monotonic():
    previous = storage_capacity_at_depot_level(45)
    for level in range(46, 181):
        current = storage_capacity_at_depot_level(level)
        assert current > previous
        previous = current
