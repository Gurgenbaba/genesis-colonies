"""Sign-in universe chooser on the identity authority (DEV): preselection of the last universe.

The chooser is only a convenience. Identity stays on DEV, every universe keeps its own game
data, and the chosen key is handled by the existing ``network_target`` hand-off.
"""
from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import create_user, init_db

ROOT = Path(__file__).resolve().parent.parent
COOKIE = "gc_last_universe"


def _env(monkeypatch, *, uni1_open: str = "1", universe: str = "dev") -> None:
    monkeypatch.setenv("GC_UNIVERSE_KEY", universe)
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_KEY", "dev")
    monkeypatch.setenv("GC_NETWORK_AUTH_SECRET", "network-test-secret-" + ("x" * 48))
    monkeypatch.setenv("GC_NETWORK_DOMAIN", "genesis-colonies.com")
    monkeypatch.setenv("GC_NETWORK_AUTHORITY_URL", "https://dev.genesis-colonies.com")
    monkeypatch.setenv("GC_NETWORK_UNIVERSES", "uni1")
    monkeypatch.setenv("GC_NETWORK_UNI1_OPEN", uni1_open)


@pytest.fixture()
def authority(tmp_path, monkeypatch):
    db_file = tmp_path / "login_universe.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    _env(monkeypatch)
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(ROOT / "migrate.py")], cwd=str(ROOT), capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()
    try:
        db().close()
    except Exception:
        pass

    import game.network_auth as network_auth
    import app as app_mod

    importlib.reload(network_auth)
    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True

    def make_client():
        return app_mod.app.test_client()

    return make_client


def _user() -> tuple[str, str]:
    name = f"lu_{uuid.uuid4().hex[:8]}"
    ok, err, _ = create_user(name, "secret-pass-1")
    assert ok, err
    return name, "secret-pass-1"


def _radios(html: str) -> dict[str, bool]:
    """{network_target value: checked} for the chooser radios."""
    found: dict[str, bool] = {}
    for tag in re.findall(r'<input[^>]*name="network_target"[^>]*>', html):
        value = re.search(r'value="([^"]*)"', tag).group(1)
        found[value] = " checked" in tag
    return found


def _set_cookie_headers(response) -> list[str]:
    return [h for h in response.headers.getlist("Set-Cookie") if h.startswith(COOKIE + "=")]


def test_chooser_defaults_to_dev_without_history(authority):
    html = authority().get("/login").get_data(as_text=True)
    assert _radios(html) == {"dev": True, "uni1": False}
    assert "auth-universe-choice-tag" not in html


def test_chooser_preselects_last_universe_and_marks_it(authority):
    client = authority()
    client.set_cookie(COOKIE, "uni1")
    html = client.get("/login").get_data(as_text=True)
    assert _radios(html) == {"dev": False, "uni1": True}
    assert html.count('class="auth-universe-choice-tag"') == 1  # only the last universe is tagged


def test_unknown_or_foreign_cookie_values_are_ignored(authority):
    for bad in ("evil", "uni99", "DEV;x", ""):
        client = authority()
        client.set_cookie(COOKIE, bad)
        html = client.get("/login").get_data(as_text=True)
        assert _radios(html) == {"dev": True, "uni1": False}, bad


def test_explicit_network_target_beats_the_cookie(authority):
    client = authority()
    client.set_cookie(COOKIE, "dev")
    html = client.get("/login?network_target=uni1").get_data(as_text=True)
    assert _radios(html) == {"dev": False, "uni1": True}


def test_register_page_offers_the_same_chooser(authority):
    client = authority()
    client.set_cookie(COOKIE, "uni1")
    assert _radios(client.get("/register").get_data(as_text=True)) == {"dev": False, "uni1": True}


def test_closed_universe_is_not_offered_or_preselected(authority, monkeypatch):
    _env(monkeypatch, uni1_open="0")
    client = authority()
    client.set_cookie(COOKIE, "uni1")
    html = client.get("/login").get_data(as_text=True)
    assert "auth-universe-choice" not in html  # a single open universe: no chooser at all
    assert _radios(html) == {}


def test_login_with_uni1_selected_hands_off_and_remembers_it(authority):
    name, pw = _user()
    client = authority()
    resp = client.post("/login", data={"username": name, "password": pw, "network_target": "uni1"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/network/universe/uni1/enter")
    cookies = _set_cookie_headers(resp)
    assert len(cookies) == 1 and cookies[0].startswith(f"{COOKIE}=uni1")
    assert "HttpOnly" in cookies[0] and "SameSite=Lax" in cookies[0]


def test_login_with_dev_selected_stays_on_dev_even_if_uni1_was_last(authority):
    name, pw = _user()
    client = authority()
    client.set_cookie(COOKIE, "uni1")
    resp = client.post("/login", data={"username": name, "password": pw, "network_target": "dev"})
    assert resp.status_code == 302
    assert "/network/universe/" not in resp.headers["Location"]
    cookies = _set_cookie_headers(resp)
    assert len(cookies) == 1 and cookies[0].startswith(f"{COOKIE}=dev")


def test_failed_login_keeps_the_choice_and_sets_no_cookie(authority):
    name, _pw = _user()
    client = authority()
    resp = client.post("/login", data={"username": name, "password": "wrong-password", "network_target": "uni1"})
    assert resp.status_code == 200
    assert _radios(resp.get_data(as_text=True)) == {"dev": False, "uni1": True}
    assert _set_cookie_headers(resp) == []


def test_non_authority_universe_never_renders_a_chooser(authority, monkeypatch):
    _env(monkeypatch, universe="uni1")
    import game.network_auth as network_auth

    importlib.reload(network_auth)
    from flask import Flask

    app = Flask(__name__)
    with app.test_request_context("/login"):
        assert network_auth.login_universe_choice() == {"options": [], "selected": "", "last": ""}


def test_universe_badge_is_replaced_by_the_chooser_when_it_is_shown(authority, monkeypatch):
    client = authority()
    assert "auth-universe-badge" not in client.get("/login").get_data(as_text=True)
    assert "auth-universe-badge" not in client.get("/register").get_data(as_text=True)
    # a single open universe: no chooser, so the static badge stays
    _env(monkeypatch, uni1_open="0")
    assert "auth-universe-badge" in authority().get("/login").get_data(as_text=True)
