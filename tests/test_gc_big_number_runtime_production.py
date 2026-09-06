"""No-Max production runtime contract beyond IEEE-754."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

import pytest

from game.economy_balance import storage_capacity_at_depot_level
from game.effects import EffectResolver
from game.exact_math import decimal_mul_div_floor
from game.production_formula import (
    ProductionContext,
    calculate_resource_output,
    calculate_resource_output_decimal,
    mine_output,
    mine_output_decimal,
)
from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
FLOAT_OVERFLOW_LEVEL = 20_000


@pytest.mark.parametrize("level", [1, 10, 30, 60, 120])
def test_decimal_mine_curve_preserves_normal_balance(level):
    legacy = mine_output("metal", level)
    exact = mine_output_decimal("metal", level)
    assert float(exact) == pytest.approx(legacy, rel=1e-12)


def test_decimal_production_crosses_ieee754_range_without_infinity():
    mine = mine_output_decimal("metal", FLOAT_OVERFLOW_LEVEL)
    total = calculate_resource_output_decimal(
        "metal",
        ProductionContext("metal", FLOAT_OVERFLOW_LEVEL, slot=9),
    )

    assert mine.is_finite()
    assert total.is_finite()
    assert mine > Decimal("1e308")
    assert total > Decimal("1e308")


def test_authoritative_integer_output_uses_decimal_curve():
    resolver = EffectResolver(
        {
            "metal_mine": FLOAT_OVERFLOW_LEVEL,
            "crystal_mine": 0,
            "fuel_cell_plant": 0,
            "solar_plant": FLOAT_OVERFLOW_LEVEL,
            "metal_storage": 7_000,
        },
        {},
    )
    output = resolver.get_building_production_per_hour(1.0)
    assert isinstance(output["metal_mine"], int)
    assert output["metal_mine"] > 10**308


def test_bigint_energy_ratio_is_bounded_without_float_conversion():
    huge = 10**400
    assert EffectResolver.energy_ratio(huge, huge * 2) == 0.5
    assert EffectResolver.energy_ratio(huge * 2, huge) == 1.0


def test_storage_reference_capacity_survives_float_range():
    cap = storage_capacity_at_depot_level(7_000)
    assert isinstance(cap, int)
    assert cap > 10**308


def test_decimal_tick_scaling_keeps_full_integer_precision():
    per_hour = Decimal("1234567890123456789012345678901234567890.75")
    assert decimal_mul_div_floor(per_hour, 3600, 3600) == int(per_hour)
    assert decimal_mul_div_floor(per_hour, 1800, 3600) == 617283945061728394506172839450617283945


def test_runtime_sources_route_authoritative_production_around_float():
    production = (ROOT / "game" / "production_formula.py").read_text(encoding="utf-8")
    resolver = (ROOT / "game" / "effects" / "effect_resolver.py").read_text(encoding="utf-8")
    resources = (ROOT / "game" / "resources.py").read_text(encoding="utf-8")
    economy = (ROOT / "game" / "economy_balance.py").read_text(encoding="utf-8")

    assert "def mine_output_decimal" in production
    assert "def calculate_resource_output_decimal" in production
    assert "def production_per_hour_exact" in resolver
    assert "calculate_resource_output_decimal" in resolver
    assert "resolver.production_per_hour_exact(ratio)" in resources
    assert "decimal_mul_div_floor(metal_ph, delta, 3600)" in resources
    assert "mine_output_decimal(" in economy


@requires_postgres
def test_live_postgres_projection_roundtrip_above_float_range(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.db import commit, db
    from game.models import create_user, get_homeworld, save_planet
    from game.resources import project_planet_resource_balances

    username = f"PgNoMaxProd{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NoMaxProduction99")
    assert ok and user, reason
    player_id = int(user["id"])

    conn = db()
    try:
        planet = dict(get_homeworld(player_id=player_id, conn=conn))
        planet_id = int(planet["id"])
        base_time = 1_700_000_000.0

        conn.execute(
            """
            UPDATE planet_buildings
            SET metal_mine = ?,
                crystal_mine = 0,
                fuel_cell_plant = 0,
                solar_plant = ?,
                metal_storage = ?
            WHERE planet_id = ?;
            """,
            (FLOAT_OVERFLOW_LEVEL, FLOAT_OVERFLOW_LEVEL, 7_000, planet_id),
        )
        conn.execute(
            """
            UPDATE planets
            SET metal = 0,
                crystal = 0,
                fuel_cells = 0,
                last_update = ?
            WHERE id = ?;
            """,
            (base_time, planet_id),
        )
        commit(conn)

        planet = dict(get_homeworld(player_id=player_id, conn=conn))
        projected = project_planet_resource_balances(
            planet,
            conn=conn,
            now=base_time + 3600,
        )

        assert int(projected["metal"]) > 10**308
        assert int(projected["metal"]) < storage_capacity_at_depot_level(7_000)

        save_planet(projected, conn=conn)
        commit(conn)
        row = conn.execute(
            "SELECT metal FROM planets WHERE id = ?;",
            (planet_id,),
        ).fetchone()
        assert int(row["metal"]) == int(projected["metal"])
    finally:
        conn.close()
        close_pg_pool()
