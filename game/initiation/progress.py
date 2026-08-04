"""Apply gameplay events to Command Initiation (fan-out from directives bus)."""

from __future__ import annotations

import time
from typing import Any, Dict, Mapping, Sequence

from ..db import is_integrity_error, table_exists
from .engine import (
    STATUS_ACTIVE,
    advance_if_complete,
    ensure_player_initiation,
    initiation_schema_ready,
)
from .packs import step_at

PROGRESS_TABLE = "player_initiation_progress"


def progress_schema_ready(conn) -> bool:
    return table_exists(conn, PROGRESS_TABLE)


def apply_gameplay_events(
    player_id: int,
    events: Sequence[Mapping[str, Any]],
    *,
    conn,
    now: float | None = None,
) -> Dict[str, Any]:
    """Apply gameplay events to the active initiation step (idempotent)."""
    pid = int(player_id)
    if pid <= 0 or not events:
        return {"updated": 0, "completed": 0}

    if not initiation_schema_ready(conn) or not progress_schema_ready(conn):
        return {"updated": 0, "completed": 0}

    ts = float(now if now is not None else time.time())
    ensure_player_initiation(pid, conn=conn, now=ts)

    row = conn.execute(
        """
        SELECT status, step_index, progress_value, target_value
        FROM player_initiation
        WHERE player_id = ?;
        """,
        (pid,),
    ).fetchone()
    if not row or str(row["status"] or "") != STATUS_ACTIVE:
        return {"updated": 0, "completed": 0}

    step = step_at(int(row["step_index"] or 0))
    if not step:
        return {"updated": 0, "completed": 0}

    from ..directives.progress import gameplay_event_delta

    objective_key = str(step.get("objective_key") or "")
    filters = step.get("filters") if isinstance(step.get("filters"), dict) else {}
    objective_kind = str(step.get("objective_kind") or "count")
    updated = 0
    completed = 0
    now_i = int(ts)
    progress = int(row["progress_value"] or 0)
    target = max(1, int(row["target_value"] or step.get("target") or 1))

    for event in events:
        if not event:
            continue
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
            pid,
            source_event_id=source_event_id,
            delta=delta,
            conn=conn,
            now=now_i,
        ):
            continue
        progress = min(target, progress + delta)
        conn.execute(
            """
            UPDATE player_initiation
            SET progress_value = ?, target_value = ?, updated_at = ?
            WHERE player_id = ? AND status = ?;
            """,
            (int(progress), int(target), now_i, pid, STATUS_ACTIVE),
        )
        updated += 1
        if progress >= target:
            adv = advance_if_complete(pid, conn=conn, now=ts)
            if adv.get("advanced"):
                completed += 1
            row2 = conn.execute(
                """
                SELECT status, step_index, progress_value, target_value
                FROM player_initiation
                WHERE player_id = ?;
                """,
                (pid,),
            ).fetchone()
            if not row2 or str(row2["status"] or "") != STATUS_ACTIVE:
                break
            step = step_at(int(row2["step_index"] or 0))
            if not step:
                break
            objective_key = str(step.get("objective_key") or "")
            filters = step.get("filters") if isinstance(step.get("filters"), dict) else {}
            objective_kind = str(step.get("objective_kind") or "count")
            progress = int(row2["progress_value"] or 0)
            target = max(1, int(row2["target_value"] or step.get("target") or 1))

    return {"updated": updated, "completed": completed}


def _record_progress_delta(
    player_id: int,
    *,
    source_event_id: str,
    delta: int,
    conn,
    now: int,
) -> bool:
    try:
        conn.execute(
            """
            INSERT INTO player_initiation_progress (
                player_id, source_event_id, delta, created_at
            ) VALUES (?, ?, ?, ?);
            """,
            (int(player_id), str(source_event_id), int(delta), int(now)),
        )
        return True
    except Exception as exc:
        if is_integrity_error(exc):
            return False
        raise
