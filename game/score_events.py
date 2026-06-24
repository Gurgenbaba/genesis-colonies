"""
Batch score updates — ranking worker and admin only (not gameplay hot paths).
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Set

from .ranking import invalidate_player_score_cache, recompute_and_upsert_score, recalculate_ranks


def apply_score_updates_for_players(
    player_ids: Iterable[int],
    conn: sqlite3.Connection | None = None,
    *,
    recalc_ranks: bool = True,
) -> int:
    """
    Recompute scores for affected players; recalculate ranks once at the end.
    Returns number of players updated.
    """
    unique: Set[int] = {int(p) for p in player_ids if p is not None}
    if not unique:
        return 0

    count = 0
    for pid in sorted(unique):
        recompute_and_upsert_score(int(pid), conn=conn, recalc_ranks=False)
        invalidate_player_score_cache(int(pid))
        count += 1

    if recalc_ranks:
        recalculate_ranks(conn=conn)

    return count
