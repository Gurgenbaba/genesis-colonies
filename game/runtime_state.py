"""
Persistent runtime metrics (queue ticks, workers) for admin health.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from .db import begin_write_transaction, commit, db, in_transaction, rollback

logger = logging.getLogger(__name__)

QUEUE_TICK_KEY = "queue_tick_last"


def ensure_runtime_state_table(conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_state (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_runtime_state_updated "
            "ON runtime_state (updated_at DESC);"
        )
        if own:
            commit(conn)
    finally:
        if own and conn is not None:
            conn.close()


def get_runtime_value(key: str, conn=None) -> Optional[str]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_runtime_state_table(conn)
        row = conn.execute(
            "SELECT value FROM runtime_state WHERE key = ? LIMIT 1;",
            (str(key),),
        ).fetchone()
        return str(row["value"]) if row else None
    finally:
        if own and conn is not None:
            conn.close()


def set_runtime_value(key: str, value: str, conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_runtime_state_table(conn)
        if own and not in_transaction(conn):
            begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO runtime_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at;
            """,
            (str(key), str(value), float(time.time())),
        )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def record_queue_tick_result(tick_result: Dict[str, Any], conn=None) -> None:
    """Persist last queue tick summary for admin runtime panel."""
    payload = {
        "at": int(time.time()),
        "ok": bool(tick_result.get("ok", True)),
        "source": str(tick_result.get("source") or "cron"),
        "scope": str(tick_result.get("scope") or "due"),
        "finished": dict(tick_result.get("finished") or {}),
        "affected_players": list(tick_result.get("affected_players") or []),
        "affected_planets": list(tick_result.get("affected_planets") or []),
        "batches": int(tick_result.get("batches") or 0),
        "players_processed": int(tick_result.get("players_processed") or 0),
        "duration_ms": int(tick_result.get("duration_ms") or tick_result.get("tick_elapsed_ms") or 0),
        "errors": list(tick_result.get("errors") or []),
    }
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_runtime_state_table(conn)
        if own and not in_transaction(conn):
            begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO runtime_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at;
            """,
            (QUEUE_TICK_KEY, json.dumps(payload, ensure_ascii=False), float(time.time())),
        )
        if own:
            commit(conn)
    except Exception as exc:
        if own:
            rollback(conn)
        logger.warning("record_queue_tick_result failed: %s", exc)
    finally:
        if own and conn is not None:
            conn.close()


def _empty_queue_tick_status() -> Dict[str, Any]:
    return {
        "last_tick_at": None,
        "last_tick_source": None,
        "last_tick_duration_ms": None,
        "last_at": None,
        "ok": None,
        "source": None,
        "scope": None,
        "finished": {},
        "duration_ms": None,
        "affected_players": [],
        "affected_players_count": 0,
        "errors": [],
        "errors_count": 0,
        "batches": 0,
        "players_processed": 0,
    }


def get_queue_tick_status(conn=None) -> Dict[str, Any]:
    raw = get_runtime_value(QUEUE_TICK_KEY, conn=conn)
    if not raw:
        return _empty_queue_tick_status()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        out = _empty_queue_tick_status()
        out["ok"] = False
        out["parse_error"] = True
        out["raw"] = raw
        return out

    errors = list(data.get("errors") or [])
    affected = list(data.get("affected_players") or [])
    finished = data.get("finished") or {}
    duration_ms = data.get("duration_ms")
    at = data.get("at")
    source = data.get("source")

    return {
        "last_tick_at": at,
        "last_tick_source": source,
        "last_tick_duration_ms": duration_ms,
        "last_at": at,
        "ok": data.get("ok"),
        "source": source,
        "scope": data.get("scope"),
        "finished": finished,
        "duration_ms": duration_ms,
        "affected_players": affected,
        "affected_players_count": len(affected),
        "errors": errors,
        "errors_count": len(errors),
        "batches": int(data.get("batches") or 0),
        "players_processed": int(data.get("players_processed") or 0),
    }
