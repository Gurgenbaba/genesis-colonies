from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

from .db import begin_write_transaction, commit, db, in_transaction, rollback, table_exists

_MESSAGE_COMMANDER_PREFIX = "Commander "

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


def _message_recipient_name_candidates(name: str) -> list[str]:
    """Distinct stored-name variants tried for player-mail recipient lookup."""
    q = str(name or "").strip()
    if not q:
        return []
    seen: set[str] = set()
    ordered: list[str] = []

    def add(value: str) -> None:
        v = str(value or "").strip()
        key = v.lower()
        if len(v) < 2 or key in seen:
            return
        seen.add(key)
        ordered.append(v)

    add(q)
    lower = q.lower()
    prefix_lower = _MESSAGE_COMMANDER_PREFIX.lower()
    if lower.startswith(prefix_lower):
        add(q[len(_MESSAGE_COMMANDER_PREFIX) :].strip())
    else:
        add(f"{_MESSAGE_COMMANDER_PREFIX}{q}")
    return ordered


def resolve_message_recipient(name: str | None, conn) -> tuple[dict[str, Any] | None, str | None]:
    """
    Resolve a player-mail recipient by stored player name.

    Accepts the exact stored name or the suffix without the Commander prefix.
    Returns ambiguous when multiple distinct players match (e.g. "Alpha" vs
    "Commander Alpha"). Never filters by score or ranking.
    """
    q = str(name or "").strip()
    if len(q) < 2:
        return None, "validation"

    cur = conn.cursor()
    matches: dict[int, dict[str, Any]] = {}

    for candidate in _message_recipient_name_candidates(q):
        cur.execute(
            """
            SELECT id, name FROM players
            WHERE LOWER(name) = LOWER(?)
            ORDER BY id ASC;
            """,
            (candidate,),
        )
        for row in cur.fetchall():
            pid = int(row["id"])
            matches[pid] = {"id": pid, "name": str(row["name"] or "")}

    if not matches:
        return None, "not_found"
    if len(matches) > 1:
        return None, "ambiguous"
    return next(iter(matches.values())), None


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


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        if raw is None or raw == "":
            return int(default)
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


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
    sender_raw = row["sender_player_id"]
    sender_player_id = _safe_int(sender_raw, 0) if sender_raw is not None else None
    if sender_player_id is not None and sender_player_id <= 0:
        sender_player_id = None
    out: dict[str, Any] = {
        "id": _safe_int(row["id"]),
        "recipient_player_id": _safe_int(row["recipient_player_id"]),
        "sender_player_id": sender_player_id,
        "sender_name": str(row["sender_name"]) if row["sender_name"] is not None else None,
        "category": str(row["category"] or "system"),
        "subject": str(row["subject"] or ""),
        "body": str(row["body"] or ""),
        "is_read": bool(_safe_int(row["is_read"], 0)),
        "is_archived": bool(_safe_int(row["is_archived"], 0)),
        "created_at": _safe_int(row["created_at"], 0),
        "read_at": _safe_int(row["read_at"], 0) if row["read_at"] is not None else None,
        "metadata": meta,
    }
    if recipient_name is not None:
        out["recipient_name"] = recipient_name
    if sender_player_id is not None:
        out["reply_to_player_id"] = sender_player_id
        out["reply_to_name"] = out["sender_name"]
    return out


def _row_to_list_item(row: Any) -> dict[str, Any]:
    """Inbox list row — omit body/metadata (loaded on detail fetch)."""
    sender_raw = row["sender_player_id"]
    sender_player_id = _safe_int(sender_raw, 0) if sender_raw is not None else None
    if sender_player_id is not None and sender_player_id <= 0:
        sender_player_id = None
    out: dict[str, Any] = {
        "id": _safe_int(row["id"]),
        "recipient_player_id": _safe_int(row["recipient_player_id"]),
        "sender_player_id": sender_player_id,
        "sender_name": str(row["sender_name"]) if row["sender_name"] is not None else None,
        "category": str(row["category"] or "system"),
        "subject": str(row["subject"] or ""),
        "is_read": bool(_safe_int(row["is_read"], 0)),
        "is_archived": bool(_safe_int(row["is_archived"], 0)),
        "created_at": _safe_int(row["created_at"], 0),
        "read_at": _safe_int(row["read_at"], 0) if row["read_at"] is not None else None,
    }
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
    if cat == "trade":
        return (
            " AND category = 'system' AND ("
            "metadata_json LIKE '%\"mission_type\":\"transport\"%' OR "
            "metadata_json LIKE '%\"mission_type\":\"collect\"%' OR "
            "metadata_json LIKE '%\"mission_type\":\"deploy\"%' OR "
            "metadata_json LIKE '%\"mission_type\":\"recycle\"%' OR "
            "metadata_json LIKE '%\"report_phase\"%'"
            ")",
            [],
        )
    if cat in VALID_CATEGORIES:
        return " AND category = ?", [cat]
    return "", []


def _not_deleted_sql() -> str:
    return "(deleted_at IS NULL OR deleted_at = 0)"


def _not_deleted_clause() -> str:
    return f" AND {_not_deleted_sql()}"


def normalize_inbox_rows(conn, player_id: int) -> None:
    """Repair legacy rows so list + unread_count stay consistent."""
    pid = int(player_id)
    conn.execute(
        "UPDATE player_messages SET deleted_at = NULL WHERE recipient_player_id = ? AND deleted_at = 0;",
        (pid,),
    )
    conn.execute(
        "UPDATE player_messages SET is_archived = 0 WHERE recipient_player_id = ? AND is_archived IS NULL;",
        (pid,),
    )
    conn.execute(
        "UPDATE player_messages SET is_read = 0 WHERE recipient_player_id = ? AND is_read IS NULL;",
        (pid,),
    )


def _inbox_needs_normalize(conn, player_id: int) -> bool:
    """Cheap check — skip write transaction when migration 021 already normalized rows."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1
        FROM player_messages
        WHERE recipient_player_id = ?
          AND (deleted_at = 0 OR is_archived IS NULL OR is_read IS NULL)
        LIMIT 1;
        """,
        (int(player_id),),
    )
    return cur.fetchone() is not None


def _prepare_inbox(conn, player_id: int) -> None:
    if not _table_ready(conn):
        return
    pid = int(player_id)
    if not _inbox_needs_normalize(conn, pid):
        return
    if in_transaction(conn):
        normalize_inbox_rows(conn, pid)
        return
    begin_write_transaction(conn)
    try:
        normalize_inbox_rows(conn, pid)
        commit(conn)
    except Exception:
        rollback(conn)
        raise


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


def _fleet_report_exists(
    conn,
    recipient_player_id: int,
    fleet_id: int,
    category: str,
    *,
    report_phase: str | None = None,
) -> bool:
    """True if an inbox row already exists for this fleet report."""
    if not _table_ready(conn):
        return False
    cur = conn.cursor()
    phase_sql = ""
    params: list[Any] = [int(recipient_player_id), str(category), int(fleet_id)]
    if report_phase:
        phase_sql = " AND json_extract(metadata_json, '$.report_phase') = ?"
        params.append(str(report_phase))
    cur.execute(
        f"""
        SELECT 1 FROM player_messages
        WHERE recipient_player_id = ?
          AND category = ?
          AND {_not_deleted_sql()}
          AND json_extract(metadata_json, '$.fleet_id') = ?{phase_sql}
        LIMIT 1;
        """,
        params,
    )
    return cur.fetchone() is not None


def _notify_player_idempotent_fleet(
    player_id: int,
    subject: str,
    body: str,
    *,
    category: str = "system",
    metadata: dict[str, Any] | None = None,
    sender_name: str | None = None,
    conn=None,
) -> dict[str, Any]:
    """Deliver a fleet report once per (recipient, category, fleet_id[, report_phase])."""
    pid = _valid_player_id(player_id, conn=conn)
    if pid is None:
        return _err("recipient_not_found")
    meta = dict(metadata or {})
    fleet_id = meta.get("fleet_id")
    report_phase = meta.get("report_phase")
    if fleet_id is not None and conn is not None:
        if _fleet_report_exists(
            conn,
            pid,
            int(fleet_id),
            category,
            report_phase=str(report_phase) if report_phase else None,
        ):
            return _ok({"message_id": None, "deduplicated": True})
    return create_message(
        pid,
        subject,
        body,
        category=category,
        sender_player_id=None,
        sender_name=sender_name or "System",
        metadata=meta or None,
        conn=conn,
    )


def _valid_player_id(player_id: int, *, conn=None) -> int | None:
    try:
        pid = int(player_id)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM players WHERE id = ? LIMIT 1;", (pid,))
        row = cur.fetchone()
        return int(row["id"]) if row else None
    finally:
        if own_conn and conn is not None:
            conn.close()


def notify_player(
    player_id: int,
    subject: str,
    body: str,
    *,
    category: str = "system",
    metadata: dict[str, Any] | None = None,
    sender_name: str | None = None,
    conn=None,
) -> dict[str, Any]:
    """Helper for other systems to deliver inbox messages (plain text subject/body)."""
    pid = _valid_player_id(player_id, conn=conn)
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
        conn=conn,
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


def normalize_combat_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure structured combat report blocks for inbox renderers and archival reads."""
    from .combat import COMBAT_REPORT_VERSION

    meta = dict(metadata or {})
    meta.setdefault("report_version", COMBAT_REPORT_VERSION)
    meta.setdefault("target_coords", str(meta.get("target_coords") or ""))
    meta.setdefault("origin_coords", str(meta.get("origin_coords") or ""))
    meta.setdefault("origin_planet_name", str(meta.get("origin_planet_name") or ""))
    meta.setdefault("target_planet_name", str(meta.get("target_planet_name") or ""))
    meta.setdefault("attacker_id", int(meta.get("attacker_id") or 0))
    meta.setdefault("defender_id", int(meta.get("defender_id") or 0))
    meta.setdefault("attacker_name", str(meta.get("attacker_name") or ""))
    meta.setdefault("defender_name", str(meta.get("defender_name") or ""))
    meta.setdefault("result", str(meta.get("result") or meta.get("winner") or "undecided"))
    meta.setdefault("winner", meta["result"])
    meta.setdefault("attacking_ships", dict(meta.get("attacking_ships") or {}))
    meta.setdefault("defending_ships", dict(meta.get("defending_ships") or {}))
    meta.setdefault("defending_defense", dict(meta.get("defending_defense") or {}))
    meta.setdefault("attacker_losses", dict(meta.get("attacker_losses") or {}))
    meta.setdefault("defender_losses", dict(meta.get("defender_losses") or {}))
    meta.setdefault("return_ships", dict(meta.get("return_ships") or {}))
    meta.setdefault("loot", dict(meta.get("loot") or {}))
    rounds = meta.get("rounds")
    if not isinstance(rounds, list):
        rounds = []
    meta["rounds"] = rounds
    if "rounds_fought" not in meta:
        meta["rounds_fought"] = len(rounds)
    return meta


def notify_combat(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    *,
    locale: str | None = None,
    conn=None,
) -> dict[str, Any]:
    from .i18n import tr

    meta = normalize_combat_metadata(metadata)
    return _notify_player_idempotent_fleet(
        player_id,
        subject,
        body,
        category="combat",
        metadata=meta,
        sender_name=tr("messages_sender_combat", "Kampfbericht", locale=locale),
        conn=conn,
    )


def dispatch_combat_reports(
    *,
    attacker_id: int,
    defender_id: int,
    coords: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    conn=None,
    attacker_locale: str | None = None,
    defender_locale: str | None = None,
) -> dict[str, Any]:
    """Persist combat inbox messages for attacker and defender (``player_messages``)."""
    from .i18n import tr

    meta = normalize_combat_metadata(metadata)
    out: dict[str, Any] = {"attacker": None, "defender": None}
    atk_subject = tr(
        "fleet_report_combat_subject_coords",
        "Combat report — %(coords)s",
        locale=attacker_locale,
        coords=coords,
    )
    atk_meta = {**meta, "perspective": "attacker"}
    out["attacker"] = notify_combat(
        int(attacker_id),
        atk_subject,
        body,
        metadata=atk_meta,
        locale=attacker_locale,
        conn=conn,
    )
    def_id = int(defender_id)
    if def_id > 0 and def_id != int(attacker_id):
        def_subject = tr(
            "fleet_report_combat_subject_defender",
            "Attack report — %(coords)s",
            locale=defender_locale,
            coords=coords,
        )
        def_meta = {**meta, "perspective": "defender"}
        out["defender"] = notify_combat(
            def_id,
            def_subject,
            body,
            metadata=def_meta,
            locale=defender_locale,
            conn=conn,
        )
    return out


def notify_espionage(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    *,
    locale: str | None = None,
    conn=None,
) -> dict[str, Any]:
    from .i18n import tr

    meta = normalize_espionage_metadata(metadata)
    return _notify_player_idempotent_fleet(
        player_id,
        subject,
        body,
        category="espionage",
        metadata=meta,
        sender_name=tr("messages_sender_espionage", "Spionagebericht", locale=locale),
        conn=conn,
    )


def normalize_espionage_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure structured spy report blocks (incl. defense) are present for inbox renderers."""
    meta = dict(metadata or {})
    tiers = meta.get("intel_tiers")
    if isinstance(tiers, dict) and "defense" not in tiers:
        tiers = dict(tiers)
        tiers.setdefault("defense", False)
        meta["intel_tiers"] = tiers
    if "defense" not in meta:
        meta["defense"] = {}
    return meta


def append_spy_defense_report_lines(
    body_lines: list[str],
    defense: Mapping[str, Any],
    *,
    tiers: Mapping[str, Any],
    probe_count: int,
    tr,
    fmt_int,
) -> None:
    """Append plain-text defense intel section to a spy report body."""
    from .defense_defs import get_defense

    if tiers.get("defense"):
        lines: list[str] = []
        total_units = int(defense.get("total_units") or 0)
        defense_power = int(defense.get("defense_power") or 0)
        shield_power = int(defense.get("shield_power") or 0)
        lines.append(
            tr(
                "fleet_spy_report_defense_total",
                "Defense units: %(count)s",
                count=fmt_int(total_units),
            )
        )
        lines.append(
            tr(
                "fleet_spy_report_defense_power",
                "Defense power: %(power)s",
                power=fmt_int(defense_power),
            )
        )
        lines.append(
            tr(
                "fleet_spy_report_shield_power",
                "Shield power: %(power)s",
                power=fmt_int(shield_power),
            )
        )
        units = defense.get("units") or {}
        if units:
            for key, qty in sorted(units.items()):
                spec = get_defense(str(key)) or {}
                label = tr(str(spec.get("name_key") or key), str(key))
                lines.append(f"{label} ×{fmt_int(int(qty or 0))}")
        elif total_units <= 0:
            lines.append(tr("fleet_spy_report_defense_empty", "No defensive structures detected"))
        accuracy_pct = defense.get("accuracy_pct")
        if accuracy_pct is not None and not defense.get("exact"):
            lines.append(
                tr(
                    "fleet_spy_report_defense_accuracy",
                    "Intel accuracy: ~%(pct)s%% (espionage research)",
                    pct=fmt_int(int(accuracy_pct)),
                )
            )
        title = tr("fleet_spy_report_section_defense", "Planetary defense")
        body_lines.append(f"{title}\n" + "\n".join(f"  {line}" for line in lines))
    elif int(probe_count) >= 4:
        body_lines.append(
            tr(
                "fleet_spy_report_defense_locked",
                "Planetary defense: insufficient probe data",
            )
        )


def notify_expedition(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    *,
    locale: str | None = None,
    conn=None,
) -> dict[str, Any]:
    from .i18n import tr

    return _notify_player_idempotent_fleet(
        player_id,
        subject,
        body,
        category="expedition",
        metadata=metadata,
        sender_name=tr("messages_sender_expedition", "Expeditionsbericht", locale=locale),
        conn=conn,
    )


def notify_transport(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    *,
    locale: str | None = None,
    conn=None,
) -> dict[str, Any]:
    from .i18n import tr

    return _notify_player_idempotent_fleet(
        player_id,
        subject,
        body,
        category="system",
        metadata=metadata,
        sender_name=tr("messages_sender_transport", "Transportbericht", locale=locale),
        conn=conn,
    )


def notify_logistics_fleet_report(
    player_id: int,
    subject: str,
    body: str,
    metadata: dict[str, Any] | None = None,
    *,
    locale: str | None = None,
    conn=None,
) -> dict[str, Any]:
    from .i18n import tr

    meta = dict(metadata or {})
    if meta.get("fleet_id") is not None and not meta.get("report_phase"):
        return _err("logistics_report_phase_required")
    return _notify_player_idempotent_fleet(
        player_id,
        subject,
        body,
        category="system",
        metadata=meta,
        sender_name=tr("messages_sender_logistics", "Logistikbericht", locale=locale),
        conn=conn,
    )


def _inbox_visibility_clause(*, archived: bool = False) -> str:
    """Shared inbox filters for list + unread_count (non-archive tab)."""
    if archived:
        return (
            f"recipient_player_id = ? AND {_not_deleted_sql()} "
            "AND COALESCE(is_archived, 0) = 1"
        )
    return (
        f"recipient_player_id = ? AND {_not_deleted_sql()} "
        "AND COALESCE(is_archived, 0) = 0"
    )


def _unread_clause() -> str:
    return " AND COALESCE(is_read, 0) = 0"


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
        _prepare_inbox(conn, int(player_id))

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
                   category, subject, is_read, is_archived, created_at, read_at
            FROM player_messages
            WHERE {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?;
            """,
            (*params, lim, off),
        )
        rows = [_row_to_list_item(r) for r in cur.fetchall()]
        unread = unread_count(int(player_id), conn=conn, prepare=False)
        logger.debug(
            "list_messages player_id=%s category=%r item_count=%s unread=%s",
            int(player_id),
            category,
            len(rows),
            unread,
        )
        return _ok({"messages": rows, "unread_count": unread, "player_id": int(player_id)})
    finally:
        conn.close()


def get_message(player_id: int, message_id: int, *, mark_read: bool = True) -> dict[str, Any]:
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        _prepare_inbox(conn, int(player_id))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, recipient_player_id, sender_player_id, sender_name,
                   category, subject, body, is_read, is_archived,
                   metadata_json, created_at, read_at
            FROM player_messages
            WHERE id = ? AND recipient_player_id = ? AND """
            + _not_deleted_sql()
            + """
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
            WHERE id = ? AND recipient_player_id = ? AND """
            + _not_deleted_sql()
            + """;
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
        _prepare_inbox(conn, int(player_id))
        where = f"{_inbox_visibility_clause(archived=False)}{_unread_clause()}"
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
            WHERE id = ? AND recipient_player_id = ? AND """
            + _not_deleted_sql()
            + """;
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


def bulk_update_messages(
    player_id: int,
    message_ids: list[int],
    *,
    action: str,
) -> dict[str, Any]:
    """Bulk read / archive / delete for selected inbox rows."""
    conn = db()
    try:
        if not _table_ready(conn):
            return _err("messages_not_ready")
        act = str(action or "").strip().lower()
        if act not in ("read", "archive", "delete"):
            return _err("validation")
        ids = sorted({int(i) for i in (message_ids or []) if int(i) > 0})
        if not ids:
            return _err("validation")

        _prepare_inbox(conn, int(player_id))
        placeholders = ",".join("?" for _ in ids)
        begin_write_transaction(conn)
        cur = conn.cursor()
        now = _now()

        if act == "read":
            cur.execute(
                f"""
                UPDATE player_messages
                SET is_read = 1, read_at = COALESCE(read_at, ?)
                WHERE recipient_player_id = ? AND id IN ({placeholders})
                  AND {_not_deleted_sql()};
                """,
                (now, int(player_id), *ids),
            )
        elif act == "archive":
            cur.execute(
                f"""
                UPDATE player_messages
                SET is_archived = 1
                WHERE recipient_player_id = ? AND id IN ({placeholders})
                  AND {_not_deleted_sql()};
                """,
                (int(player_id), *ids),
            )
        else:
            cur.execute(
                f"""
                UPDATE player_messages
                SET deleted_at = ?
                WHERE recipient_player_id = ? AND id IN ({placeholders})
                  AND {_not_deleted_sql()};
                """,
                (now, int(player_id), *ids),
            )

        updated = int(cur.rowcount or 0)
        if updated < 1:
            rollback(conn)
            return _err("not_found")
        commit(conn)
        return _with_unread(player_id, {"updated": updated, "action": act, "ids": ids})
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
            WHERE id = ? AND recipient_player_id = ? AND """
            + _not_deleted_sql()
            + """;
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


def unread_count(player_id: int, *, conn=None, prepare: bool = True) -> int:
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not _table_ready(conn):
            return 0
        if prepare:
            _prepare_inbox(conn, int(player_id))
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM player_messages
            WHERE {_inbox_visibility_clause(archived=False)}
              {_unread_clause()};
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

        lookup_input = str(recipient_name or "").strip()
        recipient, lookup_err = resolve_message_recipient(lookup_input, conn)
        if lookup_err == "ambiguous":
            return _err("recipient_ambiguous")
        if lookup_err or not recipient:
            return _err("recipient_not_found")
        recipient_id = int(recipient["id"])
        if recipient_id == int(sender_player_id):
            return _err("validation")

        logger.debug(
            "send_player_message sender_player_id=%s recipient_player_id=%s recipient_lookup_input=%r",
            int(sender_player_id),
            recipient_id,
            lookup_input,
        )

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
                "recipient_player_id": recipient_id,
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
            hit, lookup_err = resolve_message_recipient(str(recipient), conn)
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
