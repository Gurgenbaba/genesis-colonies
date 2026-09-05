"""Unbounded runtime arithmetic contract for Planet Evolution special resources."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path

from game.exact_math import decimal_text, decimal_value
from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400


def test_decimal_text_keeps_values_beyond_ieee754_range():
    assert decimal_value(HUGE) == Decimal(HUGE)
    assert decimal_text(HUGE) == str(HUGE)
    assert decimal_text("1e400") == "1" + ("0" * 400)


def test_pe_special_resource_owners_have_no_balance_float_binds():
    ascension = (
        ROOT / "game" / "planet_evolution" / "ascension.py"
    ).read_text(encoding="utf-8")
    events = (
        ROOT / "game" / "planet_evolution" / "events.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        'float(row["amount"] or 0)',
        "float(amount)",
        "SET amount = amount - ?",
    ):
        assert forbidden not in ascension

    assert 'decimal_value(row["amount"] if row else 0)' in ascension
    assert "amount - CAST(? AS NUMERIC)" in ascension
    assert "amount >= CAST(? AS NUMERIC)" in ascension

    assert "(float(amount), int(planet_id), str(res_key))" not in events
    assert "amount + CAST(? AS NUMERIC)" in events
    assert "decimal_text(amount)" in events


@requires_postgres
def test_live_postgres_pe_ascension_and_event_amounts_are_exact(pg_parity_db, monkeypatch):
    from migrate import main as migrate_main

    migrate_main()

    from game.db import begin_write_transaction, commit, db
    from game.models import create_user, get_homeworld
    from game.planet_evolution import ascension as ascension_module
    from game.planet_evolution import events as events_module
    from game.planet_evolution.economy import ensure_special_resource_row

    username = f"PgNumericPERuntime{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericPERuntime99")
    assert ok and user, reason
    player_id = int(user["id"])
    planet_id = int(get_homeworld(player_id)["id"])

    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            "UPDATE planets SET planet_level = 25 WHERE id = ?;",
            (planet_id,),
        )
        ensure_special_resource_row(planet_id, "quantum_data", conn)
        conn.execute(
            """
            UPDATE planet_special_resources
            SET amount = CAST(? AS NUMERIC),
                cap = CAST(? AS NUMERIC)
            WHERE planet_id = ? AND resource_key = 'quantum_data';
            """,
            (str(HUGE * 3), str(HUGE * 5), planet_id),
        )
        commit(conn)

        definition = {
            "ascension_key": "numeric_probe",
            "label_key": "numeric_probe",
            "duration_days": 1,
            "requirements": {
                "cost": {
                    "quantum_data": str(HUGE),
                }
            },
        }
        monkeypatch.setattr(
            ascension_module,
            "get_ascension",
            lambda key: definition if str(key) == "numeric_probe" else None,
        )
        monkeypatch.setattr(
            ascension_module,
            "check_requirements",
            lambda planet_id, req, conn: (True, []),
        )

        eligible, missing = ascension_module.check_ascension_requirements(
            planet_id,
            "numeric_probe",
            conn,
        )
        assert eligible, missing

        started, start_reason, _ = ascension_module.start_ascension(
            planet_id,
            "numeric_probe",
            conn=conn,
        )
        assert started, start_reason

        row = conn.execute(
            """
            SELECT amount
            FROM planet_special_resources
            WHERE planet_id = ? AND resource_key = 'quantum_data';
            """,
            (planet_id,),
        ).fetchone()
        assert Decimal(row["amount"]) == Decimal(HUGE * 2)

        monkeypatch.setattr(
            events_module,
            "compile_planet_mechanics",
            lambda planet_id, conn: {},
        )
        begin_write_transaction(conn)
        events_module.PlanetEventEngine._apply_outcome(
            conn,
            planet_id,
            {"grant_special_resource": {"quantum_data": str(HUGE)}},
            "numeric_probe_event",
            {},
        )
        commit(conn)

        row = conn.execute(
            """
            SELECT amount
            FROM planet_special_resources
            WHERE planet_id = ? AND resource_key = 'quantum_data';
            """,
            (planet_id,),
        ).fetchone()
        assert Decimal(row["amount"]) == Decimal(HUGE * 3)
    finally:
        conn.close()
        close_pg_pool()
