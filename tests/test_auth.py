"""
GC-733A — Discord OAuth login/register tests.

Run: python -m pytest tests/test_auth.py -v
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import app as app_mod
import game.db as dbmod
import game.discord_auth as discord_auth
import game.models as models
from game.discord_auth import (
    SESSION_LINK_MODE_KEY,
    SESSION_STATE_KEY,
    create_user_from_discord,
    get_user_by_discord_id,
    link_discord_to_user,
    unlink_discord_from_user,
)
from game.models import create_user, init_db

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "auth_discord.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def _close_db() -> None:
    try:
        models.db().close()
    except Exception:
        pass


@pytest.fixture()
def discord_env(monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "http://localhost/auth/discord/callback")


@pytest.fixture()
def app_client(temp_db, discord_env, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    importlib.reload(discord_auth)
    importlib.reload(models)
    importlib.reload(app_mod)

    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_discord_oauth_requires_configuration(app_client, monkeypatch):
    monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False)
    importlib.reload(discord_auth)

    resp = app_client.get("/auth/discord", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


def test_discord_start_stores_state_and_redirects(app_client):
    resp = app_client.get("/auth/discord", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "discord.com/api/oauth2/authorize" in location
    assert "client_id=test-client-id" in location
    assert "state=" in location

    with app_client.session_transaction() as sess:
        state = sess.get(SESSION_STATE_KEY)
    assert state
    assert f"state={state}" in location


def test_discord_callback_rejects_invalid_state(app_client):
    resp = app_client.get(
        "/auth/discord/callback?code=abc&state=wrong",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


def test_discord_callback_registers_new_user(app_client, monkeypatch):
    profile = {
        "id": "987654321012345678",
        "username": "BobbyGurken",
        "global_name": "Bobby Gurkenvater",
        "avatar": "avatarhash",
        "email": "bobby@example.com",
    }

    def fake_complete(code: str):
        assert code == "good-code"
        ok, err, user = create_user_from_discord(profile)
        assert ok, err
        return True, "discord_register_ok", user

    monkeypatch.setattr(discord_auth, "complete_discord_callback", fake_complete)

    with app_client.session_transaction() as sess:
        sess[SESSION_STATE_KEY] = "valid-state"

    resp = app_client.get(
        "/auth/discord/callback?code=good-code&state=valid-state",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/welcome/discord" in resp.headers.get("Location", "")

    row = get_user_by_discord_id("987654321012345678")
    assert row is not None
    assert row["discord_username"] == "BobbyGurken"
    assert row["discord_email"] == "bobby@example.com"


def test_discord_callback_logs_in_existing_user(app_client, monkeypatch):
    profile = {
        "id": "111222333444555666",
        "username": "linked_user",
        "email": "linked@example.com",
    }
    ok, err, user = create_user_from_discord(profile)
    assert ok, err
    user_id = int(user["id"])

    def fake_complete(code: str):
        row = get_user_by_discord_id(profile["id"])
        return True, "discord_login_ok", dict(row)

    monkeypatch.setattr(discord_auth, "complete_discord_callback", fake_complete)

    with app_client.session_transaction() as sess:
        sess[SESSION_STATE_KEY] = "state-2"

    resp = app_client.get(
        "/auth/discord/callback?code=any&state=state-2",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/overview" in resp.headers.get("Location", "")

    with app_client.session_transaction() as sess:
        assert int(sess.get("user_id") or 0) == user_id


def test_discord_id_is_unique(temp_db, discord_env):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    profile = {"id": "555666777888999000", "username": "dup_discord"}
    ok, err, _ = create_user_from_discord(profile)
    assert ok, err

    ok2, err2, _ = create_user_from_discord(profile)
    assert not ok2
    assert err2 == "discord_id_taken"


def test_discord_register_does_not_merge_email(temp_db, discord_env):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    uname = f"email_owner_{uuid.uuid4().hex[:6]}"
    ok, _, _ = create_user(uname, "test-pass-123", email="shared@example.com")
    assert ok

    profile = {
        "id": "444555666777888999",
        "username": "discord_new",
        "email": "shared@example.com",
    }
    ok2, err2, user = create_user_from_discord(profile)
    assert ok2, err2
    assert user is not None

    row = get_user_by_discord_id("444555666777888999")
    assert row is not None
    assert row["discord_email"] == "shared@example.com"
    assert row["email"] in (None, "")


def test_login_page_shows_discord_button_first(app_client):
    resp = app_client.get("/login")
    assert resp.status_code == 200
    html = resp.data.decode("utf-8")
    assert "auth-btn-discord" in html
    assert "/auth/discord" in html
    discord_pos = html.index("auth-btn-discord")
    form_pos = html.index('data-validate="login"')
    assert discord_pos < form_pos
    assert 'data-no-pjax' in html
    assert "/auth/discord" in html


def test_discord_welcome_page_after_register(app_client, monkeypatch):
    profile = {
        "id": "welcome_page_user_001",
        "username": "WelcomeUser",
        "email": "welcome@example.com",
    }

    def fake_complete(code: str):
        ok, err, user = create_user_from_discord(profile)
        assert ok, err
        return True, "discord_register_ok", user

    monkeypatch.setattr(discord_auth, "complete_discord_callback", fake_complete)

    with app_client.session_transaction() as sess:
        sess[SESSION_STATE_KEY] = "welcome-state"

    app_client.get(
        "/auth/discord/callback?code=ok&state=welcome-state",
        follow_redirects=False,
    )

    resp = app_client.get("/welcome/discord")
    assert resp.status_code == 200
    assert b"discord.gg" in resp.data
    assert b"auth-welcome-checklist" in resp.data


def test_env_value_strips_surrounding_quotes(monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", '"quoted-secret"')
    import importlib
    import game.discord_auth as da
    importlib.reload(da)
    assert da._client_secret() == "quoted-secret"


def test_map_discord_token_error_invalid_client():
    from game.discord_auth import _map_discord_token_error

    assert _map_discord_token_error(401, '{"error":"invalid_client"}') == "discord_token_invalid_client"


def test_map_discord_token_error_redirect_mismatch():
    from game.discord_auth import _map_discord_token_error

    key = _map_discord_token_error(
        400,
        '{"error":"invalid_grant","error_description":"Invalid redirect_uri"}',
    )
    assert key == "discord_token_redirect_mismatch"


def test_map_discord_token_error_cloudflare_block():
    from game.discord_auth import _map_discord_token_error

    body = (
        '{"title":"Error 1010: Access denied","status":403,'
        '"error_code":1010,"error_name":"browser_signature_banned"}'
    )
    assert _map_discord_token_error(403, body) == "discord_token_cloudflare_blocked"


def test_http_post_form_sends_user_agent(monkeypatch):
    import game.discord_auth as da

    captured = {}

    def fake_urlopen(req, timeout=15):
        captured["user_agent"] = req.headers.get("User-agent") or req.headers.get("User-Agent")
        captured["accept"] = req.headers.get("Accept")
        class Resp:
            status = 200

            def read(self):
                return b'{"access_token":"tok"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    monkeypatch.setattr(da.urllib.request, "urlopen", fake_urlopen)
    status, _ = da._http_post_form("https://discord.com/api/oauth2/token", {"a": "b"})
    assert status == 200
    assert captured.get("user_agent")
    assert "Genesis-Colonies" in captured["user_agent"]
    assert captured.get("accept") == "application/json"


def test_exchange_code_for_token_sends_discord_api_headers(monkeypatch):
    import game.discord_auth as da

    captured: dict = {}

    def fake_urlopen(req, timeout=15):
        captured["user_agent"] = req.headers.get("User-agent") or req.headers.get("User-Agent")
        captured["accept"] = req.headers.get("Accept")
        captured["content_type"] = req.headers.get("Content-type") or req.headers.get("Content-Type")

        class Resp:
            status = 200

            def read(self):
                return b'{"access_token":"token-abc"}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    monkeypatch.setenv("DISCORD_CLIENT_ID", "cid")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "sec")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://www.genesis-colonies.de/auth/discord/callback")
    monkeypatch.setattr(da.urllib.request, "urlopen", fake_urlopen)

    ok, token, err = da.exchange_code_for_token("oauth-code-123")
    assert ok, err
    assert token == "token-abc"
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert captured["accept"] == "application/json"
    assert "Genesis-Colonies" in captured["user_agent"]


def test_complete_discord_callback_exchanges_code(temp_db, discord_env, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    _close_db()
    importlib.reload(discord_auth)

    monkeypatch.setattr(
        discord_auth,
        "_http_post_form",
        lambda url, data, headers=None: (200, '{"access_token":"token-123"}'),
    )
    monkeypatch.setattr(
        discord_auth,
        "_http_get_json",
        lambda url, token: (
            200,
            {
                "id": "123456789012345678",
                "username": "oauth_user",
                "email": "oauth@example.com",
            },
        ),
    )

    ok, err, user = discord_auth.complete_discord_callback("auth-code")
    assert ok, err
    assert user is not None
    assert get_user_by_discord_id("123456789012345678") is not None


def _session_login(client, user_id: int, username: str) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["username"] = str(username)


def test_discord_link_route_requires_login(app_client):
    resp = app_client.get("/auth/discord/link", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers.get("Location", "")


def test_discord_link_route_stores_link_mode(app_client):
    uname = f"linker_{uuid.uuid4().hex[:6]}"
    ok, _, user = create_user(uname, "known-pass-123", email="linker@example.com")
    assert ok
    _session_login(app_client, int(user["id"]), uname)

    resp = app_client.get("/auth/discord/link", follow_redirects=False)
    assert resp.status_code == 302
    assert "discord.com/api/oauth2/authorize" in resp.headers.get("Location", "")

    with app_client.session_transaction() as sess:
        assert sess.get(SESSION_LINK_MODE_KEY) == "1"
        assert sess.get(SESSION_STATE_KEY)


def test_link_discord_to_existing_account(temp_db, discord_env):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    uname = f"existing_{uuid.uuid4().hex[:6]}"
    ok, _, user = create_user(uname, "known-pass-123", email="existing@example.com")
    assert ok
    user_id = int(user["id"])

    profile = {"id": "link_target_001", "username": "LinkedPlayer", "avatar": "abc123"}
    ok2, err2, snap = link_discord_to_user(user_id, profile)
    assert ok2, err2
    assert snap and snap.get("discord_linked") is True
    assert snap.get("discord_username") == "LinkedPlayer"

    row = get_user_by_discord_id("link_target_001")
    assert row is not None
    assert int(row["id"]) == user_id


def test_link_rejects_discord_id_on_other_account(temp_db, discord_env):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    profile = {"id": "shared_discord_999", "username": "TakenDiscord"}
    ok, _, _ = create_user_from_discord(profile)
    assert ok

    uname = f"other_{uuid.uuid4().hex[:6]}"
    ok2, _, user = create_user(uname, "pass-123", email="other@example.com")
    assert ok2

    ok3, err3, _ = link_discord_to_user(int(user["id"]), profile)
    assert not ok3
    assert err3 == "discord_id_taken"


def test_unlink_discord_with_email(temp_db, discord_env):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    uname = f"unlink_email_{uuid.uuid4().hex[:6]}"
    ok, _, user = create_user(uname, "pass-123", email="unlink@example.com")
    assert ok
    user_id = int(user["id"])

    ok2, _, _ = link_discord_to_user(user_id, {"id": "unlink_email_discord", "username": "UnlinkMe"})
    assert ok2

    ok3, err3, snap = unlink_discord_from_user(user_id)
    assert ok3, err3
    assert snap and not snap.get("discord_linked")
    assert get_user_by_discord_id("unlink_email_discord") is None


def test_unlink_blocked_for_discord_only_without_password(temp_db, discord_env):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    profile = {"id": "discord_only_unlink", "username": "OnlyDiscord"}
    ok, _, user = create_user_from_discord(profile)
    assert ok
    user_id = int(user["id"])

    ok2, err2, _ = unlink_discord_from_user(user_id)
    assert not ok2
    assert err2 == "discord_unlink_no_fallback"


def test_unlink_allowed_with_password_when_no_email(temp_db, discord_env):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    uname = f"nopwemail_{uuid.uuid4().hex[:6]}"
    ok, _, user = create_user(uname, "my-secret-pass")
    assert ok
    user_id = int(user["id"])

    ok2, _, _ = link_discord_to_user(user_id, {"id": "pw_unlink_discord", "username": "PwUnlink"})
    assert ok2

    ok3, err3, snap = unlink_discord_from_user(user_id, current_password="my-secret-pass")
    assert ok3, err3
    assert snap and not snap.get("discord_linked")


def test_link_callback_redirects_to_options(app_client, monkeypatch):
    uname = f"cb_link_{uuid.uuid4().hex[:6]}"
    ok, _, user = create_user(uname, "pass-123", email="cblink@example.com")
    assert ok
    _session_login(app_client, int(user["id"]), uname)

    profile = {"id": "callback_link_001", "username": "CbLinkUser"}

    def fake_link(code, user_id):
        return link_discord_to_user(int(user_id), profile)

    monkeypatch.setattr(discord_auth, "complete_discord_link", fake_link)

    with app_client.session_transaction() as sess:
        sess[SESSION_STATE_KEY] = "link-state"
        sess[SESSION_LINK_MODE_KEY] = "1"

    resp = app_client.get(
        "/auth/discord/callback?code=ok&state=link-state",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/options" in resp.headers.get("Location", "")
    assert get_user_by_discord_id("callback_link_001") is not None
