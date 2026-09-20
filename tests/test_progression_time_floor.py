"""Global normal-progression duration floor.

Normal speed stacks may never collapse server-calculated progression/production
queues to instant or 1-second jobs. Explicit skip mechanics are separate.
"""

from __future__ import annotations

from game.effects import EffectResolver
from game.shipyard import production_job_duration_seconds, production_level_cycle_seconds
from game.time_floors import (
    MIN_PROGRESS_DURATION_SECONDS,
    building_progress_floor_seconds,
)


def test_canonical_progression_floor_is_ten_seconds():
    assert MIN_PROGRESS_DURATION_SECONDS == 10


def test_endgame_production_mines_gain_progressive_floor_without_level_cap():
    assert building_progress_floor_seconds("metal_mine", 200) == 10
    assert building_progress_floor_seconds("metal_mine", 224) == 10
    assert building_progress_floor_seconds("metal_mine", 225) == 12
    assert building_progress_floor_seconds("crystal_mine", 300) == 30
    assert building_progress_floor_seconds("fuel_cell_plant", 400) == 82
    assert building_progress_floor_seconds("metal_mine", 500) == 166
    assert building_progress_floor_seconds("metal_mine", 650) == 352
    assert building_progress_floor_seconds("metal_mine", 10_000) == 3600
    assert building_progress_floor_seconds("research_lab", 650) == 10


def test_effect_resolver_enforces_endgame_mine_floor_after_extreme_speed_stack():
    resolver = EffectResolver(
        {"nanofactory": 10_000},
        {"buildtime_tech": 10_000},
        settings={"build_speed": 1_000_000_000.0},
    )
    assert resolver.get_build_time_seconds("metal_mine", 400) == 82
    assert resolver.get_build_time_seconds("metal_mine", 650) == 352
    assert resolver.get_build_time_seconds("research_lab", 400) == 10


def test_building_and_account_research_share_ten_second_floor():
    resolver = EffectResolver(
        {"nanofactory": 500, "research_lab": 500, "academy": 500},
        {"buildtime_tech": 500},
        settings={
            "build_speed": 1_000_000.0,
            "research_speed": 1_000_000.0,
        },
    )

    assert resolver.get_build_time_seconds("metal_mine", 1) == 10
    assert resolver.get_research_time_seconds("energy_tech", 1) == 10


def test_shared_yard_cycle_and_order_duration_never_drop_below_ten_seconds():
    assert production_level_cycle_seconds(1, 1_000_000) == 10
    assert production_job_duration_seconds(
        unit_seconds=1,
        amount=1,
        batch_capacity=1_000_000,
    ) == 10


def test_defense_final_speed_stack_cannot_break_floor():
    from game.defense import unit_build_seconds

    assert unit_build_seconds(
        "sentinel_turret",
        1_000,
        build_time_speed=1_000_000_000.0,
    ) == 10


def test_troop_training_inherits_shared_production_floor():
    from game.troops import unit_train_seconds
    from game.troop_defs import ACTIVE_TROOP_KEYS

    troop_key = next(iter(ACTIVE_TROOP_KEYS))
    assert unit_train_seconds(troop_key, 1_000_000) >= 10


def test_nodebuster_rebuild_scaling_uses_level_aware_build_floor():
    source = (__import__("pathlib").Path(__file__).resolve().parent.parent / "game" / "buildings.py").read_text(encoding="utf-8")
    assert "minimum=building_progress_floor_seconds(btype, target_level)" in source
    assert "minimum=building_progress_floor_seconds(building_type, target_level)" in source
    assert "minimum=building_progress_floor_seconds(building_type, target)" in source
