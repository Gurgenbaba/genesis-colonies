"""P1-C exact Planet Evolution economic decimal contract."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "172_pg_p1_planet_economy_numeric.sql"

HUGE_RATE = Decimal("1000000000000000000000000000000.125")
HUGE_SPECIAL_RATE = Decimal("2000000000000000000000000000000.375")
SOURCE_METAL = Decimal("9000000000000000000000000000000.875")
SPECIAL_SOURCE = Decimal("8000000000000000000000000000000.625")
SPECIAL_CAP = Decimal("99999999999999999999999999999999.999")


def test_p1_planet_economy_migration_is_unbounded_numeric():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    assert "NUMERIC(" not in sql
    for token in (
        "planet_special_resources\n    ALTER COLUMN amount TYPE NUMERIC",
        "planet_special_resources\n    ALTER COLUMN cap TYPE NUMERIC",
        "planet_special_resources\n    ALTER COLUMN production_per_hour TYPE NUMERIC",
        "planet_special_resources\n    ALTER COLUMN consumption_per_hour TYPE NUMERIC",
        "planet_trade_routes\n    ALTER COLUMN amount_per_hour TYPE NUMERIC",
        "planet_import_demands\n    ALTER COLUMN required_per_hour TYPE NUMERIC",
        "pe_special_resource_definitions\n    ALTER COLUMN base_cap TYPE NUMERIC",
        "pe_production_chain_definitions\n    ALTER COLUMN base_output_per_hour TYPE NUMERIC",
    ):
        assert token in sql


def test_p1_planet_economy_runtime_has_no_balance_float_coercions():
    economy = (ROOT / "game" / "planet_evolution" / "economy.py").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "game" / "planet_evolution" / "service.py").read_text(
        encoding="utf-8"
    )
    mechanics = (ROOT / "game" / "planet_evolution" / "mechanics.py").read_text(
        encoding="utf-8"
    )
    audit = (ROOT / "scripts" / "pg_numeric_readiness_audit.py").read_text(
        encoding="utf-8"
    )

    for forbidden in (
        'float(prow["metal"]',
        'float(prow["crystal"]',
        'float(route["amount_per_hour"]',
        'float(row["amount"]',
        'float(row["cap"]',
        'float(demand["required_per_hour"]',
    ):
        assert forbidden not in economy

    assert "Decimal(str(amount_per_hour))" in service
    assert "float(amount_per_hour)" not in service
    assert "CAST(? AS NUMERIC)" in service
    assert 'Decimal(str(d.get("required_per_hour", 0)))' in mechanics
    assert 'float(d.get("required_per_hour", 0))' not in mechanics
    assert (
        'NumericPolicy("pe_special_resource_definitions", "base_cap", '
        '"exact_unbounded", "P1"'
    ) in audit
    assert (
        'NumericPolicy("pe_production_chain_definitions", '
        '"base_output_per_hour", "decimal_rate", "P1"'
    ) in audit


def test_p1_decimal_helpers_keep_fraction_beyond_i64():
    from game.planet_evolution.economy import _decimal_sql, _decimal_value

    assert _decimal_value(str(HUGE_RATE)) == HUGE_RATE
    assert Decimal(_decimal_sql(HUGE_RATE)) == HUGE_RATE


@requires_postgres
def test_live_postgres_planet_economy_roundtrip_and_transfer_is_exact(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.db import begin_write_transaction, commit, db
    from game.models import create_user, get_homeworld
    from game.planet_evolution.economy import (
        ensure_special_resource_row,
        process_trade_routes,
    )
    from game.planet_evolution.service import colonize_planet, create_trade_route

    username = f"PgNumericPEC{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericPECxx99")
    assert ok and user, reason
    player_id = int(user["id"])
    source_id = int(get_homeworld(player_id)["id"])

    ok_colony, reason_colony, extra = colonize_planet(
        player_id,
        name=f"NumericPE-{username[-5:]}",
        galaxy=1,
        allow_legacy_coordinates=True,
        source="test",
    )
    assert ok_colony and extra, reason_colony
    target_id = int(extra["planet_id"])

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type, numeric_precision
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'planet_special_resources'
                 AND column_name IN (
                    'amount','cap','production_per_hour','consumption_per_hour'
                 ))
                OR (table_name = 'planet_trade_routes'
                    AND column_name = 'amount_per_hour')
                OR (table_name = 'planet_import_demands'
                    AND column_name = 'required_per_hour')
                OR (table_name = 'pe_special_resource_definitions'
                    AND column_name = 'base_cap')
                OR (table_name = 'pe_production_chain_definitions'
                    AND column_name = 'base_output_per_hour')
              );
            """
        ).fetchall()
        expected_columns = {
            ("planet_special_resources", "amount"),
            ("planet_special_resources", "cap"),
            ("planet_special_resources", "production_per_hour"),
            ("planet_special_resources", "consumption_per_hour"),
            ("planet_trade_routes", "amount_per_hour"),
            ("planet_import_demands", "required_per_hour"),
            ("pe_special_resource_definitions", "base_cap"),
            ("pe_production_chain_definitions", "base_output_per_hour"),
        }
        seen = set()
        for row in rows:
            key = (str(row["table_name"]), str(row["column_name"]))
            seen.add(key)
            assert str(row["data_type"]).lower() == "numeric"
            assert row["numeric_precision"] is None
        assert seen == expected_columns

        ok_route, route_reason, _ = create_trade_route(
            player_id,
            source_id,
            target_id,
            "metal",
            str(HUGE_RATE),
            conn=conn,
        )
        assert ok_route, route_reason

        ok_special, special_reason, _ = create_trade_route(
            player_id,
            source_id,
            target_id,
            "quantum_data",
            str(HUGE_SPECIAL_RATE),
            conn=conn,
        )
        assert ok_special, special_reason

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE planets
            SET metal = CAST(? AS NUMERIC)
            WHERE id = ?;
            """,
            (format(SOURCE_METAL, "f"), source_id),
        )
        conn.execute(
            "UPDATE planets SET metal = 0 WHERE id = ?;",
            (target_id,),
        )
        ensure_special_resource_row(source_id, "quantum_data", conn)
        ensure_special_resource_row(target_id, "quantum_data", conn)
        conn.execute(
            """
            UPDATE planet_special_resources
            SET amount = CAST(? AS NUMERIC), cap = CAST(? AS NUMERIC)
            WHERE planet_id = ? AND resource_key = 'quantum_data';
            """,
            (
                format(SPECIAL_SOURCE, "f"),
                format(SPECIAL_CAP, "f"),
                source_id,
            ),
        )
        conn.execute(
            """
            UPDATE planet_special_resources
            SET amount = 0, cap = CAST(? AS NUMERIC)
            WHERE planet_id = ? AND resource_key = 'quantum_data';
            """,
            (format(SPECIAL_CAP, "f"), target_id),
        )
        commit(conn)

        begin_write_transaction(conn)
        result = process_trade_routes(source_id, Decimal("1"), conn)
        commit(conn)

        moved = {
            str(item["resource_key"]): Decimal(str(item["amount"]))
            for item in result["transfers"]
        }
        assert moved["metal"] == HUGE_RATE
        assert moved["quantum_data"] == HUGE_SPECIAL_RATE

        source = conn.execute(
            "SELECT metal FROM planets WHERE id = ?;",
            (source_id,),
        ).fetchone()
        target = conn.execute(
            "SELECT metal FROM planets WHERE id = ?;",
            (target_id,),
        ).fetchone()
        assert Decimal(source["metal"]) == SOURCE_METAL - HUGE_RATE
        assert Decimal(target["metal"]) == HUGE_RATE

        source_special = conn.execute(
            """
            SELECT amount FROM planet_special_resources
            WHERE planet_id = ? AND resource_key = 'quantum_data';
            """,
            (source_id,),
        ).fetchone()
        target_special = conn.execute(
            """
            SELECT amount FROM planet_special_resources
            WHERE planet_id = ? AND resource_key = 'quantum_data';
            """,
            (target_id,),
        ).fetchone()
        assert Decimal(source_special["amount"]) == (
            SPECIAL_SOURCE - HUGE_SPECIAL_RATE
        )
        assert Decimal(target_special["amount"]) == HUGE_SPECIAL_RATE
    finally:
        conn.close()
        close_pg_pool()
