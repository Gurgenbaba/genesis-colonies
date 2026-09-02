"""Apply gameplay events to active story objectives (fan-out from directives)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

from ..db import table_exists
from .packs import get_arc, resolve_beat

logger = logging.getLogger(__name__)

ARCS_TABLE = "player_story_arcs"
PROGRESS_TABLE = "player_story_progress"

STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"


def story_schema_ready(conn) -> bool:
    return table_exists(conn, ARCS_TABLE) and table_exists(conn, PROGRESS_TABLE)


def apply_gameplay_events(
    player_id: int,
    events: Sequence[Mapping[str, Any]],
    *,
    conn,
    now: float | None = None,
) -> Dict[str, Any]:
    """Apply gameplay events to active story objective beats (idempotent)."""
    pid = int(player_id)
    if pid <= 0 or not events:
        return {"updated": 0, "completed": 0}

    if not story_schema_ready(conn):
        return {"updated": 0, "completed": 0}

    from .engine import ensure_player_story, try_auto_advance_arc

    ts = float(now if now is not None else time.time())
    ensure_player_story(pid, conn=conn, now=ts)

    active = _load_active_arcs(pid, conn=conn)
    if not active:
        return {"updated": 0, "completed": 0}

    from ..directives.progress import gameplay_event_delta

    updated = 0
    completed = 0
    now_i = int(ts)

    for event in events:
        if not event:
            continue
        for row in active:
            if str(row.get("status") or "") != STATUS_ACTIVE:
                continue
            arc_def = get_arc(str(row["pack_id"]), str(row["arc_id"]))
            if not arc_def:
                continue
            beat = resolve_beat(
                arc_def,
                chapter_index=int(row["chapter_index"] or 0),
                beat_index=int(row["beat_index"] or 0),
            )
            if not beat or str(beat.get("type") or "") != "objective":
                continue
            objective_key = str(beat.get("objective_key") or "")
            filters = beat.get("filters") if isinstance(beat.get("filters"), dict) else {}
            objective_kind = str(beat.get("objective_kind") or "count")
            delta = gameplay_event_delta(
                objective_key,
                event,
                objective_kind=objective_kind,
                filters=filters,
            )
            if delta <= 0:
                continue
            source_event_id = str(event.get("source_event_id") or "").strip()
            if not source_event_id:
                continue
            if not _record_progress_delta(
                int(row["id"]),
                source_event_id=source_event_id,
                delta=delta,
                conn=conn,
                now=now_i,
            ):
                continue
            new_progress = int(row.get("progress_value") or 0) + delta
            target = max(1, int(row.get("target_value") or beat.get("target") or 1))
            if new_progress >= target:
                new_progress = target
            conn.execute(
                """
                UPDATE player_story_arcs
                SET progress_value = ?, target_value = ?, updated_at = ?
                WHERE id = ? AND status = ?;
                """,
                (int(new_progress), int(target), now_i, int(row["id"]), STATUS_ACTIVE),
            )
            row["progress_value"] = new_progress
            row["target_value"] = target
            updated += 1
            if new_progress >= target:
                adv = try_auto_advance_arc(pid, int(row["id"]), conn=conn, now=ts)
                if adv.get("advanced") or adv.get("completed"):
                    completed += 1

    return {"updated": updated, "completed": completed}


def _load_active_arcs(player_id: int, *, conn) -> List[MutableMapping[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, pack_id, arc_id, status, chapter_index, beat_index,
               progress_value, target_value
        FROM player_story_arcs
        WHERE player_id = ? AND status = ?;
        """,
        (int(player_id), STATUS_ACTIVE),
    ).fetchall()
    return [dict(r) for r in rows]


def _record_progress_delta(
    player_arc_id: int,
    *,
    source_event_id: str,
    delta: int,
    conn,
    now: int,
) -> bool:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO player_story_progress (
            player_arc_id, source_event_id, delta, created_at
        ) VALUES (?, ?, ?, ?);
        """,
        (int(player_arc_id), str(source_event_id), int(delta), int(now)),
    )
    return int(cur.rowcount or 0) > 0
