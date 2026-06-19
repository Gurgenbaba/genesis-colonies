"""
Discord OAuth2 login/register (GC-733A).

Authorization Code Flow with scopes: identify, email.
No bot token or guild join in this phase.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from .db import begin_write_transaction, commit, db, rollback
from .models import ensure_player_and_homeworld, get_user_by_username, hash_password, verify_user

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api"
DISCORD_AUTHORIZE_URL = f"{DISCORD_API_BASE}/oauth2/authorize"
DISCORD_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"
DISCORD_USER_URL = f"{DISCORD_API_BASE}/users/@me"
DISCORD_SCOPES = "identify email"

SESSION_STATE_KEY = "discord_oauth_state"
SESSION_LINK_MODE_KEY = "discord_oauth_link"


def discord_oauth_configured() -> bool:
    return bool(_client_id() and _client_secret() and _redirect_uri())


def _env_value(name: str) -> str:
    """Read env var; strip whitespace and optional surrounding quotes (Railway copy-paste)."""
    val = str(os.environ.get(name) or "").strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        val = val[1:-1].strip()
    return val


def _client_id() -> str:
    return _env_value("DISCORD_CLIENT_ID")


def _client_secret() -> str:
    return _env_value("DISCORD_CLIENT_SECRET")


def _redirect_uri() -> str:
    explicit = _env_value("DISCORD_REDIRECT_URI")
    if explicit:
        return explicit.rstrip("/")
    base = _env_value("PUBLIC_BASE_URL") or _env_value("GC_PUBLIC_URL")
    base = base.rstrip("/")
    if base:
        return f"{base}/auth/discord/callback"
    return ""


def discord_invite_url() -> str:
    return str(
        os.environ.get("DISCORD_INVITE_URL") or "https://discord.gg/CYP8qWE7VM"
    ).strip()


def generate_oauth_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": DISCORD_SCOPES,
        "state": state,
    }
    return f"{DISCORD_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def _http_post_form(url: str, data: Dict[str, str], headers: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return int(resp.status), resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), raw


def _http_get_json(url: str, access_token: str) -> Tuple[int, Optional[Dict[str, Any]]]:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return int(resp.status), payload if isinstance(payload, dict) else None
    except urllib.error.HTTPError as exc:
        logger.warning("discord userinfo failed status=%s", exc.code)
        return int(exc.code), None
    except (json.JSONDecodeError, OSError, TimeoutError) as exc:
        logger.warning("discord userinfo error: %s", exc)
        return 0, None


def _map_discord_token_error(status: int, raw: str) -> str:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    err = str(payload.get("error") or "").strip().lower()
    desc = str(payload.get("error_description") or "").strip().lower()

    if err == "invalid_client" or status == 401:
        return "discord_token_invalid_client"
    if err == "invalid_grant":
        if "redirect_uri" in desc:
            return "discord_token_redirect_mismatch"
        if "code" in desc:
            return "discord_token_code_invalid"
        return "discord_token_invalid_grant"
    return "discord_token_failed"


def exchange_code_for_token(code: str) -> Tuple[bool, Optional[str], str]:
    redirect_uri = _redirect_uri()
    status, raw = _http_post_form(
        DISCORD_TOKEN_URL,
        {
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "grant_type": "authorization_code",
            "code": str(code or "").strip(),
            "redirect_uri": redirect_uri,
        },
    )
    if status != 200:
        err_key = _map_discord_token_error(status, raw)
        logger.warning(
            "discord token exchange failed status=%s key=%s redirect_uri=%s client_id=%s body=%s",
            status,
            err_key,
            redirect_uri,
            _client_id(),
            raw[:400],
        )
        return False, None, err_key

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False, None, "discord_token_failed"

    token = str(payload.get("access_token") or "").strip()
    if not token:
        return False, None, "discord_token_failed"
    return True, token, ""


def fetch_discord_user(access_token: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    status, profile = _http_get_json(DISCORD_USER_URL, access_token)
    if status != 200 or not profile:
        return False, None, "discord_profile_failed"

    discord_id = str(profile.get("id") or "").strip()
    if not discord_id:
        return False, None, "discord_profile_failed"
    return True, profile, ""


def get_user_by_discord_id(discord_id: str, conn=None):
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute(
            "SELECT * FROM users WHERE discord_id = ? LIMIT 1;",
            (str(discord_id or "").strip(),),
        )
        return cur.fetchone()
    finally:
        if own:
            c.close()


def get_user_discord_row(user_id: int, conn=None) -> Optional[Dict[str, Any]]:
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute(
            """
            SELECT discord_id, discord_username, discord_avatar, discord_email
            FROM users
            WHERE id = ?
            LIMIT 1;
            """,
            (int(user_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def discord_display_name(row: Optional[Dict[str, Any]]) -> Optional[str]:
    if not row:
        return None
    name = str(row.get("discord_username") or "").strip()
    return name or None


def discord_avatar_url(discord_id: Any, avatar_hash: Any, *, size: int = 64) -> Optional[str]:
    did = str(discord_id or "").strip()
    avatar = str(avatar_hash or "").strip()
    if not did or not avatar:
        return None
    return f"https://cdn.discordapp.com/avatars/{did}/{avatar}.png?size={int(size)}"


def start_oauth_session(session: Any, *, link: bool = False) -> str:
    """Store OAuth state (and optional link mode) in Flask session."""
    state = generate_oauth_state()
    session[SESSION_STATE_KEY] = state
    if link:
        session[SESSION_LINK_MODE_KEY] = "1"
    else:
        session.pop(SESSION_LINK_MODE_KEY, None)
    return state


def consume_oauth_session(session: Any, received_state: str) -> Tuple[bool, bool]:
    """Validate OAuth state. Returns (valid, is_link_flow)."""
    expected = str(session.pop(SESSION_STATE_KEY, "") or "")
    is_link = str(session.pop(SESSION_LINK_MODE_KEY, "") or "") == "1"
    received = str(received_state or "")
    valid = bool(expected and received and expected == received)
    return valid, is_link


def get_user_auth_row(user_id: int, conn=None) -> Optional[Dict[str, Any]]:
    own = conn is None
    c = conn or db()
    try:
        cur = c.cursor()
        cur.execute(
            """
            SELECT
                id,
                username,
                email,
                password_hash,
                discord_id,
                discord_username,
                discord_avatar,
                discord_email
            FROM users
            WHERE id = ?
            LIMIT 1;
            """,
            (int(user_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            c.close()


def discord_link_snapshot(user_id: int, conn=None) -> Dict[str, Any]:
    row = get_user_auth_row(user_id, conn=conn) or {}
    discord_id = str(row.get("discord_id") or "").strip()
    email = str(row.get("email") or "").strip()
    linked = bool(discord_id)
    return {
        "discord_linked": linked,
        "discord_id": discord_id or None,
        "discord_username": str(row.get("discord_username") or "").strip() or None,
        "discord_avatar": str(row.get("discord_avatar") or "").strip() or None,
        "discord_email": str(row.get("discord_email") or "").strip() or None,
        "discord_avatar_url": discord_avatar_url(discord_id, row.get("discord_avatar")),
        "discord_can_unlink": linked and bool(email),
        "discord_unlink_requires_password": linked and not bool(email),
    }


def user_can_unlink_discord(
    user_id: int,
    *,
    current_password: Optional[str] = None,
    conn=None,
) -> Tuple[bool, str]:
    row = get_user_auth_row(user_id, conn=conn)
    if not row:
        return False, "not_logged_in"
    if not str(row.get("discord_id") or "").strip():
        return False, "discord_not_linked"
    email = str(row.get("email") or "").strip()
    if email:
        return True, ""
    password = str(current_password or "")
    if password and verify_user(str(row.get("username") or ""), password):
        return True, ""
    return False, "discord_unlink_no_fallback"


def _sanitize_username(raw: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "", str(raw or "").replace(" ", "_"))
    base = base.strip("_")[:40]
    if len(base) >= 3:
        return base
    fallback = re.sub(r"\D", "", base) or "cmd"
    candidate = f"Discord{fallback}"[:40]
    return candidate if len(candidate) >= 3 else "DiscordUser"


def _derive_username(profile: Dict[str, Any]) -> str:
    for key in ("global_name", "username"):
        val = str(profile.get(key) or "").strip()
        if val:
            return _sanitize_username(val)
    return _sanitize_username(str(profile.get("id") or "DiscordUser"))


def _pick_unique_username(base: str) -> str:
    candidate = _sanitize_username(base)
    if not get_user_by_username(candidate):
        return candidate
    for _ in range(12):
        suffix = secrets.randbelow(9000) + 1000
        alt = _sanitize_username(f"{candidate[:32]}{suffix}")
        if len(alt) >= 3 and not get_user_by_username(alt):
            return alt
    return _sanitize_username(f"{candidate}{secrets.token_hex(3)}")


def _email_taken(email: str, conn) -> bool:
    normalized = str(email or "").strip().lower()
    if not normalized:
        return False
    row = conn.execute(
        "SELECT 1 FROM users WHERE LOWER(email) = LOWER(?) LIMIT 1;",
        (normalized,),
    ).fetchone()
    return row is not None


def create_user_from_discord(profile: Dict[str, Any], conn=None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Create a Genesis account for a new Discord identity.
    Does not merge by email — discord_email is stored separately.
    """
    discord_id = str(profile.get("id") or "").strip()
    if not discord_id:
        return False, "discord_profile_failed", None

    discord_username = str(profile.get("username") or "").strip() or None
    discord_avatar = str(profile.get("avatar") or "").strip() or None
    discord_email = str(profile.get("email") or "").strip().lower() or None

    username = _pick_unique_username(_derive_username(profile))
    random_password = secrets.token_urlsafe(32)

    own = conn is None
    c = conn or db()
    try:
        begin_write_transaction(c)
        account_email = None
        if discord_email and not _email_taken(discord_email, c):
            account_email = discord_email

        cur = c.cursor()
        cur.execute(
            """
            INSERT INTO users (
                username,
                password_hash,
                is_admin,
                email,
                email_verified,
                discord_id,
                discord_username,
                discord_avatar,
                discord_email
            )
            VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?);
            """,
            (
                username,
                hash_password(random_password),
                account_email,
                1 if account_email else 0,
                discord_id,
                discord_username,
                discord_avatar,
                discord_email,
            ),
        )
        user_id = int(cur.lastrowid)

        ensure_player_and_homeworld(
            player_id=user_id,
            player_name=username,
            conn=c,
        )

        from .ranking import ensure_player_score_row

        ensure_player_score_row(user_id, conn=c)
        if own:
            commit(c)
        return True, "", {"id": user_id, "username": username, "is_admin": False}
    except Exception as exc:
        if own:
            rollback(c)
        logger.exception("create_user_from_discord failed: %s", exc)
        if "idx_users_discord_id" in str(exc).lower() or "UNIQUE constraint failed" in str(exc):
            return False, "discord_id_taken", None
        return False, "discord_register_failed", None
    finally:
        if own:
            c.close()


def resolve_discord_login(profile: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Existing discord_id -> login; otherwise create new account.
    """
    discord_id = str(profile.get("id") or "").strip()
    if not discord_id:
        return False, "discord_profile_failed", None

    existing = get_user_by_discord_id(discord_id)
    if existing:
        return True, "discord_login_ok", dict(existing)

    ok, err, user = create_user_from_discord(profile)
    if ok and user:
        return True, "discord_register_ok", user
    return False, err or "discord_register_failed", None


def update_discord_profile(user_id: int, profile: Dict[str, Any], conn=None) -> None:
    """Refresh stored Discord metadata on login."""
    discord_username = str(profile.get("username") or "").strip() or None
    discord_avatar = str(profile.get("avatar") or "").strip() or None
    discord_email = str(profile.get("email") or "").strip().lower() or None
    own = conn is None
    c = conn or db()
    try:
        c.execute(
            """
            UPDATE users
            SET discord_username = ?,
                discord_avatar = ?,
                discord_email = ?
            WHERE id = ?;
            """,
            (discord_username, discord_avatar, discord_email, int(user_id)),
        )
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def complete_discord_callback(code: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    ok, token, err = exchange_code_for_token(code)
    if not ok or not token:
        return False, err or "discord_token_failed", None

    ok, profile, err = fetch_discord_user(token)
    if not ok or not profile:
        return False, err or "discord_profile_failed", None

    ok, err, user = resolve_discord_login(profile)
    if not ok or not user:
        return False, err or "discord_register_failed", None

    try:
        update_discord_profile(int(user["id"]), profile)
    except Exception:
        logger.exception("discord profile refresh failed user_id=%s", user.get("id"))

    return True, err, user


def complete_discord_link(code: str, user_id: int) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    ok, token, err = exchange_code_for_token(code)
    if not ok or not token:
        return False, err or "discord_token_failed", None

    ok, profile, err = fetch_discord_user(token)
    if not ok or not profile:
        return False, err or "discord_profile_failed", None

    return link_discord_to_user(int(user_id), profile)


def link_discord_to_user(user_id: int, profile: Dict[str, Any]) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    discord_id = str(profile.get("id") or "").strip()
    if not discord_id:
        return False, "discord_profile_failed", None

    discord_username = str(profile.get("username") or "").strip() or None
    discord_avatar = str(profile.get("avatar") or "").strip() or None
    discord_email = str(profile.get("email") or "").strip().lower() or None

    current = get_user_auth_row(user_id)
    if not current:
        return False, "not_logged_in", None

    existing_discord_id = str(current.get("discord_id") or "").strip()
    if existing_discord_id:
        if existing_discord_id == discord_id:
            try:
                update_discord_profile(user_id, profile)
            except Exception:
                logger.exception("discord profile refresh failed user_id=%s", user_id)
            snap = discord_link_snapshot(user_id)
            return True, "discord_already_linked", snap
        return False, "discord_already_linked", None

    owner = get_user_by_discord_id(discord_id)
    if owner and int(owner["id"]) != int(user_id):
        return False, "discord_id_taken", None

    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE users
            SET discord_id = ?,
                discord_username = ?,
                discord_avatar = ?,
                discord_email = ?
            WHERE id = ?;
            """,
            (discord_id, discord_username, discord_avatar, discord_email, int(user_id)),
        )
        commit(conn)
        return True, "discord_link_ok", discord_link_snapshot(user_id, conn=conn)
    except Exception as exc:
        rollback(conn)
        logger.exception("link_discord_to_user failed user_id=%s: %s", user_id, exc)
        if "UNIQUE constraint failed" in str(exc) or "idx_users_discord_id" in str(exc).lower():
            return False, "discord_id_taken", None
        return False, "discord_link_failed", None
    finally:
        conn.close()


def unlink_discord_from_user(
    user_id: int,
    *,
    current_password: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    conn = db()
    try:
        ok, err = user_can_unlink_discord(user_id, current_password=current_password, conn=conn)
        if not ok:
            return False, err, None

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE users
            SET discord_id = NULL,
                discord_username = NULL,
                discord_avatar = NULL,
                discord_email = NULL
            WHERE id = ?;
            """,
            (int(user_id),),
        )
        commit(conn)
        return True, "discord_unlink_ok", discord_link_snapshot(user_id, conn=conn)
    except Exception:
        rollback(conn)
        logger.exception("unlink_discord_from_user failed user_id=%s", user_id)
        return False, "discord_unlink_failed", None
    finally:
        conn.close()
