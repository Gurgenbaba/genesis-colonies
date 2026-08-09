"""
GC-PERF remaining tickets — worker, state delta, cache, res interval, JS scaffold, load script.

Run: python -m pytest tests/test_gc_perf_core_suite.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def test_game_worker_primary_skips_interval_finish(monkeypatch):
    from game.config import is_game_worker_primary

    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")
    assert is_game_worker_primary() is True
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "0")
    assert is_game_worker_primary() is False


def test_resource_persist_interval_default(monkeypatch):
    from game.config import get_resource_persist_interval_sec

    monkeypatch.delenv("GC_RESOURCE_PERSIST_SEC", raising=False)
    assert get_resource_persist_interval_sec() == 600.0


def test_state_version_stable_for_same_payload():
    from game.live_state import compute_state_version

    payload = {
        "resources": {"metal": 1, "crystal": 2},
        "energy": {"total": 10, "used": 3},
        "build_queue": [],
        "notification_revision": "0:0:",
    }
    a = compute_state_version(payload)
    b = compute_state_version(payload)
    assert a == b
    assert isinstance(a, int)


def test_delta_unchanged_short_circuit():
    from game.live_state import build_delta_game_state, compute_state_version

    payload = {
        "ok": True,
        "server_time": 1.0,
        "resources": {"metal": 5},
        "energy": {},
        "build_queue": [],
        "notification_revision": "0:0:",
    }
    ver = compute_state_version(payload)
    payload["state_version"] = ver
    out = build_delta_game_state(payload, since=ver)
    assert out.get("unchanged") is True
    assert out.get("version") == ver
    assert "resources" not in out or out.get("unchanged")


def test_definition_cache_roundtrip():
    from game.definition_cache import bump_config_version, cached, cache_get, clear_definition_cache

    clear_definition_cache()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return {"ok": True}

    a = cached("unit-test-key", factory, ttl_sec=60)
    b = cached("unit-test-key", factory, ttl_sec=60)
    assert a == b == {"ok": True}
    assert calls["n"] == 1
    bump_config_version()
    assert cache_get("unit-test-key") is None


def test_queue_tick_cron_handler_unauthorized():
    from flask import Flask

    from game.internal_cron import handle_internal_cron_queue_tick

    app = Flask(__name__)
    with app.test_request_context("/api/internal/cron/queue-tick", method="POST"):
        from flask import request

        payload, status = handle_internal_cron_queue_tick(request)
    assert status == 401
    assert payload.get("ok") is False


def test_js_core_scaffold_files_exist():
    assert (ROOT / "static" / "js" / "core" / "gc.js").is_file()
    assert (ROOT / "static" / "js" / "core" / "state.js").is_file()
    assert (ROOT / "static" / "js" / "core" / "lifecycle.js").is_file()
    assert (ROOT / "static" / "js" / "pages" / "buildings.js").is_file()
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "js/core/gc.js" in base


def test_game_worker_and_load_scripts_exist():
    assert (ROOT / "scripts" / "run_game_worker.py").is_file()
    assert (ROOT / "scripts" / "perf_load_test.py").is_file()
    assert (ROOT / "docs" / "GC_PERF_DB_001_POSTGRES_AUDIT.md").is_file()


def test_diet_payload_has_state_version(game_client, monkeypatch):
    monkeypatch.delenv("GC_STATE_DELTA", raising=False)
    client, _pid = game_client
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True
    assert "state_version" in data  # GC-557C clock
    assert "poll_version" in data  # GC-PERF-STATE-002 fingerprint
    assert "buildings" not in data

    ver = int(data["poll_version"])
    resp2 = client.get(f"/api/game-state?since={ver}")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2.get("ok") is True
    if data2.get("unchanged") is True:
        assert int(data2.get("version") or data2.get("poll_version") or 0) == ver
    else:
        assert int(data2.get("poll_version") or data2.get("version") or 0) != 0


def test_delta_api_default_on_when_fingerprint_forced(game_client, monkeypatch):
    """GC-PERF-LIVE-001: delta short-circuit is default-on (no GC_STATE_DELTA=1 required)."""
    from game import live_state as ls

    monkeypatch.delenv("GC_STATE_DELTA", raising=False)
    monkeypatch.setattr(ls, "compute_poll_version", lambda _payload: 424242)

    client, _pid = game_client
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert int(resp.get_json()["poll_version"]) == 424242

    resp2 = client.get("/api/game-state?since=424242")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2.get("unchanged") is True
    assert int(data2.get("version")) == 424242


def test_delta_api_unchanged_when_fingerprint_forced(game_client, monkeypatch):
    """Force stable poll_version so ?since= short-circuit is deterministic."""
    from game import live_state as ls

    monkeypatch.setenv("GC_STATE_DELTA", "1")
    monkeypatch.setattr(ls, "compute_poll_version", lambda _payload: 424242)

    client, _pid = game_client
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    assert int(resp.get_json()["poll_version"]) == 424242

    resp2 = client.get("/api/game-state?since=424242")
    data2 = resp2.get_json()
    assert data2.get("unchanged") is True
    assert int(data2.get("version")) == 424242


def test_delta_api_can_be_disabled(game_client, monkeypatch):
    from game import live_state as ls

    monkeypatch.setenv("GC_STATE_DELTA", "0")
    monkeypatch.setattr(ls, "compute_poll_version", lambda _payload: 424242)
    monkeypatch.setattr(ls, "probe_poll_version", lambda *_a, **_k: 424242)

    client, _pid = game_client
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    resp2 = client.get("/api/game-state?since=424242")
    assert resp2.status_code == 200
    data2 = resp2.get_json()
    assert data2.get("unchanged") is not True
    assert "poll_version" in data2


def test_probe_poll_version_matches_compute_for_fixture(game_client):
    """GC-PERF-STATE-004: probe fingerprint matches diet compute_poll_version."""
    from game.db import db
    from game.live_state import compute_poll_version, probe_poll_version

    client, pid = game_client
    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload.get("ok") is True
    diet_ver = int(payload["poll_version"])
    assert diet_ver == compute_poll_version(payload)

    conn = db()
    try:
        probed = probe_poll_version(int(pid), conn)
    finally:
        conn.close()
    assert probed is not None
    assert int(probed) == diet_ver


def test_diet_early_exit_skips_full_payload_build(game_client, monkeypatch):
    """Idle matching since must not call _build_game_state_payload."""
    import app as app_module
    from game import live_state as ls

    monkeypatch.delenv("GC_STATE_DELTA", raising=False)
    monkeypatch.setattr(ls, "probe_poll_version", lambda *_a, **_k: 777001)
    monkeypatch.setattr(
        "game.queue_poll.player_has_due_queue_work", lambda *_a, **_k: False
    )
    monkeypatch.setattr("game.queue_poll.player_fleet_is_dirty", lambda *_a, **_k: False)

    calls = {"n": 0}
    real_build = app_module._build_game_state_payload

    def counting_build(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(app_module, "_build_game_state_payload", counting_build)

    client, _pid = game_client
    resp = client.get("/api/game-state?since=777001")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("unchanged") is True
    assert data.get("diet_early_exit") == 1
    assert int(data.get("poll_version")) == 777001
    assert calls["n"] == 0


def test_diet_early_exit_blocked_when_queue_due(game_client, monkeypatch):
    """Due queue work must take the full build path (finish owner)."""
    import app as app_module
    from game import live_state as ls

    monkeypatch.delenv("GC_STATE_DELTA", raising=False)
    monkeypatch.setattr(ls, "probe_poll_version", lambda *_a, **_k: 777002)
    monkeypatch.setattr(ls, "compute_poll_version", lambda _payload: 777002)
    monkeypatch.setattr(
        "game.queue_poll.player_has_due_queue_work", lambda *_a, **_k: True
    )
    monkeypatch.setattr("game.queue_poll.player_fleet_is_dirty", lambda *_a, **_k: False)

    calls = {"n": 0}
    real_build = app_module._build_game_state_payload

    def counting_build(*args, **kwargs):
        calls["n"] += 1
        return real_build(*args, **kwargs)

    monkeypatch.setattr(app_module, "_build_game_state_payload", counting_build)

    client, _pid = game_client
    resp = client.get("/api/game-state?since=777002")
    assert resp.status_code == 200
    data = resp.get_json()
    assert calls["n"] == 1
    assert data.get("diet_early_exit") != 1

def test_diet_probe_skip_uses_process_local_fingerprint(game_client, monkeypatch):
    """GC-PERF-STATE-005: matching since skips heavy probe_poll_version (within TTL)."""
    from game import live_state as ls

    monkeypatch.delenv("GC_STATE_DELTA", raising=False)
    monkeypatch.setattr(
        "game.queue_poll.player_has_due_queue_work", lambda *_a, **_k: False
    )
    monkeypatch.setattr("game.queue_poll.player_fleet_is_dirty", lambda *_a, **_k: False)
    ls.clear_diet_poll_fingerprint()

    probe_calls = {"n": 0}

    def counting_probe(*_a, **_k):
        probe_calls["n"] += 1
        return 888001

    monkeypatch.setattr(ls, "probe_poll_version", counting_probe)
    monkeypatch.setattr("game.messages.unread_count", lambda *_a, **_k: 0)

    client, pid = game_client
    ls.remember_diet_poll_fingerprint(int(pid), version=888001, unread=0)

    resp = client.get("/api/game-state?since=888001")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("unchanged") is True
    assert data.get("diet_early_exit") == 1
    assert data.get("diet_probe_skip") == 1
    assert probe_calls["n"] == 0


def test_diet_probe_skip_expires_so_nav_badges_reprobe(game_client, monkeypatch):
    """TTL forces probe_poll_version so Inventar/LiveOps/Vote badges stay live."""
    from game import live_state as ls

    monkeypatch.delenv("GC_STATE_DELTA", raising=False)
    monkeypatch.setattr(
        "game.queue_poll.player_has_due_queue_work", lambda *_a, **_k: False
    )
    monkeypatch.setattr("game.queue_poll.player_fleet_is_dirty", lambda *_a, **_k: False)
    ls.clear_diet_poll_fingerprint()

    probe_calls = {"n": 0}

    def counting_probe(*_a, **_k):
        probe_calls["n"] += 1
        return 888002

    monkeypatch.setattr(ls, "probe_poll_version", counting_probe)
    monkeypatch.setattr("game.messages.unread_count", lambda *_a, **_k: 0)

    client, pid = game_client
    ls.remember_diet_poll_fingerprint(int(pid), version=888002, unread=0)
    # Age the fingerprint past TTL
    cached = ls._DIET_POLL_FP_CACHE[int(pid)]
    ls._DIET_POLL_FP_CACHE[int(pid)] = (cached[0], cached[1], cached[2] - 10.0)

    resp = client.get("/api/game-state?since=888002")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("unchanged") is True
    assert data.get("diet_early_exit") == 1
    assert data.get("diet_probe_skip") != 1
    assert probe_calls["n"] == 1


def test_poll_thrash_pattern_removed_from_refresh():
    """GC-PERF-POLL-THRASH-001: poll path must not stop+start on lastInterval > active."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "static" / "main.js").read_text(
        encoding="utf-8"
    )
    assert "Cadence is owned by gameStatePollTick" in src
    parts = src.split("if (data.unchanged === true)")
    assert len(parts) >= 2
    unchanged_branch = parts[1].split("rememberPollVersion(data);")[0]
    assert "GC.stopPolling()" not in unchanged_branch
    assert "GC.startPolling(true)" not in unchanged_branch
