"""Session consistency + fleet drawer timer stability (no Ankunft/mission flicker)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_auth_failure_ignores_non_json_noise():
    src = _read("static/main.js")
    auth = src.split("function isAuthStatusFailure(err, data)")[1].split(
        "function noteConfirmedAuthFailure"
    )[0]
    assert "non_json_response" not in auth
    assert "invalid_json_response" not in auth
    assert 'status === 401' in auth
    assert 'data?.error === "banned"' in auth


def test_auth_failure_requires_streak_except_hard_cases():
    src = _read("static/main.js")
    handle = src.split("function handleAuthFailure(reason)")[1].split(
        "function throwAuthError"
    )[0]
    assert "noteConfirmedAuthFailure" in handle
    assert "AUTH_FAILURE_STREAK_LIMIT" in src
    assert "clearAuthFailureStreak" in src
    refresh = src.split("async function refreshGameState(reason)")[1].split(
        "GC.refreshGameState = refreshGameState"
    )[0]
    assert "clearAuthFailureStreak()" in refresh


def test_timer_clock_does_not_pull_backward_each_tick():
    src = _read("static/main.js")
    timer_now = src.split("function getTimerServerNow()")[1].split(
        "function queryTimerElements"
    )[0]
    assert "st > approx + 0.05" in timer_now
    assert "st > approx - 0.5" not in timer_now


def test_fleet_drawer_timer_stays_numeric_at_zero():
    src = _read("static/main.js")
    timers = src.split("function updateFleetDrawerRowTimers(serverNow)")[1].split(
        "function rememberFleetDrawerMovements"
    )[0]
    assert '_setIfChanged(cdEl, "0s")' in timers
    assert 't("fleet_arrival_at"' not in timers
    assert "fleetArrivedKey" in timers
    assert "fleetDrawerCountdownAt(mv) === target" in timers


def test_permanent_session_configured():
    app = _read("app.py")
    assert "PERMANENT_SESSION_LIFETIME" in app
    assert "SESSION_REFRESH_EACH_REQUEST" in app
    auth = _read("game/auth.py")
    assert "session.permanent = True" in auth


def test_game_state_uses_require_login_api():
    app = _read("app.py")
    block = app.split('@app.route("/api/game-state")')[1].split("def api_game_state")[0]
    assert "@require_login_api" in block
    assert "@require_login\n" not in block
    status = app.split('@app.route("/api/status")')[1].split("def api_status")[0]
    assert "@require_login_api" in status
    notif = app.split('@app.route("/api/notifications/summary")')[1].split(
        "def api_notifications_summary"
    )[0]
    assert "@require_login_api" in notif
