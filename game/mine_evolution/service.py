"""Mine Evolution owner — Ascension action, rank persistence, production modifier."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from ..db import begin_write_transaction, commit, lock_planet_for_update, rollback, table_exists
from ..models import db, get_build_queue_rows, get_planet_buildings, try_spend_resources_conn
from .formulas import (
    EVOLVABLE_MINES,
    building_modifier_from_rank,
    is_evolvable_mine,
    required_level_for_evolution,
    roman_numeral,
    tribute_cost_for_next_rank,
)


def schema_ready(conn: sqlite3.Connection) -> bool:
    try:
        return table_exists(conn, "planet_mine_evolution")
    except Exception:
        return False


def get_evolution_rank(
    planet_id: int,
    building_type: str,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    if not is_evolvable_mine(building_type):
        return 0
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn):
            return 0
        cur = conn.cursor()
        cur.execute(
            """
            SELECT evolution_rank FROM planet_mine_evolution
            WHERE planet_id = ? AND building_type = ? LIMIT 1;
            """,
            (int(planet_id), str(building_type)),
        )
        row = cur.fetchone()
        if not row:
            return 0
        return max(0, int(row["evolution_rank"] if isinstance(row, sqlite3.Row) else row[0]) or 0)
    finally:
        if own:
            conn.close()


def get_evolution_ranks_for_planet(
    planet_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, int]:
    """Return ranks for all evolvable mines (missing → 0)."""
    out = {k: 0 for k in EVOLVABLE_MINES}
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn):
            return out
        cur = conn.cursor()
        cur.execute(
            """
            SELECT building_type, evolution_rank FROM planet_mine_evolution
            WHERE planet_id = ?;
            """,
            (int(planet_id),),
        )
        for row in cur.fetchall():
            bt = str(row["building_type"] if isinstance(row, sqlite3.Row) else row[0])
            if bt in out:
                rank = int(row["evolution_rank"] if isinstance(row, sqlite3.Row) else row[1]) or 0
                out[bt] = max(0, rank)
        return out
    finally:
        if own:
            conn.close()


def building_modifier_for(
    planet_id: int,
    building_type: str,
    conn: Optional[sqlite3.Connection] = None,
    *,
    ranks: Optional[Dict[str, int]] = None,
) -> float:
    if not is_evolvable_mine(building_type):
        return 1.0
    if ranks is not None:
        rank = int(ranks.get(building_type, 0) or 0)
    else:
        rank = get_evolution_rank(planet_id, building_type, conn=conn)
    return building_modifier_from_rank(rank)


def _progress_percent_exact(value: Any, required: Any) -> int:
    """Round value/required to a bounded 0..100 percent without float conversion."""
    numerator = max(0, int(value or 0)) * 100
    denominator = int(required or 0)
    if denominator <= 0:
        return 0
    quotient, remainder = divmod(numerator, denominator)
    doubled = remainder * 2
    if doubled > denominator or (doubled == denominator and quotient % 2):
        quotient += 1
    return max(0, min(100, quotient))


def panel_evolution_fields(
    planet_id: Optional[int],
    building_type: str,
    level: int,
    *,
    ranks: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """SSR/UI fields for building cards. Non-mines → empty/disabled."""
    if not is_evolvable_mine(building_type) or planet_id is None:
        return {
            "mine_evolution": False,
            "evolution_rank": 0,
            "evolution_roman": "",
            "evolution_next_roman": "",
            "evolution_required_level": 0,
            "evolution_can_evolve": False,
            "evolution_bonus_pct": 0.0,
            "evolution_next_bonus_pct": 0.0,
            "evolution_bonus_gain_pct": 0.0,
            "evolution_uncapped": False,
            "evolution_tribute_metal": 0,
            "evolution_tribute_crystal": 0,
        }
    if ranks is not None:
        rank = int(ranks.get(building_type, 0) or 0)
    else:
        rank = get_evolution_rank(int(planet_id), building_type)
    next_n = rank + 1
    required = required_level_for_evolution(next_n)
    bonus = building_modifier_from_rank(rank) - 1.0
    next_bonus = building_modifier_from_rank(next_n) - 1.0
    tribute_m, tribute_c = tribute_cost_for_next_rank(building_type, next_n)
    lvl = int(level or 0)
    progress_pct = _progress_percent_exact(lvl, required)
    return {
        "mine_evolution": True,
        "evolution_rank": rank,
        "evolution_roman": roman_numeral(rank),
        "evolution_next_roman": roman_numeral(next_n),
        "evolution_required_level": required,
        "evolution_can_evolve": lvl >= required,
        "evolution_bonus_pct": round(bonus * 100.0, 2),
        "evolution_next_bonus_pct": round(next_bonus * 100.0, 2),
        "evolution_bonus_gain_pct": round((next_bonus - bonus) * 100.0, 2),
        "evolution_progress_pct": progress_pct,
        "evolution_uncapped": True,
        "evolution_tribute_metal": int(tribute_m),
        "evolution_tribute_crystal": int(tribute_c),
    }


def evolve_mine(
    user_id: int,
    planet: dict,
    building_type: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Finish due work, then Ascend a production mine on the context planet.

    Level is kept. Player pays milestone tribute; rank increases by one.
    Returns (ok, reason, payload).
    """
    bt = str(building_type or "").strip()
    if not is_evolvable_mine(bt):
        return False, "invalid_building", {"msg": "Not an evolvable mine"}

    planet_id = int(planet["id"])
    owner_id = int(planet.get("player_id") or 0)
    if owner_id != int(user_id):
        return False, "forbidden", {"msg": "Planet not owned"}

    from ..options import vacation_blocks_outbound

    # GC-MINE-ASC-NEXUS-001: reuse the mutation connection for the vacation
    # probe instead of leaking an orphan checkout immediately before the TX.
    conn = db()
    try:
        ok_vacation, vac_reason = vacation_blocks_outbound(int(user_id), conn=conn)
        if not ok_vacation:
            return False, vac_reason, {}

        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)

        if not schema_ready(conn):
            rollback(conn)
            return False, "schema_missing", {"msg": "Mine evolution schema not applied"}

        now = time.time()
        from ..queue_engine import finish_due_work

        finish_due_work(
            player_id=int(user_id),
            planet_id=planet_id,
            now=now,
            conn=conn,
            source="action",
            recalc_ranks=False,
        )

        buildings = get_planet_buildings(planet_id, conn=conn)
        level = int(buildings.get(bt, 0) or 0)
        rank = get_evolution_rank(planet_id, bt, conn=conn)
        next_rank = rank + 1
        required = required_level_for_evolution(next_rank)

        if level < required:
            rollback(conn)
            return False, "level_too_low", {
                "msg": "Mine level below evolution threshold",
                "level": level,
                "required": required,
                "evolution_rank": rank,
            }

        pending = [
            r
            for r in get_build_queue_rows(planet_id, conn=conn)
            if str(r["building_type"]) == bt
        ]
        if pending:
            rollback(conn)
            return False, "queue_pending", {
                "msg": "Cancel or finish mine build jobs before evolving",
                "pending": len(pending),
            }

        tribute_m, tribute_c = tribute_cost_for_next_rank(bt, next_rank)
        if not try_spend_resources_conn(conn, planet_id, int(tribute_m), int(tribute_c)):
            rollback(conn)
            return False, "insufficient_resources", {
                "msg": "Not enough resources for Ascension tribute",
                "cost_metal": int(tribute_m),
                "cost_crystal": int(tribute_c),
                "evolution_rank": rank,
            }

        new_rank = next_rank
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planet_mine_evolution (planet_id, building_type, evolution_rank, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(planet_id, building_type) DO UPDATE SET
                evolution_rank = excluded.evolution_rank,
                updated_at = excluded.updated_at;
            """,
            (planet_id, bt, new_rank, float(now)),
        )
        commit(conn)

        return True, "ok", {
            "building_type": bt,
            "level": level,
            "evolution_rank": new_rank,
            "evolution_roman": roman_numeral(new_rank),
            "evolution_bonus_pct": round((building_modifier_from_rank(new_rank) - 1.0) * 100.0, 2),
            "next_required_level": required_level_for_evolution(new_rank + 1),
            "tribute_metal": int(tribute_m),
            "tribute_crystal": int(tribute_c),
        }
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
