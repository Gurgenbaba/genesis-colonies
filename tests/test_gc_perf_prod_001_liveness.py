"""GC-PERF-PROD-001 — liveness vs readiness + request phase wall splits."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def test_healthz_is_alive_without_deep_checks(game_client):
    client, _pid = game_client
    res = client.get("/healthz")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["status"] == "alive"
    assert "checks" not in data
    assert "total_ms" not in data


def test_health_readiness_includes_per_check_timings(game_client):
    client, _pid = game_client
    res = client.get("/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "ok"
    assert isinstance(data.get("total_ms"), (int, float))
    checks = data["checks"]
    for key in ("database", "migrations", "writable", "config"):
        assert key in checks
        assert "duration_ms" in checks[key]
        assert float(checks[key]["duration_ms"]) >= 0.0


def test_dockerfile_healthcheck_targets_healthz():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "/healthz" in text


def test_request_perf_wall_phase_keys():
    from game.live_state import _REQUEST_PERF_PHASE_KEYS

    for key in ("before_request_ms", "handler_ms", "after_request_ms"):
        assert key in _REQUEST_PERF_PHASE_KEYS


def test_request_perf_records_wall_phases(game_client, monkeypatch, caplog):
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    client, _pid = game_client

    caplog.set_level("INFO")
    resp = client.get("/healthz")
    assert resp.status_code == 200
    perf_logs = [rec.message for rec in caplog.records if "[GC REQUEST PERF]" in rec.message]
    assert perf_logs, "expected a request-perf log for sampled /healthz"
    joined = " ".join(perf_logs)
    assert "before_request_ms=" in joined
    assert "handler_ms=" in joined
    assert "after_request_ms=" in joined
