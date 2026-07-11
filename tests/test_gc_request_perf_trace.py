"""
GC-PERF-REQUEST-TRACE — global slow-request profiling contracts.

Run: python -m pytest tests/test_gc_request_perf_trace.py -v
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc_request_perf_log_format_contract():
    src = _read("game/live_state.py")
    assert "[GC REQUEST PERF]" in src
    assert "db_begin_immediate_ms" in src
    assert "fleet_tick_ms" in src


def test_gc_request_perf_config_defaults(monkeypatch):
    from game.config import (
        get_request_perf_sample,
        get_request_perf_slow_ms,
        is_request_perf_debug_enabled,
    )

    monkeypatch.delenv("GC_REQUEST_PERF_DEBUG", raising=False)
    monkeypatch.delenv("GC_PERF_DEBUG", raising=False)
    monkeypatch.delenv("GC_REQUEST_PERF_SLOW_MS", raising=False)
    monkeypatch.delenv("GC_REQUEST_PERF_SAMPLE", raising=False)
    assert is_request_perf_debug_enabled() is False
    assert get_request_perf_slow_ms() == 500.0
    assert get_request_perf_sample() == 1.0


def test_gc_request_perf_gc_perf_debug_implies_request_perf(monkeypatch):
    from game.config import is_request_perf_debug_enabled

    monkeypatch.delenv("GC_REQUEST_PERF_DEBUG", raising=False)
    monkeypatch.setenv("GC_PERF_DEBUG", "1")
    assert is_request_perf_debug_enabled() is True


def test_gc_request_perf_invalid_env_clamps(monkeypatch):
    from game.config import get_request_perf_sample, get_request_perf_slow_ms

    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "not-a-number")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "99")
    assert get_request_perf_slow_ms() == 500.0
    assert get_request_perf_sample() == 1.0
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "-5")
    assert get_request_perf_sample() == 0.0


def test_gc_request_perf_helpers_noop_when_disabled():
    from game.live_state import (
        RequestPerfState,
        record_request_perf_phase,
        set_request_perf_meta,
        start_request_perf,
    )

    start_request_perf(method="GET", endpoint="x", path="/x")
    record_request_perf_phase("finish_ms", 100.0)
    set_request_perf_meta("finish_source", "game_state")
    state = RequestPerfState(sampled=True)
    state.phases["finish_ms"] = 10.0
    assert state.phases["finish_ms"] == 10.0


def test_gc_request_perf_phase_whitelist():
    from flask import Flask, g

    from game.live_state import record_request_perf_phase, start_request_perf

    app = Flask(__name__)
    with app.test_request_context("/"):
        g.gc_request_perf = type(
            "S",
            (),
            {"sampled": True, "phases": {}, "meta": {}, "sql_count": 0, "sql_write_count": 0},
        )()
        record_request_perf_phase("finish_ms", 5.0)
        record_request_perf_phase("not_allowed_key", 9.0)
        assert g.gc_request_perf.phases.get("finish_ms") == 5.0
        assert "not_allowed_key" not in g.gc_request_perf.phases


def test_gc_request_perf_disabled_no_log(game_client, monkeypatch, caplog):
    monkeypatch.delenv("GC_REQUEST_PERF_DEBUG", raising=False)
    monkeypatch.delenv("GC_PERF_DEBUG", raising=False)
    client, _pid = game_client

    with caplog.at_level(logging.INFO):
        resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert not any("[GC REQUEST PERF]" in rec.message for rec in caplog.records)


def test_gc_request_perf_under_threshold_no_log(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "999999")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    client, _pid = game_client

    with caplog.at_level(logging.INFO):
        resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert not any("[GC REQUEST PERF]" in rec.message for rec in caplog.records)


def test_gc_request_perf_slow_request_logs_once(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")

    clock = {"t": 1000.0}

    def _fake_perf_counter():
        clock["t"] += 0.001
        return clock["t"]

    monkeypatch.setattr("game.live_state.time.perf_counter", _fake_perf_counter)

    client, _pid = game_client
    with caplog.at_level(logging.INFO):
        resp = client.get("/api/game-state")
    assert resp.status_code == 200
    perf_logs = [rec for rec in caplog.records if "[GC REQUEST PERF]" in rec.message]
    assert len(perf_logs) == 1
    msg = perf_logs[0].message
    assert "method=GET" in msg
    assert "endpoint=api_game_state" in msg
    assert "status=200" in msg
    assert "total_ms=" in msg
    assert "finish_source=game_state" in msg


def test_gc_request_perf_sampling_zero_no_log(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "0.0")
    client, _pid = game_client

    with caplog.at_level(logging.INFO):
        resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert not any("[GC REQUEST PERF]" in rec.message for rec in caplog.records)


def test_gc_request_perf_panel_poll_meta(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    client, _pid = game_client

    with caplog.at_level(logging.INFO):
        resp = client.get("/api/game-state?include_panel=1")
    assert resp.status_code == 200
    perf_logs = [rec for rec in caplog.records if "[GC REQUEST PERF]" in rec.message]
    assert perf_logs
    msg = perf_logs[0].message
    assert "finish_source=game_state_panel" in msg
    assert "include_panel=1" in msg


def test_gc_request_perf_content_length_bytes(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")

    times = iter([2000.0, 2000.0, 2001.0])
    monkeypatch.setattr("game.live_state.time.perf_counter", lambda: next(times, 2001.0))

    client, _pid = game_client
    with caplog.at_level(logging.INFO):
        resp = client.get("/api/game-state")
    assert resp.status_code == 200
    perf_logs = [rec for rec in caplog.records if "[GC REQUEST PERF]" in rec.message]
    assert perf_logs
    assert "bytes=" in perf_logs[0].message


def test_gc_request_perf_phases_recorded(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    client, _pid = game_client

    with caplog.at_level(logging.INFO):
        resp = client.get("/api/game-state")
    assert resp.status_code == 200
    msg = next(rec.message for rec in caplog.records if "[GC REQUEST PERF]" in rec.message)
    assert "live_context_ms=" in msg
    assert "payload_ms=" in msg


def test_gc_request_perf_db_begin_immediate_timing(monkeypatch):
    from flask import Flask

    import game.db as dbmod
    from game.live_state import start_request_perf

    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")

    times = iter([0.0, 0.0, 0.5, 0.5])
    monkeypatch.setattr("game.db.time.perf_counter", lambda: next(times, 0.5))
    monkeypatch.setattr("game.live_state.time.perf_counter", lambda: next(iter([0.0]), 0.0))

    app = Flask(__name__)
    with app.test_request_context("/"):
        start_request_perf(method="GET", endpoint="test", path="/test")
        conn = dbmod.db()
        try:
            dbmod.begin_write_transaction(conn)
            dbmod.commit(conn)
        finally:
            conn.close()

        from flask import g

        state = g.gc_request_perf
        assert state is not None
        assert state.phases.get("db_begin_immediate_ms", 0) >= 0


def test_gc_request_perf_profiler_never_breaks_request(game_client, monkeypatch):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")

    def _boom(*_a, **_k):
        raise RuntimeError("perf broke")

    monkeypatch.setattr("game.live_state._emit_request_perf_log", _boom)
    client, _pid = game_client
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert resp.get_json().get("ok") is True


def test_gc_request_perf_dev_header_not_in_testing(game_client, monkeypatch):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    monkeypatch.setenv("APP_ENV", "development")
    client, _pid = game_client
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert "X-GC-Request-Perf-Total-Ms" in resp.headers
