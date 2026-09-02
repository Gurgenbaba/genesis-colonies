"""Canonical production contract: Nexus -> L200 -> Mine Ascension."""

from pathlib import Path

from game.buildings import _effective_building_queue_cap
from game.effects.effect_resolver import EffectResolver
from game.mine_evolution import UNCAPPED_BUILDING_LEVEL, required_level_for_evolution


def test_nexus_limits_normal_mine_progression_and_caps_at_200():
    low = EffectResolver({"planet_core_nexus": 20, "geothermal_nexus": 10}, {})
    assert low.get_max_building_level("metal_mine") == 90

    maxed = EffectResolver({"planet_core_nexus": 100, "geothermal_nexus": 100}, {})
    assert maxed.get_max_building_level("metal_mine") == 200
    assert maxed.get_max_building_level("crystal_mine") == 200
    assert maxed.get_max_building_level("fuel_cell_plant") == 200


def test_rank_zero_cannot_bypass_current_nexus_cap():
    assert _effective_building_queue_cap(
        "metal_mine", 90, planet_id=1, evolution_rank=0
    ) == 90
    assert _effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=0
    ) == 200


def test_ascension_takes_over_after_level_200_in_25_level_steps():
    assert required_level_for_evolution(1) == 200
    assert required_level_for_evolution(2) == 225
    assert required_level_for_evolution(8) == 375
    assert required_level_for_evolution(9) == 400

    assert _effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=1
    ) == 225
    assert _effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=7
    ) == 375
    assert _effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=8
    ) == 400


def test_mando_level_385_needs_rank_viii_then_can_build_to_400():
    before = _effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=7
    )
    after = _effective_building_queue_cap(
        "metal_mine", 200, planet_id=1, evolution_rank=8
    )
    assert before == 375
    assert 385 > before
    assert after == 400
    assert 386 <= after


def test_legacy_uncapped_sentinel_still_cannot_skip_ascension_gates():
    assert _effective_building_queue_cap(
        "metal_mine", UNCAPPED_BUILDING_LEVEL, planet_id=1, evolution_rank=0
    ) == 200
    assert _effective_building_queue_cap(
        "metal_mine", UNCAPPED_BUILDING_LEVEL, planet_id=1, evolution_rank=2
    ) == 250


def test_ascension_error_has_localized_user_feedback():
    src = Path("static/main.js").read_text(encoding="utf-8")
    block = src.split("function mapActionError(reason, payload)", 1)[1].split("\n  function ", 1)[0]
    assert 'reason === "ascension_required"' in block
    assert 't("buildings_mine_evo_progress"' in block
    assert 't("buildings_mine_evo_action"' in block


def test_shipyard_ascension_increases_ships_per_cycle():
    from game.shipyard import orbital_production_batch_capacity

    base = orbital_production_batch_capacity(50, forge_rank=0)
    rank1 = orbital_production_batch_capacity(50, forge_rank=1)
    rank5 = orbital_production_batch_capacity(50, forge_rank=5)
    assert rank1 > base
    assert rank5 > rank1


def test_docs_lock_both_ascension_contracts():
    mine_doc = Path("docs/MINE_EVOLUTION.md").read_text(encoding="utf-8")
    forge_doc = Path("docs/STELLAR_FORGE.md").read_text(encoding="utf-8")
    assert "Nexuses are the normal building-limit system" in mine_doc
    assert "ships built per production cycle" in forge_doc
    assert "orbital_production_batch_capacity(..., forge_rank)" in forge_doc
