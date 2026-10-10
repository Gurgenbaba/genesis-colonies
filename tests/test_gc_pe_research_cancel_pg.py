"""Planet research cancel on PostgreSQL: concurrent cancel / settle races.

Runs only with GC_TEST_POSTGRES_URL (see tests/pg_fixtures.py); skipped on SQLite.
"""
from __future__ import annotations

import threading
import time

from tests.pg_fixtures import requires_postgres

TECH = "industry_t1_automation"


def _player_with_job(name: str):
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.planet_evolution.bootstrap import ensure_planet_evolution
    from game.planet_evolution.planet_research import queue_planet_research

    ok, err, user = create_user(name, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        ensure_planet_evolution(pid, conn)
        conn.execute("UPDATE planets SET metal = 500000, crystal = 500000 WHERE id = ?;", (pid,))
        conn.execute("UPDATE planet_buildings SET research_lab = 5 WHERE planet_id = ?;", (pid,))
        conn.commit()
        ok, reason, extra = queue_planet_research(pid, TECH, player_id=uid, conn=conn)
        assert ok is True, reason
        job_id = int(extra["job_id"])
        conn.commit()
    finally:
        conn.close()
    return uid, pid, job_id


def _resources(pid: int):
    from game.db import db

    conn = db()
    try:
        row = conn.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,)).fetchone()
        return float(row["metal"]), float(row["crystal"])
    finally:
        conn.close()


def _level(pid: int) -> int:
    from game.db import db
    from game.planet_evolution.planet_research import get_planet_research_levels

    conn = db()
    try:
        return int(get_planet_research_levels(pid, conn=conn).get(TECH, 0))
    finally:
        conn.close()


def _queue_ids(pid: int):
    from game.db import db
    from game.planet_evolution.planet_research import get_planet_research_queue

    conn = db()
    try:
        return [int(r["id"]) for r in get_planet_research_queue(pid, conn=conn)]
    finally:
        conn.close()


def _run_parallel(fns):
    results = [None] * len(fns)
    errors = [None] * len(fns)
    barrier = threading.Barrier(len(fns))

    def runner(i, fn):
        try:
            barrier.wait(timeout=10)
            results[i] = fn()
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertions
            errors[i] = exc

    threads = [threading.Thread(target=runner, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not any(t.is_alive() for t in threads), "parallel cancel hung (lock not released)"
    return results, errors


@requires_postgres
def test_pg_parallel_double_cancel_refunds_exactly_once(pg_parity_db):
    from game.planet_evolution.planet_research import cancel_planet_research_job

    _uid, pid, job_id = _player_with_job("pgcancel_dbl")
    spent = _resources(pid)

    results, errors = _run_parallel(
        [lambda: cancel_planet_research_job(pid, job_id) for _ in range(4)]
    )
    assert errors == [None] * 4, errors
    assert sorted(r[0] for r in results) == [False, False, False, True], results
    assert {r[1] for r in results if not r[0]} == {"job_not_found"}

    after = _resources(pid)
    assert after[0] > spent[0] and after[1] > spent[1]
    assert after[0] <= 500000 and after[1] <= 500000  # refunded once, never above the original balance
    assert _queue_ids(pid) == []
    assert _level(pid) == 0  # cancelled, not completed


@requires_postgres
def test_pg_cancel_racing_completion_is_all_or_nothing(pg_parity_db):
    """A job that becomes due while cancel runs is either completed or refunded, never both/neither."""
    from game.db import db
    from game.planet_evolution.planet_research import (
        cancel_planet_research_job,
        finish_planet_research_jobs,
    )

    _uid, pid, job_id = _player_with_job("pgcancel_race")
    spent = _resources(pid)
    conn = db()
    try:
        now = time.time()
        conn.execute(
            "UPDATE planet_research_queue SET start_at = ?, finish_at = ? WHERE id = ?;",
            (now - 30, now + 0.4, job_id),
        )
        conn.commit()
    finally:
        conn.close()

    def settle():
        time.sleep(0.4)
        c = db()
        try:
            c.execute("BEGIN")
            n = finish_planet_research_jobs(c, pid, time.time())
            c.commit()
            return n
        finally:
            c.close()

    def cancel_late():
        time.sleep(0.35)
        return cancel_planet_research_job(pid, job_id)

    results, errors = _run_parallel([settle, cancel_late])
    assert errors == [None, None], errors

    after = _resources(pid)
    cancelled = bool(results[1][0])
    assert _queue_ids(pid) == []
    if cancelled:
        assert _level(pid) == 0
        assert after[0] > spent[0]  # refunded
    else:
        assert results[1] == (False, "job_not_found")
        assert _level(pid) == 1  # tech granted
        assert after == spent  # and not refunded


@requires_postgres
def test_pg_cancel_of_due_job_completes_it_without_refund(pg_parity_db):
    from game.db import db
    from game.planet_evolution.planet_research import cancel_planet_research_job

    _uid, pid, job_id = _player_with_job("pgcancel_due")
    spent = _resources(pid)
    conn = db()
    try:
        now = time.time()
        conn.execute(
            "UPDATE planet_research_queue SET start_at = ?, finish_at = ? WHERE id = ?;",
            (now - 120, now - 5, job_id),
        )
        conn.commit()
    finally:
        conn.close()

    assert cancel_planet_research_job(pid, job_id) == (False, "job_not_found")
    assert _level(pid) == 1  # finished work is granted, not deleted
    assert _resources(pid) == spent  # and not refunded
    assert _queue_ids(pid) == []
