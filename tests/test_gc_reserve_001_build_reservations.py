"""GC-RESERVE-001 - reserve the next building: contract tests against the REAL build owner.

Ports ``tests/test_reserve_next_purchase_model.py`` (analysis branch) to ``queue_build_for_planet``:
arming changes nothing, the start charges exactly once (replay / race / failure / cancel racing the
start), the queue limit and the level cap are the manual ones, every ended state is reachable, the flag
is a real kill switch, and the autoplay never competes with a reservation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"
POOR = 0
RICH = 50_000_000_000


# ---------------------------------------------------------------------------
# fixtures: one migrated template database, copied per test
# ---------------------------------------------------------------------------


def _postgres_url() -> str:
    """The PostgreSQL gate: the SAME tests run on a real PostgreSQL when asked for explicitly.

    ``GC_RESERVE_TEST_BACKEND=postgres`` + ``GC_TEST_POSTGRES_URL`` (a migrated, disposable database).
    A stray ``DATABASE_URL`` in the shell never flips the backend by itself.
    """
    if os.environ.get("GC_RESERVE_TEST_BACKEND", "").strip().lower() != "postgres":
        return ""
    return os.environ.get("GC_TEST_POSTGRES_URL", "").strip()


ON_POSTGRES = bool(_postgres_url())
sqlite_only = pytest.mark.skipif(ON_POSTGRES, reason="SQLite-specific check")
postgres_only = pytest.mark.skipif(not ON_POSTGRES, reason="needs GC_RESERVE_TEST_BACKEND=postgres + GC_TEST_POSTGRES_URL")


@pytest.fixture(scope="module")
def template_db(tmp_path_factory):
    if ON_POSTGRES:
        return None  # the PostgreSQL database is migrated up front (python migrate.py)
    path = tmp_path_factory.mktemp("gc_reserve_template") / "template.db"
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(path)
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    result = subprocess.run([sys.executable, str(MIGRATE_SCRIPT)], cwd=str(ROOT), capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr or result.stdout
    return path


@pytest.fixture()
def world(template_db, tmp_path, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "on")
    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE_USER_IDS", raising=False)
    if ON_POSTGRES:
        from tests.pg_fixtures import close_pg_pool, wipe_postgres_game_data_direct

        url = _postgres_url()
        close_pg_pool()
        monkeypatch.setenv("GC_DB_BACKEND", "postgres")
        monkeypatch.setenv("DATABASE_URL", url)
        monkeypatch.setenv("SECRET_KEY", "reserve-pg-test-secret-key-not-for-production")
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("GC_PG_POOL_MAX", os.environ.get("GC_PG_POOL_MAX", "12") or "12")
        monkeypatch.setenv("GC_PG_LOCK_TIMEOUT", "15s")
        wipe_postgres_game_data_direct(url)  # TRUNCATE ... CASCADE also empties build_reservations (FK)
    else:
        db_file = tmp_path / "reserve.db"
        shutil.copy(template_db, db_file)
        monkeypatch.setenv("GC_DB_PATH", str(db_file))
        monkeypatch.setattr(dbmod, "DB_PATH", db_file)
        monkeypatch.setattr(models, "DB_PATH", db_file)
    models.init_db()
    ok, err, info = models.create_user("reserve_user", "secret123")
    assert ok, err
    uid = int(info["id"])
    planet = dict(models.get_homeworld(player_id=uid))
    yield uid, planet
    if ON_POSTGRES:
        close_pg_pool()


def _db():
    return models.db()


def _stock(planet_id: int) -> tuple[int, int]:
    conn = _db()
    try:
        row = conn.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (int(planet_id),)).fetchone()
        return int(row["metal"]), int(row["crystal"])
    finally:
        conn.close()


def _set_stock(planet_id: int, metal: int, crystal: int) -> None:
    conn = _db()
    conn.execute("UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;", (int(metal), int(crystal), int(planet_id)))
    conn.commit()
    conn.close()


def _set_level(planet_id: int, building: str, level: int) -> None:
    conn = _db()
    conn.execute(f"UPDATE planet_buildings SET {building} = ? WHERE planet_id = ?;", (int(level), int(planet_id)))
    conn.commit()
    conn.close()


def _queue(planet_id: int) -> list[dict]:
    conn = _db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, building_type, start_time, finish_time FROM build_queue WHERE planet_id = ? ORDER BY id;", (int(planet_id),)
        ).fetchall()]
    finally:
        conn.close()


def _reservation(rid: int) -> dict:
    from game.build_reservations import get_reservation

    conn = _db()
    try:
        return get_reservation(conn, int(rid))
    finally:
        conn.close()


def _set_reservation(rid: int, **cols) -> None:
    conn = _db()
    sets = ", ".join(f"{k} = ?" for k in cols)
    conn.execute(f"UPDATE build_reservations SET {sets} WHERE id = ?;", (*cols.values(), int(rid)))
    conn.commit()
    conn.close()


def _arm_poor(uid: int, planet: dict, building: str = "metal_mine", **kw):
    from game.build_reservations import arm_reservation

    _set_stock(planet["id"], POOR, POOR)
    ok, reason, payload = arm_reservation(uid, building, planet_id=int(planet["id"]), **kw)
    assert ok and reason == "ok", (reason, payload)
    return payload["reservation"]


def _cost_of_next(planet: dict, building: str = "metal_mine") -> tuple[int, int]:
    from game.buildings import get_upgrade_cost

    level = int(models.get_planet_buildings(int(planet["id"])).get(building, 0) or 0)
    return tuple(int(x) for x in get_upgrade_cost(building, level))  # type: ignore[return-value]


def _evaluate(rid: int, **kw):
    from game.build_reservations import evaluate_reservation

    return evaluate_reservation(_reservation(rid), **kw)


# ---------------------------------------------------------------------------
# the migration
# ---------------------------------------------------------------------------


def test_migration_creates_the_table_and_the_three_guards(world):
    conn = _db()
    try:
        if ON_POSTGRES:
            names = {r["indexname"] for r in conn.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'build_reservations';").fetchall()}
            names.add("build_reservations")
        else:
            names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE tbl_name = 'build_reservations';").fetchall()}
    finally:
        conn.close()
    assert {
        "build_reservations",
        "ux_build_reservations_one_armed_per_planet",
        "ux_build_reservations_request",
        "ux_build_reservations_job",
    } <= names


def test_migration_changes_no_existing_row_and_charges_nothing(world):
    uid, planet = world
    metal, crystal = _stock(planet["id"])
    assert metal > 0 and crystal > 0  # a fresh homeworld keeps its stock; the migration is create-only
    assert _queue(planet["id"]) == []


# ---------------------------------------------------------------------------
# the feature flag is a real kill switch
# ---------------------------------------------------------------------------


def test_flag_off_by_default_refuses_arming_and_ticks_nothing(world, monkeypatch):
    from game.build_reservations import arm_reservation, planet_has_armed_reservation, run_reservation_tick

    uid, planet = world
    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    _set_stock(planet["id"], POOR, POOR)
    assert arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))[:2] == (False, "disabled")
    assert run_reservation_tick() == {"enabled": False, "evaluated": 0, "outcomes": {}, "errors": 0}
    conn = _db()
    try:
        assert planet_has_armed_reservation(conn, int(planet["id"]), uid) is False
    finally:
        conn.close()


def test_test_mode_is_an_allow_list(world, monkeypatch):
    from game.build_reservations import arm_reservation

    uid, planet = world
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "test")
    _set_stock(planet["id"], POOR, POOR)
    assert arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))[:2] == (False, "disabled")
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE_USER_IDS", f"999, {uid}")
    ok, reason, _ = arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))
    assert (ok, reason) == (True, "ok")


def test_turning_the_flag_off_leaves_armed_rows_unstarted_and_uncharged(world, monkeypatch):
    from game.build_reservations import run_reservation_tick

    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m + 10, cost_c + 10)
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "off")
    assert run_reservation_tick()["enabled"] is False
    assert _reservation(res["id"])["state"] == "armed"
    assert _stock(planet["id"]) == (cost_m + 10, cost_c + 10) and _queue(planet["id"]) == []


# ---------------------------------------------------------------------------
# arming: validation on the server, no side effects
# ---------------------------------------------------------------------------


def test_arm_holds_no_resources_and_changes_no_queue_or_timer(world):
    uid, planet = world
    _set_stock(planet["id"], 5, 5)
    before_stock, before_queue = _stock(planet["id"]), _queue(planet["id"])
    from game.build_reservations import arm_reservation

    ok, reason, payload = arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))
    assert (ok, reason) == (True, "ok")
    assert _stock(planet["id"]) == before_stock and _queue(planet["id"]) == before_queue
    view = payload["reservation"]
    assert view["state"] == "armed" and view["building_type"] == "metal_mine"
    level = int(models.get_planet_buildings(int(planet["id"]))["metal_mine"])
    assert view["target_level"] == level + 1
    assert view["expires_at"] > time.time() + 40 * 3600


def test_arm_refuses_what_could_start_right_now(world):
    from game.build_reservations import arm_reservation

    uid, planet = world
    _set_stock(planet["id"], RICH, RICH)
    ok, reason, _ = arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))
    assert (ok, reason) == (False, "affordable_now")
    assert _stock(planet["id"]) == (RICH, RICH) and _queue(planet["id"]) == []


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"building_type": "not_a_building"}, "invalid_type"),
        ({"building_type": "metal_storage"}, "requirements"),  # needs metal_mine 4 on a fresh account
    ],
)
def test_arm_server_side_validation(world, kwargs, expected):
    from game.build_reservations import arm_reservation

    uid, planet = world
    _set_stock(planet["id"], POOR, POOR)
    _set_level(planet["id"], "metal_mine", 1)
    ok, reason, _ = arm_reservation(uid, planet_id=int(planet["id"]), **kwargs)
    assert (ok, reason) == (False, expected)


def test_arm_refuses_someone_elses_planet_and_vacation(world):
    from game.build_reservations import arm_reservation

    uid, planet = world
    ok, err, other = models.create_user("reserve_other", "secret123")
    assert ok, err
    other_planet = dict(models.get_homeworld(player_id=int(other["id"])))
    _set_stock(other_planet["id"], POOR, POOR)
    assert arm_reservation(uid, "metal_mine", planet_id=int(other_planet["id"]))[:2] == (False, "not_owner")

    _set_stock(planet["id"], POOR, POOR)
    conn = _db()
    conn.execute("UPDATE players SET vacation_mode_active = 1 WHERE id = ?;", (uid,))
    conn.commit()
    conn.close()
    assert arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))[:2] == (False, "vacation")


def test_arm_is_idempotent_per_request_id(world):
    from game.build_reservations import arm_reservation

    uid, planet = world
    first = _arm_poor(uid, planet, request_id="req-1")
    ok, reason, payload = arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]), request_id="req-1")
    assert (ok, reason) == (True, "ok") and payload["idempotent"] is True and payload["reservation"]["id"] == first["id"]
    conn = _db()
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM build_reservations;").fetchone()["n"] == 1
    finally:
        conn.close()


def test_one_armed_reservation_per_planet_and_replace_is_explicit(world):
    from game.build_reservations import arm_reservation

    uid, planet = world
    first = _arm_poor(uid, planet, "metal_mine")
    ok, reason, payload = arm_reservation(uid, "crystal_mine", planet_id=int(planet["id"]))
    assert (ok, reason) == (False, "reservation_exists") and payload["reservation"]["id"] == first["id"]
    ok, reason, payload = arm_reservation(uid, "crystal_mine", planet_id=int(planet["id"]), replace=True)
    assert (ok, reason) == (True, "ok") and payload["replaced"] is True
    assert _reservation(first["id"])["state"] == "cancelled" and _reservation(first["id"])["reason"] == "replaced"
    assert payload["reservation"]["building_type"] == "crystal_mine"


def test_database_refuses_a_second_armed_row_per_planet(world):
    """The guarantee holds even if the application code is wrong."""
    uid, planet = world
    _arm_poor(uid, planet)
    conn = _db()
    now = time.time()
    with pytest.raises(Exception) as exc:
        conn.execute(
            "INSERT INTO build_reservations (player_id, planet_id, building_type, expected_level, state, created_at, updated_at, expires_at)"
            " VALUES (?, ?, 'crystal_mine', 1, 'armed', ?, ?, ?);",
            (uid, int(planet["id"]), now, now, now + 100),
        )
    conn.close()
    assert dbmod.is_integrity_error(exc.value)


# ---------------------------------------------------------------------------
# starting: exactly the manual build, charged once
# ---------------------------------------------------------------------------


def test_starts_when_funds_arrive_and_charges_exactly_the_canonical_cost(world):
    uid, planet = world
    res = _arm_poor(uid, planet)
    assert _evaluate(res["id"])["outcome"] == "waiting_funds"
    assert _queue(planet["id"]) == [] and _reservation(res["id"])["state"] == "armed"

    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m + 7, cost_c + 3)
    out = _evaluate(res["id"])
    assert out["outcome"] == "started"
    assert _stock(planet["id"]) == (7, 3)  # exactly the price, nothing more
    jobs = _queue(planet["id"])
    assert len(jobs) == 1 and jobs[0]["building_type"] == "metal_mine" and jobs[0]["id"] == out["job_id"]
    row = _reservation(res["id"])
    assert row["state"] == "started" and row["job_id"] == jobs[0]["id"]


def test_started_job_is_the_same_as_a_manual_one(world):
    """Same duration, same stored cost snapshot as a manual enqueue of the same level."""
    from game.buildings import queue_build_for_planet

    uid, planet = world
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m, cost_c)
    ok, _, manual = queue_build_for_planet(planet, {}, "metal_mine", user_id=uid)
    assert ok
    conn = _db()
    manual_row = dict(conn.execute("SELECT * FROM build_queue WHERE id = ?;", (manual["job_id"],)).fetchone())
    conn.execute("DELETE FROM build_queue WHERE id = ?;", (manual["job_id"],))
    conn.commit()
    conn.close()

    res = _arm_poor(uid, planet)
    _set_stock(planet["id"], cost_m, cost_c)
    assert _evaluate(res["id"])["outcome"] == "started"
    conn = _db()
    auto_row = dict(conn.execute("SELECT * FROM build_queue WHERE planet_id = ?;", (planet["id"],)).fetchone())
    conn.close()
    for column in ("building_type", "cost_metal_exact", "cost_crystal_exact"):
        assert auto_row[column] == manual_row[column]
    assert abs((auto_row["finish_time"] - auto_row["start_time"]) - (manual_row["finish_time"] - manual_row["start_time"])) < 2.0


def test_replayed_evaluation_charges_once(world):
    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m * 3, cost_c * 3)
    assert _evaluate(res["id"])["outcome"] == "started"
    stock_after = _stock(planet["id"])
    stale = _reservation(res["id"])
    stale["state"] = "armed"  # a worker holding a stale copy of the row
    from game.build_reservations import evaluate_reservation

    for _ in range(3):
        assert evaluate_reservation(stale)["outcome"] in ("skipped", "superseded")
    assert _stock(planet["id"]) == stock_after and len(_queue(planet["id"])) == 1


def test_cancel_racing_the_start_leaves_no_charge_and_no_job(world):
    """A worker passed every check, then the player cancelled: the claim loses, the debit and the job roll back."""
    from game.build_reservations import cancel_reservation, evaluate_reservation

    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m + 1, cost_c + 1)
    stale = _reservation(res["id"])  # the worker loaded the armed row ...
    assert cancel_reservation(uid, res["id"])[:2] == (True, "ok")  # ... then the player cancelled it
    out = evaluate_reservation(stale)
    assert out["outcome"] == "skipped" and out["reason"] == "reservation_not_armed"
    assert _stock(planet["id"]) == (cost_m + 1, cost_c + 1) and _queue(planet["id"]) == []
    assert _reservation(res["id"])["state"] == "cancelled"


def test_failure_between_debit_and_commit_leaves_no_trace_and_the_retry_charges_once(world, monkeypatch):
    import game.build_reservations as br

    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m + 5, cost_c + 5)

    real = br.claim_reservation_in_transaction

    def boom(*_a, **_k):
        raise RuntimeError("injected failure after the debit and the job insert")

    monkeypatch.setattr(br, "claim_reservation_in_transaction", boom)
    with pytest.raises(RuntimeError):
        _evaluate(res["id"])
    assert _stock(planet["id"]) == (cost_m + 5, cost_c + 5) and _queue(planet["id"]) == []
    assert _reservation(res["id"])["state"] == "armed"

    monkeypatch.setattr(br, "claim_reservation_in_transaction", real)
    assert _evaluate(res["id"])["outcome"] == "started"
    assert _stock(planet["id"]) == (5, 5) and len(_queue(planet["id"])) == 1


def test_four_threads_racing_one_reservation_start_it_exactly_once(world):
    from game.build_reservations import evaluate_reservation

    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m * 10, cost_c * 10)
    snapshot = _reservation(res["id"])
    barrier = threading.Barrier(4)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def worker():
        try:
            barrier.wait(timeout=10)
            outcomes.append(evaluate_reservation(dict(snapshot))["outcome"])
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    assert outcomes.count("started") == 1 and len(outcomes) == 4
    assert len(_queue(planet["id"])) == 1
    assert _stock(planet["id"]) == (cost_m * 9, cost_c * 9)  # one price paid, not four


# ---------------------------------------------------------------------------
# concurrent actors and the manual rules
# ---------------------------------------------------------------------------


def test_manual_build_of_the_same_building_supersedes_without_a_second_charge(world):
    from game.buildings import queue_build_for_planet

    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m * 5, cost_c * 5)
    ok, _, _ = queue_build_for_planet(planet, {}, "metal_mine", user_id=uid)  # the player did it by hand
    assert ok
    after_manual = _stock(planet["id"])
    out = _evaluate(res["id"])
    assert out["outcome"] == "superseded"
    assert _stock(planet["id"]) == after_manual and len(_queue(planet["id"])) == 1
    row = _reservation(res["id"])
    assert row["state"] == "cancelled" and row["reason"] == "superseded"


def test_a_manual_build_of_a_different_building_does_not_cancel_it(world):
    from game.buildings import queue_build_for_planet

    uid, planet = world
    res = _arm_poor(uid, planet, "metal_mine")
    cost_c_m, cost_c_c = _cost_of_next(planet, "crystal_mine")
    _set_stock(planet["id"], RICH, RICH)
    assert queue_build_for_planet(planet, {}, "crystal_mine", user_id=uid)[0]
    out = _evaluate(res["id"])
    assert out["outcome"] == "started"  # funds + slot: both jobs queued, each charged once
    assert sorted(j["building_type"] for j in _queue(planet["id"])) == ["crystal_mine", "metal_mine"]


def test_full_queue_keeps_the_reservation_and_it_never_exceeds_the_limit(world):
    from game.buildings import queue_build_for_planet

    uid, planet = world
    models.save_game_settings({"queue_limit": 1})
    _set_stock(planet["id"], RICH, RICH)
    assert queue_build_for_planet(planet, {}, "crystal_mine", user_id=uid)[0]  # fills the single slot
    # affordable but the queue is full: a reservation is allowed (the ordinary button would be refused)
    from game.build_reservations import arm_reservation

    ok, reason, payload = arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))
    assert (ok, reason) == (True, "ok")
    rid = payload["reservation"]["id"]
    for _ in range(3):
        assert _evaluate(rid)["outcome"] == "waiting_slot"
        assert len(_queue(planet["id"])) == 1  # the limit is never bypassed
    stock_waiting = _stock(planet["id"])

    conn = _db()
    now = time.time()
    conn.execute("UPDATE build_queue SET start_time = ?, finish_time = ? WHERE planet_id = ?;", (now - 100, now - 1, int(planet["id"])))
    conn.commit()
    conn.close()
    out = _evaluate(rid)  # the owner finishes the due job first, which frees the slot
    assert out["outcome"] == "started"
    assert [j["building_type"] for j in _queue(planet["id"])] == ["metal_mine"]
    cost_m, cost_c = _cost_of_next(planet, "metal_mine")  # level advanced by one; the price paid was the old level's
    assert _stock(planet["id"])[0] < stock_waiting[0]


def test_expiry_cancels_without_a_charge_and_vacation_pauses_instead(world):
    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m * 2, cost_c * 2)

    conn = _db()
    conn.execute("UPDATE players SET vacation_mode_active = 1 WHERE id = ?;", (uid,))
    conn.commit()
    conn.close()
    _set_reservation(res["id"], expires_at=time.time() - 5)
    assert _evaluate(res["id"])["outcome"] == "paused"  # expiry does not run while paused
    assert _reservation(res["id"])["state"] == "armed" and _queue(planet["id"]) == []

    conn = _db()
    conn.execute("UPDATE players SET vacation_mode_active = 0 WHERE id = ?;", (uid,))
    conn.commit()
    conn.close()
    assert _evaluate(res["id"])["outcome"] == "expired"
    row = _reservation(res["id"])
    assert row["state"] == "expired" and row["reason"] == "expired"
    assert _stock(planet["id"]) == (cost_m * 2, cost_c * 2) and _queue(planet["id"]) == []


def test_requirement_lost_cancels_as_invalid(world):
    uid, planet = world
    _set_level(planet["id"], "metal_mine", 4)
    res = _arm_poor(uid, planet, "metal_storage")
    _set_level(planet["id"], "metal_mine", 1)  # the requirement (metal_mine 4) no longer holds
    _set_stock(planet["id"], RICH, RICH)
    out = _evaluate(res["id"])
    assert out["outcome"] == "invalid"
    row = _reservation(res["id"])
    assert row["state"] == "cancelled" and row["reason"] == "invalid"
    assert _stock(planet["id"]) == (RICH, RICH) and _queue(planet["id"]) == []


def test_player_cancel_is_free_and_owner_only(world):
    from game.build_reservations import cancel_reservation

    uid, planet = world
    res = _arm_poor(uid, planet)
    ok, err, other = models.create_user("reserve_other", "secret123")
    assert ok, err
    assert cancel_reservation(int(other["id"]), res["id"])[:2] == (False, "not_found")
    assert _reservation(res["id"])["state"] == "armed"
    stock = _stock(planet["id"])
    ok, reason, payload = cancel_reservation(uid, res["id"])
    assert (ok, reason) == (True, "ok") and payload["reservation"]["reason"] == "player"
    assert _stock(planet["id"]) == stock
    assert cancel_reservation(uid, res["id"])[:2] == (False, "not_armed")


def test_ascension_cap_is_not_bypassed_by_a_reservation(world):
    """A mine at its Ascension gate cannot be reserved beyond it; the owner's own cap decides."""
    from game.build_reservations import arm_reservation
    from game.mine_evolution import get_evolution_rank
    from game.buildings import _effective_building_queue_cap, BuildingsPanelContext

    uid, planet = world
    conn = _db()
    try:
        cap = int(_effective_building_queue_cap("metal_mine", 10_000, planet_id=int(planet["id"]), conn=conn, evolution_rank=get_evolution_rank(int(planet["id"]), "metal_mine", conn=conn)))
    finally:
        conn.close()
    _set_level(planet["id"], "metal_mine", cap)
    _set_stock(planet["id"], POOR, POOR)
    ok, reason, _ = arm_reservation(uid, "metal_mine", planet_id=int(planet["id"]))
    assert ok is False and reason in ("ascension_required", "max_level")


# ---------------------------------------------------------------------------
# the heartbeat, the autoplay guard, the payload, the routes
# ---------------------------------------------------------------------------


def test_tick_starts_what_is_ready_and_skips_what_is_not(world):
    from game.build_reservations import run_reservation_tick

    uid, planet = world
    res = _arm_poor(uid, planet)
    out = run_reservation_tick()
    assert out["enabled"] and out["evaluated"] == 0  # the pre-filter: not affordable, no owner call at all
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m + 1, cost_c + 1)
    out = run_reservation_tick()
    assert out["outcomes"] == {"started": 1} and _reservation(res["id"])["state"] == "started"
    assert run_reservation_tick()["evaluated"] == 0  # nothing armed any more


def test_tick_runner_calls_the_reservation_heartbeat_after_the_due_work(world):
    from game.tick_runner import run_tick

    uid, planet = world
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m + 1, cost_c + 1)
    result = run_tick(persist=False, include_fleet_tail=False, include_inbox_retention=False)
    assert result["reservations"]["outcomes"] == {"started": 1} and _reservation(res["id"])["state"] == "started"


def test_tick_runner_adds_nothing_when_the_flag_is_off(world, monkeypatch):
    from game.tick_runner import run_tick

    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    result = run_tick(persist=False, include_fleet_tail=False, include_inbox_retention=False)
    assert "reservations" not in result


def test_autoplay_never_builds_on_a_planet_with_a_reservation(world):
    from game.auto_empire import plan_passive_planet_tick
    from game.build_reservations import planet_has_armed_reservation

    uid, planet = world
    _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], RICH, RICH)
    conn = _db()
    try:
        assert planet_has_armed_reservation(conn, int(planet["id"]), uid) is True
        before = len(_queue(planet["id"]))
        out = plan_passive_planet_tick(conn, player_id=uid, planet=planet, allow_research=False, allow_defense=False, now=time.time())
        conn.commit()
    finally:
        conn.close()
    assert out["builds"] == [] and len(_queue(planet["id"])) == before


def test_queue_payload_carries_the_reservation_only_when_the_flag_is_on(world, monkeypatch):
    from flask import Flask

    from game.buildings import get_build_queue_status_for_planet

    uid, planet = world
    res = _arm_poor(uid, planet)
    app = Flask("gc_reserve_payload")
    conn = _db()  # caller-owned: closed below (a leaked read transaction would block a PostgreSQL TRUNCATE)
    try:
        with app.test_request_context("/"):
            on = get_build_queue_status_for_planet(int(planet["id"]), conn=conn, skip_finish=True)
            assert on["reservation"]["armed"]["id"] == res["id"] and on["reservation"]["armed"]["waiting_for"] == "funds"
            monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
            off = get_build_queue_status_for_planet(int(planet["id"]), conn=conn, skip_finish=True)
            assert "reservation" not in off
    finally:
        conn.close()


def test_last_ended_reservation_is_reported_for_a_day(world):
    from game.build_reservations import planet_reservation_payload

    uid, planet = world
    res = _arm_poor(uid, planet)
    _set_reservation(res["id"], state="cancelled", reason="superseded", ended_at=time.time() - 60)
    conn = _db()
    try:
        info = planet_reservation_payload(conn, int(planet["id"]), uid)
        assert info["armed"] is None and info["last_ended"]["reason"] == "superseded"
        stale = planet_reservation_payload(conn, int(planet["id"]), uid, now=time.time() + 2 * 86400)
        assert stale["last_ended"] is None
    finally:
        conn.close()


def test_prune_removes_only_old_ended_rows(world):
    from game.build_reservations import RESERVATION_RETENTION_SECONDS, prune_ended

    uid, planet = world
    res = _arm_poor(uid, planet)
    assert prune_ended(time.time() + RESERVATION_RETENTION_SECONDS * 2) == 0  # armed rows are never pruned
    _set_reservation(res["id"], state="expired", reason="expired", ended_at=time.time() - 1)
    assert prune_ended(time.time()) == 0
    assert prune_ended(time.time() + RESERVATION_RETENTION_SECONDS + 10) == 1


def test_routes_arm_cancel_and_idempotent_replay(world):
    import importlib

    import app as app_module

    uid, planet = world
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    models.save_game_settings({"queue_limit": 5})
    _set_stock(planet["id"], POOR, POOR)

    r = client.post("/api/buildings/reserve", json={"building_type": "metal_mine", "planet_id": planet["id"], "request_id": "r-1"})
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] is True and body["reason"] == "ok"
    rid = body["job"]["reservation"]["id"]
    replay = client.post("/api/buildings/reserve", json={"building_type": "metal_mine", "planet_id": planet["id"], "request_id": "r-1"})
    assert replay.get_json()["job"]["reservation"]["id"] == rid

    again = client.post("/api/buildings/reserve", json={"building_type": "crystal_mine", "planet_id": planet["id"]})
    assert again.get_json()["ok"] is False and again.get_json()["reason"] == "reservation_exists"

    missing = client.post("/api/buildings/reserve/cancel", json={})
    assert missing.status_code == 400
    cancelled = client.post("/api/buildings/reserve/cancel", json={"reservation_id": rid})
    assert cancelled.get_json()["ok"] is True and _reservation(rid)["state"] == "cancelled"

    _set_stock(planet["id"], RICH, RICH)
    refused = client.post("/api/buildings/reserve", json={"building_type": "metal_mine", "planet_id": planet["id"]})
    assert refused.get_json()["ok"] is False and refused.get_json()["reason"] == "affordable_now"


def test_routes_report_disabled_when_the_flag_is_off(world, monkeypatch):
    import importlib

    import app as app_module

    uid, planet = world
    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    _set_stock(planet["id"], POOR, POOR)
    r = client.post("/api/buildings/reserve", json={"building_type": "metal_mine", "planet_id": planet["id"]})
    assert r.get_json()["ok"] is False and r.get_json()["reason"] == "disabled"


# ---------------------------------------------------------------------------
# audit: random sequences never create resources or charge twice
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_sequences_conserve_resources_and_start_each_reservation_at_most_once(world, monkeypatch, seed):
    """stock_end == stock_start + credited - sum(job costs), and no reservation owns more than one job."""
    import random

    from game.build_reservations import arm_reservation, cancel_reservation, evaluate_reservation
    from game.buildings import queue_build_for_planet

    import game.buildings as gb

    uid, planet = world
    pid = int(planet["id"])
    rng = random.Random(seed)
    types = ["metal_mine", "crystal_mine", "solar_plant"]
    models.save_game_settings({"queue_limit": 2})
    debits: list[tuple[int, int]] = []
    real_spend = gb.try_spend_resources_conn

    def recording_spend(conn, planet_id, metal_cost, crystal_cost):
        ok = real_spend(conn, planet_id, metal_cost, crystal_cost)
        if ok:
            debits.append((int(metal_cost), int(crystal_cost)))
        return ok

    monkeypatch.setattr(gb, "try_spend_resources_conn", recording_spend)
    _set_stock(pid, POOR, POOR)
    credited_m = credited_c = 0
    start_m, start_c = _stock(pid)
    started = 0

    for step in range(150):
        action = rng.choice(["drain", "drain", "arm", "arm", "arm", "credit", "credit", "credit", "credit", "evaluate", "evaluate", "evaluate", "evaluate", "manual", "cancel", "finish", "finish"])
        if action == "drain":
            m, c = _stock(pid)  # a spend elsewhere (fleet, shop ...): recorded in the ledger as a negative credit
            _set_stock(pid, 0, 0)
            credited_m -= m
            credited_c -= c
        elif action == "credit":
            m, c = _stock(pid)
            scale = max(max(_cost_of_next(planet, t)) for t in types)  # credits sized to real prices
            add_m, add_c = rng.randint(0, scale), rng.randint(0, scale)
            _set_stock(pid, m + add_m, c + add_c)
            credited_m += add_m
            credited_c += add_c
        elif action == "arm":
            arm_reservation(uid, rng.choice(types), planet_id=pid, replace=rng.random() < 0.5)
        elif action == "evaluate":
            conn = _db()
            rows = conn.execute("SELECT id FROM build_reservations WHERE state = 'armed';").fetchall()
            conn.close()
            for row in rows:
                out = evaluate_reservation(_reservation(int(row["id"])))
                started += 1 if out["outcome"] == "started" else 0
        elif action == "manual":
            queue_build_for_planet(planet, {}, rng.choice(types), user_id=uid)
        elif action == "cancel":
            conn = _db()
            rows = conn.execute("SELECT id FROM build_reservations WHERE state = 'armed';").fetchall()
            conn.close()
            if rows:
                cancel_reservation(uid, int(rng.choice(rows)["id"]))
        elif action == "finish":
            conn = _db()
            conn.execute("UPDATE build_queue SET finish_time = ? WHERE planet_id = ?;", (time.time() - 1, pid))
            conn.commit()
            conn.close()

    conn = _db()
    try:
        per_reservation = conn.execute(
            "SELECT job_id, COUNT(*) AS n FROM build_reservations WHERE job_id IS NOT NULL GROUP BY job_id HAVING COUNT(*) > 1;"
        ).fetchall()
        armed_per_planet = conn.execute(
            "SELECT planet_id, COUNT(*) AS n FROM build_reservations WHERE state = 'armed' GROUP BY planet_id HAVING COUNT(*) > 1;"
        ).fetchall()
        started_rows = conn.execute("SELECT COUNT(*) AS n FROM build_reservations WHERE state = 'started';").fetchone()["n"]
    finally:
        conn.close()
    assert not per_reservation and not armed_per_planet
    assert started_rows == started
    assert len(_queue(pid)) <= 2  # the admin queue limit held throughout
    metal, crystal = _stock(pid)
    assert metal >= 0 and crystal >= 0
    # conservation: every unit that left the planet is a recorded, committed job price. The mines keep
    # producing while the test runs (a few units), so the stock may only be ABOVE the ledger by that
    # trickle - never below it (a double charge would be a whole price lower) and never by a price.
    trickle = max(200, int(0.05 * min(max(_cost_of_next(planet, t)) for t in types)))
    assert 0 <= metal - (start_m + credited_m - sum(d[0] for d in debits)) <= trickle
    assert 0 <= crystal - (start_c + credited_c - sum(d[1] for d in debits)) <= trickle
    assert started > 0, "the walk must actually start reservations, or it proves nothing"


# ---------------------------------------------------------------------------
# UI contract: template markers, JS handlers, locales (static checks, no browser)
# ---------------------------------------------------------------------------

_RESERVE_LOCALE_KEYS = [
    "reserve_btn", "reserve_btn_title", "reserve_strip_label", "reserve_strip_body", "reserve_wait_funds",
    "reserve_wait_slot", "reserve_wait_vacation", "reserve_cancel", "reserve_expires", "reserve_notice_started",
    "reserve_notice_superseded", "reserve_notice_invalid", "reserve_notice_replaced", "reserve_notice_player",
    "reserve_notice_expired", "reserve_err_affordable_now", "reserve_err_exists", "reserve_err_disabled",
    "reserve_err_vacation", "reserve_err_max_level", "reserve_err_not_armed",
]


def test_template_marks_the_card_states_and_hosts_the_strip():
    text = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    for marker in ('data-reason="resources"', 'data-reason="queue_full"', 'data-reason="requirements"', 'id="gc-build-reservation"'):
        assert marker in text, marker
    host = text[text.index('id="gc-build-reservation"'):][:200]
    assert "hidden" in host  # invisible until the server sends a reservation
    # ... and not rendered at all while the flag is off for the player
    assert "{% if reserve_next_enabled %}<div id=\"gc-build-reservation\"" in text


def test_main_js_wires_both_routes_and_the_error_texts():
    text = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    for needle in (
        '"/api/buildings/reserve"', '"/api/buildings/reserve/cancel"', "syncBuildReservationUi", "[data-build-reserve]",
        "[data-reserve-cancel-id]", "affordable_now:", "reservation_exists:",
    ):
        assert needle in text, needle
    # the sync must be a no-op without a server-sent reservation (flag off): it only acts on `.reservation`
    body = text[text.index("function syncBuildReservationUi"):][:600]
    assert "buildQueueRaw.reservation" in body and "info.enabled" in body


def test_every_locale_has_the_reservation_texts_with_the_same_placeholders():
    import json
    import re

    ph = re.compile(r"%\(([^)]+)\)s")
    base = json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))
    for key in _RESERVE_LOCALE_KEYS:
        assert key in base, key
    for loc in ("de", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for key in _RESERVE_LOCALE_KEYS:
            assert data.get(key), (loc, key)
            assert set(ph.findall(data[key])) == set(ph.findall(base[key])), (loc, key)


def test_action_response_state_carries_the_armed_reservation(world):
    import importlib

    import app as app_module

    uid, planet = world
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    _set_stock(planet["id"], POOR, POOR)
    body = client.post("/api/buildings/reserve", json={"building_type": "metal_mine", "planet_id": planet["id"]}).get_json()
    assert body["ok"] is True
    resv = body["state"]["build_queue"]["reservation"]
    assert resv["enabled"] is True and resv["armed"]["building_type"] == "metal_mine" and resv["armed"]["waiting_for"] == "funds"
    cancelled = client.post("/api/buildings/reserve/cancel", json={"reservation_id": resv["armed"]["id"]}).get_json()
    after = cancelled["state"]["build_queue"]["reservation"]
    assert after["armed"] is None and after["last_ended"]["reason"] == "player"


def test_game_state_has_no_reservation_key_when_the_flag_is_off(world, monkeypatch):
    import importlib

    import app as app_module

    uid, planet = world
    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    state = client.get("/api/game-state").get_json()
    assert state.get("ok") is True and "reservation" not in (state.get("build_queue") or {})


# ---------------------------------------------------------------------------
# PostgreSQL gate: real row locks, real partial unique indexes, real concurrent transactions
# (run with GC_RESERVE_TEST_BACKEND=postgres + GC_TEST_POSTGRES_URL; skipped otherwise)
# ---------------------------------------------------------------------------


def _run_threads(count: int, target) -> list:
    barrier = threading.Barrier(count)
    results: list = [None] * count
    errors: list = []

    def runner(i: int) -> None:
        try:
            barrier.wait(timeout=20)
            results[i] = target(i)
        except BaseException as exc:  # pragma: no cover - reported by the caller
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)
    assert not errors, errors
    return results


@postgres_only
def test_postgres_worker_never_waits_for_a_planet_row_another_transaction_holds(world):
    """SKIP LOCKED: a transaction holds the planet (e.g. a manual click mid-flight) -> the worker leaves at once."""
    from game.db import begin_write_transaction, lock_planet_for_update, rollback

    uid, planet = world
    pid = int(planet["id"])
    res = _arm_poor(uid, planet)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(pid, cost_m * 3, cost_c * 3)
    before = _stock(pid)

    holder = _db()
    try:
        begin_write_transaction(holder)
        lock_planet_for_update(holder, pid)  # SELECT ... FOR UPDATE, held until rollback below
        started = time.monotonic()
        out = _evaluate(res["id"])
        elapsed = time.monotonic() - started
        assert out["outcome"] == "skipped" and out.get("reason") == "lock_busy", out
        assert elapsed < 5.0, f"the worker waited {elapsed:.1f}s for a locked planet (lock_timeout would be 15s)"
        assert _stock(pid) == before and _queue(pid) == []
        assert _reservation(res["id"])["state"] == "armed"
    finally:
        rollback(holder)
        holder.close()

    assert _evaluate(res["id"])["outcome"] == "started"  # the next beat gets it
    assert _stock(pid) == (before[0] - cost_m, before[1] - cost_c) and len(_queue(pid)) == 1


@postgres_only
def test_postgres_eight_workers_over_twelve_rounds_charge_exactly_one_price_per_round(world):
    from game.build_reservations import evaluate_reservation

    uid, planet = world
    pid = int(planet["id"])
    cost_m, cost_c = _cost_of_next(planet)
    for _ in range(12):
        res = _arm_poor(uid, planet)
        _set_stock(pid, cost_m * 10, cost_c * 10)
        snapshot = _reservation(res["id"])
        outcomes = _run_threads(8, lambda _i: evaluate_reservation(dict(snapshot))["outcome"])
        assert outcomes.count("started") == 1, outcomes
        assert set(outcomes) <= {"started", "skipped"}, outcomes
        assert len(_queue(pid)) == 1
        assert _stock(pid) == (cost_m * 9, cost_c * 9)
        conn = _db()
        conn.execute("DELETE FROM build_queue WHERE planet_id = ?;", (pid,))
        conn.commit()
        conn.close()


@postgres_only
def test_postgres_concurrent_arming_leaves_exactly_one_armed_row(world):
    from game.build_reservations import cancel_reservation, arm_reservation

    uid, planet = world
    pid = int(planet["id"])
    kinds = ("metal_mine", "crystal_mine")
    for _ in range(10):
        _set_stock(pid, POOR, POOR)
        results = _run_threads(2, lambda i: arm_reservation(uid, kinds[i], planet_id=pid)[:2])
        assert sorted(r[1] for r in results) == ["ok", "reservation_exists"], results
        conn = _db()
        try:
            armed = conn.execute("SELECT id FROM build_reservations WHERE planet_id = ? AND state = 'armed';", (pid,)).fetchall()
        finally:
            conn.close()
        assert len(armed) == 1
        assert cancel_reservation(uid, int(armed[0]["id"]))[:2] == (True, "ok")


@postgres_only
def test_postgres_one_request_id_from_six_threads_is_one_reservation(world):
    from game.build_reservations import arm_reservation

    uid, planet = world
    pid = int(planet["id"])
    _set_stock(pid, POOR, POOR)
    results = _run_threads(6, lambda _i: arm_reservation(uid, "metal_mine", planet_id=pid, request_id="same-click"))
    assert all(r[0] and r[1] == "ok" for r in results), [r[:2] for r in results]
    assert len({int(r[2]["reservation"]["id"]) for r in results}) == 1
    conn = _db()
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM build_reservations WHERE player_id = ? AND request_id = 'same-click';", (uid,)).fetchone()["c"]
    finally:
        conn.close()
    assert int(count) == 1


@postgres_only
def test_postgres_manual_click_racing_the_worker_never_charges_one_level_twice(world):
    """The player clicks the very building they reserved while the worker starts it: one job per level, exact debit."""
    from game.build_reservations import evaluate_reservation
    from game.buildings import get_upgrade_cost, queue_build_for_planet

    uid, planet = world
    pid = int(planet["id"])
    level = int(models.get_planet_buildings(pid).get("metal_mine", 0) or 0)
    price_l = tuple(int(x) for x in get_upgrade_cost("metal_mine", level))
    price_l1 = tuple(int(x) for x in get_upgrade_cost("metal_mine", level + 1))
    seen = set()
    for _ in range(10):
        res = _arm_poor(uid, planet)
        _set_stock(pid, RICH, RICH)
        snapshot = _reservation(res["id"])

        def act(i: int):
            if i == 0:
                return ("worker", evaluate_reservation(dict(snapshot))["outcome"])
            ok, reason, _p = queue_build_for_planet(planet, {}, "metal_mine", user_id=uid)
            return ("manual", ok)

        out = dict(_run_threads(2, act))
        jobs = len(_queue(pid))
        spent = (RICH - _stock(pid)[0], RICH - _stock(pid)[1])
        state = _reservation(res["id"])["state"]
        if state == "armed":  # the worker met the click's planet lock and left; the next beat settles it, free of charge
            assert jobs == 1 and spent == price_l, (out, jobs, spent)
            assert _evaluate(res["id"])["outcome"] == "superseded"
            assert (RICH - _stock(pid)[0], RICH - _stock(pid)[1]) == spent
            state = _reservation(res["id"])["state"]
            assert state == "cancelled"
        if jobs == 1:  # one side won the level; the other did nothing (superseded) -> exactly one price of that level
            assert spent == price_l, (out, spent)
        else:  # worker took level L, the manual click became level L+1 -> two different levels, two prices
            assert jobs == 2 and spent == (price_l[0] + price_l1[0], price_l[1] + price_l1[1]), (out, jobs, spent)
            assert state == "started"
        seen.add(jobs)
        conn = _db()
        conn.execute("DELETE FROM build_queue WHERE planet_id = ?;", (pid,))
        conn.commit()
        conn.close()
    assert seen  # coverage marker: at least one of the two legal interleavings occurred


@postgres_only
def test_postgres_prune_reports_zero_when_nothing_is_old(world):
    """The PostgreSQL cursor wrapper reports 'no rows' as -1; the pruning count must still be a plain 0."""
    from game.build_reservations import prune_ended

    assert prune_ended(time.time()) == 0


# ---------------------------------------------------------------------------
# gate 3: flag isolation - OFF is today's behaviour exactly, TEST admits only the listed accounts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, mode",
    [
        (None, "off"), ("", "off"), ("off", "off"), ("OFF", "off"), ("0", "off"), ("false", "off"), ("no", "off"),
        ("garbage", "off"), ("tset", "off"), ("on ", "on"), ("ON", "on"), ("1", "on"), ("true", "on"), ("yes", "on"),
        ("all", "on"), ("test", "test"), (" Test ", "test"), ("allowlist", "test"), ("beta", "test"),
    ],
)
def test_flag_values_fail_closed(monkeypatch, raw, mode):
    from game.config import reserve_next_purchase_mode

    if raw is None:
        monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    else:
        monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", raw)
    assert reserve_next_purchase_mode() == mode


def test_allow_list_parsing_and_test_mode_edges(monkeypatch):
    from game.config import is_reserve_next_purchase_enabled_for, reserve_next_purchase_user_ids

    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "test")
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE_USER_IDS", "abc, ,12;13, -4 ,x7, 014")
    assert reserve_next_purchase_user_ids() == frozenset({12, 13, 14})
    assert is_reserve_next_purchase_enabled_for(12) and is_reserve_next_purchase_enabled_for(14)
    assert not is_reserve_next_purchase_enabled_for(11) and not is_reserve_next_purchase_enabled_for(None)
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE_USER_IDS", "")
    assert not is_reserve_next_purchase_enabled_for(12)  # test mode with an empty list admits nobody
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "off")
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE_USER_IDS", "12")
    assert not is_reserve_next_purchase_enabled_for(12)  # the list never switches the feature on by itself


def _touch_every_reservation_entry_point(uid: int, planet: dict) -> dict:
    """Everything the feature adds to a running game: payload, guard, autoplay, heartbeat, both routes, game state, page."""
    import importlib

    import app as app_module
    from flask import Flask

    from game.auto_empire import plan_passive_planet_tick
    from game.build_reservations import arm_reservation, cancel_reservation, planet_has_armed_reservation, run_reservation_tick
    from game.buildings import get_build_queue_status_for_planet, queue_build_for_planet

    pid = int(planet["id"])
    out: dict = {}
    conn = _db()
    try:
        with Flask("gc_reserve_isolation").test_request_context("/"):
            out["payload"] = get_build_queue_status_for_planet(pid, conn=conn, skip_finish=True)
        out["guard"] = planet_has_armed_reservation(conn, pid, uid)
        out["autoplay"] = plan_passive_planet_tick(conn, player_id=uid, planet=planet, allow_research=False, allow_defense=False, now=time.time())
        conn.commit()
    finally:
        conn.close()
    out["arm"] = arm_reservation(uid, "metal_mine", planet_id=pid)[:2]
    out["cancel"] = cancel_reservation(uid, 1)[:2]
    out["tick"] = run_reservation_tick()
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    out["route_arm"] = client.post("/api/buildings/reserve", json={"building_type": "metal_mine", "planet_id": pid}).get_json()
    out["route_cancel"] = client.post("/api/buildings/reserve/cancel", json={"reservation_id": 1}).get_json()
    out["state"] = client.get("/api/game-state").get_json()
    page = client.get("/buildings")
    out["page_status"] = page.status_code
    out["page"] = page.get_data(as_text=True)
    ok, _reason, _job = queue_build_for_planet(planet, {}, "metal_mine", user_id=uid)  # the manual path, as ever
    out["manual_ok"] = ok
    return out


@sqlite_only
def test_flag_off_touches_the_reservation_table_nowhere_and_adds_nothing_visible(world, monkeypatch):
    """Positive control included: with the flag ON the same walk DOES query the table and render the strip host."""
    import sqlite3

    uid, planet = world
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m * 20, cost_c * 20)

    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    del statements[:]
    off = _touch_every_reservation_entry_point(uid, planet)
    touched = [s for s in statements if "build_reservations" in s.lower()]
    assert touched == [], touched[:3]
    assert "reservation" not in off["payload"] and off["guard"] is False
    assert off["arm"] == (False, "disabled") and off["cancel"] == (False, "disabled")
    assert off["tick"] == {"enabled": False, "evaluated": 0, "outcomes": {}, "errors": 0}
    assert off["route_arm"].get("ok") is False and off["route_arm"].get("reason") == "disabled"
    assert off["route_cancel"].get("ok") is False and off["route_cancel"].get("reason") == "disabled"
    assert "reservation" not in (off["state"].get("build_queue") or {})
    assert off["page_status"] == 200 and 'id="gc-build-reservation"' not in off["page"]
    assert off["manual_ok"] is True  # the manual build path is untouched

    # positive control: the walk is not vacuous - switched on, it reaches the table and the page
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "on")
    conn = _db()
    conn.execute("DELETE FROM build_queue WHERE planet_id = ?;", (int(planet["id"]),))
    conn.commit()
    conn.close()
    del statements[:]
    on = _touch_every_reservation_entry_point(uid, planet)
    assert any("build_reservations" in s.lower() for s in statements)
    assert on["payload"]["reservation"]["enabled"] is True
    assert on["page_status"] == 200 and 'id="gc-build-reservation"' in on["page"]


def test_test_mode_admits_only_the_listed_accounts_at_every_entry_point(world, monkeypatch):
    from flask import Flask

    from game.build_reservations import arm_reservation, cancel_reservation, planet_has_armed_reservation, run_reservation_tick
    from game.buildings import get_build_queue_status_for_planet

    uid, planet = world
    ok, err, info = models.create_user("reserve_other", "secret123")
    assert ok, err
    other = int(info["id"])
    oplanet = dict(models.get_homeworld(player_id=other))
    assert other != uid

    mine = _arm_poor(uid, planet)  # both hold an armed row, as if a wider test phase had run before
    _set_stock(oplanet["id"], POOR, POOR)
    ok, reason, payload = arm_reservation(other, "metal_mine", planet_id=int(oplanet["id"]))
    assert ok and reason == "ok", (reason, payload)
    theirs = payload["reservation"]

    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "test")
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE_USER_IDS", str(uid))
    cost_m, cost_c = _cost_of_next(planet)
    _set_stock(planet["id"], cost_m * 3, cost_c * 3)
    _set_stock(oplanet["id"], cost_m * 3, cost_c * 3)

    assert arm_reservation(other, "crystal_mine", planet_id=int(oplanet["id"]))[:2] == (False, "disabled")
    assert cancel_reservation(other, int(theirs["id"]))[:2] == (False, "disabled")
    conn = _db()
    try:
        with Flask("gc_reserve_test_mode").test_request_context("/"):
            assert "reservation" not in get_build_queue_status_for_planet(int(oplanet["id"]), conn=conn, skip_finish=True)
            assert get_build_queue_status_for_planet(int(planet["id"]), conn=conn, skip_finish=True)["reservation"]["enabled"] is True
        assert planet_has_armed_reservation(conn, int(oplanet["id"]), other) is False  # the autoplay guard stays silent for them
        assert planet_has_armed_reservation(conn, int(planet["id"]), uid) is True
    finally:
        conn.close()

    tick = run_reservation_tick()
    assert tick["enabled"] is True
    assert _reservation(mine["id"])["state"] == "started"
    still = _reservation(theirs["id"])
    assert still["state"] == "armed" and _queue(oplanet["id"]) == [] and _stock(oplanet["id"]) == (cost_m * 3, cost_c * 3)
    assert _evaluate(theirs["id"])["outcome"] == "disabled"  # even a worker that is handed their row declines it


# ---------------------------------------------------------------------------
# an idle tab must learn that a reservation ended (diet poll version / ?since= short-circuit)
# ---------------------------------------------------------------------------


def test_poll_fingerprint_reads_the_reservation_only_while_the_feature_is_on():
    from game.live_state import compute_poll_version, poll_slim_from_payload

    base = {"build_queue": {"queue": []}, "research": {"queue": []}, "energy": {}, "active_planet": {"id": 1}}
    assert "reservation" not in poll_slim_from_payload(base)  # off: the legacy slim dict, key for key
    off_version = compute_poll_version(base)
    on_idle = {**base, "build_queue": {"queue": [], "reservation": {"enabled": True, "armed": None, "last_ended": None}}}
    on_armed = {**base, "build_queue": {"queue": [], "reservation": {"enabled": True, "armed": {"id": 7}, "last_ended": None}}}
    on_ended = {**base, "build_queue": {"queue": [], "reservation": {"enabled": True, "armed": None, "last_ended": {"id": 7}}}}
    assert poll_slim_from_payload(on_armed)["reservation"] == [7, 0] and poll_slim_from_payload(on_ended)["reservation"] == [0, 7]
    assert len({compute_poll_version(p) for p in (on_idle, on_armed, on_ended)}) == 3
    # a payload whose reservation block says "disabled" hashes exactly like one without the block
    disabled = {**base, "build_queue": {"queue": [], "reservation": {"enabled": False}}}
    assert compute_poll_version(disabled) == off_version


def test_probe_version_changes_when_a_reservation_arms_and_when_it_ends_without_touching_the_queue(world, monkeypatch):
    from game.build_reservations import evaluate_reservation
    from game.live_state import clear_diet_poll_fingerprint, probe_poll_version, try_diet_poll_early_unchanged

    uid, planet = world

    def probe():
        conn = _db()
        try:
            return probe_poll_version(uid, conn)
        finally:
            conn.close()

    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    legacy = probe()
    assert legacy is not None

    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "on")
    idle = probe()
    res = _arm_poor(uid, planet)
    armed = probe()
    assert len({idle, armed}) == 2 and armed != legacy

    # the idle tab polls with the version it has: unchanged while nothing moved ...
    clear_diet_poll_fingerprint(uid)
    conn = _db()
    try:
        assert (try_diet_poll_early_unchanged(uid, armed, conn=conn) or {}).get("unchanged") is True
    finally:
        conn.close()

    # ... and a full state the moment the reservation ends WITHOUT a queue change (expiry)
    _set_reservation(res["id"], expires_at=time.time() - 5)
    assert evaluate_reservation(_reservation(res["id"]))["outcome"] == "expired"
    ended = probe()
    assert ended not in (armed, idle)
    clear_diet_poll_fingerprint(uid)
    conn = _db()
    try:
        assert try_diet_poll_early_unchanged(uid, armed, conn=conn) is None  # not "unchanged": the client gets the new state
    finally:
        conn.close()

    # switching the feature off restores the legacy version exactly - the armed/ended rows are invisible again
    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
    assert probe() == legacy


def test_probe_fingerprint_equals_the_one_read_from_the_full_reservation_payload(world):
    """The cheap probe and the full payload derive the same two facts, or the idle short-circuit would misfire."""
    from game.build_reservations import evaluate_reservation, planet_reservation_payload, reservation_poll_fingerprint
    from game.live_state import _reservation_fp_for_poll

    uid, planet = world
    pid = int(planet["id"])

    def both():
        conn = _db()
        try:
            full = _reservation_fp_for_poll({"build_queue": {"reservation": planet_reservation_payload(conn, pid, uid)}})
            return full, reservation_poll_fingerprint(conn, pid, uid)
        finally:
            conn.close()

    assert both() == ([0, 0], [0, 0])
    res = _arm_poor(uid, planet)
    full, probe = both()
    assert full == probe == [int(res["id"]), 0]
    _set_reservation(res["id"], expires_at=time.time() - 5)
    assert evaluate_reservation(_reservation(res["id"]))["outcome"] == "expired"
    full, probe = both()
    assert full == probe == [0, int(res["id"])]
    # the 24 h window of "last ended" ages out the same way on both sides
    conn = _db()
    try:
        later = time.time() + 2 * 86400
        aged_full = _reservation_fp_for_poll({"build_queue": {"reservation": planet_reservation_payload(conn, pid, uid, now=later)}})
        assert aged_full == reservation_poll_fingerprint(conn, pid, uid, now=later) == [0, 0]
    finally:
        conn.close()
