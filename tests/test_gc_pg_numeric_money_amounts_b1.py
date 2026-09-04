"""P0-B1 PostgreSQL exact auction + alliance money contract."""

from __future__ import annotations

import time
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path

from tests.pg_fixtures import close_pg_pool, requires_postgres

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "166_pg_money_amounts_numeric.sql"

HUGE = 10**30 + 987_654_321


def test_pg_money_amounts_migration_is_unbounded_numeric():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- GC-BACKEND: postgres" in sql
    for token in (
        "auction_house_listings\n    ALTER COLUMN start_price TYPE NUMERIC",
        "auction_house_listings\n    ALTER COLUMN current_bid TYPE NUMERIC",
        "auction_house_bids\n    ALTER COLUMN amount TYPE NUMERIC",
        "alliances\n    ALTER COLUMN pool_metal TYPE NUMERIC",
        "alliances\n    ALTER COLUMN pool_crystal TYPE NUMERIC",
        "alliances\n    ALTER COLUMN pool_fuel_cells TYPE NUMERIC",
        "alliance_donations\n    ALTER COLUMN amount TYPE NUMERIC",
        "alliance_projects\n    ALTER COLUMN cost_metal TYPE NUMERIC",
        "alliance_projects\n    ALTER COLUMN cost_crystal TYPE NUMERIC",
        "alliance_projects\n    ALTER COLUMN cost_fuel_cells TYPE NUMERIC",
    ):
        assert token in sql
    assert "NUMERIC(" not in sql


def test_auction_min_bid_is_exact_above_i64():
    from game.auction_house import MIN_BID_INCREASE_BPS, _min_next_bid

    current = HUGE
    expected = (
        current * (10_000 + MIN_BID_INCREASE_BPS) + 9_999
    ) // 10_000
    got = _min_next_bid({"start_price": 1, "current_bid": current})
    assert got == expected


def test_alliance_cost_and_pool_cap_math_is_exact_above_i64():
    from game.alliance_catalog import _scale_cost, pool_cap_from_projects

    base = {
        "metal": HUGE,
        "crystal": HUGE + 1,
        "fuel_cells": HUGE + 2,
    }
    factor = 1.75
    level = 7
    got = _scale_cost(base, factor, level)

    with localcontext() as ctx:
        ctx.prec = 160
        mult = Decimal(str(factor)) ** (level - 1)
        expected = {
            key: int(
                (Decimal(value) * mult).to_integral_value(
                    rounding=ROUND_HALF_EVEN
                )
            )
            for key, value in base.items()
        }
    assert got == expected

    available = [
        {"cost": base},
        {
            "cost": {
                "metal": HUGE + 10,
                "crystal": HUGE + 20,
                "fuel_cells": HUGE + 30,
            }
        },
    ]
    cap = pool_cap_from_projects(available, cap_bonus_pct=0.25)
    raw = {
        "metal": HUGE + HUGE + 10,
        "crystal": HUGE + 1 + HUGE + 20,
        "fuel_cells": HUGE + 2 + HUGE + 30,
    }
    with localcontext() as ctx:
        ctx.prec = 160
        expected_cap = {
            key: int(
                (Decimal(value) * Decimal("1.25")).to_integral_value(
                    rounding=ROUND_HALF_EVEN
                )
            )
            for key, value in raw.items()
        }
    assert cap == expected_cap


def test_money_runtime_blocks_authoritative_float_paths():
    auction = (ROOT / "game" / "auction_house.py").read_text(encoding="utf-8")
    alliance = (ROOT / "game" / "alliance.py").read_text(encoding="utf-8")
    catalog = (ROOT / "game" / "alliance_catalog.py").read_text(encoding="utf-8")

    for token in (
        "current * (1.0 + MIN_BID_INCREASE_PCT)",
        "(int(amount), int(planet_id))",
        "(box_key, currency, start_price, now_i",
        "(bid_amount, int(player_id), int(planet_id), int(listing_id))",
    ):
        assert token not in auction

    for token in (
        "float(fuel_cells),",
        "(amt, _now(), aid)",
        "(aid, int(player_id), res, amt, int(xp_grant)",
        'int(cost["metal"]),\n                int(cost["crystal"])',
    ):
        assert token not in alliance

    assert "float(factor) **" not in catalog
    assert "int(round(v * bonus))" not in catalog


@requires_postgres
def test_live_postgres_money_roundtrip_above_i64(pg_parity_db, monkeypatch):
    from migrate import main as migrate_main

    migrate_main()

    from game import alliance as alliance_mod
    from game.alliance import _deduct_pool, create_alliance, donate_to_alliance
    from game.auction_house import place_bid
    from game.db import db
    from game.models import (
        create_user,
        get_homeworld,
        resource_db_param,
        save_planet,
    )

    username = f"PgNumericB1{int(time.time() * 1000) % 10_000_000}"
    ok, reason, user = create_user(username, "Pass!NumericB1xx99")
    assert ok and user, reason
    player_id = int(user["id"])

    planet = dict(get_homeworld(player_id))
    planet_id = int(planet["id"])
    planet["metal"] = HUGE * 3
    planet["crystal"] = HUGE * 3
    planet["fuel_cells"] = HUGE * 3
    save_planet(planet)

    conn = db()
    try:
        expected_columns = {
            ("auction_house_listings", "start_price"),
            ("auction_house_listings", "current_bid"),
            ("auction_house_bids", "amount"),
            ("alliances", "pool_metal"),
            ("alliances", "pool_crystal"),
            ("alliances", "pool_fuel_cells"),
            ("alliance_donations", "amount"),
            ("alliance_projects", "cost_metal"),
            ("alliance_projects", "cost_crystal"),
            ("alliance_projects", "cost_fuel_cells"),
        }
        rows = conn.execute(
            """
            SELECT table_name, column_name, data_type, numeric_precision
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND (
                (table_name = 'auction_house_listings' AND column_name IN ('start_price','current_bid'))
                OR (table_name = 'auction_house_bids' AND column_name = 'amount')
                OR (table_name = 'alliances' AND column_name IN ('pool_metal','pool_crystal','pool_fuel_cells'))
                OR (table_name = 'alliance_donations' AND column_name = 'amount')
                OR (table_name = 'alliance_projects' AND column_name IN ('cost_metal','cost_crystal','cost_fuel_cells'))
              );
            """
        ).fetchall()
        seen = set()
        for row in rows:
            key = (str(row["table_name"]), str(row["column_name"]))
            seen.add(key)
            assert str(row["data_type"]).lower() == "numeric"
            assert row["numeric_precision"] is None
        assert seen == expected_columns

        now = int(time.time())
        listing = conn.execute(
            """
            INSERT INTO auction_house_listings (
                box_key, currency, start_price, current_bid,
                starts_at, ends_at, status, created_at
            ) VALUES (?, 'metal', ?, 0, ?, ?, 'active', ?)
            RETURNING id;
            """,
            (
                "generic_supply_container",
                resource_db_param(HUGE - 10),
                now,
                now + 3600,
                now,
            ),
        ).fetchone()
        listing_id = int(listing["id"])
        conn.commit()

        ok_bid, reason_bid, _ = place_bid(
            player_id=player_id,
            planet_id=planet_id,
            listing_id=listing_id,
            amount=HUGE,
            currency="metal",
            conn=conn,
        )
        assert ok_bid, reason_bid

        row = conn.execute(
            "SELECT current_bid FROM auction_house_listings WHERE id = ?;",
            (listing_id,),
        ).fetchone()
        assert int(row["current_bid"]) == HUGE
        row = conn.execute(
            "SELECT amount FROM auction_house_bids WHERE listing_id = ?;",
            (listing_id,),
        ).fetchone()
        assert int(row["amount"]) == HUGE
        row = conn.execute(
            "SELECT metal FROM planets WHERE id = ?;",
            (planet_id,),
        ).fetchone()
        assert int(row["metal"]) == HUGE * 2

        ally = create_alliance(
            "NB1",
            "Numeric B1",
            player_id,
            conn=conn,
        )
        alliance_id = int(ally["id"])

        monkeypatch.setattr(
            alliance_mod,
            "_pool_snapshot",
            lambda *_args, **_kwargs: {
                "pool": {"metal": 0, "crystal": 0, "fuel_cells": 0},
                "cap": {
                    "metal": HUGE * 2,
                    "crystal": HUGE * 2,
                    "fuel_cells": HUGE * 2,
                },
                "cap_bonus_pct": 0,
            },
        )

        donate_to_alliance(
            player_id,
            "crystal",
            HUGE,
            conn=conn,
        )

        row = conn.execute(
            "SELECT pool_crystal FROM alliances WHERE id = ?;",
            (alliance_id,),
        ).fetchone()
        assert int(row["pool_crystal"]) == HUGE
        row = conn.execute(
            """
            SELECT amount
            FROM alliance_donations
            WHERE alliance_id = ? AND player_id = ?
            ORDER BY id DESC
            LIMIT 1;
            """,
            (alliance_id, player_id),
        ).fetchone()
        assert int(row["amount"]) == HUGE

        row = conn.execute(
            "SELECT crystal FROM planets WHERE id = ?;",
            (planet_id,),
        ).fetchone()
        assert int(row["crystal"]) == HUGE * 2

        _deduct_pool(
            conn,
            alliance_id,
            {"metal": 0, "crystal": HUGE // 2, "fuel_cells": 0},
        )
        conn.commit()
        row = conn.execute(
            "SELECT pool_crystal FROM alliances WHERE id = ?;",
            (alliance_id,),
        ).fetchone()
        assert int(row["pool_crystal"]) == HUGE - (HUGE // 2)

        conn.execute(
            """
            INSERT INTO alliance_projects (
                alliance_id, project_kind, target_key, target_level, status,
                started_at, finish_at, cost_metal, cost_crystal,
                cost_fuel_cells, created_by
            ) VALUES (?, 'building', 'numeric_probe', 1, 'completed',
                      ?, ?, ?, ?, ?, ?);
            """,
            (
                alliance_id,
                now,
                now,
                resource_db_param(HUGE + 1),
                resource_db_param(HUGE + 2),
                resource_db_param(HUGE + 3),
                player_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT cost_metal, cost_crystal, cost_fuel_cells
            FROM alliance_projects
            WHERE alliance_id = ? AND target_key = 'numeric_probe';
            """,
            (alliance_id,),
        ).fetchone()
        assert (
            int(row["cost_metal"]),
            int(row["cost_crystal"]),
            int(row["cost_fuel_cells"]),
        ) == (HUGE + 1, HUGE + 2, HUGE + 3)
    finally:
        conn.close()
        close_pg_pool()
