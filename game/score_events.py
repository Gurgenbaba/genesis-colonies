"""
Live score updates after gameplay mutations (queue finish, combat, admin).

Full-universe recompute remains in ``ranking_worker`` as a safety net.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Iterable, Set

from .ranking import invalidate_player_score_cache, recompute_and_upsert_score, recalculate_ranks

logger = logging.getLogger(__name__)

RANK_RECALC_MIN_INTERVAL_SEC = 45
RANK_RECALC_RUNTIME_KEY = "ranking_live_recalc_last_at"


def _rank_recalc_allowed(conn: sqlite3.Connection | None, *, force: bool) -> bool:
    if force:
        return True
    from .runtime_state import get_runtime_value

    raw = get_runtime_value(RANK_RECALC_RUNTIME_KEY, conn=conn)
    if not raw:
        return True
    try:
        last_at = float(raw)
    except (TypeError, ValueError):
        return True
    return (time.time() - last_at) >= float(RANK_RECALC_MIN_INTERVAL_SEC)


def _mark_rank_recalc(conn: sqlite3.Connection | None) -> None:
    from .runtime_state import set_runtime_value

    set_runtime_value(RANK_RECALC_RUNTIME_KEY, str(time.time()), conn=conn)


def apply_score_updates_for_players(
    player_ids: Iterable[int],
    conn: sqlite3.Connection | None = None,
    *,
    recalc_ranks: bool = True,
    force_rank_recalc: bool = False,
    reason: str = "",
) -> int:
    """
    Recompute scores for affected players; optionally recalculate ranks once at the end.

    Only touches the given player IDs — never full-universe score recompute.
    Rank reassignment is throttled (``RANK_RECALC_MIN_INTERVAL_SEC``) unless forced.
    Returns number of players updated.
    """
    unique: Set[int] = {int(p) for p in player_ids if p is not None and int(p) > 0}
    if not unique:
        return 0

    started = time.perf_counter()
    count = 0
    did_recalc = False
    for pid in sorted(unique):
        recompute_and_upsert_score(int(pid), conn=conn, recalc_ranks=False)
        invalidate_player_score_cache(int(pid))
        count += 1

    if recalc_ranks and count > 0 and _rank_recalc_allowed(conn, force=force_rank_recalc):
        recalculate_ranks(conn=conn)
        _mark_rank_recalc(conn)
        did_recalc = True
    else:
        did_recalc = False

    if count > 0:
        logger.info(
            "score_updates reason=%s players=%s rank_recalc=%s duration_ms=%.1f",
            reason or "unspecified",
            count,
            did_recalc,
            (time.perf_counter() - started) * 1000.0,
        )

    return count
