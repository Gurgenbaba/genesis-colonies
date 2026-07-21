"""Diplomatic resolution definitions and per-galaxy active state (GC-721E)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from ..db import begin_write_transaction, column_exists, commit, db, table_exists
from .blocs import normalize_galaxy
from .definitions import schema_ready

_CACHE_LOCK = threading.RLock()
_RESOLUTION_CACHE: Dict[str, Any] = {"loaded": False}

RESOLUTION_KEYS = frozenset({
    "ban_directive",
    "boost_directive",
    "emergency_session",
    "gate_control",
    "bloc_sanction",
})

_RESOLUTION_JSON_COLS = ("mechanics_json", "tradeoffs_json")


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _parse_resolution_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    for col in _RESOLUTION_JSON_COLS:
        if col not in data:
            continue
        key = col.replace("_json", "")
        data[key] = _json_loads(data.pop(col), {})
    return data


def normalize_resolution_key(value: Any) -> str:
    """Return canonical resolution key or empty string if invalid."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw if raw in RESOLUTION_KEYS else ""


def resolution_schema_ready(*, conn: sqlite3.Connection) -> bool:
    try:
        if not table_exists(conn, "gd_resolution_state"):
            return False
        return column_exists(conn, "gd_resolution_definitions", "resolution_key")
    except Exception:
        return False


def reload_resolution_definitions(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn=conn) or not resolution_schema_ready(conn=conn):
            with _CACHE_LOCK:
                _RESOLUTION_CACHE["resolutions"] = {}
                _RESOLUTION_CACHE["loaded"] = True
            return

        rows = conn.execute(
            """
            SELECT resolution_key, label_key, description_key, category,
                   mechanics_json, tradeoffs_json, duration_days, sort_order
            FROM gd_resolution_definitions
            ORDER BY sort_order ASC, resolution_key ASC;
            """
        ).fetchall()

        resolutions: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            parsed = _parse_resolution_row(row)
            key = normalize_resolution_key(parsed.get("resolution_key"))
            if not key:
                continue
            parsed["resolution_key"] = key
            resolutions[key] = parsed

        with _CACHE_LOCK:
            _RESOLUTION_CACHE["resolutions"] = resolutions
            _RESOLUTION_CACHE["loaded"] = True
    finally:
        if own:
            conn.close()


def _ensure_resolutions_loaded(conn: Optional[sqlite3.Connection] = None) -> None:
    if conn is not None:
        reload_resolution_definitions(conn=conn)
        return
    if not _RESOLUTION_CACHE.get("loaded"):
        reload_resolution_definitions()


def list_resolution_definitions(
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """All resolution definitions sorted by sort_order."""
    _ensure_resolutions_loaded(conn)
    items = list((_RESOLUTION_CACHE.get("resolutions") or {}).values())
    items.sort(
        key=lambda d: (int(d.get("sort_order") or 0), str(d.get("resolution_key") or ""))
    )
    return items


def get_resolution_definition(
    resolution_key: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Single resolution definition or None."""
    key = normalize_resolution_key(resolution_key)
    if not key:
        return None
    _ensure_resolutions_loaded(conn)
    row = (_RESOLUTION_CACHE.get("resolutions") or {}).get(key)
    return dict(row) if row else None


def _parse_payload(raw: Any) -> Dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _build_active_payload(
    row: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    key = normalize_resolution_key(row.get("resolution_key"))
    definition = get_resolution_definition(key, conn=conn) if key else None
    return {
        "galaxy": int(row["galaxy"]),
        "resolution_key": key,
        "definition": dict(definition) if definition else None,
        "payload": _parse_payload(row.get("payload_json")),
        "started_at": int(row.get("started_at") or 0),
        "ends_at": (
            int(row["ends_at"]) if row.get("ends_at") not in (None, "") else None
        ),
        "updated_at": int(row.get("updated_at") or 0),
    }


def set_active_resolution(
    galaxy: Any,
    resolution_key: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Upsert the single active resolution for a galaxy."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        raise ValueError("invalid_galaxy")

    key = normalize_resolution_key(resolution_key)
    if not key:
        raise ValueError("invalid_resolution_key")

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn) or not resolution_schema_ready(conn=conn):
            raise ValueError("schema_not_ready")

        definition = get_resolution_definition(key, conn=conn)
        if not definition:
            raise ValueError("invalid_resolution_key")

        payload_data = dict(payload or {})
        now = int(time.time())
        duration_days = int(definition.get("duration_days") or 0)
        ends_at = payload_data.get("ends_at")
        if ends_at is None and duration_days > 0:
            ends_at = now + duration_days * 86400
        elif ends_at is not None:
            ends_at = int(ends_at)

        begin_write_transaction(conn)
        try:
            conn.execute(
                """
                INSERT INTO gd_resolution_state (
                    galaxy, resolution_key, payload_json, started_at, ends_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(galaxy) DO UPDATE SET
                    resolution_key = excluded.resolution_key,
                    payload_json = excluded.payload_json,
                    started_at = excluded.started_at,
                    ends_at = excluded.ends_at,
                    updated_at = excluded.updated_at;
                """,
                (
                    galaxy_id,
                    key,
                    json.dumps(payload_data),
                    now,
                    ends_at,
                    now,
                ),
            )
            commit(conn)
        except sqlite3.Error:
            raise

        row = conn.execute(
            "SELECT * FROM gd_resolution_state WHERE galaxy = ? LIMIT 1;",
            (galaxy_id,),
        ).fetchone()
        if not row:
            raise RuntimeError("resolution_state_upsert_failed")
        return _build_active_payload(dict(row), conn=conn)
    finally:
        if own_conn:
            conn.close()


def get_active_resolution(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Return active resolution for galaxy, or None if unset."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return None

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn) or not resolution_schema_ready(conn=conn):
            return None

        row = conn.execute(
            "SELECT * FROM gd_resolution_state WHERE galaxy = ? LIMIT 1;",
            (galaxy_id,),
        ).fetchone()
        if not row:
            return None
        return _build_active_payload(dict(row), conn=conn)
    finally:
        if own_conn:
            conn.close()


def clear_active_resolution(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """Remove active resolution for galaxy. Returns True if a row was deleted."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        raise ValueError("invalid_galaxy")

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn) or not resolution_schema_ready(conn=conn):
            return False

        begin_write_transaction(conn)
        try:
            cur = conn.execute(
                "DELETE FROM gd_resolution_state WHERE galaxy = ?;",
                (galaxy_id,),
            )
            commit(conn)
            return int(cur.rowcount or 0) > 0
        except sqlite3.Error:
            raise
    finally:
        if own_conn:
            conn.close()


def list_active_resolutions(
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """All galaxies with an active resolution, sorted by galaxy id."""
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn) or not resolution_schema_ready(conn=conn):
            return []

        rows = conn.execute(
            """
            SELECT * FROM gd_resolution_state
            ORDER BY galaxy ASC;
            """
        ).fetchall()
        return [_build_active_payload(dict(row), conn=conn) for row in rows]
    finally:
        if own_conn:
            conn.close()
