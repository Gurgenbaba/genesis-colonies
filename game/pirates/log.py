"""Admin Bot-Log writer (EPIC-21 / GC-P01 foundation)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from ..db import table_exists

logger = logging.getLogger(__name__)

ACTION_LOG_TABLE = "pirate_action_log"
MAX_LOG_ROWS = 50_000


def _now() -> float:
    return time.time()


def log_schema_ready(conn) -> bool:
    return table_exists(conn, ACTION_LOG_TABLE)


def log_pirate_action(
    conn,
    *,
    kind: str,
    message: str = "",
    severity: str = "info",
    bot_player_id: Optional[int] = None,
    faction_key: Optional[str] = None,
    base_id: Optional[int] = None,
    galaxy_id: Optional[int] = None,
    target_player_id: Optional[int] = None,
    tick_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    if not log_schema_ready(conn):
        return
    sev = severity if severity in {"info", "warn", "error"} else "info"
    try:
        conn.execute(
            """
            INSERT INTO pirate_action_log (
                ts, tick_id, bot_player_id, faction_key, base_id, galaxy_id,
                kind, severity, target_player_id, payload_json, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                _now(),
                tick_id,
                bot_player_id,
                faction_key,
                base_id,
                galaxy_id,
                str(kind),
                sev,
                target_player_id,
                json.dumps(payload or {}, separators=(",", ":")),
                str(message or "")[:2000],
            ),
        )
    except Exception:
        logger.exception("pirate_action_log insert failed kind=%s", kind)


def recent_action_log(
    conn,
    *,
    limit: int = 100,
    kind: Optional[str] = None,
    galaxy_id: Optional[int] = None,
    faction_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not log_schema_ready(conn):
        return []
    limit = max(1, min(int(limit), 500))
    clauses = []
    args: List[Any] = []
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if galaxy_id is not None:
        clauses.append("galaxy_id = ?")
        args.append(int(galaxy_id))
    if faction_key:
        clauses.append("faction_key = ?")
        args.append(faction_key)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    args.append(limit)
    cur = conn.execute(
        f"""
        SELECT id, ts, tick_id, bot_player_id, faction_key, base_id, galaxy_id,
               kind, severity, target_player_id, payload_json, message
        FROM pirate_action_log
        {where}
        ORDER BY ts DESC
        LIMIT ?;
        """,
        tuple(args),
    )
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except Exception:
            payload = {}
        out.append(
            {
                "id": int(row["id"]),
                "ts": float(row["ts"]),
                "tick_id": row["tick_id"],
                "bot_player_id": row["bot_player_id"],
                "faction_key": row["faction_key"],
                "base_id": row["base_id"],
                "galaxy_id": row["galaxy_id"],
                "kind": row["kind"],
                "severity": row["severity"],
                "target_player_id": row["target_player_id"],
                "payload": payload if isinstance(payload, dict) else {},
                "message": row["message"] or "",
            }
        )
    return out


def prune_action_log(conn, *, keep: int = MAX_LOG_ROWS) -> int:
    """Delete oldest rows beyond ``keep``. Returns deleted count."""
    if not log_schema_ready(conn):
        return 0
    keep = max(1000, int(keep))
    cur = conn.execute("SELECT COUNT(*) AS c FROM pirate_action_log;")
    total = int(cur.fetchone()["c"] or 0)
    if total <= keep:
        return 0
    drop = total - keep
    conn.execute(
        """
        DELETE FROM pirate_action_log
        WHERE id IN (
            SELECT id FROM pirate_action_log ORDER BY ts ASC LIMIT ?
        );
        """,
        (drop,),
    )
    return drop
