"""
GC-SEC-P0 — auth rate limits, HTML-form CSRF, response security headers.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Dict, Optional

from flask import Request, Response, session

CSRF_SESSION_KEY = "_csrf_token"

_LOGIN_BUCKETS: Dict[str, list] = {}
_REGISTER_BUCKETS: Dict[str, list] = {}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1.0, float(raw))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


LOGIN_RATE_WINDOW_SEC = _env_float("GC_AUTH_LOGIN_RATE_WINDOW_SEC", 900.0)
LOGIN_RATE_MAX = _env_int("GC_AUTH_LOGIN_RATE_MAX", 10)
REGISTER_RATE_WINDOW_SEC = _env_float("GC_AUTH_REGISTER_RATE_WINDOW_SEC", 3600.0)
REGISTER_RATE_MAX = _env_int("GC_AUTH_REGISTER_RATE_MAX", 5)


def reset_auth_rate_limits() -> None:
    """Test helper — clear in-process auth rate buckets."""
    _LOGIN_BUCKETS.clear()
    _REGISTER_BUCKETS.clear()


def client_ip(request: Request) -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return (forwarded or request.remote_addr or "unknown")[:64]


def _rate_ok(bucket: Dict[str, list], key: str, window: float, max_count: int) -> bool:
    now = time.time()
    entries = [t for t in bucket.get(key, []) if t > now - window]
    if len(entries) >= max_count:
        bucket[key] = entries
        return False
    entries.append(now)
    bucket[key] = entries
    return True


def check_login_rate_limit(ip: str) -> bool:
    """Return True when the login attempt is allowed."""
    return _rate_ok(_LOGIN_BUCKETS, ip, LOGIN_RATE_WINDOW_SEC, LOGIN_RATE_MAX)


def check_register_rate_limit(ip: str) -> bool:
    """Return True when the register attempt is allowed."""
    return _rate_ok(_REGISTER_BUCKETS, ip, REGISTER_RATE_WINDOW_SEC, REGISTER_RATE_MAX)


def generate_csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return str(token)


def validate_csrf_request(request: Request, *, testing: bool = False) -> bool:
    if testing:
        return True
    token = (request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or "").strip()
    expected = str(session.get(CSRF_SESSION_KEY) or "")
    if not expected or not token:
        return False
    return secrets.compare_digest(expected, token)


def apply_security_headers(response: Response, *, secure: bool) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if secure:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


def session_cookie_secure_override() -> Optional[bool]:
    """None = use production default; True/False = explicit override."""
    raw = os.environ.get("GC_SESSION_COOKIE_SECURE", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None
