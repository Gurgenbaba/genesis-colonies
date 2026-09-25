"""Client for the central Gurgenbaba Mail Hub.

The game never stores marketing consent locally. Consent state lives in the
Mail Hub and is queried on demand. All calls are fail-closed: a hub outage
must never break registration, login or gameplay.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 3.0


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def configured() -> bool:
    return bool(_env("MAIL_HUB_URL") and _env("MAIL_HUB_API_KEY"))


def _identity(user_id: int) -> str:
    universe = _env("GC_UNIVERSE_KEY", "uni1") or "uni1"
    return f"{universe}:{int(user_id)}"


def _post(path: str, payload: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    base = _env("MAIL_HUB_URL").rstrip("/")
    key = _env("MAIL_HUB_API_KEY")
    if not base or not key:
        return False, {"ok": False, "error": "mail_hub_unavailable"}

    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Genesis-Colonies-MailHub/1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
            raw = resp.read(128 * 1024)
            data = json.loads(raw.decode("utf-8")) if raw else {}
            return bool(data.get("ok")), data
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(32 * 1024)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            data = {}
        logger.warning("mail hub HTTP %s path=%s", exc.code, path)
        return False, {"ok": False, "error": data.get("detail") or f"http_{exc.code}"}
    except Exception as exc:
        logger.warning("mail hub unavailable path=%s error=%s", path, exc)
        return False, {"ok": False, "error": "mail_hub_unavailable"}


def status(user_id: int) -> Dict[str, Any]:
    if not configured():
        return {"ok": False, "status": "unavailable", "configured": False}
    ok, data = _post(
        "/api/v1/consents/status",
        {
            "project": "genesis",
            "external_user_id": _identity(user_id),
            "scope": "genesis_updates",
        },
    )
    return {
        "ok": ok,
        "status": str(data.get("status") or ("none" if ok else "unavailable")),
        "configured": True,
    }


def request_updates(
    user_id: int,
    email: str,
    *,
    locale: str = "de",
    email_verified: bool = False,
    source: str = "game",
) -> Tuple[bool, Dict[str, Any]]:
    return _post(
        "/api/v1/consents/request",
        {
            "project": "genesis",
            "external_user_id": _identity(user_id),
            "email": str(email or "").strip(),
            "locale": str(locale or "de")[:12],
            "email_verified": bool(email_verified),
            "scope": "genesis_updates",
            "source": str(source or "game")[:64],
        },
    )


def revoke_updates(user_id: int) -> Tuple[bool, Dict[str, Any]]:
    return _post(
        "/api/v1/consents/revoke",
        {
            "project": "genesis",
            "external_user_id": _identity(user_id),
            "scope": "genesis_updates",
        },
    )
