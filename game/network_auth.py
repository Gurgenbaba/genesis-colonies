"""Genesis Network account handoff between isolated universe databases.

DEV is the identity authority. Other universes keep their own users/players rows
for compatibility, but local credentials are never used for interactive login.
A signed, short-lived one-time handoff maps the authority account to one local
commander row per universe.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from flask import Response, jsonify, redirect, request, session, url_for

from .db import begin_write_transaction, commit, db, is_integrity_error, rollback, table_exists
from .models import create_user, get_homeworld

AUTHORITY_KEY_DEFAULT = "dev"
HANDOFF_TTL_SECONDS = 90
MAX_CLOCK_SKEW_SECONDS = 30
NETWORK_LINK_TABLE = "network_account_links"
NETWORK_NONCE_TABLE = "network_auth_nonces"


def _env(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def current_universe_key() -> str:
    return (_env("GC_UNIVERSE_KEY", AUTHORITY_KEY_DEFAULT) or AUTHORITY_KEY_DEFAULT).lower()


def authority_key() -> str:
    return (_env("GC_NETWORK_AUTHORITY_KEY", AUTHORITY_KEY_DEFAULT) or AUTHORITY_KEY_DEFAULT).lower()


def authority_url() -> str:
    return (_env("GC_NETWORK_AUTHORITY_URL", "https://www.genesis-colonies.de")).rstrip("/")


def universe_url(key: str) -> str:
    k = str(key or "").strip().lower()
    if k == authority_key():
        return authority_url()
    if k == "uni1":
        return (_env(
            "GC_NETWORK_UNI1_URL",
            "https://genesis-colonies-u2-production.up.railway.app",
        )).rstrip("/")
    return ""


def universe_is_open(key: str) -> bool:
    k = str(key or "").strip().lower()
    if k == authority_key():
        return True
    raw = _env(f"GC_NETWORK_{k.upper()}_OPEN", "0").lower()
    return raw in {"1", "true", "yes", "on"}


def network_enabled() -> bool:
    secret = _env("GC_NETWORK_AUTH_SECRET")
    return len(secret) >= 32


def is_authority() -> bool:
    return current_universe_key() == authority_key()


def schema_ready(conn) -> bool:
    return table_exists(conn, NETWORK_LINK_TABLE) and table_exists(conn, NETWORK_NONCE_TABLE)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    text = str(raw or "")
    padding = "=" * ((4 - (len(text) % 4)) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("ascii"))


def _sign_payload(payload: dict[str, Any]) -> str:
    secret = _env("GC_NETWORK_AUTH_SECRET").encode("utf-8")
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = _b64encode(body)
    sig = hmac.new(secret, body_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64encode(sig)}"


def _decode_token(token: str, *, expected_audience: str) -> tuple[bool, str, dict[str, Any] | None]:
    if not network_enabled():
        return False, "network_auth_disabled", None
    try:
        body_b64, sig_b64 = str(token or "").split(".", 1)
        expected_sig = hmac.new(
            _env("GC_NETWORK_AUTH_SECRET").encode("utf-8"),
            body_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        supplied_sig = _b64decode(sig_b64)
        if not hmac.compare_digest(expected_sig, supplied_sig):
            return False, "invalid_signature", None
        payload = json.loads(_b64decode(body_b64).decode("utf-8"))
    except Exception:
        return False, "invalid_token", None

    now = int(time.time())
    try:
        issued = int(payload.get("iat") or 0)
        expires = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return False, "invalid_time", None

    if issued > now + MAX_CLOCK_SKEW_SECONDS:
        return False, "issued_in_future", None
    if expires < now or expires - issued > HANDOFF_TTL_SECONDS + MAX_CLOCK_SKEW_SECONDS:
        return False, "expired", None
    if str(payload.get("iss") or "").lower() != authority_key():
        return False, "invalid_issuer", None
    if str(payload.get("aud") or "").lower() != str(expected_audience or "").lower():
        return False, "invalid_audience", None
    if not str(payload.get("sub") or "").strip() or not str(payload.get("nonce") or "").strip():
        return False, "invalid_subject", None
    if not str(payload.get("username") or "").strip():
        return False, "invalid_username", None
    return True, "ok", payload


def issue_handoff(player_id: int, target_key: str) -> tuple[bool, str, str | None]:
    target = str(target_key or "").strip().lower()
    if not network_enabled():
        return False, "network_auth_disabled", None
    if not is_authority():
        return False, "not_authority", None
    if target == current_universe_key() or not universe_url(target):
        return False, "invalid_target", None
    if not universe_is_open(target):
        return False, "universe_closed", None

    now = int(time.time())
    conn = db()
    try:
        if not schema_ready(conn):
            return False, "network_schema_missing", None
        begin_write_transaction(conn)
        row = conn.execute(
            "SELECT id, username FROM users WHERE id = ? LIMIT 1;",
            (int(player_id),),
        ).fetchone()
        if not row:
            rollback(conn)
            return False, "account_missing", None
        user = dict(row)

        link = conn.execute(
            f"""
            SELECT network_account_id
              FROM {NETWORK_LINK_TABLE}
             WHERE local_user_id = ?
             LIMIT 1;
            """,
            (int(player_id),),
        ).fetchone()
        if link:
            network_account_id = str(
                link["network_account_id"] if isinstance(link, dict) else link[0]
            )
            conn.execute(
                f"""
                UPDATE {NETWORK_LINK_TABLE}
                   SET last_login_at = ?
                 WHERE local_user_id = ?;
                """,
                (now, int(player_id)),
            )
        else:
            network_account_id = f"acct_{secrets.token_urlsafe(24)}"
            conn.execute(
                f"""
                INSERT INTO {NETWORK_LINK_TABLE}
                    (local_user_id, network_account_id, authority_key, created_at, last_login_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (int(player_id), network_account_id, authority_key(), now, now),
            )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    payload = {
        "v": 1,
        "iss": authority_key(),
        "aud": target,
        "sub": network_account_id,
        "username": str(user.get("username") or "").strip(),
        "iat": now,
        "exp": now + HANDOFF_TTL_SECONDS,
        "nonce": secrets.token_urlsafe(24),
    }
    return True, "ok", _sign_payload(payload)


def _purge_old_nonces(conn, now: int) -> None:
    conn.execute(
        f"DELETE FROM {NETWORK_NONCE_TABLE} WHERE expires_at < ?;",
        (int(now) - 300,),
    )


def _starter_resource_multiplier() -> int:
    try:
        return max(1, min(1000, int(_env("GC_NETWORK_START_RESOURCE_MULTIPLIER", "1"))))
    except ValueError:
        return 1


def _starter_timekeeper_seconds() -> int:
    try:
        return max(0, min(365 * 24 * 3600, int(_env("GC_NETWORK_START_TIMEKEEPER_SECONDS", "0"))))
    except ValueError:
        return 0


def _grant_first_entry_bundle(local_user_id: int, *, conn) -> None:
    multiplier = _starter_resource_multiplier()
    homeworld = get_homeworld(int(local_user_id), conn=conn)
    if homeworld and multiplier != 1:
        conn.execute(
            """
            UPDATE planets
               SET metal = metal * ?,
                   crystal = crystal * ?,
                   fuel_cells = fuel_cells * ?
             WHERE id = ? AND player_id = ?;
            """,
            (
                multiplier,
                multiplier,
                multiplier,
                int(homeworld["id"]),
                int(local_user_id),
            ),
        )

    seconds = _starter_timekeeper_seconds()
    if seconds > 0:
        from .timekeeper import credit, schema_ready as timekeeper_schema_ready

        if timekeeper_schema_ready(conn):
            credit(
                int(local_user_id),
                int(seconds),
                "network_universe_starter",
                conn=conn,
            )


def consume_handoff(token: str) -> tuple[bool, str, dict[str, Any] | None]:
    universe = current_universe_key()
    if universe == authority_key():
        return False, "authority_cannot_consume", None

    ok, reason, payload = _decode_token(token, expected_audience=universe)
    if not ok or payload is None:
        return False, reason, None

    network_account_id = str(payload["sub"])
    username = str(payload["username"]).strip()
    nonce = str(payload["nonce"])
    now = int(time.time())

    conn = db()
    try:
        if not schema_ready(conn):
            return False, "network_schema_missing", None

        row = conn.execute(
            f"""
            SELECT l.local_user_id, u.username
              FROM {NETWORK_LINK_TABLE} l
              JOIN users u ON u.id = l.local_user_id
             WHERE l.network_account_id = ?
             LIMIT 1;
            """,
            (network_account_id,),
        ).fetchone()
        local_user = dict(row) if row else None
    finally:
        conn.close()

    created = False
    if local_user is None:
        conn = db()
        try:
            collision = conn.execute(
                "SELECT id FROM users WHERE username = ? LIMIT 1;",
                (username,),
            ).fetchone()
        finally:
            conn.close()
        if collision:
            return False, "username_conflict", None

        shadow_password = secrets.token_urlsafe(48)
        created_ok, create_reason, created_user = create_user(username, shadow_password)
        if not created_ok or not created_user:
            return False, create_reason or "local_account_create_failed", None
        local_user = {"local_user_id": int(created_user["id"]), "username": username}
        created = True

    local_user_id = int(local_user["local_user_id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        _purge_old_nonces(conn, now)
        try:
            conn.execute(
                f"""
                INSERT INTO {NETWORK_NONCE_TABLE} (nonce, expires_at, consumed_at)
                VALUES (?, ?, ?);
                """,
                (nonce, int(payload["exp"]), now),
            )
        except Exception as exc:
            if is_integrity_error(exc):
                rollback(conn)
                return False, "replayed", None
            raise

        existing = conn.execute(
            f"""
            SELECT local_user_id FROM {NETWORK_LINK_TABLE}
             WHERE network_account_id = ?
             LIMIT 1;
            """,
            (network_account_id,),
        ).fetchone()
        if existing:
            linked_id = int(existing["local_user_id"] if isinstance(existing, dict) else existing[0])
            if linked_id != local_user_id:
                rollback(conn)
                return False, "link_conflict", None
            conn.execute(
                f"""
                UPDATE {NETWORK_LINK_TABLE}
                   SET last_login_at = ?
                 WHERE network_account_id = ?;
                """,
                (now, network_account_id),
            )
            created = False
        else:
            conn.execute(
                f"""
                INSERT INTO {NETWORK_LINK_TABLE}
                    (local_user_id, network_account_id, authority_key, created_at, last_login_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (local_user_id, network_account_id, authority_key(), now, now),
            )
            if created:
                _grant_first_entry_bundle(local_user_id, conn=conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return True, "created" if created else "linked", {
        "id": local_user_id,
        "username": username,
        "network_account_id": network_account_id,
        "created": created,
    }


def _authority_auth_url(endpoint: str, target: str) -> str:
    path = "/register" if endpoint == "register" else "/login"
    return f"{authority_url()}{path}?{urlencode({'network_target': target})}"


def _network_before_request():
    if not network_enabled():
        return None

    endpoint = str(request.endpoint or "")
    universe = current_universe_key()

    if not is_authority():
        if request.path in {
            "/api/options/email",
            "/api/options/password",
            "/api/options/resend-verification",
        }:
            return jsonify({
                "ok": False,
                "error": "network_identity_managed",
                "authority_url": f"{authority_url()}/options",
            }), 409
        if endpoint in {"auth_discord_start", "auth_discord_link_start"}:
            return redirect(f"{authority_url()}/options", code=302)
        if endpoint in {"login", "register"}:
            if session.get("user_id"):
                return redirect(url_for("overview"))
            return redirect(_authority_auth_url(endpoint, universe), code=302)
        if endpoint in {"forgot_password", "reset_password", "auth_discord_start"}:
            return redirect(f"{authority_url()}/login?{urlencode({'network_target': universe})}", code=302)
        return None

    if endpoint in {"login", "register"}:
        target = str(request.args.get("network_target") or "").strip().lower()
        if request.method == "GET" and target and target != universe and universe_url(target):
            session["gc_network_target"] = target
            if session.get("user_id") and universe_is_open(target):
                return redirect(url_for("network_universe_enter", target_key=target))
    return None


def _network_after_request(response: Response) -> Response:
    if not network_enabled() or not is_authority():
        return response
    if request.method != "POST" or str(request.endpoint or "") not in {"login", "register"}:
        return response
    if not session.get("user_id") or response.status_code not in {301, 302, 303, 307, 308}:
        return response

    pending_target = session.pop("gc_network_target", "")
    target = str(
        request.args.get("network_target")
        or request.form.get("network_target")
        or pending_target
        or ""
    ).strip().lower()
    if target and target != current_universe_key() and universe_url(target) and universe_is_open(target):
        response.headers["Location"] = url_for("network_universe_enter", target_key=target)
    return response


def _universe_enter(target_key: str):
    target = str(target_key or "").strip().lower()
    if not network_enabled():
        return ("Genesis Network authentication is not configured.", 503)
    if not is_authority():
        return redirect(authority_url(), code=302)
    if not session.get("user_id"):
        return redirect(_authority_auth_url("login", target), code=302)

    ok, reason, token = issue_handoff(int(session["user_id"]), target)
    if not ok or not token:
        status = 423 if reason == "universe_closed" else 400
        return (f"Universe handoff unavailable: {reason}", status)

    target_base = universe_url(target)
    return redirect(f"{target_base}/network/handoff?{urlencode({'token': token})}", code=302)


def _network_handoff():
    if not network_enabled():
        return ("Genesis Network authentication is not configured.", 503)
    if is_authority():
        return redirect(url_for("overview") if session.get("user_id") else url_for("login"), code=302)

    ok, reason, local_user = consume_handoff(str(request.args.get("token") or ""))
    if not ok or not local_user:
        return (f"Universe handoff rejected: {reason}", 400)

    from .auth import login_user

    login_user(local_user)
    return redirect(url_for("overview"), code=302)


def install_network_auth(app) -> None:
    """Register the network auth routes/hooks once on the Flask app."""
    if getattr(app, "_gc_network_auth_installed", False):
        return
    app._gc_network_auth_installed = True

    app.add_url_rule(
        "/network/universe/<target_key>/enter",
        endpoint="network_universe_enter",
        view_func=_universe_enter,
        methods=["GET"],
    )
    app.add_url_rule(
        "/network/handoff",
        endpoint="network_handoff",
        view_func=_network_handoff,
        methods=["GET"],
    )
    app.before_request(_network_before_request)
    app.after_request(_network_after_request)

    app.jinja_env.globals["GC_NETWORK_UNI1_OPEN"] = universe_is_open("uni1")
