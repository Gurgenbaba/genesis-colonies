"""
Live score invalidation after gameplay mutations (queue finish, combat, autoplay).

GC-SCORE-PERF-001: hot paths only mark players dirty. Canonical score formulas
and persistence run in ``ranking_worker`` (dirty batch every 10 minutes).
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .db import db

logger = logging.getLogger(__name__)

# Legacy constants kept for import compatibility / docs; live rank rewrite
# no longer runs on the mutation path (worker owns ranks after dirty batch).
RANK_RECALC_MIN_INTERVAL_SEC = 45
RANK_RECALC_RUNTIME_KEY = "ranking_live_recalc_last_at"


def mark_player_score_dirty(
    player_id: int,
    *,
    conn: sqlite3.Connection | None = None,
    reason: str = "",
) -> bool:
    """Persistently mark one player for deferred score refresh.

    Idempotent: repeated marks bump ``dirty_version`` but keep the original
    ``dirty_since`` (first event in the pending window). Never runs the score
    formula and never rewrites rank columns.
    """
    pid = int(player_id or 0)
    if pid <= 0:
        return False

    owns_conn = conn is None
    if owns_conn:
        conn = db()
    try:
        now = float(time.time())
        conn.execute(
            """
            INSERT INTO player_score_dirty (player_id, dirty_version, dirty_since, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                dirty_version = player_score_dirty.dirty_version + 1,
                updated_at = excluded.updated_at
            """,
            (pid, now, now),
        )
        if owns_conn:
            conn.commit()
        logger.debug(
            "score_dirty mark player=%s reason=%s",
            pid,
            reason or "unspecified",
        )
        return True
    except Exception:
        logger.exception(
            "score_dirty mark failed player=%s reason=%s",
            pid,
            reason or "unspecified",
        )
        if owns_conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if owns_conn:
            conn.close()


def list_dirty_score_players(
    *,
    conn: sqlite3.Connection | None = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Oldest-first dirty batch for the ranking worker."""
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    try:
        rows = conn.execute(
            """
            SELECT player_id, dirty_version, dirty_since, updated_at
            FROM player_score_dirty
            ORDER BY dirty_since ASC, player_id ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "player_id": int(row["player_id"]),
                    "dirty_version": int(row["dirty_version"]),
                    "dirty_since": float(row["dirty_since"] or 0),
                    "updated_at": float(row["updated_at"] or 0),
                }
            )
        return out
    finally:
        if owns_conn:
            conn.close()


def get_player_score_dirty(
    player_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> Optional[Dict[str, Any]]:
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    try:
        row = conn.execute(
            """
            SELECT player_id, dirty_version, dirty_since, updated_at
            FROM player_score_dirty
            WHERE player_id = ?
            LIMIT 1
            """,
            (int(player_id),),
        ).fetchone()
        if not row:
            return None
        return {
            "player_id": int(row["player_id"]),
            "dirty_version": int(row["dirty_version"]),
            "dirty_since": float(row["dirty_since"] or 0),
            "updated_at": float(row["updated_at"] or 0),
        }
    finally:
        if owns_conn:
            conn.close()


def clear_player_score_dirty_if_version(
    player_id: int,
    expected_version: int,
    *,
    conn: sqlite3.Connection,
) -> bool:
    """Compare-and-clear: only drop dirty when version still matches the batch read."""
    cur = conn.execute(
        """
        DELETE FROM player_score_dirty
        WHERE player_id = ? AND dirty_version = ?
        """,
        (int(player_id), int(expected_version)),
    )
    return int(cur.rowcount or 0) > 0


def clear_all_player_score_dirty(*, conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM player_score_dirty;")
    return int(cur.rowcount or 0)


def count_dirty_score_players(*, conn: sqlite3.Connection | None = None) -> int:
    owns_conn = conn is None
    if owns_conn:
        conn = db()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM player_score_dirty;").fetchone()
        return int(row["c"] if row else 0)
    finally:
        if owns_conn:
            conn.close()


def apply_score_updates_for_players(
    player_ids: Iterable[int],
    conn: sqlite3.Connection | None = None,
    *,
    recalc_ranks: bool = True,
    force_rank_recalc: bool = False,
    reason: str = "",
) -> int:
    """
    Invalidate scores for affected players (GC-SCORE-PERF-001).

    Does **not** run ``compute_player_scores`` and does **not** rewrite ranks.
    ``recalc_ranks`` / ``force_rank_recalc`` are accepted for call-site
    compatibility but ignored — the ranking worker refreshes ranks once per
    successful dirty batch.
    """
    del recalc_ranks, force_rank_recalc  # deferred to ranking_worker
    unique: Set[int] = {int(p) for p in player_ids if p is not None and int(p) > 0}
    if not unique:
        return 0

    started = time.perf_counter()
    count = 0
    for pid in sorted(unique):
        if mark_player_score_dirty(pid, conn=conn, reason=reason):
            count += 1

    if count > 0:
        logger.info(
            "score_dirty reason=%s players=%s duration_ms=%.1f",
            reason or "unspecified",
            count,
            (time.perf_counter() - started) * 1000.0,
        )
    return count
