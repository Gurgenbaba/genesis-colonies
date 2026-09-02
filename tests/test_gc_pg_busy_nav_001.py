from unittest.mock import patch

from flask import Flask

from game.auth import _cache_guard_player, _clear_guard_player, require_login
from game.db import DbPoolTimeout


def _app():
    app = Flask(__name__)
    app.secret_key = "gc-pg-busy-nav-test-secret"

    @app.get("/overview")
    @require_login
    def overview():
        return "ok"

    @app.get("/api/protected")
    @require_login
    def api_protected():
        return {"ok": True}

    return app


def _login(client, pid):
    with client.session_transaction() as sess:
        sess["user_id"] = pid


def _player(pid):
    return {"id": pid, "name": "Cache", "banned_until": None}


def test_safe_html_navigation_reuses_fresh_guard_cache():
    pid = 910001
    _clear_guard_player(pid)
    _cache_guard_player(pid, _player(pid))
    app = _app()
    with app.test_client() as client:
        _login(client, pid)
        with patch("game.auth.get_player_by_user_id") as load, patch("game.auth.touch_player_online"):
            response = client.get("/overview")
    assert response.status_code == 200
    load.assert_not_called()
    _clear_guard_player(pid)


def test_safe_html_navigation_uses_stale_cache_on_pool_timeout():
    pid = 910002
    _clear_guard_player(pid)
    _cache_guard_player(pid, _player(pid))
    import game.auth as auth
    with auth._player_guard_lock:
        cached_at, player = auth._player_guard_cache[pid]
        auth._player_guard_cache[pid] = (cached_at - 5.0, player)

    app = _app()
    with app.test_client() as client:
        _login(client, pid)
        with patch("game.auth.get_player_by_user_id", side_effect=DbPoolTimeout("busy")), patch("game.auth.touch_player_online"):
            response = client.get("/overview")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"
    _clear_guard_player(pid)


def test_api_request_never_uses_stale_cache_on_pool_timeout():
    pid = 910003
    _clear_guard_player(pid)
    _cache_guard_player(pid, _player(pid))
    import game.auth as auth
    with auth._player_guard_lock:
        cached_at, player = auth._player_guard_cache[pid]
        auth._player_guard_cache[pid] = (cached_at - 5.0, player)

    app = _app()
    with app.test_client() as client:
        _login(client, pid)
        with patch("game.auth.get_player_by_user_id", side_effect=DbPoolTimeout("busy")), patch("game.auth.touch_player_online"):
            response = client.get("/api/protected")
    assert response.status_code == 503
    _clear_guard_player(pid)
