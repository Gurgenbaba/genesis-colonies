"""GC-860 / GC-860B — static high-tier fuel_cells; Odyssey + early hulls frozen."""

from __future__ import annotations

import pytest

from game.defense import max_build_amount_for_planet
from game.defense_defs import ACTIVE_DEFENSE_KEYS, DEFENSES, unit_build_cost
from game.expedition_events import calculate_base_expedition_loot, expedition_ship_fleet_value
from game.fleet_defs import ACTIVE_SHIP_KEYS, SHIPS, get_ship
from game.queue_refund import refund_from_stored_costs
from game.ship_detail import build_ship_detail_card
from game.shipyard import _unit_build_cost, max_build_amount_for_planet as ship_max_build

ODYSSEY_BUILD_COST = {"metal": 5000, "crystal": 3750, "fuel_cells": 0}
ODYSSEY_EXPO_VALUE = 8750

UNCHANGED_EARLY_SHIP_COSTS = {
    "spark_drone": {"metal": 625, "crystal": 250, "fuel_cells": 0},
    "mule_courier": {"metal": 2500, "crystal": 2500, "fuel_cells": 0},
    "veil_probe": {"metal": 1250, "crystal": 625, "fuel_cells": 0},
    "falcon_interceptor": {"metal": 3750, "crystal": 1250, "fuel_cells": 0},
    "solar_skiff": {"metal": 5000, "crystal": 3750, "fuel_cells": 0},
}

ODYSSEY_EXPO_BASE_LOOT = {
    100: 18_978,
    1_000: 99_597,
    10_000: 522_692,
}

HIGH_TIER_SHIP_FUEL = {
    "atlas_hauler": 750,
    "harvest_reclaimer": 7500,
    "ironclad_frigate": 12500,
    "seed_ark": 60000,
}

HIGH_TIER_DEFENSE_FUEL = {
    "plasma_arc": 750,
    "ion_bastion": 1500,
    "flak_array": 2500,
    "pulse_barrier": 8500,
    "orbital_shield": 25000,
}


def test_no_ship_unit_build_cost_in_economy_balance():
    import game.economy_balance as eb

    assert not hasattr(eb, "ship_unit_build_cost")
    assert not hasattr(eb, "ship_build_fuel_value_share")


def test_solar_skiff_odyssey_without_fuel_build_cost():
    cost = (get_ship("solar_skiff") or {}).get("build_cost") or {}
    assert cost == ODYSSEY_BUILD_COST
    assert cost["fuel_cells"] == 0
    assert _unit_build_cost("solar_skiff") == ODYSSEY_BUILD_COST


def test_odyssey_expo_value_without_fuel_component():
    assert expedition_ship_fleet_value("solar_skiff") == ODYSSEY_EXPO_VALUE


@pytest.mark.parametrize("hull_count,expected_loot", list(ODYSSEY_EXPO_BASE_LOOT.items()))
def test_odyssey_expo_base_loot_frozen(hull_count: int, expected_loot: int):
    expo_value = hull_count * ODYSSEY_EXPO_VALUE
    assert calculate_base_expedition_loot(expo_value) == pytest.approx(expected_loot, rel=0.01)


@pytest.mark.parametrize("ship_key,expected", list(UNCHANGED_EARLY_SHIP_COSTS.items()))
def test_early_ships_unchanged(ship_key: str, expected: dict) -> None:
    raw = (get_ship(ship_key) or {}).get("build_cost") or {}
    assert raw == expected
    assert _unit_build_cost(ship_key) == expected


@pytest.mark.parametrize("ship_key,expected_fuel", list(HIGH_TIER_SHIP_FUEL.items()))
def test_high_tier_ship_fuel_targets(ship_key: str, expected_fuel: int) -> None:
    assert _unit_build_cost(ship_key)["fuel_cells"] == expected_fuel


@pytest.mark.parametrize("defense_key", ["sentinel_turret"])
def test_early_defense_without_fuel(defense_key: str) -> None:
    assert unit_build_cost(defense_key)["fuel_cells"] == 0


@pytest.mark.parametrize("defense_key,expected_fuel", list(HIGH_TIER_DEFENSE_FUEL.items()))
def test_high_tier_defense_fuel_targets(defense_key: str, expected_fuel: int) -> None:
    assert unit_build_cost(defense_key)["fuel_cells"] == expected_fuel


def test_ship_detail_reads_static_defs():
    cost = _unit_build_cost("ironclad_frigate")
    card, err = build_ship_detail_card("ironclad_frigate")
    assert err is None
    assert card["build_cost_fuel_cells"] == cost["fuel_cells"] == 12500


def test_all_active_defs_declare_fuel_cells_explicitly():
    for key in ACTIVE_SHIP_KEYS:
        assert "fuel_cells" in ((SHIPS[key].get("build_cost") or {})), key
    for key in ACTIVE_DEFENSE_KEYS:
        assert "fuel_cells" in ((DEFENSES[key].get("build_cost") or {})), key


def test_shipyard_max_build_blocked_by_fuel():
    cost = _unit_build_cost("ironclad_frigate")
    max_qty = ship_max_build(500_000, 500_000, cost["fuel_cells"] - 1, "ironclad_frigate", 8)
    assert max_qty == 0


def test_defense_max_build_blocked_by_fuel():
    cost = unit_build_cost("orbital_shield")
    assert max_build_amount_for_planet(500_000, 500_000, cost["fuel_cells"] - 1, "orbital_shield", 8) == 0
    assert max_build_amount_for_planet(500_000, 500_000, cost["fuel_cells"], "orbital_shield", 8) == 1


def test_refund_from_stored_costs_includes_fuel_cells():
    class _Conn:
        def cursor(self):
            return self

        def execute(self, sql, params=()):
            self.last_refund = params
            return self

        def fetchone(self):
            return None

    conn = _Conn()
    out = refund_from_stored_costs(
        conn,
        1,
        {"cost_metal": 1000, "cost_crystal": 500, "cost_fuel_cells": 25000},
        start_time=100.0,
        finish_time=200.0,
        now=0.0,
    )
    assert out["refund_fuel_cells"] == 25000.0
    assert conn.last_refund[2] == 25000.0
