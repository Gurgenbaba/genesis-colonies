"""Ensure / advance Command Initiation progress."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..db import table_exists
from .credit import world_progress_for_step
from .packs import flatten_steps, load_pack, step_at, step_count

STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
PLAYER_TABLE = "player_initiation"


def initiation_schema_ready(conn) -> bool:
    return table_exists(conn, PLAYER_TABLE)


def ensure_player_initiation(
    player_id: int,
    *,
    conn,
    now: float | None = None,
    credit: bool = True,
) -> Dict[str, Any]:
    """Lazy-create active track for the player (auto-start, once)."""
    pid = int(player_id)
    empty = {"ready": False, "status": "", "step_index": 0, "progress_value": 0, "target_value": 0}
    if pid <= 0 or not initiation_schema_ready(conn):
        return empty

    ts = float(now if now is not None else time.time())
    now_i = int(ts)
    row = conn.execute(
        """
        SELECT player_id, status, step_index, progress_value, target_value,
               started_at, updated_at, completed_at
        FROM player_initiation
        WHERE player_id = ?;
        """,
        (pid,),
    ).fetchone()
    if not row:
        first = step_at(0)
        target = max(1, int((first or {}).get("target") or 1))
        conn.execute(
            """
            INSERT INTO player_initiation (
                player_id, status, step_index, progress_value, target_value,
                started_at, updated_at, completed_at
            ) VALUES (?, ?, 0, 0, ?, ?, ?, NULL);
            """,
            (pid, STATUS_ACTIVE, target, now_i, now_i),
        )
        row_dict: Dict[str, Any] = {
            "player_id": pid,
            "status": STATUS_ACTIVE,
            "step_index": 0,
            "progress_value": 0,
            "target_value": target,
            "started_at": now_i,
            "updated_at": now_i,
            "completed_at": None,
        }
    else:
        row_dict = dict(row)

    if credit and str(row_dict.get("status") or "") == STATUS_ACTIVE:
        credit_existing_progress(pid, conn=conn, now=ts)
        refreshed = load_row(pid, conn=conn)
        if refreshed:
            return refreshed
    return row_dict


def credit_existing_progress(
    player_id: int,
    *,
    conn,
    now: float | None = None,
    max_hops: int = 48,
) -> Dict[str, Any]:
    """
    Credit already-met building/tech/hangar state toward the active step.

    Skips forward through consecutive completed thresholds so veterans are not
    forced to rebuild Solar L10→L13 for a "reach L3" objective.
    """
    pid = int(player_id)
    if pid <= 0 or not initiation_schema_ready(conn):
        return {"credited": 0, "advanced": 0, "completed": False}

    ts = float(now if now is not None else time.time())
    now_i = int(ts)
    credited = 0
    advanced = 0
    completed = False

    for _ in range(max(1, int(max_hops))):
        row = load_row(pid, conn=conn)
        if not row or str(row.get("status") or "") != STATUS_ACTIVE:
            break

        step_index = int(row.get("step_index") or 0)
        step = step_at(step_index)
        if not step:
            break

        target = max(1, int(row.get("target_value") or step.get("target") or 1))
        progress = int(row.get("progress_value") or 0)
        world = world_progress_for_step(pid, step, conn=conn)
        if world is None:
            break

        next_progress = max(progress, min(target, int(world)))
        if next_progress > progress:
            conn.execute(
                """
                UPDATE player_initiation
                SET progress_value = ?, target_value = ?, updated_at = ?
                WHERE player_id = ? AND status = ?;
                """,
                (int(next_progress), int(target), now_i, pid, STATUS_ACTIVE),
            )
            credited += 1
            progress = next_progress

        if progress < target:
            break

        adv = advance_if_complete(pid, conn=conn, now=ts)
        if not adv.get("advanced"):
            break
        advanced += 1
        if adv.get("completed"):
            completed = True
            break

    return {"credited": credited, "advanced": advanced, "completed": completed}


def advance_if_complete(
    player_id: int,
    *,
    conn,
    now: float | None = None,
) -> Dict[str, Any]:
    """If current step progress >= target, move to next step or complete track."""
    pid = int(player_id)
    if pid <= 0 or not initiation_schema_ready(conn):
        return {"advanced": False, "completed": False}

    ts = float(now if now is not None else time.time())
    now_i = int(ts)
    row = conn.execute(
        """
        SELECT status, step_index, progress_value, target_value
        FROM player_initiation
        WHERE player_id = ?;
        """,
        (pid,),
    ).fetchone()
    if not row or str(row["status"] or "") != STATUS_ACTIVE:
        return {"advanced": False, "completed": False}

    progress = int(row["progress_value"] or 0)
    target = max(1, int(row["target_value"] or 1))
    if progress < target:
        return {"advanced": False, "completed": False}

    next_index = int(row["step_index"] or 0) + 1
    total = step_count()
    if next_index >= total:
        conn.execute(
            """
            UPDATE player_initiation
            SET status = ?, progress_value = ?, target_value = ?,
                updated_at = ?, completed_at = ?
            WHERE player_id = ? AND status = ?;
            """,
            (
                STATUS_COMPLETED,
                target,
                target,
                now_i,
                now_i,
                pid,
                STATUS_ACTIVE,
            ),
        )
        return {"advanced": True, "completed": True, "step_index": next_index - 1}

    nxt = step_at(next_index) or {}
    next_target = max(1, int(nxt.get("target") or 1))
    conn.execute(
        """
        UPDATE player_initiation
        SET step_index = ?, progress_value = 0, target_value = ?, updated_at = ?
        WHERE player_id = ? AND status = ?;
        """,
        (next_index, next_target, now_i, pid, STATUS_ACTIVE),
    )
    return {"advanced": True, "completed": False, "step_index": next_index}


def load_row(player_id: int, *, conn) -> Optional[Dict[str, Any]]:
    if not initiation_schema_ready(conn):
        return None
    row = conn.execute(
        """
        SELECT player_id, status, step_index, progress_value, target_value,
               started_at, updated_at, completed_at
        FROM player_initiation
        WHERE player_id = ?;
        """,
        (int(player_id),),
    ).fetchone()
    return dict(row) if row else None


def pack_meta() -> Dict[str, Any]:
    pack = load_pack()
    steps = flatten_steps(pack)
    return {
        "pack_id": str(pack.get("id") or "command_initiation"),
        "version": int(pack.get("version") or 1),
        "step_count": len(steps),
        "steps": steps,
    }
