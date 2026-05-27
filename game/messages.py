from __future__ import annotations

import json
import time
from typing import Any, Optional

from .player_display import resolve_player_by_name
from .db import begin_write_transaction, commit, db, rollback, table_exists

VALID_CATEGORIES = frozenset(
    {"system", "player", "combat", "espionage", "expedition", "admin"}
)
REPORT_CATEGORIES = frozenset({"combat", "espionage", "expedition"})

SUBJECT_MIN = 3
SUBJECT_MAX = 120
BODY_MIN = 3
BODY_MAX = 5000
SEND_COOLDOWN_SEC = 30
DEFAULT_LIST_LIMIT = 50


def _now() -> int:
    return int(time.time())


def _err(key: str) -> dict[str, Any]:
    return {"ok": False, "error": key, "data": None}


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "error": None, "data": data}


def _norm_text(raw: Any, max_len: int) -> str:
    text = str(raw or "").replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _with_unread(player_id: int, data: Any, *, conn=None) -> dict[str, Any]:
    if isinstance(data, dict):
        data = {**data, "unread_count": unread_count(int(player_id), conn=conn)}
    return _ok(data)


def _table_ready(conn) -> bool:
    return table_exists(conn, "player_messages")


def _parse_metadata(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _row_to_dict(row: Any, *, recipient_name: str | None = None) -> dict[str, Any]:
    meta = _parse_metadata(row["metadata_json"])
    sender_player_id = (
        int(row["sender_player_id"]) if row["sender_player_id"] is not None else None
    )
    out: dict[str, Any] = {
        "id": int(row["id"]),
        "recipient_player_id": int(row["recipient_player_id"]),
        "sender_player_id": sender_player_id,
        "sender_name": str(row["sender_name"]) if row["sender_name"] is not None else None,
        "category": str(row["category"] or "system"),
        "subject": str(row["subject"] or ""),
        "body": str(row["body"] or ""),
        "is_read": bool(int(row["is_read"] or 0)),
        "is_archived": bool(int(row["is_archived"] or 0)),
        "created_at": int(row["created_at"] or 0),
        "read_at": int(row["read_at"]) if row["read_at"] is not None else None,
        "metadata": meta,
    }
    if recipient_name is not None:
        out["recipient_name"] = recipient_name
    if sender_player_id is not None:
        out["reply_to_player_id"] = sender_player_id
        out["reply_to_name"] = out["sender_name"]
    return out


def _category_clause(category: str | None) -> tuple[str, list[Any]]:
    cat = str(category or "").strip().lower()
    if not cat or cat == "all":
        return "", []
    if cat == "archive":
        return " AND is_archived = 1", []
    if cat == "reports":
        placeholders = ",".join("?" for _ in REPORT_CATEGORIES)
        return f" AND category IN ({placeholders})", list(REPORT_CATEGORIES)
    if cat in VALID_CATEGORIES:
        return " AND category = ?", [cat]
    return "", []


def _not_deleted_clause() -> str:
    return " AND deleted_at IS NULL"


def create_message(
    recipient_player_id: int,
    subject: str,
    body: str,
    *,
    category: str = "system",
    sender_player_id: int | None = None,
    sender_name: str | None = None,
    metadata: dict[str, Any] | None = None,
    conn=None,
) -> dict[str, Any]:
    subject_n = _norm_text(subject, SUBJECT_MAX)
    body_n = _norm_text(body, BODY_MAX)
    cat = str(category or "system").strip().lower()
    if cat not in VALID_CATEGORIES:
        cat = "system"
    if not subject_n:
        return _err("validation")
    if not body_n:
        return _err("validation")

    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    now = _now()
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        if own_conn:
            begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO player_messages (
                recipient_player_id, sender_player_id, sender_name,
                category, subject, body, is_read, is_archived,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?);
            """,
            (
                int(recipient_player_id),
                int(sender_player_id) if sender_player_id is not None else None,
                sender_name,
                cat,
                subject_n,
                body_n,
                meta_json,
                now,
            ),
        )
        message_id = int(cur.lastrowid)
        if own_conn:
            commit(conn)
    except Exception:
        if own_conn:
            rollback(conn)
        raise
    finally:
        if own_conn:
            conn.close()

    return _ok({"message_id": message_id})


def _valid_player_id(player_id: int) -> int | None:
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM players WHERE id = ? LIMIT 1;", (pid,))
        row = cur.fetchone()
        return int(row["id"]) if row else None
    finally:
        conn.close()


def notify_player(
    player_id: int,
    subject: str,
    body: str,
    *,
    category: str = "system",
    metadata: dict[str, Any] | None = None,
    sender_name: str | None = None,
) -> dict[str, Any]:
    """Helper for other systems to deliver inbox messages (plain text subject/body)."""
    pid = _valid_player_id(player_id)
    if pid is None:
        return _err("recipient_not_found")
    return create_message(
        pid,
        subject,
        body,
        category=category,
        sender_player_id=None,
        sender_name=sender_name or "System",
        metadata=metadata,
    )


def notify_system(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return notify_player(
        player_id, subject, body, category="system", metadata=metadata, sender_name="System"
    )


def notify_admin(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return notify_player(
        player_id,
        subject,
        body,
        category="admin",
        metadata=metadata,
        sender_name="Administration",
    )


def notify_combat(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return notify_player(
        player_id,
        subject,
        body,
        category="combat",
        metadata=metadata,
        sender_name="Kampfbericht",
    )


def notify_espionage(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return notify_player(
        player_id,
        subject,
        body,
        category="espionage",
        metadata=metadata,
        sender_name="Spionagebericht",
    )


def notify_expedition(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return notify_player(
        player_id,
        subject,
        body,
        category="expedition",
        metadata=metadata,
        sender_name="Expeditionsbericht",
    )


def _inbox_visibility_clause(*, archived: bool = False) -> str:
    """Shared inbox filters for list + unread_count (non-archive tab)."""
    if archived:
        return "recipient_player_id = ? AND deleted_at IS NULL AND is_archived = 1"
    return "recipient_player_id = ? AND deleted_at IS NULL AND is_archived = 0"


def list_messages(
    player_id: int,
    *,
    category: str | None = None,
    include_archived: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")

        cat = str(category or "").strip().lower()
        if cat == "archive":
            include_archived = True

        if cat == "archive":
            where = _inbox_visibility_clause(archived=True)
        else:
            where = _inbox_visibility_clause(archived=False)
        params: list[Any] = [int(player_id)]

        cat_sql, cat_params = _category_clause(None if cat in ("", "all", "archive") else cat)
        where += cat_sql
        params.extend(cat_params)

        lim = max(1, min(int(limit or DEFAULT_LIST_LIMIT), 100))
        off = max(0, int(offset or 0))

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, recipient_player_id, sender_player_id, sender_name,
                   category, subject, body, is_read, is_archived,
                   metadata_json, created_at, read_at
            FROM player_messages
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?;
            """,
            (*params, lim, off),
        )
        rows = [_row_to_dict(r) for r in cur.fetchall()]
        unread = unread_count(int(player_id), conn=conn)
        return _ok({"messages": rows, "unread_count": unread})
    finally:
        conn.close()


def get_message(player_id: int, message_id: int, *, mark_read: bool = True) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, recipient_player_id, sender_player_id, sender_name,
                   category, subject, body, is_read, is_archived,
                   metadata_json, created_at, read_at
            FROM player_messages
            WHERE id = ? AND recipient_player_id = ? AND deleted_at IS NULL
            LIMIT 1;
            """,
            (int(message_id), int(player_id)),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found")

        if mark_read and not int(row["is_read"] or 0):
            now = _now()
            begin_write_transaction(conn)
            try:
                conn.execute(
                    """
                    UPDATE player_messages
                    SET is_read = 1, read_at = ?
                    WHERE id = ? AND recipient_player_id = ?;
                    """,
                    (now, int(message_id), int(player_id)),
                )
                commit(conn)
            except Exception:
                rollback(conn)
                raise
            cur.execute(
                """
                SELECT id, recipient_player_id, sender_player_id, sender_name,
                       category, subject, body, is_read, is_archived,
                       metadata_json, created_at, read_at
                FROM player_messages
                WHERE id = ? LIMIT 1;
                """,
                (int(message_id),),
            )
            row = cur.fetchone()

        return _with_unread(player_id, {"message": _row_to_dict(row)}, conn=conn)
    finally:
        conn.close()


def mark_message_read(player_id: int, message_id: int) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        begin_write_transaction(conn)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE player_messages
            SET is_read = 1, read_at = COALESCE(read_at, ?)
            WHERE id = ? AND recipient_player_id = ? AND deleted_at IS NULL;
            """,
            (now, int(message_id), int(player_id)),
        )
        if int(cur.rowcount or 0) < 1:
            rollback(conn)
            return _err("not_found")
        commit(conn)
        return _with_unread(player_id, {"message_id": int(message_id), "read_at": now})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def mark_all_messages_read(player_id: int, *, category: str | None = None) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        where = f"{_inbox_visibility_clause(archived=False)} AND is_read = 0"
        params: list[Any] = [int(player_id)]
        cat_sql, cat_params = _category_clause(category)
        where += cat_sql
        params.extend(cat_params)

        begin_write_transaction(conn)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE player_messages
            SET is_read = 1, read_at = COALESCE(read_at, ?)
            WHERE {where};
            """,
            (now, *params),
        )
        updated = int(cur.rowcount or 0)
        commit(conn)
        return _with_unread(player_id, {"updated": updated})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def archive_message(player_id: int, message_id: int) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE player_messages
            SET is_archived = 1
            WHERE id = ? AND recipient_player_id = ? AND deleted_at IS NULL;
            """,
            (int(message_id), int(player_id)),
        )
        if int(cur.rowcount or 0) < 1:
            rollback(conn)
            return _err("not_found")
        commit(conn)
        return _with_unread(player_id, {"message_id": int(message_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def delete_message(player_id: int, message_id: int) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        begin_write_transaction(conn)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE player_messages
            SET deleted_at = ?
            WHERE id = ? AND recipient_player_id = ? AND deleted_at IS NULL;
            """,
            (now, int(message_id), int(player_id)),
        )
        if int(cur.rowcount or 0) < 1:
            rollback(conn)
            return _err("not_found")
        commit(conn)
        return _with_unread(player_id, {"message_id": int(message_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def unread_count(player_id: int, *, conn=None) -> int:
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not _table_ready(conn):
            return 0
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM player_messages
            WHERE {_inbox_visibility_clause(archived=False)}
              AND is_read = 0;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        return int(row["c"] or 0) if row else 0
    finally:
        if own_conn:
            conn.close()


def send_player_message(
    sender_player_id: int,
    recipient_name: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    subject_n = _norm_text(subject, SUBJECT_MAX)
    body_n = _norm_text(body, BODY_MAX)
    if len(subject_n) < SUBJECT_MIN or len(body_n) < BODY_MIN:
        return _err("validation")
    if len(subject_n) > SUBJECT_MAX or len(body_n) > BODY_MAX:
        return _err("validation")

    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")

        recipient, lookup_err = resolve_player_by_name(recipient_name, conn)
        if lookup_err == "ambiguous":
            return _err("recipient_ambiguous")
        if lookup_err or not recipient:
            return _err("recipient_not_found")
        recipient_id = int(recipient["id"])
        if recipient_id == int(sender_player_id):
            return _err("validation")

        cur = conn.cursor()
        cur.execute(
            """
            SELECT created_at FROM player_messages
            WHERE sender_player_id = ? AND category = 'player'
            ORDER BY id DESC LIMIT 1;
            """,
            (int(sender_player_id),),
        )
        last = cur.fetchone()
        if last and int(last["created_at"] or 0) > _now() - SEND_COOLDOWN_SEC:
            return _err("cooldown")

        cur.execute("SELECT name FROM players WHERE id = ? LIMIT 1;", (int(sender_player_id),))
        sender_row = cur.fetchone()
        sender_name = str(sender_row["name"]) if sender_row else f"Spieler #{sender_player_id}"

        begin_write_transaction(conn)
        try:
            result = create_message(
                recipient_id,
                subject_n,
                body_n,
                category="player",
                sender_player_id=int(sender_player_id),
                sender_name=sender_name,
                conn=conn,
            )
            if not result.get("ok"):
                rollback(conn)
                return result
            commit(conn)
        except Exception:
            rollback(conn)
            raise
        return _with_unread(
            int(sender_player_id),
            {
                "message_id": result["data"]["message_id"],
                "recipient_id": recipient_id,
                "recipient_name": str(recipient.get("name") or ""),
            },
        )
    finally:
        conn.close()


def admin_list_messages(
    *,
    player_id: int | None = None,
    category: str | None = None,
    include_deleted: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")

        where = "1=1"
        params: list[Any] = []
        if player_id is not None:
            where += " AND m.recipient_player_id = ?"
            params.append(int(player_id))
        if not include_deleted:
            where += " AND m.deleted_at IS NULL"

        cat = str(category or "").strip().lower()
        if cat and cat not in ("all", "archive"):
            cat_sql, cat_params = _category_clause(cat)
            where += cat_sql.replace("category", "m.category")
            params.extend(cat_params)
        elif cat == "archive":
            where += " AND m.is_archived = 1"

        lim = max(1, min(int(limit or DEFAULT_LIST_LIMIT), 200))
        off = max(0, int(offset or 0))

        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT m.id, m.recipient_player_id, m.sender_player_id, m.sender_name,
                   m.category, m.subject, m.body, m.is_read, m.is_archived,
                   m.metadata_json, m.created_at, m.read_at,
                   rp.name AS recipient_name
            FROM player_messages m
            LEFT JOIN players rp ON rp.id = m.recipient_player_id
            WHERE {where}
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ? OFFSET ?;
            """,
            (*params, lim, off),
        )
        rows = [
            _row_to_dict(r, recipient_name=str(r["recipient_name"] or ""))
            for r in cur.fetchall()
        ]
        return _ok({"messages": rows})
    finally:
        conn.close()


def admin_get_message(message_id: int) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, m.recipient_player_id, m.sender_player_id, m.sender_name,
                   m.category, m.subject, m.body, m.is_read, m.is_archived,
                   m.metadata_json, m.created_at, m.read_at,
                   rp.name AS recipient_name
            FROM player_messages m
            LEFT JOIN players rp ON rp.id = m.recipient_player_id
            WHERE m.id = ? AND m.deleted_at IS NULL
            LIMIT 1;
            """,
            (int(message_id),),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found")
        return _ok(
            {
                "message": _row_to_dict(
                    row, recipient_name=str(row["recipient_name"] or "")
                )
            }
        )
    finally:
        conn.close()


def admin_send_message(
    recipient: str | int,
    subject: str,
    body: str,
    *,
    category: str = "admin",
    sender_name: str | None = None,
) -> dict[str, Any]:
    subject_n = _norm_text(subject, SUBJECT_MAX)
    body_n = _norm_text(body, BODY_MAX)
    if len(subject_n) < SUBJECT_MIN or len(body_n) < BODY_MIN:
        return _err("validation")

    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")

        recipient_id: int | None = None
        if isinstance(recipient, int) or str(recipient).isdigit():
            recipient_id = int(recipient)
            cur = conn.cursor()
            cur.execute("SELECT id, name FROM players WHERE id = ? LIMIT 1;", (recipient_id,))
            row = cur.fetchone()
            if not row:
                return _err("recipient_not_found")
        else:
            hit, lookup_err = resolve_player_by_name(str(recipient), conn)
            if lookup_err == "ambiguous":
                return _err("recipient_ambiguous")
            if lookup_err or not hit:
                return _err("recipient_not_found")
            recipient_id = int(hit["id"])

        cat = str(category or "admin").strip().lower()
        if cat not in VALID_CATEGORIES:
            cat = "admin"

        if cat == "admin":
            return notify_admin(int(recipient_id), subject_n, body_n, metadata=None)
        return create_message(
            int(recipient_id),
            subject_n,
            body_n,
            category=cat,
            sender_name=sender_name or "Administration",
        )
    finally:
        conn.close()
