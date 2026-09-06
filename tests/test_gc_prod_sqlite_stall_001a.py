"""GC-PROD-SQLITE-STALL-001A — queue heartbeat, single-flight claim, fleet deferral, score dirty."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from game.db import db
from game.fleet_worker import (
    FLEET_WORKER_KEY,
    is_fleet_worker_heartbeat_fresh,
    record_fleet_worker_result,
)
from game.logic import read_player_live_state_for_poll
from game.queue_poll import (
    clear_poll_due_claim_for_tests,
    should_poll_attempt_queue_finish,
    try_claim_poll_due_finish,
)
from game.runtime_state import (
    QUEUE_TICK_KEY,
    is_queue_tick_heartbeat_fresh,
    record_queue_tick_result,
    set_runtime_value,
)
from game.score_events import get_player_score_dirty

pytest_plugins = ["tests.test_game_state_live"]


def _stamp_queue_tick(*, ok: bool = True, at: float | None = None) -> None:
    at_i = int(at if at is not None else time.time())
    record_queue_tick_result(
        {
            "ok": ok,
            "source": "test_queue_worker",
            "scope": "due",
            "finished": {"build": 1},
            "affected_players": [],
            "batches": 1,
            "players_processed": 1,
            "duration_ms": 10,
            "errors": [] if ok else ["boom"],
            "at": at_i,
        }
    )
    # record_queue_tick_result overwrites at with time.time() in payload — force exact at
    set_runtime_value(
        QUEUE_TICK_KEY,
        json.dumps(
            {
                "at": at_i,
                "ok": ok,
                "source": "test_queue_worker",
                "scope": "due",
                "finished": {"build": 1},
                "affected_players": [],
                "batches": 1,
                "players_processed": 1,
                "duration_ms": 10,
                "errors": [] if ok else ["boom"],
            },
            ensure_ascii=False,
        ),
    )


def _enqueue_due_build(uid: int, *, finish_offset: float = -5.0) -> int:
    conn = db()
    try:
        planet = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? ORDER BY id LIMIT 1;",
            (int(uid),),
        ).fetchone()
        assert planet is not None
        pid = int(planet["id"])
        now = time.time()
        cur = conn.execute(
            """
            INSERT INTO build_queue (planet_id, building_type, start_time, finish_time)
            VALUES (?, 'metal_mine', ?, ?);
            """,
            (pid, now - 60.0, now + float(finish_offset)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_queue_tick_heartbeat_fresh_and_stale(monkeypatch):
    monkeypatch.setenv("GC_QUEUE_TICK_FRESH_SEC", "30")
    _stamp_queue_tick(at=time.time())
    assert is_queue_tick_heartbeat_fresh() is True

    _stamp_queue_tick(at=time.time() - 120)
    assert is_queue_tick_heartbeat_fresh() is False

    conn = db()
    try:
        conn.execute("DELETE FROM runtime_state WHERE key = ?;", (QUEUE_TICK_KEY,))
        conn.commit()
    finally:
        conn.close()
    assert is_queue_tick_heartbeat_fresh() is False


def test_poll_defers_queue_finish_when_queue_tick_fresh(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    monkeypatch.setenv("GC_QUEUE_TICK_FRESH_SEC", "60")
    _stamp_queue_tick(at=time.time())
    job_id = _enqueue_due_build(int(uid))
    clear_poll_due_claim_for_tests(int(uid))

    allowed, reason = should_poll_attempt_queue_finish(int(uid))
    assert allowed is False
    assert reason == "queue_tick_fresh_defer"

    calls = {"n": 0}
    import game.queue_engine as qe

    orig = qe.finish_player_due_work

    def _track(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(qe, "finish_player_due_work", _track)

    conn = db()
    try:
        read_player_live_state_for_poll(int(uid), conn=conn)
        row = conn.execute(
            "SELECT 1 FROM build_queue WHERE id = ? LIMIT 1;", (job_id,)
        ).fetchone()
        assert row is not None, "due build must remain when queue-tick heartbeat is fresh"
    finally:
        conn.close()
    assert calls["n"] == 0


def test_poll_safety_net_finishes_when_queue_tick_stale(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    monkeypatch.setenv("GC_QUEUE_TICK_FRESH_SEC", "30")
    _stamp_queue_tick(at=time.time() - 120)
    job_id = _enqueue_due_build(int(uid))
    clear_poll_due_claim_for_tests(int(uid))

    allowed, reason = should_poll_attempt_queue_finish(int(uid))
    assert allowed is True
    assert reason == "safety_net_due"

    conn = db()
    try:
        read_player_live_state_for_poll(int(uid), conn=conn)
        row = conn.execute(
            "SELECT 1 FROM build_queue WHERE id = ? LIMIT 1;", (job_id,)
        ).fetchone()
        assert row is None, "stale queue-tick must allow poll safety-net finish"
    finally:
        conn.close()


def test_poll_safety_net_finishes_when_queue_tick_missing(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    conn = db()
    try:
        conn.execute("DELETE FROM runtime_state WHERE key = ?;", (QUEUE_TICK_KEY,))
        conn.commit()
    finally:
        conn.close()
    job_id = _enqueue_due_build(int(uid))
    clear_poll_due_claim_for_tests(int(uid))

    allowed, reason = should_poll_attempt_queue_finish(int(uid))
    assert allowed is True
    assert reason == "safety_net_due"

    conn = db()
    try:
        read_player_live_state_for_poll(int(uid), conn=conn)
        row = conn.execute(
            "SELECT 1 FROM build_queue WHERE id = ? LIMIT 1;", (job_id,)
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_try_claim_single_flight_same_player(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_POLL_DUE_CLAIM_SEC", "5")
    clear_poll_due_claim_for_tests(int(uid))
    assert try_claim_poll_due_finish(int(uid), lease_sec=5.0) is True
    assert try_claim_poll_due_finish(int(uid), lease_sec=5.0) is False


def test_try_claim_expired_lease_recovers(game_client, monkeypatch):
    _client, uid = game_client
    clear_poll_due_claim_for_tests(int(uid))
    assert try_claim_poll_due_finish(int(uid), lease_sec=0.5) is True
    time.sleep(0.6)
    clear_poll_due_claim_for_tests(int(uid))  # clear process-local; persisted until may remain
    # Force expired persisted claim
    set_runtime_value(
        f"queue_finish_poll_claim:{int(uid)}",
        json.dumps({"until": time.time() - 1.0}),
    )
    with __import__("game.queue_poll", fromlist=["_LOCAL_CLAIMS"])._LOCAL_CLAIM_LOCK:
        from game import queue_poll as qp

        qp._LOCAL_CLAIMS.pop(int(uid), None)
    assert try_claim_poll_due_finish(int(uid), lease_sec=5.0) is True


def test_try_claim_independent_players(game_client, monkeypatch):
    client, uid = game_client
    # second player via register if fixture only one — use uid and uid+offset via DB insert skip;
    # claim keys differ by player_id even if second player is synthetic id.
    clear_poll_due_claim_for_tests(int(uid))
    clear_poll_due_claim_for_tests(int(uid) + 99991)
    assert try_claim_poll_due_finish(int(uid), lease_sec=5.0) is True
    assert try_claim_poll_due_finish(int(uid) + 99991, lease_sec=5.0) is True


def test_claim_loser_does_not_call_finish(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    conn = db()
    try:
        conn.execute("DELETE FROM runtime_state WHERE key = ?;", (QUEUE_TICK_KEY,))
        conn.commit()
    finally:
        conn.close()
    _enqueue_due_build(int(uid))
    clear_poll_due_claim_for_tests(int(uid))
    assert try_claim_poll_due_finish(int(uid), lease_sec=30.0) is True

    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("finish must not run for claim loser")

    monkeypatch.setattr("game.queue_engine.finish_player_due_work", _boom)

    conn = db()
    try:
        # Loser path: attempt allowed but claim fails → no finish
        read_player_live_state_for_poll(int(uid), conn=conn)
    finally:
        conn.close()
    assert calls["n"] == 0


def test_concurrent_claims_exactly_one_winner(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_POLL_DUE_CLAIM_SEC", "5")
    clear_poll_due_claim_for_tests(int(uid))
    # Clear process-local between threads by not pre-claiming; each thread starts clean
    # Use separate local maps simulation: clear then race with barrier
    results = []
    barrier = threading.Barrier(8)

    def _worker():
        # Each thread clears only its view of local claim by competing on shared _LOCAL_CLAIMS
        barrier.wait(timeout=5)
        results.append(try_claim_poll_due_finish(int(uid), lease_sec=5.0))

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_worker) for _ in range(8)]
        for f in futs:
            f.result(timeout=10)
    assert sum(1 for x in results if x) == 1
    assert sum(1 for x in results if not x) == 7


def test_poll_safety_net_marks_score_dirty(game_client, monkeypatch):
    """update_scores=True on poll finish must mark dirty (not skipped)."""
    _client, uid = game_client
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    conn = db()
    try:
        conn.execute("DELETE FROM runtime_state WHERE key = ?;", (QUEUE_TICK_KEY,))
        conn.execute("DELETE FROM player_score_dirty WHERE player_id = ?;", (int(uid),))
        conn.commit()
    finally:
        conn.close()
    _enqueue_due_build(int(uid))
    clear_poll_due_claim_for_tests(int(uid))

    conn = db()
    try:
        read_player_live_state_for_poll(int(uid), conn=conn)
        dirty = get_player_score_dirty(int(uid), conn=conn)
        assert dirty is not None
        assert int(dirty.get("dirty_version") or 0) >= 1
    finally:
        conn.close()


def test_fleet_heartbeat_fresh_does_not_block_due_poll_fleet_tick(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    monkeypatch.setenv("GC_FLEET_WORKER_FRESH_SEC", "120")
    # Fresh queue tick keeps queue work deferred. Fleet heartbeat freshness must
    # not suppress a genuinely due player fleet deadline.
    _stamp_queue_tick(at=time.time())
    record_fleet_worker_result(
        {
            "ok": True,
            "processed_arrivals": 0,
            "processed_returns": 0,
            "processed_holding": 0,
            "duration_ms": 1,
            "errors": [],
        },
        source="test",
    )
    # Force at fresh
    set_runtime_value(
        FLEET_WORKER_KEY,
        json.dumps(
            {
                "at": time.time(),
                "ok": True,
                "source": "test",
                "processed_arrivals": 0,
                "processed_returns": 0,
                "processed_holding": 0,
                "duration_ms": 1,
                "errors": [],
            }
        ),
    )
    assert is_fleet_worker_heartbeat_fresh() is True

    calls = {"n": 0}

    def _track(*_a, **_k):
        calls["n"] += 1
        return {
            "processed_arrivals": 0,
            "processed_returns": 0,
            "processed_holding": 0,
            "errors": [],
        }

    monkeypatch.setattr("game.fleet.process_fleet_tick", _track)
    monkeypatch.setattr(
        "game.queue_poll.player_fleet_is_dirty", lambda *_a, **_k: True
    )

    conn = db()
    try:
        read_player_live_state_for_poll(int(uid), conn=conn)
    finally:
        conn.close()
    assert calls["n"] == 1


def test_fleet_stale_uses_player_scoped_short_tx_tick(game_client, monkeypatch):
    _client, uid = game_client
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    _stamp_queue_tick(at=time.time())  # queues deferred
    set_runtime_value(
        FLEET_WORKER_KEY,
        json.dumps(
            {
                "at": time.time() - 10_000,
                "ok": True,
                "source": "test",
                "processed_arrivals": 0,
                "processed_returns": 0,
                "processed_holding": 0,
                "duration_ms": 1,
                "errors": [],
            }
        ),
    )
    seen = {}

    def _track(*, player_id=None, conn=None, manage_transaction=None, **_k):
        seen["player_id"] = player_id
        seen["manage_transaction"] = manage_transaction
        return {
            "processed_arrivals": 0,
            "processed_returns": 0,
            "processed_holding": 0,
            "errors": [],
        }

    monkeypatch.setattr("game.fleet.process_fleet_tick", _track)
    monkeypatch.setattr(
        "game.queue_poll.player_fleet_is_dirty", lambda *_a, **_k: True
    )

    conn = db()
    try:
        read_player_live_state_for_poll(int(uid), conn=conn)
    finally:
        conn.close()
    assert seen.get("player_id") == int(uid)
    # Deadline safety-net owns a dedicated connection/short-TX pass so a mass
    # return cannot expand or roll back the caller-owned request transaction.
    assert seen.get("manage_transaction") is True
