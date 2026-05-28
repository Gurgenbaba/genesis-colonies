"""
Account email verification and password reset tests.

Run: python -m pytest tests/test_account_email.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.account_email import (
    issue_email_verification,
    register_user_with_email,
    request_password_reset,
    resend_verification_email,
    reset_account_email_rate_limits,
    reset_password_with_token,
    verify_email_token,
)
from game.db import db
from game.mail import send_mail
from game.models import create_user, init_db, verify_user

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "account_email_test.db"
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
        db().close()
    except Exception:
        pass


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    reset_account_email_rate_limits()
    _run_migrate(temp_db)
    init_db()
    _close_db()

    sent = []

    def _fake_send(to, subject, text, html=None):
        sent.append({"to": to, "subject": subject, "text": text, "html": html})
        return True

    monkeypatch.setattr("game.account_email.send_mail", _fake_send)
    monkeypatch.setattr("game.mail.send_mail", _fake_send)

    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    client = app_mod.app.test_client()
    client._sent_mails = sent  # type: ignore[attr-defined]
    return client


def test_register_with_email(app_client):
    email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"reg_{uuid.uuid4().hex[:6]}"
    res = app_client.post(
        "/register",
        data={
            "username": uname,
            "email": email,
            "password": "secret123",
            "password2": "secret123",
        },
        follow_redirects=False,
    )
    assert res.status_code in (302, 303)
    _close_db()
    conn = db()
    row = conn.execute("SELECT email, email_verified FROM users WHERE username = ?;", (uname,)).fetchone()
    conn.close()
    assert row["email"] == email.lower()
    assert int(row["email_verified"]) == 0
    assert len(app_client._sent_mails) >= 1  # type: ignore[attr-defined]
    mail = app_client._sent_mails[0]  # type: ignore[attr-defined]
    assert mail.get("html") and "Genesis Colonies" in mail["html"]


def test_register_duplicate_email(app_client):
    email = f"dup_{uuid.uuid4().hex[:6]}@example.com"
    ok, err, _ = register_user_with_email(f"u1_{uuid.uuid4().hex[:4]}", "pass1234", email)
    assert ok, err
    _close_db()
    ok2, err2, _ = register_user_with_email(f"u2_{uuid.uuid4().hex[:4]}", "pass1234", email)
    assert not ok2
    assert err2 == "register_email_taken"


def test_verify_email_flow(app_client):
    email = f"verify_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"v_{uuid.uuid4().hex[:6]}"
    ok, _, user = register_user_with_email(uname, "pass1234", email)
    assert ok and user
    uid = int(user["id"])
    _close_db()
    conn = db()
    token = conn.execute(
        "SELECT email_verification_token FROM users WHERE id = ?;", (uid,)
    ).fetchone()["email_verification_token"]
    conn.close()
    assert token

    ok_v, err_v = verify_email_token(token)
    assert ok_v, err_v
    _close_db()
    conn = db()
    row = conn.execute("SELECT email_verified, email_verification_token FROM users WHERE id = ?;", (uid,)).fetchone()
    conn.close()
    assert int(row["email_verified"]) == 1
    assert row["email_verification_token"] is None

    ok_v2, _ = verify_email_token(token)
    assert not ok_v2


def test_password_reset_flow(app_client):
    email = f"reset_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"r_{uuid.uuid4().hex[:6]}"
    register_user_with_email(uname, "oldpass99", email)
    _close_db()

    request_password_reset(email)
    _close_db()
    conn = db()
    row = conn.execute(
        "SELECT password_reset_token, password_reset_expires_at FROM users WHERE username = ?;", (uname,)
    ).fetchone()
    conn.close()
    token = row["password_reset_token"]
    assert token

    ok, err = reset_password_with_token(token, "newpass88", "newpass88")
    assert ok, err
    _close_db()
    assert verify_user(uname, "newpass88")
    conn = db()
    row2 = conn.execute(
        "SELECT password_reset_token FROM users WHERE username = ?;", (uname,)
    ).fetchone()
    conn.close()
    assert row2["password_reset_token"] is None

    ok2, err2 = reset_password_with_token(token, "another1", "another1")
    assert not ok2
    assert err2 == "account_token_invalid"


def test_expired_reset_token(app_client):
    email = f"exp_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"e_{uuid.uuid4().hex[:6]}"
    register_user_with_email(uname, "oldpass99", email)
    _close_db()
    conn = db()
    conn.execute(
        """
        UPDATE users SET password_reset_token = ?, password_reset_expires_at = ?
        WHERE username = ?;
        """,
        ("expired-token-xyz", int(time.time()) - 10, uname),
    )
    conn.commit()
    conn.close()

    ok, err = reset_password_with_token("expired-token-xyz", "newpass88", "newpass88")
    assert not ok
    assert err == "account_token_expired"


def test_forgot_password_no_enumeration(app_client):
    res_known = app_client.post("/forgot-password", data={"email": "nobody@example.com"})
    assert res_known.status_code == 200
    body = res_known.get_data(as_text=True)
    assert "account_reset_generic" in body or "E-Mail" in body or "email" in body.lower()

    email = f"enum_{uuid.uuid4().hex[:6]}@example.com"
    register_user_with_email(f"x_{uuid.uuid4().hex[:4]}", "pass1234", email)
    _close_db()
    res2 = app_client.post("/forgot-password", data={"email": email})
    assert res2.status_code == 200


def test_send_mail_without_smtp_does_not_crash(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert send_mail("a@b.com", "subj", "body") is False


def test_resend_verification_cooldown(app_client):
    email = f"resend_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"rs_{uuid.uuid4().hex[:6]}"
    ok, _, user = register_user_with_email(uname, "pass1234", email)
    assert ok and user
    uid = int(user["id"])
    _close_db()

    ok1, err1 = resend_verification_email(uid)
    assert ok1, err1
    ok2, err2 = resend_verification_email(uid)
    assert not ok2
    assert err2 == "options_error_verify_resend_rate"


def test_verified_account_cannot_reuse_token(app_client):
    email = f"reuse_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"ru_{uuid.uuid4().hex[:6]}"
    ok, _, user = register_user_with_email(uname, "pass1234", email)
    assert ok and user
    uid = int(user["id"])
    _close_db()
    conn = db()
    token = conn.execute(
        "SELECT email_verification_token FROM users WHERE id = ?;", (uid,)
    ).fetchone()["email_verification_token"]
    conn.close()

    ok_v, _ = verify_email_token(token)
    assert ok_v
    ok_v2, err2 = verify_email_token(token)
    assert not ok_v2
    assert err2 == "account_token_invalid"


def test_resend_blocked_when_already_verified(app_client):
    email = f"ver_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"vr_{uuid.uuid4().hex[:6]}"
    ok, _, user = register_user_with_email(uname, "pass1234", email)
    uid = int(user["id"])
    _close_db()
    conn = db()
    token = conn.execute(
        "SELECT email_verification_token FROM users WHERE id = ?;", (uid,)
    ).fetchone()["email_verification_token"]
    conn.close()
    verify_email_token(token)
    _close_db()

    ok_r, err_r = resend_verification_email(uid)
    assert not ok_r
    assert err_r == "account_already_verified"


def test_resend_api_requires_login(app_client):
    res = app_client.post("/api/options/resend-verification", json={})
    assert res.status_code == 401


def test_verify_rejects_already_verified_with_stale_token(app_client):
    email = f"stale_{uuid.uuid4().hex[:6]}@example.com"
    uname = f"st_{uuid.uuid4().hex[:6]}"
    register_user_with_email(uname, "pass1234", email)
    _close_db()
    conn = db()
    row = conn.execute(
        "SELECT id, email_verification_token FROM users WHERE username = ?;", (uname,)
    ).fetchone()
    token = row["email_verification_token"]
    conn.execute(
        "UPDATE users SET email_verified = 1 WHERE id = ?;", (int(row["id"]),)
    )
    conn.commit()
    conn.close()

    ok, err = verify_email_token(token)
    assert not ok
    assert err == "account_already_verified"
    _close_db()
    conn = db()
    cleared = conn.execute(
        "SELECT email_verification_token FROM users WHERE username = ?;", (uname,)
    ).fetchone()["email_verification_token"]
    conn.close()
    assert cleared is None


def test_mail_template_has_html_cta(app_client):
    from game.mail_templates import build_genesis_mail

    text, html = build_genesis_mail(
        subject="Test",
        headline="Headline",
        lead="Lead text",
        cta_label="Click",
        cta_url="https://example.com/verify",
        footer_note="Footer",
    )
    assert "https://example.com/verify" in text
    assert "Click" in html
    assert "Genesis Colonies" in html

