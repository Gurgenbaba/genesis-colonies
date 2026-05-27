"""
Throttled queue-finish policy for high-frequency polling (game-state).

Avoids BEGIN IMMEDIATE on every /api/game-state tick while still finishing due jobs
within a bounded interval.
"""

from __future__ import annotations

import os
import time
from typing import Optional

from .db import db

# Minimum seconds between queue-finish passes triggered by game-state polling.
POLL_FINISH_INTERVAL_SEC = float(os.environ.get("GC_POLL_FINISH_INTERVAL_SEC", "25"))


def player_has_due_queue_work(player_id: int, conn=None, *, now: Optional[float] = None) -> bool:
    """Read-only check: any build/research job past due for this player?"""
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    ts = float(now if now is not None else time.time())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM build_queue bq
            INNER JOIN planets p ON p.id = bq.planet_id
            WHERE p.player_id = ? AND bq.finish_time <= ?
            LIMIT 1;
            """,
            (int(player_id), ts),
        )
        if cur.fetchone():
            return True
        cur.execute(
            """
            SELECT 1 FROM research_queue
            WHERE user_id = ? AND finish_at <= ?
            LIMIT 1;
            """,
            (int(player_id), ts),
        )
        if cur.fetchone():
            return True
        try:
            from .planet_evolution.repository import evolution_schema_ready

            if evolution_schema_ready(conn):
                cur.execute(
                    """
                    SELECT 1
                    FROM planet_research_queue prq
                    INNER JOIN planets p ON p.id = prq.planet_id
                    WHERE p.player_id = ? AND prq.finish_at <= ?
                    LIMIT 1;
                    """,
                    (int(player_id), ts),
                )
                if cur.fetchone():
                    return True
        except Exception:
            pass
        return False
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _lease_key(player_id: int) -> str:
    return f"queue_finish_poll:{int(player_id)}"


def seconds_until_poll_finish_allowed(player_id: int, conn=None) -> float:
    """Read-only: seconds remaining until poll may trigger queue finish (0 = allowed now)."""
    from .runtime_state import get_runtime_value

    raw = get_runtime_value(_lease_key(player_id), conn=conn)
    if not raw:
        return 0.0
    try:
        last = float(raw)
    except (TypeError, ValueError):
        return 0.0
    remaining = POLL_FINISH_INTERVAL_SEC - (time.time() - last)
    return max(0.0, remaining)


def should_run_queue_finish_for_poll(
    player_id: int,
    conn=None,
    *,
    force_due: bool = True,
) -> bool:
    """
    True when game-state polling may run finish_due_work_once.

    - Always when due queue work exists (force_due=True).
    - Otherwise only after POLL_FINISH_INTERVAL_SEC since last recorded poll finish.
    """
    if force_due and player_has_due_queue_work(player_id, conn=conn):
        return True
    return seconds_until_poll_finish_allowed(player_id, conn=conn) <= 0.0


def record_poll_queue_finish(player_id: int, conn=None) -> None:
    """Persist poll finish timestamp (single small write, not per GET row)."""
    from .runtime_state import set_runtime_value

    set_runtime_value(_lease_key(player_id), str(time.time()), conn=conn)
