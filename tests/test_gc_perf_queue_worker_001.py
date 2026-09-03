"""GC-PERF-QUEUE-WORKER-001 — keep due queue completion out of HTTP."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from game.tick_runner import list_due_work_scopes, list_players_with_due_work, run_tick
from scripts.run_game_worker import (
    _queue_heartbeat_interval,
    _queue_tick_has_activity,
    _should_persist_queue_heartbeat,
)

ROOT = Path(__file__).resolve().parents[1]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE players (id INTEGER PRIMARY KEY);
        CREATE TABLE planets (id INTEGER PRIMARY KEY, player_id INTEGER);
        CREATE TABLE build_queue (id INTEGER PRIMARY KEY, planet_id INTEGER, finish_time REAL);
        CREATE TABLE research_queue (id INTEGER PRIMARY KEY, user_id INTEGER, finish_at REAL);
        CREATE TABLE planet_research_queue (id INTEGER PRIMARY KEY, planet_id INTEGER, finish_at REAL);
        CREATE TABLE planet_ascension_queue (id INTEGER PRIMARY KEY, planet_id INTEGER, state TEXT, finish_at REAL);
        CREATE TABLE shipyard_queue (id INTEGER PRIMARY KEY, planet_id INTEGER, status TEXT, finish_at REAL);
        CREATE TABLE defense_queue (id INTEGER PRIMARY KEY, planet_id INTEGER, status TEXT, finish_at REAL);
        CREATE TABLE troop_queue (id INTEGER PRIMARY KEY, player_id INTEGER, planet_id INTEGER, status TEXT, finish_at REAL);
        """
    )
    for pid in range(1, 8):
        conn.execute("INSERT INTO players(id) VALUES (?);", (pid,))
        conn.execute("INSERT INTO planets(id, player_id) VALUES (?, ?);", (pid * 10, pid))
    conn.commit()
    return conn


def test_due_candidate_scan_covers_all_server_queue_families(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    conn = _conn()
    try:
        due = 100.0
        conn.execute("INSERT INTO build_queue VALUES (1, 10, ?);", (due,))
        conn.execute("INSERT INTO research_queue VALUES (1, 2, ?);", (due,))
        conn.execute("INSERT INTO planet_research_queue VALUES (1, 30, ?);", (due,))
        conn.execute("INSERT INTO planet_ascension_queue VALUES (1, 40, 'active', ?);", (due,))
        conn.execute("INSERT INTO shipyard_queue VALUES (1, 50, 'queued', ?);", (due,))
        conn.execute("INSERT INTO defense_queue VALUES (1, 60, 'queued', ?);", (due,))
        conn.execute("INSERT INTO troop_queue VALUES (1, 7, 70, 'queued', ?);", (due,))
        conn.commit()

        assert list_players_with_due_work(now=101.0, conn=conn) == [1, 2, 3, 4, 5, 6, 7]
        scopes = list_due_work_scopes(now=101.0, conn=conn)
        assert scopes[1] == {"planet_ids": {10}, "account_research": False}
        assert scopes[2] == {"planet_ids": set(), "account_research": True}
        assert scopes[3] == {"planet_ids": {30}, "account_research": False}
        assert scopes[7] == {"planet_ids": {70}, "account_research": False}
    finally:
        conn.close()


def test_future_and_inactive_optional_jobs_do_not_trigger_worker(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    conn = _conn()
    try:
        conn.execute("INSERT INTO shipyard_queue VALUES (1, 10, 'queued', 200.0);")
        conn.execute("INSERT INTO defense_queue VALUES (1, 20, 'completed', 50.0);")
        conn.execute("INSERT INTO planet_ascension_queue VALUES (1, 30, 'completed', 50.0);")
        conn.execute("INSERT INTO troop_queue VALUES (1, 4, 40, 'cancelled', 50.0);")
        conn.commit()
        assert list_players_with_due_work(now=100.0, conn=conn) == []
    finally:
        conn.close()


def test_queue_only_tick_never_runs_global_fleet_or_retention(monkeypatch):
    monkeypatch.setattr("game.tick_runner.list_due_work_scopes", lambda **_kw: {})

    def forbidden(*_a, **_kw):
        raise AssertionError("queue-only worker must not run maintenance tail")

    monkeypatch.setattr("game.fleet_worker.run_fleet_worker", forbidden)
    monkeypatch.setattr("game.messages.purge_expired_inbox_messages", forbidden)

    result = run_tick(
        source="queue_worker",
        persist=False,
        include_fleet_tail=False,
        include_inbox_retention=False,
    )
    assert result["ok"] is True
    assert result["players_processed"] == 0
    assert result["finished"]["fleet_arrivals"] == 0
    assert result["finished"]["inbox_purged"] == 0


def test_queue_only_tick_finishes_exact_planet_scopes_without_maintenance(monkeypatch):
    monkeypatch.setattr(
        "game.tick_runner.list_due_work_scopes",
        lambda **_kw: {
            7: {"planet_ids": {72, 71}, "account_research": True},
        },
    )
    calls = []

    def fake_finish(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "finished": {"buildings": 1},
            "affected_players": [7],
            "affected_planets": [kwargs.get("planet_id")]
            if kwargs.get("planet_id")
            else [],
            "errors": [],
            "skipped_locked_planets": [],
        }

    monkeypatch.setattr("game.tick_runner.finish_due_work", fake_finish)
    result = run_tick(
        source="queue_worker",
        persist=False,
        include_fleet_tail=False,
        include_inbox_retention=False,
    )

    assert result["players_processed"] == 1
    assert result["planet_scopes_processed"] == 2
    assert result["account_scopes_processed"] == 1
    assert [call.get("planet_id") for call in calls] == [71, 72, None]
    for call in calls:
        assert call["include_fleet"] is False
        assert call["include_relocations"] is False
    assert calls[0]["include_account_research"] is False
    assert calls[1]["include_account_research"] is False
    assert calls[0]["skip_locked_planets"] is True
    assert calls[1]["skip_locked_planets"] is True
    assert calls[2]["include_planet_queues"] is False
    assert "skip_locked_planets" not in calls[2]


def test_postgres_planet_try_lock_is_nonblocking_skip_locked(monkeypatch):
    import game.db as dbmod

    class _Result:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _FakeConn:
        def __init__(self, row):
            self.row = row
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append((sql, params))
            return _Result(self.row)

    monkeypatch.setattr(dbmod, "get_db_backend", lambda: "postgres")
    busy = _FakeConn(None)
    assert dbmod.try_lock_planet_for_update(busy, 175) is False
    assert len(busy.calls) == 1
    assert "FOR UPDATE SKIP LOCKED" in busy.calls[0][0]
    assert busy.calls[0][1] == (175,)

    free = _FakeConn({"id": 175})
    assert dbmod.try_lock_planet_for_update(free, 175) is True


def test_docker_enables_queue_sidecar_only_for_postgres_by_default():
    src = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert 'GAME_WORKER="${GC_GAME_WORKER:-auto}"' in src
    assert "postgres|postgresql) GAME_WORKER=1" in src
    assert "python scripts/run_game_worker.py --queue-only" in src
    assert "export GC_GAME_WORKER_PRIMARY=1" in src
    assert "Queue worker sidecar off" in src


def test_game_worker_queue_only_passes_tail_kill_switches():
    src = (ROOT / "scripts" / "run_game_worker.py").read_text(encoding="utf-8")
    assert 'parser.add_argument(\n        "--queue-only"' in src
    assert "include_fleet_tail=False" in src
    assert "include_inbox_retention=False" in src
    assert "persist=False" in src
    assert "record_queue_tick_result" in src
    assert 'f"planet_scopes=' in src
    assert 'f"account_scopes=' in src


def test_idle_queue_worker_heartbeat_defaults_to_fifteen_seconds(monkeypatch):
    monkeypatch.delenv("GC_GAME_WORKER_HEARTBEAT_SEC", raising=False)
    assert _queue_heartbeat_interval(5.0) == 15.0


def test_queue_worker_heartbeat_interval_never_runs_faster_than_tick(monkeypatch):
    monkeypatch.setenv("GC_GAME_WORKER_HEARTBEAT_SEC", "5")
    assert _queue_heartbeat_interval(20.0) == 20.0
    monkeypatch.setenv("GC_GAME_WORKER_HEARTBEAT_SEC", "999")
    assert _queue_heartbeat_interval(5.0) == 30.0


def test_idle_ticks_skip_runtime_state_write_until_heartbeat_due():
    idle = {"ok": True, "players_processed": 0, "finished": {"buildings": 0}}
    assert _queue_tick_has_activity(idle) is False
    assert _should_persist_queue_heartbeat(
        idle,
        now_mono=100.0,
        last_persist_mono=90.0,
        heartbeat_sec=15.0,
    ) is False
    assert _should_persist_queue_heartbeat(
        idle,
        now_mono=106.0,
        last_persist_mono=90.0,
        heartbeat_sec=15.0,
    ) is True


def test_real_queue_work_and_errors_persist_immediately():
    work = {
        "ok": True,
        "players_processed": 1,
        "finished": {"buildings": 1, "research": 0},
    }
    failed = {
        "ok": False,
        "players_processed": 0,
        "finished": {},
        "errors": ["boom"],
    }
    for result in (work, failed):
        assert _queue_tick_has_activity(result) is True
        assert _should_persist_queue_heartbeat(
            result,
            now_mono=101.0,
            last_persist_mono=100.0,
            heartbeat_sec=15.0,
        ) is True
