"""Sign-in universe choice must survive the auth pages and the Discord OAuth round trip.

Follow-up to the sign-in chooser (#517/#518). Two review findings:

* the pending target kept in the session (``gc_network_target``) was ignored by the chooser, and the
  login <-> register links dropped it, so a first-time visitor sent from UNI1 landed on DEV;
* Discord OAuth never carried the chosen universe, so Discord players always ended up on DEV.

Identity stays on the authority (DEV), every universe keeps its own game data, and the only way
into another universe is still the signed ``/network/universe/<key>/enter`` hand-off.
"""
from __future__ import annotations

import importlib
import re
import uuid

import pytest

from game import discord_auth
from game.discord_auth import SESSION_STATE_KEY, create_user_from_discord
from game.network_auth import OAUTH_TARGET_SESSION_KEY
from tests.test_gc_login_last_universe import (  # noqa: F401  (authority is a pytest fixture)
    COOKIE,
    ROOT,
    _env,
    _radios,
    _set_cookie_headers,
    authority,
)


# --- pending target across the auth pages (login <-> register) ------------------------------------


def test_pending_session_target_survives_login_to_register_navigation(authority):
    client = authority()
    client.set_cookie(COOKIE, "dev")
    client.get("/login?network_target=uni1")  # what UNI1 redirects a first-time visitor to
    html = client.get("/register").get_data(as_text=True)  # the "create account" link without a query
    assert _radios(html) == {"dev": False, "uni1": True}


def test_explicit_authority_target_clears_the_pending_target(authority):
    client = authority()
    client.get("/login?network_target=uni1")
    assert _radios(client.get("/login?network_target=dev").get_data(as_text=True)) == {"dev": True, "uni1": False}
    assert _radios(client.get("/register").get_data(as_text=True)) == {"dev": True, "uni1": False}


def test_closed_universe_is_ignored_even_when_it_is_pending(authority, monkeypatch):
    client = authority()
    client.get("/login?network_target=uni1")
    _env(monkeypatch, uni1_open="0")
    assert _radios(client.get("/register").get_data(as_text=True)) == {}
    resp = client.post("/login", data={"username": "nobody", "password": "x" * 8})
    assert resp.status_code == 200  # failed login: no hand-off towards the closed universe


def test_auth_page_links_carry_the_selected_universe(authority):
    client = authority()
    login = client.get("/login?network_target=uni1").get_data(as_text=True)
    assert 'href="/register?network_target=uni1"' in login
    register = client.get("/register").get_data(as_text=True)
    assert 'href="/login?network_target=uni1"' in register
    dev = authority().get("/login?network_target=dev").get_data(as_text=True)
    assert 'href="/register?network_target=dev"' in dev


def test_chooser_script_keeps_switch_and_discord_links_in_sync():
    partial = (ROOT / "templates" / "partials" / "auth_universe_choice.html").read_text(encoding="utf-8")
    for hook in ("data-auth-discord-link", "data-auth-discord-register", "data-auth-switch-link"):
        assert hook in partial
    assert "searchParams.set('network_target', radio.value)" in partial


def _register_form(client, **extra):
    name = f"reg_{uuid.uuid4().hex[:8]}"
    data = {
        "username": name,
        "email": f"{name}@example.com",
        "password": "secret-pass-1",
        "password2": "secret-pass-1",
        "age_ok": "1",
        "legal_ack": "1",
    }
    data.update(extra)
    return client.post("/register", data=data)


def test_register_after_login_page_visit_hands_off_to_uni1(authority):
    client = authority()
    client.get("/login?network_target=uni1")
    html = client.get("/register").get_data(as_text=True)
    chosen = [value for value, checked in _radios(html).items() if checked]
    assert chosen == ["uni1"]
    resp = _register_form(client, network_target=chosen[0])
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/network/universe/uni1/enter")
    cookies = _set_cookie_headers(resp)
    assert len(cookies) == 1 and cookies[0].startswith(f"{COOKIE}=uni1")


def test_register_with_dev_selected_stays_on_dev(authority):
    client = authority()
    client.get("/login?network_target=uni1")
    resp = _register_form(client, network_target="dev")
    assert resp.status_code == 302
    assert "/network/universe/" not in resp.headers["Location"]


# --- Discord OAuth keeps the universe picked on the sign-in page ----------------------------------


@pytest.fixture()
def discord(authority, monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://dev.genesis-colonies.com/auth/discord/callback")
    return authority


def _discord_user(prefix: str = "dc"):
    ok, err, user = create_user_from_discord(
        {"id": str(uuid.uuid4().int)[:18], "username": f"{prefix}_{uuid.uuid4().hex[:6]}", "email": ""}
    )
    assert ok, err
    return user


def _fake_discord_login(monkeypatch, user, key: str = "discord_login_ok"):
    def fake_complete(code, *, allow_register=False):
        return True, key, user

    monkeypatch.setattr(discord_auth, "complete_discord_callback", fake_complete)


def _callback(client, target, state: str = "oauth-state", sent_state: str | None = None):
    with client.session_transaction() as sess:
        sess[SESSION_STATE_KEY] = state
        if target is not None:
            sess[OAUTH_TARGET_SESSION_KEY] = target
    return client.get(f"/auth/discord/callback?code=ok&state={sent_state or state}")


def test_discord_buttons_on_login_and_register_carry_the_selection(discord):
    client = discord()
    login = client.get("/login?network_target=uni1").get_data(as_text=True)
    assert 'href="/auth/discord?network_target=uni1"' in login
    register = client.get("/register").get_data(as_text=True)
    assert 'href="/auth/discord?network_target=uni1"' in register


def test_discord_start_keeps_the_choice_in_the_session_not_in_the_oauth_request(discord):
    client = discord()
    resp = client.get("/auth/discord?network_target=uni1")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("https://discord.com/api/oauth2/authorize?")
    assert "uni1" not in location and "network_target" not in location  # Discord never sees it
    with client.session_transaction() as sess:
        assert sess[OAUTH_TARGET_SESSION_KEY] == "uni1"
        assert f"state={sess[SESSION_STATE_KEY]}" in location  # existing CSRF state untouched


def test_discord_start_falls_back_to_pending_target_then_cookie_then_nothing(discord):
    client = discord()
    client.get("/login?network_target=uni1")
    client.get("/auth/discord")
    with client.session_transaction() as sess:
        assert sess[OAUTH_TARGET_SESSION_KEY] == "uni1"

    other = discord()
    other.set_cookie(COOKIE, "uni1")
    other.get("/auth/discord")
    with other.session_transaction() as sess:
        assert sess[OAUTH_TARGET_SESSION_KEY] == "uni1"

    fresh = discord()
    fresh.get("/auth/discord")
    with fresh.session_transaction() as sess:
        assert OAUTH_TARGET_SESSION_KEY not in sess


def test_discord_start_rejects_unknown_foreign_and_closed_targets(discord, monkeypatch):
    for bad in ("evil", "uni99", "https://evil.example", "//evil.example", "uni1;x"):
        client = discord()
        client.get("/auth/discord", query_string={"network_target": bad})
        with client.session_transaction() as sess:
            assert OAUTH_TARGET_SESSION_KEY not in sess, bad
    _env(monkeypatch, uni1_open="0")
    client = discord()
    client.get("/auth/discord?network_target=uni1")
    with client.session_transaction() as sess:
        assert OAUTH_TARGET_SESSION_KEY not in sess


def test_discord_start_restart_drops_a_stale_target(discord):
    client = discord()
    client.get("/auth/discord?network_target=uni1")
    client.get("/auth/discord?network_target=dev")
    with client.session_transaction() as sess:
        assert sess[OAUTH_TARGET_SESSION_KEY] == "dev"


def test_discord_login_hands_off_to_the_chosen_universe(discord, monkeypatch):
    user = _discord_user()
    _fake_discord_login(monkeypatch, user)
    client = discord()
    resp = _callback(client, "uni1")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/network/universe/uni1/enter")  # internal path only
    cookies = _set_cookie_headers(resp)
    assert len(cookies) == 1 and cookies[0].startswith(f"{COOKIE}=uni1")
    with client.session_transaction() as sess:
        assert int(sess.get("user_id") or 0) == int(user["id"])  # identity signed in on the authority
        assert OAUTH_TARGET_SESSION_KEY not in sess  # consumed

    enter = client.get("/network/universe/uni1/enter")
    assert enter.status_code == 302
    assert enter.headers["Location"].startswith("https://uni1.genesis-colonies.com/network/handoff?token=")


def test_discord_login_with_dev_choice_stays_on_dev(discord, monkeypatch):
    _fake_discord_login(monkeypatch, _discord_user())
    client = discord()
    client.set_cookie(COOKIE, "uni1")
    resp = _callback(client, "dev")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/overview")
    cookies = _set_cookie_headers(resp)
    assert len(cookies) == 1 and cookies[0].startswith(f"{COOKIE}=dev")


def test_discord_login_without_a_choice_behaves_like_before(discord, monkeypatch):
    _fake_discord_login(monkeypatch, _discord_user())
    resp = _callback(discord(), None)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/overview")


def test_discord_login_never_hands_off_to_a_universe_that_closed_meanwhile(discord, monkeypatch):
    _fake_discord_login(monkeypatch, _discord_user())
    client = discord()
    client.get("/auth/discord?network_target=uni1")
    with client.session_transaction() as sess:
        state = sess[SESSION_STATE_KEY]
    _env(monkeypatch, uni1_open="0")
    resp = client.get(f"/auth/discord/callback?code=ok&state={state}")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/overview")
    assert "/network/universe/" not in resp.headers["Location"]


def test_discord_callback_with_invalid_state_neither_signs_in_nor_hands_off(discord, monkeypatch):
    _fake_discord_login(monkeypatch, _discord_user())
    client = discord()
    resp = _callback(client, "uni1", state="real-state", sent_state="forged-state")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "/network/universe/" not in location and "/overview" not in location
    assert location.endswith("/login?network_target=uni1")  # back to the form with the choice kept
    with client.session_transaction() as sess:
        assert not sess.get("user_id")
        assert OAUTH_TARGET_SESSION_KEY not in sess  # popped even on failure
    assert _set_cookie_headers(resp) == []


def test_discord_callback_failure_returns_to_the_form_with_the_choice(discord, monkeypatch):
    def failing(code, *, allow_register=False):
        return False, "discord_oauth_failed", None

    monkeypatch.setattr(discord_auth, "complete_discord_callback", failing)
    resp = _callback(discord(), "uni1")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login?network_target=uni1")

    def needs_ack(code, *, allow_register=False):
        return False, "discord_register_ack_required", None

    monkeypatch.setattr(discord_auth, "complete_discord_callback", needs_ack)
    resp = _callback(discord(), "uni1")
    assert resp.headers["Location"].endswith("/register?network_target=uni1")


def test_discord_register_keeps_the_welcome_page_and_carries_the_choice(discord, monkeypatch):
    _fake_discord_login(monkeypatch, _discord_user("newdc"), key="discord_register_ok")
    client = discord()
    resp = _callback(client, "uni1")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/welcome/discord?network_target=uni1")

    assert _welcome_overview_href(client.get("/welcome/discord?network_target=uni1")) == "/network/universe/uni1/enter"
    # an unknown / foreign / closed value never becomes a link target
    for bad in ("https://evil.example", "//evil.example", "uni99"):
        odd = client.get("/welcome/discord", query_string={"network_target": bad})
        assert odd.status_code == 200
        assert _welcome_overview_href(odd) == "/overview", bad


def _welcome_overview_href(response) -> str:
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    match = re.search(r'<a href="([^"]*)"\s+class="[^"]*auth-welcome-overview-btn', html)
    assert match, "welcome overview button not found"
    return match.group(1)


def test_discord_register_on_dev_goes_to_the_welcome_page_as_before(discord, monkeypatch):
    _fake_discord_login(monkeypatch, _discord_user("newdc2"), key="discord_register_ok")
    resp = _callback(discord(), "dev")
    assert resp.headers["Location"].endswith("/welcome/discord")


def test_discord_link_flow_ignores_the_universe_choice(discord):
    user = _discord_user("linker")
    client = discord()
    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])
    resp = client.get("/auth/discord/link")
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert OAUTH_TARGET_SESSION_KEY not in sess


# --- UNI1 itself never takes credentials or starts OAuth -----------------------------------------


@pytest.fixture()
def uni1_app(authority, monkeypatch):
    _env(monkeypatch, universe="uni1")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://dev.genesis-colonies.com/auth/discord/callback")
    import app as app_mod
    import game.network_auth as network_auth

    importlib.reload(network_auth)
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client


def test_uni1_sends_login_and_register_to_the_authority_with_its_own_key(uni1_app):
    client = uni1_app()
    for path in ("/login", "/register"):
        resp = client.get(path)
        assert resp.status_code == 302
        assert resp.headers["Location"] == f"https://dev.genesis-colonies.com{path}?network_target=uni1"


def test_uni1_never_starts_discord_oauth_or_stashes_a_target(uni1_app):
    client = uni1_app()
    resp = client.get("/auth/discord?network_target=uni1")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("https://dev.genesis-colonies.com/")
    assert "discord.com" not in resp.headers["Location"]
    with client.session_transaction() as sess:
        assert OAUTH_TARGET_SESSION_KEY not in sess


def test_oauth_target_helpers_are_inert_off_the_authority(authority, monkeypatch):
    _env(monkeypatch, universe="uni1")
    import game.network_auth as network_auth

    importlib.reload(network_auth)
    from flask import Flask

    app = Flask(__name__)
    app.secret_key = "unit-test"
    with app.test_request_context("/auth/discord?network_target=uni1"):
        assert network_auth.stash_oauth_target("uni1") == ""
        assert network_auth.take_oauth_target() == ""
