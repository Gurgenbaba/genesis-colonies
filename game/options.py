"""
Account / profile options – player name, homeworld, email, password.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from .db import begin_write_transaction, column_exists, commit, db, rollback, table_exists
from .models import (
    ensure_player_and_homeworld,
    hash_password,
    recompute_and_upsert_score,
    verify_user,
)
from .planet_evolution.repository import get_context_planet
from .playercard import _strip_control, sanitize_text_field
from .i18n import SUPPORTED_LOCALES, get_player_locale, normalize_locale, set_player_locale, ensure_locale_schema

NAME_MIN = 2
NAME_MAX = 40
PASSWORD_MIN = 4
EMAIL_MAX = 254

VACATION_MIN_DURATION_SEC = 48 * 3600
ACCOUNT_DELETION_GRACE_SEC = 7 * 24 * 3600
ACCOUNT_DELETION_WORKER_KEY = "account_deletion_worker_last"
ACCOUNT_DELETION_WORKER_INTERVAL_SEC = float(
    os.environ.get("GC_ACCOUNT_DELETION_WORKER_INTERVAL_SEC", "60")
)

logger = logging.getLogger(__name__)

ACCOUNT_SAFETY_CONFIRM_PHRASES: Dict[str, str] = {
    "vacation_enable": "ENABLE VACATION",
    "vacation_disable": "DISABLE VACATION",
    "account_delete": "DELETE ACCOUNT",
    "account_reset": "RESET ACCOUNT",
}

SENSITIVE_RATE_WINDOW_SEC = 60.0
SENSITIVE_RATE_MAX = 5
_SENSITIVE_BUCKETS: Dict[str, Dict[int, list]] = {"email": {}, "password": {}}

NOTIFY_SOUND_MODES = frozenset({"off", "quiet", "normal"})
DEFAULT_NOTIFY_ATTACK_SOUND = "normal"
DEFAULT_NOTIFY_MESSAGE_SOUND = "normal"

DEFAULT_SPY_PROBES = 5
MIN_SPY_PROBES = 1
MAX_SPY_PROBES = 9999
SPY_PROBE_QUICK_VALUES = (1, 3, 5, 10, 25)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-.]{1,39}$")
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
        if "notify_attack_sound" not in cols:
            cur.execute(
                "ALTER TABLE users ADD COLUMN notify_attack_sound TEXT NOT NULL DEFAULT 'normal';"
            )
        if "notify_message_sound" not in cols:
            cur.execute(
                "ALTER TABLE users ADD COLUMN notify_message_sound TEXT NOT NULL DEFAULT 'normal';"
            )
        if "default_spy_probes" not in cols:
            cur.execute(
                "ALTER TABLE users ADD COLUMN default_spy_probes INTEGER NOT NULL DEFAULT 5;"
            )
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
        ensure_account_safety_schema(c)
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
    from .name_policy import validate_player_name

    ok_policy, policy_reason = validate_player_name(s)
    if not ok_policy:
        return False, policy_reason or "name_policy_forbidden", ""
    return True, "", s


def validate_email(value: Any) -> Tuple[bool, str, str]:
    s = sanitize_text_field(value, EMAIL_MAX).lower()
    if not s:
        return False, "options_error_invalid_email", ""
    if len(s) > EMAIL_MAX or not _EMAIL_RE.match(s):
        return False, "options_error_invalid_email", ""
    return True, "", s


def normalize_notify_sound_mode(value: Any, *, default: str = DEFAULT_NOTIFY_ATTACK_SOUND) -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in NOTIFY_SOUND_MODES else default


def normalize_spy_probe_count(value: Any, *, default: int = DEFAULT_SPY_PROBES) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return default
    if count < MIN_SPY_PROBES:
        return MIN_SPY_PROBES
    if count > MAX_SPY_PROBES:
        return MAX_SPY_PROBES
    return count


def get_notify_sound_settings(player_id: int, *, conn=None) -> Dict[str, str]:
    pid = int(player_id or 0)
    if pid <= 0:
        return {
            "notify_attack_sound": DEFAULT_NOTIFY_ATTACK_SOUND,
            "notify_message_sound": DEFAULT_NOTIFY_MESSAGE_SOUND,
        }
    own = conn is None
    c = conn or db()
    try:
        ensure_account_options_schema(c)
        row = c.execute(
            """
            SELECT notify_attack_sound, notify_message_sound
            FROM users WHERE id = ? LIMIT 1;
            """,
            (pid,),
        ).fetchone()
        if not row:
            return {
                "notify_attack_sound": DEFAULT_NOTIFY_ATTACK_SOUND,
                "notify_message_sound": DEFAULT_NOTIFY_MESSAGE_SOUND,
            }
        return {
            "notify_attack_sound": normalize_notify_sound_mode(
                row["notify_attack_sound"],
                default=DEFAULT_NOTIFY_ATTACK_SOUND,
            ),
            "notify_message_sound": normalize_notify_sound_mode(
                row["notify_message_sound"],
                default=DEFAULT_NOTIFY_MESSAGE_SOUND,
            ),
        }
    finally:
        if own:
            c.close()


def update_notify_sounds(
    player_id: int,
    *,
    notify_attack_sound: Optional[str] = None,
    notify_message_sound: Optional[str] = None,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any]]:
    pid = int(player_id or 0)
    if pid <= 0:
        return False, "not_logged_in", {}

    attack_mode = (
        normalize_notify_sound_mode(notify_attack_sound, default=DEFAULT_NOTIFY_ATTACK_SOUND)
        if notify_attack_sound is not None
        else None
    )
    message_mode = (
        normalize_notify_sound_mode(notify_message_sound, default=DEFAULT_NOTIFY_MESSAGE_SOUND)
        if notify_message_sound is not None
        else None
    )
    if attack_mode is None and message_mode is None:
        return False, "options_error_invalid_notify_sound", {}

    own = conn is None
    c = conn or db()
    try:
        ensure_account_options_schema(c)
        current = get_notify_sound_settings(pid, conn=c)
        next_attack = attack_mode if attack_mode is not None else current["notify_attack_sound"]
        next_message = message_mode if message_mode is not None else current["notify_message_sound"]
        if (
            next_attack == current["notify_attack_sound"]
            and next_message == current["notify_message_sound"]
        ):
            return True, "options_saved", dict(current)

        begin_write_transaction(c)
        c.execute(
            """
            UPDATE users
            SET notify_attack_sound = ?, notify_message_sound = ?
            WHERE id = ?;
            """,
            (next_attack, next_message, pid),
        )
        if own:
            commit(c)
        payload = {
            "notify_attack_sound": next_attack,
            "notify_message_sound": next_message,
        }
        return True, "options_saved", payload
    except Exception:
        if own:
            rollback(c)
        return False, "options_error_invalid_notify_sound", {}
    finally:
        if own:
            c.close()


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


def ensure_account_safety_schema(conn=None) -> None:
    """Idempotent schema for account safety columns (GC-807)."""
    own = conn is None
    c = conn or db()
    cur = c.cursor()
    try:
        cols = {row[1] for row in cur.execute("PRAGMA table_info(players);").fetchall()}
        for col, typedef in (
            ("vacation_mode_active", "INTEGER NOT NULL DEFAULT 0"),
            ("vacation_locked_until", "INTEGER"),
            ("account_deletion_requested_at", "INTEGER"),
            ("account_deletion_due_at", "INTEGER"),
            ("account_deleted_at", "INTEGER"),
        ):
            if col not in cols:
                cur.execute(f"ALTER TABLE players ADD COLUMN {col} {typedef};")
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_players_account_deletion_due
                ON players (account_deletion_due_at)
                WHERE account_deletion_due_at IS NOT NULL AND account_deleted_at IS NULL;
            """
        )
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def validate_account_safety_confirm(action_key: str, confirm_text: Any) -> bool:
    expected = ACCOUNT_SAFETY_CONFIRM_PHRASES.get(str(action_key or ""))
    if not expected:
        return False
    return str(confirm_text or "").strip() == expected


def resolve_authenticated_player_id(user_id: int, *, conn=None) -> Optional[int]:
    """Map session user_id to players.id; None when no player row exists."""
    uid = int(user_id or 0)
    if uid <= 0:
        return None
    own = conn is None
    c = conn or db()
    try:
        row = c.execute("SELECT id FROM players WHERE id = ? LIMIT 1;", (uid,)).fetchone()
        return int(row["id"]) if row else None
    finally:
        if own:
            c.close()


def _player_safety_select_sql(conn) -> str:
    cols = [
        "vacation_mode_active",
        "vacation_locked_until",
        "account_deletion_requested_at",
        "account_deletion_due_at",
        "account_deleted_at",
    ]
    for legacy in ("vacation_mode", "vacation_until", "vacation_started_at"):
        if column_exists(conn, "players", legacy):
            cols.append(legacy)
    return ", ".join(cols)


def _player_safety_row(player_id: int, conn) -> Dict[str, Any]:
    ensure_account_safety_schema(conn)
    pid = resolve_authenticated_player_id(int(player_id), conn=conn)
    if pid is None:
        return {}
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT {_player_safety_select_sql(conn)}
        FROM players WHERE id = ? LIMIT 1;
        """,
        (int(pid),),
    )
    row = cur.fetchone()
    return dict(row) if row else {}


def _vacation_state_needs_repair(row: Dict[str, Any], now: int) -> bool:
    active = bool(int(row.get("vacation_mode_active") or 0))
    locked_until = row.get("vacation_locked_until")
    if active and locked_until is None:
        return True
    if not active and locked_until is not None:
        return True
    for legacy_col in ("vacation_mode", "vacation_until", "vacation_started_at"):
        if legacy_col in row and row.get(legacy_col) not in (None, "", 0):
            return True
    return False


def _vacation_hud_from_row(row: Dict[str, Any], now: int) -> Dict[str, Any]:
    locked_until = row.get("vacation_locked_until")
    deletion_due = row.get("account_deletion_due_at")
    vacation_active = bool(int(row.get("vacation_mode_active") or 0))
    deletion_pending = deletion_due is not None and int(deletion_due or 0) > now
    return {
        "vacation_active": vacation_active,
        "vacation_locked_until": int(locked_until) if locked_until else None,
        "vacation_can_disable": vacation_active
        and (locked_until is None or int(locked_until) <= now),
        "deletion_pending": deletion_pending,
        "deletion_due_at": int(deletion_due) if deletion_due else None,
        "deletion_seconds_remaining": max(0, int(deletion_due or 0) - now)
        if deletion_due and int(deletion_due) > now
        else 0,
    }


def repair_account_safety_state(
    player_id: int,
    *,
    conn=None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Clear inconsistent vacation flags for the authenticated player only."""
    own = conn is None
    c = conn or db()
    try:
        pid = resolve_authenticated_player_id(int(player_id), conn=c)
        if pid is None:
            return False, _vacation_hud_from_row({}, _now_ts())

        row = _player_safety_row(int(pid), c)
        now = _now_ts()
        if not _vacation_state_needs_repair(row, now):
            return False, _vacation_hud_from_row(row, now)

        active = bool(int(row.get("vacation_mode_active") or 0))
        locked_until = row.get("vacation_locked_until")
        set_active = active
        set_locked = locked_until
        if active and locked_until is None:
            set_active = 0
            set_locked = None
        elif not active and locked_until is not None:
            set_active = 0
            set_locked = None
        else:
            return False, _vacation_hud_from_row(row, now)

        begin_write_transaction(c)
        c.execute(
            """
            UPDATE players
            SET vacation_mode_active = ?, vacation_locked_until = ?
            WHERE id = ?;
            """,
            (int(set_active), set_locked, int(pid)),
        )
        for legacy_col, clear_val in (
            ("vacation_mode", 0),
            ("vacation_until", None),
            ("vacation_started_at", None),
        ):
            if column_exists(c, "players", legacy_col):
                c.execute(
                    f"UPDATE players SET {legacy_col} = ? WHERE id = ?;",
                    (clear_val, int(pid)),
                )
        write_account_audit(
            int(pid),
            "account_safety_repaired",
            payload={
                "before": {
                    "vacation_mode_active": active,
                    "vacation_locked_until": int(locked_until) if locked_until else None,
                },
                "after": {
                    "vacation_mode_active": bool(int(set_active)),
                    "vacation_locked_until": int(set_locked) if set_locked else None,
                },
            },
            ip=ip,
            user_agent=user_agent,
            conn=c,
        )
        commit(c)
        row = _player_safety_row(int(pid), c)
        return True, _vacation_hud_from_row(row, now)
    except Exception:
        if own:
            rollback(c)
        return False, _vacation_hud_from_row({}, _now_ts())
    finally:
        if own:
            c.close()


def get_account_safety_hud_state(
    player_id: int,
    *,
    conn=None,
    self_heal: bool = True,
) -> Dict[str, Any]:
    """Player-scoped vacation/deletion slice for shell HUD (no global cache)."""
    own = conn is None
    c = conn or db()
    try:
        pid = resolve_authenticated_player_id(int(player_id), conn=c)
        if pid is None:
            return _vacation_hud_from_row({}, _now_ts())
        if self_heal:
            repair_account_safety_state(int(pid), conn=c)
            process_due_account_deletion(int(pid), conn=c)
        row = _player_safety_row(int(pid), c)
        return _vacation_hud_from_row(row, _now_ts())
    finally:
        if own:
            c.close()


def get_account_safety_state(
    player_id: int,
    *,
    conn=None,
    self_heal: bool = True,
) -> Dict[str, Any]:
    """Canonical account safety snapshot for options + APIs."""
    own = conn is None
    c = conn or db()
    try:
        pid = resolve_authenticated_player_id(int(player_id), conn=c)
        if pid is None:
            return {
                "vacation_active": False,
                "vacation_locked_until": None,
                "vacation_can_disable": False,
                "deletion_pending": False,
                "deletion_requested_at": None,
                "deletion_due_at": None,
                "deletion_seconds_remaining": 0,
                "blockers": [],
                "blocker_details": {},
                "confirm_phrases": dict(ACCOUNT_SAFETY_CONFIRM_PHRASES),
            }
        if self_heal:
            repair_account_safety_state(int(pid), conn=c)
        return get_account_safety_snapshot(int(pid), conn=c, self_heal=False)
    finally:
        if own:
            c.close()


def is_account_deleted(player_id: int, *, conn=None) -> bool:
    own = conn is None
    c = conn or db()
    try:
        row = _player_safety_row(int(player_id), c)
        deleted_at = row.get("account_deleted_at")
        return deleted_at is not None and int(deleted_at or 0) > 0
    finally:
        if own:
            c.close()


def is_vacation_mode_active(player_id: int, *, conn=None) -> bool:
    own = conn is None
    c = conn or db()
    try:
        row = _player_safety_row(int(player_id), c)
        return bool(int(row.get("vacation_mode_active") or 0))
    finally:
        if own:
            c.close()


def vacation_blocks_outbound(player_id: int, *, conn=None) -> Tuple[bool, str]:
    if is_vacation_mode_active(int(player_id), conn=conn):
        return False, "options_error_vacation_active"
    return True, ""


def vacation_freezes_account_progress(player_id: int, *, conn=None) -> bool:
    """Pause production and queue progress while vacation mode is active."""
    return is_vacation_mode_active(int(player_id), conn=conn)


def vacation_blocks_incoming_attack(target_player_id: int, *, conn=None) -> bool:
    return is_vacation_mode_active(int(target_player_id), conn=conn)


def _cleanup_orphan_fleet_movements(player_id: int, *, conn) -> int:
    """Remove active movements whose origin planet no longer exists (UI cannot show/recall them)."""
    from .fleet import fleet_schema_ready

    if not fleet_schema_ready(conn):
        return 0
    from game.fleet_defs import ACTIVE_FLEET_STATUSES

    pid = int(player_id)
    placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)
    cur = conn.cursor()
    cur.execute(
        f"""
        DELETE FROM fleet_movements
        WHERE player_id = ?
          AND status IN ({placeholders})
          AND NOT EXISTS (
              SELECT 1 FROM planets p
              WHERE p.id = fleet_movements.origin_planet_id
                AND p.player_id = ?
          );
        """,
        (pid, *ACTIVE_FLEET_STATUSES, pid),
    )
    return int(cur.rowcount or 0)


def get_destructive_action_blocker_details(player_id: int, *, conn=None) -> Dict[str, int]:
    """Count open fleets, auctions, and queue jobs after finishing due work."""
    pid = int(player_id)
    from .fleet import fleet_schema_ready, list_active_movements, process_fleet_tick
    from .queue_engine import finish_due_work_once

    finish_due_work_once(
        player_id=pid,
        source="account_safety_blockers",
        recalc_ranks=False,
    )

    own = conn is None
    c = conn or db()
    details: Dict[str, int] = {
        "fleet_movements": 0,
        "auction_bids": 0,
        "build_queue": 0,
        "research_queue": 0,
        "shipyard_queue": 0,
        "defense_queue": 0,
        "planet_evolution_queue": 0,
    }
    try:
        if fleet_schema_ready(c):
            process_fleet_tick(player_id=pid)
            removed = _cleanup_orphan_fleet_movements(pid, conn=c)
            if removed > 0:
                commit(c)
            details["fleet_movements"] = len(list_active_movements(pid, conn=c))

        if table_exists(c, "auction_house_listings"):
            cur = c.cursor()
            now_i = _now_ts()
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM auction_house_listings
                WHERE status = 'active' AND ends_at > ?
                  AND current_bidder_id = ? AND current_bid > 0;
                """,
                (now_i, pid),
            )
            details["auction_bids"] = int(cur.fetchone()["c"] or 0)

        cur = c.cursor()
        cur.execute("SELECT id FROM planets WHERE player_id = ?;", (pid,))
        planet_ids = [int(r["id"]) for r in cur.fetchall()]
        if not planet_ids:
            return details

        ph = ",".join("?" for _ in planet_ids)

        if table_exists(c, "build_queue"):
            cur.execute(
                f"SELECT COUNT(*) AS c FROM build_queue WHERE planet_id IN ({ph});",
                planet_ids,
            )
            details["build_queue"] = int(cur.fetchone()["c"] or 0)

        if table_exists(c, "research_queue"):
            cur.execute(
                "SELECT COUNT(*) AS c FROM research_queue WHERE user_id = ?;",
                (pid,),
            )
            details["research_queue"] = int(cur.fetchone()["c"] or 0)

        if table_exists(c, "shipyard_queue"):
            cur.execute(
                f"""
                SELECT COUNT(*) AS c FROM shipyard_queue
                WHERE planet_id IN ({ph}) AND status = 'queued';
                """,
                planet_ids,
            )
            details["shipyard_queue"] = int(cur.fetchone()["c"] or 0)

        if table_exists(c, "defense_queue"):
            cur.execute(
                f"""
                SELECT COUNT(*) AS c FROM defense_queue
                WHERE planet_id IN ({ph}) AND status = 'queued';
                """,
                planet_ids,
            )
            details["defense_queue"] = int(cur.fetchone()["c"] or 0)

        if table_exists(c, "planet_evolution_queue"):
            cur.execute(
                f"SELECT COUNT(*) AS c FROM planet_evolution_queue WHERE planet_id IN ({ph});",
                planet_ids,
            )
            details["planet_evolution_queue"] = int(cur.fetchone()["c"] or 0)

        return details
    finally:
        if own:
            c.close()


def _blockers_from_details(details: Dict[str, int]) -> List[str]:
    blockers: List[str] = []
    if int(details.get("fleet_movements") or 0) > 0:
        blockers.append("active_fleets")
    if int(details.get("auction_bids") or 0) > 0:
        blockers.append("active_auctions")
    queue_total = sum(
        int(details.get(key) or 0)
        for key in (
            "build_queue",
            "research_queue",
            "shipyard_queue",
            "defense_queue",
            "planet_evolution_queue",
        )
    )
    if queue_total > 0:
        blockers.append("active_queues")
    return blockers


def get_destructive_action_blockers(player_id: int, *, conn=None) -> List[str]:
    """Return blocker codes when reset/deletion/vacation-enable is unsafe."""
    details = get_destructive_action_blocker_details(player_id, conn=conn)
    return _blockers_from_details(details)


def _destructive_action_blocker_payload(player_id: int, *, conn) -> Optional[Dict[str, Any]]:
    details = get_destructive_action_blocker_details(int(player_id), conn=conn)
    blockers = _blockers_from_details(details)
    if not blockers:
        return None
    return {"blockers": blockers, "blocker_details": details}


def get_account_safety_snapshot(
    player_id: int,
    *,
    conn=None,
    self_heal: bool = False,
) -> Dict[str, Any]:
    own = conn is None
    c = conn or db()
    try:
        pid = resolve_authenticated_player_id(int(player_id), conn=c)
        if pid is None:
            return {
                "vacation_active": False,
                "vacation_locked_until": None,
                "vacation_can_disable": False,
                "deletion_pending": False,
                "deletion_requested_at": None,
                "deletion_due_at": None,
                "deletion_seconds_remaining": 0,
                "blockers": [],
                "blocker_details": {},
                "confirm_phrases": dict(ACCOUNT_SAFETY_CONFIRM_PHRASES),
            }
        if self_heal:
            repair_account_safety_state(int(pid), conn=c)
        process_due_account_deletion(int(pid), conn=c)
        row = _player_safety_row(int(pid), c)
        now = _now_ts()
        hud = _vacation_hud_from_row(row, now)
        blocker_details = get_destructive_action_blocker_details(int(pid), conn=c)
        blockers = _blockers_from_details(blocker_details)
        return {
            **hud,
            "deletion_requested_at": int(row["account_deletion_requested_at"])
            if row.get("account_deletion_requested_at")
            else None,
            "blockers": blockers,
            "blocker_details": blocker_details,
            "confirm_phrases": dict(ACCOUNT_SAFETY_CONFIRM_PHRASES),
        }
    finally:
        if own:
            c.close()


def get_options_snapshot(player_id: int, conn=None) -> Dict[str, Any]:
    own = conn is None
    c = conn or db()
    try:
        ensure_locale_schema(c)
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
            "locale": get_player_locale(int(player_id), conn=c),
            "active_planet_id": int(planet["id"]) if planet and planet.get("id") else None,
            "active_planet_name": str(planet.get("name") or "") if planet else "",
            # Backward-compatible keys for older clients
            "homeworld_id": int(planet["id"]) if planet and planet.get("id") else None,
            "homeworld_name": str(planet.get("name") or "") if planet else "",
            "account_safety": get_account_safety_state(int(player_id), conn=c),
            **get_notify_sound_settings(int(player_id), conn=c),
            **get_spy_probe_settings(int(player_id), conn=c),
        }
    finally:
        if own:
            c.close()


def get_spy_probe_settings(player_id: int, *, conn=None) -> Dict[str, int]:
    pid = int(player_id or 0)
    if pid <= 0:
        return {"default_spy_probes": DEFAULT_SPY_PROBES}
    own = conn is None
    c = conn or db()
    try:
        ensure_account_options_schema(c)
        row = c.execute(
            "SELECT default_spy_probes FROM users WHERE id = ? LIMIT 1;",
            (pid,),
        ).fetchone()
        if not row:
            return {"default_spy_probes": DEFAULT_SPY_PROBES}
        return {
            "default_spy_probes": normalize_spy_probe_count(
                row["default_spy_probes"],
                default=DEFAULT_SPY_PROBES,
            ),
        }
    finally:
        if own:
            c.close()


def update_spy_probe_settings(
    player_id: int,
    *,
    default_spy_probes: Any,
    conn=None,
) -> Tuple[bool, str, Dict[str, int]]:
    pid = int(player_id or 0)
    if pid <= 0:
        return False, "not_logged_in", {}
    count = normalize_spy_probe_count(default_spy_probes)
    own = conn is None
    c = conn or db()
    try:
        ensure_account_options_schema(c)
        current = get_spy_probe_settings(pid, conn=c)
        if count == current["default_spy_probes"]:
            return True, "options_saved", dict(current)
        begin_write_transaction(c)
        c.execute(
            "UPDATE users SET default_spy_probes = ? WHERE id = ?;",
            (count, pid),
        )
        if own:
            commit(c)
        return True, "options_saved", {"default_spy_probes": count}
    except Exception:
        if own:
            rollback(c)
        return False, "options_error_invalid_spy_probes", {}
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


def update_locale(
    player_id: int,
    locale: str,
    *,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any]]:
    raw = str(locale or "").strip().lower()
    if raw not in SUPPORTED_LOCALES:
        return False, "options_error_invalid_locale", {}
    loc = normalize_locale(raw)
    own = conn is None
    c = conn or db()
    try:
        ensure_locale_schema(c)
        set_player_locale(int(player_id), loc, conn=c)
        if own:
            c.commit()
        return True, "options_saved", {"locale": loc}
    except Exception:
        if own:
            rollback(c)
        return False, "options_error_invalid_locale", {}
    finally:
        if own:
            c.close()


def _wipe_player_game_progress(player_id: int, *, conn) -> None:
    """Remove colonies, fleets, queues and progress; recreate homeworld. Keeps users row."""
    pid = int(player_id)
    cur = conn.cursor()
    cur.execute("SELECT id, name, is_admin FROM players WHERE id = ? LIMIT 1;", (pid,))
    prow = cur.fetchone()
    if not prow:
        raise ValueError("player_not_found")
    pname = str(prow["name"] or f"Player-{pid}")
    is_admin = int(prow["is_admin"] or 0)

    cur.execute("SELECT id FROM planets WHERE player_id = ?;", (pid,))
    planet_ids = [int(r["id"]) for r in cur.fetchall()]
    if planet_ids:
        ph = ",".join("?" for _ in planet_ids)
        for table, col in (
            ("build_queue", "planet_id"),
            ("shipyard_queue", "planet_id"),
            ("defense_queue", "planet_id"),
            ("planet_evolution_queue", "planet_id"),
            ("planet_ships", "planet_id"),
            ("planet_buildings", "planet_id"),
        ):
            if table_exists(conn, table):
                cur.execute(f"DELETE FROM {table} WHERE {col} IN ({ph});", planet_ids)

    if table_exists(conn, "fleet_movements"):
        cur.execute("DELETE FROM fleet_movements WHERE player_id = ?;", (pid,))
    if table_exists(conn, "research_queue"):
        cur.execute("DELETE FROM research_queue WHERE user_id = ?;", (pid,))
    if table_exists(conn, "research_levels"):
        cur.execute("DELETE FROM research_levels WHERE user_id = ?;", (pid,))
    if table_exists(conn, "player_scores"):
        cur.execute("DELETE FROM player_scores WHERE player_id = ?;", (pid,))
    if table_exists(conn, "player_messages"):
        cur.execute("DELETE FROM player_messages WHERE recipient_player_id = ?;", (pid,))

    if table_exists(conn, "planets"):
        cur.execute("DELETE FROM planets WHERE player_id = ?;", (pid,))

    from .planet_evolution.repository import set_active_planet_id

    ensure_player_and_homeworld(player_id=pid, player_name=pname, is_admin=is_admin, conn=conn)
    cur.execute(
        "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
        (pid,),
    )
    hw = cur.fetchone()
    if hw:
        set_active_planet_id(pid, int(hw["id"]), conn)
    recompute_and_upsert_score(pid, conn=conn)


def hard_delete_player_account(player_id: int, *, conn) -> Dict[str, Any]:
    """
    Permanently remove user, player, planets, queues, fleets, and related rows.
    Admin-only — caller must pre-clean FK blockers and run inside a write transaction.
    """
    pid = int(player_id)
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE id = ? LIMIT 1;", (pid,))
    user_row = cur.fetchone()
    if not user_row:
        raise ValueError("player_not_found")

    cur.execute("SELECT id, name FROM players WHERE id = ? LIMIT 1;", (pid,))
    player_row = cur.fetchone()
    planet_ids = [
        int(r[0])
        for r in cur.execute("SELECT id FROM planets WHERE player_id = ?;", (pid,)).fetchall()
    ]

    if table_exists(conn, "gd_votes"):
        cur.execute("DELETE FROM gd_votes WHERE player_id = ?;", (pid,))
    if table_exists(conn, "activity_xp_log"):
        cur.execute("DELETE FROM activity_xp_log WHERE player_id = ?;", (pid,))
    if table_exists(conn, "world_progress"):
        cur.execute("DELETE FROM world_progress WHERE player_id = ?;", (pid,))
    if table_exists(conn, "world_claims"):
        cur.execute("DELETE FROM world_claims WHERE player_id = ?;", (pid,))
    if table_exists(conn, "auction_house_bids"):
        cur.execute("DELETE FROM auction_house_bids WHERE player_id = ?;", (pid,))
    if table_exists(conn, "auction_house_listings"):
        if planet_ids:
            ph = ",".join("?" for _ in planet_ids)
            cur.execute(
                f"""
                UPDATE auction_house_listings
                SET current_bidder_id = NULL, current_bid_planet_id = NULL
                WHERE current_bidder_id = ? OR current_bid_planet_id IN ({ph});
                """,
                [pid, *planet_ids],
            )
        else:
            cur.execute(
                """
                UPDATE auction_house_listings
                SET current_bidder_id = NULL, current_bid_planet_id = NULL
                WHERE current_bidder_id = ?;
                """,
                (pid,),
            )
    if table_exists(conn, "lootbox_inventory"):
        cur.execute("DELETE FROM lootbox_inventory WHERE player_id = ?;", (pid,))
    if table_exists(conn, "combat_hall_of_fame"):
        cur.execute(
            """
            DELETE FROM combat_hall_of_fame
            WHERE attacker_player_id = ? OR defender_player_id = ?;
            """,
            (pid, pid),
        )

    cur.execute("DELETE FROM users WHERE id = ?;", (pid,))

    return {
        "player_id": pid,
        "username": str(user_row["username"] or ""),
        "player_name": str(player_row["name"] or "") if player_row else "",
        "planet_count": len(planet_ids),
        "planet_ids": planet_ids,
    }


def execute_account_deletion(player_id: int, *, conn) -> None:
    """Anonymize login and wipe game data after grace period."""
    pid = int(player_id)
    _wipe_player_game_progress(pid, conn=conn)
    token = secrets.token_hex(8)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE users
        SET username = ?, email = NULL, email_verified = 0,
            email_verification_token = NULL, password_reset_token = NULL,
            password_reset_expires_at = NULL,
            discord_id = NULL, discord_username = NULL, discord_avatar = NULL,
            discord_email = NULL,
            password_hash = ?
        WHERE id = ?;
        """,
        (f"deleted_{pid}_{token}", hash_password(secrets.token_urlsafe(24)), pid),
    )
    cur.execute(
        """
        UPDATE players
        SET name = ?, vacation_mode_active = 0, vacation_locked_until = NULL,
            account_deletion_requested_at = NULL, account_deletion_due_at = NULL,
            account_deleted_at = ?
        WHERE id = ?;
        """,
        (f"Deleted-{pid}", _now_ts(), pid),
    )


def any_due_account_deletions(*, now: Optional[int] = None, conn=None) -> bool:
    """True when any player is past account_deletion_due_at and not yet anonymized."""
    owns = conn is None
    c = conn or db()
    ts = int(now if now is not None else _now_ts())
    try:
        row = c.execute(
            """
            SELECT 1 FROM players
            WHERE account_deletion_due_at IS NOT NULL
              AND account_deletion_due_at <= ?
              AND (account_deleted_at IS NULL OR account_deleted_at = 0)
            LIMIT 1;
            """,
            (ts,),
        ).fetchone()
        return row is not None
    finally:
        if owns:
            c.close()


def process_all_due_account_deletions(*, conn=None) -> Dict[str, Any]:
    """Execute every scheduled account deletion that is past due."""
    owns = conn is None
    c = conn or db()
    now = _now_ts()
    processed: List[int] = []
    errors: List[Dict[str, Any]] = []
    try:
        rows = c.execute(
            """
            SELECT id FROM players
            WHERE account_deletion_due_at IS NOT NULL
              AND account_deletion_due_at <= ?
              AND (account_deleted_at IS NULL OR account_deleted_at = 0)
            ORDER BY account_deletion_due_at ASC;
            """,
            (now,),
        ).fetchall()
        if not rows:
            return {"ok": True, "processed": processed, "count": 0, "errors": errors}
        begin_write_transaction(c)
        try:
            for row in rows:
                pid = int(row["id"])
                try:
                    if process_due_account_deletion(pid, conn=c):
                        processed.append(pid)
                except Exception as exc:
                    errors.append({"player_id": pid, "error": str(exc)})
                    logger.exception("account deletion failed player_id=%s", pid)
            commit(c)
        except Exception:
            rollback(c)
            raise
        return {
            "ok": not errors,
            "processed": processed,
            "count": len(processed),
            "errors": errors,
        }
    except Exception:
        if owns:
            rollback(c)
        raise
    finally:
        if owns:
            c.close()


def _load_account_deletion_worker_record(conn=None) -> Optional[Dict[str, Any]]:
    from .runtime_state import get_runtime_value

    raw = get_runtime_value(ACCOUNT_DELETION_WORKER_KEY, conn=conn)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def seconds_until_account_deletion_worker_allowed(
    *,
    now: Optional[float] = None,
    conn=None,
) -> float:
    data = _load_account_deletion_worker_record(conn=conn)
    if not data or not data.get("ok"):
        return 0.0
    try:
        last_at = float(data.get("at") or 0)
    except (TypeError, ValueError):
        return 0.0
    if last_at <= 0:
        return 0.0
    now_f = float(now if now is not None else time.time())
    remaining = (last_at + ACCOUNT_DELETION_WORKER_INTERVAL_SEC) - now_f
    return max(0.0, remaining)


def should_run_account_deletion_worker(
    *,
    force: bool = False,
    now: Optional[float] = None,
    conn=None,
) -> bool:
    if force:
        return True
    if any_due_account_deletions(now=int(now) if now is not None else None, conn=conn):
        return True
    return seconds_until_account_deletion_worker_allowed(now=now, conn=conn) <= 0.0


def maybe_run_due_account_deletions(
    *,
    force: bool = False,
    source: str = "",
    conn=None,
) -> Dict[str, Any]:
    """Throttled global pass — offline players and cron safety net."""
    from .runtime_state import set_runtime_value

    owns = conn is None
    c = conn or db()
    started = time.time()
    if not should_run_account_deletion_worker(force=force, conn=c):
        remaining = seconds_until_account_deletion_worker_allowed(conn=c)
        return {
            "ok": True,
            "skipped_interval": True,
            "count": 0,
            "processed": [],
            "errors": [],
            "next_run_in_sec": int(remaining),
            "duration_ms": int((time.time() - started) * 1000),
            "source": source,
        }
    try:
        result = process_all_due_account_deletions(conn=c)
        payload = {
            **result,
            "skipped_interval": False,
            "duration_ms": int((time.time() - started) * 1000),
            "source": source,
        }
        set_runtime_value(
            ACCOUNT_DELETION_WORKER_KEY,
            json.dumps({"at": time.time(), "ok": bool(result.get("ok", True)), "source": source}),
            conn=c,
        )
        if result.get("count"):
            logger.info(
                "account deletion worker processed=%s source=%s",
                result.get("count"),
                source,
            )
        return payload
    except Exception as exc:
        logger.exception("account deletion worker failed source=%s", source)
        return {
            "ok": False,
            "skipped_interval": False,
            "count": 0,
            "processed": [],
            "errors": [{"error": str(exc)}],
            "duration_ms": int((time.time() - started) * 1000),
            "source": source,
        }
    finally:
        if owns:
            c.close()


def process_due_account_deletion(player_id: int, *, conn=None) -> bool:
    """Execute scheduled deletion when grace period elapsed. Returns True if executed."""
    own = conn is None
    c = conn or db()
    try:
        row = _player_safety_row(int(player_id), c)
        due = row.get("account_deletion_due_at")
        deleted_at = row.get("account_deleted_at")
        if deleted_at is not None and int(deleted_at or 0) > 0:
            return False
        if due is None or int(due) > _now_ts():
            return False
        own_tx = own
        if own_tx:
            begin_write_transaction(c)
        execute_account_deletion(int(player_id), conn=c)
        write_account_audit(
            int(player_id),
            "account_deletion_executed",
            payload={"due_at": int(due)},
            conn=c,
        )
        if own_tx:
            commit(c)
        return True
    except Exception:
        if own:
            rollback(c)
        raise
    finally:
        if own:
            c.close()


def enable_vacation_mode(
    player_id: int,
    confirm_text: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not validate_account_safety_confirm("vacation_enable", confirm_text):
        return False, "options_error_confirm_required", {}

    conn = db()
    try:
        blocked = _destructive_action_blocker_payload(int(player_id), conn=conn)
        if blocked:
            return False, "options_error_safety_blockers", blocked

        row = _player_safety_row(int(player_id), conn)
        if bool(int(row.get("vacation_mode_active") or 0)):
            return True, "options_vacation_already_active", get_account_safety_snapshot(int(player_id), conn=conn)

        now = _now_ts()
        locked_until = now + VACATION_MIN_DURATION_SEC
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE players
            SET vacation_mode_active = 1, vacation_locked_until = ?
            WHERE id = ?;
            """,
            (locked_until, int(player_id)),
        )
        write_account_audit(
            int(player_id),
            "vacation_mode_enabled",
            payload={"locked_until": locked_until},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "options_vacation_enabled", get_account_safety_snapshot(int(player_id), conn=conn)
    except Exception:
        rollback(conn)
        return False, "options_error_vacation_failed", {}
    finally:
        conn.close()


def disable_vacation_mode(
    player_id: int,
    confirm_text: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not validate_account_safety_confirm("vacation_disable", confirm_text):
        return False, "options_error_confirm_required", {}

    conn = db()
    try:
        row = _player_safety_row(int(player_id), conn)
        if not bool(int(row.get("vacation_mode_active") or 0)):
            return False, "options_error_vacation_not_active", {}

        locked_until = row.get("vacation_locked_until")
        now = _now_ts()
        if locked_until is not None and int(locked_until) > now:
            return False, "options_error_vacation_locked", {
                "vacation_locked_until": int(locked_until),
            }

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE players
            SET vacation_mode_active = 0, vacation_locked_until = NULL
            WHERE id = ?;
            """,
            (int(player_id),),
        )
        write_account_audit(
            int(player_id),
            "vacation_mode_disabled",
            payload={},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "options_vacation_disabled", get_account_safety_snapshot(int(player_id), conn=conn)
    except Exception:
        rollback(conn)
        return False, "options_error_vacation_failed", {}
    finally:
        conn.close()


def request_account_deletion(
    player_id: int,
    confirm_text: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not validate_account_safety_confirm("account_delete", confirm_text):
        return False, "options_error_confirm_required", {}

    conn = db()
    try:
        blocked = _destructive_action_blocker_payload(int(player_id), conn=conn)
        if blocked:
            return False, "options_error_safety_blockers", blocked

        row = _player_safety_row(int(player_id), conn)
        if row.get("account_deletion_due_at") and int(row["account_deletion_due_at"]) > _now_ts():
            return True, "options_deletion_already_pending", get_account_safety_snapshot(int(player_id), conn=conn)

        now = _now_ts()
        due = now + ACCOUNT_DELETION_GRACE_SEC
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE players
            SET account_deletion_requested_at = ?, account_deletion_due_at = ?
            WHERE id = ?;
            """,
            (now, due, int(player_id)),
        )
        write_account_audit(
            int(player_id),
            "account_deletion_requested",
            payload={"due_at": due},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "options_deletion_requested", get_account_safety_snapshot(int(player_id), conn=conn)
    except Exception:
        rollback(conn)
        return False, "options_error_deletion_failed", {}
    finally:
        conn.close()


def cancel_account_deletion(
    player_id: int,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    conn = db()
    try:
        row = _player_safety_row(int(player_id), conn)
        if not row.get("account_deletion_due_at"):
            return False, "options_error_deletion_not_pending", {}

        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE players
            SET account_deletion_requested_at = NULL, account_deletion_due_at = NULL
            WHERE id = ?;
            """,
            (int(player_id),),
        )
        write_account_audit(
            int(player_id),
            "account_deletion_cancelled",
            payload={},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        return True, "options_deletion_cancelled", get_account_safety_snapshot(int(player_id), conn=conn)
    except Exception:
        rollback(conn)
        return False, "options_error_deletion_failed", {}
    finally:
        conn.close()


def execute_account_reset(
    player_id: int,
    username: str,
    current_password: str,
    confirm_text: str,
    *,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not validate_account_safety_confirm("account_reset", confirm_text):
        return False, "options_error_confirm_required", {}

    if not verify_user(username, current_password):
        write_account_audit(
            int(player_id),
            "account_reset_denied",
            payload={"reason": "wrong_password"},
            ip=ip,
            user_agent=user_agent,
        )
        return False, "options_error_password_wrong", {}

    conn = db()
    try:
        blocked = _destructive_action_blocker_payload(int(player_id), conn=conn)
        if blocked:
            return False, "options_error_safety_blockers", blocked

        begin_write_transaction(conn)
        _wipe_player_game_progress(int(player_id), conn=conn)
        conn.execute(
            """
            UPDATE players
            SET vacation_mode_active = 0, vacation_locked_until = NULL,
                account_deletion_requested_at = NULL, account_deletion_due_at = NULL
            WHERE id = ?;
            """,
            (int(player_id),),
        )
        write_account_audit(
            int(player_id),
            "account_reset_executed",
            payload={},
            ip=ip,
            user_agent=user_agent,
            conn=conn,
        )
        commit(conn)
        snap = get_options_snapshot(int(player_id), conn=conn)
        return True, "options_reset_executed", snap
    except Exception:
        rollback(conn)
        return False, "options_error_reset_failed", {}
    finally:
        conn.close()
