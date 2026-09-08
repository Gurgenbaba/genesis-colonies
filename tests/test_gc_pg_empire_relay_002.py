"""GC-MANDO-RELAY-002 PostgreSQL parity: exact NUMERIC relay + independent direction cooldowns."""

from __future__ import annotations

import time

from tests.pg_fixtures import close_pg_pool, requires_postgres


@requires_postgres
def test_postgres_relay_preserves_huge_numeric_and_direction_cooldowns(pg_parity_db):
    from game.db import begin_write_transaction, commit, db
    from game.empire_relay import (
        RELAY_COOLDOWN_SECONDS,
        collect_empire_resources,
        distribute_empire_resources,
    )
    from tests.test_fleet_logistics import _hub_and_sources, _player

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    now = int(time.time())
    huge = 10**40 + 123_456_789

    conn.execute(
        """
        UPDATE planets
        SET metal = CAST(? AS NUMERIC),
            crystal = CAST(0 AS NUMERIC),
            fuel_cells = CAST(0 AS NUMERIC),
            last_update = ?
        WHERE id = ?;
        """,
        (str(100), float(now + 3600), int(hub)),
    )
    for source in sources:
        conn.execute(
            """
            UPDATE planets
            SET metal = CAST(? AS NUMERIC),
                crystal = CAST(? AS NUMERIC),
                fuel_cells = CAST(? AS NUMERIC),
                last_update = ?
            WHERE id = ?;
            """,
            (str(huge), str(huge + 1), str(huge + 2), float(now + 3600), int(source)),
        )
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, collected = collect_empire_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        conn=conn,
        now=now,
    )
    assert ok, reason
    commit(conn)

    assert int(collected["moved"]["metal"]) == huge * 2
    row = conn.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
        (hub,),
    ).fetchone()
    assert int(row["metal"]) == 100 + huge * 2
    assert int(row["crystal"]) == (huge + 1) * 2
    assert int(row["fuel_cells"]) == (huge + 2) * 2

    # Collect cooldown is source-owned and direction-specific. The same planets
    # may immediately receive distribution from the hub.
    distribute_total = {"metal": huge, "crystal": huge, "fuel_cells": huge}
    begin_write_transaction(conn)
    ok2, reason2, distributed = distribute_empire_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=sources,
        resources=distribute_total,
        conn=conn,
        now=now + 1,
    )
    assert ok2, reason2
    commit(conn)

    assert distributed["processed_count"] == 2
    assert int(distributed["debited"]["metal"]) == huge
    for source in sources:
        cooldowns = conn.execute(
            """
            SELECT direction, ready_at
            FROM empire_resource_relay_cooldowns
            WHERE player_id = ? AND planet_id = ?
            ORDER BY direction;
            """,
            (uid, int(source)),
        ).fetchall()
        by_direction = {str(r["direction"]): int(r["ready_at"]) for r in cooldowns}
        assert by_direction["collect"] == now + RELAY_COOLDOWN_SECONDS
        assert by_direction["distribute"] == now + 1 + RELAY_COOLDOWN_SECONDS
        stock = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
            (int(source),),
        ).fetchone()
        assert int(stock["metal"]) == huge // 2
        assert int(stock["crystal"]) == huge // 2
        assert int(stock["fuel_cells"]) == huge // 2

    meta = conn.execute(
        """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'empire_resource_relay_cooldowns'
          AND column_name = 'ready_at';
        """
    ).fetchone()
    assert str(meta["data_type"]).lower() == "bigint"

    conn.close()
    close_pg_pool()
