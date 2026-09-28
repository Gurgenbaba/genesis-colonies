"""UNI1 2026-10-02 RC gate — five concurrent authenticated PostgreSQL sessions.

This test is intentionally test-only. It exercises the exact release code against
PostgreSQL with the same short pool timeout used in production. The regression
target is issue #142: authenticated traffic must not starve the pool, return 500,
or create an active-planet 409 storm.
"""

from __future__ import annotations

import importlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from tests.pg_fixtures import close_pg_pool, requires_postgres


PLAYERS = 5
ROUNDS = 3
READ_ROUTES = (
    "/api/game-state",
    "/overview",
    "/buildings",
    "/research",
    "/shipyard",
    "/fleet",
    "/galaxy",
    "/messages",
    "/trader-hub",
    "/inventory",
)


@requires_postgres
def test_uni1_rc_five_parallel_authenticated_sessions(pg_parity_db, monkeypatch):
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    monkeypatch.setenv("GC_PG_POOL_TIMEOUT", "3")
    monkeypatch.setenv("GC_PG_POOL_MAX", "10")
    monkeypatch.setenv("GC_PRESENCE_TOUCH_INTERVAL_SEC", "5")

    from game.bootstrap import bootstrap_application
    from game.models import create_user, get_homeworld

    bootstrap_application(skip_migration_check=True)

    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True

    password = "RcGate!Pass99xx"
    accounts: list[tuple[int, str, int]] = []
    for idx in range(PLAYERS):
        username = f"rcgate_{idx}_{uuid.uuid4().hex[:8]}"
        ok, reason, user = create_user(username, password)
        assert ok and user, reason
        player_id = int(user["id"])
        home = get_homeworld(player_id=player_id)
        assert home is not None
        accounts.append((player_id, username, int(home["id"])))

    barrier = threading.Barrier(PLAYERS)

    def run_player(account: tuple[int, str, int]) -> dict:
        player_id, username, home_id = account
        observed: list[tuple[str, int]] = []
        with app_module.app.test_client() as client:
            barrier.wait(timeout=10)

            login = client.post(
                "/login",
                data={"username": username, "password": password},
                follow_redirects=False,
            )
            assert login.status_code in (200, 302), (
                player_id,
                "login",
                login.status_code,
                login.get_data(as_text=True)[:500],
            )

            # Exercise the active-planet writer once per authenticated player.
            # There is no legitimate contention here: a 409 means the old launch
            # symptom reproduced under ordinary parallel traffic.
            switch = client.post(
                "/api/planets/active",
                json={
                    "planet_id": home_id,
                    "request_id": f"rcgate-{player_id}-{uuid.uuid4().hex}",
                },
            )
            observed.append(("/api/planets/active", switch.status_code))
            assert switch.status_code == 200, (
                player_id,
                "planet_switch",
                switch.status_code,
                switch.get_data(as_text=True)[:500],
            )
            switch_body = switch.get_json() or {}
            assert switch_body.get("ok") is True, (player_id, switch_body)

            for _ in range(ROUNDS):
                for route in READ_ROUTES:
                    resp = client.get(route)
                    observed.append((route, resp.status_code))
                    assert resp.status_code == 200, (
                        player_id,
                        route,
                        resp.status_code,
                        resp.get_data(as_text=True)[:500],
                    )

                galaxy = client.get("/api/galaxy/system?galaxy=1&system=1")
                observed.append(("/api/galaxy/system", galaxy.status_code))
                assert galaxy.status_code == 200, (
                    player_id,
                    "galaxy_api",
                    galaxy.status_code,
                    galaxy.get_data(as_text=True)[:500],
                )

        return {"player_id": player_id, "observed": observed}

    results = []
    with ThreadPoolExecutor(max_workers=PLAYERS) as executor:
        futures = [executor.submit(run_player, account) for account in accounts]
        for future in as_completed(futures, timeout=90):
            results.append(future.result())

    assert len(results) == PLAYERS
    statuses = [
        status
        for result in results
        for _route, status in result["observed"]
    ]
    assert 500 not in statuses
    assert 503 not in statuses
    assert 409 not in statuses

    # Presence is the specific #142 ownership cutover. Every successfully
    # authenticated player must have its canonical dedicated presence row.
    from game.db import db

    conn = db()
    try:
        ids = [player_id for player_id, _username, _home_id in accounts]
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT player_id, last_seen FROM player_presence "
            f"WHERE player_id IN ({placeholders});",
            tuple(ids),
        ).fetchall()
        found = {int(row["player_id"]) for row in rows}
        assert found == set(ids), (found, ids)
    finally:
        conn.close()
        close_pg_pool()
