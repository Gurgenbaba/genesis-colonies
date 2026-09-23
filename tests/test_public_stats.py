"""
Public aggregate stats endpoint for the developer portfolio.

Run: python -m pytest tests/test_public_stats.py -v
"""

from __future__ import annotations

import sqlite3

import pytest
from flask import Flask

import game.public_stats as public_stats

NOW = 1_800_000_000


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, is_admin INTEGER NOT NULL DEFAULT 0,
                              last_seen INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE planets (id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL);
        CREATE TABLE fleet_movements (id INTEGER PRIMARY KEY, player_id INTEGER, status TEXT NOT NULL);
        CREATE TABLE alliances (id INTEGER PRIMARY KEY, tag TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO players (id, name, is_admin, last_seen) VALUES (?, ?, ?, ?)",
        [
            (1, "a", 0, NOW - 60),
            (2, "b", 0, NOW - 3 * 86400),
            (3, "c", 0, NOW - 3600),
            (4, "admin", 1, NOW),
        ],
    )
    conn.executemany("INSERT INTO planets (player_id) VALUES (?)", [(1,), (1,), (2,), (3,), (4,)])
    conn.executemany(
        "INSERT INTO fleet_movements (player_id, status) VALUES (?, ?)",
        [(1, "outbound"), (1, "returning"), (2, "holding"), (3, "completed"), (3, "cancelled"), (4, "outbound")],
    )
    conn.execute("INSERT INTO alliances (tag) VALUES ('GEN')")
    return conn


@pytest.fixture(autouse=True)
def _sqlite_backend(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    public_stats.reset_public_stats_cache()
    yield
    public_stats.reset_public_stats_cache()


def test_collect_counts_aggregates_only():
    stats = public_stats.collect_public_stats(_conn(), now=NOW)
    assert stats == {
        "players": 3,
        "active_24h": 2,
        "colonies": 4,
        "fleets_in_flight": 3,
        "alliances": 1,
        "generated_at": NOW,
    }


def test_collect_tolerates_missing_optional_tables():
    conn = _conn()
    conn.executescript("DROP TABLE fleet_movements; DROP TABLE alliances;")
    stats = public_stats.collect_public_stats(conn, now=NOW)
    assert stats["fleets_in_flight"] == 0
    assert stats["alliances"] == 0
    assert stats["colonies"] == 4


def _client(monkeypatch, payloads):
    calls = iter(payloads)

    def fake_collect(conn, *, now=None):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    class _FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(public_stats, "collect_public_stats", fake_collect)
    monkeypatch.setattr("game.db.db", lambda: _FakeConn())
    monkeypatch.setattr("game.db.rollback", lambda conn: None)
    app = Flask(__name__)
    public_stats.register_public_stats_routes(app)
    return app.test_client()


def test_route_sets_cors_only_for_allowed_origin(monkeypatch):
    client = _client(monkeypatch, [{"players": 7, "generated_at": NOW}])

    allowed = client.get("/api/public/stats", headers={"Origin": "https://gurgenbaba.github.io"})
    assert allowed.status_code == 200
    assert allowed.get_json() == {"ok": True, "players": 7, "generated_at": NOW}
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://gurgenbaba.github.io"
    assert allowed.headers["Cache-Control"].startswith("private")

    foreign = client.get("/api/public/stats", headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 200
    assert "Access-Control-Allow-Origin" not in foreign.headers


def test_route_caches_and_serves_last_good_payload(monkeypatch):
    client = _client(monkeypatch, [{"players": 1, "generated_at": NOW}, RuntimeError("db down")])
    assert client.get("/api/public/stats").get_json()["players"] == 1
    # Cached: the failing second collection is not reached yet.
    assert client.get("/api/public/stats").get_json()["players"] == 1

    public_stats._CACHE["expires_at"] = 0.0
    stale = client.get("/api/public/stats")
    assert stale.status_code == 200
    assert stale.get_json()["players"] == 1


def test_route_reports_unavailable_without_any_payload(monkeypatch):
    client = _client(monkeypatch, [RuntimeError("db down")])
    response = client.get("/api/public/stats")
    assert response.status_code == 503
    assert response.get_json() == {"ok": False, "error": "stats_unavailable"}
