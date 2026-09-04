"""P0-A3 exact core-resource consumer contract."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**40 + 123_456_789


def test_fleet_resource_math_is_exact_above_i64():
    from game.fleet_calc import (
        apply_departure_deduction,
        calculate_loaded_resources,
        planet_resource_stock,
        validate_departure_balances,
    )
    from game.fleet_defs import FLEET_FUEL_RESOURCE

    cargo = {
        "metal": HUGE,
        "crystal": HUGE + 1,
        "fuel_cells": HUGE + 2,
    }
    loaded = calculate_loaded_resources(cargo)
    assert loaded == cargo

    pg_like_row = {
        "metal": Decimal(HUGE + 7),
        "crystal": Decimal(HUGE + 8),
        "fuel_cells": Decimal(HUGE + 9),
    }
    assert planet_resource_stock(pg_like_row) == {
        "metal": HUGE + 7,
        "crystal": HUGE + 8,
        "fuel_cells": HUGE + 9,
    }

    metal_have = HUGE * 3 + 7
    crystal_have = HUGE * 3 + 11
    fuel_have = HUGE * 3 + 13
    fuel_cost = 17
    ok, reason = validate_departure_balances(
        metal_have,
        crystal_have,
        fuel_have,
        cargo,
        fuel_cost,
    )
    assert ok, reason

    new_metal, new_crystal, new_fuel = apply_departure_deduction(
        metal_have,
        crystal_have,
        fuel_have,
        cargo,
        fuel_cost,
    )
    expected = {
        "metal": metal_have - cargo["metal"],
        "crystal": crystal_have - cargo["crystal"],
        "fuel_cells": fuel_have - cargo["fuel_cells"],
    }
    expected[FLEET_FUEL_RESOURCE] -= fuel_cost
    assert new_metal == expected["metal"]
    assert new_crystal == expected["crystal"]
    assert new_fuel == expected["fuel_cells"]


def test_queue_refund_decimal_precision_scales_above_i64():
    from game.queue_refund import scaled_refund_amount

    odd = HUGE + 1
    assert scaled_refund_amount(odd, 0.5) == odd // 2
    assert scaled_refund_amount(odd, 1.0) == odd


def test_core_resource_consumers_block_authoritative_float_roundtrips():
    sources = {
        rel: (ROOT / rel).read_text(encoding="utf-8")
        for rel in (
            "game/fleet.py",
            "game/fleet_calc.py",
            "game/ranking.py",
            "game/scrapyard.py",
            "game/buildings.py",
            "game/research.py",
            "game/shipyard.py",
            "game/defense.py",
            "game/inactive_autoplay.py",
            "game/planet_evolution/dashboard.py",
            "game/queue_refund.py",
            "game/spy.py",
            "game/commander_classes.py",
            "game/admin_balance.py",
            "game/overview_page.py",
            "game/planet_evolution/ascension.py",
        )
    }

    forbidden_by_file = {
        "game/fleet.py": (
            'float(origin_planet.get("metal")',
            'float(origin_planet.get("crystal")',
            'float(origin_planet.get("fuel_cells")',
            'float(row["metal"]) + loaded["metal"]',
            'float(row["crystal"]) + loaded["crystal"]',
            'int(float(planet.get("metal")',
        ),
        "game/fleet_calc.py": (
            'int(float(raw.get("metal")',
            'int(float(raw.get("crystal")',
            'int(float(raw.get("fuel_cells")',
            'float(metal_have) - loaded["metal"]',
            'float(crystal_have) - loaded["crystal"]',
        ),
        "game/ranking.py": (
            'int(float(planet.get("metal")',
            'int(float(planet.get("crystal")',
            'int(float(planet.get("fuel_cells")',
        ),
        "game/scrapyard.py": (
            'int(float(planet["metal"]',
            'int(float(planet["crystal"]',
            'int(float(planet["fuel_cells"]',
            'float(refund["fuel_cells"])',
        ),
        "game/buildings.py": (
            'metal_available=float(planet.get("metal"',
            'crystal_available=float(planet.get("crystal"',
            'planet_metal = float(planet.get("metal"',
            'planet_crystal = float(planet.get("crystal"',
            'planet_metal = float(prow["metal"]',
            'planet_crystal = float(prow["crystal"]',
        ),
        "game/research.py": (
            'planet_metal = float(prow["metal"]',
            'planet_crystal = float(prow["crystal"]',
            'planet_metal = float(resource_planet.get("metal")',
            'planet_crystal = float(resource_planet.get("crystal")',
            'avail_m = float(after["metal"]',
            'avail_c = float(after["crystal"]',
        ),
        "game/shipyard.py": (
            'float(row["metal"] or 0)',
            'float(row["crystal"] or 0)',
            'float(row["fuel_cells"] or 0)',
        ),
        "game/defense.py": (
            # Queue cost snapshots remain P0-C; only live planet reads are blocked here.
            'return (\n        float(row["metal"] or 0)',
            'float(row["crystal"] or 0),\n        float(row["fuel_cells"] or 0)',
        ),
        "game/inactive_autoplay.py": (
            'max(float(row["metal"]',
            'max(float(row["crystal"]',
            'max(float(row["fuel_cells"]',
            'int(float(row["metal"]',
            'int(float(row["crystal"]',
            'int(float(row["fuel_cells"]',
        ),
        "game/planet_evolution/dashboard.py": (
            'metal = float(planet.get("metal")',
            'crystal = float(planet.get("crystal")',
        ),
        "game/queue_refund.py": (
            'fuel_cells=float(refund_f)',
            '"refund_fuel_cells": float(refund_f)',
        ),
        "game/spy.py": (
            'int(float(data.get("metal")',
            'int(float(data.get("crystal")',
            'int(float(data.get("fuel_cells")',
        ),
        "game/commander_classes.py": (
            'float(fuel_cells),',
        ),
        "game/admin_balance.py": (
            'int(float(player_view.get("metal")',
            'int(float(player_view.get("crystal")',
            'int(float(player_view.get("fuel_cells")',
        ),
        "game/overview_page.py": (
            '"metal": float(player_view.get("metal")',
            '"crystal": float(player_view.get("crystal")',
            '"fuel_cells": float(player_view.get("fuel_cells")',
            'metal=float(player_view.get("metal")',
            'crystal=float(player_view.get("crystal")',
            'fuel_cells=float(player_view.get("fuel_cells")',
        ),
        "game/planet_evolution/ascension.py": (
            'float(prow["metal"]',
            'float(prow["crystal"]',
        ),
    }

    for rel, forbidden in forbidden_by_file.items():
        source = sources[rel]
        for token in forbidden:
            assert token not in source, f"{rel} reintroduced resource float path: {token}"


def test_backend_aware_binder_is_used_for_resource_writes():
    sources = {
        rel: (ROOT / rel).read_text(encoding="utf-8")
        for rel in (
            "game/fleet.py",
            "game/shipyard.py",
            "game/defense.py",
            "game/inactive_autoplay.py",
            "game/queue_refund.py",
            "game/commander_classes.py",
        )
    }
    for rel, source in sources.items():
        assert "resource_db_param" in source, rel
