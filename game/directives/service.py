"""Player-facing Imperial Directives state (GC-911B)."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional

from ..db import commit
from ..inventory_catalog import container_image_path, item_catalog_entry
from .definitions import directives_schema_ready, get_definition
from .generator import (
    STATUS_ACTIVE,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    ensure_player_directives,
)


def _empty_summary() -> Dict[str, Any]:
    return {
        "ready": False,
        "daily_completed": 0,
        "daily_total": 0,
        "weekly_completed": 0,
        "weekly_total": 0,
        "claimable_count": 0,
        "daily_reset_at": 0,
        "weekly_reset_at": 0,
    }


def _empty_state() -> Dict[str, Any]:
    return {
        "ready": False,
        "daily_reset_at": 0,
        "weekly_reset_at": 0,
        "claimable_count": 0,
        "directives": [],
    }


def _json_loads(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _reward_preview(reward: Mapping[str, Any]) -> List[Dict[str, Any]]:
    preview: List[Dict[str, Any]] = []
    container_key = str(reward.get("container_key") or "").strip()
    if container_key:
        cat = item_catalog_entry(container_key) or {}
        preview.append(
            {
                "item_key": container_key,
                "amount": int(reward.get("container_amount") or 1),
                "item_type": "container",
                "name_key": cat.get("name_key") or container_key,
                "image": container_image_path(container_key),
                "rarity": str(reward.get("rarity") or cat.get("rarity") or "common"),
            }
        )
    for entry in reward.get("boosters") or []:
        if not isinstance(entry, dict):
            continue
        item_key = str(entry.get("item_key") or "").strip()
        if not item_key:
            continue
        cat = item_catalog_entry(item_key) or {}
        preview.append(
            {
                "item_key": item_key,
                "amount": int(entry.get("amount") or 1),
                "item_type": "booster",
                "name_key": cat.get("name_key") or item_key,
                "image": cat.get("image") or "",
                "rarity": str(cat.get("rarity") or "common"),
            }
        )
    return preview


def serialize_directive_row(
    row: Mapping[str, Any],
    definition: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    defn = dict(definition or {})
    reward = _json_loads(row.get("reward_json"))
    progress = int(row.get("progress_value") or 0)
    target = max(1, int(row.get("target_value") or 1))
    status = str(row.get("status") or STATUS_ACTIVE)
    return {
        "id": int(row.get("id") or 0),
        "definition_key": str(row.get("definition_key") or ""),
        "cadence": str(row.get("cadence") or "daily"),
        "category": str(defn.get("category") or ""),
        "rarity": str(row.get("rarity") or "common"),
        "title_key": str(defn.get("title_key") or ""),
        "description_key": str(defn.get("description_key") or ""),
        "objective_kind": str(defn.get("objective_kind") or "count"),
        "progress": progress,
        "target": target,
        "status": status,
        "claimable": status == STATUS_COMPLETED,
        "expires_at": int(row.get("expires_at") or 0),
        "completed_at": int(row["completed_at"]) if row.get("completed_at") else None,
        "claimed_at": int(row["claimed_at"]) if row.get("claimed_at") else None,
        "rewards_preview": _reward_preview(reward),
    }


def get_imperial_directives_state(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    """Lazy-generate and return the live-state slice for Imperial Directives."""
    pid = int(player_id)
    if pid <= 0:
        return _empty_state()

    if not directives_schema_ready(conn):
        return _empty_state()

    ts = float(now if now is not None else time.time())
    raw = ensure_player_directives(pid, conn=conn, now=ts)
    try:
        commit(conn)
    except Exception:
        pass

    directives: List[Dict[str, Any]] = []
    for row in list(raw.get("daily") or []) + list(raw.get("weekly") or []):
        defn = get_definition(str(row.get("definition_key") or ""), conn=conn)
        directives.append(serialize_directive_row(row, defn))

    claimable = sum(1 for d in directives if d.get("claimable"))
    return {
        "ready": True,
        "daily_reset_at": int(raw.get("daily_reset_at") or 0),
        "weekly_reset_at": int(raw.get("weekly_reset_at") or 0),
        "daily_period_key": str(raw.get("daily_period_key") or ""),
        "weekly_period_key": str(raw.get("weekly_period_key") or ""),
        "claimable_count": claimable,
        "directives": directives,
    }


def get_imperial_directives_summary(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    """Compact HUD slice for /api/game-state — no card payload."""
    pid = int(player_id)
    if pid <= 0:
        return _empty_summary()

    if not directives_schema_ready(conn):
        return _empty_summary()

    ts = float(now if now is not None else time.time())
    raw = ensure_player_directives(pid, conn=conn, now=ts)
    try:
        commit(conn)
    except Exception:
        pass

    daily = list(raw.get("daily") or [])
    weekly = list(raw.get("weekly") or [])

    def _completed(rows: List[Mapping[str, Any]]) -> int:
        return sum(1 for row in rows if str(row.get("status") or "") == STATUS_COMPLETED)

    claimable = sum(
        1 for row in daily + weekly if str(row.get("status") or "") == STATUS_COMPLETED
    )
    return {
        "ready": True,
        "daily_completed": _completed(daily),
        "daily_total": len(daily),
        "weekly_completed": _completed(weekly),
        "weekly_total": len(weekly),
        "claimable_count": claimable,
        "daily_reset_at": int(raw.get("daily_reset_at") or 0),
        "weekly_reset_at": int(raw.get("weekly_reset_at") or 0),
    }


def count_claimable_directives(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    read_only: bool = False,
) -> int:
    """Nav-badge helper: set read_only=True to avoid ensure/generate during diet polls."""
    pid = int(player_id)
    if pid <= 0:
        return 0
    if read_only:
        if not directives_schema_ready(conn):
            return 0
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM player_directives
            WHERE player_id = ? AND status = ?;
            """,
            (pid, STATUS_COMPLETED),
        ).fetchone()
        return int((row["n"] if row else 0) or 0)
    summary = get_imperial_directives_summary(pid, conn=conn)
    return int(summary.get("claimable_count") or 0)
