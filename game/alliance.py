"""
Minimal alliance helpers for chat (and future alliance hub).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .db import db, begin_write_transaction, commit, rollback, table_exists


def _now() -> int:
    return int(time.time())


def get_player_alliance(player_id: int, conn=None) -> Optional[Dict[str, Any]]:
    """Return alliance row + member role for player, or None."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not table_exists(conn, "alliance_members"):
            return None
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                a.id AS alliance_id,
                a.tag,
                a.name,
                am.role,
                am.joined_at
            FROM alliance_members am
            JOIN alliances a ON a.id = am.alliance_id
            WHERE am.player_id = ?
            LIMIT 1;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()


def get_alliance_members(alliance_id: int, conn=None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT am.player_id, am.role, p.name AS player_name
            FROM alliance_members am
            JOIN players p ON p.id = am.player_id
            WHERE am.alliance_id = ?
            ORDER BY am.joined_at ASC;
            """,
            (int(alliance_id),),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        if own:
            conn.close()


def create_alliance(tag: str, name: str, founder_id: int, conn=None) -> Dict[str, Any]:
    """Create alliance and add founder as owner."""
    own = conn is None
    if own:
        conn = db()
    tag = str(tag or "").strip().upper()[:8]
    name = str(name or "").strip()[:64]
    if not tag or not name:
        raise ValueError("invalid_alliance")

    now = _now()
    try:
        if own:
            begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alliances (tag, name, created_at, updated_at)
            VALUES (?, ?, ?, ?);
            """,
            (tag, name, now, now),
        )
        aid = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO alliance_members (alliance_id, player_id, role, joined_at)
            VALUES (?, ?, 'owner', ?);
            """,
            (aid, int(founder_id), now),
        )
        if own:
            commit(conn)
        return {"id": aid, "tag": tag, "name": name}
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def add_alliance_member(alliance_id: int, player_id: int, role: str = "member", conn=None) -> None:
    own = conn is None
    if own:
        conn = db()
    now = _now()
    try:
        if own:
            begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO alliance_members (alliance_id, player_id, role, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(alliance_id, player_id) DO NOTHING;
            """,
            (int(alliance_id), int(player_id), str(role), now),
        )
        if own:
            commit(conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()
