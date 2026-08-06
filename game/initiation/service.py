"""Player-facing Command Initiation state."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..db import commit
from .engine import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    ensure_player_initiation,
    initiation_schema_ready,
    load_row,
    pack_meta,
)
from .packs import flatten_steps, resolve_step_route, step_at, step_highlight_key, step_image_path


def _empty_summary() -> Dict[str, Any]:
    return {
        "ready": False,
        "active": False,
        "completed": False,
        "step_index": 0,
        "step_count": 0,
        "progress": 0,
        "target": 0,
        "route": "",
        "title_key": "",
        "hint_key": "",
        "step_id": "",
        "phase_id": "",
    }


def _empty_state() -> Dict[str, Any]:
    return {
        "ready": False,
        "status": "",
        "completed": False,
        "step_index": 0,
        "step_count": 0,
        "completed_steps": 0,
        "progress": 0,
        "target": 0,
        "current": None,
        "steps": [],
        "phases": [],
        "build_order": None,
    }


def _serialize_step(
    step: Dict[str, Any],
    *,
    index: int,
    current_index: int,
    status: str,
    progress: int,
    target: int,
) -> Dict[str, Any]:
    done = False
    active = False
    if status == STATUS_COMPLETED:
        done = True
    elif index < current_index:
        done = True
    elif index == current_index and status == STATUS_ACTIVE:
        active = True
    step_progress = progress if active else (int(step.get("target") or 1) if done else 0)
    step_target = target if active else max(1, int(step.get("target") or 1))
    highlight = step_highlight_key(step)
    return {
        "id": str(step.get("id") or ""),
        "index": index,
        "phase_id": str(step.get("phase_id") or ""),
        "phase_title_key": str(step.get("phase_title_key") or ""),
        "route": resolve_step_route(step),
        "highlight": highlight,
        "image": step_image_path(step),
        "title_key": str(step.get("title_key") or ""),
        "hint_key": str(step.get("hint_key") or ""),
        "objective_key": str(step.get("objective_key") or ""),
        "progress": step_progress,
        "target": step_target,
        "status": "completed" if done else ("active" if active else "locked"),
        "active": active,
        "done": done,
    }


def get_initiation_summary(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
    ensure: bool = True,
) -> Dict[str, Any]:
    """Compact HUD / diet-safe slice."""
    pid = int(player_id)
    if pid <= 0 or not initiation_schema_ready(conn):
        return _empty_summary()

    ts = float(now if now is not None else time.time())
    if ensure:
        before = load_row(pid, conn=conn)
        ensure_player_initiation(pid, conn=conn, now=ts)
        after = load_row(pid, conn=conn)
        if before is None and after is not None:
            try:
                commit(conn)
            except Exception:
                pass

    row = load_row(pid, conn=conn)
    meta = pack_meta()
    step_count = int(meta.get("step_count") or 0)
    if not row:
        return {**_empty_summary(), "step_count": step_count}

    status = str(row.get("status") or "")
    completed = status == STATUS_COMPLETED
    active = status == STATUS_ACTIVE
    step_index = int(row.get("step_index") or 0)
    progress = int(row.get("progress_value") or 0)
    target = max(1, int(row.get("target_value") or 1))
    step = step_at(step_index) if active else None

    return {
        "ready": True,
        "active": active,
        "completed": completed,
        "step_index": step_index,
        "step_count": step_count,
        "progress": progress if active else (step_count if completed else 0),
        "target": target if active else 1,
        "route": resolve_step_route(step) if step else "",
        "highlight": step_highlight_key(step) if step else "",
        "title_key": str((step or {}).get("title_key") or ("initiation_complete_title" if completed else "")),
        "hint_key": str((step or {}).get("hint_key") or ("initiation_complete_hint" if completed else "")),
        "step_id": str((step or {}).get("id") or ""),
        "phase_id": str((step or {}).get("phase_id") or ""),
    }


def get_initiation_state(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Dict[str, Any]:
    """Full mission-page state."""
    pid = int(player_id)
    if pid <= 0 or not initiation_schema_ready(conn):
        return _empty_state()

    ts = float(now if now is not None else time.time())
    ensure_player_initiation(pid, conn=conn, now=ts)
    try:
        commit(conn)
    except Exception:
        pass

    row = load_row(pid, conn=conn)
    steps_raw = flatten_steps()
    if not row:
        return _empty_state()

    status = str(row.get("status") or "")
    step_index = int(row.get("step_index") or 0)
    progress = int(row.get("progress_value") or 0)
    target = max(1, int(row.get("target_value") or 1))
    completed = status == STATUS_COMPLETED

    serialized: List[Dict[str, Any]] = []
    for i, step in enumerate(steps_raw):
        serialized.append(
            _serialize_step(
                step,
                index=i,
                current_index=step_index,
                status=status,
                progress=progress,
                target=target,
            )
        )

    phases: List[Dict[str, Any]] = []
    by_phase: Dict[str, List[Dict[str, Any]]] = {}
    for s in serialized:
        pid_key = str(s.get("phase_id") or "unknown")
        by_phase.setdefault(pid_key, []).append(s)
    for phase_id, phase_steps in by_phase.items():
        title_key = str((phase_steps[0] or {}).get("phase_title_key") or "")
        done_n = sum(1 for s in phase_steps if s.get("done"))
        phases.append(
            {
                "id": phase_id,
                "title_key": title_key,
                "done": done_n,
                "total": len(phase_steps),
                "steps": phase_steps,
            }
        )

    current: Optional[Dict[str, Any]] = None
    if status == STATUS_ACTIVE and 0 <= step_index < len(serialized):
        current = serialized[step_index]

    completed_steps = len(serialized) if completed else step_index

    build_order = None
    try:
        from .build_order import plan_build_order

        build_order = plan_build_order(pid, conn=conn)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "initiation build_order plan failed player_id=%s", pid
        )
        build_order = {"ready": False, "steps": [], "goals": {}, "next": None, "complete": False}

    return {
        "ready": True,
        "status": status,
        "completed": completed,
        "step_index": step_index,
        "step_count": len(serialized),
        "completed_steps": completed_steps,
        "progress": progress,
        "target": target,
        "current": current,
        "steps": serialized,
        "phases": phases,
        "build_order": build_order,
    }


def count_initiation_attention(player_id: int, *, conn: sqlite3.Connection) -> int:
    """Nav badge: 1 while track active (do-first guidance visible)."""
    summary = get_initiation_summary(player_id, conn=conn, ensure=False)
    return 1 if summary.get("active") else 0
