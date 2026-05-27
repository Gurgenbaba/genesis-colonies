"""
Genesis TChat – multiplayer chat service (rooms, whisper, alliance, moderation hooks).
"""

from __future__ import annotations

import html
import re
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from markupsafe import escape

from .alliance import get_player_alliance
from .db import db, begin_write_transaction, commit, rollback, table_exists
from .models import load_player

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_MESSAGE_LEN = 500
RATE_LIMIT_COUNT = 5
RATE_LIMIT_WINDOW_SEC = 10.0
MESSAGE_FETCH_LIMIT = 100

ROOM_GLOBAL = "global"
ROOM_SYSTEM = "system"
ROOM_ADMIN = "admin"

_rate_buckets: Dict[int, Deque[float]] = defaultdict(deque)

_MENTION_RE = re.compile(r"@([A-Za-z0-9_\-\.]{2,32})")


def _now() -> int:
    return int(time.time())


def _json_error(key: str) -> Dict[str, Any]:
    return {"ok": False, "error": key, "data": None}


def _json_ok(data: Any) -> Dict[str, Any]:
    return {"ok": True, "error": None, "data": data}


# ---------------------------------------------------------------------------
# Rate limit (in-process; swap for Redis later)
# ---------------------------------------------------------------------------

def check_rate_limit(player_id: int) -> bool:
    """Return True if allowed, False if rate limited."""
    now = time.time()
    bucket = _rate_buckets[int(player_id)]
    while bucket and bucket[0] < now - RATE_LIMIT_WINDOW_SEC:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_COUNT:
        return False
    bucket.append(now)
    return True


def reset_rate_limits() -> None:
    _rate_buckets.clear()


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def normalize_body(raw: str) -> str:
    s = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def render_message_body(body: str, viewer_id: Optional[int] = None, viewer_name: Optional[str] = None) -> str:
    """
    Escape all HTML, highlight @mentions safely (plain escaped text + span wrappers).
    Returns HTML string safe for insertion via innerHTML in controlled renderer.
    """
    text = escape(body)
    viewer_name_l = (viewer_name or "").strip().lower()

    def _repl(m: re.Match) -> str:
        name = m.group(1)
        cls = "gc-chat-mention"
        if viewer_name_l and name.lower() == viewer_name_l:
            cls += " gc-chat-mention-self"
        return f'<span class="{cls}">@{escape(name)}</span>'

    return _MENTION_RE.sub(_repl, text)


# ---------------------------------------------------------------------------
# Room resolution
# ---------------------------------------------------------------------------

def _get_room_by_id(conn, room_id: int) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_rooms WHERE id = ? AND is_active = 1 LIMIT 1;", (int(room_id),))
    row = cur.fetchone()
    return dict(row) if row else None


def _get_room_by_id_any(conn, room_id: int) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_rooms WHERE id = ? LIMIT 1;", (int(room_id),))
    row = cur.fetchone()
    return dict(row) if row else None


def _get_room_by_key(conn, room_key: str) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_rooms WHERE room_key = ? AND is_active = 1 LIMIT 1;", (str(room_key),))
    row = cur.fetchone()
    return dict(row) if row else None


def ensure_global_rooms(conn) -> None:
    now = _now()
    for key, rtype, title, is_system, is_private in (
        (ROOM_GLOBAL, "global", "Global", 0, 0),
        (ROOM_SYSTEM, "system", "System", 1, 0),
        (ROOM_ADMIN, "admin", "Admin", 0, 1),
    ):
        conn.execute(
            """
            INSERT OR IGNORE INTO chat_rooms
                (room_key, room_type, title, is_private, is_system, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?);
            """,
            (key, rtype, title, is_private, is_system, now, now),
        )


def ensure_alliance_room(alliance_id: int, tag: str, conn) -> Dict[str, Any]:
    room_key = f"alliance:{int(alliance_id)}"
    existing = _get_room_by_key(conn, room_key)
    if existing:
        return existing
    now = _now()
    title = f"[{tag}] Alliance"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO chat_rooms
            (room_key, room_type, title, alliance_id, is_private, is_system, is_active, created_at, updated_at)
        VALUES (?, 'alliance', ?, ?, 1, 0, 1, ?, ?);
        """,
        (room_key, title, int(alliance_id), now, now),
    )
    return dict(_get_room_by_id(conn, int(cur.lastrowid)) or {})


def dm_room_key(a: int, b: int) -> str:
    x, y = sorted((int(a), int(b)))
    return f"dm:{x}:{y}"


def get_or_create_dm_room(player_a: int, player_b: int, conn) -> Dict[str, Any]:
    if player_a == player_b:
        raise ValueError("cannot_dm_self")
    key = dm_room_key(player_a, player_b)
    room = _get_room_by_key(conn, key)
    now = _now()
    if not room:
        cur = conn.cursor()
        pa = load_player(int(player_a), conn=conn)
        pb = load_player(int(player_b), conn=conn)
        title = f"DM: {pa.get('name', player_a)} & {pb.get('name', player_b)}"
        cur.execute(
            """
            INSERT INTO chat_rooms
                (room_key, room_type, title, is_private, is_system, is_active, created_by, created_at, updated_at)
            VALUES (?, 'dm', ?, 1, 0, 1, ?, ?, ?);
            """,
            (key, title, int(player_a), now, now),
        )
        room_id = int(cur.lastrowid)
        for pid in (int(player_a), int(player_b)):
            conn.execute(
                """
                INSERT OR IGNORE INTO chat_room_members (room_id, player_id, role, joined_at)
                VALUES (?, ?, 'member', ?);
                """,
                (room_id, pid, now),
            )
        room = _get_room_by_id(conn, room_id)
    return room or {}


def create_custom_room(owner_id: int, title: str, conn) -> Dict[str, Any]:
    clean_title = normalize_body(title)
    if not clean_title:
        raise ValueError("invalid_room_title")
    now = _now()
    room_key = f"custom:{int(owner_id)}:{now}:{int(time.time() * 1000) % 100000}"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO chat_rooms
            (room_key, room_type, title, is_private, is_system, is_active, created_by, created_at, updated_at)
        VALUES (?, 'custom', ?, 1, 0, 1, ?, ?, ?);
        """,
        (room_key, clean_title[:64], int(owner_id), now, now),
    )
    room_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO chat_room_members (room_id, player_id, role, joined_at)
        VALUES (?, ?, 'owner', ?);
        """,
        (room_id, int(owner_id), now),
    )
    return dict(_get_room_by_id(conn, room_id) or {})


def _member_role(room_id: int, player_id: int, conn) -> Optional[str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT role FROM chat_room_members
        WHERE room_id = ? AND player_id = ?
        LIMIT 1;
        """,
        (int(room_id), int(player_id)),
    )
    row = cur.fetchone()
    if not row:
        return None
    return str(row["role"]) if row["role"] else None


def _can_manage_custom_room(actor_id: int, room: Dict[str, Any], conn) -> bool:
    if is_admin(actor_id, conn):
        return True
    if str(room.get("room_type") or "") != "custom":
        return False
    role = _member_role(int(room["id"]), int(actor_id), conn)
    return role == "owner"


def add_custom_room_member(actor_id: int, room_id: int, target_player_id: int, conn) -> Optional[str]:
    room = _get_room_by_id(conn, int(room_id))
    if not room or str(room.get("room_type") or "") != "custom":
        return "room_not_found"
    if not _can_manage_custom_room(actor_id, room, conn):
        return "no_permission"
    target = load_player(int(target_player_id), conn=conn)
    if not target:
        return "player_not_found"
    now = _now()
    conn.execute(
        """
        INSERT INTO chat_room_members (room_id, player_id, role, joined_at)
        VALUES (?, ?, 'member', ?)
        ON CONFLICT(room_id, player_id) DO NOTHING;
        """,
        (int(room_id), int(target_player_id), now),
    )
    return None


def remove_custom_room_member(actor_id: int, room_id: int, target_player_id: int, conn) -> Optional[str]:
    room = _get_room_by_id(conn, int(room_id))
    if not room or str(room.get("room_type") or "") != "custom":
        return "room_not_found"
    if not _can_manage_custom_room(actor_id, room, conn):
        return "no_permission"
    role = _member_role(int(room_id), int(target_player_id), conn)
    if role is None:
        return "not_found"
    if role == "owner":
        return "cannot_remove_owner"
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM chat_room_members
        WHERE room_id = ? AND player_id = ?;
        """,
        (int(room_id), int(target_player_id)),
    )
    if cur.rowcount == 0:
        return "not_found"
    return None


def find_player_by_name(name: str, conn) -> Optional[Dict[str, Any]]:
    from .player_display import commander_name_candidates

    q = str(name or "").strip()
    if len(q) < 2:
        return None
    cur = conn.cursor()

    for candidate in commander_name_candidates(q):
        if len(candidate) < 2:
            continue
        cur.execute(
            """
            SELECT id, name FROM players
            WHERE LOWER(name) = LOWER(?)
            LIMIT 1;
            """,
            (candidate,),
        )
        row = cur.fetchone()
        if row:
            return dict(row)

    cur.execute(
        """
        SELECT id, name FROM players
        WHERE name LIKE ? ESCAPE '\\'
        LIMIT 5;
        """,
        (q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return dict(rows[0])
    return None


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------

def is_admin(player_id: int, conn) -> bool:
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


def player_can_read_room(player_id: int, room: Dict[str, Any], conn) -> bool:
    if is_player_chat_banned(player_id, conn):
        return False
    rtype = str(room.get("room_type") or "")
    if rtype in ("global", "system"):
        return True
    if rtype == "admin":
        return is_admin(player_id, conn)
    if rtype == "alliance":
        aid = room.get("alliance_id")
        if aid is None:
            return False
        ally = get_player_alliance(player_id, conn=conn)
        return bool(ally and int(ally["alliance_id"]) == int(aid))
    if rtype == "dm":
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM chat_room_members
            WHERE room_id = ? AND player_id = ? LIMIT 1;
            """,
            (int(room["id"]), int(player_id)),
        )
        return cur.fetchone() is not None
    if rtype == "custom":
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM chat_room_members
            WHERE room_id = ? AND player_id = ? LIMIT 1;
            """,
            (int(room["id"]), int(player_id)),
        )
        return cur.fetchone() is not None
    return False


def player_can_write_room(player_id: int, room: Dict[str, Any], conn) -> bool:
    if is_player_chat_banned(player_id, conn):
        return False
    if not player_can_read_room(player_id, room, conn):
        return False
    rtype = str(room.get("room_type") or "")
    if rtype == "system":
        return is_admin(player_id, conn)
    if is_player_muted(player_id, room, conn):
        return False
    return True


def is_player_muted(player_id: int, room: Dict[str, Any], conn) -> bool:
    now = _now()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM chat_mutes
        WHERE player_id = ?
          AND muted_until > ?
          AND (
            scope = 'global'
            OR (scope = 'room' AND room_id = ?)
            OR (scope = 'alliance' AND ? = 'alliance')
            OR scope = 'dm'
          )
        LIMIT 1;
        """,
        (int(player_id), now, int(room["id"]), str(room.get("room_type") or "")),
    )
    return cur.fetchone() is not None


def is_player_chat_banned(player_id: int, conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1
        FROM chat_bans
        WHERE player_id = ? AND is_active = 1
        LIMIT 1;
        """,
        (int(player_id),),
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Mute helpers
# ---------------------------------------------------------------------------

def mute_player(
    player_id: int,
    muted_by: int,
    scope: str,
    muted_until: int,
    *,
    room_id: Optional[int] = None,
    reason: Optional[str] = None,
    conn=None,
) -> None:
    own = conn is None
    if own:
        conn = db()
    try:
        if own:
            begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO chat_mutes (player_id, muted_by, scope, room_id, reason, muted_until, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (int(player_id), int(muted_by), str(scope), room_id, reason, int(muted_until), _now()),
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


# ---------------------------------------------------------------------------
# Message serialization
# ---------------------------------------------------------------------------

def _sender_alliance_tag(sender_id: Optional[int], conn) -> str:
    if not sender_id:
        return ""
    ally = get_player_alliance(int(sender_id), conn=conn)
    return str(ally.get("tag") or "") if ally else ""


def serialize_message(row: Dict[str, Any], viewer_id: int, viewer_name: str, conn) -> Dict[str, Any]:
    body = str(row.get("body") or "")
    deleted = row.get("deleted_at") is not None
    if deleted:
        body = ""
    return {
        "id": int(row["id"]),
        "room_id": int(row["room_id"]),
        "sender_id": int(row["sender_id"]) if row.get("sender_id") is not None else None,
        "sender_name": str(row.get("sender_name") or "System"),
        "sender_alliance_tag": str(row.get("sender_alliance_tag") or ""),
        "target_user_id": int(row["target_user_id"]) if row.get("target_user_id") is not None else None,
        "alliance_id": int(row["alliance_id"]) if row.get("alliance_id") is not None else None,
        "message_type": str(row.get("message_type") or "normal"),
        "message": body if not deleted else "",
        "body_rendered": render_message_body(body, viewer_id, viewer_name) if body and not deleted else "",
        "created_at": int(row["created_at"]),
        "edited_at": int(row["edited_at"]) if row.get("edited_at") else None,
        "deleted_at": int(row["deleted_at"]) if row.get("deleted_at") else None,
        "is_deleted": deleted,
    }


def fetch_messages(
    player_id: int,
    room_id: int,
    after_id: int = 0,
    limit: int = MESSAGE_FETCH_LIMIT,
    conn=None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    own = conn is None
    if own:
        conn = db()
    try:
        room = _get_room_by_id(conn, int(room_id))
        if not room:
            return [], "room_not_found"
        if not player_can_read_room(player_id, room, conn):
            return [], "no_permission"

        viewer = load_player(player_id, conn=conn) or {}
        viewer_name = str(viewer.get("name") or "")

        cur = conn.cursor()
        if after_id > 0:
            cur.execute(
                """
                SELECT m.*, p.name AS sender_name
                FROM chat_messages m
                LEFT JOIN players p ON p.id = m.sender_id
                WHERE m.room_id = ? AND m.id > ?
                ORDER BY m.id ASC
                LIMIT ?;
                """,
                (int(room_id), int(after_id), int(limit)),
            )
        else:
            cur.execute(
                """
                SELECT m.*, p.name AS sender_name
                FROM chat_messages m
                LEFT JOIN players p ON p.id = m.sender_id
                WHERE m.room_id = ?
                ORDER BY m.id DESC
                LIMIT ?;
                """,
                (int(room_id), int(limit)),
            )
            rows = list(cur.fetchall())
            rows.reverse()
            out = []
            for r in rows:
                d = dict(r)
                d["sender_alliance_tag"] = _sender_alliance_tag(d.get("sender_id"), conn)
                out.append(serialize_message(d, player_id, viewer_name, conn))
            return out, None

        rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["sender_alliance_tag"] = _sender_alliance_tag(d.get("sender_id"), conn)
            out.append(serialize_message(d, player_id, viewer_name, conn))
        return out, None
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# Unread counts
# ---------------------------------------------------------------------------

def _unread_for_room(player_id: int, room_id: int, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT last_read_message_id FROM chat_room_members
        WHERE room_id = ? AND player_id = ? LIMIT 1;
        """,
        (int(room_id), int(player_id)),
    )
    mem = cur.fetchone()
    last_read = int(mem["last_read_message_id"] or 0) if mem else 0
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM chat_messages
        WHERE room_id = ? AND id > ? AND deleted_at IS NULL
          AND (sender_id IS NULL OR sender_id != ?);
        """,
        (int(room_id), last_read, int(player_id)),
    )
    return int(cur.fetchone()["c"] or 0)


def get_unread_counts(player_id: int, room_ids: List[int], conn) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for rid in room_ids:
        out[str(rid)] = _unread_for_room(player_id, rid, conn)
    return out


# ---------------------------------------------------------------------------
# UI state
# ---------------------------------------------------------------------------

def clamp_ui_state_values(state: Dict[str, Any]) -> Dict[str, Any]:
    """Clamp persisted panel geometry to safe bounds."""
    w = max(280, min(720, int(state.get("width") or 380)))
    h = max(320, min(720, int(state.get("height") or 480)))
    px = int(state.get("pos_x") or 0)
    py = int(state.get("pos_y") or 0)
    if px < 0:
        px = 0
    if py < 0:
        py = 0
    if px > 0:
        px = min(px, 4096)
    if py > 0:
        py = min(py, 4096)
    out = dict(state)
    out["width"] = w
    out["height"] = h
    out["pos_x"] = px
    out["pos_y"] = py
    return out


def get_user_state(player_id: int, conn) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM chat_user_state WHERE player_id = ? LIMIT 1;", (int(player_id),))
    row = cur.fetchone()
    if not row:
        return {
            "version": 1,
            "saved_at": 0,
            "is_open": False,
            "is_minimized": True,
            "active_room_id": None,
            "width": 380,
            "height": 480,
            "pos_x": 0,
            "pos_y": 0,
        }
    d = dict(row)
    return {
        "version": 1,
        "saved_at": int(d.get("updated_at") or 0),
        "is_open": bool(int(d.get("is_open") or 0)),
        "is_minimized": bool(int(d.get("is_minimized") or 1)),
        "active_room_id": int(d["active_room_id"]) if d.get("active_room_id") else None,
        "width": int(d.get("width") or 380),
        "height": int(d.get("height") or 480),
        "pos_x": int(d.get("pos_x") or 0),
        "pos_y": int(d.get("pos_y") or 0),
    }


def save_user_state(player_id: int, payload: Dict[str, Any], conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    now = _now()
    state = get_user_state(player_id, conn)
    state.update({k: payload[k] for k in payload if k in state})
    state = clamp_ui_state_values(state)
    try:
        if own:
            begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO chat_user_state
                (player_id, is_open, is_minimized, active_room_id, width, height, pos_x, pos_y, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                is_open = excluded.is_open,
                is_minimized = excluded.is_minimized,
                active_room_id = excluded.active_room_id,
                width = excluded.width,
                height = excluded.height,
                pos_x = excluded.pos_x,
                pos_y = excluded.pos_y,
                updated_at = excluded.updated_at;
            """,
            (
                int(player_id),
                1 if state.get("is_open") else 0,
                1 if state.get("is_minimized") else 0,
                state.get("active_room_id"),
                int(state.get("width") or 380),
                int(state.get("height") or 480),
                int(state.get("pos_x") or 0),
                int(state.get("pos_y") or 0),
                now,
            ),
        )
        if own:
            commit(conn)
        out = dict(state)
        out["version"] = 1
        out["saved_at"] = int(now)
        return out
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


def mark_room_read(player_id: int, room_id: int, last_read_message_id: int, conn=None) -> Optional[str]:
    own = conn is None
    if own:
        conn = db()
    try:
        room = _get_room_by_id(conn, int(room_id))
        if not room:
            return "room_not_found"
        if not player_can_read_room(player_id, room, conn):
            return "no_permission"
        now = _now()
        rtype = str(room.get("room_type") or "")
        if rtype in ("global", "system", "alliance", "admin"):
            conn.execute(
                """
                INSERT INTO chat_room_members (room_id, player_id, role, last_read_message_id, joined_at)
                VALUES (?, ?, 'member', ?, ?)
                ON CONFLICT(room_id, player_id) DO UPDATE SET
                    last_read_message_id = MAX(COALESCE(chat_room_members.last_read_message_id, 0), excluded.last_read_message_id);
                """,
                (int(room_id), int(player_id), int(last_read_message_id), now),
            )
        else:
            conn.execute(
                """
                UPDATE chat_room_members
                SET last_read_message_id = MAX(COALESCE(last_read_message_id, 0), ?)
                WHERE room_id = ? AND player_id = ?;
                """,
                (int(last_read_message_id), int(room_id), int(player_id)),
            )
        if own:
            commit(conn)
        return None
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
# Room listing
# ---------------------------------------------------------------------------

def list_rooms_for_player(player_id: int, conn=None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        ensure_global_rooms(conn)

        if is_player_chat_banned(player_id, conn):
            return _json_error("chat_banned")
        rooms: List[Dict[str, Any]] = []

        for key in (ROOM_GLOBAL, ROOM_SYSTEM):
            r = _get_room_by_key(conn, key)
            if r and player_can_read_room(player_id, r, conn):
                rooms.append(_room_summary(r))

        ally = get_player_alliance(player_id, conn=conn)
        if ally:
            ar = ensure_alliance_room(int(ally["alliance_id"]), str(ally["tag"]), conn)
            if ar:
                rooms.append(_room_summary(ar, extra={"alliance_tag": ally["tag"]}))
        else:
            rooms.append({
                "id": None,
                "room_key": "alliance:disabled",
                "room_type": "alliance",
                "title_key": "chat_alliance",
                "disabled": True,
            })

        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.* FROM chat_rooms r
            JOIN chat_room_members m ON m.room_id = r.id
            WHERE m.player_id = ? AND r.room_type IN ('dm', 'custom') AND r.is_active = 1
            ORDER BY r.updated_at DESC;
            """,
            (int(player_id),),
        )
        for row in cur.fetchall():
            r = dict(row)
            if player_can_read_room(player_id, r, conn):
                extra: Dict[str, Any] = {}
                if str(r.get("room_type") or "") == "dm":
                    extra["dm_partner_name"] = _dm_partner_name(player_id, r, conn)
                role = _member_role(int(r["id"]), int(player_id), conn)
                if role:
                    extra["member_role"] = role
                rooms.append(_room_summary(r, extra=extra))

        if is_admin(player_id, conn):
            adm = _get_room_by_key(conn, ROOM_ADMIN)
            if adm:
                rooms.append(_room_summary(adm))

        return rooms
    finally:
        if own:
            conn.close()


def _dm_partner_name(player_id: int, room: Dict[str, Any], conn) -> str:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.name FROM chat_room_members m
        JOIN players p ON p.id = m.player_id
        WHERE m.room_id = ? AND m.player_id != ? LIMIT 1;
        """,
        (int(room["id"]), int(player_id)),
    )
    row = cur.fetchone()
    return str(row["name"]) if row else "DM"


def _room_summary(room: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = {
        "id": int(room["id"]),
        "room_key": str(room["room_key"]),
        "room_type": str(room["room_type"]),
        "title": str(room.get("title") or ""),
        "disabled": False,
    }
    if extra:
        d.update(extra)
    return d


# ---------------------------------------------------------------------------
# Whisper state (/r)
# ---------------------------------------------------------------------------

def set_whisper_partner(player_id: int, partner_id: int, dm_room_id: Optional[int], conn) -> None:
    conn.execute(
        """
        INSERT INTO chat_whisper_state (player_id, last_partner_id, last_dm_room_id, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            last_partner_id = excluded.last_partner_id,
            last_dm_room_id = excluded.last_dm_room_id,
            updated_at = excluded.updated_at;
        """,
        (int(player_id), int(partner_id), dm_room_id, _now()),
    )


def get_whisper_partner(player_id: int, conn) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM chat_whisper_state WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------

def resolve_player_name_prefix(name_prefix: str, conn) -> Optional[Dict[str, Any]]:
    """
    Match player by full name or longest prefix (supports names with spaces).
    """
    q = str(name_prefix or "").strip()
    if not q:
        return None
    hit = find_player_by_name(q, conn)
    if hit:
        return hit
    words = q.split()
    for i in range(len(words), 0, -1):
        candidate = " ".join(words[:i])
        hit = find_player_by_name(candidate, conn)
        if hit:
            return hit
    return None


def parse_whisper_args(rest: str, conn) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Split /w target (possibly multi-word) and message body."""
    text = str(rest or "").strip()
    if not text:
        return None, None
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 1:
            name = text[1:end]
            msg = text[end + 1 :].strip()
            if msg:
                return {"target_name": name, "message": msg}, None
            return None, "usage"
    words = text.split()
    for i in range(len(words), 0, -1):
        candidate = " ".join(words[:i])
        hit = find_player_by_name(candidate, conn)
        if hit:
            msg = " ".join(words[i:]).strip()
            if msg:
                return {"target_name": str(hit.get("name") or candidate), "message": msg}, None
            return None, "usage"
    return None, "usage"


def parse_slash_command(body: str, conn=None) -> Tuple[Optional[str], Dict[str, Any]]:
    """Return (command_name, args_dict) or (None, {}) for normal message."""
    if not body.startswith("/"):
        return None, {}
    parts = body[1:].split()
    if not parts:
        return None, {}
    cmd = parts[0].lower()
    rest = body[1 + len(parts[0]):].strip()
    if cmd in ("w", "whisper"):
        if conn is None:
            conn = db()
            own = True
        else:
            own = False
        try:
            args, err = parse_whisper_args(rest, conn)
            if err or not args:
                return "whisper", {"error": "usage"}
            return "whisper", args
        finally:
            if own:
                conn.close()
    if cmd == "r":
        if not rest:
            return "reply", {"error": "usage"}
        return "reply", {"message": rest}
    if cmd in ("a", "alliance"):
        return "alliance", {"message": rest}
    if cmd in ("g", "global"):
        return "global", {"message": rest}
    if cmd == "me":
        return "me", {"action": rest}
    if cmd == "help":
        return "help", {}
    if cmd == "clear":
        return "clear", {}
    if cmd == "room":
        return "room", {"raw": rest}
    return None, {}


# ---------------------------------------------------------------------------
# Send message
# ---------------------------------------------------------------------------

def insert_message(
    conn,
    *,
    room_id: int,
    sender_id: Optional[int],
    body: str,
    message_type: str = "normal",
    target_user_id: Optional[int] = None,
    alliance_id: Optional[int] = None,
) -> Dict[str, Any]:
    now = _now()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO chat_messages
            (room_id, sender_id, target_user_id, alliance_id, message_type, body, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (int(room_id), sender_id, target_user_id, alliance_id, message_type, body, now),
    )
    msg_id = int(cur.lastrowid)
    conn.execute(
        "UPDATE chat_rooms SET updated_at = ? WHERE id = ?;",
        (now, int(room_id)),
    )
    cur.execute(
        """
        SELECT m.*, p.name AS sender_name
        FROM chat_messages m
        LEFT JOIN players p ON p.id = m.sender_id
        WHERE m.id = ? LIMIT 1;
        """,
        (msg_id,),
    )
    row = dict(cur.fetchone())
    row["sender_alliance_tag"] = _sender_alliance_tag(sender_id, conn)
    viewer = load_player(int(sender_id), conn=conn) if sender_id else {}
    return serialize_message(row, int(sender_id or 0), str(viewer.get("name") or ""), conn)


def send_chat_message(
    player_id: int,
    body: str,
    *,
    room_id: Optional[int] = None,
    command: Optional[str] = None,
) -> Dict[str, Any]:
    body = normalize_body(body)
    if not body:
        return _json_error("empty_message")

    if not check_rate_limit(player_id):
        return _json_error("rate_limited")

    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_global_rooms(conn)

        cmd_name, cmd_args = parse_slash_command(body, conn=conn)
        if command:
            cmd_name = command

        if cmd_name == "clear":
            return _json_ok({"client_only": True, "action": "clear"})

        if cmd_name == "help":
            return _json_ok({"client_only": True, "action": "help"})

        viewer = load_player(player_id, conn=conn) or {}
        viewer_name = str(viewer.get("name") or "")

        target_room: Optional[Dict[str, Any]] = None
        msg_type = "normal"
        target_uid: Optional[int] = None
        alliance_id: Optional[int] = None
        msg_body = body

        if cmd_name == "whisper":
            if cmd_args.get("error"):
                return _json_error("invalid_command")
            target = resolve_player_name_prefix(cmd_args.get("target_name", ""), conn)
            if not target:
                return _json_error("player_not_found")
            target_uid = int(target["id"])
            msg_body = normalize_body(cmd_args.get("message", ""))
            if not msg_body:
                return _json_error("empty_message")
            target_room = get_or_create_dm_room(player_id, target_uid, conn)
            msg_type = "whisper"
            set_whisper_partner(player_id, target_uid, int(target_room["id"]), conn)
            set_whisper_partner(target_uid, player_id, int(target_room["id"]), conn)

        elif cmd_name == "reply":
            if cmd_args.get("error"):
                return _json_error("invalid_command")
            ws = get_whisper_partner(player_id, conn)
            if not ws:
                return _json_error("no_whisper_target")
            partner_id = int(ws["last_partner_id"])
            target_room = get_or_create_dm_room(player_id, partner_id, conn)
            msg_body = normalize_body(cmd_args.get("message", ""))
            if not msg_body:
                return _json_error("empty_message")
            msg_type = "whisper"
            target_uid = partner_id

        elif cmd_name == "alliance":
            ally = get_player_alliance(player_id, conn=conn)
            if not ally:
                return _json_error("no_alliance")
            msg_body = normalize_body(cmd_args.get("message", ""))
            if not msg_body:
                return _json_error("empty_message")
            target_room = ensure_alliance_room(int(ally["alliance_id"]), str(ally["tag"]), conn)
            alliance_id = int(ally["alliance_id"])

        elif cmd_name == "global":
            msg_body = normalize_body(cmd_args.get("message", ""))
            if not msg_body:
                return _json_error("empty_message")
            target_room = _get_room_by_key(conn, ROOM_GLOBAL)

        elif cmd_name == "me":
            action = normalize_body(cmd_args.get("action", ""))
            if not action:
                return _json_error("empty_message")
            if len(action) > MAX_MESSAGE_LEN:
                action = action[:MAX_MESSAGE_LEN]
            msg_body = action
            msg_type = "action"
            if room_id:
                target_room = _get_room_by_id(conn, int(room_id))
            else:
                target_room = _get_room_by_key(conn, ROOM_GLOBAL)

        elif cmd_name == "room":
            raw = normalize_body(cmd_args.get("raw", ""))
            if not raw:
                return _json_error("invalid_command")
            parts = raw.split()
            sub = parts[0].lower()
            if sub == "create":
                title = raw[len(parts[0]):].strip()
                if not title:
                    return _json_error("invalid_room_title")
                target_room = create_custom_room(player_id, title, conn)
                msg_type = "system"
                msg_body = f"Raum erstellt: {target_room.get('title')}"
            elif sub in ("invite", "add"):
                if not room_id:
                    return _json_error("invalid_room")
                target_room = _get_room_by_id(conn, int(room_id))
                if not target_room or str(target_room.get("room_type") or "") != "custom":
                    return _json_error("no_permission")
                who = raw[len(parts[0]):].strip()
                target = resolve_player_name_prefix(who, conn)
                if not target:
                    return _json_error("player_not_found")
                err = add_custom_room_member(player_id, int(room_id), int(target["id"]), conn)
                if err:
                    return _json_error(err)
                msg_type = "system"
                msg_body = f"{target.get('name')} wurde eingeladen."
            elif sub in ("remove", "kick"):
                if not room_id:
                    return _json_error("invalid_room")
                target_room = _get_room_by_id(conn, int(room_id))
                if not target_room or str(target_room.get("room_type") or "") != "custom":
                    return _json_error("no_permission")
                who = raw[len(parts[0]):].strip()
                target = resolve_player_name_prefix(who, conn)
                if not target:
                    return _json_error("player_not_found")
                err = remove_custom_room_member(player_id, int(room_id), int(target["id"]), conn)
                if err:
                    return _json_error(err)
                msg_type = "system"
                msg_body = f"{target.get('name')} wurde entfernt."
            else:
                return _json_error("invalid_command")

        else:
            if len(body) > MAX_MESSAGE_LEN:
                return _json_error("message_too_long")
            if room_id:
                target_room = _get_room_by_id(conn, int(room_id))
            else:
                target_room = _get_room_by_key(conn, ROOM_GLOBAL)

        if not target_room:
            return _json_error("room_not_found")

        if len(msg_body) > MAX_MESSAGE_LEN:
            return _json_error("message_too_long")

        if not player_can_write_room(player_id, target_room, conn):
            if is_player_chat_banned(player_id, conn):
                return _json_error("chat_banned")
            if is_player_muted(player_id, target_room, conn):
                return _json_error("muted")
            return _json_error("no_permission")

        if msg_type == "action":
            msg_body = f"* {viewer_name} {msg_body}"

        msg = insert_message(
            conn,
            room_id=int(target_room["id"]),
            sender_id=player_id,
            body=msg_body,
            message_type=msg_type,
            target_user_id=target_uid,
            alliance_id=alliance_id,
        )

        commit(conn)
        return _json_ok({
            "message": msg,
            "room_id": int(target_room["id"]),
            "room_key": str(target_room["room_key"]),
        })
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bootstrap API payload
# ---------------------------------------------------------------------------

def open_dm_room(player_id: int, target_player_id: int) -> Dict[str, Any]:
    """Open or create a DM room with target player (no message required)."""
    if int(player_id) == int(target_player_id):
        return _json_error("cannot_whisper_self")

    conn = db()
    try:
        begin_write_transaction(conn)
        target = load_player(int(target_player_id), conn=conn)
        if not target:
            return _json_error("player_not_found")
        room = get_or_create_dm_room(int(player_id), int(target_player_id), conn)
        rid = int(room["id"])
        set_whisper_partner(int(player_id), int(target_player_id), rid, conn)
        set_whisper_partner(int(target_player_id), int(player_id), rid, conn)
        commit(conn)
        return _json_ok({
            "room_id": rid,
            "room_key": str(room.get("room_key") or ""),
            "target_name": str(target.get("name") or ""),
        })
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def admin_search_messages(admin_id: int, query: str, limit: int = 50) -> Dict[str, Any]:
    if not is_admin(admin_id, db()):
        return _json_error("no_permission")
    q = normalize_body(query)
    if len(q) < 2:
        return _json_ok({"messages": []})

    conn = db()
    try:
        cur = conn.cursor()
        like = f"%{q.replace('%', '')[:80]}%"
        cur.execute(
            """
            SELECT m.id, m.room_id, m.sender_id, m.message_type, m.body, m.created_at, m.deleted_at,
                   p.name AS sender_name, r.room_key, r.title
            FROM chat_messages m
            LEFT JOIN players p ON p.id = m.sender_id
            JOIN chat_rooms r ON r.id = m.room_id
            WHERE m.body LIKE ? ESCAPE '\\'
            ORDER BY m.id DESC
            LIMIT ?;
            """,
            (like, int(min(limit, 100))),
        )
        rows = []
        for row in cur.fetchall():
            d = dict(row)
            rows.append({
                "id": int(d["id"]),
                "room_id": int(d["room_id"]),
                "room_key": str(d.get("room_key") or ""),
                "room_title": str(d.get("title") or ""),
                "sender_id": int(d["sender_id"]) if d.get("sender_id") else None,
                "sender_name": str(d.get("sender_name") or "System"),
                "message_type": str(d.get("message_type") or "normal"),
                "message": "" if d.get("deleted_at") else str(d.get("body") or ""),
                "is_deleted": d.get("deleted_at") is not None,
                "created_at": int(d["created_at"]),
            })
        return _json_ok({"messages": rows})
    finally:
        conn.close()


def chat_bootstrap(player_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        if not table_exists(conn, "chat_rooms"):
            return _json_error("chat_not_ready")

        begin_write_transaction(conn)
        ensure_global_rooms(conn)
        commit(conn)

        player = load_player(player_id, conn=conn) or {}
        ally = get_player_alliance(player_id, conn=conn)
        rooms = list_rooms_for_player(player_id, conn=conn)
        room_ids = [int(r["id"]) for r in rooms if r.get("id")]
        unread = get_unread_counts(player_id, room_ids, conn)
        state = clamp_ui_state_values(get_user_state(player_id, conn))
        active_room_id = state.get("active_room_id")
        if active_room_id and int(active_room_id) not in room_ids:
            active_room_id = None
        if not active_room_id and room_ids:
            global_room = _get_room_by_key(conn, ROOM_GLOBAL)
            active_room_id = int(global_room["id"]) if global_room else room_ids[0]

        return _json_ok({
            "player": {
                "id": int(player_id),
                "name": str(player.get("name") or ""),
                "alliance": ally,
            },
            "rooms": rooms,
            "active_room_id": active_room_id,
            "unread": unread,
            "ui_state": state,
            "permissions": {
                "is_admin": is_admin(player_id, conn),
                "has_alliance": bool(ally),
                "can_post_system": is_admin(player_id, conn),
                "chat_banned": is_player_chat_banned(player_id, conn),
            },
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Admin operations
# ---------------------------------------------------------------------------

def admin_delete_message(admin_id: int, message_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        if not is_admin(admin_id, conn):
            return _json_error("no_permission")
        begin_write_transaction(conn)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE chat_messages
            SET deleted_at = ?, deleted_by = ?, body = ''
            WHERE id = ? AND deleted_at IS NULL;
            """,
            (now, int(admin_id), int(message_id)),
        )
        if cur.rowcount == 0:
            rollback(conn)
            return _json_error("not_found")
        commit(conn)
        return _json_ok({"message_id": int(message_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def admin_system_notice(admin_id: int, body: str) -> Dict[str, Any]:
    body = normalize_body(body)
    if not body:
        return _json_error("empty_message")
    conn = db()
    try:
        if not is_admin(admin_id, conn):
            return _json_error("no_permission")
        begin_write_transaction(conn)
        ensure_global_rooms(conn)
        room = _get_room_by_key(conn, ROOM_SYSTEM)
        if not room:
            return _json_error("room_not_found")
        msg = insert_message(
            conn,
            room_id=int(room["id"]),
            sender_id=None,
            body=body,
            message_type="system",
        )
        commit(conn)
        return _json_ok({"message": msg})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def admin_mute_player(
    admin_id: int,
    target_player_id: int,
    scope: str,
    muted_until: int,
    *,
    room_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    if not is_admin(admin_id, db()):
        return _json_error("no_permission")
    mute_player(
        target_player_id,
        admin_id,
        scope,
        muted_until,
        room_id=room_id,
        reason=reason,
    )
    return _json_ok({"player_id": int(target_player_id), "muted_until": int(muted_until)})


def admin_unmute_player(admin_id: int, target_player_id: int, scope: Optional[str] = None) -> Dict[str, Any]:
    conn = db()
    try:
        if not is_admin(admin_id, conn):
            return _json_error("no_permission")
        begin_write_transaction(conn)
        if scope:
            conn.execute(
                "DELETE FROM chat_mutes WHERE player_id = ? AND scope = ?;",
                (int(target_player_id), str(scope)),
            )
        else:
            conn.execute("DELETE FROM chat_mutes WHERE player_id = ?;", (int(target_player_id),))
        commit(conn)
        return _json_ok({"player_id": int(target_player_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def admin_chat_ban_player(admin_id: int, target_player_id: int, reason: Optional[str] = None) -> Dict[str, Any]:
    conn = db()
    try:
        if not is_admin(admin_id, conn):
            return _json_error("no_permission")
        if not load_player(int(target_player_id), conn=conn):
            return _json_error("player_not_found")
        begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO chat_bans (player_id, banned_by, reason, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                banned_by = excluded.banned_by,
                reason = excluded.reason,
                is_active = 1,
                updated_at = excluded.updated_at;
            """,
            (int(target_player_id), int(admin_id), (reason or "").strip()[:200], _now(), _now()),
        )
        commit(conn)
        return _json_ok({"player_id": int(target_player_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def admin_chat_unban_player(admin_id: int, target_player_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        if not is_admin(admin_id, conn):
            return _json_error("no_permission")
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE chat_bans
            SET is_active = 0, updated_at = ?
            WHERE player_id = ?;
            """,
            (_now(), int(target_player_id)),
        )
        commit(conn)
        return _json_ok({"player_id": int(target_player_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def create_player_custom_room(player_id: int, title: str) -> Dict[str, Any]:
    conn = db()
    try:
        begin_write_transaction(conn)
        room = create_custom_room(int(player_id), title, conn)
        commit(conn)
        return _json_ok({"room": _room_summary(room), "room_id": int(room["id"])})
    except ValueError:
        rollback(conn)
        return _json_error("invalid_room_title")
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def invite_player_to_custom_room(player_id: int, room_id: int, target_player_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        begin_write_transaction(conn)
        err = add_custom_room_member(int(player_id), int(room_id), int(target_player_id), conn)
        if err:
            rollback(conn)
            return _json_error(err)
        room = _get_room_by_id(conn, int(room_id))
        if not room:
            rollback(conn)
            return _json_error("room_not_found")
        commit(conn)
        return _json_ok({"room_id": int(room_id), "room": _room_summary(room)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def remove_player_from_custom_room(player_id: int, room_id: int, target_player_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        begin_write_transaction(conn)
        err = remove_custom_room_member(int(player_id), int(room_id), int(target_player_id), conn)
        if err:
            rollback(conn)
            return _json_error(err)
        commit(conn)
        return _json_ok({"room_id": int(room_id), "player_id": int(target_player_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def delete_custom_room(player_id: int, room_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        begin_write_transaction(conn)
        room = _get_room_by_id_any(conn, int(room_id))
        if not room or str(room.get("room_type") or "") != "custom":
            rollback(conn)
            return _json_error("room_not_found")
        if int(room.get("is_active") or 0) == 0:
            commit(conn)
            return _json_ok({"room_id": int(room_id), "already_deleted": True})
        if not _can_manage_custom_room(int(player_id), room, conn):
            rollback(conn)
            return _json_error("no_permission")
        conn.execute(
            """
            UPDATE chat_rooms
            SET is_active = 0, updated_at = ?
            WHERE id = ?;
            """,
            (_now(), int(room_id)),
        )
        commit(conn)
        return _json_ok({"room_id": int(room_id)})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def leave_custom_room(player_id: int, room_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        begin_write_transaction(conn)
        room = _get_room_by_id(conn, int(room_id))
        if not room or str(room.get("room_type") or "") != "custom":
            rollback(conn)
            return _json_error("room_not_found")
        role = _member_role(int(room_id), int(player_id), conn)
        if not role:
            rollback(conn)
            return _json_error("no_permission")
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM chat_room_members WHERE room_id = ?;",
            (int(room_id),),
        )
        member_count = int(cur.fetchone()["c"] or 0)
        if role == "owner":
            if member_count > 1:
                rollback(conn)
                return _json_error("owner_cannot_leave_room")
            conn.execute(
                "UPDATE chat_rooms SET is_active = 0, updated_at = ? WHERE id = ?;",
                (_now(), int(room_id)),
            )
            commit(conn)
            return _json_ok({"room_id": int(room_id), "deleted_on_leave": True})

        conn.execute(
            "DELETE FROM chat_room_members WHERE room_id = ? AND player_id = ?;",
            (int(room_id), int(player_id)),
        )
        commit(conn)
        return _json_ok({"room_id": int(room_id), "left": True})
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def list_custom_room_members(player_id: int, room_id: int) -> Dict[str, Any]:
    conn = db()
    try:
        room = _get_room_by_id(conn, int(room_id))
        if not room or str(room.get("room_type") or "") != "custom":
            return _json_error("room_not_found")
        if not player_can_read_room(int(player_id), room, conn):
            return _json_error("no_permission")
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.player_id, m.role, p.name
            FROM chat_room_members m
            JOIN players p ON p.id = m.player_id
            WHERE m.room_id = ?
            ORDER BY CASE WHEN m.role = 'owner' THEN 0 ELSE 1 END, LOWER(p.name) ASC;
            """,
            (int(room_id),),
        )
        members = []
        for row in cur.fetchall():
            pid = int(row["player_id"])
            members.append(
                {
                    "player_id": pid,
                    "name": str(row["name"] or ""),
                    "role": str(row["role"] or "member"),
                    "is_admin": is_admin(pid, conn),
                }
            )
        can_manage = _can_manage_custom_room(int(player_id), room, conn)
        return _json_ok(
            {
                "room_id": int(room_id),
                "members": members,
                "can_manage": bool(can_manage),
                "can_leave": _member_role(int(room_id), int(player_id), conn) in ("member", "moderator"),
                "ownership_transfer_supported": False,
            }
        )
    finally:
        conn.close()


def search_players_for_autocomplete(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    q = str(query or "").strip()
    if len(q) < 1:
        return []
    conn = db()
    try:
        cur = conn.cursor()
        like = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cur.execute(
            """
            SELECT id, name FROM players
            WHERE name LIKE ? ESCAPE '\\'
            ORDER BY name ASC
            LIMIT ?;
            """,
            (like, int(limit)),
        )
        return [{"id": int(r["id"]), "name": str(r["name"])} for r in cur.fetchall()]
    finally:
        conn.close()
