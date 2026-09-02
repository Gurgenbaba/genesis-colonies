"""
Persistent runtime metrics (queue ticks, workers) for admin health.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

from .db import begin_write_transaction, commit, db, in_transaction, rollback

logger = logging.getLogger(__name__)

QUEUE_TICK_KEY = "queue_tick_last"


def _is_missing_runtime_state_table_error(exc: BaseException) -> bool:
    """True only for the legacy/dev case where migration 015 was not applied yet."""
    msg = str(exc).lower()
    return "runtime_state" in msg and any(
        marker in msg
        for marker in (
            "no such table",
            "does not exist",
            "undefinedtable",
        )
    )


def ensure_runtime_state_table(conn=None) -> None:
    """Explicit/lazy schema repair only; normal hot paths rely on migration 015."""
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


def _select_runtime_value(conn, key: str):
    return conn.execute(
        "SELECT value FROM runtime_state WHERE key = ? LIMIT 1;",
        (str(key),),
    ).fetchone()


def get_runtime_value(key: str, conn=None) -> Optional[str]:
    """Read a runtime value without running schema DDL on every call."""
    own = conn is None
    if own:
        conn = db()
    try:
        try:
            row = _select_runtime_value(conn, key)
        except Exception as exc:
            if not _is_missing_runtime_state_table_error(exc):
                raise
            # Legacy/test fail-safe. Production startup applies migration 015, so
            # this branch must never be part of the steady-state request path.
            ensure_runtime_state_table(conn)
            if own:
                commit(conn)
            row = _select_runtime_value(conn, key)
        return str(row["value"]) if row else None
    finally:
        if own and conn is not None:
            conn.close()


def set_runtime_value(key: str, value: str, conn=None) -> None:
    """Upsert a runtime metric.

    Steady-state reads/writes never execute CREATE TABLE/CREATE INDEX. Migration
    015 owns schema creation; lazy repair is retained only for legacy/dev DBs.

    On a shared connection, uses a SAVEPOINT so Postgres deadlocks / unique
    conflicts do not abort the caller's larger transaction (page-load TX).
    Deadlocks are retried once, then swallowed after logging (metrics only).
    """
    own = conn is None
    if own:
        conn = db()
    sp = "gc_runtime_state_upsert"
    last_exc: Optional[BaseException] = None
    schema_repaired = False
    try:
        if own and not in_transaction(conn):
            begin_write_transaction(conn)
        for attempt in range(3):
            savepoint_open = False
            try:
                if not own:
                    conn.execute(f"SAVEPOINT {sp}")
                    savepoint_open = True
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
                if not own:
                    conn.execute(f"RELEASE SAVEPOINT {sp}")
                    savepoint_open = False
                if own:
                    commit(conn)
                return
            except Exception as exc:
                last_exc = exc
                if not own and savepoint_open:
                    try:
                        conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                        conn.execute(f"RELEASE SAVEPOINT {sp}")
                    except Exception:
                        try:
                            rollback(conn)
                        except Exception:
                            pass
                elif own:
                    rollback(conn)

                if _is_missing_runtime_state_table_error(exc) and not schema_repaired:
                    schema_repaired = True
                    ensure_runtime_state_table(conn)
                    if own:
                        commit(conn)
                        if not in_transaction(conn):
                            begin_write_transaction(conn)
                    continue

                from .db import is_db_lock_error

                msg = str(exc).lower()
                is_deadlock = "deadlock" in msg
                if is_deadlock and attempt < 2:
                    time.sleep(0.05)
                    if own and not in_transaction(conn):
                        begin_write_transaction(conn)
                    continue
                if is_deadlock or is_db_lock_error(exc):
                    logger.warning(
                        "runtime_state upsert skipped (lock) key=%s",
                        key,
                    )
                    return
                raise
        if last_exc is not None:
            raise last_exc
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
    try:
        set_runtime_value(
            QUEUE_TICK_KEY,
            json.dumps(payload, ensure_ascii=False),
            conn=conn,
        )
    except Exception as exc:
        logger.warning("record_queue_tick_result failed: %s", exc)


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


def get_queue_tick_fresh_max_age_sec() -> float:
    """
    GC-PROD-SQLITE-STALL-001A: max age for QUEUE_TICK_KEY to count as healthy.

    Default 45s ≈ 2× typical ``run_game_worker`` interval (15s).
    Must NOT be derived from fleet_worker / maintenance heartbeats.
    """
    raw = os.environ.get("GC_QUEUE_TICK_FRESH_SEC", "").strip()
    if not raw:
        return 45.0
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return 45.0


def is_queue_tick_heartbeat_fresh(
    conn=None,
    *,
    now: Optional[float] = None,
    max_age_sec: Optional[float] = None,
) -> bool:
    """
    True only when ``execute_queue_tick`` / ``record_queue_tick_result`` left a
    recent successful ``QUEUE_TICK_KEY`` stamp.

    Missing or stale heartbeat ⇒ poll safety-net must remain responsible for
    queue finishes. Fleet/maintenance liveness must never be used here.
    """
    status = get_queue_tick_status(conn=conn)
    at = status.get("last_tick_at")
    if at is None:
        return False
    if status.get("ok") is False:
        return False
    try:
        last_at = float(at)
    except (TypeError, ValueError):
        return False
    if last_at <= 0:
        return False
    age_limit = float(max_age_sec if max_age_sec is not None else get_queue_tick_fresh_max_age_sec())
    now_f = float(now if now is not None else time.time())
    return (now_f - last_at) <= age_limit
