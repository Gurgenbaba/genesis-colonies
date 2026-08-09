"""
GC-PERF-AUTO — Automatic Performance Intelligence contracts.

Run: python -m pytest tests/test_gc_perf_auto.py -v
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from flask import Flask, g

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_perf_intel():
    from game.perf_intel import reset_perf_intel_for_tests

    reset_perf_intel_for_tests()
    yield
    reset_perf_intel_for_tests()


@pytest.fixture()
def admin_env(tmp_path, monkeypatch):
    db_file = tmp_path / "perf_auto_admin.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_PERF_INTEL", "1")
    return db_file


@pytest.fixture()
def app_client(admin_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import migrate

    migrate.main()

    import importlib
    import app as app_module

    importlib.reload(app_module)

    from game.models import create_user, ensure_player_and_homeworld

    ok_a, _, admin_info = create_user("admin_perf", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("normal_perf", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def _login(client, username, password):
    from game.models import verify_user

    user = verify_user(str(username), str(password))
    if user:
        with client.session_transaction() as sess:
            sess["user_id"] = int(user["id"])
        return user
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_normalize_sql_signature_strips_literals():
    from game.perf_intel import normalize_sql_signature

    sig = normalize_sql_signature(
        "SELECT * FROM planets WHERE player_id = 42 AND name = 'Alice''s Base'"
    )
    assert "42" not in sig
    assert "Alice" not in sig
    assert "?" in sig
    assert "planets" in sig.lower()


def test_percentile_and_summarize():
    from game.perf_intel import percentile, summarize_latencies

    vals = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    assert percentile(vals, 50) == 50.0
    assert percentile(vals, 95) == 100.0
    summary = summarize_latencies(vals)
    assert summary["count"] == 10
    assert summary["p50_ms"] == 50.0
    assert summary["max_ms"] == 100.0


def test_ringbuffer_is_bounded():
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore(ring_max=32)
    for i in range(100):
        store.record(
            RequestSample(
                ts=time.time(),
                method="GET",
                route=f"/r{i % 3}",
                path=f"/r{i % 3}",
                status=200,
                total_ms=float(i),
                error=False,
            )
        )
    assert store.ring_len == 32


def test_pressure_hysteresis_and_recovery():
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore()
    # Old elevated traffic (outside 60s window after recovery samples)
    old = time.time() - 120.0
    for _ in range(10):
        store.record(
            RequestSample(
                ts=old,
                method="GET",
                route="/api/game-state",
                path="/api/game-state",
                status=200,
                total_ms=900.0,
                error=False,
            )
        )
    # Force pressure with recent slow samples
    now = time.time()
    for _ in range(10):
        store.record(
            RequestSample(
                ts=now,
                method="GET",
                route="/api/game-state",
                path="/api/game-state",
                status=200,
                total_ms=1800.0,
                error=False,
            )
        )
    assert store.get_pressure_state() in ("pressure", "critical")

    # Age the slow samples out, then feed fast traffic
    aged = time.time() - 90.0
    with store._lock:
        for s in store._ring:
            if s.total_ms >= 1500:
                s.ts = aged
    for _ in range(20):
        store.record(
            RequestSample(
                ts=time.time(),
                method="GET",
                route="/api/game-state",
                path="/api/game-state",
                status=200,
                total_ms=80.0,
                error=False,
            )
        )
    assert store.get_pressure_state() in ("recovery", "warm", "normal")


def test_hotspot_and_diagnosis():
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore()
    now = time.time()
    for _ in range(15):
        store.record(
            RequestSample(
                ts=now,
                method="GET",
                route="api_game_state",
                path="/api/game-state",
                status=200,
                total_ms=1200.0,
                error=False,
                phases={
                    "handler_ms": 1100.0,
                    "finish_ms": 800.0,
                    "payload_ms": 50.0,
                },
            )
        )
    comps = store.component_stats(300.0)
    assert comps and comps[0]["component"] == "queue_finish"
    assert all(c["component"] != "handler" for c in comps)
    assert all(c["component"] != "state_build" for c in comps)
    diag = store.build_diagnosis(300.0)
    assert diag["cause"] == "queue_finish"
    assert "queue" in diag["recommendation"].lower() or "finish" in diag["recommendation"].lower()


def test_payload_child_hotspot_not_state_build_envelope():
    """GC-PERF-AUTO-007A: payload children beat envelope state_build in hotspots."""
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore()
    now = time.time()
    for _ in range(12):
        store.record(
            RequestSample(
                ts=now,
                method="GET",
                route="api_game_state",
                path="/api/game-state",
                status=200,
                total_ms=900.0,
                error=False,
                phases={
                    "payload_ms": 700.0,
                    "payload_fleets_hud_ms": 420.0,
                    "fleets_radar_ms": 300.0,
                    "fleets_active_ms": 80.0,
                    "payload_nav_badges_ms": 80.0,
                    "finish_ms": 40.0,
                },
                slow_class="slow",
            )
        )
    comps = store.component_stats(300.0)
    names = [c["component"] for c in comps]
    assert "fleets.radar" in names
    assert names[0] == "fleets.radar"
    assert "state_build" not in names
    assert "payload.fleets_hud" not in names
    diag = store.build_diagnosis(300.0)
    assert diag["cause"] == "fleets.radar"


def test_live_context_envelope_prefers_finish_child():
    """GC-PERF-AUTO-007B: live_context wall must not beat finish_ms in diagnosis."""
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore()
    now = time.time()
    for _ in range(12):
        store.record(
            RequestSample(
                ts=now,
                method="GET",
                route="api_game_state",
                path="/api/game-state",
                status=200,
                total_ms=1400.0,
                error=False,
                phases={
                    "live_context_ms": 900.0,
                    "finish_ms": 700.0,
                    "resource_sync_ms": 80.0,
                    "live_hud_reads_ms": 40.0,
                    "payload_fleets_hud_ms": 200.0,
                    "fleets_active_ms": 150.0,
                },
                slow_class="very_slow",
            )
        )
    comps = store.component_stats(300.0)
    names = [c["component"] for c in comps]
    assert "live_context" not in names
    assert "payload.fleets_hud" not in names
    assert names[0] == "queue_finish"
    diag = store.build_diagnosis(300.0)
    assert diag["cause"] == "queue_finish"


def test_spike_ring_captures_slow_only():
    """GC-PERF-AUTO-007A: slow requests land in spikes[]; fast ones do not."""
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore(spike_max=16)
    now = time.time()
    store.record(
        RequestSample(
            ts=now,
            method="GET",
            route="api_game_state",
            path="/api/game-state",
            status=200,
            total_ms=80.0,
            error=False,
            phases={"payload_score_ms": 10.0},
            slow_class="",
        )
    )
    store.record(
        RequestSample(
            ts=now + 1,
            method="GET",
            route="overview",
            path="/overview",
            status=200,
            total_ms=1800.0,
            error=False,
            phases={
                "page_context_overview_ms": 900.0,
                "live_context_ms": 400.0,
            },
            slow_class="very_slow",
            sql_count=12,
            db_query_ms=55.0,
        )
    )
    spikes = store.recent_spikes(10)
    assert len(spikes) == 1
    assert spikes[0]["route"] == "overview"
    assert spikes[0]["slow_class"] == "very_slow"
    assert spikes[0]["top_costs"][0]["name"] == "page_context.overview"
    snap = store.snapshot()
    assert "spikes" in snap
    assert len(snap["spikes"]) == 1


def test_spike_ring_ignores_debug_zero_threshold(monkeypatch):
    """GC_REQUEST_PERF_SLOW_MS=0 must not flood spikes with healthy polls."""
    monkeypatch.setenv("GC_REQUEST_PERF_SLOW_MS", "0")
    monkeypatch.delenv("GC_PERF_SLOW_MS", raising=False)
    from game.perf_intel import PerfIntelStore, RequestSample, classify_slow, get_spike_request_ms

    assert get_spike_request_ms() >= 500.0
    assert classify_slow(80.0) == ""
    assert classify_slow(800.0) == "slow"

    store = PerfIntelStore(spike_max=16)
    now = time.time()
    # Simulate a buggy caller that still set slow_class while total is fast
    store.record(
        RequestSample(
            ts=now,
            method="GET",
            route="api_chat_messages",
            path="/api/chat/messages",
            status=200,
            total_ms=45.0,
            error=False,
            phases={"db_connection_ms": 3.0},
            slow_class="slow",
        )
    )
    assert store.recent_spikes() == []
    store.record(
        RequestSample(
            ts=now + 1,
            method="GET",
            route="api_game_state",
            path="/api/game-state",
            status=200,
            total_ms=1800.0,
            error=False,
            phases={"live_context_ms": 900.0, "payload_panel_ms": 400.0},
            slow_class="very_slow",
        )
    )
    spikes = store.recent_spikes()
    assert len(spikes) == 1
    assert spikes[0]["route"] == "api_game_state"


def test_pressure_ignores_sparse_traffic():
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore()
    now = time.time()
    # Fewer than _PRESSURE_MIN_SAMPLES even if each is slow
    for _ in range(5):
        store.record(
            RequestSample(
                ts=now,
                method="GET",
                route="overview",
                path="/overview",
                status=200,
                total_ms=1800.0,
                error=False,
            )
        )
    assert store.get_pressure_state() == "normal"


def test_process_metrics_never_raises_without_psutil(monkeypatch):
    import game.perf_intel as pi

    monkeypatch.setattr(pi, "_psutil", None)
    monkeypatch.setattr(pi, "_psutil_checked", True)
    snap = pi.collect_process_metrics()
    assert "pid" in snap
    assert snap["pid"] == __import__("os").getpid()


def test_thread_safety_smoke():
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore(ring_max=256)
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(50):
                store.begin_request()
                store.record(
                    RequestSample(
                        ts=time.time(),
                        method="GET",
                        route="/x",
                        path="/x",
                        status=200,
                        total_ms=float(i + n),
                        error=False,
                        phases={"finish_ms": 10.0},
                    )
                )
                store.end_request()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert store.ring_len <= 256
    assert store.active_requests == 0


def test_perf_span_records_phase():
    from game.live_state import RequestPerfState, perf_span

    app = Flask(__name__)
    with app.test_request_context("/api/game-state"):
        g.gc_request_perf = RequestPerfState(sampled=True, intel_enabled=True)
        with perf_span("queue_finish"):
            time.sleep(0.01)
        assert g.gc_request_perf.phases.get("finish_ms", 0) >= 5.0


def test_admin_performance_requires_login(app_client):
    client, _, _ = app_client
    r = client.get("/api/admin/performance")
    assert r.status_code == 401
    data = r.get_json() or {}
    assert data.get("ok") is False


def test_admin_performance_forbidden_for_non_admin(app_client):
    client, _, _ = app_client
    _login(client, "normal_perf", "userpass123")
    r = client.get("/api/admin/performance")
    assert r.status_code == 403
    assert (r.get_json() or {}).get("error") == "forbidden"


def test_admin_performance_ok_for_admin(app_client):
    from game.perf_intel import record_request_sample

    client, _, _ = app_client
    _login(client, "admin_perf", "adminpass123")
    record_request_sample(
        method="GET",
        route="api_game_state",
        path="/api/game-state",
        status=200,
        total_ms=120.0,
        phases={"finish_ms": 40.0},
        sql_count=3,
        db_query_ms=12.0,
    )
    r = client.get("/api/admin/performance")
    assert r.status_code == 200
    data = r.get_json() or {}
    assert data.get("ok") is True
    assert "status" in data
    assert "process" in data
    assert "requests" in data
    assert "routes" in data
    assert "components" in data
    assert "spikes" in data
    assert isinstance(data.get("spikes"), list)
    assert "diagnosis" in data
    assert "history_60m" in data


def test_payload_child_span_aliases():
    from game.perf_intel import resolve_phase_name
    from game.live_state import _REQUEST_PERF_PHASE_KEYS

    assert resolve_phase_name("payload.fleets_hud") == "payload_fleets_hud_ms"
    assert resolve_phase_name("page_context.overview") == "page_context_overview_ms"
    assert resolve_phase_name("fleets.radar") == "fleets_radar_ms"
    assert resolve_phase_name("live.hud_reads") == "live_hud_reads_ms"
    assert "payload_fleets_hud_ms" in _REQUEST_PERF_PHASE_KEYS
    assert "page_context_overview_ms" in _REQUEST_PERF_PHASE_KEYS
    assert "fleets_radar_ms" in _REQUEST_PERF_PHASE_KEYS
    assert "live_hud_reads_ms" in _REQUEST_PERF_PHASE_KEYS


def test_admin_spikes_ui_contract():
    admin = _read("static/admin.js")
    assert "data.spikes" in admin
    assert "admin_perf_spikes" in admin
    assert "LETZTE SPIKES" in admin or 't("admin_perf_spikes"' in admin
    assert 'perf_span("payload.fleets_hud")' in _read("app.py")
    assert 'perf_span("page_context.overview")' in _read("app.py")
    assert 'perf_span("fleets.radar")' in _read("game/live_state.py")
    assert 'perf_span("live.hud_reads")' in _read("app.py") or '_live_perf_span("live.hud_reads")' in _read("app.py")


def test_poll_jitter_contract_in_main_js():
    src = _read("static/main.js")
    assert "applyPollJitter" in src
    assert "gc_poll_jitter_seed" in src
    assert "0.125" in src


def test_admin_tab_and_docs_exist():
    assert "performance" in _read("static/admin.js")
    assert "admin-tab-performance" in _read("templates/admin_panel.html")
    assert "GC-PERF-AUTO" in _read("docs/PERFORMANCE.md")
    assert "/api/game-state" in _read("docs/PERFORMANCE.md")
    assert "GC-PERF-AUTO-006" in _read("docs/PERFORMANCE.md")
    assert "GC-PERF-AUTO-007A" in _read("docs/PERFORMANCE.md")
    assert "spikes" in _read("docs/PERFORMANCE.md")


def test_perf_intel_owner_in_core_architecture():
    src = _read("docs/CORE_ARCHITECTURE.md")
    assert "perf_intel" in src
