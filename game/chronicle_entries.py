"""Persistent chronicle archive — independent of inbox message lifecycle (GC-P0)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Mapping

from .db import table_exists
from .scoring import compute_destroyed_raw_from_losses

logger = logging.getLogger(__name__)

CHRONICLE_ENTRIES_TABLE = "chronicle_entries"
ENTRY_TYPE_COMBAT = "combat"
ENTRY_TYPE_EXPEDITION = "expedition"


def chronicle_schema_ready(conn) -> bool:
    return table_exists(conn, CHRONICLE_ENTRIES_TABLE)


def _json_dumps(payload: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(payload or {}), ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _loot_total(loot: Mapping[str, Any]) -> int:
    return (
        max(0, int(loot.get("metal") or 0))
        + max(0, int(loot.get("crystal") or 0))
        + max(0, int(loot.get("fuel_cells") or 0))
    )


def _combat_score_value(meta: Mapping[str, Any]) -> int:
    atk = compute_destroyed_raw_from_losses(dict(meta.get("attacker_losses") or {}))
    def_ = compute_destroyed_raw_from_losses(dict(meta.get("defender_losses") or {}))
    return int(atk) + int(def_)


def _expedition_score_value(meta: Mapping[str, Any]) -> int:
    return _loot_total(dict(meta.get("rewards") or {}))


def _related_player_id(entry_type: str, meta: Mapping[str, Any]) -> int | None:
    if entry_type != ENTRY_TYPE_COMBAT:
        return None
    perspective = str(meta.get("perspective") or "").strip().lower()
    if perspective == "attacker":
        raw = meta.get("defender_id")
    elif perspective == "defender":
        raw = meta.get("attacker_id")
    else:
        return None
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _planet_id_from_meta(meta: Mapping[str, Any]) -> int | None:
    for key in ("defender_planet_id", "target_planet_id", "origin_planet_id"):
        raw = meta.get(key)
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid > 0:
            return pid
    return None


def _source_event_id(
    entry_type: str,
    meta: Mapping[str, Any],
    *,
    source_message_id: int | None = None,
) -> str | None:
    fleet_raw = meta.get("fleet_id")
    try:
        fleet_id = int(fleet_raw)
    except (TypeError, ValueError):
        fleet_id = 0
    if fleet_id > 0:
        if entry_type == ENTRY_TYPE_COMBAT:
            perspective = str(meta.get("perspective") or "unknown").strip().lower() or "unknown"
            return f"combat:{fleet_id}:{perspective}"
        if entry_type == ENTRY_TYPE_EXPEDITION:
            phase = str(meta.get("report_phase") or "").strip()
            if phase:
                return f"expedition:{fleet_id}:{phase}"
            return f"expedition:{fleet_id}"
    if source_message_id:
        return f"{entry_type}:msg:{int(source_message_id)}"
    return None


def record_chronicle_for_fleet_report(
    *,
    player_id: int,
    entry_type: str,
    subject: str,
    metadata: Mapping[str, Any] | None,
    source_message_id: int | None = None,
    occurred_at: int | None = None,
    conn,
) -> bool:
    """
    Persist one chronicle snapshot for a combat or expedition fleet report.

    Idempotent per (player_id, entry_type, source_event_id). No FK to messages.
    """
    if not chronicle_schema_ready(conn):
        return False

    etype = str(entry_type or "").strip().lower()
    if etype not in (ENTRY_TYPE_COMBAT, ENTRY_TYPE_EXPEDITION):
        return False

    pid = int(player_id)
    if pid <= 0:
        return False

    meta = dict(metadata or {})
    event_id = _source_event_id(etype, meta, source_message_id=source_message_id)
    if etype == ENTRY_TYPE_COMBAT:
        score = _combat_score_value(meta)
    else:
        score = _expedition_score_value(meta)

    body = {
        "subject": str(subject or ""),
        "metadata": meta,
    }
    now = int(occurred_at if occurred_at is not None else time.time())
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT OR IGNORE INTO {CHRONICLE_ENTRIES_TABLE} (
            entry_type,
            player_id,
            planet_id,
            related_player_id,
            source_message_id,
            source_event_id,
            title_key,
            body_json,
            score_value,
            occurred_at,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            etype,
            pid,
            _planet_id_from_meta(meta),
            _related_player_id(etype, meta),
            int(source_message_id) if source_message_id else None,
            event_id,
            None,
            _json_dumps(body),
            int(score),
            now,
            int(time.time()),
        ),
    )
    inserted = int(cur.rowcount or 0) > 0
    if not inserted:
        logger.debug(
            "chronicle entry deduplicated player_id=%s entry_type=%s event_id=%s",
            pid,
            etype,
            event_id,
        )
    return inserted


def chronicle_row_subject(body_json: Any) -> str:
    body = _json_loads(body_json)
    return str(body.get("subject") or "")


def chronicle_row_metadata(body_json: Any) -> dict[str, Any]:
    body = _json_loads(body_json)
    meta = body.get("metadata")
    return dict(meta) if isinstance(meta, dict) else body
