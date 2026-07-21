"""Load galactic diplomacy definitions from DB with in-memory cache (GC-721B)."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from ..db import table_exists
from ..models import db

_CACHE_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {"loaded": False}

BLOC_KEYS = frozenset({
    "scientific_bloc",
    "military_bloc",
    "industrial_bloc",
    "frontier_bloc",
    "neutral_bloc",
})

PERSONALITY_KEYS = frozenset({
    "academia_prime",
    "forge_of_war",
    "frontier_space",
    "trade_nexus",
    "bastion_sector",
})

_BLOC_JSON_COLS = ("affinity_directives_json",)
_PERSONALITY_JSON_COLS = ("mechanics_json", "unlock_rules_json")


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _parse_bloc_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    for col in _BLOC_JSON_COLS:
        if col not in data:
            continue
        key = col.replace("_json", "")
        data[key] = _json_loads(data.pop(col), [])
    return data


def _parse_personality_row(row: sqlite3.Row) -> Dict[str, Any]:
    data = dict(row)
    for col in _PERSONALITY_JSON_COLS:
        if col not in data:
            continue
        default: Any = {} if col != "unlock_rules_json" else {}
        key = col.replace("_json", "")
        data[key] = _json_loads(data.pop(col), default)
    return data


def normalize_bloc_key(value: Any) -> str:
    """Return canonical bloc key or empty string if invalid."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw if raw in BLOC_KEYS else ""


def normalize_personality_key(value: Any) -> str:
    """Return canonical personality key or empty string if invalid."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return raw if raw in PERSONALITY_KEYS else ""


def schema_ready(*, conn: sqlite3.Connection) -> bool:
    # Owner: game.db.table_exists (PG-safe). Never query sqlite_master on Postgres.
    try:
        return table_exists(conn, "gd_bloc_definitions")
    except Exception:
        return False


def reload_definitions(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            with _CACHE_LOCK:
                _CACHE["blocs"] = {}
                _CACHE["personalities"] = {}
                _CACHE["loaded"] = True
            return

        bloc_rows = conn.execute(
            """
            SELECT bloc_key, label_key, description_key,
                   affinity_directives_json, sort_order
            FROM gd_bloc_definitions
            ORDER BY sort_order ASC, bloc_key ASC;
            """
        ).fetchall()

        blocs: Dict[str, Dict[str, Any]] = {}
        for row in bloc_rows:
            parsed = _parse_bloc_row(row)
            key = normalize_bloc_key(parsed.get("bloc_key"))
            if not key:
                continue
            parsed["bloc_key"] = key
            blocs[key] = parsed

        personality_rows = conn.execute(
            """
            SELECT personality_key, label_key, description_key,
                   mechanics_json, unlock_rules_json, sort_order
            FROM gd_galaxy_personality_definitions
            ORDER BY sort_order ASC, personality_key ASC;
            """
        ).fetchall()

        personalities: Dict[str, Dict[str, Any]] = {}
        for row in personality_rows:
            parsed = _parse_personality_row(row)
            key = normalize_personality_key(parsed.get("personality_key"))
            if not key:
                continue
            parsed["personality_key"] = key
            personalities[key] = parsed

        with _CACHE_LOCK:
            _CACHE["blocs"] = blocs
            _CACHE["personalities"] = personalities
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


def list_bloc_definitions(conn: Optional[sqlite3.Connection] = None) -> List[Dict[str, Any]]:
    """All bloc definitions sorted by sort_order."""
    _ensure_loaded(conn)
    items = list((_CACHE.get("blocs") or {}).values())
    items.sort(key=lambda d: (int(d.get("sort_order") or 0), str(d.get("bloc_key") or "")))
    return items


def get_bloc_definition(
    bloc_key: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Single bloc definition or None."""
    key = normalize_bloc_key(bloc_key)
    if not key:
        return None
    _ensure_loaded(conn)
    row = (_CACHE.get("blocs") or {}).get(key)
    return dict(row) if row else None


def list_personality_definitions(
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """All galaxy personality definitions sorted by sort_order."""
    _ensure_loaded(conn)
    items = list((_CACHE.get("personalities") or {}).values())
    items.sort(
        key=lambda d: (int(d.get("sort_order") or 0), str(d.get("personality_key") or ""))
    )
    return items


def get_personality_definition(
    personality_key: str,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Single personality definition or None."""
    key = normalize_personality_key(personality_key)
    if not key:
        return None
    _ensure_loaded(conn)
    row = (_CACHE.get("personalities") or {}).get(key)
    return dict(row) if row else None
