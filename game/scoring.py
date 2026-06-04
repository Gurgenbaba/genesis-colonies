"""Empire score helpers — defense stock, combat destruction, military aggregate."""

from __future__ import annotations

from typing import Dict, Mapping

from .defense_defs import defense_score_value


def compute_destroyed_raw_from_losses(losses: Mapping[str, int]) -> int:
    """Raw destruction value from combat losses (sum of unit build costs)."""
    from .combat import unit_build_cost_for_debris

    total = 0
    for raw_key, raw_qty in losses.items():
        lost = max(0, int(raw_qty))
        if lost <= 0:
            continue
        metal, crystal = unit_build_cost_for_debris(str(raw_key))
        total += (int(metal) + int(crystal)) * lost
    return max(0, int(total))


def get_destroyed_raw(player_id: int, *, conn) -> int:
    """Cumulative destroyed-unit raw score persisted on ``player_scores``."""
    from .db import column_exists

    if not column_exists(conn, "player_scores", "score_destroyed_raw"):
        return 0
    cur = conn.cursor()
    cur.execute(
        "SELECT score_destroyed_raw FROM player_scores WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    )
    row = cur.fetchone()
    if not row:
        return 0
    try:
        return max(0, int(row["score_destroyed_raw"] or 0))
    except (TypeError, ValueError):
        return 0


def increment_destroyed_raw(player_id: int, delta: int, *, conn) -> None:
    """Add combat destruction credit (idempotent per battle via caller)."""
    from .db import column_exists
    from .ranking import backfill_player_score_rows

    add = max(0, int(delta))
    if add <= 0:
        return
    if not column_exists(conn, "player_scores", "score_destroyed_raw"):
        return
    backfill_player_score_rows(conn=conn)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE player_scores
        SET score_destroyed_raw = COALESCE(score_destroyed_raw, 0) + ?
        WHERE player_id = ?;
        """,
        (add, int(player_id)),
    )
    if cur.rowcount <= 0:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_buildings, score_research,
                score_destroyed_raw, updated_at
            )
            VALUES (?, 0, 0, 0, ?, strftime('%s','now'));
            """,
            (int(player_id), add),
        )


def record_combat_outcome(
    *,
    attacker_id: int,
    defender_id: int,
    attacker_losses: Mapping[str, int],
    defender_losses: Mapping[str, int],
    conn,
) -> None:
    """Credit destroyed-unit raw score to each side for units they eliminated."""
    atk_id = int(attacker_id)
    def_id = int(defender_id)
    if atk_id > 0 and sum((defender_losses or {}).values()) > 0:
        increment_destroyed_raw(
            atk_id,
            compute_destroyed_raw_from_losses(defender_losses),
            conn=conn,
        )
    if def_id > 0 and def_id != atk_id and sum((attacker_losses or {}).values()) > 0:
        increment_destroyed_raw(
            def_id,
            compute_destroyed_raw_from_losses(attacker_losses),
            conn=conn,
        )


def compute_combat_score(fleet_score: int, defense_score: int) -> int:
    """Active military ranking component (fleet + planetary defense)."""
    return max(0, int(fleet_score or 0)) + max(0, int(defense_score or 0))


def compute_military_score(
    fleet_score: int,
    defense_score: int,
    destroyed_score: int = 0,
) -> int:
    """Combined military ranking: active force + combat destruction credit."""
    return compute_combat_score(fleet_score, defense_score) + max(
        0, int(destroyed_score or 0)
    )


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


def attach_military_score(scores: Dict[str, int]) -> Dict[str, int]:
    """Return a copy with combat_score, destroyed_score, and military_score."""
    out = dict(scores)
    fleet = int(out.get("fleet_score") or out.get("score_fleet") or 0)
    defense = int(out.get("defense_score") or out.get("score_defense") or 0)
    destroyed = int(out.get("destroyed_score") or 0)
    out["combat_score"] = int(out.get("combat_score") or compute_combat_score(fleet, defense))
    out["destroyed_score"] = destroyed
    out["military_score"] = compute_military_score(fleet, defense, destroyed)
    return out
