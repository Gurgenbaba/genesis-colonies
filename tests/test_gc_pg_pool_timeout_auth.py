"""GC-PG — PoolTimeout must not 500 as 'postgres not configured'."""

from __future__ import annotations

from unittest.mock import patch

from game.auth import _get_active_ban, _handle_if_banned
from game.db import DbPoolTimeout, db, is_db_pool_timeout
from game.db_pg import get_pool_checkout_timeout_s

pytest_plugins = ["tests.test_planet_registry"]


def test_pool_checkout_timeout_default_is_short(monkeypatch):
    monkeypatch.delenv("GC_PG_POOL_TIMEOUT", raising=False)
    assert get_pool_checkout_timeout_s() == 3.0


def test_is_db_pool_timeout_detects_psycopg_message():
    class PoolTimeout(Exception):
        pass

    exc = PoolTimeout("couldn't get a connection after 30.00 sec")
    assert is_db_pool_timeout(exc) is True
    assert is_db_pool_timeout(DbPoolTimeout("busy")) is True


def test_db_wraps_pool_timeout_not_notimplemented(monkeypatch):
    monkeypatch.setenv("GC_DB_BACKEND", "postgres")

    class PoolTimeout(Exception):
        pass

    with patch("game.db.get_db_backend", return_value="postgres"), patch(
        "game.db_pg.connect_postgres",
        side_effect=PoolTimeout("couldn't get a connection after 30.00 sec"),
    ):
        try:
            db()
        except DbPoolTimeout:
            return
        except NotImplementedError as exc:
            raise AssertionError(f"must not wrap as NotImplementedError: {exc}") from exc
        raise AssertionError("expected DbPoolTimeout")


def test_get_active_ban_fail_open_on_pool_timeout(switcher_db, monkeypatch):
    from tests.test_planet_registry import _create_player

    player_id, _ = _create_player()
    import game.auth as auth_mod

    auth_mod._ban_neg_until.clear()
    with patch("game.auth.db", side_effect=DbPoolTimeout("pool busy")):
        assert _get_active_ban(player_id) is None


def test_get_active_ban_uses_player_row_without_db(switcher_db):
    from tests.test_planet_registry import _create_player

    player_id, _ = _create_player()
    import game.auth as auth_mod

    auth_mod._ban_neg_until.clear()
    player = {"id": player_id, "banned_until": None}
    with patch("game.auth.db") as db_mock:
        assert _get_active_ban(player_id, player=player) is None
        db_mock.assert_not_called()


def test_handle_if_banned_fail_open_on_pool_timeout(switcher_db):
    from tests.test_planet_registry import _create_player

    player_id, _ = _create_player()
    import game.auth as auth_mod

    auth_mod._ban_neg_until.clear()
    with patch("game.auth._get_active_ban", side_effect=DbPoolTimeout("pool busy")):
        assert _handle_if_banned(player_id) is None


def test_api_game_state_pool_timeout_is_503(switcher_db, monkeypatch):
    from tests.test_planet_registry import _app_client, _create_player, _login

    player_id, uname = _create_player()
    client = _app_client(monkeypatch)
    _login(client, player_id, uname)

    with patch(
        "game.auth.get_player_by_user_id",
        side_effect=DbPoolTimeout("couldn't get a connection after 3.00 sec"),
    ):
        resp = client.get("/api/game-state")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "db_busy"
    assert body.get("retry") is True
