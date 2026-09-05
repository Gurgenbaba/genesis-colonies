"""Final literal no-max PostgreSQL gameplay numeric contract."""

from __future__ import annotations

import time
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "173_pg_p1_final_no_max_numeric.sql"

HUGE = 10**30 + 314_159_265_358_979
HUGE_2 = 10**30 + 271_828_182_845_904

FINAL_NO_MAX_COLUMNS = {
    ("defense_queue", "amount"),
    ("planet_troops", "amount"),
    ("troop_queue", "amount"),
    ("expedition_daily_value", "expo_value_total"),
    ("expedition_daily_recorded", "expo_value"),
    ("pirate_intel", "resources_score"),
    ("pirate_intel", "fleet_score"),
    ("pirate_intel", "defense_score"),
    ("chronicle_entries", "score_value"),
    ("planet_shipyard_ascension", "hull_mass_progress"),
}


def test_final_no_max_migration_uses_unconstrained_numeric():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    assert "NUMERIC(" not in sql

    for table, column in FINAL_NO_MAX_COLUMNS:
        assert f"ALTER TABLE {table}" in sql
        assert f"ALTER COLUMN {column} TYPE NUMERIC" in sql


def test_numeric_readiness_requires_no_max_for_gameplay_growth():
    source = (ROOT / "scripts" / "pg_numeric_readiness_audit.py").read_text(
        encoding="utf-8"
    )

    for table, column in (
        ("defense_queue", "amount"),
        ("planet_troops", "amount"),
        ("troop_queue", "amount"),
        ("world_boss_events", "current_hp"),
        ("world_boss_contributions", "damage"),
        ("expedition_daily_value", "expo_value_total"),
        ("pirate_intel", "resources_score"),
        ("chronicle_entries", "score_value"),
        ("planet_shipyard_ascension", "hull_mass_progress"),
    ):
        needle = f'NumericPolicy("{table}", "{column}", "exact_unbounded"'
        assert needle in source


def test_i64_bootstrap_list_no_longer_owns_no_max_gameplay_columns():
    source = (ROOT / "game" / "schema_bootstrap.py").read_text(encoding="utf-8")

    for table, column in FINAL_NO_MAX_COLUMNS:
        assert f'("{table}", "{column}")' not in source


@requires_postgres
def test_live_postgres_final_no_max_roundtrips_through_runtime_owners(pg_parity_db):
    from migrate import main as migrate_main

    migrate_main()

    from game.chronicle_entries import (
        ENTRY_TYPE_WORLD_BOSS,
        record_chronicle_for_fleet_report,
    )
    from game.db import db
    from game.expedition_events import (
        expedition_daily_day_bucket,
        get_expedition_daily_expo_value,
        record_expedition_daily_value,
    )
    from game.models import create_user, get_homeworld
    from game.pirates.brain import _write_intel
    from game.stellar_forge.service import (
        get_raw_state,
        record_hull_mass_delivery,
    )

    username = f"PgNumericFinal{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericFinalxx99")
    assert ok and user, reason
    player_id = int(user["id"])
    planet = get_homeworld(player_id)
    planet_id = int(planet["id"])

    conn = db()
    try:
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type, numeric_precision
            FROM information_schema.columns
            WHERE table_schema = current_schema();
            """
        ).fetchall()
        meta = {
            (str(row["table_name"]), str(row["column_name"])): row
            for row in rows
        }
        for key in FINAL_NO_MAX_COLUMNS:
            row = meta[key]
            assert str(row["data_type"]).lower() == "numeric"
            assert row["numeric_precision"] is None

        now = time.time()

        # Expedition aggregate owner: exact add + idempotent movement ledger.
        assert record_expedition_daily_value(
            player_id,
            910_001,
            HUGE,
            conn=conn,
            ts=now,
        )
        assert record_expedition_daily_value(
            player_id,
            910_002,
            HUGE_2,
            conn=conn,
            ts=now,
        )
        assert not record_expedition_daily_value(
            player_id,
            910_002,
            HUGE_2,
            conn=conn,
            ts=now,
        )
        bucket = expedition_daily_day_bucket(now)
        assert get_expedition_daily_expo_value(
            player_id,
            conn=conn,
            ts=now,
        ) == HUGE + HUGE_2

        recorded = conn.execute(
            """
            SELECT expo_value FROM expedition_daily_recorded
            WHERE movement_id = ?;
            """,
            (910_001,),
        ).fetchone()
        assert int(recorded["expo_value"]) == HUGE

        # Pirate intel runtime owner accepts no-max score inputs without float.
        _write_intel(
            conn,
            bot_player_id=player_id,
            target_planet_id=planet_id,
            target_player_id=player_id,
            galaxy=int(planet.get("galaxy") or 1),
            system=int(planet.get("system") or 1),
            position=int(planet.get("position") or 1),
            resources_score=HUGE,
            fleet_score=HUGE_2,
            defense_score=HUGE + HUGE_2,
            opportunity=77,
            now=now,
        )
        intel = conn.execute(
            """
            SELECT resources_score, fleet_score, defense_score
            FROM pirate_intel
            WHERE bot_player_id = ? AND target_planet_id = ?;
            """,
            (player_id, planet_id),
        ).fetchone()
        assert int(intel["resources_score"]) == HUGE
        assert int(intel["fleet_score"]) == HUGE_2
        assert int(intel["defense_score"]) == HUGE + HUGE_2

        # Chronicle score owner persists huge combat/world-boss values exactly.
        assert record_chronicle_for_fleet_report(
            player_id=player_id,
            entry_type=ENTRY_TYPE_WORLD_BOSS,
            subject="numeric-final",
            metadata={"fleet_id": 910_003, "damage": HUGE + 17},
            occurred_at=int(now),
            conn=conn,
        )
        chronicle = conn.execute(
            """
            SELECT score_value
            FROM chronicle_entries
            WHERE player_id = ? AND source_event_id = ?;
            """,
            (player_id, "world_boss:910003"),
        ).fetchone()
        assert int(chronicle["score_value"]) == HUGE + 17

        # Stellar Forge owner: make a campaign-active row and deliver an
        # absurdly large batch through the canonical hull-mass hook.
        conn.execute(
            """
            INSERT INTO planet_shipyard_ascension (
                planet_id, campaign_active, hull_mass_progress,
                hull_mass_by_role, manufacturing_roles,
                operational_protocols_done, updated_at
            ) VALUES (?, 1, 0, '{}', '[]', '{}', ?)
            ON CONFLICT(planet_id) DO UPDATE SET
                campaign_active = 1,
                hull_mass_progress = 0,
                hull_mass_by_role = '{}',
                manufacturing_roles = '[]',
                operational_protocols_done = '{}',
                updated_at = excluded.updated_at;
            """,
            (planet_id, now),
        )
        record_hull_mass_delivery(
            planet_id,
            "spark_drone",
            HUGE,
            conn=conn,
            now=now,
        )
        forge_state = get_raw_state(planet_id, conn=conn)
        assert int(forge_state["hull_mass_progress"]) > HUGE

        persisted = conn.execute(
            """
            SELECT hull_mass_progress
            FROM planet_shipyard_ascension
            WHERE planet_id = ?;
            """,
            (planet_id,),
        ).fetchone()
        assert int(persisted["hull_mass_progress"]) == int(
            forge_state["hull_mass_progress"]
        )

        conn.commit()
    finally:
        conn.close()
        close_pg_pool()
