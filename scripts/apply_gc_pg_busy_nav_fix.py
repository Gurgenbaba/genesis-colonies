from pathlib import Path

p = Path("game/auth.py")
text = p.read_text(encoding="utf-8")

marker = "_BAN_NEG_TTL_SEC = 15.0\n_ban_neg_until: dict[int, float] = {}\n_ban_neg_lock = threading.Lock()\n"
insert = '''_BAN_NEG_TTL_SEC = 15.0
_ban_neg_until: dict[int, float] = {}
_ban_neg_lock = threading.Lock()

# GC-PG-BUSY-NAV-001: auth is on every protected route. A rapid action ->
# navigation burst must not consume another PG checkout merely to reload the
# same player row. Fresh cache is intentionally tiny; stale use is allowed
# only as a fail-soft path for safe non-API GET/HEAD navigation after a pool
# timeout. Mutating/API requests never use stale auth state.
_PLAYER_GUARD_TTL_SEC = 2.0
_PLAYER_GUARD_STALE_SEC = 30.0
_player_guard_cache: dict[int, tuple[float, Dict[str, Any]]] = {}
_player_guard_lock = threading.Lock()


def _cache_guard_player(player_id: int, player: Dict[str, Any]) -> None:
    with _player_guard_lock:
        _player_guard_cache[int(player_id)] = (time.monotonic(), dict(player))


def _cached_guard_player(player_id: int, *, allow_stale: bool = False) -> Optional[Dict[str, Any]]:
    now_m = time.monotonic()
    max_age = _PLAYER_GUARD_STALE_SEC if allow_stale else _PLAYER_GUARD_TTL_SEC
    with _player_guard_lock:
        entry = _player_guard_cache.get(int(player_id))
        if entry is None:
            return None
        cached_at, player = entry
        if now_m - cached_at > max_age:
            _player_guard_cache.pop(int(player_id), None)
            return None
        return dict(player)


def _clear_guard_player(player_id: int) -> None:
    with _player_guard_lock:
        _player_guard_cache.pop(int(player_id), None)


def _safe_html_navigation_request() -> bool:
    return request.method in ("GET", "HEAD") and not request.path.startswith("/api/")
'''
if marker not in text:
    raise SystemExit("auth cache marker not found")
text = text.replace(marker, insert, 1)

old_logout = '''def logout_user() -> None:
    """Leert die Session."""
    session.clear()
'''
new_logout = '''def logout_user() -> None:
    """Leert die Session."""
    try:
        pid = int(session.get("user_id") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid:
        _clear_guard_player(pid)
    session.clear()
'''
if old_logout not in text:
    raise SystemExit("logout marker not found")
text = text.replace(old_logout, new_logout, 1)

old_guard = '''        try:
            player = get_player_by_user_id(pid)
        except DbPoolTimeout:
            logger.warning("login guard pool_timeout player=%s", pid)
            return _db_busy_response(json_api=False)
        if not player:
            session.clear()
            return redirect(url_for("login"))
'''
new_guard = '''        player = _cached_guard_player(pid)
        if player is None:
            try:
                player = get_player_by_user_id(pid)
            except DbPoolTimeout:
                if _safe_html_navigation_request():
                    player = _cached_guard_player(pid, allow_stale=True)
                    if player is not None:
                        logger.warning(
                            "login guard pool_timeout using cached player for safe navigation player=%s path=%s",
                            pid,
                            request.path,
                        )
                    else:
                        logger.warning("login guard pool_timeout player=%s path=%s", pid, request.path)
                        return _db_busy_response(json_api=False)
                else:
                    logger.warning("login guard pool_timeout player=%s path=%s", pid, request.path)
                    return _db_busy_response(json_api=False)
            else:
                if player:
                    _cache_guard_player(pid, player)
        if not player:
            _clear_guard_player(pid)
            session.clear()
            return redirect(url_for("login"))
'''
if old_guard not in text:
    raise SystemExit("login guard marker not found")
text = text.replace(old_guard, new_guard, 1)
p.write_text(text, encoding="utf-8")

Path("tests/test_gc_pg_busy_nav_001.py").write_text('''from unittest.mock import patch

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
''', encoding="utf-8")
