"""
GC-SEC-P0 — password KDF, auth rate limits, CSRF, security headers.

Run: python -m pytest tests/test_gc_sec_p0.py -v
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import app as app_mod
import game.db as dbmod
import game.models as models
import game.security as security
from game.models import (
    create_user,
    hash_password,
    init_db,
    password_needs_upgrade,
    verify_password,
    verify_user,
)
from game.security import CSRF_SESSION_KEY, reset_auth_rate_limits

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc_sec_p0.db"
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
def app_client(temp_db, monkeypatch):
    reset_auth_rate_limits()
    _run_migrate(temp_db)
    init_db()
    _close_db()

    import importlib

    importlib.reload(security)
    importlib.reload(models)
    importlib.reload(app_mod)

    app_mod.app.config["TESTING"] = True
    client = app_mod.app.test_client()
    return client


def _csrf_token(client, path: str = "/login") -> str:
    client.get(path)
    with client.session_transaction() as sess:
        return str(sess.get(CSRF_SESSION_KEY) or "")


def test_hash_password_uses_argon2():
    stored = hash_password("secret-pass-123")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "secret-pass-123")
    assert not verify_password(stored, "wrong")


def test_legacy_sha256_verify_and_upgrade(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    uname = f"legacy_{uuid.uuid4().hex[:6]}"
    legacy_hash = hashlib.sha256(b"legacy-pass").hexdigest()
    conn = models.db()
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0);",
        (uname, legacy_hash),
    )
    conn.commit()
    conn.close()

    assert password_needs_upgrade(legacy_hash)
    user = verify_user(uname, "legacy-pass")
    assert user is not None

    conn = models.db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?;",
        (uname,),
    ).fetchone()
    conn.close()
    assert str(row["password_hash"]).startswith("$argon2")
    assert verify_password(row["password_hash"], "legacy-pass")


def test_legacy_pbkdf2_upgrades_on_login(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    uname = f"pbkdf2_{uuid.uuid4().hex[:6]}"
    from werkzeug.security import generate_password_hash

    legacy = generate_password_hash("pbkdf2-pass", method="pbkdf2:sha256")
    conn = models.db()
    conn.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0);",
        (uname, legacy),
    )
    conn.commit()
    conn.close()

    assert password_needs_upgrade(legacy)
    assert verify_user(uname, "pbkdf2-pass") is not None

    conn = models.db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username = ?;",
        (uname,),
    ).fetchone()
    conn.close()
    assert str(row["password_hash"]).startswith("$argon2")


def test_login_rate_limit_blocks_bruteforce(app_client, monkeypatch):
    monkeypatch.setattr(security, "LOGIN_RATE_MAX", 3)
    monkeypatch.setattr(security, "LOGIN_RATE_WINDOW_SEC", 600.0)
    reset_auth_rate_limits()

    token = _csrf_token(app_client)
    for _ in range(3):
        res = app_client.post(
            "/login",
            data={"username": "nobody", "password": "wrong", "csrf_token": token},
        )
        assert res.status_code == 200

    blocked = app_client.post(
        "/login",
        data={"username": "nobody", "password": "wrong", "csrf_token": token},
    )
    assert blocked.status_code == 200
    assert "Zu viele Versuche" in blocked.get_data(as_text=True) or "Too many attempts" in blocked.get_data(as_text=True)


def test_register_rate_limit(app_client, monkeypatch):
    monkeypatch.setattr(security, "REGISTER_RATE_MAX", 2)
    monkeypatch.setattr(security, "REGISTER_RATE_WINDOW_SEC", 3600.0)
    reset_auth_rate_limits()

    token = _csrf_token(app_client, "/register")
    for i in range(2):
        email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        res = app_client.post(
            "/register",
            data={
                "username": f"reg_{uuid.uuid4().hex[:6]}",
                "email": email,
                "password": "test-pass-123",
                "password2": "test-pass-123",
                "csrf_token": token,
            },
        )
        assert res.status_code in (200, 302)

    blocked = app_client.post(
        "/register",
        data={
            "username": f"reg_{uuid.uuid4().hex[:6]}",
            "email": f"blocked_{uuid.uuid4().hex[:6]}@example.com",
            "password": "test-pass-123",
            "password2": "test-pass-123",
            "csrf_token": token,
        },
    )
    assert blocked.status_code == 200
    assert "Zu viele Versuche" in blocked.get_data(as_text=True) or "Too many attempts" in blocked.get_data(as_text=True)


def test_csrf_blocks_login_without_token(app_client, monkeypatch):
    monkeypatch.setitem(app_mod.app.config, "TESTING", False)

    res = app_client.post(
        "/login",
        data={"username": "nobody", "password": "wrong"},
    )
    assert res.status_code == 200
    assert "Sitzung abgelaufen" in res.get_data(as_text=True) or "Session expired" in res.get_data(as_text=True)


def test_security_headers_on_health(app_client):
    res = app_client.get("/health")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_session_cookie_flags_configured(app_client):
    assert app_mod.app.config.get("SESSION_COOKIE_HTTPONLY") is True
    assert app_mod.app.config.get("SESSION_COOKIE_SAMESITE") == "Lax"


def test_create_user_hashes_with_argon2(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db()

    uname = f"new_{uuid.uuid4().hex[:6]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok is True
    assert user is not None

    conn = models.db()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id = ?;",
        (int(user["id"]),),
    ).fetchone()
    conn.close()
    assert str(row["password_hash"]).startswith("$argon2")
