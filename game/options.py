"""
Account / profile options – player name, homeworld, email, password.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Optional, Tuple

from .db import begin_write_transaction, column_exists, commit, db, rollback
from .models import hash_password, verify_user
from .planet_evolution.repository import get_context_planet
from .playercard import _strip_control, sanitize_text_field

NAME_MIN = 2
NAME_MAX = 32
PASSWORD_MIN = 4
EMAIL_MAX = 254

SENSITIVE_RATE_WINDOW_SEC = 60.0
SENSITIVE_RATE_MAX = 5
_SENSITIVE_BUCKETS: Dict[str, Dict[int, list]] = {"email": {}, "password": {}}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-.]{1,31}$")
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def _now_ts() -> int:
    return int(time.time())


def reset_sensitive_rate_limits() -> None:
    """Test helper – clear in-process rate buckets."""
    for bucket in _SENSITIVE_BUCKETS.values():
        bucket.clear()


def check_sensitive_rate_limit(player_id: int, kind: str) -> bool:
    """Return True if request is allowed (email / password APIs)."""
    if kind not in _SENSITIVE_BUCKETS:
        return True
    pid = int(player_id)
    now = time.time()
    bucket = _SENSITIVE_BUCKETS[kind]
    entries = bucket.get(pid, [])
    entries = [t for t in entries if t > now - SENSITIVE_RATE_WINDOW_SEC]
    if len(entries) >= SENSITIVE_RATE_MAX:
        bucket[pid] = entries
        return False
    entries.append(now)
    bucket[pid] = entries
    return True


def ensure_account_options_schema(conn=None) -> None:
    """Idempotent schema for tests and fresh DBs."""
    own = conn is None
    c = conn or db()
    cur = c.cursor()
    try:
        cols = {row[1] for row in cur.execute("PRAGMA table_info(users);").fetchall()}
        if "email" not in cols:
            cur.execute("ALTER TABLE users ADD COLUMN email TEXT;")
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
                ON users (LOWER(email))
                WHERE email IS NOT NULL AND email != '';
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS account_audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id    INTEGER NOT NULL,
                action       TEXT NOT NULL,
                payload_json TEXT,
                ip           TEXT,
                user_agent   TEXT,
                created_at   INTEGER NOT NULL,
                FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_account_audit_player "
            "ON account_audit_log (player_id, created_at DESC);"
        )
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def validate_display_name(value: Any) -> Tuple[bool, str, str]:
    """Validate player or planet display name."""
    raw = _strip_control(str(value or "").strip())
    if re.search(r'[<>&"\']', raw):
        return False, "options_error_invalid_name", ""
    s = raw.replace("<", "").replace(">", "")
    if len(s) < NAME_MIN or len(s) > NAME_MAX:
        return False, "options_error_invalid_name", ""
    if not _NAME_RE.match(s):
        return False, "options_error_invalid_name", ""
    return True, "", s


def validate_email(value: Any) -> Tuple[bool, str, str]:
    s = sanitize_text_field(value, EMAIL_MAX).lower()
    if not s:
        return False, "options_error_invalid_email", ""
    if len(s) > EMAIL_MAX or not _EMAIL_RE.match(s):
        return False, "options_error_invalid_email", ""
    return True, "", s


def validate_new_password(password: Any, confirm: Any) -> Tuple[bool, str]:
    p = str(password or "")
    c = str(confirm or "")
    if len(p) < PASSWORD_MIN:
        return False, "options_error_password_short"
    if p != c:
        return False, "options_error_password_mismatch"
    return True, ""


def _player_name_taken(name: str, player_id: int, conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM players
        WHERE LOWER(name) = LOWER(?) AND id != ?
        LIMIT 1;
        """,
        (name, int(player_id)),
    )
    return cur.fetchone() is not None


def _email_taken(email: str, user_id: int, conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM users
        WHERE LOWER(email) = LOWER(?) AND id != ?
        LIMIT 1;
        """,
        (email, int(user_id)),
    )
    return cur.fetchone() is not None


def write_account_audit(
    player_id: int,
    action: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    conn=None,
) -> None:
    own = conn is None
    c = conn or db()
    try:
        ensure_account_options_schema(c)
        c.execute(
            """
            INSERT INTO account_audit_log
                (player_id, action, payload_json, ip, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                int(player_id),
                str(action)[:128],
                json.dumps(payload or {}, ensure_ascii=False)[:4000],
                (str(ip)[:64] if ip else None),
                (str(user_agent)[:256] if user_agent else None),
                _now_ts(),
            ),
        )
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def get_options_snapshot(player_id: int, conn=None) -> Dict[str, Any]:
    own = conn is None
    c = conn or db()
    try:
        ensure_account_options_schema(c)
        cur = c.cursor()
        email_sel = "u.email" if column_exists(c, "users", "email") else "NULL AS email"
        verified_sel = (
            "u.email_verified"
            if column_exists(c, "users", "email_verified")
            else "0 AS email_verified"
        )
        cur.execute(
            f"""
            SELECT u.id, u.username, {email_sel}, {verified_sel}, p.name AS player_name
            FROM users u
            LEFT JOIN players p ON p.id = u.id
            WHERE u.id = ?;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        if not row:
            return {}
        planet = get_context_planet(int(player_id), conn=c)
        return {
            "player_id": int(player_id),
            "player_name": str(row["player_name"] or ""),
            "username": str(row["username"] or ""),
            "email": str(row["email"] or "") if row["email"] is not None else "",
            "email_verified": bool(int(row["email_verified"] or 0)),
            "active_planet_id": int(planet["id"]) if planet and planet.get("id") else None,
            "active_planet_name": str(planet.get("name") or "") if planet else "",
            # Backward-compatible keys for older clients
            "homeworld_id": int(planet["id"]) if planet and planet.get("id") else None,
            "homeworld_name": str(planet.get("name") or "") if planet else "",
        }
    finally:
        if own:
            c.close()


def update_player_name(
    player_id: int,
    new_name: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    ok, err, name = validate_display_name(new_name)
    if not ok:
        return False, err, {}

    conn = db()
    try:
        snap = get_options_snapshot(player_id, conn=conn)
        if snap.get("player_name") == name:
            return True, "options_saved", {"player_name": name}

        if _player_name_taken(name, player_id, conn):
            return False, "options_error_name_taken", {}

        begin_write_transaction(conn)
        conn.execute(
            "UPDATE players SET name = ? WHERE id = ?;",
            (name, int(player_id)),
        )
        write_account_audit(
            player_id,
            "player_name_change",
            payload={"from": snap.get("player_name"), "to": name},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "options_saved", {"player_name": name}
    except Exception:
        rollback(conn)
        return False, "options_error_invalid_name", {}
    finally:
        conn.close()


def update_active_planet_name(
    player_id: int,
    new_name: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Rename the player's currently active planet (session context, not client planet id)."""
    ok, err, name = validate_display_name(new_name)
    if not ok:
        return False, err, {}

    conn = db()
    try:
        planet = get_context_planet(int(player_id), conn=conn)
        if not planet or not planet.get("id"):
            return False, "options_error_invalid_name", {}

        planet_id = int(planet["id"])
        saved = {
            "planet_name": name,
            "planet_id": planet_id,
            "active_planet_name": name,
            "active_planet_id": planet_id,
            "homeworld_name": name,
            "homeworld_id": planet_id,
        }
        if str(planet.get("name") or "") == name:
            return True, "options_saved", saved

        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM planets
            WHERE player_id = ? AND LOWER(name) = LOWER(?) AND id != ?
            LIMIT 1;
            """,
            (int(player_id), name, planet_id),
        )
        if cur.fetchone():
            return False, "options_error_name_taken", {}

        begin_write_transaction(conn)
        conn.execute(
            "UPDATE planets SET name = ? WHERE id = ? AND player_id = ?;",
            (name, planet_id, int(player_id)),
        )
        write_account_audit(
            player_id,
            "planet_name_change",
            payload={"planet_id": planet_id, "from": planet.get("name"), "to": name},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "options_saved", saved
    except Exception:
        rollback(conn)
        return False, "options_error_invalid_name", {}
    finally:
        conn.close()


def update_homeworld_name(
    player_id: int,
    new_name: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Backward-compatible alias – renames the active planet, not homeworld only."""
    return update_active_planet_name(
        player_id,
        new_name,
        ip=ip,
        user_agent=user_agent,
    )


def delete_active_planet(
    player_id: int,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Delete the player's currently active colony (never the homeworld)."""
    conn = db()
    try:
        from .models import get_homeworld
        from .planet_evolution.repository import get_context_planet, set_active_planet_id

        planet = get_context_planet(int(player_id), conn=conn)
        if not planet or not planet.get("id"):
            return False, "planet_error_not_found", {}

        planet_id = int(planet["id"])
        if int(planet.get("is_homeworld") or 0):
            return False, "planet_error_cannot_delete_homeworld", {}

        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM planets WHERE player_id = ?;",
            (int(player_id),),
        )
        if int(cur.fetchone()["c"]) <= 1:
            return False, "planet_error_last_planet", {}

        homeworld = get_homeworld(int(player_id), conn=conn)
        hw_id = int(homeworld["id"])

        begin_write_transaction(conn)
        set_active_planet_id(int(player_id), hw_id, conn)
        cur.execute(
            "DELETE FROM planets WHERE id = ? AND player_id = ? AND is_homeworld = 0;",
            (planet_id, int(player_id)),
        )
        if int(cur.rowcount or 0) <= 0:
            rollback(conn)
            return False, "planet_error_delete_failed", {}

        write_account_audit(
            player_id,
            "planet_deleted",
            payload={
                "planet_id": planet_id,
                "name": planet.get("name"),
                "switched_to": hw_id,
            },
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "planet_deleted", {
            "deleted_planet_id": planet_id,
            "active_planet_id": hw_id,
            "active_planet_name": str(homeworld.get("name") or ""),
        }
    except Exception:
        rollback(conn)
        return False, "planet_error_delete_failed", {}
    finally:
        conn.close()


def update_email(
    player_id: int,
    new_email: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not check_sensitive_rate_limit(int(player_id), "email"):
        return False, "options_error_rate_limited", {}

    ok, err, email = validate_email(new_email)
    if not ok:
        return False, err, {}

    conn = db()
    try:
        snap = get_options_snapshot(player_id, conn=conn)
        if (snap.get("email") or "").lower() == email:
            return True, "options_saved", {
                "email": email,
                "email_verified": bool(snap.get("email_verified")),
            }

        if _email_taken(email, player_id, conn):
            return False, "options_error_email_taken", {}

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE users
            SET email = ?, email_verified = 0, email_verification_token = NULL
            WHERE id = ?;
            """,
            (email, int(player_id)),
        )
        write_account_audit(
            player_id,
            "email_change",
            payload={"from": snap.get("email"), "to": email},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        try:
            from .account_email import issue_email_verification

            issue_email_verification(int(player_id), send=True)
        except Exception:
            pass
        return True, "options_saved", {"email": email, "email_verified": False}
    except Exception:
        rollback(conn)
        return False, "options_error_invalid_email", {}
    finally:
        conn.close()


def update_password(
    player_id: int,
    username: str,
    current_password: str,
    new_password: str,
    confirm_password: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    pid = int(player_id)
    if not check_sensitive_rate_limit(pid, "password"):
        return False, "options_error_rate_limited", {}

    ok, err = validate_new_password(new_password, confirm_password)
    if not ok:
        return False, err, {}

    if not verify_user(username, current_password):
        write_account_audit(
            pid,
            "password_change_denied",
            payload={"reason": "wrong_password"},
            ip=ip,
            user_agent=user_agent,
        )
        return False, "options_error_password_wrong", {}

    conn = db()
    try:
        begin_write_transaction(conn)
        new_hash = hash_password(new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?;",
            (new_hash, pid),
        )
        write_account_audit(
            pid,
            "password_change",
            payload={"hash_upgraded": new_hash.startswith("pbkdf2:")},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "options_saved", {}
    except Exception:
        rollback(conn)
        return False, "options_error_password_wrong", {}
    finally:
        conn.close()
