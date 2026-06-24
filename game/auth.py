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
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional

from flask import flash, g, jsonify, redirect, request, session, url_for

logger = logging.getLogger(__name__)

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


def logout_user() -> None:
    """Leert die Session."""
    session.clear()


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

def _get_active_ban(player_id: int) -> Optional[Dict[str, Any]]:
    """
    Prüft, ob der Player aktuell gebannt ist (players.banned_until > now).
    Zusätzlich wird versucht, den letzten bans-Eintrag zu laden.

    Rückgabe:
      None  -> kein aktiver Bann
      Dict  -> { reason, banned_until, created_at, is_permanent, expires_text }
    """
    pid = int(player_id)
    now = int(time.time())

    conn = db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT banned_until FROM players WHERE id = ?;", (pid,))
        row = cur.fetchone()
        if not row:
            return None

        raw_bu = row.get("banned_until") if isinstance(row, dict) else row["banned_until"]
        if raw_bu is None:
            return None

        try:
            banned_until = int(raw_bu)
        except (TypeError, ValueError):
            return None

        if banned_until <= now:
            return None

        # Optional: letzter Ban-Eintrag
        ban_row = None
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
        except Exception:
            ban_row = None

        reason = ""
        created_at: Optional[int] = None

        if ban_row:
            try:
                reason = (ban_row["reason"] or "") if ban_row["reason"] is not None else ""
            except Exception:
                reason = ""

            try:
                bu2 = ban_row["banned_until"]
                if bu2 is not None:
                    banned_until = int(bu2)
            except Exception:
                pass

            try:
                ca = ban_row["created_at"]
                created_at = int(ca) if ca is not None else None
            except Exception:
                created_at = None

        def _fmt(ts: Optional[int]) -> str:
            if ts is None:
                return "-"
            try:
                return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
            except (OverflowError, OSError, ValueError):
                return "-"

        expires_text = _fmt(banned_until)

        # Permanent, wenn >10 Jahre in Zukunft
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
    finally:
        conn.close()


def _handle_if_banned(player_id: int):
    """
    Wenn gebannt:
      - Session leeren
      - flash
      - redirect -> /login
    """
    ban = _get_active_ban(int(player_id))
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

        ban_response = _handle_if_banned(pid)
        if ban_response is not None:
            return ban_response

        player = get_player_by_user_id(pid)
        if not player:
            session.clear()
            return redirect(url_for("login"))

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

        ban_response = _handle_if_banned(pid)
        if ban_response is not None:
            return ban_response

        user = get_current_user()
        if not user:
            session.clear()
            return redirect(url_for("login"))

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

        ban_response = _handle_if_banned(pid)
        if ban_response is not None:
            return jsonify({"ok": False, "error": "banned", "data": None}), 403

        player = get_player_by_user_id(pid)
        if not player:
            session.clear()
            return jsonify({"ok": False, "error": "not_logged_in", "data": None}), 401

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

        ban_response = _handle_if_banned(pid)
        if ban_response is not None:
            return jsonify({"ok": False, "error": "banned"}), 403

        user = get_current_user()
        if not user:
            session.clear()
            return jsonify({"ok": False, "error": "not_logged_in"}), 401

        if not bool(user.get("is_admin")):
            return jsonify({"ok": False, "error": "forbidden"}), 403

        g.admin_user = user
        try:
            touch_player_online(int(user["id"]))
        except Exception:
            pass
        return func(*args, **kwargs)

    return decorated  # type: ignore[return-value]
