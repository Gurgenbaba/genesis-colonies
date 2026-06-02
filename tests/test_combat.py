"""Pure combat simulation tests (GC-500–GC-510)."""

from __future__ import annotations

import random
import time

import pytest

from game.combat import (
    WINNER_ATTACKER,
    WINNER_DEFENDER,
    WINNER_DRAW,
    CombatModifiers,
    _apply_damage_to_lead,
    _effective_attack,
    _effective_hull,
    _effective_shield,
    _side_from_stacks,
    battle_loser,
    combat_modifiers_from_effect_resolver,
    simulate_battle,
)
from game.effects.effect_resolver import EffectResolver
from game.combat_models import (
    COMBAT_UNIT_DEFENSE,
    COMBAT_UNIT_SHIP,
    CombatStack,
    combat_stats_for_defense,
    combat_stats_for_ship,
    make_combat_side,
    rapid_fire_against,
    stacks_from_counts,
    validate_combat_registry,
)
from game.defense_defs import defense_rapid_fire_multiplier
from game.fleet_defs import (
    rapid_fire_bonus_shot_chance,
    ship_rapid_fire_multiplier,
)


def _rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


def _stack(ship_key: str, amount: int, *, unit_type: str = COMBAT_UNIT_SHIP) -> CombatStack:
    if unit_type == COMBAT_UNIT_SHIP:
        stats = combat_stats_for_ship(ship_key)
    else:
        stats = combat_stats_for_defense(ship_key)
    assert stats is not None, f"unknown unit: {ship_key}"
    return CombatStack(
        unit_key=stats.unit_key,
        unit_type=stats.unit_type,
        amount=amount,
        stats=stats,
    )


def test_registry_has_no_combat_errors():
    assert validate_combat_registry() == []


def test_rapid_fire_multiplier_from_ship_defs():
    assert ship_rapid_fire_multiplier("falcon_interceptor", "spark_drone") == 3
    assert ship_rapid_fire_multiplier("falcon_interceptor", "mule_courier") == 1


def test_rapid_fire_multiplier_from_defense_defs():
    assert defense_rapid_fire_multiplier("flak_array", "spark_drone") == 5
    assert defense_rapid_fire_multiplier("flak_array", "orbital_shield") == 1


def test_rapid_fire_bonus_shot_chance_from_multiplier():
    assert rapid_fire_bonus_shot_chance(1) == 0.0
    assert rapid_fire_bonus_shot_chance(2) == 0.5
    assert rapid_fire_bonus_shot_chance(3) == pytest.approx(2 / 3)
    assert rapid_fire_bonus_shot_chance(5) == pytest.approx(0.8)


def test_effect_resolver_combat_modifiers_from_research():
    resolver = EffectResolver(
        {},
        {"weapon_tech": 4, "armor_tech": 2, "shield_tech": 6},
    )
    raw = resolver.get_combat_modifiers()
    assert raw["weapon_bonus"] == pytest.approx(0.20)
    assert raw["armor_bonus"] == pytest.approx(0.10)
    assert raw["shield_bonus"] == pytest.approx(0.30)

    mods = combat_modifiers_from_effect_resolver(resolver)
    assert mods.weapon_bonus == pytest.approx(0.20)
    assert mods.armor_bonus == pytest.approx(0.10)
    assert mods.shield_bonus == pytest.approx(0.30)


def test_research_weapon_tech_boosts_effective_attack():
    stats = combat_stats_for_ship("falcon_interceptor")
    assert stats is not None
    base = _effective_attack(stats, CombatModifiers())
    boosted = _effective_attack(
        stats,
        combat_modifiers_from_effect_resolver(EffectResolver({}, {"weapon_tech": 10})),
    )
    assert boosted == int(round(base * 1.5))


def test_research_armor_and_shield_tech_boost_hull_and_shield():
    stats = combat_stats_for_defense("pulse_barrier")
    assert stats is not None
    resolver = EffectResolver({}, {"armor_tech": 4, "shield_tech": 2})
    mods = combat_modifiers_from_effect_resolver(resolver)
    assert _effective_hull(stats, mods) == int(round(stats.hull * 1.2))
    assert _effective_shield(stats, mods) == int(round(stats.shield * 1.1))


def test_weapon_tech_increases_battle_damage_with_same_seed():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 20)])
    defender = make_combat_side("defender", [_stack("sentinel_turret", 20, unit_type=COMBAT_UNIT_DEFENSE)])
    baseline = simulate_battle(attacker, defender, rng=_rng(88))
    with_research = simulate_battle(
        attacker,
        defender,
        rng=_rng(88),
        attacker_modifiers=combat_modifiers_from_effect_resolver(
            EffectResolver({}, {"weapon_tech": 8})
        ),
    )
    assert sum(with_research.defender_losses.values()) >= sum(baseline.defender_losses.values())


def test_combat_stats_rapid_fire_matches_defs():
    falcon = combat_stats_for_ship("falcon_interceptor")
    assert falcon is not None
    assert rapid_fire_against(falcon, "spark_drone") == ship_rapid_fire_multiplier(
        "falcon_interceptor", "spark_drone"
    )


def test_empty_defender_attacker_wins_no_attacker_losses():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 5)])
    defender = make_combat_side("defender", [])
    result = simulate_battle(attacker, defender, rng=_rng())

    assert result.winner == WINNER_ATTACKER
    assert battle_loser(result.winner) == WINNER_DEFENDER
    assert result.attacker_losses == {}
    assert result.defender_losses == {}
    assert result.rounds == ()


def test_empty_attacker_defender_wins():
    attacker = make_combat_side("attacker", [])
    defender = make_combat_side("defender", [_stack("sentinel_turret", 3, unit_type=COMBAT_UNIT_DEFENSE)])
    result = simulate_battle(attacker, defender, rng=_rng())

    assert result.winner == WINNER_DEFENDER
    assert battle_loser(result.winner) == WINNER_ATTACKER
    assert result.attacker_losses == {}


def test_fleet_vs_fleet_seeded_reproducible():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 10)])
    defender = make_combat_side("defender", [_stack("ironclad_frigate", 8)])
    first = simulate_battle(attacker, defender, rng=_rng(12345))
    second = simulate_battle(attacker, defender, rng=_rng(12345))

    assert first == second
    assert first.winner in (WINNER_ATTACKER, WINNER_DEFENDER, WINNER_DRAW)
    assert sum(first.attacker_losses.values()) + sum(first.defender_losses.values()) > 0


def test_fleet_vs_defense_attacker_wins():
    attacker = make_combat_side("attacker", [_stack("ironclad_frigate", 20)])
    defender = make_combat_side(
        "defender",
        [_stack("sentinel_turret", 10, unit_type=COMBAT_UNIT_DEFENSE)],
    )
    result = simulate_battle(attacker, defender, rng=_rng(7))

    assert result.winner == WINNER_ATTACKER
    assert battle_loser(result.winner) == WINNER_DEFENDER
    assert sum(result.defender_losses.values()) == 10
    assert sum(result.attacker_losses.values()) == 0


def test_fleet_vs_mixed_defense_stacks():
    defender_stacks = stacks_from_counts(
        {"falcon_interceptor": 2},
        unit_type=COMBAT_UNIT_SHIP,
    ) + stacks_from_counts(
        {"sentinel_turret": 3, "plasma_arc": 1},
        unit_type=COMBAT_UNIT_DEFENSE,
    )
    attacker = make_combat_side("attacker", [_stack("ironclad_frigate", 15)])
    defender = make_combat_side("defender", defender_stacks)
    a = simulate_battle(attacker, defender, rng=_rng(99))
    b = simulate_battle(attacker, defender, rng=_rng(99))

    assert a == b
    assert a.winner == WINNER_ATTACKER
    assert sum(a.defender_losses.values()) > 0


def test_rapid_fire_increases_kills_vs_same_attack_without_rf():
    """Falcon (RF 3 vs spark_drone) vs mule (no RF) — similar round damage, more kills with RF."""
    falcon_attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 3)])
    mule_attacker = make_combat_side("attacker", [_stack("mule_courier", 30)])
    defender = make_combat_side("defender", [_stack("spark_drone", 25)])

    assert ship_rapid_fire_multiplier("falcon_interceptor", "spark_drone") == 3
    assert ship_rapid_fire_multiplier("mule_courier", "spark_drone") == 1

    falcon_result = simulate_battle(falcon_attacker, defender, rng=_rng(202))
    mule_result = simulate_battle(mule_attacker, defender, rng=_rng(202))

    assert sum(falcon_result.defender_losses.values()) > sum(mule_result.defender_losses.values())


def test_round_structure_attacker_then_defender_phase():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 5)])
    defender = make_combat_side("defender", [_stack("falcon_interceptor", 5)])
    result = simulate_battle(attacker, defender, max_rounds=6, rng=_rng(1))

    assert len(result.rounds) >= 1
    assert result.rounds[0].number == 1
    total_round_def_losses = sum(
        sum(r.defender_losses.values()) for r in result.rounds
    )
    assert total_round_def_losses == sum(result.defender_losses.values())


def test_weapon_bonus_increases_damage_with_same_seed():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 30)])
    defender = make_combat_side("defender", [_stack("sentinel_turret", 30, unit_type=COMBAT_UNIT_DEFENSE)])
    baseline = simulate_battle(attacker, defender, rng=_rng(7))
    boosted = simulate_battle(
        attacker,
        defender,
        rng=_rng(7),
        attacker_modifiers=CombatModifiers(weapon_bonus=0.5),
    )

    assert sum(boosted.defender_losses.values()) >= sum(baseline.defender_losses.values())


def test_max_rounds_cap_at_six():
    attacker = make_combat_side("attacker", [_stack("veil_probe", 50)])
    defender = make_combat_side(
        "defender",
        [_stack("orbital_shield", 5, unit_type=COMBAT_UNIT_DEFENSE)],
    )
    result = simulate_battle(attacker, defender, max_rounds=99, rng=_rng(0))

    assert len(result.rounds) <= 6
    assert result.winner == WINNER_DRAW
    assert sum(result.attacker_losses.values()) == 0


def test_input_stacks_not_mutated():
    stack = _stack("mule_courier", 4)
    original_amount = stack.amount
    attacker = make_combat_side("attacker", [stack])
    defender = make_combat_side("defender", [_stack("plasma_arc", 2, unit_type=COMBAT_UNIT_DEFENSE)])
    simulate_battle(attacker, defender, rng=_rng(11))

    assert stack.amount == original_amount


def test_accepts_raw_stack_sequences():
    attacker = [_stack("falcon_interceptor", 3)]
    defender = [_stack("sentinel_turret", 1, unit_type=COMBAT_UNIT_DEFENSE)]
    result = simulate_battle(attacker, defender, rng=_rng(5))

    assert result.winner in (WINNER_ATTACKER, WINNER_DEFENDER, WINNER_DRAW)
    assert isinstance(result.rounds, tuple)


def test_shield_absorbs_before_hull_on_lead_unit():
    stack = _stack("pulse_barrier", 1, unit_type=COMBAT_UNIT_DEFENSE)
    units = _side_from_stacks([stack], mods=CombatModifiers())
    unit = units[0]

    assert unit.current_shield == 500
    assert unit.current_hull == 2000

    _apply_damage_to_lead(unit, 300, mods=CombatModifiers())
    assert unit.amount == 1
    assert unit.current_shield == 200
    assert unit.current_hull == 2000

    _apply_damage_to_lead(unit, 250, mods=CombatModifiers())
    assert unit.amount == 1
    assert unit.current_shield == 0
    assert unit.current_hull == 1950


def test_hull_zero_destroys_unit_and_refreshes_next_copy():
    stack = _stack("sentinel_turret", 2, unit_type=COMBAT_UNIT_DEFENSE)
    units = _side_from_stacks([stack], mods=CombatModifiers())
    unit = units[0]

    _apply_damage_to_lead(unit, 200, mods=CombatModifiers())
    assert unit.amount == 1
    assert unit.current_shield == 0
    assert unit.current_hull == 200

    _apply_damage_to_lead(unit, 200, mods=CombatModifiers())
    assert unit.amount == 0
    assert unit.current_shield == 0
    assert unit.current_hull == 0


def test_shield_delays_defense_losses_in_battle():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 10)])
    defender = make_combat_side(
        "defender",
        [_stack("pulse_barrier", 1, unit_type=COMBAT_UNIT_DEFENSE)],
    )
    result = simulate_battle(attacker, defender, max_rounds=1, rng=_rng(3))

    assert sum(result.defender_losses.values()) == 0
    assert result.rounds[0].defender_losses == {}


def test_shield_bonus_reduces_hull_damage():
    stack = _stack("pulse_barrier", 1, unit_type=COMBAT_UNIT_DEFENSE)
    baseline = _side_from_stacks([stack], mods=CombatModifiers())[0]
    boosted = _side_from_stacks([stack], mods=CombatModifiers(shield_bonus=1.0))[0]

    _apply_damage_to_lead(baseline, 800, mods=CombatModifiers())
    _apply_damage_to_lead(boosted, 800, mods=CombatModifiers(shield_bonus=1.0))

    assert boosted.current_hull >= baseline.current_hull
    assert boosted.current_shield >= baseline.current_shield


def test_calculate_plunder_pool_fraction():
    from game.resources import calculate_plunder_pool

    pool = calculate_plunder_pool(
        {"metal": 10_000, "crystal": 4000, "fuel_cells": 200},
        plunder_fraction=0.5,
    )
    assert pool == {"metal": 5000, "crystal": 2000, "fuel_cells": 100}


def test_load_resources_up_to_cargo_respects_cap_and_order():
    from game.resources import load_resources_up_to_cargo

    pool = {"metal": 10_000, "crystal": 8000, "fuel_cells": 5000}
    assert load_resources_up_to_cargo(pool, 0) == {
        "metal": 0,
        "crystal": 0,
        "fuel_cells": 0,
    }
    assert load_resources_up_to_cargo(pool, 6000) == {
        "metal": 6000,
        "crystal": 0,
        "fuel_cells": 0,
    }
    assert load_resources_up_to_cargo(pool, 15_000) == {
        "metal": 10_000,
        "crystal": 5000,
        "fuel_cells": 0,
    }
    assert load_resources_up_to_cargo(pool, 50_000) == {
        "metal": 10_000,
        "crystal": 8000,
        "fuel_cells": 5000,
    }


def test_calculate_debris_from_ship_losses():
    from game.combat import (
        DEBRIS_CRYSTAL_FRACTION,
        DEBRIS_METAL_FRACTION,
        calculate_combat_debris,
        calculate_debris_from_losses,
    )

    metal, crystal = calculate_debris_from_losses({"falcon_interceptor": 2})
    assert metal == int(3000 * 2 * DEBRIS_METAL_FRACTION)
    assert crystal == int(1000 * 2 * DEBRIS_CRYSTAL_FRACTION)

    m2, c2 = calculate_combat_debris(
        {"falcon_interceptor": 1},
        {"sentinel_turret": 3},
    )
    assert m2 == int(3000 * DEBRIS_METAL_FRACTION) + int(200 * 3 * DEBRIS_METAL_FRACTION)
    assert c2 == int(1000 * DEBRIS_CRYSTAL_FRACTION) + int(100 * 3 * DEBRIS_CRYSTAL_FRACTION)


def test_both_sides_empty_returns_draw_without_rounds():
    attacker = make_combat_side("attacker", [])
    defender = make_combat_side("defender", [])
    result = simulate_battle(attacker, defender, rng=_rng())

    assert result.winner == WINNER_DRAW
    assert result.rounds == ()
    assert result.attacker_losses == {}
    assert result.defender_losses == {}


def test_empty_attacker_defender_wins_without_combat():
    attacker = make_combat_side("attacker", [])
    defender = make_combat_side(
        "defender",
        [_stack("sentinel_turret", 3, unit_type=COMBAT_UNIT_DEFENSE)],
    )
    result = simulate_battle(attacker, defender, rng=_rng())

    assert result.winner == WINNER_DEFENDER
    assert result.rounds == ()
    assert result.attacker_losses == {}
    assert result.defender_losses == {}


def test_empty_defender_attacker_wins_without_combat():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 4)])
    defender = make_combat_side("defender", [])
    result = simulate_battle(attacker, defender, rng=_rng())

    assert result.winner == WINNER_ATTACKER
    assert result.rounds == ()
    assert result.defender_losses == {}


def test_stacks_from_counts_skips_unknown_and_invalid_keys():
    stacks = stacks_from_counts(
        {"falcon_interceptor": 5, "unknown_ship": 99, "": 3, "bad": -1},
        unit_type=COMBAT_UNIT_SHIP,
    )
    assert len(stacks) == 1
    assert stacks[0].unit_key == "falcon_interceptor"
    assert stacks[0].amount == 5


def test_remaining_stock_applies_losses():
    from game.combat import remaining_stock

    stock = {"ironclad_frigate": 10, "sentinel_turret": 5}
    losses = {"ironclad_frigate": 3, "sentinel_turret": 8, "unknown": 100}
    remain = remaining_stock(stock, losses, canonical_ship_keys=True)

    assert remain == {"ironclad_frigate": 7}


def test_split_defender_losses_separates_ships_and_defense():
    from game.combat import split_defender_losses

    ships, defense = split_defender_losses(
        {
            "falcon_interceptor": 2,
            "sentinel_turret": 4,
            "not_a_unit": 9,
        }
    )
    assert ships == {"falcon_interceptor": 2}
    assert defense == {"sentinel_turret": 4}


def test_max_rounds_zero_still_runs_one_round_when_fighting():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 5)])
    defender = make_combat_side("defender", [_stack("falcon_interceptor", 5)])
    result = simulate_battle(attacker, defender, max_rounds=0, rng=_rng(1))

    assert len(result.rounds) == 1


def test_large_symmetric_battle_completes_quickly():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 200)])
    defender = make_combat_side("defender", [_stack("falcon_interceptor", 200)])
    start = time.perf_counter()
    result = simulate_battle(attacker, defender, max_rounds=6, rng=_rng(777))
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0
    assert result.winner in (WINNER_ATTACKER, WINNER_DEFENDER, WINNER_DRAW)
    assert len(result.rounds) >= 1


def test_balance_ironclad_fleet_beats_equal_sentinel_turrets():
    attacker = make_combat_side("attacker", [_stack("ironclad_frigate", 12)])
    defender = make_combat_side(
        "defender",
        [_stack("sentinel_turret", 8, unit_type=COMBAT_UNIT_DEFENSE)],
    )
    result = simulate_battle(attacker, defender, rng=_rng(505))

    assert result.winner == WINNER_ATTACKER
    assert sum(result.defender_losses.values()) > 0
