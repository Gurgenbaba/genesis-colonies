"""P1-B no-max stocks + exact troop paid-cost contract."""

from __future__ import annotations

import time
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_MIGRATION = ROOT / "migrations" / "170_troop_queue_exact_cost_snapshots.sql"
STOCK_MIGRATION = ROOT / "migrations" / "171_pg_p1_stock_amounts_numeric.sql"

HUGE = 10**30 + 135_791_113


def test_p1_stock_and_troop_snapshot_migrations_match_contract():
    snapshot_sql = SNAPSHOT_MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-REQUIRES-TABLES: troop_queue" in snapshot_sql
    assert (
        "ALTER TABLE troop_queue ADD COLUMN cost_metal_exact TEXT NOT NULL DEFAULT '0'"
        in snapshot_sql
    )
    assert (
        "ALTER TABLE troop_queue ADD COLUMN cost_crystal_exact TEXT NOT NULL DEFAULT '0'"
        in snapshot_sql
    )
    assert "cost_metal_exact = CAST(cost_metal AS TEXT)" in snapshot_sql
    assert "cost_crystal_exact = CAST(cost_crystal AS TEXT)" in snapshot_sql

    stock_sql = STOCK_MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in stock_sql
    assert "NUMERIC(" not in stock_sql
    for table in ("planet_ships", "shipyard_queue", "planet_defense"):
        assert f"ALTER TABLE {table}" in stock_sql
        assert "ALTER COLUMN amount TYPE NUMERIC" in stock_sql


def test_troop_max_affordability_is_exact_above_js_safe_integer():
    from game.troops import get_troop, max_train_amount_for_planet

    spec = get_troop("militia")
    assert spec
    cost = spec["train_cost"]
    cost_m = int(cost.get("metal") or 0)
    cost_c = int(cost.get("crystal") or 0)

    metal = HUGE * 3
    crystal = HUGE * 5
    capacity = HUGE * 10
    expected = min(
        capacity,
        metal // cost_m if cost_m > 0 else capacity,
        crystal // cost_c if cost_c > 0 else capacity,
    )
    assert (
        max_train_amount_for_planet(
            metal,
            crystal,
            "militia",
            99,
            capacity_left=capacity,
        )
        == expected
    )


def test_troop_runtime_uses_exact_cost_snapshots_and_integer_resources():
    source = (ROOT / "game" / "troops.py").read_text(encoding="utf-8")
    audit = (ROOT / "scripts" / "pg_numeric_readiness_audit.py").read_text(
        encoding="utf-8"
    )

    assert "cost_metal_exact, cost_crystal_exact" in source
    assert "_legacy_i64_cost_snapshot(cost_m)" in source
    assert "_legacy_i64_cost_snapshot(cost_c)" in source
    assert "str(cost_m)" in source
    assert "str(cost_c)" in source
    assert 'stored_cost_int(paid, "metal")' in source
    assert 'stored_cost_int(paid, "crystal")' in source

    assert 'metal_have = float((prow["metal"]' not in source
    assert 'crystal_have = float((prow["crystal"]' not in source
    assert 'metal_have = int((prow["metal"]' in source
    assert 'crystal_have = int((prow["crystal"]' in source

    assert (
        'NumericPolicy("troop_queue", "cost_metal_exact", "exact_snapshot"'
        in audit
    )
    assert (
        'NumericPolicy("troop_queue", "cost_crystal_exact", "exact_snapshot"'
        in audit
    )


@requires_postgres
def test_live_postgres_p1_stock_and_troop_snapshot_roundtrip(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.db import db
    from game.fleet import get_planet_ships, set_planet_ships
    from game.models import (
        create_user,
        get_homeworld,
        get_planet_defense,
        set_planet_defense,
    )
    from game.troops import cancel_troop_job

    username = f"PgNumericP1B{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericP1Bxx99")
    assert ok and user, reason
    player_id = int(user["id"])
    planet_id = int(get_homeworld(player_id)["id"])

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type, numeric_precision
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'planet_ships' AND column_name = 'amount')
                OR (table_name = 'shipyard_queue' AND column_name = 'amount')
                OR (table_name = 'planet_defense' AND column_name = 'amount')
                OR (table_name = 'troop_queue'
                    AND column_name IN ('cost_metal_exact','cost_crystal_exact'))
              );
            """
        ).fetchall()
        meta = {
            (str(row["table_name"]), str(row["column_name"])): row
            for row in rows
        }
        for key in (
            ("planet_ships", "amount"),
            ("shipyard_queue", "amount"),
            ("planet_defense", "amount"),
        ):
            assert str(meta[key]["data_type"]).lower() == "numeric"
            assert meta[key]["numeric_precision"] is None
        for key in (
            ("troop_queue", "cost_metal_exact"),
            ("troop_queue", "cost_crystal_exact"),
        ):
            assert str(meta[key]["data_type"]).lower() == "text"

        set_planet_ships(
            planet_id,
            player_id,
            {"spark_drone": HUGE},
            conn=conn,
        )
        set_planet_defense(
            planet_id,
            {"slug_launcher": HUGE + 1},
            conn=conn,
        )

        now = time.time()
        ship_job = conn.execute(
            """
            INSERT INTO shipyard_queue (
                player_id, planet_id, ship_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal, cost_fuel_cells,
                cost_metal_exact, cost_crystal_exact, cost_fuel_cells_exact
            ) VALUES (?, ?, 'spark_drone', ?, 'queued',
                      ?, ?, ?, 0, 0, 0, 0, '0', '0', '0')
            RETURNING id;
            """,
            (player_id, planet_id, HUGE + 2, now, now + 3600, now),
        ).fetchone()
        ship_job_id = int(ship_job["id"])

        # Two queued troop rows: cancel the second one so the historical rule
        # refunds 100%. Its legacy costs are deliberately zero; only exact TEXT
        # contains the real paid value.
        conn.execute(
            """
            INSERT INTO troop_queue (
                player_id, planet_id, troop_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal, cost_metal_exact, cost_crystal_exact
            ) VALUES (?, ?, 'militia', 1, 'queued',
                      ?, ?, ?, 0, 0, 0, '0', '0');
            """,
            (player_id, planet_id, now, now + 3600, now),
        )
        target = conn.execute(
            """
            INSERT INTO troop_queue (
                player_id, planet_id, troop_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal, cost_metal_exact, cost_crystal_exact
            ) VALUES (?, ?, 'militia', 1, 'queued',
                      ?, ?, ?, 1, 0, 0, ?, ?)
            RETURNING id;
            """,
            (
                player_id,
                planet_id,
                now + 3600,
                now + 7200,
                now,
                str(HUGE + 3),
                str(HUGE + 4),
            ),
        ).fetchone()
        target_id = int(target["id"])

        conn.execute(
            "UPDATE planets SET metal = 0, crystal = 0 WHERE id = ?;",
            (planet_id,),
        )
        conn.commit()

        assert get_planet_ships(planet_id, conn=conn)["spark_drone"] == HUGE
        assert get_planet_defense(planet_id, conn=conn)["slug_launcher"] == HUGE + 1

        row = conn.execute(
            "SELECT amount FROM shipyard_queue WHERE id = ?;",
            (ship_job_id,),
        ).fetchone()
        assert int(row["amount"]) == HUGE + 2

        ok_cancel, reason_cancel = cancel_troop_job(
            player_id,
            target_id,
            conn=conn,
        )
        assert ok_cancel, reason_cancel
        conn.commit()

        balances = conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ?;",
            (planet_id,),
        ).fetchone()
        assert int(balances["metal"]) == HUGE + 3
        assert int(balances["crystal"]) == HUGE + 4
    finally:
        conn.close()
        close_pg_pool()
