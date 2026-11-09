"""Reserve-next-purchase: contract of the reference model + the analysis harness.  Sandbox only, no game code."""

from __future__ import annotations

import random
import sqlite3
import threading
from pathlib import Path

import pytest

from scripts import reserve_next_purchase_model as m

NOW = 1_000_000.0


def make(path: str = ":memory:", *, metal: int = 0, crystal: int = 0, levels=None, timeout: float = 5.0):
    conn = m.connect(path, timeout=timeout)
    conn.execute("INSERT INTO planets (id, player_id, metal, crystal) VALUES (1, 10, ?, ?)", (metal, crystal))
    conn.execute("INSERT INTO planets (id, player_id, metal, crystal) VALUES (2, 20, 0, 0)")
    for bt, lvl in (levels or {}).items():
        conn.execute("INSERT INTO buildings (planet_id, building_type, level) VALUES (1, ?, ?)", (bt, lvl))
    return conn


def stock(conn, pid: int = 1):
    r = conn.execute("SELECT metal, crystal FROM planets WHERE id = ?", (pid,)).fetchone()
    return int(r["metal"]), int(r["crystal"])


def credit(conn, metal: int, crystal: int = 0, pid: int = 1):
    conn.execute("UPDATE planets SET metal = metal + ?, crystal = crystal + ? WHERE id = ?", (metal, crystal, pid))


def arm(conn, rules, bt="metal_mine", rid="r1", now=NOW, **kw):
    return m.arm(conn, rules, player_id=kw.pop("player_id", 10), planet_id=kw.pop("planet_id", 1), building_type=bt, request_id=rid, now=now, **kw)


def jobs(conn):
    return list(conn.execute("SELECT * FROM build_queue ORDER BY id"))


# ---------------------------------------------------------------------------
# arming: validation and "holds nothing"
# ---------------------------------------------------------------------------


def test_arm_holds_no_resources_and_changes_no_timer():
    rules = m.Rules()
    conn = make(metal=50, levels={"metal_mine": 4})
    before = stock(conn)
    r = arm(conn, rules)
    assert r.ok and r.reason == "armed" and r.extra["expected_level"] == 5 and r.extra["cost"] == rules.cost("metal_mine", 4)
    assert stock(conn) == before and jobs(conn) == []  # no hold, no job


def test_arm_rejects_what_the_normal_queue_could_start_now():
    rules = m.Rules()
    conn = make(metal=10_000, crystal=10_000)
    r = arm(conn, rules)
    assert not r.ok and r.reason == "affordable_now"
    assert conn.execute("SELECT COUNT(*) FROM build_reservations").fetchone()[0] == 0


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({"player_id": 99}, "not_owner"),
        ({"planet_id": 2}, "not_owner"),
        ({"vacation": True}, "vacation"),
        ({"bt": "not_a_building"}, "invalid_type"),
        ({"bt": "shipyard"}, "requirements"),
    ],
)
def test_arm_server_side_validation(kwargs, expected):
    rules = m.Rules()
    conn = make(metal=0)
    r = arm(conn, rules, **kwargs)
    assert not r.ok and r.reason == expected
    assert conn.execute("SELECT COUNT(*) FROM build_reservations").fetchone()[0] == 0


def test_arm_rejects_max_level():
    rules = m.Rules(max_level=5)
    conn = make(levels={"metal_mine": 5})
    assert arm(conn, rules).reason == "max_level"


def test_arm_is_idempotent_per_request_id():
    rules = m.Rules()
    conn = make()
    a, b = arm(conn, rules, rid="same"), arm(conn, rules, rid="same")
    assert a.ok and b.ok and b.reason == "duplicate" and a.reservation_id == b.reservation_id
    assert conn.execute("SELECT COUNT(*) FROM build_reservations").fetchone()[0] == 1


def test_one_armed_reservation_per_planet_and_replace_is_explicit():
    rules = m.Rules()
    conn = make()
    first = arm(conn, rules, rid="a")
    second = arm(conn, rules, bt="crystal_mine", rid="b")
    assert not second.ok and second.reason == "reservation_exists" and second.reservation_id == first.reservation_id
    third = arm(conn, rules, bt="crystal_mine", rid="c", replace=True)
    assert third.ok
    states = {r["id"]: (r["state"], r["reason"]) for r in conn.execute("SELECT * FROM build_reservations")}
    assert states[first.reservation_id] == ("cancelled", "replaced") and states[third.reservation_id][0] == "armed"
    with pytest.raises(sqlite3.IntegrityError):  # the database itself refuses a second armed row, whatever the application does
        conn.execute(
            "INSERT INTO build_reservations (player_id, planet_id, building_type, expected_level, state, request_id, created_at, updated_at, expires_at)"
            " VALUES (10, 1, 'metal_mine', 1, 'armed', 'x', 0, 0, 1)"
        )


# ---------------------------------------------------------------------------
# starting: charge once, at the start price, never early
# ---------------------------------------------------------------------------


def test_starts_when_funds_arrive_and_charges_exactly_the_cost():
    rules = m.Rules()
    conn = make(metal=10, levels={"metal_mine": 2})
    arm(conn, rules)
    cost_m, cost_c = rules.cost("metal_mine", 2)
    waiting = m.evaluate(conn, rules, planet_id=1, now=NOW + 10)
    assert waiting.reason == "waiting_funds" and stock(conn) == (10, 0) and jobs(conn) == []
    credit(conn, cost_m + 7, cost_c + 3)
    started = m.evaluate(conn, rules, planet_id=1, now=NOW + 20)
    assert started.ok and started.charged == (cost_m, cost_c)
    assert stock(conn) == (10 + 7, 3)  # only the cost left the stock
    assert len(jobs(conn)) == 1 and jobs(conn)[0]["start_time"] == NOW + 20  # no backdating
    res = conn.execute("SELECT * FROM build_reservations").fetchone()
    assert res["state"] == "started" and res["job_id"] == jobs(conn)[0]["id"]


def test_cost_is_the_canonical_cost_at_the_start_not_at_arming():
    base = m.Rules()
    conn = make(metal=0, levels={"metal_mine": 1})
    arm(conn, base)
    seen_at_arming = base.cost("metal_mine", 1)
    dearer = m.Rules(cost=lambda bt, lvl: (base.cost(bt, lvl)[0] * 2, base.cost(bt, lvl)[1] * 2))  # e.g. an Ascension rebuild share changed meanwhile
    credit(conn, seen_at_arming[0], seen_at_arming[1])
    assert m.evaluate(conn, dearer, planet_id=1, now=NOW + 1).reason == "waiting_funds"
    credit(conn, seen_at_arming[0], seen_at_arming[1])
    r = m.evaluate(conn, dearer, planet_id=1, now=NOW + 2)
    assert r.ok and r.charged == dearer.cost("metal_mine", 1)


def test_replayed_evaluation_charges_once():
    rules = m.Rules()
    conn = make(levels={"metal_mine": 0})
    arm(conn, rules)
    credit(conn, 1_000, 1_000)
    first = m.evaluate(conn, rules, planet_id=1, now=NOW + 5)
    after_first = stock(conn)
    for k in range(5):
        assert m.evaluate(conn, rules, planet_id=1, now=NOW + 6 + k) is None  # nothing armed any more
    assert first.ok and stock(conn) == after_first and len(jobs(conn)) == 1


def test_failure_between_debit_and_commit_leaves_no_trace_and_the_retry_charges_once():
    rules = m.Rules()
    conn = make()
    arm(conn, rules)
    credit(conn, 1_000, 1_000)
    before = stock(conn)
    with pytest.raises(RuntimeError):
        m.evaluate(conn, rules, planet_id=1, now=NOW + 5, fail_after_spend=True)
    assert stock(conn) == before and jobs(conn) == []
    assert conn.execute("SELECT state FROM build_reservations").fetchone()[0] == "armed"
    assert m.evaluate(conn, rules, planet_id=1, now=NOW + 6).ok
    assert len(jobs(conn)) == 1 and stock(conn) != before


def test_two_workers_racing_on_one_reservation_start_it_exactly_once(tmp_path: Path):
    rules = m.Rules()
    path = str(tmp_path / "race.sqlite")
    seed = make(path)
    arm(seed, rules)
    credit(seed, 1_000, 1_000)
    start_stock = stock(seed)
    seed.close()
    barrier = threading.Barrier(4)
    results = []

    def worker():
        conn = m.connect(path, timeout=10.0)
        barrier.wait()
        results.append(m.evaluate(conn, rules, planet_id=1, now=NOW + 5))
        conn.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check = m.connect(path)
    started = [r for r in results if r is not None and r.reason == "started"]
    assert len(started) == 1
    assert len(jobs(check)) == 1
    assert stock(check) == (start_stock[0] - started[0].charged[0], start_stock[1] - started[0].charged[1])  # one debit, not four


def test_background_worker_never_waits_behind_a_planet_that_a_request_owns(tmp_path: Path):
    rules = m.Rules()
    path = str(tmp_path / "busy.sqlite")
    owner = make(path)
    arm(owner, rules)
    credit(owner, 1_000, 1_000)
    owner.execute("BEGIN IMMEDIATE")  # an action request holds the write lock
    worker = m.connect(path, timeout=0.05)
    r = m.evaluate(worker, rules, planet_id=1, now=NOW + 5)
    owner.execute("ROLLBACK")
    assert r is not None and r.reason == "skipped_locked"
    assert m.evaluate(worker, rules, planet_id=1, now=NOW + 6).ok  # the next heartbeat retries


# ---------------------------------------------------------------------------
# aborting: superseded, invalid, expired, paused, cancelled
# ---------------------------------------------------------------------------


def test_manual_enqueue_of_the_same_building_supersedes_the_reservation_without_a_second_charge():
    rules = m.Rules()
    conn = make(levels={"metal_mine": 3})
    armed = arm(conn, rules)
    credit(conn, 1_000, 1_000)
    assert armed.extra["expected_level"] == 4
    manual = m.manual_enqueue(conn, rules, planet_id=1, building_type="metal_mine", now=NOW + 5)
    after_manual = stock(conn)
    r = m.evaluate(conn, rules, planet_id=1, now=NOW + 6)
    assert manual.ok and r.reason == "superseded" and stock(conn) == after_manual and len(jobs(conn)) == 1
    row = conn.execute("SELECT state, reason FROM build_reservations").fetchone()
    assert (row["state"], row["reason"]) == ("cancelled", "superseded")


def test_full_queue_keeps_the_reservation_and_it_starts_when_a_slot_frees():
    rules = m.Rules(queue_limit=2)
    conn = make(levels={"command_center": 1})
    credit(conn, 100_000, 100_000)
    assert m.manual_enqueue(conn, rules, planet_id=1, building_type="solar_plant", now=NOW).ok
    assert m.manual_enqueue(conn, rules, planet_id=1, building_type="crystal_mine", now=NOW).ok
    armed = arm(conn, rules, bt="metal_mine")  # affordable, but the queue is full: waiting for the slot is exactly what a reservation is for
    assert armed.ok
    assert m.evaluate(conn, rules, planet_id=1, now=NOW + 1).reason == "waiting_slot"
    finish_first = min(float(j["finish_time"]) for j in jobs(conn))
    assert m.finish_due(conn, planet_id=1, now=finish_first) == 1
    r = m.evaluate(conn, rules, planet_id=1, now=finish_first)
    assert r.ok and r.extra["start_time"] >= max(float(j["finish_time"]) for j in jobs(conn) if j["reservation_id"] is None)  # behind the running job, like the canonical queue


def test_expiry_cancels_without_a_charge_and_vacation_pauses_instead():
    rules = m.Rules(expiry_sec=3600.0)
    conn = make()
    armed = arm(conn, rules)
    credit(conn, 1_000, 1_000)
    before = stock(conn)
    assert m.evaluate(conn, rules, planet_id=1, now=NOW + 7200, vacation=True).reason == "paused"
    assert conn.execute("SELECT state FROM build_reservations").fetchone()[0] == "armed" and stock(conn) == before
    expired = m.evaluate(conn, rules, planet_id=1, now=NOW + 7200)
    assert expired.reason == "expired" and expired.reservation_id == armed.reservation_id
    assert stock(conn) == before and jobs(conn) == []


def test_requirement_lost_cancels_as_invalid():
    rules = m.Rules(requirements=lambda levels, bt: levels.get("command_center", 0) >= 1)
    conn = make(levels={"command_center": 1})
    arm(conn, rules)
    conn.execute("UPDATE buildings SET level = 0 WHERE building_type = 'command_center'")
    credit(conn, 1_000, 1_000)
    r = m.evaluate(conn, rules, planet_id=1, now=NOW + 1)
    assert r.reason == "invalid" and jobs(conn) == []


def test_player_cancel_is_free_and_only_works_on_an_armed_reservation_of_the_owner():
    rules = m.Rules()
    conn = make()
    armed = arm(conn, rules)
    assert not m.cancel(conn, player_id=20, reservation_id=armed.reservation_id, now=NOW + 1).ok  # someone else's
    before = stock(conn)
    assert m.cancel(conn, player_id=10, reservation_id=armed.reservation_id, now=NOW + 1).ok and stock(conn) == before
    assert m.cancel(conn, player_id=10, reservation_id=armed.reservation_id, now=NOW + 2).reason == "not_armed"
    again = arm(conn, rules, rid="r2")
    credit(conn, 1_000, 1_000)
    assert m.evaluate(conn, rules, planet_id=1, now=NOW + 3).ok
    assert m.cancel(conn, player_id=10, reservation_id=again.reservation_id, now=NOW + 4).reason == "already_started"


# ---------------------------------------------------------------------------
# the whole contract under random operation sequences
# ---------------------------------------------------------------------------


def random_walk(seed: int, *, steps: int = 320, sabotage: bool = False):
    """A resource-poor random game: stock is scarce so reservations really wait, start, are superseded, expire and are replaced."""
    import collections

    rng = random.Random(seed)
    rules = m.Rules(queue_limit=3, expiry_sec=14 * 3600.0, cost=lambda bt, lvl: ((lvl + 1) * 320, (lvl + 1) * 130))  # dear upgrades: the stock lags behind the wishes
    conn = make(metal=60, crystal=20, levels={"command_center": 1})
    conn.execute("INSERT INTO planets (id, player_id, metal, crystal) VALUES (3, 10, 40, 10)")
    baseline = {(1, "command_center"): 1}
    funded = {1: (60, 20), 2: (0, 0), 3: (40, 10)}
    seen: "collections.Counter[str]" = collections.Counter()
    now = t_now = NOW
    types = list(rules.building_types)
    for step in range(steps):
        now += rng.uniform(60, 3000)
        pid = rng.choice([1, 3])
        op = rng.random()
        if op < 0.36:
            dm, dc = rng.randint(0, 260), rng.randint(0, 110)
            credit(conn, dm, dc, pid)
            funded[pid] = (funded[pid][0] + dm, funded[pid][1] + dc)
        elif op < 0.56:
            r = arm(conn, rules, bt=rng.choice(types), rid=f"s{seed}-{step}", now=now, planet_id=pid, replace=rng.random() < 0.25)
            seen["arm:" + r.reason] += 1
        elif op < 0.60:
            row = conn.execute("SELECT id FROM build_reservations WHERE planet_id = ? AND state = 'armed'", (pid,)).fetchone()
            if row:
                seen["cancel:" + m.cancel(conn, player_id=10, reservation_id=int(row["id"]), now=now).reason] += 1
        elif op < 0.68:
            armed_row = conn.execute("SELECT building_type FROM build_reservations WHERE planet_id = ? AND state = 'armed'", (pid,)).fetchone()
            bt = armed_row["building_type"] if armed_row is not None and rng.random() < 0.5 else rng.choice(types)  # often the very building a reservation waits for
            seen["manual:" + m.manual_enqueue(conn, rules, planet_id=pid, building_type=bt, now=now).reason] += 1
        elif op < 0.80:
            m.finish_due(conn, planet_id=pid, now=now)
        else:
            for r in m.tick(conn, rules, now=now):
                seen["tick:" + r.reason] += 1
            for r in m.tick(conn, rules, now=now):  # a duplicated heartbeat must change nothing
                assert r.reason != "started"
        if sabotage:  # a buggy start path that debits a started reservation a second time
            row = conn.execute("SELECT planet_id FROM build_queue WHERE reservation_id IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
            if row is not None and rng.random() < 0.2:
                conn.execute("UPDATE planets SET metal = MAX(0, metal - 5) WHERE id = ?", (row["planet_id"],))
        if step % 20 == 0:
            assert m.audit(conn, rules, funded=funded, baseline=baseline) == [] or sabotage
    m.tick(conn, rules, now=now)
    return conn, rules, funded, baseline, seen


@pytest.mark.parametrize("seed", range(10))
def test_random_sequences_never_create_resources_or_double_charge(seed: int):
    conn, rules, funded, baseline, _seen = random_walk(seed)
    assert m.audit(conn, rules, funded=funded, baseline=baseline) == []
    for r in conn.execute("SELECT id, job_id FROM build_reservations WHERE state = 'started'"):
        job = conn.execute("SELECT reservation_id FROM build_queue WHERE id = ?", (r["job_id"],)).fetchone()
        assert job is None or job["reservation_id"] == r["id"]  # a started reservation owns its job (finished jobs have left the queue table)


def test_the_random_walk_really_exercises_the_paths_it_claims_to():
    import collections

    total: "collections.Counter[str]" = collections.Counter()
    for seed in range(10):
        total.update(random_walk(seed)[4])
    assert total["tick:started"] >= 40 and total["tick:waiting_funds"] >= 100, dict(total)
    assert total["arm:armed"] >= 100 and total["arm:reservation_exists"] >= 20, dict(total)
    assert total["tick:superseded"] >= 3 and total["tick:expired"] >= 3 and total["tick:waiting_slot"] >= 3, dict(total)


def test_the_audit_detects_a_planted_double_debit():
    caught = 0
    for seed in range(10):
        conn, rules, funded, baseline, _ = random_walk(seed, sabotage=True)
        caught += bool(m.audit(conn, rules, funded=funded, baseline=baseline))
    assert caught >= 5  # the audit is not vacuous: it sees resources that vanished after a start
