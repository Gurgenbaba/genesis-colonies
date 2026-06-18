"""Load galactic directive definitions from DB with in-memory cache (GC-720B)."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from ..models import db

_CACHE_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {"loaded": False}

DIRECTIVE_KEYS = frozenset({
    "industrial",
    "scientific",
    "military",
    "logistics",
    "defensive",
    "expansion",
    "exploration",
})

_JSON_COLS = (
    "mechanics_json",
    "secondary_mechanics_json",
    "tradeoffs_json",
    "eligible_as",
)


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _parse_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    for col in _JSON_COLS:
        if col not in data:
            continue
        default: Any = [] if col == "eligible_as" else {}
        parsed = _json_loads(data.pop(col), default)
        key = col.replace("_json", "")
        data[key] = parsed
    return data


def normalize_directive_key(value: Any) -> str:
    """Return canonical directive key or empty string if invalid."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw if raw in DIRECTIVE_KEYS else ""


def schema_ready(*, conn: sqlite3.Connection) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gd_directive_definitions' LIMIT 1;"
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def reload_definitions(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            with _CACHE_LOCK:
                _CACHE["directives"] = {}
                _CACHE["loaded"] = True
            return

        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT directive_key, label_key, description_key,
                   mechanics_json, secondary_mechanics_json, tradeoffs_json,
                   eligible_as, sort_order
            FROM gd_directive_definitions
            ORDER BY sort_order ASC, directive_key ASC;
            """
        ).fetchall()

        directives: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            parsed = _parse_row(row)
            key = normalize_directive_key(parsed.get("directive_key"))
            if not key:
                continue
            parsed["directive_key"] = key
            directives[key] = parsed

        with _CACHE_LOCK:
            _CACHE["directives"] = directives
            _CACHE["loaded"] = True
    finally:
        if own:
            conn.close()


def _ensure_loaded(conn: Optional[sqlite3.Connection] = None) -> None:
    if conn is not None:
        reload_definitions(conn=conn)
        return
    if not _CACHE.get("loaded"):
        reload_definitions()


def list_directive_definitions(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """All directive definitions sorted by sort_order."""
    _ensure_loaded(conn)
    items = list((_CACHE.get("directives") or {}).values())
    items.sort(key=lambda d: (int(d.get("sort_order") or 0), str(d.get("directive_key") or "")))
    return items


def get_directive_definition(
    directive_key: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Single directive definition or None."""
    key = normalize_directive_key(directive_key)
    if not key:
        return None
    _ensure_loaded(conn)
    row = (_CACHE.get("directives") or {}).get(key)
    return dict(row) if row else None
