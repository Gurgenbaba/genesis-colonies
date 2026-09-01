"""
Auth / Guard-Helpers für Genesis Colonies.

Exports (so wie in app.py benutzt):
- login_user(user_or_id)
- logout_user()
- get_current_user()
- require_login
- require_admin

Bann-Logik:
- Wenn players.banned_until > now:
    * Session wird geleert
    * Meldung geflasht
    * Redirect zur Login-Seite
"""

from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional

from flask import Response, current_app, flash, g, jsonify, redirect, request, session, url_for

logger = logging.getLogger(__name__)

from .db import DbPoolTimeout
from .models import (
    db,
    ensure_player_and_homeworld,
    get_player_by_user_id,
    touch_player_online,
)

ViewFunc = Callable[..., Any]


# =============================================================================
# Session / User Helpers
# =============================================================================

def login_user(user: Any) -> None:
    """
    Setzt die Login-Session für einen User/Player.

    Akzeptiert:
      - int              -> wird als player_id interpretiert
      - dict/Row/Objekt  -> versucht 'id' + optional 'username'/'name' zu lesen

    Effekte:
      - ensure_player_and_homeworld(...) sorgt für gültigen Player + Homeworld
      - session["user_id"] = player_id
      - session["username"] = username (falls verfügbar)

    Annahme:
      - users.id == players.id (1:1 Mapping)
    """
    player_id: Optional[int] = None
    username: Optional[str] = None

    if isinstance(user, int):
        player_id = user
    elif isinstance(user, dict):
        if "id" in user:
            player_id = user.get("id")
        username = user.get("username") or user.get("name")
    else:
        # Objekt/Row: Attribute
        if hasattr(user, "id"):
            try:
                player_id = getattr(user, "id")
            except Exception:
                player_id = None

        # username/name Attribute
        for key in ("username", "name"):
            if username is None and hasattr(user, key):
                try:
                    username = getattr(user, key)
                except Exception:
                    pass

        # Mapping-Fallback
        if player_id is None and hasattr(user, "get"):
            try:
                player_id = user.get("id")  # type: ignore[attr-defined]
            except Exception:
                player_id = None

        if username is None and hasattr(user, "get"):
            try:
                username = user.get("username") or user.get("name")  # type: ignore[attr-defined]
            except Exception:
                pass

    try:
        if player_id is None:
            return
        pid = int(player_id)
    except (TypeError, ValueError):
        return

    # Player + Homeworld sicherstellen
    try:
        ensure_player_and_homeworld(
            player_id=pid,
            player_name=username or None,
        )
    except Exception:
        # Setup-Fehler sollen Login nicht komplett blocken
        pass

    session["user_id"] = pid
    if username:
        session["username"] = str(username)
    # Persist across browser restarts — avoid silent session drops on refresh/poll.
    session.permanent = True
    session.modified = True


def logout_user() -> None:
    """Leert die Session."""
    session.clear()


def expire_browser_session_cookies(response: Response) -> Response:
    """
    Drop all plausible session cookie variants.

    Flipping SESSION_COOKIE_DOMAIN (host-only ↔ .apex) leaves duplicate cookies;
    session.clear() only rewrites the currently configured one, so logout appears
    broken until every variant is deleted.
    """
    name = str(current_app.config.get("SESSION_COOKIE_NAME") or "session")
    path = str(current_app.config.get("SESSION_COOKIE_PATH") or "/")
    secure = bool(current_app.config.get("SESSION_COOKIE_SECURE"))
    samesite = current_app.config.get("SESSION_COOKIE_SAMESITE") or "Lax"

    domains: list[Optional[str]] = [None]
    cfg = current_app.config.get("SESSION_COOKIE_DOMAIN")
    if cfg:
        raw = str(cfg).strip()
        if raw:
            domains.append(raw)
            domains.append(raw.lstrip("."))
            if not raw.startswith("."):
                domains.append(f".{raw}")

    try:
        from game.config import public_shop_host

        host = public_shop_host()
    except Exception:
        host = ""
    if host:
        domains.extend(
            [
                host,
                f".{host}",
                f"www.{host}",
                f".www.{host}",
            ]
        )

    seen: set[str] = set()
    for domain in domains:
        key = domain or ""
        if key in seen:
            continue
        seen.add(key)
        kwargs: Dict[str, Any] = {
            "path": path,
            "secure": secure,
            "httponly": True,
            "samesite": samesite,
        }
        if domain:
            kwargs["domain"] = domain
        try:
            response.delete_cookie(name, **kwargs)
        except Exception:
            logger.debug("session cookie delete skipped domain=%r", domain, exc_info=True)
    return response


def get_current_user() -> Optional[Dict[str, Any]]:
    """
    Liefert den aktuell eingeloggten User als Dict (JOIN users + players),
    oder None, wenn niemand eingeloggt ist.

    Rückgabe enthält u.a.:
      - id, username
      - user_is_admin, player_is_admin
      - is_admin (vereinheitlicht)
      - player_name
      - name (Anzeige-Name: player_name bevorzugt)
    """
    user_id = session.get("user_id")
    if not user_id:
        return None

    try:
        pid = int(user_id)
    except (TypeError, ValueError):
        return None

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                u.id           AS id,
                u.username     AS username,
                u.is_admin     AS user_is_admin,
                p.name         AS player_name,
                p.is_admin     AS player_is_admin
            FROM users u
            LEFT JOIN players p
                   ON p.id = u.id
            WHERE u.id = ?;
            """,
            (pid,),
        )
        row = cur.fetchone()
    except Exception:
        row = None
    finally:
        conn.close()

    if not row:
        return None

    d: Dict[str, Any] = dict(row)

    user_is_admin = int(d.get("user_is_admin", 0) or 0)
    player_is_admin = int(d.get("player_is_admin", 0) or 0)
    d["is_admin"] = 1 if (user_is_admin or player_is_admin) else 0

    player_name = d.get("player_name")
    d["name"] = player_name if player_name else d.get("username")

    return d


# =============================================================================
# Bann-Helpers
# =============================================================================

# Negative cache: polls must not checkout a pool connection every 2s for "not banned".
_BAN_NEG_TTL_SEC = 15.0
_ban_neg_until: dict[int, float] = {}
_ban_neg_lock = threading.Lock()


def _mark_not_banned(player_id: int) -> None:
    with _ban_neg_lock:
        _ban_neg_until[int(player_id)] = time.monotonic() + _BAN_NEG_TTL_SEC


def _cached_not_banned(player_id: int) -> bool:
    now_m = time.monotonic()
    with _ban_neg_lock:
        exp = _ban_neg_until.get(int(player_id))
        if exp is None:
            return False
        if exp <= now_m:
            _ban_neg_until.pop(int(player_id), None)
            return False
        return True


def _db_busy_response(*, json_api: bool):
    if json_api:
        return jsonify({"ok": False, "error": "db_busy", "retry": True}), 503
    return Response("Service temporarily busy. Please retry.", status=503, mimetype="text/plain")


def _ban_dict_from_until(
    banned_until: int,
    *,
    now: int,
    reason: str = "",
    created_at: Optional[int] = None,
) -> Dict[str, Any]:
    def _fmt(ts: Optional[int]) -> str:
        if ts is None:
            return "-"
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
        except (OverflowError, OSError, ValueError):
            return "-"

    expires_text = _fmt(banned_until)
    is_permanent = bool(banned_until - now > 10 * 365 * 24 * 3600)
    if is_permanent:
        expires_text = "permanent"
    return {
        "reason": reason,
        "banned_until": banned_until,
        "created_at": created_at,
        "expires_text": expires_text,
        "is_permanent": is_permanent,
    }


def _banned_until_from_player(player: Dict[str, Any], now: int) -> Optional[int]:
    raw_bu = player.get("banned_until")
    if raw_bu is None:
        return None
    try:
        banned_until = int(raw_bu)
    except (TypeError, ValueError):
        return None
    if banned_until <= now:
        return None
    return banned_until


def _load_latest_ban_row(player_id: int) -> Optional[Dict[str, Any]]:
    try:
        conn = db()
    except DbPoolTimeout:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT reason, banned_until, created_at
              FROM bans
             WHERE player_id = ?
             ORDER BY created_at DESC
             LIMIT 1;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def _get_active_ban(player_id: int, player: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Prüft, ob der Player aktuell gebannt ist (players.banned_until > now).
    Zusätzlich wird versucht, den letzten bans-Eintrag zu laden.

    Rückgabe:
      None  -> kein aktiver Bann
      Dict  -> { reason, banned_until, created_at, is_permanent, expires_text }

    PoolTimeout / lock: fail-open (treat as not banned) so polls cannot 500.
    """
    pid = int(player_id)
    now = int(time.time())
    if _cached_not_banned(pid):
        return None

    if player is not None:
        banned_until = _banned_until_from_player(player, now)
        if banned_until is None:
            _mark_not_banned(pid)
            return None
        try:
            extra = _load_latest_ban_row(pid)
        except DbPoolTimeout:
            extra = None
        reason = ""
        created_at: Optional[int] = None
        if extra:
            reason = extra.get("reason") or ""
            created_at = extra.get("created_at")
            if extra.get("banned_until") is not None:
                banned_until = int(extra["banned_until"])
        return _ban_dict_from_until(
            banned_until, now=now, reason=reason, created_at=created_at
        )

    try:
        conn = db()
    except DbPoolTimeout:
        logger.warning("ban check skipped pool_timeout player=%s", pid)
        return None
    try:
        cur = conn.cursor()

        cur.execute("SELECT banned_until FROM players WHERE id = ?;", (pid,))
        row = cur.fetchone()
        if not row:
            _mark_not_banned(pid)
            return None

        raw_bu = row.get("banned_until") if isinstance(row, dict) else row["banned_until"]
        player_view = {"banned_until": raw_bu}
        banned_until = _banned_until_from_player(player_view, now)
        if banned_until is None:
            _mark_not_banned(pid)
            return None

        extra = None
        try:
            cur.execute(
                """
                SELECT reason, banned_until, created_at
                  FROM bans
                 WHERE player_id = ?
                 ORDER BY created_at DESC
                 LIMIT 1;
                """,
                (pid,),
            )
            ban_row = cur.fetchone()
            extra = dict(ban_row) if ban_row else None
        except Exception:
            extra = None

        reason = ""
        created_at: Optional[int] = None
        if extra:
            try:
                reason = (extra.get("reason") or "") if extra.get("reason") is not None else ""
            except Exception:
                reason = ""
            try:
                bu2 = extra.get("banned_until")
                if bu2 is not None:
                    banned_until = int(bu2)
            except Exception:
                pass
            try:
                ca = extra.get("created_at")
                created_at = int(ca) if ca is not None else None
            except Exception:
                created_at = None
        return _ban_dict_from_until(
            banned_until, now=now, reason=reason, created_at=created_at
        )
    except DbPoolTimeout:
        logger.warning("ban check skipped pool_timeout player=%s", pid)
        return None
    finally:
        conn.close()


def _handle_if_banned(player_id: int, player: Optional[Dict[str, Any]] = None):
    """
    Wenn gebannt:
      - Session leeren
      - flash
      - redirect -> /login
    """
    try:
        ban = _get_active_ban(int(player_id), player=player)
    except DbPoolTimeout:
        logger.warning("ban check skipped pool_timeout player=%s", int(player_id))
        return None
    if not ban:
        return None

    reason = ban.get("reason") or "kein Grund angegeben"
    expires_text = ban.get("expires_text") or "-"

    if ban.get("is_permanent"):
        msg = f"Dein Account ist dauerhaft gesperrt. Grund: {reason}."
    else:
        msg = f"Dein Account ist bis {expires_text} gesperrt. Grund: {reason}."

    session.clear()
    flash(msg, "error")
    return redirect(url_for("login"))


# =============================================================================
# Decorators
# =============================================================================

def require_login(func: ViewFunc) -> ViewFunc:
    """
    Schützt eine Route: nur eingeloggte User.

    Zusätzlich:
    - Bann-Check
    - g.player setzen (für Templates/Logic)
    - touch_player_online(player_id) aufrufen
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("login"))

        try:
            pid = int(user_id)
        except (TypeError, ValueError):
            session.clear()
            return redirect(url_for("login"))

        try:
            player = get_player_by_user_id(pid)
        except DbPoolTimeout:
            logger.warning("login guard pool_timeout player=%s", pid)
            return _db_busy_response(json_api=False)
        if not player:
            session.clear()
            return redirect(url_for("login"))

        ban_response = _handle_if_banned(pid, player=player)
        if ban_response is not None:
            return ban_response

        # online markieren
        try:
            touch_player_online(int(player["id"]))
        except Exception:
            logger.warning("touch_player_online failed", exc_info=True)

        g.player = player
        return func(*args, **kwargs)

    return decorated  # type: ignore[return-value]


def require_admin(func: ViewFunc) -> ViewFunc:
    """
    Schützt eine Route: nur Admins.

    - require_login Logik wird hier bewusst wiederholt, damit du Decorators
      einzeln verwenden kannst (wie in app.py).
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return redirect(url_for("login"))

        try:
            pid = int(user_id)
        except (TypeError, ValueError):
            session.clear()
            return redirect(url_for("login"))

        try:
            user = get_current_user()
        except DbPoolTimeout:
            logger.warning("admin guard pool_timeout player=%s", pid)
            return _db_busy_response(json_api=False)
        if not user:
            session.clear()
            return redirect(url_for("login"))

        ban_response = _handle_if_banned(pid)
        if ban_response is not None:
            return ban_response

        if not bool(user.get("is_admin")):
            flash("Du hast keine Berechtigung für diesen Bereich.", "error")
            return redirect(url_for("overview"))

        # optional: player in g setzen (falls Admin-Templates es nutzen)
        try:
            player = get_player_by_user_id(pid)
            if player:
                g.player = player
                try:
                    touch_player_online(int(player["id"]))
                except Exception:
                    logger.warning("touch_player_online failed", exc_info=True)
        except Exception:
            pass

        return func(*args, **kwargs)

    return decorated  # type: ignore[return-value]


def require_login_api(func: ViewFunc) -> ViewFunc:
    """
    JSON API guard for /api/* player routes – returns 401/403 JSON instead of redirects.
    Sets g.player on success (same as require_login).
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401

        try:
            pid = int(user_id)
        except (TypeError, ValueError):
            session.clear()
            return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401

        try:
            player = get_player_by_user_id(pid)
        except DbPoolTimeout:
            logger.warning("api login guard pool_timeout player=%s", pid)
            return _db_busy_response(json_api=True)
        if not player:
            session.clear()
            return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401

        ban_response = _handle_if_banned(pid, player=player)
        if ban_response is not None:
            return jsonify({"ok": False, "error": "banned", "data": None}), 403

        try:
            touch_player_online(int(player["id"]))
        except Exception:
            pass

        g.player = player
        return func(*args, **kwargs)

    return decorated  # type: ignore[return-value]


def require_admin_api(func: ViewFunc) -> ViewFunc:
    """
    JSON API guard for /api/admin/* – returns 401/403 instead of redirects.
    Sets g.admin_user on success.
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"ok": False, "error": "not_logged_in"}), 401

        try:
            pid = int(user_id)
        except (TypeError, ValueError):
            session.clear()
            return jsonify({"ok": False, "error": "not_logged_in"}), 401

        try:
            user = get_current_user()
        except DbPoolTimeout:
            logger.warning("admin api guard pool_timeout player=%s", pid)
            return _db_busy_response(json_api=True)
        if not user:
            session.clear()
            return jsonify({"ok": False, "error": "not_logged_in"}), 401

        ban_response = _handle_if_banned(pid)
        if ban_response is not None:
            return jsonify({"ok": False, "error": "banned"}), 403

        if not bool(user.get("is_admin")):
            return jsonify({"ok": False, "error": "forbidden"}), 403

        g.admin_user = user
        try:
            touch_player_online(int(user["id"]))
        except Exception:
            pass
        return func(*args, **kwargs)

    return decorated  # type: ignore[return-value]
