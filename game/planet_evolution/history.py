"""Append-only planet history and legacy tags."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..models import db
from .repository import _json_dumps, _json_loads


def append_history(
    planet_id: int,
    event_type: str,
    title_key: str,
    *,
    body_key: Optional[str] = None,
    history_tag: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    visibility: str = "owner",
    conn: sqlite3.Connection,
    created_at: Optional[float] = None,
) -> int:
    cur = conn.cursor()
    ts = float(created_at if created_at is not None else time.time())
    cur.execute(
        """
        INSERT INTO planet_history (
            planet_id, event_type, history_tag, title_key, body_key,
            payload_json, visibility, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(planet_id),
            str(event_type),
            str(history_tag) if history_tag else None,
            str(title_key),
            str(body_key) if body_key else None,
            _json_dumps(payload or {}),
            str(visibility or "owner"),
            ts,
        ),
    )
    history_id = int(cur.lastrowid)

    if history_tag:
        cur.execute(
            """
            INSERT INTO planet_legacy_tags (planet_id, tag_key, count, first_at, last_at)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(planet_id, tag_key) DO UPDATE SET
                count = planet_legacy_tags.count + 1,
                last_at = excluded.last_at;
            """,
            (int(planet_id), str(history_tag), ts, ts),
        )

    return history_id


def get_history(
    planet_id: int,
    *,
    limit: int = 50,
    cursor: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        params: List[Any] = [int(planet_id)]
        where = "planet_id = ?"
        if cursor is not None:
            where += " AND id < ?"
            params.append(int(cursor))

        params.append(max(1, min(int(limit), 200)))
        cur.execute(
            f"""
            SELECT id, planet_id, event_type, history_tag, title_key, body_key,
                   payload_json, visibility, created_at
            FROM planet_history
            WHERE {where}
            ORDER BY id DESC
            LIMIT ?;
            """,
            params,
        )
        rows = []
        for row in cur.fetchall():
            item = dict(row)
            item["payload"] = _json_loads(item.pop("payload_json"), {})
            rows.append(item)

        next_cursor = rows[-1]["id"] if len(rows) >= limit else None
        return {"items": rows, "next_cursor": next_cursor}
    finally:
        if own:
            conn.close()
