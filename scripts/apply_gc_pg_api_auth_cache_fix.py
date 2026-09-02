from pathlib import Path

p = Path("game/auth.py")
text = p.read_text(encoding="utf-8")
old = '''        try:\n            player = get_player_by_user_id(pid)\n        except DbPoolTimeout:\n            logger.warning("api login guard pool_timeout player=%s", pid)\n            return _db_busy_response(json_api=True)\n        if not player:\n            session.clear()\n            return jsonify({"ok": False, "error": "unauthorized"}), 401\n'''
new = '''        player = _cached_guard_player(pid)\n        if player is None:\n            try:\n                player = get_player_by_user_id(pid)\n            except DbPoolTimeout:\n                logger.warning("api login guard pool_timeout player=%s", pid)\n                return _db_busy_response(json_api=True)\n            else:\n                if player:\n                    _cache_guard_player(pid, player)\n        if not player:\n            _clear_guard_player(pid)\n            session.clear()\n            return jsonify({"ok": False, "error": "unauthorized"}), 401\n'''
if old not in text:
    raise SystemExit("require_login_api marker not found")
text = text.replace(old, new, 1)
p.write_text(text, encoding="utf-8")

t = Path("tests/test_gc_pg_busy_nav_001.py")
txt = t.read_text(encoding="utf-8")
marker = '''def test_api_request_never_uses_stale_cache_on_pool_timeout():\n'''
insert = '''def test_api_request_reuses_fresh_guard_cache_without_db_checkout():\n    pid = 910004\n    _clear_guard_player(pid)\n    _cache_guard_player(pid, _player(pid))\n    app = _app()\n    with app.test_client() as client:\n        _login(client, pid)\n        with patch("game.auth.get_player_by_user_id") as load, patch("game.auth.touch_player_online"):\n            response = client.get("/api/protected")\n    assert response.status_code == 200\n    load.assert_not_called()\n    _clear_guard_player(pid)\n\n\n'''
if marker not in txt:
    raise SystemExit("test marker not found")
txt = txt.replace(marker, insert + marker, 1)
t.write_text(txt, encoding="utf-8")
