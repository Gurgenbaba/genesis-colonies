"""Apply gameplay events to Command Initiation (fan-out from directives bus)."""

from __future__ import annotations

import time
from typing import Any, Dict, Mapping, Sequence

from ..db import table_exists
from .engine import (
    STATUS_ACTIVE,
    advance_if_complete,
    ensure_player_initiation,
    initiation_schema_ready,
    load_row,
)
from .packs import step_at
from .pages import resolve_page_key, should_record_page_visit

PROGRESS_TABLE = "player_initiation_progress"


def progress_schema_ready(conn) -> bool:
    return table_exists(conn, PROGRESS_TABLE)


def page_seen_event_id(page_key: str, player_id: int) -> str:
    """Stable idempotent id for early / late page-visit credit."""
    return f"ini_page_seen:{str(page_key or '').strip()}:{int(player_id)}"


def has_page_seen(player_id: int, page_key: str, *, conn) -> bool:
    """True when the player has opened this initiation visit surface at least once."""
    pid = int(player_id)
    page = str(page_key or "").strip()
    if pid <= 0 or not page or not progress_schema_ready(conn):
        return False
    row = conn.execute(
        """
        SELECT 1 AS ok
        FROM player_initiation_progress
        WHERE player_id = ? AND source_event_id = ?
        LIMIT 1;
        """,
        (pid, page_seen_event_id(page, pid)),
    ).fetchone()
    return bool(row)


def mark_page_seen(
    player_id: int,
    page_key: str,
    *,
    conn,
    now: float | None = None,
) -> bool:
    """
    Persist that the player opened a visit surface (even before that step is active).

    Returns True when a new row was inserted.
    """
    pid = int(player_id)
    page = str(page_key or "").strip()
    if pid <= 0 or not page or not progress_schema_ready(conn):
        return False
    now_i = int(now if now is not None else time.time())
    return _record_progress_delta(
        pid,
        source_event_id=page_seen_event_id(page, pid),
        delta=1,
        conn=conn,
        now=now_i,
    )


def record_page_visit(
    player_id: int,
    page_key: str,
    *,
    conn,
    now: float | None = None,
    source_event_id: str | None = None,
) -> Dict[str, Any]:
    """
    Log a page visit and complete the matching visit_page step when it is (or becomes) active.

    Early visits are stored as ``ini_page_seen:{page}:{player}`` so
    ``credit_existing_progress`` can complete the step later without a re-open.
    """
    pid = int(player_id)
    page = str(page_key or "").strip()
    if pid <= 0 or not page:
        return {"updated": 0, "completed": 0}

    if not initiation_schema_ready(conn) or not progress_schema_ready(conn):
        return {"updated": 0, "completed": 0}

    ts = float(now if now is not None else time.time())
    ensure_player_initiation(pid, conn=conn, now=ts)
    mark_page_seen(pid, page, conn=conn, now=ts)

    row = load_row(pid, conn=conn)
    if not row or str(row.get("status") or "") != STATUS_ACTIVE:
        return {"updated": 0, "completed": 0}

    from .engine import credit_existing_progress

    # Prefer world/seen credit (also advances when this visit matches the cursor).
    cred = credit_existing_progress(pid, conn=conn, now=ts)
    if cred.get("credited") or cred.get("advanced") or cred.get("completed"):
        return {
            "updated": int(cred.get("credited") or 0) + int(cred.get("advanced") or 0),
            "completed": 1 if cred.get("completed") or int(cred.get("advanced") or 0) > 0 else 0,
        }

    # Fallback: direct event when cursor already matches (seen row may already exist).
    step = step_at(int(row.get("step_index") or 0))
    if not step or str(step.get("objective_key") or "") != "visit_page":
        return {"updated": 0, "completed": 0}

    filters = step.get("filters") if isinstance(step.get("filters"), dict) else {}
    allowed = {str(x) for x in (filters.get("pages") or [])}
    if page not in allowed:
        return {"updated": 0, "completed": 0}

    eid = str(source_event_id or "").strip() or page_seen_event_id(page, pid)
    return apply_gameplay_events(
        pid,
        [
            {
                "kind": "page_visit",
                "page": page,
                "amount": 1,
                "source_event_id": eid,
            }
        ],
        conn=conn,
        now=ts,
    )


def maybe_record_page_visit_from_request(
    player_id: int,
    *,
    conn,
    finish_source: str | None = None,
    path: str | None = None,
    now: float | None = None,
) -> Dict[str, Any]:
    """Hook for page live-context: map path/finish_source → visit event if relevant."""
    if not should_record_page_visit(finish_source):
        return {"updated": 0, "completed": 0}

    req_path = path
    if req_path is None:
        try:
            from flask import has_request_context, request as flask_request

            if has_request_context():
                req_path = str(flask_request.path or "")
        except Exception:
            req_path = None

    page = resolve_page_key(path=req_path, finish_source=finish_source)
    if not page:
        return {"updated": 0, "completed": 0}
    return record_page_visit(player_id, page, conn=conn, now=now)


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
    ensure_player_initiation(pid, conn=conn, now=ts, credit=True)

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
    from .credit import world_progress_for_step
    from .engine import credit_existing_progress

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
        # Prefer absolute world level (have Solar ≥ N) over raw event counts.
        world = world_progress_for_step(pid, step, conn=conn)
        if world is not None:
            progress = max(progress, min(target, int(world)))
        else:
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
            # Veterans may already satisfy the next threshold(s).
            cred = credit_existing_progress(pid, conn=conn, now=ts)
            completed += 1 if cred.get("completed") else 0
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
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO player_initiation_progress (
            player_id, source_event_id, delta, created_at
        ) VALUES (?, ?, ?, ?);
        """,
        (int(player_id), str(source_event_id), int(delta), int(now)),
    )
    return int(cur.rowcount or 0) > 0
