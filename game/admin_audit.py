"""
Admin audit log – records privileged actions for the Control Center.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from game.db import db, table_exists


def ensure_admin_audit_table(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id     INTEGER NOT NULL,
                action       TEXT NOT NULL,
                target_type  TEXT,
                target_id    TEXT,
                payload_json TEXT,
                ip           TEXT,
                user_agent   TEXT,
                created_at   INTEGER NOT NULL,
                FOREIGN KEY(admin_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log (created_at DESC);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_audit_admin ON admin_audit_log (admin_id, created_at DESC);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON admin_audit_log (action, created_at DESC);"
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def write_admin_audit(
    admin_id: int,
    action: str,
    *,
    target_type: Optional[str] = None,
    target_id: Optional[str | int] = None,
    payload: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_admin_audit_table(conn)
        conn.execute(
            """
            INSERT INTO admin_audit_log
                (admin_id, action, target_type, target_id, payload_json, ip, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(admin_id),
                str(action)[:128],
                (str(target_type)[:64] if target_type else None),
                (str(target_id)[:64] if target_id is not None else None),
                json.dumps(payload or {}, ensure_ascii=False)[:8000],
                (str(ip)[:64] if ip else None),
                (str(user_agent)[:256] if user_agent else None),
                int(time.time()),
            ),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def list_admin_audit(
    *,
    admin_id: Optional[int] = None,
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    if not table_exists(db(), "admin_audit_log"):
        ensure_admin_audit_table()
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    clauses: List[str] = []
    params: List[Any] = []

    if admin_id is not None:
        clauses.append("a.admin_id = ?")
        params.append(int(admin_id))
    if action:
        clauses.append("a.action = ?")
        params.append(str(action).strip()[:128])
    if target_type:
        clauses.append("a.target_type = ?")
        params.append(str(target_type).strip()[:64])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                a.id, a.admin_id, u.username AS admin_username,
                a.action, a.target_type, a.target_id, a.payload_json,
                a.ip, a.user_agent, a.created_at
            FROM admin_audit_log a
            LEFT JOIN users u ON u.id = a.admin_id
            {where}
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT ? OFFSET ?;
            """,
            params + [limit, offset],
        )
        rows = []
        for row in cur.fetchall():
            d = dict(row)
            try:
                d["payload"] = json.loads(d.pop("payload_json") or "{}")
            except Exception:
                d["payload"] = {}
                d.pop("payload_json", None)
            rows.append(d)
        return rows
    finally:
        conn.close()
