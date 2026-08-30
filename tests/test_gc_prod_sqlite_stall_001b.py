"""GC-PROD-SQLITE-STALL-001B — fleet worker RUN budget (not single-TX hold)."""

from __future__ import annotations

import time

from game.db import begin_write_transaction, commit, db
from game.fleet import process_fleet_tick

pytest_plugins = ["tests.test_game_state_live"]


def _insert_due_outbound(uid: int, n: int) -> list[int]:
    import json

    conn = db()
    ids = []
    try:
        planet = conn.execute(
            "SELECT id, galaxy, system, position FROM planets WHERE player_id = ? LIMIT 1;",
            (int(uid),),
        ).fetchone()
        assert planet is not None
        now = time.time()
        begin_write_transaction(conn)
        for _i in range(n):
            cur = conn.execute(
                """
                INSERT INTO fleet_movements (
                    player_id, origin_planet_id,
                    target_galaxy, target_system, target_position,
                    mission_type, status, ships_json, resources_json,
                    fuel_cost, speed_percent, distance, flight_seconds,
                    departure_at, arrival_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'transport', 'outbound', ?, '{}',
                          0, 100, 1, 60, ?, ?, ?, ?);
                """,
                (
                    int(uid),
                    int(planet["id"]),
                    int(planet["galaxy"] or 1),
                    int(planet["system"] or 1),
                    (int(planet["position"] or 1) % 14) + 1,
                    json.dumps({"falcon_interceptor": 1}),
                    now - 120,
                    now - 10,
                    now,
                    now,
                ),
            )
            ids.append(int(cur.lastrowid))
        commit(conn)
        return ids
    finally:
        conn.close()


def test_fleet_worker_run_budget_defers_remainder(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_FLEET_WORKER_MAX_MOVEMENTS", "3")
    monkeypatch.setenv("GC_FLEET_WORKER_MAX_MS", "60000")
    ids = _insert_due_outbound(int(uid), 8)
    assert len(ids) == 8

    conn = db()
    try:
        result = process_fleet_tick(
            player_id=int(uid), conn=conn, manage_transaction=True
        )
    finally:
        conn.close()

    budget = result.get("budget") or {}
    assert int(budget.get("started") or 0) == 3
    assert int(budget.get("deferred") or 0) >= 5
    assert budget.get("hit_limit") is True

    # Remainder still due for next tick — not permanently starved
    conn = db()
    try:
        remaining = conn.execute(
            """
            SELECT COUNT(*) AS c FROM fleet_movements
            WHERE player_id = ? AND status = 'outbound' AND id IN ({})
            """.format(
                ",".join("?" * len(ids))
            ),
            (int(uid), *ids),
        ).fetchone()
        assert int(remaining["c"]) >= 5
    finally:
        conn.close()
