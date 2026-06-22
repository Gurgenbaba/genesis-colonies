"""Expedition loot scaling — fleet value, economy floor, cargo cap, lootboxes."""

from __future__ import annotations

import math

import pytest

from game.expedition_events import (
    EXPEDITION_LOOT_FACTOR,
    FLEET_LOOT_EXPONENT,
    apply_expedition_ship_losses,
    build_expedition_report,
    calculate_fleet_value,
    grant_expedition_lootboxes,
    is_allowed_expedition_lootbox,
    resolve_expedition_outcome,
    resolve_pirate_encounter,
)

_LARGE_FLEET = {"seed_ark": 163}
_LARGE_FLEET_VALUE = calculate_fleet_value(_LARGE_FLEET)
_SMALL_FLEET = {"solar_skiff": 1}
_ENDGAME_DAILY = 750_000_000_000


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
    assert _LARGE_FLEET_VALUE == pytest.approx(13_040_000, rel=0.01)
    assert calculate_fleet_value(_SMALL_FLEET) == 7000


def test_large_cargo_floor_when_empire_aggregate_is_low():
    """10B cargo must not return ~5M when empire aggregate under-reports production."""
    movement_id = _find_movement_for_event(
        "mineral_deposit",
        ships=_LARGE_FLEET,
        cargo_total=10_000_000_000,
        empire_daily_total=750_000_000,
    )
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=10_000_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
        empire_daily_total=750_000_000,
    )
    total = int(outcome["reward_total"])
    assert total > 5_224_703
    assert total >= 500_000_000
    assert int(outcome.get("economy_base") or 0) >= 10_000_000_000


def test_endgame_economy_floor_beats_flat_early_game_loot():
    movement_id = _find_movement_for_event(
        "mineral_deposit",
        ships=_LARGE_FLEET,
        empire_daily_total=_ENDGAME_DAILY,
    )
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=2_000_000_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
        empire_daily_total=_ENDGAME_DAILY,
    )
    total = int(outcome["reward_total"])
    assert total > 200_000
    assert total >= 5_000_000_000


def test_ancient_stash_endgame_can_fill_large_cargo():
    movement_id = _find_movement_for_event(
        "ancient_stash",
        ships=_LARGE_FLEET,
        empire_daily_total=_ENDGAME_DAILY,
    )
    cargo_cap = 1_763_200_000
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=cargo_cap,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
        empire_daily_total=_ENDGAME_DAILY,
    )
    assert int(outcome["reward_total"]) <= cargo_cap * max(1, int(outcome.get("cargo_jackpot_mult") or 1))
    assert int(outcome["reward_total"]) >= int(cargo_cap * 0.999) or bool(outcome.get("cargo_jackpot"))


def test_large_fleet_produces_much_more_than_small_fleet():
    movement_id = _find_movement_for_event(
        "mineral_deposit",
        ships=_LARGE_FLEET,
        cargo_total=500_000,
        empire_daily_total=0,
    )
    large = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
        empire_daily_total=0,
    )
    small = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
        empire_daily_total=0,
    )
    assert int(large["reward_total"]) > int(small["reward_total"]) * 5


def test_small_fleet_still_produces_modest_loot():
    movement_id = _find_movement_for_event("mineral_deposit", ships=_SMALL_FLEET)
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=500_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_SMALL_FLEET,
    )
    total = int(outcome["reward_total"])
    assert 1_000 <= total <= 2_000_000


def test_loot_capped_by_cargo_capacity():
    movement_id = _find_movement_for_event("ancient_stash", ships=_LARGE_FLEET, empire_daily_total=_ENDGAME_DAILY)
    cargo_cap = 12_345
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=cargo_cap,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
        empire_daily_total=_ENDGAME_DAILY,
    )
    mult = int(outcome.get("cargo_jackpot_mult") or 1)
    assert int(outcome["reward_total"]) <= cargo_cap * mult


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
    movement_id = _find_movement_for_event("mineral_deposit", ships=_LARGE_FLEET, empire_daily_total=_ENDGAME_DAILY)
    mineral = resolve_expedition_outcome(
        movement_id,
        cargo_total=5_000_000_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
        empire_daily_total=_ENDGAME_DAILY,
    )
    ancient_id = _find_movement_for_event("ancient_stash", ships=_LARGE_FLEET, empire_daily_total=_ENDGAME_DAILY)
    ancient = resolve_expedition_outcome(
        ancient_id,
        cargo_total=5_000_000_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
        empire_daily_total=_ENDGAME_DAILY,
    )
    assert int(ancient["reward_total"]) > int(mineral["reward_total"])


def test_fleet_scaling_formula_reference():
    fleet_score = math.pow(_LARGE_FLEET_VALUE, FLEET_LOOT_EXPONENT)
    base_loot = fleet_score * EXPEDITION_LOOT_FACTOR
    assert base_loot == pytest.approx(1_577_496, rel=0.01)


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
            ships=_LARGE_FLEET,
        )
        if outcome["event_key"] != "ancient_stash":
            continue
        repeat = resolve_expedition_outcome(
            movement_id,
            cargo_total=1_000_000,
            expedition_ship_count=1,
            flight_seconds=120,
            ships=_LARGE_FLEET,
        )
        assert outcome.get("lootboxes") == repeat.get("lootboxes")
        jackpots = [b for b in (outcome.get("lootboxes") or []) if b.get("jackpot")]
        if jackpots:
            assert jackpots[0]["key"] in {"void_artifact", "ancient_relic", "mythic_container"}
        return
    pytest.skip("no ancient_stash in search window")


def test_lootbox_drop_deterministic_for_movement():
    movement_id = _find_movement_for_event("ancient_stash", ships=_LARGE_FLEET)
    first = resolve_expedition_outcome(
        movement_id,
        cargo_total=1_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
    )
    second = resolve_expedition_outcome(
        movement_id,
        cargo_total=1_000_000,
        expedition_ship_count=1,
        flight_seconds=120,
        ships=_LARGE_FLEET,
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
    assert 0.03 <= rate <= 0.10


def test_pirate_encounter_never_wipes_fleet():
    import random

    ships = {"solar_skiff": 5, "falcon_interceptor": 50}
    for seed in range(200):
        rng = random.Random(seed)
        combat = resolve_pirate_encounter(rng, ships, calculate_fleet_value(ships))
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
