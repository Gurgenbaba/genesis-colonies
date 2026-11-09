"""Executable reference model of "reserve next purchase" (building queue) - sandbox only, NOT game code.

Specifies and tests the server-side contract of the feature (``docs/GC_RESERVE_NEXT_PURCHASE.md``) against an in-memory / file SQLite
database with a minimal schema: ``planets`` (stock), ``buildings`` (levels), ``build_queue`` (jobs, charged at enqueue exactly like the game's
``queue_build_for_planet``), ``build_reservations`` (the new table).  The model uses the same primitives the game uses: one write
transaction per planet (``begin_write_transaction`` + ``lock_planet_for_update`` in the game, ``BEGIN IMMEDIATE`` here) and an atomic
conditional ``UPDATE planets ... WHERE metal >= ? AND crystal >= ?`` (``try_spend_resources_conn`` in the game).

The contract in one paragraph: a reservation is an *intent*, it holds no resources and changes no timer.  It is started by the
same transaction that charges the canonical cost at that moment and enqueues the job; the reservation row is claimed by a
compare-and-swap (``armed -> started``) and the job row carries a UNIQUE ``reservation_id``, so a replayed tick, a second worker or a retried
request can never charge twice.  There is no backdating: a job never starts before the moment it was evaluated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS planets (
    id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL,
    metal INTEGER NOT NULL,
    crystal INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS buildings (
    planet_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    level INTEGER NOT NULL,
    PRIMARY KEY (planet_id, building_type)
);
CREATE TABLE IF NOT EXISTS build_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    start_time REAL NOT NULL,
    finish_time REAL NOT NULL,
    cost_metal INTEGER NOT NULL,
    cost_crystal INTEGER NOT NULL,
    reservation_id INTEGER UNIQUE
);
CREATE TABLE IF NOT EXISTS build_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    expected_level INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('armed', 'started', 'cancelled', 'expired')),
    reason TEXT,
    request_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    job_id INTEGER,
    UNIQUE (player_id, request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_armed_reservation_per_planet ON build_reservations (planet_id) WHERE state = 'armed';
"""

STATES = ("armed", "started", "cancelled", "expired")
CANCEL_REASONS = ("player", "replaced", "superseded", "invalid", "expired")


@dataclass
class Rules:
    """The canonical rules the start path must re-apply at the moment of the start (injected so the model needs no game data)."""

    queue_limit: int = 3
    expiry_sec: float = 48 * 3600.0
    max_level: int = 50
    cost: Callable[[str, int], Tuple[int, int]] = lambda bt, level: ((level + 1) * 100, (level + 1) * 40)  # cost of the upgrade FROM ``level``
    duration: Callable[[str, int], float] = lambda bt, target: 600.0 * target
    requirements: Callable[[Dict[str, int], str], bool] = lambda levels, bt: bt != "shipyard" or levels.get("command_center", 0) >= 2
    building_types: Tuple[str, ...] = ("metal_mine", "crystal_mine", "solar_plant", "command_center", "shipyard")


@dataclass
class Result:
    ok: bool
    reason: str
    reservation_id: Optional[int] = None
    job_id: Optional[int] = None
    charged: Tuple[int, int] = (0, 0)
    extra: Dict[str, Any] = field(default_factory=dict)


def connect(path: str = ":memory:", *, timeout: float = 5.0) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=timeout, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def _levels(conn: sqlite3.Connection, planet_id: int) -> Dict[str, int]:
    return {r["building_type"]: int(r["level"]) for r in conn.execute("SELECT building_type, level FROM buildings WHERE planet_id = ?", (planet_id,))}


def _queued(conn: sqlite3.Connection, planet_id: int) -> List[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM build_queue WHERE planet_id = ? ORDER BY finish_time", (planet_id,)))


def _target_level(levels: Dict[str, int], queue: List[sqlite3.Row], building_type: str) -> int:
    return levels.get(building_type, 0) + sum(1 for q in queue if q["building_type"] == building_type) + 1


def _cancel(conn: sqlite3.Connection, reservation_id: int, state: str, reason: str, now: float) -> bool:
    cur = conn.execute(
        "UPDATE build_reservations SET state = ?, reason = ?, updated_at = ? WHERE id = ? AND state = 'armed'",
        (state, reason, now, reservation_id),
    )
    return cur.rowcount == 1


def arm(
    conn: sqlite3.Connection,
    rules: Rules,
    *,
    player_id: int,
    planet_id: int,
    building_type: str,
    request_id: str,
    now: float,
    replace: bool = False,
    vacation: bool = False,
) -> Result:
    """Register the intent to build ``building_type`` next on ``planet_id``.  Holds nothing, charges nothing."""
    _begin(conn)
    try:
        dup = conn.execute("SELECT id, state FROM build_reservations WHERE player_id = ? AND request_id = ?", (player_id, request_id)).fetchone()
        if dup is not None:
            conn.execute("COMMIT")
            return Result(True, "duplicate", reservation_id=int(dup["id"]), extra={"state": dup["state"]})
        planet = conn.execute("SELECT * FROM planets WHERE id = ?", (planet_id,)).fetchone()
        if planet is None or int(planet["player_id"]) != int(player_id):
            conn.execute("ROLLBACK")
            return Result(False, "not_owner")
        if vacation:
            conn.execute("ROLLBACK")
            return Result(False, "vacation")
        if building_type not in rules.building_types:
            conn.execute("ROLLBACK")
            return Result(False, "invalid_type")
        levels, queue = _levels(conn, planet_id), _queued(conn, planet_id)
        target = _target_level(levels, queue, building_type)
        if target > rules.max_level:
            conn.execute("ROLLBACK")
            return Result(False, "max_level")
        if not rules.requirements(levels, building_type):
            conn.execute("ROLLBACK")
            return Result(False, "requirements")
        cost_m, cost_c = rules.cost(building_type, target - 1)
        if len(queue) < rules.queue_limit and int(planet["metal"]) >= cost_m and int(planet["crystal"]) >= cost_c:
            conn.execute("ROLLBACK")  # could start right now: the normal enqueue path is the right tool, a reservation would only delay it
            return Result(False, "affordable_now", extra={"cost": (cost_m, cost_c)})
        existing = conn.execute("SELECT id FROM build_reservations WHERE planet_id = ? AND state = 'armed'", (planet_id,)).fetchone()
        if existing is not None:
            if not replace:
                conn.execute("ROLLBACK")
                return Result(False, "reservation_exists", reservation_id=int(existing["id"]))
            _cancel(conn, int(existing["id"]), "cancelled", "replaced", now)
        cur = conn.execute(
            "INSERT INTO build_reservations (player_id, planet_id, building_type, expected_level, state, request_id, created_at, updated_at, expires_at)"
            " VALUES (?, ?, ?, ?, 'armed', ?, ?, ?, ?)",
            (player_id, planet_id, building_type, target, request_id, now, now, now + rules.expiry_sec),
        )
        conn.execute("COMMIT")
        return Result(True, "armed", reservation_id=int(cur.lastrowid), extra={"expected_level": target, "cost": (cost_m, cost_c)})
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def cancel(conn: sqlite3.Connection, *, player_id: int, reservation_id: int, now: float) -> Result:
    """Player cancels the intent.  Nothing was charged, so nothing is refunded; a started reservation is cancelled through its job (canonical refund rules)."""
    _begin(conn)
    try:
        row = conn.execute("SELECT * FROM build_reservations WHERE id = ? AND player_id = ?", (reservation_id, player_id)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return Result(False, "not_found")
        if row["state"] == "armed" and _cancel(conn, reservation_id, "cancelled", "player", now):
            conn.execute("COMMIT")
            return Result(True, "cancelled", reservation_id=reservation_id)
        conn.execute("ROLLBACK")
        return Result(False, "already_started" if row["state"] == "started" else "not_armed", reservation_id=reservation_id)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def evaluate(
    conn: sqlite3.Connection,
    rules: Rules,
    *,
    planet_id: int,
    now: float,
    vacation: bool = False,
    fail_after_spend: bool = False,
) -> Optional[Result]:
    """Evaluate the armed reservation of one planet.  Safe to call any number of times, from any number of workers.

    ``fail_after_spend`` is a test hook: raises after the stock was debited and before the commit, to prove that the transaction is the only
    thing that makes the charge real.
    """
    try:
        _begin(conn)
    except sqlite3.OperationalError:
        return Result(False, "skipped_locked")  # a background worker never waits behind a request that owns the planet
    try:
        res = conn.execute("SELECT * FROM build_reservations WHERE planet_id = ? AND state = 'armed'", (planet_id,)).fetchone()
        if res is None:
            conn.execute("ROLLBACK")
            return None
        rid = int(res["id"])
        if vacation:
            conn.execute("ROLLBACK")
            return Result(False, "paused", reservation_id=rid)
        if now >= float(res["expires_at"]):
            _cancel(conn, rid, "expired", "expired", now)
            conn.execute("COMMIT")
            return Result(False, "expired", reservation_id=rid)
        bt = str(res["building_type"])
        levels, queue = _levels(conn, planet_id), _queued(conn, planet_id)
        target = _target_level(levels, queue, bt)
        if target != int(res["expected_level"]):
            _cancel(conn, rid, "cancelled", "superseded", now)  # the level the player meant is no longer the next one (manual enqueue, finished job, another actor)
            conn.execute("COMMIT")
            return Result(False, "superseded", reservation_id=rid)
        if target > rules.max_level or not rules.requirements(levels, bt):
            _cancel(conn, rid, "cancelled", "invalid", now)
            conn.execute("COMMIT")
            return Result(False, "invalid", reservation_id=rid)
        if len(queue) >= rules.queue_limit:
            conn.execute("ROLLBACK")
            return Result(False, "waiting_slot", reservation_id=rid)
        cost_m, cost_c = rules.cost(bt, target - 1)  # the canonical cost AT THE START, not the cost seen when arming
        spent = conn.execute(
            "UPDATE planets SET metal = metal - ?, crystal = crystal - ? WHERE id = ? AND metal >= ? AND crystal >= ?",
            (cost_m, cost_c, planet_id, cost_m, cost_c),
        )
        if spent.rowcount != 1:
            conn.execute("ROLLBACK")
            return Result(False, "waiting_funds", reservation_id=rid, extra={"cost": (cost_m, cost_c)})
        if fail_after_spend:
            raise RuntimeError("injected failure after the debit")
        start = max([now] + [float(q["finish_time"]) for q in queue])
        finish = start + rules.duration(bt, target)
        cur = conn.execute(
            "INSERT INTO build_queue (planet_id, building_type, start_time, finish_time, cost_metal, cost_crystal, reservation_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (planet_id, bt, start, finish, cost_m, cost_c, rid),
        )
        job_id = int(cur.lastrowid)
        claimed = conn.execute(
            "UPDATE build_reservations SET state = 'started', job_id = ?, updated_at = ? WHERE id = ? AND state = 'armed'",
            (job_id, now, rid),
        )
        if claimed.rowcount != 1:  # lost the race: undo the debit and the job together
            conn.execute("ROLLBACK")
            return Result(False, "lost_race", reservation_id=rid)
        conn.execute("COMMIT")
        return Result(True, "started", reservation_id=rid, job_id=job_id, charged=(cost_m, cost_c), extra={"start_time": start, "finish_time": finish})
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def tick(conn: sqlite3.Connection, rules: Rules, *, now: float, vacation_players: Tuple[int, ...] = ()) -> List[Result]:
    """One pass of the background worker: evaluate every planet that has an armed reservation."""
    out: List[Result] = []
    for row in list(conn.execute("SELECT DISTINCT planet_id, player_id FROM build_reservations WHERE state = 'armed'")):
        r = evaluate(conn, rules, planet_id=int(row["planet_id"]), now=now, vacation=int(row["player_id"]) in vacation_players)
        if r is not None:
            out.append(r)
    return out


def manual_enqueue(conn: sqlite3.Connection, rules: Rules, *, planet_id: int, building_type: str, now: float) -> Result:
    """The player's (or autoplay's) ordinary enqueue, the model of ``queue_build_for_planet``: validates, debits atomically, appends the job."""
    _begin(conn)
    try:
        levels, queue = _levels(conn, planet_id), _queued(conn, planet_id)
        target = _target_level(levels, queue, building_type)
        if target > rules.max_level or not rules.requirements(levels, building_type):
            conn.execute("ROLLBACK")
            return Result(False, "invalid")
        if len(queue) >= rules.queue_limit:
            conn.execute("ROLLBACK")
            return Result(False, "queue_full")
        cost_m, cost_c = rules.cost(building_type, target - 1)
        spent = conn.execute(
            "UPDATE planets SET metal = metal - ?, crystal = crystal - ? WHERE id = ? AND metal >= ? AND crystal >= ?",
            (cost_m, cost_c, planet_id, cost_m, cost_c),
        )
        if spent.rowcount != 1:
            conn.execute("ROLLBACK")
            return Result(False, "resources")
        start = max([now] + [float(q["finish_time"]) for q in queue])
        cur = conn.execute(
            "INSERT INTO build_queue (planet_id, building_type, start_time, finish_time, cost_metal, cost_crystal) VALUES (?, ?, ?, ?, ?, ?)",
            (planet_id, building_type, start, start + rules.duration(building_type, target), cost_m, cost_c),
        )
        conn.execute("COMMIT")
        return Result(True, "queued", job_id=int(cur.lastrowid), charged=(cost_m, cost_c))
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def finish_due(conn: sqlite3.Connection, *, planet_id: int, now: float) -> int:
    """Complete jobs whose finish time has passed (the level rises); the next reservation can only be evaluated after this."""
    _begin(conn)
    try:
        due = list(conn.execute("SELECT * FROM build_queue WHERE planet_id = ? AND finish_time <= ?", (planet_id, now)))
        for q in due:
            conn.execute(
                "INSERT INTO buildings (planet_id, building_type, level) VALUES (?, ?, 1) ON CONFLICT(planet_id, building_type) DO UPDATE SET level = level + 1",
                (planet_id, q["building_type"]),
            )
            conn.execute("DELETE FROM build_queue WHERE id = ?", (q["id"],))
        conn.execute("COMMIT")
        return len(due)
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def audit(conn: sqlite3.Connection, rules: Rules, *, funded: Dict[int, Tuple[int, int]], baseline: Optional[Dict[Tuple[int, str], int]] = None) -> List[str]:
    """Check the invariants of the contract; ``funded[planet_id]`` = (metal, crystal) ever credited (start stock + production), ``baseline`` = levels that
    existed before the run (not paid from the stock).  Returns violations."""
    bad: List[str] = []
    for p in conn.execute("SELECT * FROM planets"):
        pid = int(p["id"])
        spent_m = conn.execute("SELECT COALESCE(SUM(cost_metal), 0) FROM build_queue WHERE planet_id = ?", (pid,)).fetchone()[0]
        spent_c = conn.execute("SELECT COALESCE(SUM(cost_crystal), 0) FROM build_queue WHERE planet_id = ?", (pid,)).fetchone()[0]
        done_m, done_c = _completed_spend(conn, pid, rules, baseline or {})
        if int(p["metal"]) < 0 or int(p["crystal"]) < 0:
            bad.append(f"planet {pid}: negative stock")
        if int(p["metal"]) + spent_m + done_m != funded[pid][0] or int(p["crystal"]) + spent_c + done_c != funded[pid][1]:
            bad.append(f"planet {pid}: stock + charged != credited (resources created or lost)")
        if conn.execute("SELECT COUNT(*) FROM build_queue WHERE planet_id = ?", (pid,)).fetchone()[0] > rules.queue_limit:
            bad.append(f"planet {pid}: queue over the limit")
        if conn.execute("SELECT COUNT(*) FROM build_reservations WHERE planet_id = ? AND state = 'armed'", (pid,)).fetchone()[0] > 1:
            bad.append(f"planet {pid}: more than one armed reservation")
    for r in conn.execute("SELECT * FROM build_reservations"):
        jobs = conn.execute("SELECT COUNT(*) FROM build_queue WHERE reservation_id = ?", (r["id"],)).fetchone()[0]
        if r["state"] == "started" and r["job_id"] is None:
            bad.append(f"reservation {r['id']}: started without a job")
        if r["state"] != "started" and jobs:
            bad.append(f"reservation {r['id']}: job exists although the state is {r['state']}")
        if jobs > 1:
            bad.append(f"reservation {r['id']}: {jobs} jobs (double charge)")
    return bad


def _completed_spend(conn: sqlite3.Connection, planet_id: int, rules: Rules, baseline: Dict[Tuple[int, str], int]) -> Tuple[int, int]:
    """Cost of every finished level (levels are bought one by one, the model has no other source of levels)."""
    m = c = 0
    for row in conn.execute("SELECT building_type, level FROM buildings WHERE planet_id = ?", (planet_id,)):
        for lvl in range(baseline.get((planet_id, row["building_type"]), 0), int(row["level"])):
            cm, cc = rules.cost(row["building_type"], lvl)
            m, c = m + cm, c + cc
    return m, c
