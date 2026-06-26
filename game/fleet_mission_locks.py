"""
Live-ops fleet mission lockdown — universe-wide mission gates for new fleet sends.

Stored in game_settings.fleet_mission_locks_json. Existing fleet_movements are unaffected.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple

from game.db import db
from game.fleet_defs import MISSION_TYPES
from game.models import get_game_settings

SETTINGS_KEY = "fleet_mission_locks_json"

VALID_FLEET_MISSIONS = frozenset(MISSION_TYPES)

LOCK_REASONS = frozenset(
    {"reset_protection", "maintenance", "exploit_fix", "event", "manual"}
)

DEFAULT_RESET_ATTACK_SECONDS = 72 * 3600


def _empty_lock_entry() -> Dict[str, Any]:
    return {"locked": False, "until": None, "reason": None}


def _normalize_entry(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _empty_lock_entry()
    locked = bool(raw.get("locked"))
    until_raw = raw.get("until")
    until: Optional[int]
    try:
        until = int(until_raw) if until_raw not in (None, "") else None
    except (TypeError, ValueError):
        until = None
    if until is not None and until <= 0:
        until = None
    reason = str(raw.get("reason") or "").strip() or None
    if reason and reason not in LOCK_REASONS:
        reason = "manual"
    return {"locked": locked, "until": until, "reason": reason}


def _effective_entry(entry: Dict[str, Any], *, now: Optional[int] = None) -> Dict[str, Any]:
    """Return entry with expired timed locks treated as inactive."""
    norm = _normalize_entry(entry)
    if not norm["locked"]:
        return norm
    until = norm.get("until")
    now_i = int(now if now is not None else time.time())
    if until is not None and int(until) <= now_i:
        return _empty_lock_entry()
    return norm


def _read_raw_locks(conn=None) -> Dict[str, Any]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        settings = get_game_settings(conn=conn)
        raw = settings.get(SETTINGS_KEY) or "{}"
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(str(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    finally:
        if owns and conn is not None:
            conn.close()


def _write_raw_locks(data: Dict[str, Any], *, conn=None) -> None:
    owns = conn is None
    if owns:
        conn = db()
    try:
        from game.db import begin_write_transaction, commit

        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO game_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """,
            (SETTINGS_KEY, json.dumps(data, ensure_ascii=False)),
        )
        commit(conn)
    finally:
        if owns and conn is not None:
            conn.close()


def public_lock_info(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Client-safe lock payload (preview / admin UI)."""
    eff = _effective_entry(entry)
    return {
        "mission": None,
        "locked": bool(eff.get("locked")),
        "locked_until": eff.get("until"),
        "reason": eff.get("reason"),
    }


def get_active_fleet_mission_locks_for_client(*, conn=None) -> Dict[str, Dict[str, Any]]:
    """Active universe locks only — for fleet page / live-state (player UI)."""
    return {
        mission: info
        for mission, info in get_fleet_mission_locks(conn=conn).items()
        if info.get("locked")
    }


def get_fleet_mission_locks(*, conn=None) -> Dict[str, Dict[str, Any]]:
    """Effective lock state for all canonical missions."""
    raw = _read_raw_locks(conn=conn)
    out: Dict[str, Dict[str, Any]] = {}
    for mission in sorted(VALID_FLEET_MISSIONS):
        entry = _effective_entry(raw.get(mission) or {})
        info = public_lock_info(entry)
        info["mission"] = mission
        out[mission] = info
    return out


def is_fleet_mission_locked(
    mission_key: str,
    *,
    now: Optional[int] = None,
    conn=None,
) -> Tuple[bool, Dict[str, Any]]:
    mission = str(mission_key or "").strip().lower()
    if mission not in VALID_FLEET_MISSIONS:
        return False, _empty_lock_entry()
    raw = _read_raw_locks(conn=conn)
    entry = _effective_entry(raw.get(mission) or {}, now=now)
    info = public_lock_info(entry)
    info["mission"] = mission
    if entry.get("locked"):
        return True, info
    return False, info


def set_fleet_mission_lock(
    mission_key: str,
    locked: bool,
    *,
    locked_until: int | None = None,
    reason: str | None = None,
    admin_id: int | None = None,
    conn=None,
) -> Dict[str, Any]:
    mission = str(mission_key or "").strip().lower()
    if mission not in VALID_FLEET_MISSIONS:
        raise ValueError(f"invalid mission: {mission}")

    owns = conn is None
    if owns:
        conn = db()

    try:
        from game.db import begin_write_transaction, commit

        raw = _read_raw_locks(conn=conn)
        until: Optional[int]
        if locked_until in (None, ""):
            until = None
        else:
            until = int(locked_until)
            if until <= 0:
                until = None

        reason_norm = str(reason or "").strip() or None
        if reason_norm and reason_norm not in LOCK_REASONS:
            reason_norm = "manual"

        if locked:
            entry = {
                "locked": True,
                "until": until,
                "reason": reason_norm or "manual",
            }
        else:
            entry = _empty_lock_entry()

        raw[mission] = entry
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO game_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """,
            (SETTINGS_KEY, json.dumps(raw, ensure_ascii=False)),
        )
        commit(conn)

        eff = _effective_entry(entry)
        info = public_lock_info(eff)
        info["mission"] = mission
        if admin_id is not None:
            info["updated_by"] = int(admin_id)
        info["updated_at"] = int(time.time())
        return info
    finally:
        if owns and conn is not None:
            conn.close()


def apply_reset_attack_protection(
    *,
    duration_seconds: int = DEFAULT_RESET_ATTACK_SECONDS,
    admin_id: int | None = None,
    conn=None,
) -> Dict[str, Any]:
    """Lock attack missions until now + duration_seconds (default 72h)."""
    until = int(time.time()) + max(60, int(duration_seconds))
    return set_fleet_mission_lock(
        "attack",
        True,
        locked_until=until,
        reason="reset_protection",
        admin_id=admin_id,
        conn=conn,
    )
