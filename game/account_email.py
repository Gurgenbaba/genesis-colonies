"""
Email verification and password reset flows.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from .db import begin_write_transaction, column_exists, commit, db, rollback
from .mail import send_mail
from .models import hash_password, verify_password
from .options import ensure_account_options_schema, validate_email, validate_new_password

logger = logging.getLogger(__name__)

TOKEN_TTL_SEC = 3600
RATE_WINDOW_SEC = 60.0
RATE_MAX = 5

_VERIFY_BUCKETS: Dict[str, list] = {}
_RESET_BUCKETS: Dict[str, list] = {}
_RESEND_LAST: Dict[int, float] = {}

RESEND_COOLDOWN_SEC = 60.0


def reset_account_email_rate_limits() -> None:
    _VERIFY_BUCKETS.clear()
    _RESET_BUCKETS.clear()
    _RESEND_LAST.clear()


def _now_ts() -> int:
    return int(time.time())


def _rate_ok(bucket: Dict[str, list], key: str) -> bool:
    now = time.time()
    entries = [t for t in bucket.get(key, []) if t > now - RATE_WINDOW_SEC]
    if len(entries) >= RATE_MAX:
        bucket[key] = entries
        return False
    entries.append(now)
    bucket[key] = entries
    return True


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_user_email_auth_schema(conn=None) -> None:
    own = conn is None
    c = conn or db()
    cur = c.cursor()
    try:
        ensure_account_options_schema(c)
        cols = {row[1] for row in cur.execute("PRAGMA table_info(users);").fetchall()}
        additions = {
            "email_verified": "INTEGER NOT NULL DEFAULT 0",
            "email_verification_token": "TEXT",
            "password_reset_token": "TEXT",
            "password_reset_expires_at": "INTEGER",
        }
        for col, typedef in additions.items():
            if col not in cols:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef};")
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_email_verify_token
                ON users (email_verification_token)
                WHERE email_verification_token IS NOT NULL;
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_users_password_reset_token
                ON users (password_reset_token)
                WHERE password_reset_token IS NOT NULL;
            """
        )
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def get_user_by_email(email: str, conn=None):
    own = conn is None
    c = conn or db()
    try:
        if not column_exists(c, "users", "email"):
            return None
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM users WHERE LOWER(email) = LOWER(?) LIMIT 1;",
            (str(email or "").strip(),),
        )
        return cur.fetchone()
    finally:
        if own:
            c.close()


def _resend_rate_ok(user_id: int) -> bool:
    now = time.time()
    pid = int(user_id)
    last = float(_RESEND_LAST.get(pid, 0) or 0)
    if last and (now - last) < RESEND_COOLDOWN_SEC:
        return False
    _RESEND_LAST[pid] = now
    return True


def _send_verification_mail(email: str, url: str) -> None:
    from .mail_templates import build_genesis_mail

    text, html = build_genesis_mail(
        subject="Genesis Colonies – E-Mail bestätigen",
        headline="Kommando-Frequenz bestätigen",
        lead="Bestätige deine E-Mail-Adresse, um deinen Commander-Account im Genesis-Cluster zu aktivieren.",
        cta_label="E-Mail verifizieren",
        cta_url=url,
        footer_note="Link gültig für 1 Stunde. Wenn du das nicht warst, ignoriere diese Nachricht.",
    )
    send_mail(email, "Genesis Colonies – E-Mail bestätigen", text, html=html)


def _send_reset_mail(email: str, url: str) -> None:
    from .mail_templates import build_genesis_mail

    text, html = build_genesis_mail(
        subject="Genesis Colonies – Passwort zurücksetzen",
        headline="Zugangsprotokoll zurücksetzen",
        lead="Du hast ein neues Passwort für deinen Commander-Account angefordert.",
        cta_label="Passwort setzen",
        cta_url=url,
        footer_note="Link gültig für 1 Stunde. Wenn du das nicht warst, ändere dein Passwort in den Optionen.",
    )
    send_mail(email, "Genesis Colonies – Passwort zurücksetzen", text, html=html)


def _public_base_url() -> str:
    import os

    return (os.environ.get("PUBLIC_BASE_URL") or os.environ.get("GC_PUBLIC_URL") or "http://127.0.0.1:5000").rstrip("/")


def issue_email_verification(user_id: int, *, send: bool = True) -> Tuple[bool, str]:
    """Create verification token and optionally send mail."""
    conn = db()
    try:
        ensure_user_email_auth_schema(conn)
        cur = conn.cursor()
        cur.execute("SELECT id, email, email_verified FROM users WHERE id = ?;", (int(user_id),))
        row = cur.fetchone()
        if not row or not row["email"]:
            return False, "account_email_missing"
        if int(row["email_verified"] or 0) == 1:
            return False, "account_already_verified"

        token = _new_token()
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE users
            SET email_verification_token = ?, email_verified = 0
            WHERE id = ? AND COALESCE(email_verified, 0) = 0;
            """,
            (token, int(user_id)),
        )
        commit(conn)

        if send:
            url = f"{_public_base_url()}/verify-email/{token}"
            _send_verification_mail(str(row["email"]), url)
        return True, "account_email_verify_sent"
    except Exception as exc:
        rollback(conn)
        logger.warning("issue_email_verification failed: %s", exc)
        return False, "account_email_verify_failed"
    finally:
        conn.close()


def resend_verification_email(user_id: int) -> Tuple[bool, str]:
    """Resend verify mail – max once per RESEND_COOLDOWN_SEC per user."""
    if not _resend_rate_ok(int(user_id)):
        return False, "options_error_verify_resend_rate"

    conn = db()
    try:
        ensure_user_email_auth_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, email_verified FROM users WHERE id = ?;",
            (int(user_id),),
        )
        row = cur.fetchone()
        if not row or not row["email"]:
            return False, "account_email_missing"
        if int(row["email_verified"] or 0) == 1:
            return False, "account_already_verified"
    finally:
        conn.close()

    return issue_email_verification(int(user_id), send=True)


def verify_email_token(token: str) -> Tuple[bool, str]:
    tok = str(token or "").strip()
    if not tok or len(tok) < 16:
        return False, "account_token_invalid"

    conn = db()
    try:
        ensure_user_email_auth_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, email_verification_token, email_verified
            FROM users WHERE email_verification_token = ? LIMIT 1;
            """,
            (tok,),
        )
        row = cur.fetchone()
        if not row:
            return False, "account_token_invalid"

        if int(row["email_verified"] or 0) == 1:
            conn.execute(
                "UPDATE users SET email_verification_token = NULL WHERE id = ?;",
                (int(row["id"]),),
            )
            conn.commit()
            return False, "account_already_verified"

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE users
            SET email_verified = 1, email_verification_token = NULL
            WHERE id = ?;
            """,
            (int(row["id"]),),
        )
        commit(conn)
        return True, "account_email_verified"
    except Exception:
        rollback(conn)
        return False, "account_token_invalid"
    finally:
        conn.close()


def request_password_reset(email: str, *, ip: Optional[str] = None) -> Tuple[bool, str]:
    """
    Always returns success message key (no user enumeration).
    Sends mail only when account exists.
    """
    rate_key = str(ip or email or "global")
    if not _rate_ok(_RESET_BUCKETS, rate_key):
        return True, "account_reset_generic"

    ok, err, normalized = validate_email(email)
    if not ok:
        return True, "account_reset_generic"

    conn = db()
    try:
        ensure_user_email_auth_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email FROM users WHERE LOWER(email) = LOWER(?) LIMIT 1;",
            (normalized,),
        )
        row = cur.fetchone()
        if not row:
            return True, "account_reset_generic"

        token = _new_token()
        expires = _now_ts() + TOKEN_TTL_SEC
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE users
            SET password_reset_token = ?, password_reset_expires_at = ?
            WHERE id = ?;
            """,
            (token, expires, int(row["id"])),
        )
        commit(conn)

        url = f"{_public_base_url()}/reset-password/{token}"
        _send_reset_mail(str(row["email"]), url)
        return True, "account_reset_generic"
    except Exception as exc:
        rollback(conn)
        logger.warning("request_password_reset failed: %s", exc)
        return True, "account_reset_generic"
    finally:
        conn.close()


def reset_password_with_token(
    token: str,
    new_password: str,
    confirm_password: str,
) -> Tuple[bool, str]:
    tok = str(token or "").strip()
    ok, err = validate_new_password(new_password, confirm_password)
    if not ok:
        return False, err

    conn = db()
    try:
        ensure_user_email_auth_schema(conn)
        now = _now_ts()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, password_reset_token, password_reset_expires_at
            FROM users WHERE password_reset_token = ? LIMIT 1;
            """,
            (tok,),
        )
        row = cur.fetchone()
        if not row:
            return False, "account_token_invalid"

        expires = int(row["password_reset_expires_at"] or 0)
        if expires <= now:
            conn.execute(
                "UPDATE users SET password_reset_token = NULL, password_reset_expires_at = NULL WHERE id = ?;",
                (int(row["id"]),),
            )
            conn.commit()
            return False, "account_token_expired"

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?,
                password_reset_token = NULL,
                password_reset_expires_at = NULL
            WHERE id = ?;
            """,
            (hash_password(new_password), int(row["id"])),
        )
        commit(conn)
        return True, "account_password_reset_ok"
    except Exception:
        rollback(conn)
        return False, "account_token_invalid"
    finally:
        conn.close()


def register_user_with_email(
    username: str,
    password: str,
    email: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    from .models import create_user, get_user_by_username

    uname = str(username or "").strip()
    if get_user_by_username(uname):
        return False, "msg_register_username_taken", None

    ok, err, normalized = validate_email(email)
    if not ok:
        return False, "register_email_invalid", None

    conn = db()
    try:
        ensure_user_email_auth_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM users WHERE LOWER(email) = LOWER(?) LIMIT 1;",
            (normalized,),
        )
        if cur.fetchone():
            return False, "register_email_taken", None
    finally:
        conn.close()

    ok, msg, user = create_user(uname, password, email=normalized)
    if not ok or not user:
        return False, msg or "msg_register_failed", None

    uid = int(user["id"])
    issue_email_verification(uid, send=True)
    return True, "msg_register_success", user
