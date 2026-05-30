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

# Sub-second tolerance so jobs with 1s duration are not stuck between float ticks.
DUE_TIME_EPSILON_SEC = float(os.environ.get("GC_DUE_TIME_EPSILON_SEC", "0.05"))


def player_has_due_queue_work(
    player_id: int,
    conn=None,
    *,
    now: Optional[float] = None,
    planet_id: Optional[int] = None,
) -> bool:
    """Read-only check: any build/research job past due for this player (optional: one planet)."""
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    ts = float(now if now is not None else time.time()) + DUE_TIME_EPSILON_SEC
    pid_filter = int(planet_id) if planet_id is not None else None
    try:
        cur = conn.cursor()
        if pid_filter is not None:
            cur.execute(
                """
                SELECT 1
                FROM build_queue bq
                WHERE bq.planet_id = ? AND bq.finish_time <= ?
                LIMIT 1;
                """,
                (pid_filter, ts),
            )
        else:
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
                if pid_filter is not None:
                    cur.execute(
                        """
                        SELECT 1
                        FROM planet_research_queue prq
                        WHERE prq.planet_id = ? AND prq.finish_at <= ?
                        LIMIT 1;
                        """,
                        (pid_filter, ts),
                    )
                else:
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
        try:
            from .shipyard_queue import shipyard_queue_table_ready

            if shipyard_queue_table_ready(conn):
                if pid_filter is not None:
                    cur.execute(
                        """
                        SELECT 1 FROM shipyard_queue
                        WHERE planet_id = ? AND status = 'queued' AND finish_at <= ?
                        LIMIT 1;
                        """,
                        (pid_filter, ts),
                    )
                else:
                    cur.execute(
                        """
                        SELECT 1
                        FROM shipyard_queue sq
                        INNER JOIN planets p ON p.id = sq.planet_id
                        WHERE p.player_id = ? AND sq.status = 'queued' AND sq.finish_at <= ?
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
    planet_id: Optional[int] = None,
) -> bool:
    """
    True when game-state polling may run finish_due_work_once.

    - Always when due queue work exists on the scoped planet (force_due=True).
    - Otherwise only after POLL_FINISH_INTERVAL_SEC since last recorded poll finish.
    """
    if force_due and player_has_due_queue_work(
        player_id,
        conn=conn,
        planet_id=planet_id,
    ):
        return True
    return seconds_until_poll_finish_allowed(player_id, conn=conn) <= 0.0


def record_poll_queue_finish(player_id: int, conn=None) -> None:
    """Persist poll finish timestamp (single small write, not per GET row)."""
    from .runtime_state import set_runtime_value

    set_runtime_value(_lease_key(player_id), str(time.time()), conn=conn)


def player_has_pending_queue_work(
    player_id: int,
    conn=None,
    *,
    planet_id: Optional[int] = None,
) -> bool:
    """Read-only: any queued build/research job still open (due or not)."""
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    try:
        cur = conn.cursor()
        pid_filter = int(planet_id) if planet_id is not None else None

        if pid_filter is not None:
            cur.execute(
                "SELECT 1 FROM build_queue WHERE planet_id = ? LIMIT 1;",
                (pid_filter,),
            )
        else:
            cur.execute(
                """
                SELECT 1
                FROM build_queue bq
                INNER JOIN planets p ON p.id = bq.planet_id
                WHERE p.player_id = ?
                LIMIT 1;
                """,
                (int(player_id),),
            )
        if cur.fetchone():
            return True

        cur.execute(
            "SELECT 1 FROM research_queue WHERE user_id = ? LIMIT 1;",
            (int(player_id),),
        )
        if cur.fetchone():
            return True

        try:
            from .planet_evolution.repository import evolution_schema_ready

            if evolution_schema_ready(conn):
                if pid_filter is not None:
                    cur.execute(
                        "SELECT 1 FROM planet_research_queue WHERE planet_id = ? LIMIT 1;",
                        (pid_filter,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT 1
                        FROM planet_research_queue prq
                        INNER JOIN planets p ON p.id = prq.planet_id
                        WHERE p.player_id = ?
                        LIMIT 1;
                        """,
                        (int(player_id),),
                    )
                if cur.fetchone():
                    return True
        except Exception:
            pass
        return False
    finally:
        if owns_conn and conn is not None:
            conn.close()
