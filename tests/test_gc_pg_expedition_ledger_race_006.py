"""GC-PERF-EXPO-RACE-006 — PostgreSQL duplicate expedition ledger claim is race-safe."""

from __future__ import annotations

import threading
import time

import pytest

from game.db import begin_write_transaction, commit, db, get_db_backend, rollback
from game.expedition_events import (
    expedition_daily_day_bucket,
    record_expedition_daily_value,
)


@pytest.mark.skipif(get_db_backend() != "postgres", reason="PostgreSQL concurrency contract")
def test_concurrent_duplicate_expedition_daily_record_is_exactly_once():
    movement_id = 9_006_000_000 + int(time.time() * 1000) % 1_000_000
    player_id = 8_006_000_000 + int(time.time() * 1000) % 1_000_000
    ts = float(time.time())
    bucket = expedition_daily_day_bucket(ts)
    value = 987_654_321

    barrier = threading.Barrier(2)
    results: list[bool] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def worker() -> None:
        conn = db()
        try:
            begin_write_transaction(conn)
            barrier.wait(timeout=10)
            inserted = record_expedition_daily_value(
                player_id,
                movement_id,
                value,
                conn=conn,
                ts=ts,
            )
            commit(conn)
            with guard:
                results.append(bool(inserted))
        except BaseException as exc:  # pragma: no cover - surfaced below
            try:
                rollback(conn)
            except Exception:
                pass
            with guard:
                errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads), "ledger race deadlocked"
    assert errors == []
    assert sorted(results) == [False, True]

    conn = db()
    try:
        row = conn.execute(
            """
            SELECT expo_value_total, expedition_count
            FROM expedition_daily_value
            WHERE player_id = ? AND day_bucket = ?;
            """,
            (player_id, bucket),
        ).fetchone()
        assert row is not None
        assert int(row["expo_value_total"]) == value
        assert int(row["expedition_count"]) == 1

        ledger = conn.execute(
            """
            SELECT COUNT(*) AS c, MAX(expo_value) AS expo_value
            FROM expedition_daily_recorded
            WHERE movement_id = ?;
            """,
            (movement_id,),
        ).fetchone()
        assert int(ledger["c"]) == 1
        assert int(ledger["expo_value"]) == value
    finally:
        # Unique synthetic ids make cleanup optional, but keep the shared CI DB tidy.
        try:
            begin_write_transaction(conn)
            conn.execute(
                "DELETE FROM expedition_daily_recorded WHERE movement_id = ?;",
                (movement_id,),
            )
            conn.execute(
                "DELETE FROM expedition_daily_value WHERE player_id = ? AND day_bucket = ?;",
                (player_id, bucket),
            )
            commit(conn)
        except Exception:
            try:
                rollback(conn)
            except Exception:
                pass
        conn.close()
