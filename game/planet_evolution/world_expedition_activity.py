"""World-map expedition activity overlay (GC-583C) — fleet_movements + messages, no new tables."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional

RECENT_REPORT_SECONDS = 48 * 3600
_EXPEDITION_ACTIVE_STATUSES = frozenset({"outbound", "holding", "returning"})


def _json_loads(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _world_key_from_movement(row: Any) -> str:
    data = dict(row) if not isinstance(row, dict) else row
    payload = _json_loads(data.get("resources_json"), {}) or {}
    return str(payload.get("world_key") or "").strip()


def _world_key_from_message_meta(raw: Any) -> str:
    meta = _json_loads(raw, {}) or {}
    report_kind = str(meta.get("report_kind") or "")
    if report_kind not in {"world_expedition", "world_salvage"}:
        return ""
    return str(meta.get("world_key") or "").strip()


def build_world_expedition_activity_map(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> Dict[str, Dict[str, Any]]:
    """Map world_key → expedition activity for world-map fields."""
    ts = float(now if now is not None else time.time())
    activity: Dict[str, Dict[str, Any]] = {}

    rows = conn.execute(
        """
        SELECT id, status, resources_json, arrival_at, return_at, holding_until
        FROM fleet_movements
        WHERE player_id = ?
          AND mission_type = 'expedition'
          AND status IN ('outbound', 'holding', 'returning')
        ORDER BY id DESC;
        """,
        (int(player_id),),
    ).fetchall()

    for row in rows:
        wk = _world_key_from_movement(dict(row))
        if not wk or wk in activity:
            continue
        status = str(row["status"] or "")
        if status == "outbound":
            activity[wk] = {
                "expedition_status": "expedition_active",
                "expedition_fleet_id": int(row["id"]),
                "expedition_eta_at": float(row["arrival_at"] or 0),
                "expedition_phase": "outbound",
            }
        elif status == "holding":
            activity[wk] = {
                "expedition_status": "expedition_active",
                "expedition_fleet_id": int(row["id"]),
                "expedition_eta_at": float(row["holding_until"] or 0),
                "expedition_phase": "holding",
            }
        elif status == "returning":
            activity[wk] = {
                "expedition_status": "expedition_returning",
                "expedition_fleet_id": int(row["id"]),
                "expedition_eta_at": float(row["return_at"] or 0),
                "expedition_phase": "returning",
            }

    msg_rows = conn.execute(
        """
        SELECT id, metadata_json, created_at
        FROM player_messages
        WHERE recipient_player_id = ?
          AND category = 'expedition'
          AND (deleted_at IS NULL OR deleted_at = 0)
        ORDER BY id DESC
        LIMIT 100;
        """,
        (int(player_id),),
    ).fetchall()

    for row in msg_rows:
        wk = _world_key_from_message_meta(row["metadata_json"])
        if not wk or wk in activity:
            continue
        created_at = float(row["created_at"] or 0)
        if created_at <= 0 or (ts - created_at) > RECENT_REPORT_SECONDS:
            continue
        meta = _json_loads(row["metadata_json"], {}) or {}
        activity[wk] = {
            "expedition_status": "recently_reported",
            "expedition_report_message_id": int(row["id"]),
            "expedition_report_at": created_at,
            "expedition_event_label_key": str(meta.get("event_label_key") or ""),
            "expedition_event_key": str(meta.get("event_key") or ""),
        }

    return activity


def attach_world_expedition_activity(
    nodes: List[Dict[str, Any]],
    activity_map: Mapping[str, Mapping[str, Any]],
) -> None:
    """Annotate world_field nodes with expedition activity (GC-583C)."""
    for node in nodes:
        if str(node.get("node_kind") or "") != "world_field":
            continue
        wk = str(node.get("world_key") or "").strip()
        if not wk:
            node["expedition_status"] = "idle"
            continue
        block = dict(activity_map.get(wk) or {})
        if block:
            node.update(block)
        else:
            node["expedition_status"] = "idle"
