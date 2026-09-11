from decimal import Decimal

import game.server_events as server_events
from game.economy_balance import (
    STORAGE_ENDGAME_START_LEVEL,
    storage_reference_hours_at_depot_level,
)
from game.effects.effect_resolver import EffectResolver
from game.resources import apply_fuel_production_delta, apply_production_delta


def _endgame_resolver(*, research=None, terraformer=0, storage_level=150, mine_level=450, position=9):
    return EffectResolver(
        {
            "metal_mine": mine_level,
            "crystal_mine": mine_level,
            "fuel_cell_plant": mine_level,
            "metal_storage": storage_level,
            "crystal_storage": storage_level,
            "fuel_storage": storage_level,
            "terraformer": terraformer,
        },
        research or {},
        settings={"production_speed": 1.0},
        planet_position=position,
    )


def test_storage_v2_keeps_early_game_reference_behavior():
    resolver = _endgame_resolver(storage_level=STORAGE_ENDGAME_START_LEVEL - 1, mine_level=450)
    caps = resolver.get_storage_capacity()
    assert caps["metal"] == resolver._storage_base_cap("metal", STORAGE_ENDGAME_START_LEVEL - 1)


def test_storage_v2_buffers_canonical_resource_specific_full_power_production():
    resolver = _endgame_resolver(research={"crystal_tech": 120, "drone_tech": 80})
    caps = resolver.get_storage_capacity()
    hours = storage_reference_hours_at_depot_level(150)
    metal_ph, crystal_ph = resolver.production_per_hour_exact(1.0)
    fuel_ph = resolver.fuel_cells_production_per_hour_exact(1.0)

    assert caps["metal"] >= int(metal_ph * Decimal(hours))
    assert caps["crystal"] >= int(crystal_ph * Decimal(hours))
    assert caps["fuel_cells"] >= int(fuel_ph * Decimal(hours))


def test_storage_v2_counts_active_production_event(monkeypatch):
    monkeypatch.setattr(server_events, "active_production_mult", lambda conn=None: 2.0)
    resolver = _endgame_resolver(position=4)
    hours = storage_reference_hours_at_depot_level(150)
    metal_ph, _ = resolver.production_per_hour_exact(1.0)
    cap = resolver.get_storage_capacity()["metal"]

    assert cap >= int(metal_ph * Decimal(hours))


def test_storage_v2_does_not_shrink_when_energy_is_short():
    resolver = _endgame_resolver(position=4)
    hours = storage_reference_hours_at_depot_level(150)
    full_ph, _ = resolver.production_per_hour_exact(1.0)
    low_ph, _ = resolver.production_per_hour_exact(0.01)
    cap = resolver.get_storage_capacity()["metal"]

    assert full_ph > low_ph
    assert cap >= int(full_ph * Decimal(hours))


def test_storage_v2_applies_storage_research_and_terraformer_after_floor():
    base = _endgame_resolver(position=4).get_storage_capacity()["metal"]
    boosted = _endgame_resolver(
        research={"storage_tech": 2},
        terraformer=10,
        position=4,
    ).get_storage_capacity()["metal"]

    # storage_tech 2 => 2.0x; terraformer 10 => 1.5x.
    assert boosted == base * 3


def test_storage_v2_handles_mando_scale_without_float_capacity_math():
    resolver = _endgame_resolver(storage_level=450, mine_level=2000, position=4)
    hours = storage_reference_hours_at_depot_level(450)
    metal_ph, _ = resolver.production_per_hour_exact(1.0)
    cap = resolver.get_storage_capacity()["metal"]

    assert hours == 216
    assert cap >= int(metal_ph * Decimal(hours))
    assert cap > 2**63


def test_production_delta_can_use_authoritative_contextual_resolver():
    class Resolver:
        @staticmethod
        def get_storage_capacity():
            return {"metal": 1000, "crystal": 2000, "fuel_cells": 3000}

    resolver = Resolver()
    planet = {"metal": 900, "crystal": 1900, "fuel_cells": 2900}
    apply_production_delta(
        planet, {}, delta_metal=500, delta_crystal=500, resolver=resolver
    )
    apply_fuel_production_delta(
        planet, {}, delta_fuel_cells=500, resolver=resolver
    )
    assert planet == {"metal": 1000, "crystal": 2000, "fuel_cells": 3000}
