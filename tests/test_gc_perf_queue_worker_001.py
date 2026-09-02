"""GC-PERF-QUEUE-WORKER-001 — keep due queue completion out of HTTP."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from game.tick_runner import list_players_with_due_work, run_tick

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
    monkeypatch.setattr("game.tick_runner.list_players_with_due_work", lambda **_kw: [])

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
