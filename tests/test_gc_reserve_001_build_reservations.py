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


@pytest.fixture(scope="module")
def template_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("gc_reserve_template") / "template.db"
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(path)
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    result = subprocess.run([sys.executable, str(MIGRATE_SCRIPT)], cwd=str(ROOT), capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr or result.stdout
    return path


@pytest.fixture()
def world(template_db, tmp_path, monkeypatch):
    db_file = tmp_path / "reserve.db"
    shutil.copy(template_db, db_file)
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_RESERVE_NEXT_PURCHASE", "on")
    monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE_USER_IDS", raising=False)
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    models.init_db()
    ok, err, info = models.create_user("reserve_user", "secret123")
    assert ok, err
    uid = int(info["id"])
    planet = dict(models.get_homeworld(player_id=uid))
    return uid, planet


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
    with app.test_request_context("/"):
        on = get_build_queue_status_for_planet(int(planet["id"]), conn=_db(), skip_finish=True)
        assert on["reservation"]["armed"]["id"] == res["id"] and on["reservation"]["armed"]["waiting_for"] == "funds"
        monkeypatch.delenv("GC_RESERVE_NEXT_PURCHASE", raising=False)
        off = get_build_queue_status_for_planet(int(planet["id"]), conn=_db(), skip_finish=True)
        assert "reservation" not in off


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
    assert "hidden" in text[text.index('id="gc-build-reservation"'):][:200]  # invisible until the server sends a reservation


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
