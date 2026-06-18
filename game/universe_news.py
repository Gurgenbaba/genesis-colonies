"""Universe news / changelog (GC-642) — MOTD banner + history."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import table_exists
from .models import db, get_game_settings


def _now_ts() -> int:
    return int(time.time())


def _format_published(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d.%m.%Y")
    except Exception:
        return ""


def _row_to_entry(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    published_at = int(row["published_at"] or 0)
    return {
        "id": int(row["id"]),
        "title": str(row["title"] or "").strip(),
        "body": str(row["body"] or "").strip(),
        "published_at": published_at,
        "published_label": _format_published(published_at),
        "is_banner": bool(int(row["is_banner"] or 0)),
        "created_by": int(row["created_by"]) if row["created_by"] is not None else None,
        "created_at": int(row["created_at"] or 0),
    }


def ensure_legacy_motd_migrated(conn: sqlite3.Connection | None = None) -> None:
    """One-time import of legacy game_settings motd_text into universe_news."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not table_exists(conn, "universe_news"):
            return
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM universe_news;")
        if int(cur.fetchone()["c"]) > 0:
            return
        settings = get_game_settings(conn=conn) or {}
        body = str(settings.get("motd_text") or "").strip()
        if not body:
            return
        title = "Update"
        if body.startswith("Update"):
            first_line = body.split("\n", 1)[0].strip()
            if first_line:
                title = first_line[:120]
        ts = _now_ts()
        cur.execute(
            """
            INSERT INTO universe_news (title, body, published_at, is_banner, created_at)
            VALUES (?, ?, ?, 1, ?);
            """,
            (title, body, ts, ts),
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def list_news(*, limit: int = 50, conn: sqlite3.Connection | None = None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_legacy_motd_migrated(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, body, published_at, is_banner, created_by, created_at
            FROM universe_news
            ORDER BY published_at DESC, id DESC
            LIMIT ?;
            """,
            (max(1, int(limit)),),
        )
        return [_row_to_entry(row) for row in cur.fetchall()]
    finally:
        if own:
            conn.close()


def get_news_entry(news_id: int, *, conn: sqlite3.Connection | None = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, body, published_at, is_banner, created_by, created_at
            FROM universe_news
            WHERE id = ? LIMIT 1;
            """,
            (int(news_id),),
        )
        row = cur.fetchone()
        return _row_to_entry(row) if row else None
    finally:
        if own:
            conn.close()


def get_banner_entry(*, conn: sqlite3.Connection | None = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_legacy_motd_migrated(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, body, published_at, is_banner, created_by, created_at
            FROM universe_news
            WHERE is_banner = 1
            ORDER BY published_at DESC, id DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        if row:
            return _row_to_entry(row)
        cur.execute(
            """
            SELECT id, title, body, published_at, is_banner, created_by, created_at
            FROM universe_news
            ORDER BY published_at DESC, id DESC
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        return _row_to_entry(row) if row else None
    finally:
        if own:
            conn.close()


def create_news(
    *,
    title: str,
    body: str,
    set_banner: bool = True,
    created_by: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    clean_title = str(title or "").strip() or "Update"
    clean_body = str(body or "").strip()
    if not clean_body:
        raise ValueError("body_required")

    own = conn is None
    if own:
        conn = db()
    try:
        ts = _now_ts()
        cur = conn.cursor()
        if set_banner:
            cur.execute("UPDATE universe_news SET is_banner = 0 WHERE is_banner = 1;")
        cur.execute(
            """
            INSERT INTO universe_news (title, body, published_at, is_banner, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                clean_title[:200],
                clean_body,
                ts,
                1 if set_banner else 0,
                int(created_by) if created_by is not None else None,
                ts,
            ),
        )
        news_id = int(cur.lastrowid)
        if own:
            conn.commit()
        entry = get_news_entry(news_id, conn=conn)
        assert entry is not None
        return entry
    finally:
        if own:
            conn.close()


def set_banner(news_id: int, *, conn: sqlite3.Connection | None = None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM universe_news WHERE id = ? LIMIT 1;", (int(news_id),))
        if not cur.fetchone():
            return None
        cur.execute("UPDATE universe_news SET is_banner = 0 WHERE is_banner = 1;")
        cur.execute("UPDATE universe_news SET is_banner = 1 WHERE id = ?;", (int(news_id),))
        if own:
            conn.commit()
        return get_news_entry(news_id, conn=conn)
    finally:
        if own:
            conn.close()


def delete_news(news_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM universe_news WHERE id = ?;", (int(news_id),))
        deleted = cur.rowcount > 0
        if own:
            conn.commit()
        return deleted
    finally:
        if own:
            conn.close()


def news_page_payload(*, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    entries = list_news(limit=100, conn=conn)
    return {"ok": True, "entries": entries}
