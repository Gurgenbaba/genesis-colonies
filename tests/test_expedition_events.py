"""Expedition loot scaling — canonical expo formula, cargo cap, lootboxes."""

from __future__ import annotations

import math

import pytest

from game.expedition_events import (
    EXPEDITION_LOOT_EXPONENT,
    EXPEDITION_RANDOM_FACTOR_RANGE,
    _VOIDRUNNER_DISCOVERY_BONUS,
    apply_expedition_ship_losses,
    build_expedition_fleet_rating,
    build_expedition_report,
    calculate_base_expedition_loot,
    calculate_expo_value,
    calculate_expedition_combat_value,
    calculate_expedition_escort_value,
    calculate_expedition_hull_value,
    calculate_expedition_loot_cap,
    calculate_expedition_recycler_cargo,
    calculate_fleet_value,
    expedition_event_weight_audit,
    expedition_ship_fleet_value,
    grant_expedition_lootboxes,
    is_allowed_expedition_lootbox,
    resolve_expedition_outcome,
    resolve_expedition_pirate_debris,
    resolve_minefield_hazard,
    resolve_pirate_encounter,
    roll_lost_container_lootboxes,
    roll_pirate_salvage_rewards,
)

_ODYSSEY_KEY = "solar_skiff"
_ODYSSEY_FLEET_VALUE = expedition_ship_fleet_value(_ODYSSEY_KEY)
_ODYSSEY_EXPO_UNIT = math.pow(_ODYSSEY_FLEET_VALUE, EXPEDITION_LOOT_EXPONENT)
_SMALL_FLEET = {_ODYSSEY_KEY: 1}
_MEDIUM_FLEET = {_ODYSSEY_KEY: 100}
_LARGE_EXPO_FLEET = {_ODYSSEY_KEY: 1000}
_ESCORT_FLEET = {_ODYSSEY_KEY: 10, "falcon_interceptor": 500, "atlas_hauler": 200}


def _find_movement_for_event(
    event_key: str,
    *,
    ships: dict,
    cargo_total: int = 5_000_000_000,
    empire_daily_total: int = 0,
) -> int:
    for movement_id in range(1, 8000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_total,
            expedition_ship_count=1,
            flight_seconds=120,
            ships=ships,
            empire_daily_total=empire_daily_total,
        )
        if outcome["event_key"] == event_key:
            return movement_id
    raise AssertionError(f"no movement_id produced event {event_key!r}")


def test_calculate_fleet_value_uses_ship_scores():
    assert calculate_fleet_value(_ESCORT_FLEET) == 10 * 7000 + 500 * 4000 + 200 * 12000
    assert calculate_fleet_value(_SMALL_FLEET) == 7000


def test_expo_value_uses_only_expedition_hulls():
    assert calculate_expo_value(_SMALL_FLEET) == int(_ODYSSEY_EXPO_UNIT)
    assert calculate_expo_value({_ODYSSEY_KEY: 10}) == int(10 * _ODYSSEY_EXPO_UNIT)
    assert calculate_expo_value({_ODYSSEY_KEY: 100}) == int(100 * _ODYSSEY_EXPO_UNIT)
    assert calculate_expo_value(_ESCORT_FLEET) == int(10 * _ODYSSEY_EXPO_UNIT)
    assert calculate_expo_value({"falcon_interceptor": 1000, "atlas_hauler": 500}) == 0


def test_voidrunner_hybrid_counts_for_loot_and_combat():
    """GC-SHIP-1: Voidrunner (expedition+combat) contributes to both expo loot and pirate combat."""
    from game.expedition_events import _loss_role_priority

    voidrunner = {"eclipse_runner": 5}
    # Expedition role → counts toward loot and cargo cap.
    assert calculate_expo_value(voidrunner) > 0
    assert calculate_expedition_loot_cap(voidrunner) > 0
    # Combat role → counts toward pirate survival value.
    assert calculate_expedition_combat_value(voidrunner) > 0
    # Hybrid is lost like combat (index 0) — protects pure expedition hulls (Odyssey).
    assert _loss_role_priority("eclipse_runner") == _loss_role_priority("falcon_interceptor")
    assert _loss_role_priority("eclipse_runner") < _loss_role_priority("solar_skiff")


def test_voidrunner_lost_before_odyssey():
    """Hybrid escort absorbs losses before the pure expedition hull it escorts."""
    remaining, losses = apply_expedition_ship_losses(
        {"eclipse_runner": 5, "solar_skiff": 5}, 40, min_remaining=1
    )
    assert int(losses.get("eclipse_runner") or 0) > 0
    assert int(losses.get("solar_skiff") or 0) == 0
    assert remaining.get("solar_skiff") == 5


def test_canonical_base_loot_reference_values():
    """Community reference table without random/event factors (exponent per hull, linear in count)."""
    assert _ODYSSEY_FLEET_VALUE == 8750
    assert calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 1})) == pytest.approx(
        _ODYSSEY_EXPO_UNIT, rel=0.01
    )
    assert calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 10})) == pytest.approx(
        10 * _ODYSSEY_EXPO_UNIT, rel=0.01
    )
    assert calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 100})) == pytest.approx(
        100 * _ODYSSEY_EXPO_UNIT, rel=0.01
    )
    assert calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 1000})) == pytest.approx(
        1000 * _ODYSSEY_EXPO_UNIT, rel=0.01
    )
    assert calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 10000})) == pytest.approx(
        10000 * _ODYSSEY_EXPO_UNIT, rel=0.01
    )


def test_odyssey_loot_linear_in_hull_count_sublinear_per_hull():
    one = calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 1}))
    ten = calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 10}))
    hundred = calculate_base_expedition_loot(calculate_expo_value({_ODYSSEY_KEY: 100}))
    assert ten == pytest.approx(one * 10, rel=0.001)
    assert hundred == pytest.approx(one * 100, rel=0.001)
    assert one < _ODYSSEY_FLEET_VALUE


def test_combat_and_cargo_ships_do_not_increase_expo_value():
    base = calculate_expo_value({_ODYSSEY_KEY: 50})
    with_escorts = calculate_expo_value(
        {_ODYSSEY_KEY: 50, "falcon_interceptor": 200, "atlas_hauler": 100, "ironclad_frigate": 50}
    )
    assert with_escorts == base


def test_combat_value_is_escort_only_not_expo_hulls():
    solo = calculate_expedition_combat_value({_ODYSSEY_KEY: 1})
    with_escort = calculate_expedition_combat_value({_ODYSSEY_KEY: 1, "falcon_interceptor": 10})
    with_hauler = calculate_expedition_combat_value({_ODYSSEY_KEY: 1, "atlas_hauler": 5})
    assert solo == 0
    assert with_escort == 10 * 4000
    assert with_hauler == 0


def test_hull_and_escort_values_split_roles():
    fleet = {_ODYSSEY_KEY: 100, "falcon_interceptor": 1}
    assert calculate_expedition_hull_value(fleet) == 100 * 7000
    assert calculate_expedition_escort_value(fleet) == 4000
    rating = build_expedition_fleet_rating(fleet)
    assert rating["escort_ratio"] == pytest.approx(0.0057, abs=0.0001)
    assert rating["escort_effectiveness"] < 0.05


def test_one_escort_with_large_expo_fleet_has_minimal_pirate_advantage():
    import random

    small_expo = {_ODYSSEY_KEY: 1, "falcon_interceptor": 1}
    large_expo = {_ODYSSEY_KEY: 100, "falcon_interceptor": 1}
    small = resolve_pirate_encounter(random.Random(42), small_expo)
    large = resolve_pirate_encounter(random.Random(42), large_expo)
    assert small["win_chance"] > large["win_chance"]
    assert large["escort_ratio"] < 0.01
    assert small["escort_ratio"] >= 0.5


def test_scaled_escort_improves_pirate_outcome():
    import random

    weak = resolve_pirate_encounter(random.Random(7), {_ODYSSEY_KEY: 50, "falcon_interceptor": 2})
    strong = resolve_pirate_encounter(random.Random(7), {_ODYSSEY_KEY: 50, "falcon_interceptor": 80})
    assert strong["escort_ratio"] > weak["escort_ratio"]
    assert strong["win_chance"] > weak["win_chance"]


def test_pirate_rebalance_enemy_factor_and_expo_only_win_chance():
    """GC-EXPO-P1: weaker pirates + playable expo-only desperation fight."""
    import random

    ships = {_ODYSSEY_KEY: 100}
    combat = resolve_pirate_encounter(random.Random(42), ships)
    expo_risk = int(combat["expedition_hull_value"])
    pirate_points = int(combat["pirate_points"])
    assert int(expo_risk * 0.40) <= pirate_points <= int(expo_risk * 0.75)
    assert int(combat["fleet_points"]) == max(1, int(expo_risk * 0.18))
    assert float(combat["win_chance"]) >= 0.20
    assert int(combat["loss_pct"]) <= 14


def test_voidrunner_discovery_bonus_once_per_fleet():
    assert build_expedition_fleet_rating({"eclipse_runner": 1})["voidrunner_bonus_active"] is True
    assert build_expedition_fleet_rating({"eclipse_runner": 5})["voidrunner_bonus_pct"] == 25
    assert build_expedition_fleet_rating({"solar_skiff": 10})["voidrunner_bonus_active"] is False


def test_voidrunner_boosts_positive_loot_event_weight():
    import random
    from game.expedition_events import _pick_event_key

    loot_keys = {"mineral_deposit", "fuel_cache", "debris_salvage", "ancient_stash"}
    base_loot = 0
    boosted_loot = 0
    for seed in range(500):
        if _pick_event_key(random.Random(seed), 5, voidrunner_bonus=0.0) in loot_keys:
            base_loot += 1
        if _pick_event_key(random.Random(seed), 5, voidrunner_bonus=_VOIDRUNNER_DISCOVERY_BONUS) in loot_keys:
            boosted_loot += 1
    assert boosted_loot > base_loot


def test_preview_and_outcome_share_expedition_rating():
    ships = {"solar_skiff": 10, "falcon_interceptor": 5, "eclipse_runner": 2}
    rating = build_expedition_fleet_rating(ships)
    outcome = resolve_expedition_outcome(
        4242,
        cargo_total=calculate_expedition_loot_cap(ships),
        expedition_ship_count=12,
        flight_seconds=120,
        ships=ships,
    )
    assert outcome["expedition_rating"]["escort_ratio"] == rating["escort_ratio"]
    assert outcome["expedition_rating"]["voidrunner_bonus_active"] is True
    _, meta = build_expedition_report("1:2:16", ships, outcome, locale="en")
    assert meta["expedition_rating"]["escort_ratio"] == rating["escort_ratio"]
    assert meta["voidrunner_bonus_active"] is True


def test_cargo_cap_includes_haulers_not_combat_escorts():
    solo = calculate_expedition_loot_cap({_ODYSSEY_KEY: 1})
    with_escort = calculate_expedition_loot_cap({_ODYSSEY_KEY: 1, "falcon_interceptor": 10})
    with_hauler = calculate_expedition_loot_cap({_ODYSSEY_KEY: 1, "atlas_hauler": 2})
    assert solo == 2000
    assert with_escort == solo
    assert with_hauler == 2000 + 2 * 25000


def test_combat_value_includes_escorts_not_haulers():
    """Legacy alias — combat value is escort-only."""
    test_combat_value_is_escort_only_not_expo_hulls()


def test_haulers_increase_cargo_cap_not_loot():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_SMALL_FLEET, cargo_total=500_000)
    solo = resolve_expedition_outcome(
        movement_id,
        cargo_total=calculate_expedition_loot_cap(_SMALL_FLEET),
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
    )
    hauler_fleet = {_ODYSSEY_KEY: 1, "atlas_hauler": 3}
    with_haulers = resolve_expedition_outcome(
        movement_id,
        cargo_total=calculate_expedition_loot_cap(hauler_fleet),
        expedition_ship_count=1,
        flight_seconds=120,
        ships=hauler_fleet,
    )
    assert int(with_haulers["reward_total"]) == int(solo["reward_total"])
    assert calculate_expedition_loot_cap(hauler_fleet) > calculate_expedition_loot_cap(_SMALL_FLEET)


def test_large_fleet_produces_more_than_small_fleet():
    movement_id = _find_movement_for_event(
        "mineral_deposit",
        ships=_MEDIUM_FLEET,
        cargo_total=500_000,
    )
    large = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=100,
        flight_seconds=120,
        ships=_MEDIUM_FLEET,
    )
    small = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
    )
    assert int(large["reward_total"]) > int(small["reward_total"])


def test_escort_ships_do_not_increase_loot():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_SMALL_FLEET, cargo_total=500_000)
    solo = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
    )
    escorted = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships={_ODYSSEY_KEY: 1, "falcon_interceptor": 500, "atlas_hauler": 200},
    )
    assert int(escorted["reward_total"]) == int(solo["reward_total"])


def test_small_fleet_still_produces_modest_loot():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_SMALL_FLEET, cargo_total=500_000)
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
    )
    total = int(outcome["reward_total"])
    assert total > 0
    assert total <= 500_000


def test_loot_capped_by_cargo_capacity():
    movement_id = _find_movement_for_event("ancient_stash", ships=_LARGE_EXPO_FLEET)
    cargo_cap = 12_345
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=cargo_cap,
        expedition_ship_count=1000,
        flight_seconds=120,
        ships=_LARGE_EXPO_FLEET,
    )
    assert int(outcome["reward_total"]) <= cargo_cap


def test_outcome_deterministic_for_same_movement_and_fleet():
    kwargs = dict(
        cargo_total=250_000,
        expedition_ship_count=2,
        flight_seconds=90,
        ships={"solar_skiff": 2, "falcon_interceptor": 10},
        empire_daily_total=1_000_000,
    )
    first = resolve_expedition_outcome(9001, **kwargs)
    second = resolve_expedition_outcome(9001, **kwargs)
    assert first == second


def test_event_multiplier_changes_loot_magnitude():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_MEDIUM_FLEET, cargo_total=500_000)
    mineral = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=100,
        flight_seconds=120,
        ships=_MEDIUM_FLEET,
    )
    ancient_id = _find_movement_for_event("ancient_stash", ships=_MEDIUM_FLEET, cargo_total=500_000)
    ancient = resolve_expedition_outcome(
        ancient_id,
        cargo_total=500_000,
        expedition_ship_count=100,
        flight_seconds=120,
        ships=_MEDIUM_FLEET,
    )
    assert int(ancient["reward_total"]) > int(mineral["reward_total"])


def test_fleet_scaling_formula_reference():
    expo_value = calculate_expo_value({_ODYSSEY_KEY: 100})
    base_loot = calculate_base_expedition_loot(expo_value)
    assert base_loot == pytest.approx(100 * _ODYSSEY_EXPO_UNIT, rel=0.01)
    assert EXPEDITION_RANDOM_FACTOR_RANGE == (0.66, 1.5)


def test_event_boxes_never_allowed_for_expedition_drops():
    assert is_allowed_expedition_lootbox("event_container") is False
    assert is_allowed_expedition_lootbox("event_special") is False
    assert is_allowed_expedition_lootbox("generic_supply_container") is True
    assert is_allowed_expedition_lootbox("premium_cache") is True
    assert is_allowed_expedition_lootbox("void_artifact") is True
    assert is_allowed_expedition_lootbox("mythic_container") is True


def test_jackpot_lootbox_deterministic_for_movement():
    for movement_id in range(1, 50000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=1_000_000,
            expedition_ship_count=1,
            flight_seconds=120,
            ships=_MEDIUM_FLEET,
        )
        if outcome["event_key"] != "ancient_stash":
            continue
        repeat = resolve_expedition_outcome(
            movement_id,
            cargo_total=1_000_000,
            expedition_ship_count=1,
            flight_seconds=120,
            ships=_MEDIUM_FLEET,
        )
        assert outcome.get("lootboxes") == repeat.get("lootboxes")
        jackpots = [b for b in (outcome.get("lootboxes") or []) if b.get("jackpot")]
        if jackpots:
            assert jackpots[0]["key"] in {"void_artifact", "ancient_relic", "mythic_container"}
        return
    pytest.skip("no ancient_stash in search window")


def test_lootbox_drop_deterministic_for_movement():
    movement_id = _find_movement_for_event("ancient_stash", ships=_MEDIUM_FLEET)
    first = resolve_expedition_outcome(
        movement_id,
        cargo_total=1_000_000,
        expedition_ship_count=100,
        flight_seconds=120,
        ships=_MEDIUM_FLEET,
    )
    second = resolve_expedition_outcome(
        movement_id,
        cargo_total=1_000_000,
        expedition_ship_count=100,
        flight_seconds=120,
        ships=_MEDIUM_FLEET,
    )
    assert first.get("lootboxes") == second.get("lootboxes")


def test_build_expedition_report_includes_lootbox_metadata():
    outcome = {
        "event_key": "ancient_stash",
        "severity": "major",
        "rewards": {"metal": 100, "crystal": 0, "fuel_cells": 0},
        "lootboxes": [{"key": "premium_cache", "amount": 1}],
        "delay_extra": 0,
        "expedition_ship_count": 1,
        "cargo_total": 1000,
    }
    _, meta = build_expedition_report("1:2:16", {"solar_skiff": 1}, outcome, locale="en")
    assert meta.get("lootboxes")
    assert meta["lootboxes"][0]["key"] == "premium_cache"
    assert meta["lootboxes"][0].get("name")


def test_grant_expedition_lootboxes_persists_inventory(tmp_path, monkeypatch):
    import game.db as gdb
    from game.db import db
    from game.models import init_db, table_exists

    db_path = tmp_path / "expedition_lootbox.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users ORDER BY id LIMIT 1;")
        row = cur.fetchone()
        assert row
        player_id = int(row["id"])
        if not table_exists(conn, "lootbox_inventory"):
            pytest.skip("lootbox_inventory not migrated")
        grant_expedition_lootboxes(
            player_id,
            [{"key": "generic_supply_container", "amount": 1}],
            movement_id=424242,
            conn=conn,
        )
        conn.commit()
        amount_row = conn.execute(
            "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
            (player_id, "container_basic"),
        ).fetchone()
        assert amount_row and int(amount_row["amount"]) >= 1
        stored = conn.execute(
            "SELECT COUNT(*) AS c FROM lootbox_inventory WHERE player_id = ? AND source = 'expedition';",
            (player_id,),
        ).fetchone()
        assert int(stored["c"]) >= 1
    finally:
        conn.close()
        gdb._DB_PATH = None


def test_expo_only_fleet_still_takes_losses():
    remaining, losses = apply_expedition_ship_losses({"solar_skiff": 500}, 20)
    assert int(losses.get("solar_skiff") or 0) == 100
    assert remaining.get("solar_skiff") == 400


def test_pirate_debris_created_from_ship_losses():
    import random

    ships = {"solar_skiff": 100, "falcon_interceptor": 80}
    combat = resolve_pirate_encounter(
        random.Random(101),
        ships,
    )
    assert int(combat.get("losses_total") or 0) > 0
    debris = resolve_expedition_pirate_debris(
        remaining_ships=dict(combat["remaining_ships"]),
        ship_losses=dict(combat["losses"]),
        pirate_combat=combat,
    )
    assert debris is not None
    field = debris["debris"]
    assert int(field.get("metal") or 0) + int(field.get("crystal") or 0) > 0
    assert field.get("expedition_field") is True


def test_pirate_debris_collected_when_recycler_aboard():
    fleet = {"solar_skiff": 50, "falcon_interceptor": 200, "harvest_reclaimer": 2}
    remaining, losses = apply_expedition_ship_losses(fleet, 30)
    assert sum(losses.values()) > 0
    assert calculate_expedition_recycler_cargo(remaining) == 40_000
    debris = resolve_expedition_pirate_debris(
        remaining_ships=remaining,
        ship_losses=losses,
        pirate_combat={"won": True, "pirate_points": 80_000, "recycler_protected": True},
    )
    assert debris is not None
    collected = debris["collected"]
    assert int(collected.get("metal") or 0) + int(collected.get("crystal") or 0) > 0
    assert int(debris["debris"].get("harvested_metal") or 0) == int(collected.get("metal") or 0)
    assert debris["debris"].get("recycler_protected") is True


def test_pirate_debris_without_recycler_not_collected():
    fleet = {"solar_skiff": 80, "falcon_interceptor": 120}
    remaining, losses = apply_expedition_ship_losses(fleet, 25)
    debris = resolve_expedition_pirate_debris(
        remaining_ships=remaining,
        ship_losses=losses,
        pirate_combat={"won": False, "pirate_points": 60_000},
    )
    assert debris is not None
    assert int(debris["collected"].get("metal") or 0) == 0
    assert int(debris["collected"].get("crystal") or 0) == 0
    assert int(debris["debris"].get("metal") or 0) > 0


def test_pirate_protects_recyclers_from_combat_losses():
    """GC-EXPO-P2: recyclers never die in pirate skirmish — TF always harvestable."""
    import random

    ships = {"solar_skiff": 100, "harvest_reclaimer": 2}
    for seed in range(80):
        combat = resolve_pirate_encounter(random.Random(seed), ships)
        assert combat.get("recycler_protected") is True
        assert int(combat["remaining_ships"].get("harvest_reclaimer") or 0) == 2
        assert "harvest_reclaimer" not in (combat.get("losses") or {})
    remaining, losses = apply_expedition_ship_losses(
        ships,
        40,
        protect_roles=("recycle",),
    )
    assert remaining.get("harvest_reclaimer") == 2
    assert "harvest_reclaimer" not in losses
    assert int(losses.get("solar_skiff") or 0) > 0


def test_pirate_encounter_with_recycler_always_harvests_when_debris_exists():
    """GC-EXPO-P2: if recyclers were sent, surviving cargo salvages ephemeral TF."""
    import random

    ships = {"solar_skiff": 80, "harvest_reclaimer": 1}
    harvested_any = False
    for seed in range(120):
        combat = resolve_pirate_encounter(random.Random(seed), ships)
        debris = resolve_expedition_pirate_debris(
            remaining_ships=dict(combat["remaining_ships"]),
            ship_losses=dict(combat["losses"]),
            pirate_combat=combat,
        )
        if debris is None:
            continue
        assert int(debris["recycler_cap"]) == 20_000
        field_total = int(debris["debris"].get("metal") or 0) + int(debris["debris"].get("crystal") or 0)
        collected_total = int(debris["collected"].get("metal") or 0) + int(
            debris["collected"].get("crystal") or 0
        )
        if field_total > 0:
            assert collected_total > 0
            harvested_any = True
    assert harvested_any


def test_minefield_still_can_lose_recyclers():
    """Minefield keeps default loss priority — recyclers not pirate-protected."""
    import random
    from game.expedition_events import resolve_minefield_hazard

    ships = {"solar_skiff": 100, "harvest_reclaimer": 2}
    lost_recycler = False
    for seed in range(200):
        hazard = resolve_minefield_hazard(random.Random(seed), ships)
        if int(hazard["losses"].get("harvest_reclaimer") or 0) > 0:
            lost_recycler = True
            break
    assert lost_recycler


def test_pirate_outcome_credits_debris_to_rewards_with_recycler():
    ships = {"solar_skiff": 30, "falcon_interceptor": 150, "harvest_reclaimer": 1}
    for movement_id in range(1, 6000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=30,
            flight_seconds=120,
            ships=ships,
        )
        if outcome.get("event_key") != "pirate_encounter":
            continue
        if int(outcome.get("losses_total") or 0) <= 0:
            continue
        debris = outcome.get("debris") or {}
        harvested = int(debris.get("harvested_metal") or 0) + int(debris.get("harvested_crystal") or 0)
        if harvested <= 0:
            continue
        rewards = outcome.get("rewards") or {}
        assert int(rewards.get("metal") or 0) + int(rewards.get("crystal") or 0) >= harvested
        _, meta = build_expedition_report("1:2:16", ships, outcome, locale="en")
        assert meta.get("debris")
        return
    pytest.skip("no pirate encounter with losses and recycler salvage in search window")


def test_pirate_encounter_event_weight_is_rare():
    hits = 0
    for movement_id in range(1, 5000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 2, "falcon_interceptor": 20},
        )
        if outcome["event_key"] == "pirate_encounter":
            hits += 1
    rate = hits / 4999
    assert 0.02 <= rate <= 0.08


def test_pirate_encounter_never_wipes_fleet():
    import random

    ships = {"solar_skiff": 5, "falcon_interceptor": 50}
    for seed in range(200):
        rng = random.Random(seed)
        combat = resolve_pirate_encounter(rng, ships)
        remaining = combat["remaining_ships"]
        assert sum(remaining.values()) >= 1


def test_apply_expedition_ship_losses_keeps_minimum_hull():
    remaining, losses = apply_expedition_ship_losses({"solar_skiff": 1}, 45)
    assert remaining == {"solar_skiff": 1}
    assert losses == {}

    remaining, losses = apply_expedition_ship_losses({"solar_skiff": 10, "falcon_interceptor": 100}, 40)
    assert sum(remaining.values()) >= 1
    assert sum(losses.values()) > 0
    assert sum(remaining.values()) + sum(losses.values()) == 110
    assert remaining.get("solar_skiff") == 10
    assert int(losses.get("falcon_interceptor") or 0) == 44


def test_combat_escorts_absorb_losses_before_expo_hulls():
    ships = {"solar_skiff": 500, "falcon_interceptor": 500}
    remaining, losses = apply_expedition_ship_losses(ships, 30)
    assert remaining.get("solar_skiff") == 500
    assert int(losses.get("falcon_interceptor") or 0) == 300
    assert "solar_skiff" not in losses


def test_expo_only_fleet_still_takes_losses():
    remaining, losses = apply_expedition_ship_losses({"solar_skiff": 500}, 20)
    assert int(losses.get("solar_skiff") or 0) == 100
    assert remaining.get("solar_skiff") == 400


def test_pirate_outcome_deterministic_for_movement():
    kwargs = dict(
        cargo_total=250_000,
        expedition_ship_count=2,
        flight_seconds=90,
        ships={"solar_skiff": 3, "falcon_interceptor": 30},
        empire_daily_total=1_000_000,
    )
    movement_id = _find_movement_for_event("pirate_encounter", ships=kwargs["ships"])
    first = resolve_expedition_outcome(movement_id, **kwargs)
    second = resolve_expedition_outcome(movement_id, **kwargs)
    assert first == second
    assert first["event_key"] == "pirate_encounter"
    assert first.get("pirate_combat")
    assert sum(first["remaining_ships"].values()) >= 1


def test_pirate_defeat_grants_no_loot():
    movement_id = _find_movement_for_event(
        "pirate_encounter",
        ships={"solar_skiff": 1},
        cargo_total=50_000,
    )
    for _ in range(20):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=50_000,
            expedition_ship_count=1,
            flight_seconds=120,
            ships={"solar_skiff": 1},
        )
        if not outcome.get("pirate_won"):
            assert int(outcome["reward_total"]) == 0
            assert not outcome.get("lootboxes")
            return
    pytest.skip("only pirate wins in retry window")


def test_build_expedition_report_includes_pirate_metadata():
    outcome = resolve_expedition_outcome(
        _find_movement_for_event("pirate_encounter", ships={"solar_skiff": 5, "falcon_interceptor": 40}),
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships={"solar_skiff": 5, "falcon_interceptor": 40},
    )
    _, meta = build_expedition_report("1:2:16", {"solar_skiff": 5, "falcon_interceptor": 40}, outcome, locale="en")
    assert meta.get("pirate_combat")
    assert meta.get("losses_total", 0) >= 0
    if meta.get("losses_total"):
        assert meta.get("remaining_ships")


def test_pirate_salvage_only_on_win():
    import random

    for seed in range(300):
        rng = random.Random(seed)
        combat = resolve_pirate_encounter(rng, {"solar_skiff": 10})
        if not combat.get("won"):
            continue
        salvage_rng = random.Random(seed + 999)
        salvaged, tier = roll_pirate_salvage_rewards(
            salvage_rng,
            pirate_points=int(combat["pirate_points"]),
            fleet_points=int(combat["fleet_points"]),
        )
        for key in salvaged:
            assert key in {"spark_drone", "mule_courier", "veil_probe", "solar_skiff", "falcon_interceptor"}
        return
    pytest.skip("no pirate wins in window")


def test_pirate_defeat_never_grants_salvage():
    movement_id = _find_movement_for_event(
        "pirate_encounter",
        ships={"solar_skiff": 1},
        cargo_total=50_000,
    )
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=50_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships={"solar_skiff": 1},
    )
    if outcome.get("pirate_won"):
        pytest.skip("movement rolled pirate win")
    assert not outcome.get("salvaged_ships")
    assert int(outcome.get("salvaged_total") or 0) == 0


def test_pirate_salvage_merged_into_return_fleet():
    import random

    ships = {"solar_skiff": 20, "falcon_interceptor": 40}
    fleet_value = calculate_fleet_value(ships)
    for movement_id in range(1, 12000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships=ships,
        )
        if outcome.get("event_key") != "pirate_encounter" or not outcome.get("pirate_won"):
            continue
        salvaged = dict(outcome.get("salvaged_ships") or {})
        if not salvaged:
            continue
        remaining = dict(outcome["remaining_ships"])
        for key, qty in salvaged.items():
            assert int(remaining.get(key) or 0) >= int(qty)
        repeat = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships=ships,
        )
        assert repeat == outcome
        return
    pytest.skip("no pirate win with salvage in search window")


def test_salvage_tier_distribution_approximate():
    """GC-EXPO-P3: 55% none / 35% small / 10% rare."""
    import random

    tiers: dict[str, int] = {"none": 0, "small": 0, "rare": 0}
    for seed in range(5000):
        _, tier = roll_pirate_salvage_rewards(
            random.Random(seed),
            pirate_points=50_000,
            fleet_points=60_000,
        )
        tiers[tier] = tiers.get(tier, 0) + 1
    total = sum(tiers.values())
    assert tiers["none"] / total == pytest.approx(0.55, abs=0.05)
    assert tiers["small"] / total == pytest.approx(0.35, abs=0.05)
    assert tiers["rare"] / total == pytest.approx(0.10, abs=0.04)


def test_pirate_win_wreck_debris_uses_eighty_percent_points():
    """GC-EXPO-P3: virtual pirate wrecks use 80% of pirate_points."""
    from game.expedition_events import _virtual_pirate_losses
    from game.fleet_defs import ship_score_value

    pirate_points = 100_000
    wrecks = _virtual_pirate_losses(pirate_points, won=True)
    per_hull = max(1, ship_score_value("falcon_interceptor"))
    expected = min(max(1, int(pirate_points * 0.80) // per_hull), 500)
    assert wrecks.get("falcon_interceptor") == expected
    weak = _virtual_pirate_losses(pirate_points, won=True)
    # Sanity: 80% wrecks >= old 60% curve for same points.
    old_count = min(max(1, int(pirate_points * 0.60) // per_hull), 500)
    assert int(weak.get("falcon_interceptor") or 0) >= old_count


def test_ion_storm_delay_within_flight_fraction():
    movement_id = _find_movement_for_event("ion_storm", ships={"solar_skiff": 2})
    flight_seconds = 200
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=250_000,
        expedition_ship_count=2,
        flight_seconds=flight_seconds,
        ships={"solar_skiff": 2},
    )
    assert outcome["event_key"] == "ion_storm"
    delay = int(outcome["delay_extra"])
    assert delay >= int(flight_seconds * 0.20)
    assert delay <= int(flight_seconds * 0.60) + 1
    assert int(outcome["reward_total"]) == 0
    assert not outcome.get("remaining_ships")


def test_ion_storm_deterministic():
    kwargs = dict(
        cargo_total=250_000,
        expedition_ship_count=2,
        flight_seconds=180,
        ships={"solar_skiff": 2},
    )
    movement_id = _find_movement_for_event("ion_storm", ships=kwargs["ships"])
    assert resolve_expedition_outcome(movement_id, **kwargs) == resolve_expedition_outcome(
        movement_id, **kwargs
    )


def test_ancient_minefield_never_wipes_fleet():
    import random

    ships = {"solar_skiff": 8, "falcon_interceptor": 60}
    for seed in range(200):
        hazard = resolve_minefield_hazard(random.Random(seed), ships)
        assert sum(hazard["remaining_ships"].values()) >= 1
        assert int(hazard["loss_pct"]) >= 2
        assert int(hazard["loss_pct"]) <= 8


def test_ancient_minefield_outcome_no_loot_and_updates_fleet():
    movement_id = _find_movement_for_event(
        "ancient_minefield",
        ships={"solar_skiff": 15, "falcon_interceptor": 80},
    )
    ships = {"solar_skiff": 15, "falcon_interceptor": 80}
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=2,
        flight_seconds=120,
        ships=ships,
    )
    assert outcome["event_key"] == "ancient_minefield"
    assert int(outcome["reward_total"]) == 0
    assert outcome.get("hazard")
    assert outcome.get("remaining_ships") is not None
    assert sum(outcome["remaining_ships"].values()) >= 1
    sent = sum(ships.values())
    remaining = sum(outcome["remaining_ships"].values())
    assert remaining <= sent
    if int(outcome.get("losses_total") or 0) > 0:
        assert remaining < sent


def test_expedition_weight_audit_gc620j0():
    audit = expedition_event_weight_audit()
    shares = audit["share_by_category"]

    assert audit["total_weight"] == 119
    assert audit["weights_by_key"]["mineral_deposit"] == 33
    assert audit["weights_by_key"]["pirate_encounter"] == 4
    assert audit["weights_by_key"]["ancient_minefield"] == 2
    assert audit["weights_by_key"]["lost_container"] == 3
    assert audit["weight_by_category"]["loot"] == 86
    assert audit["weight_by_category"]["legendary"] == 3
    assert audit["weight_by_category"]["treasure"] == 6
    assert shares["legendary"] == pytest.approx(3 / 119, abs=0.001)
    assert 0.023 <= shares["legendary"] <= 0.026
    assert shares["loot"] == pytest.approx(86 / 119, abs=0.001)
    assert 0.68 <= shares["loot"] <= 0.75
    assert 0.05 <= shares["neutral"] <= 0.10
    assert 0.06 <= shares["delay"] <= 0.10
    assert 0.02 <= shares["combat"] <= 0.05
    assert 0.01 <= shares["hazard"] <= 0.04
    assert 0.03 <= shares["treasure"] <= 0.07


def test_expedition_empirical_category_distribution_gc620j0():
    category_hits: dict[str, int] = {}
    key_to_category = {
        "void_scan": "neutral",
        "sensor_glitch": "neutral",
        "mineral_deposit": "loot",
        "fuel_cache": "loot",
        "debris_salvage": "loot",
        "distress_beacon": "loot",
        "ancient_stash": "loot",
        "nav_interference": "delay",
        "ion_storm": "delay",
        "pirate_encounter": "combat",
        "ancient_minefield": "hazard",
        "lost_container": "treasure",
        "abandoned_convoy": "treasure",
        "ancient_derelict": "treasure",
        "spatial_rift": "legendary",
        "time_anomaly": "legendary",
        "ancient_beacon": "legendary",
    }
    rolls = 14999
    for movement_id in range(1, rolls + 1):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 2, "falcon_interceptor": 20},
        )
        category = key_to_category[str(outcome["event_key"])]
        category_hits[category] = category_hits.get(category, 0) + 1

    empirical = {cat: hits / rolls for cat, hits in category_hits.items()}
    assert 0.58 <= empirical.get("loot", 0) <= 0.75
    assert 0.03 <= empirical.get("neutral", 0) <= 0.10
    assert 0.05 <= empirical.get("delay", 0) <= 0.12
    assert 0.02 <= empirical.get("combat", 0) <= 0.08
    assert 0.01 <= empirical.get("hazard", 0) <= 0.06
    assert 0.03 <= empirical.get("treasure", 0) <= 0.08
    assert 0.015 <= empirical.get("legendary", 0) <= 0.045


def test_expedition_lootbox_rate_stays_rare():
    """Any-lootbox rate should stay well below ~10% per expedition (GC expo balance)."""
    rolls = 10_000
    with_box = 0
    for movement_id in range(1, rolls + 1):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=5,
            flight_seconds=120,
            ships={"solar_skiff": 5},
        )
        if outcome.get("lootboxes"):
            with_box += 1
    rate = with_box / rolls
    assert 0.03 <= rate <= 0.08, f"lootbox rate {rate:.1%} outside 3–8% band"



def test_expedition_event_bonus_improves_loot_event_rate():
    from game.expedition_events import resolve_expedition_outcome

    empty_hits = 0
    loot_hits = 0
    rolls = 4000
    for movement_id in range(1, rolls + 1):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 2},
            directive_flags={"expedition_event_bonus": 0.05},
        )
        if int(outcome.get("reward_total") or 0) > 0:
            loot_hits += 1
        elif outcome["event_key"] in {"void_scan", "sensor_glitch", "nav_interference", "ion_storm"}:
            empty_hits += 1
    base_empty = 0
    base_loot = 0
    for movement_id in range(1, rolls + 1):
        outcome = resolve_expedition_outcome(
            movement_id + 900_000,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 2},
        )
        if int(outcome.get("reward_total") or 0) > 0:
            base_loot += 1
        elif outcome["event_key"] in {"void_scan", "sensor_glitch", "nav_interference", "ion_storm"}:
            base_empty += 1
    assert loot_hits > base_loot
    assert empty_hits < base_empty


def test_hazard_events_are_rare_in_weight_table():
    hits = {"ion_storm": 0, "ancient_minefield": 0}
    for movement_id in range(1, 8000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 2, "falcon_interceptor": 20},
        )
        key = outcome["event_key"]
        if key in hits:
            hits[key] += 1
    total = 7999
    for key, count in hits.items():
        rate = count / total
        assert 0.01 <= rate <= 0.08, f"{key} rate {rate:.3f} out of band"


def test_lost_container_grants_lootbox_and_resources():
    movement_id = _find_movement_for_event("lost_container", ships={"solar_skiff": 2})
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=250_000,
        expedition_ship_count=2,
        flight_seconds=120,
        ships={"solar_skiff": 2},
        empire_daily_total=500_000,
    )
    assert outcome["event_key"] == "lost_container"
    assert outcome.get("lootboxes")
    repeat = resolve_expedition_outcome(
        movement_id,
        cargo_total=250_000,
        expedition_ship_count=2,
        flight_seconds=120,
        ships={"solar_skiff": 2},
        empire_daily_total=500_000,
    )
    assert outcome == repeat


def test_lost_container_lootbox_from_allowed_pool():
    import random

    for seed in range(100):
        boxes = roll_lost_container_lootboxes(random.Random(seed))
        if not boxes:
            continue
        assert boxes[0]["key"] in {
            "generic_supply_container",
            "resource_cache",
            "research_capsule",
            "military_cache",
            "alien_cache",
        }
        return
    pytest.skip("no lootbox rolled")


def test_abandoned_convoy_can_grant_salvage_ships():
    for movement_id in range(1, 15000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 10, "falcon_interceptor": 40},
            empire_daily_total=1_000_000,
        )
        if outcome["event_key"] != "abandoned_convoy":
            continue
        if outcome.get("salvaged_ships"):
            assert outcome.get("remaining_ships")
            sent = 50
            assert sum(outcome["remaining_ships"].values()) > sent
            for key in outcome["salvaged_ships"]:
                assert key in {
                    "spark_drone",
                    "mule_courier",
                    "veil_probe",
                    "solar_skiff",
                    "falcon_interceptor",
                }
            return
    pytest.skip("no convoy with ship salvage in search window")


def test_ancient_derelict_always_falcon_and_lootbox():
    movement_id = _find_movement_for_event(
        "ancient_derelict",
        ships={"solar_skiff": 5},
        cargo_total=500_000,
    )
    ships = {"solar_skiff": 5}
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=ships,
        empire_daily_total=1_000_000,
    )
    assert outcome["event_key"] == "ancient_derelict"
    assert outcome.get("story_tier") == "legendary"
    assert outcome["salvaged_ships"].get("falcon_interceptor") == 1
    assert outcome.get("lootboxes")
    assert int(outcome["remaining_ships"].get("falcon_interceptor") or 0) >= 1
    assert sum(outcome["remaining_ships"].values()) == 6


def test_ancient_derelict_is_very_rare():
    hits = 0
    for movement_id in range(1, 12000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 2},
        )
        if outcome["event_key"] == "ancient_derelict":
            hits += 1
    rate = hits / 11999
    assert 0.001 <= rate <= 0.02


def test_story_treasure_events_deterministic():
    for event_key in ("lost_container", "abandoned_convoy", "ancient_derelict"):
        movement_id = _find_movement_for_event(event_key, ships={"solar_skiff": 5, "falcon_interceptor": 20})
        kwargs = dict(
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 5, "falcon_interceptor": 20},
            empire_daily_total=2_000_000,
        )
        assert resolve_expedition_outcome(movement_id, **kwargs) == resolve_expedition_outcome(
            movement_id, **kwargs
        )


def test_legendary_events_deterministic():
    for event_key in ("spatial_rift", "time_anomaly", "ancient_beacon"):
        movement_id = _find_movement_for_event(
            event_key,
            ships={"solar_skiff": 5},
            cargo_total=500_000,
            empire_daily_total=2_000_000,
        )
        kwargs = dict(
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 5},
            empire_daily_total=2_000_000,
        )
        assert resolve_expedition_outcome(movement_id, **kwargs) == resolve_expedition_outcome(
            movement_id, **kwargs
        )


def test_spatial_rift_variants():
    amplified = delayed = 0
    for movement_id in range(1, 12000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 5},
            empire_daily_total=2_000_000,
        )
        if outcome["event_key"] != "spatial_rift":
            continue
        assert outcome.get("story_tier") == "legendary"
        variant = outcome.get("legendary_variant")
        assert variant in ("amplified", "delayed")
        if variant == "amplified":
            amplified += 1
            assert int(outcome.get("reward_total") or 0) > 0
            assert int(outcome.get("delay_extra") or 0) == 0
        else:
            delayed += 1
            assert int(outcome.get("reward_total") or 0) == 0
            assert int(outcome.get("delay_extra") or 0) >= 30
    assert amplified >= 1
    assert delayed >= 1


def test_time_anomaly_no_return_shortening():
    for movement_id in range(1, 15000):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 5},
            empire_daily_total=2_000_000,
        )
        if outcome["event_key"] != "time_anomaly":
            continue
        assert outcome.get("legendary_variant") in ("dilated", "compressed")
        assert int(outcome.get("delay_extra") or 0) >= 0
        if outcome.get("legendary_variant") == "compressed":
            assert int(outcome.get("delay_extra") or 0) == 0
            return
    pytest.skip("no compressed time anomaly in search window")


def test_ancient_beacon_grants_lootbox_and_resources():
    movement_id = _find_movement_for_event(
        "ancient_beacon",
        ships={"solar_skiff": 5},
        cargo_total=500_000,
        empire_daily_total=2_000_000,
    )
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=2,
        flight_seconds=120,
        ships={"solar_skiff": 5},
        empire_daily_total=2_000_000,
    )
    assert outcome["event_key"] == "ancient_beacon"
    assert outcome.get("story_tier") == "legendary"
    assert outcome.get("legendary_variant") == "beacon"
    assert outcome.get("lootboxes")
    box_key = outcome["lootboxes"][0]["key"]
    assert box_key in {"alien_cache", "premium_cache", "research_capsule"}


def test_legendary_events_are_very_rare():
    hits = {"spatial_rift": 0, "time_anomaly": 0, "ancient_beacon": 0}
    rolls = 24999
    for movement_id in range(1, rolls + 1):
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=500_000,
            expedition_ship_count=2,
            flight_seconds=120,
            ships={"solar_skiff": 2},
        )
        key = outcome["event_key"]
        if key in hits:
            hits[key] += 1
    total_legendary = sum(hits.values())
    rate = total_legendary / rolls
    assert 0.015 <= rate <= 0.045, f"legendary rate {rate:.3f} out of band"
    for key, count in hits.items():
        assert count >= 1, f"never rolled {key}"


def test_expedition_daily_efficiency_steps():
    from game.expedition_events import expedition_daily_efficiency_multiplier

    assert expedition_daily_efficiency_multiplier(0) == 1.0
    assert expedition_daily_efficiency_multiplier(4) == 1.0
    assert expedition_daily_efficiency_multiplier(29) == 1.0
    assert expedition_daily_efficiency_multiplier(30) == pytest.approx(0.95, abs=0.001)
    assert expedition_daily_efficiency_multiplier(59) == pytest.approx(0.95, abs=0.001)
    assert expedition_daily_efficiency_multiplier(60) == pytest.approx(0.90, abs=0.001)
    assert expedition_daily_efficiency_multiplier(330) == pytest.approx(0.45, abs=0.001)
    assert expedition_daily_efficiency_multiplier(400) == pytest.approx(0.45, abs=0.001)


def test_expedition_daily_efficiency_ignores_expo_value(fleet_db):
    from game.db import db
    from game.expedition_events import (
        expedition_daily_status,
        get_expedition_daily_count,
        record_expedition_daily_value,
    )

    conn = db()
    uid = 42
    ts = 1_700_000_000.0
    for mid in range(6001, 6005):
        record_expedition_daily_value(uid, mid, 50_000, conn=conn, ts=ts)
    conn.commit()
    assert get_expedition_daily_count(uid, conn=conn, ts=ts) == 4
    status = expedition_daily_status(uid, conn=conn, ts=ts)
    assert status["daily_efficiency_pct"] == 100
    conn.close()


def test_expedition_daily_efficiency_reduces_loot(fleet_db):
    from game.db import db
    from game.expedition_events import (
        get_expedition_daily_count,
        record_expedition_daily_value,
        resolve_expedition_outcome,
    )

    conn = db()
    uid = 42
    ts = 1_700_000_000.0
    for mid in range(9001, 9031):
        record_expedition_daily_value(uid, mid, 1200, conn=conn, ts=ts)
    conn.commit()
    assert get_expedition_daily_count(uid, conn=conn, ts=ts) == 30

    high = resolve_expedition_outcome(
        1001,
        cargo_total=5_000_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
        daily_efficiency_mult=1.0,
    )
    low = resolve_expedition_outcome(
        1001,
        cargo_total=5_000_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
        daily_efficiency_mult=0.95,
    )
    if int(high.get("reward_total") or 0) > 0:
        assert int(low.get("reward_total") or 0) < int(high.get("reward_total") or 0)
    conn.close()


def test_expedition_daily_efficiency_per_player(fleet_db):
    from game.db import db
    from game.expedition_events import expedition_daily_status, record_expedition_daily_value

    conn = db()
    ts = 1_700_000_000.0
    for mid in range(7001, 7031):
        record_expedition_daily_value(1, mid, 500, conn=conn, ts=ts)
    conn.commit()
    assert expedition_daily_status(1, conn=conn, ts=ts)["daily_efficiency_pct"] == 95
    assert expedition_daily_status(2, conn=conn, ts=ts)["daily_efficiency_pct"] == 100
    conn.close()


def test_record_expedition_daily_value_idempotent(fleet_db):
    from game.db import db
    from game.expedition_events import get_expedition_daily_expo_value, record_expedition_daily_value

    conn = db()
    uid = 99
    ts = 1_700_000_000.0
    assert record_expedition_daily_value(uid, 5001, 1200, conn=conn, ts=ts)
    assert not record_expedition_daily_value(uid, 5001, 1200, conn=conn, ts=ts)
    assert get_expedition_daily_expo_value(uid, conn=conn, ts=ts) == 1200
    conn.commit()
    conn.close()


def test_expedition_daily_status_includes_reset_at(fleet_db):
    from game.db import db
    from game.expedition_events import expedition_daily_status

    conn = db()
    ts = 1_700_000_000.0
    status = expedition_daily_status(42, conn=conn, ts=ts)
    assert status["daily_efficiency_pct"] == 100
    assert status["reset_at"] == int((int(ts // 86400) + 1) * 86400)
    conn.close()
