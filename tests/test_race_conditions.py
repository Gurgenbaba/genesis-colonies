"""
Race-condition / double-action tests for build & research queues.

Run: python -m pytest tests/test_race_conditions.py -v
"""

from __future__ import annotations

import threading
import time

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import (
    cancel_build_job_for_planet,
    queue_build_for_planet,
    recalculate_build_queue_finish_times,
)
from game.research import (
    cancel_research_job,
    queue_research,
    recalculate_research_queue_finish_times,
)
from game.models import (
    add_build_job,
    add_research_job,
    get_homeworld,
    get_planet_buildings,
    get_build_queue_rows,
    get_research_queue_rows,
    get_idempotent_action,
    save_idempotent_action,
)

# GC-513: bounded waits — no infinite hang on Windows SQLite + thread pool.
_RACE_DB_BUSY_MS = 2000
_PARALLEL_WALL_TIMEOUT_SEC = 30.0


def _release_stale_write_mutex() -> None:
    """Recover leaked process write mutex (Windows pytest + SQLite)."""
    for _ in range(64):
        try:
            dbmod._SQLITE_WRITE_MUTEX.release()
        except RuntimeError:
            break
    dbmod._WRITE_MUTEX_DEPTH.n = 0


def _install_race_test_db(monkeypatch) -> None:
    """Shorter SQLite busy wait for race tests only (production db() unchanged)."""

    _production_db = dbmod.db

    def _race_db():
        conn = _production_db()
        conn.execute(f"PRAGMA busy_timeout={int(_RACE_DB_BUSY_MS)}")
        return conn

    monkeypatch.setattr(dbmod, "db", _race_db)
    monkeypatch.setattr(models, "db", _race_db)


def _run_parallel_attempts(
    *,
    workers: int,  # kept for call-site clarity; threading does not cap at workers
    attempts: int,
    fn,
    wall_timeout: float = _PARALLEL_WALL_TIMEOUT_SEC,
) -> list:
    """
    Run fn() concurrently via threads; never block forever (GC-513 / Windows).
    """
    del workers
    _release_stale_write_mutex()
    results: list = []
    errors: list[str] = []
    lock = threading.Lock()
    deadline = time.time() + float(wall_timeout)

    def runner() -> None:
        try:
            item = fn()
            with lock:
                results.append(item)
        except Exception as exc:
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=runner, name=f"race-{i}") for i in range(int(attempts))]
    for t in threads:
        t.start()

    for i, t in enumerate(threads):
        remaining = max(0.05, deadline - time.time())
        t.join(timeout=remaining)
        if t.is_alive():
            errors.append(
                f"thread {i} ({t.name}) did not finish within {wall_timeout}s "
                f"(SQLite write lock / deadlock suspected)"
            )

    if errors:
        pytest.fail("Parallel race test failed:\n" + "\n".join(errors))
    if len(results) != attempts:
        pytest.fail(
            f"Expected {attempts} results, got {len(results)} "
            f"(partial completion)"
        )
    return results


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "race_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_TEST_DB_BUSY_MS", str(_RACE_DB_BUSY_MS))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    _install_race_test_db(monkeypatch)
    models.init_db()
    ok, err, info = models.create_user("race_tester", "secret123")
    assert ok, err
    uid = int(info["id"])
    planet = get_homeworld(player_id=uid)
    conn = models.db()
    conn.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (500_000, 500_000, int(planet["id"])),
    )
    conn.commit()
    conn.close()
    _release_stale_write_mutex()
    return int(uid), dict(planet)


@pytest.fixture()
def fast_queue_finish(monkeypatch):
    """
    Parallel enqueue tests assert queue-limit races, not full finish_due_work.
    Full pipeline: test_queue_engine.py. Avoids Windows thread+SQLite engine deadlock (GC-513).
    """
    from game.queue_engine import _empty_result

    def _fast_finish(*, source: str = "system", **kwargs):
        return _empty_result(str(source))

    monkeypatch.setattr("game.queue_engine.finish_due_work", _fast_finish)
    return _fast_finish


def _player_view(user_id: int) -> dict:
    p = models.load_player(user_id)
    assert p is not None
    return p


def test_parallel_build_queue_respects_limit(isolated_db, fast_queue_finish):
    user_id, planet = isolated_db
    buildings = get_planet_buildings(int(planet["id"]))

    def attempt():
        import game.queue_engine as qe

        qe.finish_due_work = fast_queue_finish  # thread-visible stub (GC-513)
        return queue_build_for_planet(
            planet, buildings, "metal_mine", user_id=user_id
        )[:2]

    results = _run_parallel_attempts(workers=4, attempts=10, fn=attempt)

    ok_count = sum(1 for ok, _ in results if ok)
    queue = get_build_queue_rows(int(planet["id"]))
    settings = models.get_game_settings()
    limit = max(int(settings.get("queue_limit", 5)), 1)

    assert ok_count == limit
    assert len(queue) == limit
    assert ok_count + sum(1 for ok, _ in results if not ok) == 10


def test_parallel_build_no_double_spend(isolated_db, fast_queue_finish):
    user_id, planet = isolated_db
    buildings = get_planet_buildings(int(planet["id"]))

    conn = models.db()
    conn.execute("UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;", (75, 25, int(planet["id"])))
    conn.commit()
    conn.close()

    def attempt():
        ok, reason, _ = queue_build_for_planet(
            planet, buildings, "metal_mine", user_id=user_id
        )
        return (ok, reason)

    results = _run_parallel_attempts(workers=3, attempts=5, fn=attempt)

    conn = models.db()
    row = conn.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (int(planet["id"]),)).fetchone()
    conn.close()
    queue_len = len(get_build_queue_rows(int(planet["id"])))
    ok_count = sum(1 for ok, _ in results if ok)

    assert ok_count <= 1
    assert queue_len <= 1
    if ok_count == 1:
        assert float(row["metal"]) == 0
        assert float(row["crystal"]) == 0
    else:
        assert float(row["metal"]) == 75
        assert float(row["crystal"]) == 25


def test_same_tech_requeue_levels_sequential(isolated_db):
    user_id, planet = isolated_db
    player = _player_view(user_id)
    buildings = get_planet_buildings(int(planet["id"]))

    conn = models.db()
    conn.execute(
        "UPDATE planet_buildings SET research_lab = 3 WHERE planet_id = ?;",
        (int(planet["id"]),),
    )
    conn.commit()
    conn.close()

    ok1, _, job1 = queue_research(player, "energy_tech", user_id=user_id)
    ok2, _, job2 = queue_research(player, "energy_tech", user_id=user_id)
    assert ok1 and ok2
    assert job1["target_level"] == 1
    assert job2["target_level"] == 2

    rows = get_research_queue_rows(user_id)
    assert len(rows) == 2


def test_parallel_research_queue_full(isolated_db, fast_queue_finish):
    user_id, planet = isolated_db
    player = _player_view(user_id)

    conn = models.db()
    conn.execute(
        "UPDATE planet_buildings SET research_lab = 3 WHERE planet_id = ?;",
        (int(planet["id"]),),
    )
    conn.commit()
    conn.close()

    techs = ["energy_tech", "mining_tech", "storage_tech", "buildtime_tech", "weapon_tech"]
    tech_index = {"i": 0}
    tech_lock = threading.Lock()

    def attempt_next():
        with tech_lock:
            idx = tech_index["i"]
            tech_index["i"] = idx + 1
            tech = techs[idx]
        ok, reason, _ = queue_research(player, tech, user_id=user_id)
        return (ok, reason, tech)

    results = _run_parallel_attempts(
        workers=3, attempts=len(techs), fn=attempt_next
    )
    from game.research import _resolve_research_queue_limit

    ok_count = sum(1 for ok, _, _ in results if ok)
    limit = _resolve_research_queue_limit(player_id=user_id)
    assert ok_count <= limit
    assert len(get_research_queue_rows(user_id)) <= limit


def test_idempotency_returns_cached_response(isolated_db):
    user_id, _ = isolated_db
    cached = {"ok": True, "reason": "ok", "state": {"ok": True}}
    save_idempotent_action(user_id, "req-abc", cached)
    got = get_idempotent_action(user_id, "req-abc")
    assert got == cached


def test_build_cancel_first_job_reschedules_follower_at_now(isolated_db):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    now = time.time()

    j1 = add_build_job(planet_id, "metal_mine", now - 10, now + 50)
    j2 = add_build_job(planet_id, "crystal_mine", now + 500, now + 600)

    ok, reason, _ = cancel_build_job_for_planet(planet_id, j1, user_id=user_id)
    assert ok and reason == "ok"

    rows = get_build_queue_rows(planet_id)
    assert len(rows) == 1
    assert int(rows[0]["id"]) == j2
    assert float(rows[0]["start_time"]) <= now + 2.0
    assert float(rows[0]["finish_time"]) > float(rows[0]["start_time"])


def test_build_cancel_middle_job_chains_follower_after_active(isolated_db):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    now = time.time()

    j1 = add_build_job(planet_id, "metal_mine", now - 10, now + 50)
    j2 = add_build_job(planet_id, "crystal_mine", now + 500, now + 600)
    j3 = add_build_job(planet_id, "solar_plant", now + 600, now + 700)

    ok, reason, _ = cancel_build_job_for_planet(planet_id, j2, user_id=user_id)
    assert ok and reason == "ok"

    rows = get_build_queue_rows(planet_id)
    assert [int(r["id"]) for r in rows] == [j1, j3]
    assert float(rows[0]["start_time"]) == pytest.approx(now - 10, abs=2.0)
    assert float(rows[0]["finish_time"]) == pytest.approx(now + 50, abs=2.0)
    assert float(rows[1]["start_time"]) == pytest.approx(float(rows[0]["finish_time"]), abs=2.0)


def test_build_enqueue_recalculates_stale_follower_after_near_finish(isolated_db):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)
    now = time.time()

    add_build_job(planet_id, "metal_mine", now - 10, now + 5)
    add_build_job(planet_id, "crystal_mine", now + 500, now + 600)

    ok, reason, _ = queue_build_for_planet(planet, buildings, "solar_plant", user_id=user_id)
    assert ok and reason == "ok"

    rows = get_build_queue_rows(planet_id)
    assert len(rows) == 3
    assert float(rows[1]["start_time"]) == pytest.approx(float(rows[0]["finish_time"]), abs=2.0)
    assert float(rows[2]["start_time"]) == pytest.approx(float(rows[1]["finish_time"]), abs=2.0)


def test_build_recalculate_clears_expired_before_enqueue_basis(isolated_db):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    now = time.time()

    add_build_job(planet_id, "metal_mine", now - 120, now - 1)

    conn = models.db()
    try:
        recalculate_build_queue_finish_times(
            planet_id, user_id, conn=conn, now=now
        )
        conn.commit()
    finally:
        conn.close()

    rows = get_build_queue_rows(planet_id)
    assert len(rows) == 1
    assert float(rows[0]["start_time"]) <= now + 2.0


def test_research_cancel_first_job_reschedules_follower_at_now(isolated_db):
    user_id, planet = isolated_db
    now = time.time()

    conn = models.db()
    conn.execute(
        "UPDATE planet_buildings SET research_lab = 3 WHERE planet_id = ?;",
        (int(planet["id"]),),
    )
    conn.commit()
    conn.close()

    j1 = add_research_job(user_id, "energy_tech", now - 10, now + 50)
    j2 = add_research_job(user_id, "mining_tech", now + 500, now + 600)

    ok, reason, _ = cancel_research_job(user_id, j1)
    assert ok and reason == "ok"

    rows = get_research_queue_rows(user_id)
    assert len(rows) == 1
    assert int(rows[0]["id"]) == j2
    assert float(rows[0]["start_at"]) <= now + 2.0


def test_research_cancel_middle_job_chains_follower_after_active(isolated_db):
    user_id, planet = isolated_db
    now = time.time()

    conn = models.db()
    conn.execute(
        "UPDATE planet_buildings SET research_lab = 3 WHERE planet_id = ?;",
        (int(planet["id"]),),
    )
    conn.commit()
    conn.close()

    j1 = add_research_job(user_id, "energy_tech", now - 10, now + 50)
    j2 = add_research_job(user_id, "mining_tech", now + 500, now + 600)
    j3 = add_research_job(user_id, "storage_tech", now + 600, now + 700)

    ok, reason, _ = cancel_research_job(user_id, j2)
    assert ok and reason == "ok"

    rows = get_research_queue_rows(user_id)
    assert [int(r["id"]) for r in rows] == [j1, j3]
    assert float(rows[1]["start_at"]) == pytest.approx(float(rows[0]["finish_at"]), abs=2.0)


def test_research_enqueue_recalculates_stale_follower(isolated_db):
    user_id, planet = isolated_db
    player = _player_view(user_id)
    now = time.time()

    conn = models.db()
    conn.execute(
        "UPDATE planet_buildings SET research_lab = 4 WHERE planet_id = ?;",
        (int(planet["id"]),),
    )
    conn.commit()
    conn.close()

    add_research_job(user_id, "energy_tech", now - 10, now + 5)
    add_research_job(user_id, "mining_tech", now + 500, now + 600)

    ok, reason, _ = queue_research(player, "weapon_tech", user_id=user_id)
    assert ok and reason == "ok"

    rows = get_research_queue_rows(user_id)
    assert len(rows) == 3
    assert float(rows[1]["start_at"]) == pytest.approx(float(rows[0]["finish_at"]), abs=2.0)
    assert float(rows[2]["start_at"]) == pytest.approx(float(rows[1]["finish_at"]), abs=2.0)
