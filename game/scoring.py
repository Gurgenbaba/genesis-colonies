"""Empire score helpers — defense stock and military aggregate."""

from __future__ import annotations

from typing import Dict

from .defense_defs import defense_score_value


def compute_defense_empire_sum(player_id: int, *, conn) -> int:
    """
    Raw defense empire value: sum(amount × score_value) over all owned planets.
    Exponent / weighting is applied in ranking.compute_player_scores().
    """
    from .models import get_player_defense_counts

    totals = get_player_defense_counts(int(player_id), conn=conn)
    total = 0
    for defense_key, qty in totals.items():
        count = int(qty or 0)
        if count <= 0:
            continue
        unit = defense_score_value(str(defense_key))
        if unit <= 0:
            continue
        total += unit * count
    return max(0, int(total))


def compute_military_score(fleet_score: int, defense_score: int) -> int:
    """Combined fleet + defense ranking component (not double-counted in total_score)."""
    return max(0, int(fleet_score or 0)) + max(0, int(defense_score or 0))


def attach_military_score(scores: Dict[str, int]) -> Dict[str, int]:
    """Return a copy with derived military_score."""
    out = dict(scores)
    out["military_score"] = compute_military_score(
        int(out.get("fleet_score") or out.get("score_fleet") or 0),
        int(out.get("defense_score") or out.get("score_defense") or 0),
    )
    return out
