from __future__ import annotations

import time
from typing import Any

from .db import begin_write_transaction, commit, db, rollback, table_exists


def _now() -> int:
    return int(time.time())


def _err(key: str) -> dict[str, Any]:
    return {"ok": False, "error": key, "data": None}


def _ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "error": None, "data": data}


def _norm_text(raw: Any, max_len: int) -> str:
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(text) > max_len:
        text = text[:max_len]
    return text


def _ticket_status_label(status: str) -> str:
    mapping = {
        "open": "Offen",
        "in_progress": "In Bearbeitung",
        "closed": "Geschlossen",
    }
    return mapping.get(str(status or "open"), "Offen")


def _priority_label(priority: str) -> str:
    mapping = {
        "low": "Niedrig",
        "normal": "Normal",
        "high": "Hoch",
    }
    return mapping.get(str(priority or "normal"), "Normal")


def _category_label(category: str) -> str:
    mapping = {
        "general": "Allgemein",
        "bug": "Bug",
        "account": "Account",
        "balance": "Balance",
        "report": "Meldung",
    }
    return mapping.get(str(category or "general"), "Allgemein")


def _is_admin(player_id: int, conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(u.is_admin, 0) AS ua, COALESCE(p.is_admin, 0) AS pa
        FROM players p
        LEFT JOIN users u ON u.id = p.id
        WHERE p.id = ? LIMIT 1;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    if not row:
        return False
    return bool(int(row["ua"] or 0) or int(row["pa"] or 0))


def _table_ready(conn) -> bool:
    return table_exists(conn, "support_tickets") and table_exists(conn, "support_messages")


def create_ticket(player_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    subject = _norm_text(payload.get("subject"), 120)
    message = _norm_text(payload.get("message"), 1200)
    category = str(payload.get("category") or "general").strip().lower()
    priority = str(payload.get("priority") or "normal").strip().lower()
    if not subject:
        return _err("missing_subject")
    if not message:
        return _err("missing_message")
    if category not in {"general", "bug", "account", "balance", "report"}:
        category = "general"
    if priority not in {"low", "normal", "high"}:
        priority = "normal"

    conn = db()
    try:
        if not _table_ready(conn):
            return _err("support_not_ready")
        begin_write_transaction(conn)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO support_tickets
              (player_id, subject, category, priority, status, created_at, updated_at, last_message_at)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?);
            """,
            (int(player_id), subject, category, priority, now, now, now),
        )
        ticket_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO support_messages (ticket_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, 'player', ?, ?);
            """,
            (ticket_id, int(player_id), message, now),
        )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()

    return _ok({"ticket_id": ticket_id})


def _message_sender_name(m: Any, viewer_player_id: int | None) -> str:
    role = str(m["sender_role"] or "player")
    if role == "admin":
        return "Support"
    sender_id = int(m["sender_id"]) if m["sender_id"] is not None else None
    if viewer_player_id is not None and sender_id == int(viewer_player_id):
        return "Du"
    return str(m["sender_name"] or "Spieler")


def _fetch_ticket_messages(cur: Any, ticket_id: int, viewer_player_id: int | None) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT m.id, m.sender_id, m.sender_role, m.message, m.created_at, p.name AS sender_name
        FROM support_messages m
        LEFT JOIN players p ON p.id = m.sender_id
        WHERE m.ticket_id = ?
        ORDER BY m.id ASC
        LIMIT 60;
        """,
        (int(ticket_id),),
    )
    messages: list[dict[str, Any]] = []
    for m in cur.fetchall():
        role = str(m["sender_role"] or "player")
        messages.append(
            {
                "id": int(m["id"]),
                "sender_id": int(m["sender_id"]) if m["sender_id"] is not None else None,
                "sender_role": role,
                "sender_name": _message_sender_name(m, viewer_player_id),
                "message": str(m["message"] or ""),
                "created_at": int(m["created_at"] or 0),
            }
        )
    return messages


def _ticket_row_to_dict(row: Any, messages: list[dict[str, Any]], *, player_name: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": int(row["id"]),
        "player_id": int(row["player_id"]),
        "subject": str(row["subject"] or ""),
        "category": str(row["category"] or "general"),
        "category_label": _category_label(str(row["category"] or "general")),
        "priority": str(row["priority"] or "normal"),
        "priority_label": _priority_label(str(row["priority"] or "normal")),
        "status": str(row["status"] or "open"),
        "status_label": _ticket_status_label(str(row["status"] or "open")),
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
        "last_message_at": int(row["last_message_at"] or 0),
        "messages": messages,
    }
    if player_name is not None:
        out["player_name"] = player_name
    return out


def list_tickets(player_id: int) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("support_not_ready")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT t.id, t.player_id, t.subject, t.category, t.priority, t.status,
                   t.created_at, t.updated_at, t.last_message_at
            FROM support_tickets t
            WHERE t.player_id = ?
            ORDER BY t.last_message_at DESC, t.id DESC
            LIMIT 100;
            """,
            (int(player_id),),
        )
        tickets = []
        for row in cur.fetchall():
            ticket_id = int(row["id"])
            messages = _fetch_ticket_messages(cur, ticket_id, int(player_id))
            tickets.append(_ticket_row_to_dict(row, messages))
        return _ok({"tickets": tickets})
    finally:
        conn.close()


def list_all_tickets(admin_id: int, *, status: str | None = None) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("support_not_ready")
        if not _is_admin(int(admin_id), conn):
            return _err("forbidden")
        cur = conn.cursor()
        status_filter = str(status or "").strip().lower()
        if status_filter and status_filter not in {"open", "in_progress", "closed"}:
            status_filter = ""
        if status_filter:
            cur.execute(
                """
                SELECT t.id, t.player_id, t.subject, t.category, t.priority, t.status,
                       t.created_at, t.updated_at, t.last_message_at, p.name AS player_name
                FROM support_tickets t
                LEFT JOIN players p ON p.id = t.player_id
                WHERE t.status = ?
                ORDER BY t.last_message_at DESC, t.id DESC
                LIMIT 200;
                """,
                (status_filter,),
            )
        else:
            cur.execute(
                """
                SELECT t.id, t.player_id, t.subject, t.category, t.priority, t.status,
                       t.created_at, t.updated_at, t.last_message_at, p.name AS player_name
                FROM support_tickets t
                LEFT JOIN players p ON p.id = t.player_id
                ORDER BY t.last_message_at DESC, t.id DESC
                LIMIT 200;
                """
            )
        tickets = []
        for row in cur.fetchall():
            ticket_id = int(row["id"])
            messages = _fetch_ticket_messages(cur, ticket_id, None)
            tickets.append(
                _ticket_row_to_dict(
                    row,
                    messages,
                    player_name=str(row["player_name"] or f"Spieler #{row['player_id']}"),
                )
            )
        return _ok({"tickets": tickets})
    finally:
        conn.close()


def reply_ticket(player_id: int, ticket_id: int, message: str) -> dict[str, Any]:
    msg = _norm_text(message, 1200)
    if not msg:
        return _err("missing_message")
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("support_not_ready")
        cur = conn.cursor()
        cur.execute(
            "SELECT id, player_id, status FROM support_tickets WHERE id = ? LIMIT 1;",
            (int(ticket_id),),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found")
        owner_id = int(row["player_id"])
        if owner_id != int(player_id):
            return _err("forbidden")
        now = _now()
        begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO support_messages (ticket_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, 'player', ?, ?);
            """,
            (int(ticket_id), int(player_id), msg, now),
        )
        conn.execute(
            """
            UPDATE support_tickets
            SET status = CASE WHEN status = 'closed' THEN 'open' ELSE status END,
                updated_at = ?, last_message_at = ?
            WHERE id = ?;
            """,
            (now, now, int(ticket_id)),
        )
        commit(conn)
        return _ok({"ticket_id": int(ticket_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def admin_reply_ticket(admin_id: int, ticket_id: int, message: str) -> dict[str, Any]:
    msg = _norm_text(message, 1200)
    if not msg:
        return _err("missing_message")
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("support_not_ready")
        if not _is_admin(int(admin_id), conn):
            return _err("forbidden")
        cur = conn.cursor()
        cur.execute(
            "SELECT id, status FROM support_tickets WHERE id = ? LIMIT 1;",
            (int(ticket_id),),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found")
        now = _now()
        begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO support_messages (ticket_id, sender_id, sender_role, message, created_at)
            VALUES (?, ?, 'admin', ?, ?);
            """,
            (int(ticket_id), int(admin_id), msg, now),
        )
        conn.execute(
            """
            UPDATE support_tickets
            SET status = CASE WHEN status = 'closed' THEN 'open' WHEN status = 'open' THEN 'in_progress' ELSE status END,
                updated_at = ?, last_message_at = ?
            WHERE id = ?;
            """,
            (now, now, int(ticket_id)),
        )
        commit(conn)
        return _ok({"ticket_id": int(ticket_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def change_ticket_status(player_id: int, ticket_id: int, status: str) -> dict[str, Any]:
    next_status = str(status or "").strip().lower()
    if next_status not in {"open", "in_progress", "closed"}:
        return _err("invalid_status")
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("support_not_ready")
        cur = conn.cursor()
        cur.execute(
            "SELECT id, player_id FROM support_tickets WHERE id = ? LIMIT 1;",
            (int(ticket_id),),
        )
        row = cur.fetchone()
        if not row:
            return _err("not_found")
        is_admin = _is_admin(int(player_id), conn)
        is_owner = int(row["player_id"]) == int(player_id)
        if not (is_admin or is_owner):
            return _err("forbidden")
        if is_owner and not is_admin and next_status != "closed":
            return _err("forbidden")
        begin_write_transaction(conn)
        now = _now()
        conn.execute(
            """
            UPDATE support_tickets
            SET status = ?, updated_at = ?, last_message_at = ?
            WHERE id = ?;
            """,
            (next_status, now, now, int(ticket_id)),
        )
        if is_admin:
            conn.execute(
                """
                INSERT INTO support_messages (ticket_id, sender_id, sender_role, message, created_at)
                VALUES (?, ?, 'admin', ?, ?);
                """,
                (
                    int(ticket_id),
                    int(player_id),
                    f"Status geaendert auf: {_ticket_status_label(next_status)}",
                    now,
                ),
            )
        commit(conn)
        return _ok({"ticket_id": int(ticket_id), "status": next_status})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()
