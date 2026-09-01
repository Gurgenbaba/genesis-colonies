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
