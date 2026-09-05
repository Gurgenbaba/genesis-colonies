"""P0-B2/P1-final PostgreSQL no-max defense/troop quantity contract."""

from __future__ import annotations

import time
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "167_pg_unit_amounts_bigint.sql"
FINAL_MIGRATION = ROOT / "migrations" / "173_pg_p1_final_no_max_numeric.sql"

OVER_INT4 = 5_000_000_000
HUGE = 10**30 + 246_813_579


def test_pg_unit_amount_migration_widens_only_quantity_columns():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    for token in (
        "defense_queue\n    ALTER COLUMN amount TYPE BIGINT",
        "planet_troops\n    ALTER COLUMN amount TYPE BIGINT",
        "troop_queue\n    ALTER COLUMN amount TYPE BIGINT",
    ):
        assert token in sql

    # Paid queue snapshots are P0-C, not hidden inside this amount slice.
    for token in (
        "cost_metal TYPE",
        "cost_crystal TYPE",
        "cost_fuel_cells TYPE",
    ):
        assert token not in sql


def test_final_unit_amount_migration_removes_bigint_ceiling():
    sql = FINAL_MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    assert "NUMERIC(" not in sql
    for table in ("defense_queue", "planet_troops", "troop_queue"):
        assert f"ALTER TABLE {table}" in sql
        assert "ALTER COLUMN amount TYPE NUMERIC" in sql


def test_production_duration_math_handles_no_max_quantity():
    from game.shipyard import production_job_duration_seconds

    amount = HUGE
    capacity = 7
    unit_seconds = 13
    expected_batches = (amount + capacity - 1) // capacity
    assert production_job_duration_seconds(
        unit_seconds=unit_seconds,
        amount=amount,
        batch_capacity=capacity,
    ) == expected_batches * unit_seconds


@requires_postgres
def test_live_postgres_unit_amounts_roundtrip_above_i64(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.db import db
    from game.models import create_user, get_homeworld
    from game.troops import get_planet_troops, set_planet_troops

    username = f"PgNumericB2{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericB2xx99")
    assert ok and user, reason
    player_id = int(user["id"])
    planet_id = int(get_homeworld(player_id)["id"])

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'defense_queue' AND column_name = 'amount')
                OR (table_name = 'planet_troops' AND column_name = 'amount')
                OR (table_name = 'troop_queue' AND column_name = 'amount')
              );
            """
        ).fetchall()
        seen = {
            (str(row["table_name"]), str(row["column_name"])): str(row["data_type"]).lower()
            for row in rows
        }
        assert seen == {
            ("defense_queue", "amount"): "numeric",
            ("planet_troops", "amount"): "numeric",
            ("troop_queue", "amount"): "numeric",
        }

        set_planet_troops(
            planet_id,
            {"militia": HUGE},
            conn=conn,
        )
        conn.commit()
        stock = get_planet_troops(planet_id, conn=conn)
        assert int(stock["militia"]) == HUGE

        now = time.time()
        defense = conn.execute(
            """
            INSERT INTO defense_queue (
                player_id, planet_id, defense_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal, cost_fuel_cells
            ) VALUES (?, ?, 'numeric_probe', ?, 'queued',
                      ?, ?, ?, 0, 0, 0, 0)
            RETURNING id;
            """,
            (
                player_id,
                planet_id,
                HUGE,
                now,
                now + 3600,
                now,
            ),
        ).fetchone()
        defense_id = int(defense["id"])

        troop = conn.execute(
            """
            INSERT INTO troop_queue (
                player_id, planet_id, troop_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal
            ) VALUES (?, ?, 'militia', ?, 'queued',
                      ?, ?, ?, 0, 0, 0)
            RETURNING id;
            """,
            (
                player_id,
                planet_id,
                HUGE,
                now,
                now + 3600,
                now,
            ),
        ).fetchone()
        troop_id = int(troop["id"])
        conn.commit()

        row = conn.execute(
            "SELECT amount FROM defense_queue WHERE id = ?;",
            (defense_id,),
        ).fetchone()
        assert int(row["amount"]) == HUGE

        row = conn.execute(
            "SELECT amount FROM troop_queue WHERE id = ?;",
            (troop_id,),
        ).fetchone()
        assert int(row["amount"]) == HUGE

        # Exercise in-place queue arithmetic while still far above signed i64.
        decrement = 10**20 + 7
        conn.execute(
            "UPDATE defense_queue SET amount = amount - ? WHERE id = ?;",
            (decrement, defense_id),
        )
        conn.execute(
            "UPDATE troop_queue SET amount = amount - ? WHERE id = ?;",
            (decrement, troop_id),
        )
        conn.commit()

        row = conn.execute(
            "SELECT amount FROM defense_queue WHERE id = ?;",
            (defense_id,),
        ).fetchone()
        assert int(row["amount"]) == HUGE - decrement

        row = conn.execute(
            "SELECT amount FROM troop_queue WHERE id = ?;",
            (troop_id,),
        ).fetchone()
        assert int(row["amount"]) == HUGE - decrement
    finally:
        conn.close()
        close_pg_pool()
