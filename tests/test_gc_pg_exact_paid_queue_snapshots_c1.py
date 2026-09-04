"""P0-C exact paid queue snapshot contract."""

from __future__ import annotations

import time
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "168_paid_queue_exact_cost_snapshots.sql"

HUGE = 10**30 + 246_813_579


def test_paid_queue_exact_migration_is_additive_and_backfills_legacy_rows():
    sql = MIGRATION.read_text(encoding="utf-8")

    for table, resources in (
        ("research_queue", ("metal", "crystal")),
        ("shipyard_queue", ("metal", "crystal", "fuel_cells")),
        ("defense_queue", ("metal", "crystal", "fuel_cells")),
    ):
        for resource in resources:
            assert (
                f"ALTER TABLE {table} ADD COLUMN cost_{resource}_exact TEXT "
                "NOT NULL DEFAULT '0'"
            ) in sql
            assert f"cost_{resource}_exact = CAST(cost_{resource} AS TEXT)" in sql

    # Rolling compatibility stays additive: legacy columns are not dropped/retyped.
    assert "DROP COLUMN cost_" not in sql
    assert "ALTER COLUMN cost_" not in sql


def test_exact_snapshot_reader_prefers_text_and_handles_legacy_decimal():
    from game.queue_refund import stored_cost_int

    row = {
        "cost_metal": 123,
        "cost_metal_exact": str(HUGE),
        "cost_crystal": 456,
        "cost_crystal_exact": "0",
        "cost_fuel_cells": "789.0",
        "cost_fuel_cells_exact": "0",
    }
    assert stored_cost_int(row, "metal") == HUGE
    assert stored_cost_int(row, "crystal") == 456
    assert stored_cost_int(row, "fuel_cells") == 789


def test_runtime_writers_and_refunds_reference_exact_snapshots():
    models = (ROOT / "game" / "models.py").read_text(encoding="utf-8")
    research = (ROOT / "game" / "research.py").read_text(encoding="utf-8")
    shipyard = (ROOT / "game" / "shipyard_queue.py").read_text(encoding="utf-8")
    defense = (ROOT / "game" / "defense.py").read_text(encoding="utf-8")
    refunds = (ROOT / "game" / "queue_refund.py").read_text(encoding="utf-8")
    audit = (ROOT / "scripts" / "pg_numeric_readiness_audit.py").read_text(
        encoding="utf-8"
    )

    assert "cost_metal_exact, cost_crystal_exact" in models
    assert 'str(exact_metal)' in models
    assert 'str(exact_crystal)' in models

    assert "cost_metal_exact, cost_crystal_exact, cost_fuel_cells_exact" in shipyard
    assert "_legacy_i64_cost_snapshot(exact_fuel)" in shipyard
    assert 'stored_cost_int(row, "fuel_cells")' in shipyard

    assert "cost_metal_exact, cost_crystal_exact, cost_fuel_cells_exact" in defense
    assert "_legacy_i64_cost_snapshot(exact_fuel)" in defense
    assert 'stored_cost_int(row, "fuel_cells")' in defense

    assert "cost_metal_exact, cost_crystal_exact" in research
    assert 'stored_cost_int(dict(row), "metal")' in research
    assert 'stored_cost_int(dict(row), "crystal")' in research

    assert 'stored_cost_int(costs, "metal")' in refunds
    assert 'stored_cost_int(costs, "crystal")' in refunds
    assert 'stored_cost_int(costs, "fuel_cells")' in refunds

    for table, resource in (
        ("research_queue", "cost_metal_exact"),
        ("research_queue", "cost_crystal_exact"),
        ("shipyard_queue", "cost_metal_exact"),
        ("shipyard_queue", "cost_crystal_exact"),
        ("shipyard_queue", "cost_fuel_cells_exact"),
        ("defense_queue", "cost_metal_exact"),
        ("defense_queue", "cost_crystal_exact"),
        ("defense_queue", "cost_fuel_cells_exact"),
    ):
        assert f'NumericPolicy("{table}", "{resource}", "exact_snapshot"' in audit


@requires_postgres
def test_live_postgres_exact_paid_queue_snapshots_above_i64(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.db import db
    from game.defense import enqueue_defense_build
    from game.models import add_research_job, create_user, get_homeworld
    from game.queue_refund import refund_from_stored_costs, stored_cost_int
    from game.shipyard_queue import enqueue_ship_build

    username = f"PgNumericC1{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericC1xx99")
    assert ok and user, reason
    player_id = int(user["id"])
    planet_id = int(get_homeworld(player_id)["id"])

    now = time.time()
    research_id = add_research_job(
        player_id,
        "energy_tech",
        now + 600,
        now + 1200,
        conn=None,
        cost_metal=HUGE,
        cost_crystal=HUGE + 1,
    )

    conn = db()
    try:
        ok_ship, reason_ship, shipyard_id = enqueue_ship_build(
            player_id=player_id,
            planet_id=planet_id,
            ship_key="mule_courier",
            amount=1,
            shipyard_level=1,
            cost={
                "metal": HUGE + 2,
                "crystal": HUGE + 3,
                "fuel_cells": HUGE + 4,
            },
            conn=conn,
        )
        assert ok_ship, reason_ship
        assert shipyard_id is not None

        ok_def, reason_def, defense_id = enqueue_defense_build(
            player_id=player_id,
            planet_id=planet_id,
            defense_key="slug_launcher",
            amount=1,
            cost={
                "metal": HUGE + 5,
                "crystal": HUGE + 6,
                "fuel_cells": HUGE + 7,
            },
            conn=conn,
        )
        assert ok_def, reason_def
        assert defense_id is not None
        conn.commit()

        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'research_queue'
                    AND column_name IN ('cost_metal_exact','cost_crystal_exact'))
                OR
                (table_name = 'shipyard_queue'
                    AND column_name IN (
                        'cost_metal_exact','cost_crystal_exact','cost_fuel_cells_exact'
                    ))
                OR
                (table_name = 'defense_queue'
                    AND column_name IN (
                        'cost_metal_exact','cost_crystal_exact','cost_fuel_cells_exact'
                    ))
              );
            """
        ).fetchall()
        assert len(rows) == 8
        assert all(str(row["data_type"]).lower() == "text" for row in rows)

        research = dict(
            conn.execute(
                """
                SELECT cost_metal, cost_crystal,
                       cost_metal_exact, cost_crystal_exact
                FROM research_queue WHERE id = ?;
                """,
                (research_id,),
            ).fetchone()
        )
        assert research["cost_metal_exact"] == str(HUGE)
        assert research["cost_crystal_exact"] == str(HUGE + 1)
        assert int(research["cost_metal"]) == 0
        assert int(research["cost_crystal"]) == 0

        shipyard = dict(
            conn.execute(
                """
                SELECT cost_metal, cost_crystal, cost_fuel_cells,
                       cost_metal_exact, cost_crystal_exact, cost_fuel_cells_exact
                FROM shipyard_queue WHERE id = ?;
                """,
                (int(shipyard_id),),
            ).fetchone()
        )
        assert stored_cost_int(shipyard, "metal") == HUGE + 2
        assert stored_cost_int(shipyard, "crystal") == HUGE + 3
        assert stored_cost_int(shipyard, "fuel_cells") == HUGE + 4
        assert int(shipyard["cost_metal"]) == 0
        assert int(shipyard["cost_crystal"]) == 0
        assert int(shipyard["cost_fuel_cells"]) == 0

        defense = dict(
            conn.execute(
                """
                SELECT cost_metal, cost_crystal, cost_fuel_cells,
                       cost_metal_exact, cost_crystal_exact, cost_fuel_cells_exact
                FROM defense_queue WHERE id = ?;
                """,
                (int(defense_id),),
            ).fetchone()
        )
        assert stored_cost_int(defense, "metal") == HUGE + 5
        assert stored_cost_int(defense, "crystal") == HUGE + 6
        assert stored_cost_int(defense, "fuel_cells") == HUGE + 7
        assert int(defense["cost_metal"]) == 0
        assert int(defense["cost_crystal"]) == 0
        assert int(defense["cost_fuel_cells"]) == 0

        # Prove the refund owner consumes exact snapshots rather than legacy zeros.
        conn.execute(
            "UPDATE planets SET metal = 0, crystal = 0, fuel_cells = 0 WHERE id = ?;",
            (planet_id,),
        )
        refund_from_stored_costs(
            conn,
            planet_id,
            shipyard,
            start_time=now + 300,
            finish_time=now + 900,
            now=now,
        )
        conn.commit()

        balances = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
            (planet_id,),
        ).fetchone()
        assert int(balances["metal"]) == HUGE + 2
        assert int(balances["crystal"]) == HUGE + 3
        assert int(balances["fuel_cells"]) == HUGE + 4
    finally:
        conn.close()
        close_pg_pool()
