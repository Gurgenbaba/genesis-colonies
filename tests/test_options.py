"""
Account options page and API tests.

Run: python -m pytest tests/test_options.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db, verify_password
from game.options import reset_sensitive_rate_limits
from game.options import (
    ACCOUNT_SAFETY_CONFIRM_PHRASES,
    cancel_account_deletion,
    ensure_account_options_schema,
    ensure_account_safety_schema,
    get_account_safety_snapshot,
    get_options_snapshot,
    reset_sensitive_rate_limits,
    update_active_planet_name,
    update_email,
    update_homeworld_name,
    update_password,
    update_player_name,
    validate_display_name,
)
from game.planet_evolution.repository import set_active_planet_id
from game.planet_evolution.service import colonize_planet
from game.security import reset_auth_rate_limits

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "options_test.db"
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


def _close_db_conn() -> None:
    try:
        models.db().close()
    except Exception:
        pass


def _create_player(username: str | None = None) -> tuple[int, str, str]:
    uname = username or f"opt_{uuid.uuid4().hex[:8]}"
    password = "test-pass-123"
    ok, err, user = create_user(uname, password)
    assert ok and user and user.get("id"), err
    _close_db_conn()
    return int(user["id"]), uname, password


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    reset_sensitive_rate_limits()
    reset_auth_rate_limits()
    _run_migrate(temp_db)
    init_db()
    ensure_account_options_schema()
    _close_db_conn()

    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _login(client, username: str, password: str = "test-pass-123") -> None:
    res = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert res.status_code in (302, 303)


def test_options_page_requires_login(app_client):
    res = app_client.get("/options")
    assert res.status_code in (302, 303)
    assert "/login" in (res.headers.get("Location") or "")


def test_options_page_logged_in(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res = app_client.get("/options")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "options-page" in body or "Optionen" in body or "Options" in body
    assert 'id="options-form-player-name"' in body
    assert 'type="submit"' in body
    assert "js/options.js" in body


def test_options_snapshot_raw_player_name(temp_db):
    _run_migrate(temp_db)
    init_db()
    ensure_account_options_schema()
    raw = f"RawName_{uuid.uuid4().hex[:6]}"
    pid, _, _ = _create_player()
    conn = models.db()
    conn.execute("UPDATE players SET name = ? WHERE id = ?;", (raw, pid))
    conn.commit()
    conn.close()
    snap = get_options_snapshot(pid)
    assert snap["player_name"] == raw
    assert "Commander " not in snap["player_name"]


def test_update_player_name_ok(app_client, temp_db):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    new_name = f"Alpha_{uuid.uuid4().hex[:6]}"
    res = app_client.post(
        "/api/options/player-name",
        json={"player_name": new_name},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["data"]["player_name"] == new_name


def test_api_player_name_updates_db(app_client, temp_db):
    """POST player_name must persist exact value in players.name."""
    pid, uname, _ = _create_player()
    target = f"Gurkenvater_{uuid.uuid4().hex[:6]}"
    _close_db_conn()
    conn = models.db()
    conn.execute("UPDATE players SET name = ? WHERE id = ?;", ("Commander Gurkenvater", pid))
    conn.commit()
    conn.close()

    _login(app_client, uname)
    res = app_client.post(
        "/api/options/player-name",
        json={"player_name": target},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["ok"] is True
    assert body["data"]["player_name"] == target

    conn = models.db()
    row = conn.execute("SELECT name FROM players WHERE id = ?;", (pid,)).fetchone()
    conn.close()
    assert row["name"] == target
    assert "Commander " not in row["name"]


def test_options_forms_prevent_native_nav(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res = app_client.get("/options")
    html = res.get_data(as_text=True)
    assert 'id="options-form-player-name"' in html
    assert 'method="post"' in html
    assert 'action="#"' in html
    main_src = open(ROOT / "static" / "main.js", encoding="utf-8").read()
    assert "initOptionsFormsCapture" in main_src
    assert "GC.runOptionsFormSave" in main_src
    assert "OPTIONS_FORM_ROUTES" in main_src


def test_player_name_validation(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)

    for bad in ("", "x", "<script>", "a" * 41):
        res = app_client.post(
            "/api/options/player-name",
            json={"player_name": bad},
            headers={"Accept": "application/json"},
        )
        assert res.status_code == 400
        assert res.get_json()["ok"] is False


def test_player_name_duplicate(app_client):
    pid1, u1, _ = _create_player()
    pid2, u2, _ = _create_player()
    _close_db_conn()
    conn = models.db()
    conn.execute("UPDATE players SET name = ? WHERE id = ?;", ("TakenName", pid1))
    conn.commit()
    conn.close()

    _login(app_client, u2)
    res = app_client.post(
        "/api/options/player-name",
        json={"player_name": "TakenName"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 400
    assert res.get_json()["error"] == "options_error_name_taken"


def test_update_planet_name(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    new_name = f"Nova_{uuid.uuid4().hex[:6]}"
    res = app_client.post(
        "/api/options/planet-name",
        json={"planet_name": new_name},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["active_planet_name"] == new_name
    assert data.get("homeworld_name") == new_name


def test_update_planet_name_active_colony(app_client):
    pid, uname, _ = _create_player()
    ok, reason, extra = colonize_planet(pid, name="Colony Alpha", galaxy=1, system=400, position=3)
    assert ok, reason
    colony_id = int(extra["planet_id"])
    conn = models.db()
    set_active_planet_id(pid, colony_id, conn)
    conn.commit()
    conn.close()

    _login(app_client, uname)
    new_name = f"Colony_{uuid.uuid4().hex[:6]}"
    res = app_client.post(
        "/api/options/planet-name",
        json={"planet_name": new_name},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    assert res.get_json()["data"]["planet_id"] == colony_id
    assert res.get_json()["data"]["active_planet_name"] == new_name


def test_email_validation_and_duplicate(app_client):
    pid1, u1, _ = _create_player()
    email = f"one_{uuid.uuid4().hex[:6]}@example.com"
    ok, err, _ = update_email(pid1, email)
    assert ok, err
    _close_db_conn()

    pid2, u2, _ = _create_player()
    _login(app_client, u2)

    res_bad = app_client.post(
        "/api/options/email",
        json={"email": "not-an-email"},
        headers={"Accept": "application/json"},
    )
    assert res_bad.status_code == 400

    res_dup = app_client.post(
        "/api/options/email",
        json={"email": email},
        headers={"Accept": "application/json"},
    )
    assert res_dup.status_code == 400
    assert res_dup.get_json()["error"] == "options_error_email_taken"

    good_email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    res_ok = app_client.post(
        "/api/options/email",
        json={"email": good_email},
        headers={"Accept": "application/json"},
    )
    assert res_ok.status_code == 200


def test_password_change(app_client):
    pid, uname, password = _create_player()
    _login(app_client, uname)

    res_wrong = app_client.post(
        "/api/options/password",
        json={
            "current_password": "wrong",
            "new_password": "newpass1",
            "confirm_password": "newpass1",
        },
        headers={"Accept": "application/json"},
    )
    assert res_wrong.status_code == 400
    assert res_wrong.get_json()["error"] == "options_error_password_wrong"

    res_mismatch = app_client.post(
        "/api/options/password",
        json={
            "current_password": password,
            "new_password": "newpass1",
            "confirm_password": "newpass2",
        },
        headers={"Accept": "application/json"},
    )
    assert res_mismatch.status_code == 400
    assert res_mismatch.get_json()["error"] == "options_error_password_mismatch"

    res_short = app_client.post(
        "/api/options/password",
        json={
            "current_password": password,
            "new_password": "ab",
            "confirm_password": "ab",
        },
        headers={"Accept": "application/json"},
    )
    assert res_short.status_code == 400
    assert res_short.get_json()["error"] == "options_error_password_short"

    res_ok = app_client.post(
        "/api/options/password",
        json={
            "current_password": password,
            "new_password": "newpass9",
            "confirm_password": "newpass9",
        },
        headers={"Accept": "application/json"},
    )
    assert res_ok.status_code == 200

    _close_db_conn()
    conn = models.db()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?;", (pid,)).fetchone()
    conn.close()
    assert verify_password(row["password_hash"], "newpass9")
    assert str(row["password_hash"]).startswith("$argon2")


def test_api_requires_login(app_client):
    res = app_client.post(
        "/api/options/player-name",
        json={"player_name": "Test"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 401
    data = res.get_json()
    assert data["ok"] is False


def test_html_injection_rejected():
    ok, err, _ = validate_display_name("<script>alert(1)</script>")
    assert not ok
    assert err == "options_error_invalid_name"

    ok2, err2, cleaned = validate_display_name("Valid_Name-1")
    assert ok2
    assert cleaned == "Valid_Name-1"


def test_language_switcher_in_header(app_client):
    res = app_client.get("/login")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="gc-language-switcher"' in html
    assert 'data-locale="de"' in html
    assert 'data-api="/api/locale"' in html


def test_api_locale_cookie_guest(app_client):
    res = app_client.post(
        "/api/locale",
        json={"locale": "en"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["data"]["locale"] == "en"
    cookies = res.headers.getlist("Set-Cookie")
    assert any("gc_locale=en" in c for c in cookies)

    res_page = app_client.get("/login")
    assert res_page.status_code == 200
    assert 'data-locale="en"' in res_page.get_data(as_text=True)


def test_api_locale_invalid(app_client):
    res = app_client.post(
        "/api/locale",
        json={"locale": "fr"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 400
    assert res.get_json()["error"] == "options_error_invalid_locale"


def test_api_options_locale_logged_in(app_client):
    from game.i18n import get_player_locale

    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res = app_client.post(
        "/api/options/locale",
        json={"locale": "en"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["data"]["locale"] == "en"
    assert get_player_locale(pid) == "en"


def test_options_page_account_safety_card(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res = app_client.get("/options")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "options-account-safety" in html
    assert "options-safety-vacation" in html
    assert "options-safety-deletion" in html
    assert "options-safety-reset" in html


def test_vacation_enable_requires_confirm(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res = app_client.post(
        "/api/options/vacation/enable",
        json={"confirm_text": "wrong"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 400
    assert res.get_json()["error"] == "options_error_confirm_required"


def test_vacation_enable_and_disable(app_client):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res_on = app_client.post(
        "/api/options/vacation/enable",
        json={"confirm_text": ACCOUNT_SAFETY_CONFIRM_PHRASES["vacation_enable"]},
        headers={"Accept": "application/json"},
    )
    assert res_on.status_code == 200, res_on.get_json()
    assert res_on.get_json()["data"]["vacation_active"] is True

    res_off = app_client.post(
        "/api/options/vacation/disable",
        json={"confirm_text": "DISABLE VACATION"},
        headers={"Accept": "application/json"},
    )
    assert res_off.status_code == 400
    assert res_off.get_json()["error"] == "options_error_vacation_locked"


def test_account_deletion_request_and_cancel(app_client, temp_db):
    pid, uname, _ = _create_player()
    _login(app_client, uname)
    res_req = app_client.post(
        "/api/options/account-deletion/request",
        json={"confirm_text": ACCOUNT_SAFETY_CONFIRM_PHRASES["account_delete"]},
        headers={"Accept": "application/json"},
    )
    assert res_req.status_code == 200
    assert res_req.get_json()["data"]["deletion_pending"] is True

    res_cancel = app_client.post(
        "/api/options/account-deletion/cancel",
        json={},
        headers={"Accept": "application/json"},
    )
    assert res_cancel.status_code == 200
    assert res_cancel.get_json()["data"]["deletion_pending"] is False


def test_account_reset_wipes_colonies(app_client):
    pid, uname, password = _create_player()
    ok, reason, extra = colonize_planet(pid, name="Colony Beta", galaxy=1, system=401, position=4)
    assert ok, reason
    _login(app_client, uname)
    res = app_client.post(
        "/api/options/account-reset",
        json={
            "confirm_text": ACCOUNT_SAFETY_CONFIRM_PHRASES["account_reset"],
            "current_password": password,
        },
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200, res.get_json()
    conn = models.db()
    count = conn.execute("SELECT COUNT(*) AS c FROM planets WHERE player_id = ?;", (pid,)).fetchone()["c"]
    conn.close()
    assert int(count) == 1


def test_account_safety_snapshot(temp_db):
    _run_migrate(temp_db)
    init_db()
    ensure_account_safety_schema()
    pid, _, _ = _create_player()
    snap = get_account_safety_snapshot(pid)
    assert snap["vacation_active"] is False
    assert snap["deletion_pending"] is False
    assert "confirm_phrases" in snap
