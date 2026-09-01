"""GC-PERF-174 — Sentinel real-PJAX navigation matrix contracts."""

from pathlib import Path

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_sentinel_sandbox_enables_navigation_perf():
    src = _read("scripts/browser_test_support.py")
    assert '"GC_NAV_PERF_DEBUG": "1"' in src


def test_sentinel_drives_real_pjax_and_persists_route_samples():
    src = _read("scripts/browser_sentinel.py")
    assert "window.GC.navigateTo" in src
    assert "window.GC_GET_NAV_PERF_SAMPLES" in src
    assert '"navigation_mode": None' in src
    assert '"navigation_perf": None' in src
    assert '"navigation_perf": _navigation_perf_summary(route_results)' in src
    assert '"nav_perf_samples": report["navigation_perf"]["sample_count"]' in src


def test_sentinel_safe_controls_never_click_navigation_links():
    src = _read("scripts/browser_sentinel.py")
    block = src.split("def _probe_safe_controls(page)", 1)[1].split("def _navigate_with_pjax_perf", 1)[0]
    assert "el.tagName === 'A'" in block
    assert "el.getAttribute('href')" in block
    assert "force=True" in block


def test_sentinel_marks_primary_pjax_failures_explicitly():
    src = _read("scripts/browser_sentinel.py")
    assert "primaryError" in src
    assert '"navigation_error": None' in src
    assert 'kind="pjax_navigation_failed"' in src
    assert 'result["status"] = nav_result.get("status")' in src


def test_nav_sample_carries_database_backend_identity():
    server = _read("game/live_state.py")
    client = _read("static/main.js")
    assert 'X-GC-Nav-Db-Backend' in server
    assert 'get_db_backend()' in server
    assert 'db_backend: headerText("X-GC-Nav-Db-Backend")' in client
    assert 'db_backend: server?.db_backend ?? null' in client


def test_pjax_backend_header_behavior(game_client, monkeypatch):
    monkeypatch.setenv("GC_NAV_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")
    client, _pid = game_client
    resp = client.get(
        "/buildings",
        headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-GC-Nav-Db-Backend") == "sqlite"


def test_sentinel_lifecycle_noise_classifier_is_narrow():
    from scripts.browser_sentinel import _runtime_event_severity

    assert _runtime_event_severity(
        kind="request_failed",
        problem="Request failed: http://127.0.0.1:5000/api/chat/bootstrap (net::ERR_ABORTED)",
        url="http://127.0.0.1:5000/api/chat/bootstrap",
        base_url="http://127.0.0.1:5000",
    ) == "LOW"
    assert _runtime_event_severity(
        kind="request_failed",
        problem="Request failed: http://127.0.0.1:5000/api/messages?limit=50 (net::ERR_ABORTED)",
        url="http://127.0.0.1:5000/api/messages?limit=50",
        base_url="http://127.0.0.1:5000",
    ) == "LOW"
    assert _runtime_event_severity(
        kind="request_failed",
        problem="Request failed: http://127.0.0.1:5000/api/game-state (net::ERR_ABORTED)",
        url="http://127.0.0.1:5000/api/game-state",
        base_url="http://127.0.0.1:5000",
    ) == "HIGH"


def test_sentinel_local_werkzeug_galaxy_ws_noise_is_not_live_suppression():
    from scripts.browser_sentinel import _runtime_event_severity

    problem = "WebSocket connection to 'ws://127.0.0.1:5000/ws/galaxy/5/404' failed: Invalid frame header"
    assert _runtime_event_severity(
        kind="console_error", problem=problem, base_url="http://127.0.0.1:5000"
    ) == "LOW"
    assert _runtime_event_severity(
        kind="console_error", problem=problem, base_url="https://genesis-colonies.com"
    ) == "HIGH"
