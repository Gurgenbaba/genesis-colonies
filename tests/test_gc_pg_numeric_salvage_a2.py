"""P0-A2 PostgreSQL exact salvage-resource contract."""

from __future__ import annotations

import time
from decimal import Decimal, ROUND_FLOOR, localcontext
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "165_pg_salvage_resource_numeric.sql"

HUGE = 10**30 + 123_456_789
CAP = 10**24 + 77


def test_pg_salvage_migration_is_unbounded_numeric():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    for token in (
        "debris_fields\n    ALTER COLUMN metal TYPE NUMERIC",
        "debris_fields\n    ALTER COLUMN crystal TYPE NUMERIC",
        "asteroid_fields\n    ALTER COLUMN metal TYPE NUMERIC",
        "asteroid_fields\n    ALTER COLUMN crystal TYPE NUMERIC",
        "asteroid_fields\n    ALTER COLUMN fuel_cells TYPE NUMERIC",
        "asteroid_field_claims\n    ALTER COLUMN metal TYPE NUMERIC",
        "asteroid_field_claims\n    ALTER COLUMN crystal TYPE NUMERIC",
        "asteroid_field_claims\n    ALTER COLUMN fuel_cells TYPE NUMERIC",
    ):
        assert token in sql
    assert "NUMERIC(" not in sql


def test_debris_loss_math_is_exact_above_i64():
    from game.combat import (
        DEBRIS_CRYSTAL_FRACTION,
        DEBRIS_METAL_FRACTION,
        calculate_debris_from_losses,
        unit_build_cost_for_debris,
    )

    lost = HUGE
    unit_metal, unit_crystal = unit_build_cost_for_debris("mule_courier")
    metal, crystal = calculate_debris_from_losses({"mule_courier": lost})

    with localcontext() as ctx:
        ctx.prec = 128
        expected_m = int(
            (
                Decimal(unit_metal)
                * Decimal(lost)
                * Decimal(str(DEBRIS_METAL_FRACTION))
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
        expected_c = int(
            (
                Decimal(unit_crystal)
                * Decimal(lost)
                * Decimal(str(DEBRIS_CRYSTAL_FRACTION))
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
    assert metal == expected_m
    assert crystal == expected_c


def test_asteroid_split_load_stays_exact_above_i64():
    from game.asteroids import _split_load

    pool = {
        "metal": HUGE,
        "crystal": HUGE + 11,
        "fuel_cells": HUGE + 23,
    }
    total = sum(pool.values())
    got = _split_load(pool, CAP)

    expected_m = (CAP * pool["metal"]) // total
    expected_c = (CAP * pool["crystal"]) // total
    expected_f = CAP - expected_m - expected_c

    assert got == {
        "metal": expected_m,
        "crystal": expected_c,
        "fuel_cells": expected_f,
    }
    assert sum(got.values()) == CAP


def test_mega_belt_pool_uses_decimal_capacity_average(monkeypatch):
    from game import asteroids
    from game import economy_balance

    huge_a = 10**40 + 1
    huge_b = 10**40 + 101

    monkeypatch.setattr(
        asteroids,
        "_top_n_building_levels",
        lambda *args, **kwargs: [1, 2],
    )
    monkeypatch.setattr(
        economy_balance,
        "storage_capacity_at_depot_level",
        lambda level: huge_a if int(level) == 1 else huge_b,
    )

    got = asteroids._mega_belt_resource_pool(object())
    with localcontext() as ctx:
        ctx.prec = 128
        avg = Decimal(huge_a + huge_b) / Decimal(2)
        expected = int(
            (
                avg * Decimal(str(asteroids.MEGA_BELT_STORAGE_FRACTION))
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
    expected = max(asteroids.MEGA_BELT_MIN_POOL_PER_RESOURCE, expected)

    assert set(got) == {"metal", "crystal", "fuel_cells"}
    assert all(value == expected for value in got.values())


@requires_postgres
def test_live_postgres_salvage_roundtrip_above_i64(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.combat import add_debris_field, get_debris_at_field, harvest_debris_at_field
    from game.db import db
    from game.models import create_user

    username = f"PgNumericA2{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericA2xx99")
    assert ok and user, reason
    player_id = int(user["id"])

    conn = db()
    try:
        metadata_rows = conn.execute(
            """
            SELECT table_name, column_name, data_type, numeric_precision
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'debris_fields' AND column_name IN ('metal','crystal'))
                OR (table_name = 'asteroid_fields' AND column_name IN ('metal','crystal','fuel_cells'))
                OR (table_name = 'asteroid_field_claims' AND column_name IN ('metal','crystal','fuel_cells'))
              );
            """
        ).fetchall()
        expected_columns = {
            ("debris_fields", "metal"),
            ("debris_fields", "crystal"),
            ("asteroid_fields", "metal"),
            ("asteroid_fields", "crystal"),
            ("asteroid_fields", "fuel_cells"),
            ("asteroid_field_claims", "metal"),
            ("asteroid_field_claims", "crystal"),
            ("asteroid_field_claims", "fuel_cells"),
        }
        seen = set()
        for row in metadata_rows:
            key = (str(row["table_name"]), str(row["column_name"]))
            seen.add(key)
            assert str(row["data_type"]).lower() == "numeric"
            assert row["numeric_precision"] is None
        assert seen == expected_columns

        field = add_debris_field(1, 498, 15, HUGE, HUGE + 9, conn=conn)
        assert field["metal"] == HUGE
        assert field["crystal"] == HUGE + 9
        conn.commit()

        field = get_debris_at_field(1, 498, 15, conn=conn)
        assert field == {"metal": HUGE, "crystal": HUGE + 9}

        take = 10**20 + 3
        assert harvest_debris_at_field(
            1,
            498,
            15,
            harvested={"metal": take, "crystal": take + 1},
            conn=conn,
        )
        conn.commit()
        field = get_debris_at_field(1, 498, 15, conn=conn)
        assert field["metal"] == HUGE - take
        assert field["crystal"] == HUGE + 9 - (take + 1)

        asteroid_row = conn.execute(
            """
            INSERT INTO asteroid_fields (
                asteroid_key, galaxy, system, position,
                metal, crystal, fuel_cells, status, spawned_at, expires_at, tier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id;
            """,
            (
                "mixed_belt",
                1,
                497,
                14,
                HUGE,
                HUGE + 1,
                HUGE + 2,
                "active",
                time.time(),
                time.time() + 3600,
                "mega",
            ),
        ).fetchone()
        asteroid_id = int(asteroid_row["id"])
        conn.execute(
            """
            INSERT INTO asteroid_field_claims (
                asteroid_id, player_id, claimed_at, metal, crystal, fuel_cells
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (asteroid_id, player_id, time.time(), HUGE + 3, HUGE + 4, HUGE + 5),
        )
        conn.commit()

        row = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM asteroid_fields WHERE id = ?;",
            (asteroid_id,),
        ).fetchone()
        assert tuple(int(row[k]) for k in ("metal", "crystal", "fuel_cells")) == (
            HUGE,
            HUGE + 1,
            HUGE + 2,
        )
        row = conn.execute(
            """
            SELECT metal, crystal, fuel_cells
            FROM asteroid_field_claims
            WHERE asteroid_id = ?;
            """,
            (asteroid_id,),
        ).fetchone()
        assert tuple(int(row[k]) for k in ("metal", "crystal", "fuel_cells")) == (
            HUGE + 3,
            HUGE + 4,
            HUGE + 5,
        )
    finally:
        conn.close()
        close_pg_pool()
