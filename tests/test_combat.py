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
    build_rapid_fire_matchup_payload,
    combat_stats_for_defense,
    combat_stats_for_ship,
    make_combat_side,
    rapid_fire_against,
    stacks_from_counts,
    validate_combat_registry,
)
from game.defense_defs import defense_display_name, defense_rapid_fire_multiplier
from game.fleet_defs import (
    rapid_fire_bonus_shot_chance,
    ship_display_name,
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


def test_build_rapid_fire_matchup_payload_ship_against_and_vulnerable():
    payload = build_rapid_fire_matchup_payload("falcon_interceptor", COMBAT_UNIT_SHIP)
    against = payload["rapid_fire_against"]
    assert against
    assert all(row["rapid_fire"] >= 2 for row in against)
    assert against[0]["rapid_fire"] >= against[-1]["rapid_fire"]
    assert any(row["target_key"] == "spark_drone" and row["rapid_fire"] == 3 for row in against)

    vulnerable = payload["vulnerable_to"]
    assert any(row["source_key"] == "plasma_arc" and row["rapid_fire"] == 2 for row in vulnerable)
    assert all(row["rapid_fire"] >= 2 for row in vulnerable)


def test_build_rapid_fire_matchup_payload_defense_includes_ships():
    payload = build_rapid_fire_matchup_payload("flak_array", COMBAT_UNIT_DEFENSE)
    against = payload["rapid_fire_against"]
    assert any(row["target_type"] == COMBAT_UNIT_SHIP and row["rapid_fire"] == 5 for row in against)
    assert not any(row["rapid_fire"] <= 1 for row in against)


def test_build_rapid_fire_matchup_payload_unknown_unit_is_safe():
    payload = build_rapid_fire_matchup_payload("unknown_hull_xyz", COMBAT_UNIT_SHIP)
    assert payload == {"rapid_fire_against": [], "vulnerable_to": []}


def test_build_rapid_fire_matchup_payload_no_rf_ship():
    payload = build_rapid_fire_matchup_payload("mule_courier", COMBAT_UNIT_SHIP)
    assert payload["rapid_fire_against"] == []


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


def test_round_structure_records_per_round_losses():
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


def test_shots_to_finish_hp_matches_pool_ceil():
    from game.combat import _shots_to_finish_hp

    assert _shots_to_finish_hp(0, 0, 10) == 0
    assert _shots_to_finish_hp(100, 100, 50) == 4
    assert _shots_to_finish_hp(30, 100, 100) == 2
    assert _shots_to_finish_hp(500, 2000, 0) >= 10**18


def test_apply_shots_bulk_partial_and_full_wipe():
    from game.combat import _apply_shots_bulk

    mods = CombatModifiers()
    units = _side_from_stacks([_stack("sentinel_turret", 5, unit_type=COMBAT_UNIT_DEFENSE)], mods=mods)
    unit = units[0]
    _apply_shots_bulk(unit, 1, 50, mods=mods)
    assert unit.amount == 5
    assert unit.current_hull == 150

    _apply_shots_bulk(unit, 1000, 50, mods=mods)
    assert unit.amount == 0


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


def test_firepower_tiebreak_waits_until_round_cap():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 1)])
    defender = make_combat_side(
        "defender",
        [_stack("pulse_barrier", 1, unit_type=COMBAT_UNIT_DEFENSE)],
    )
    result = simulate_battle(attacker, defender, max_rounds=6, rng=_rng(12))

    assert len(result.rounds) == 6
    assert result.winner == WINNER_ATTACKER
    assert result.attacker_losses == {}
    assert result.defender_losses == {}


def test_shields_refresh_between_combat_rounds():
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 10)])
    defender = make_combat_side(
        "defender",
        [_stack("pulse_barrier", 1, unit_type=COMBAT_UNIT_DEFENSE)],
    )
    result = simulate_battle(attacker, defender, max_rounds=6, rng=_rng(13))

    assert len(result.rounds) == 6
    assert result.defender_losses == {}


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
    from game.defense_defs import get_defense
    from game.fleet_defs import get_ship

    falcon_cost = (get_ship("falcon_interceptor") or {}).get("build_cost") or {}
    sentinel_cost = (get_defense("sentinel_turret") or {}).get("build_cost") or {}
    falcon_metal = int(falcon_cost.get("metal") or 0)
    falcon_crystal = int(falcon_cost.get("crystal") or 0)
    sentinel_metal = int(sentinel_cost.get("metal") or 0)
    sentinel_crystal = int(sentinel_cost.get("crystal") or 0)

    metal, crystal = calculate_debris_from_losses({"falcon_interceptor": 2})
    assert metal == int(falcon_metal * 2 * DEBRIS_METAL_FRACTION)
    assert crystal == int(falcon_crystal * 2 * DEBRIS_CRYSTAL_FRACTION)

    m2, c2 = calculate_combat_debris(
        {"falcon_interceptor": 1},
        {"sentinel_turret": 3},
    )
    assert m2 == int(falcon_metal * DEBRIS_METAL_FRACTION) + int(sentinel_metal * 3 * DEBRIS_METAL_FRACTION)
    assert c2 == int(falcon_crystal * DEBRIS_CRYSTAL_FRACTION) + int(sentinel_crystal * 3 * DEBRIS_CRYSTAL_FRACTION)


def test_build_combat_report_includes_debris_metadata():
    from game.combat import (
        DEBRIS_FIELD_TTL_SECONDS,
        build_combat_debris_metadata,
        build_combat_report,
        estimate_recycler_slots_needed,
    )
    from game.combat_models import CombatResult, CombatRound

    atk_loss = {"falcon_interceptor": 2}
    def_loss = {"sentinel_turret": 3}
    debris = build_combat_debris_metadata(atk_loss, def_loss)
    assert debris is not None
    assert debris["metal"] > 0
    assert debris["ttl"] == DEBRIS_FIELD_TTL_SECONDS
    assert debris["recycler_slots_needed"] == estimate_recycler_slots_needed(
        debris["metal"], debris["crystal"]
    )

    combat_result = CombatResult(
        winner="attacker",
        rounds=(CombatRound(1, atk_loss, def_loss),),
        attacker_losses=atk_loss,
        defender_losses=def_loss,
    )
    body, meta = build_combat_report(
        attacker_id=1,
        attacker_name="Attacker",
        defender_id=2,
        defender_name="Defender",
        coords="2:3:4",
        attacking_ships={"falcon_interceptor": 5},
        defending_ships={},
        defending_defense={"sentinel_turret": 4},
        combat_result=combat_result,
        locale="en",
    )
    assert meta["debris"] == debris
    assert "Debris field" in body
    assert "Recyclers needed:" in body
    from game.fleet_defs import ship_display_name
    from game.defense_defs import defense_display_name

    assert ship_display_name("falcon_interceptor", locale="en") in body
    assert defense_display_name("sentinel_turret", locale="en") in body
    assert "falcon_interceptor" not in body
    assert "sentinel_turret" not in body


def test_build_combat_report_omits_debris_when_none():
    from game.combat import build_combat_report
    from game.combat_models import CombatResult

    combat_result = CombatResult(
        winner="draw",
        rounds=(),
        attacker_losses={},
        defender_losses={},
    )
    body, meta = build_combat_report(
        attacker_id=1,
        attacker_name="A",
        defender_id=2,
        defender_name="D",
        coords="1:1:1",
        attacking_ships={},
        defending_ships={},
        combat_result=combat_result,
    )
    assert "debris" not in meta
    assert "Trümmerfeld" not in body and "Debris field" not in body


def test_build_combat_report_expo_pirate_shows_attacker_tech_npc_na():
    """Expo pirate real battles: player tech applies; NPC side is N/A (not fake L0)."""
    from game.combat import build_combat_report
    from game.combat_models import CombatResult

    combat_result = CombatResult(
        winner="defender",
        rounds=(),
        attacker_losses={"ironclad_frigate": 10},
        defender_losses={"spark_drone": 500},
    )
    body, meta = build_combat_report(
        attacker_id=1,
        attacker_name="Commander",
        defender_id=0,
        defender_name="Void Pirates",
        coords="1:6:16",
        attacking_ships={"ironclad_frigate": 100, "solar_skiff": 1000},
        defending_ships={"spark_drone": 80_000},
        combat_result=combat_result,
        locale="en",
        combat_kind="expedition_pirate",
    )
    assert meta.get("combat_research_applicable") is True
    assert meta.get("defender_combat_research_na") is True
    assert meta.get("defender_combat_research") is None
    assert meta.get("attacker_combat_research") is not None
    assert "NPC force" in body
    assert "Ratio skirmish" not in body


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


def _build_cost_metal_crystal(spec: dict) -> int:
    cost = spec.get("build_cost") or {}
    return int(cost.get("metal") or 0) + int(cost.get("crystal") or 0)


def _ships_for_budget(ship_key: str, budget: int) -> int:
    from game.fleet_defs import get_ship

    return max(1, budget // _build_cost_metal_crystal(get_ship(ship_key) or {}))


def _defense_for_budget(defense_key: str, budget: int) -> int:
    from game.defense_defs import get_defense

    return max(1, budget // _build_cost_metal_crystal(get_defense(defense_key) or {}))


def test_balance_scout_attack_not_extreme_vs_raptor():
    scout = combat_stats_for_ship("spark_drone")
    falcon = combat_stats_for_ship("falcon_interceptor")
    assert scout is not None and falcon is not None
    assert scout.attack >= 8
    assert falcon.attack / scout.attack <= 6.0


def test_balance_scout_squad_deals_damage_to_light_fleet():
    attacker = make_combat_side("attacker", [_stack("spark_drone", 50)])
    defender = make_combat_side("defender", [_stack("falcon_interceptor", 10)])
    result = simulate_battle(attacker, defender, rng=_rng(42))

    assert sum(result.defender_losses.values()) > 0


def test_balance_raptor_counters_unarmored_light_screen_over_full_rounds():
    budget = 50_000
    falcon_n = _ships_for_budget("falcon_interceptor", budget)
    scout_n = _ships_for_budget("spark_drone", budget)
    mass_raptor = make_combat_side("attacker", [_stack("falcon_interceptor", falcon_n)])
    mixed = make_combat_side(
        "defender",
        [
            _stack("falcon_interceptor", falcon_n // 2),
            _stack("spark_drone", scout_n // 2),
        ],
    )
    wins = sum(
        1
        for seed in range(20)
        if simulate_battle(mass_raptor, mixed, rng=_rng(seed)).winner == WINNER_ATTACKER
    )
    assert wins >= 16, f"{ship_display_name('falcon_interceptor')} should punish unarmored light screens over full rounds"


def test_balance_mass_raptor_not_dominant_vs_heavy_mixed_fleet():
    budget = 50_000
    falcon_n = _ships_for_budget("falcon_interceptor", budget)
    scout_n = _ships_for_budget("spark_drone", budget)
    mass_raptor = make_combat_side("attacker", [_stack("falcon_interceptor", falcon_n)])
    mixed = make_combat_side(
        "defender",
        [
            _stack("falcon_interceptor", falcon_n // 2),
            _stack("spark_drone", scout_n // 4),
            _stack("ironclad_frigate", 1),
        ],
    )
    wins = sum(
        1
        for seed in range(20)
        if simulate_battle(mass_raptor, mixed, rng=_rng(seed)).winner == WINNER_ATTACKER
    )
    assert wins < 16, f"mass {ship_display_name('falcon_interceptor')} should not clearly beat heavy mixed fleet"


def test_balance_mixed_fleet_beats_mass_raptor_as_attacker():
    budget = 50_000
    falcon_n = _ships_for_budget("falcon_interceptor", budget)
    scout_n = _ships_for_budget("spark_drone", budget)
    mixed = make_combat_side(
        "attacker",
        [
            _stack("spark_drone", scout_n // 4),
            _stack("falcon_interceptor", falcon_n // 2),
            _stack("ironclad_frigate", 1),
        ],
    )
    mass_raptor = make_combat_side("defender", [_stack("falcon_interceptor", falcon_n)])
    wins = sum(
        1
        for seed in range(20)
        if simulate_battle(mixed, mass_raptor, rng=_rng(seed + 100)).winner == WINNER_ATTACKER
    )
    assert wins >= 14, f"mixed fleet should outperform pure {ship_display_name('falcon_interceptor')} stack in at least one role"


def test_balance_equal_cost_raptor_does_not_trivially_beat_sentinel():
    budget = 50_000
    falcon_n = _ships_for_budget("falcon_interceptor", budget)
    sent_n = _defense_for_budget("sentinel_turret", budget)
    wins = sum(
        1
        for seed in range(20)
        if simulate_battle(
            make_combat_side("attacker", [_stack("falcon_interceptor", falcon_n)]),
            make_combat_side(
                "defender",
                [_stack("sentinel_turret", sent_n, unit_type=COMBAT_UNIT_DEFENSE)],
            ),
            rng=_rng(seed + 200),
        ).winner
        == WINNER_ATTACKER
    )
    assert wins <= 4, (
        f"equal-cost {defense_display_name('sentinel_turret')} wall should remain relevant vs "
        f"mass {ship_display_name('falcon_interceptor')}"
    )


def test_balance_ironclad_clears_defense_faster_than_raptor():
    falcon_losses = []
    iron_losses = []
    iron_def_kills = 0
    for seed in range(15):
        falcon = simulate_battle(
            make_combat_side("attacker", [_stack("falcon_interceptor", 10)]),
            make_combat_side(
                "defender",
                [_stack("plasma_arc", 15, unit_type=COMBAT_UNIT_DEFENSE)],
            ),
            rng=_rng(seed + 300),
        )
        iron = simulate_battle(
            make_combat_side("attacker", [_stack("ironclad_frigate", 2)]),
            make_combat_side(
                "defender",
                [_stack("plasma_arc", 15, unit_type=COMBAT_UNIT_DEFENSE)],
            ),
            rng=_rng(seed + 300),
        )
        falcon_losses.append(sum(falcon.attacker_losses.values()))
        iron_losses.append(sum(iron.attacker_losses.values()))
        iron_def_kills += sum(iron.defender_losses.values())
    assert sum(iron_losses) < sum(falcon_losses)
    assert iron_def_kills > 0


def test_mega_fleet_battle_completes_quickly():
    """Million-scale stacks must use aggregate path and finish in wall-clock budget."""
    attacker = make_combat_side(
        "attacker",
        [
            _stack("falcon_interceptor", 1_000_000),
            _stack("ironclad_frigate", 500_000),
            _stack("atlas_hauler", 1_000_000),
        ],
    )
    defender = make_combat_side(
        "defender",
        [
            _stack("ion_bastion", 2_000_000, unit_type=COMBAT_UNIT_DEFENSE),
            _stack("flak_array", 500_000, unit_type=COMBAT_UNIT_DEFENSE),
            _stack("sentinel_turret", 50_000, unit_type=COMBAT_UNIT_DEFENSE),
        ],
    )
    t0 = time.perf_counter()
    result = simulate_battle(attacker, defender, rng=_rng(99))
    elapsed = time.perf_counter() - t0
    assert result.winner in (WINNER_ATTACKER, WINNER_DEFENDER, WINNER_DRAW)
    assert elapsed < 2.5, f"mega fleet battle too slow: {elapsed:.3f}s"


def test_exact_path_unchanged_for_small_seeded_battle():
    """Regression: small fleets stay on exact per-hull path and stay deterministic."""
    attacker = make_combat_side("attacker", [_stack("falcon_interceptor", 120)])
    defender = make_combat_side("defender", [_stack("ironclad_frigate", 40)])
    a = simulate_battle(attacker, defender, rng=_rng(4242))
    b = simulate_battle(attacker, defender, rng=_rng(4242))
    assert a == b

