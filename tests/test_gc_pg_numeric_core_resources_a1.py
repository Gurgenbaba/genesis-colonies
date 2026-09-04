"""P0-A1 PostgreSQL exact core-resource contract."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "164_pg_core_resource_numeric.sql"

HUGE_OVER_I64 = 10**30 + 987_654_321
HUGE_OVER_JS_SAFE = 9_007_199_254_740_993


def test_pg_core_resource_migration_is_backend_scoped_and_unbounded_numeric():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    for token in (
        "planets ALTER COLUMN metal TYPE NUMERIC",
        "planets ALTER COLUMN crystal TYPE NUMERIC",
        "planets ALTER COLUMN fuel_cells TYPE NUMERIC",
        "planets ALTER COLUMN fuel_exchange_daily_used TYPE NUMERIC",
        "players ALTER COLUMN exchange_daily_used TYPE NUMERIC",
        "exchange_log ALTER COLUMN give_amount TYPE NUMERIC",
        "exchange_log ALTER COLUMN receive_amount TYPE NUMERIC",
    ):
        assert token in sql
    assert "NUMERIC(" not in sql


def test_backend_scoped_migration_skips_cleanly_on_sqlite(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    from migrate import apply_migration, ensure_migration_history_table, get_applied_migrations

    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        ensure_migration_history_table(conn)
        filename = "999_pg_only_probe.sql"
        apply_migration(
            conn,
            filename,
            "-- GC-BACKEND: postgres\nTHIS WOULD NOT PARSE ON SQLITE;",
        )
        assert filename in get_applied_migrations(conn)
    finally:
        conn.close()


def test_postgres_resource_param_keeps_python_int_above_i64(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    from game.models import resource_db_param

    value = HUGE_OVER_I64
    bound = resource_db_param(value)
    assert isinstance(bound, int)
    assert bound == value


def test_exchange_preview_is_exact_above_i64():
    from game.exchange import _preview_receive

    cfg = {
        "rate_metal_to_crystal": 1.5,
        "rate_crystal_to_metal": 1.0,
        "fuel_metal_per_unit": 3.0,
        "fuel_crystal_per_unit": 2.0,
    }
    give = HUGE_OVER_I64
    assert _preview_receive("metal", "crystal", give, cfg) == (give * 2) // 3
    assert _preview_receive("metal", "fuel_cells", give, cfg) == give // 3
    assert _preview_receive("fuel_cells", "metal", give, cfg) == give * 3


def test_plunder_pool_is_exact_above_js_safe_integer():
    from game.resources import calculate_plunder_pool

    stock = {
        "metal": HUGE_OVER_JS_SAFE,
        "crystal": HUGE_OVER_I64,
        "fuel_cells": HUGE_OVER_I64 + 2,
    }
    pool = calculate_plunder_pool(stock, plunder_fraction=0.5)
    assert pool["metal"] == HUGE_OVER_JS_SAFE // 2
    assert pool["crystal"] == HUGE_OVER_I64 // 2
    assert pool["fuel_cells"] == (HUGE_OVER_I64 + 2) // 2


@requires_postgres
def test_live_postgres_numeric_resource_roundtrip_above_i64(pg_parity_db):
    # Re-run migrate so a reused parity database also receives newly-added 164.
    from migrate import main as migrate_main

    migrate_main()

    from game.db import db
    from game.models import create_user, get_homeworld, save_planet, try_spend_resources

    username = f"PgNumericA1{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericA1xx99")
    assert ok and user, reason
    player_id = int(user["id"])

    planet = dict(get_homeworld(player_id))
    planet_id = int(planet["id"])
    planet["metal"] = HUGE_OVER_I64
    planet["crystal"] = HUGE_OVER_I64 + 1
    planet["fuel_cells"] = HUGE_OVER_I64 + 2
    save_planet(planet)

    conn = db()
    try:
        row = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
            (planet_id,),
        ).fetchone()
        assert int(row["metal"]) == HUGE_OVER_I64
        assert int(row["crystal"]) == HUGE_OVER_I64 + 1
        assert int(row["fuel_cells"]) == HUGE_OVER_I64 + 2

        policies = {
            ("planets", "metal"),
            ("planets", "crystal"),
            ("planets", "fuel_cells"),
            ("planets", "fuel_exchange_daily_used"),
            ("players", "exchange_daily_used"),
            ("exchange_log", "give_amount"),
            ("exchange_log", "receive_amount"),
        }
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type, numeric_precision
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'planets' AND column_name IN ('metal','crystal','fuel_cells','fuel_exchange_daily_used'))
                OR (table_name = 'players' AND column_name = 'exchange_daily_used')
                OR (table_name = 'exchange_log' AND column_name IN ('give_amount','receive_amount'))
              );
            """
        ).fetchall()
        seen = set()
        for meta in rows:
            key = (str(meta["table_name"]), str(meta["column_name"]))
            seen.add(key)
            assert str(meta["data_type"]).lower() == "numeric"
            assert meta["numeric_precision"] is None
        assert seen == policies
    finally:
        conn.close()

    spend = 10**20 + 17
    assert try_spend_resources(planet_id, spend, 0)
    conn = db()
    try:
        row = conn.execute("SELECT metal FROM planets WHERE id = ?;", (planet_id,)).fetchone()
        assert int(row["metal"]) == HUGE_OVER_I64 - spend
    finally:
        conn.close()
        close_pg_pool()
