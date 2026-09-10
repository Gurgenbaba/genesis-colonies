"""Research Lab Ascension — endgame queue capacity + small research-speed prestige.

GC-RESEARCH-NET-ASC-001

The account research queue remains strictly sequential.  This module only owns
Research Lab prestige state and the server-authoritative capacity resolver.
Ranks are stored per planet, but empire capacity is determined by the strongest
single lab; ranks from multiple colonies are never summed.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from .db import (
    begin_write_transaction,
    commit,
    lock_planet_for_update,
    lock_player_for_update,
    rollback,
    table_exists,
)
from .models import (
    db,
    get_build_queue_rows,
    get_game_settings,
    get_homeworld,
    get_planet_buildings,
    try_spend_resources_conn,
)

MAX_ASCENSION_RANK = 5
BASE_SLOT_FLOOR = 2
BASE_SLOT_CAP = 5
PRESTIGE_SLOT_CAP = 10
ASCENSION_SPEED_PER_RANK = 0.02

ASCENSION_RESOURCE_WEIGHTS: Dict[int, Tuple[int, int]] = {
    1: (40, 60),
    2: (35, 65),
    3: (30, 70),
    4: (25, 75),
    5: (20, 80),
}

_ROMAN = {0: "0", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


def roman_rank(rank: int) -> str:
    return _ROMAN.get(max(0, min(MAX_ASCENSION_RANK, int(rank or 0))), str(int(rank or 0)))


def schema_ready(conn) -> bool:
    try:
        return table_exists(conn, "research_lab_ascension")
    except Exception:
        return False


def base_slots_for_lab_level(level: int) -> int:
    """2 starter slots; visible progression starts at L30 and caps at five."""
    lvl = max(0, int(level or 0))
    return min(BASE_SLOT_CAP, max(BASE_SLOT_FLOOR, lvl // 10))


def required_level_for_rank(rank: int) -> int:
    """Rank I at 50, II at 60, ... V at 90. 0 means no further rank."""
    r = int(rank or 0)
    if r < 1 or r > MAX_ASCENSION_RANK:
        return 0
    return 40 + 10 * r


def max_lab_level_for_rank(rank: int) -> int:
    """Rank 0→L50, I→L60, ... V→L100."""
    r = max(0, min(MAX_ASCENSION_RANK, int(rank or 0)))
    return 50 + 10 * r


def ascension_speed_multiplier(rank: int) -> float:
    r = max(0, min(MAX_ASCENSION_RANK, int(rank or 0)))
    return 1.0 + ASCENSION_SPEED_PER_RANK * r


def tribute_cost_for_rank(rank: int) -> Tuple[int, int]:
    """Derive tribute from the existing endgame Ascension curve, then re-weight.

    The total is the canonical Mine-Evolution tribute computed from
    power_upgrade_cost() for a Research Lab at the rank gate.  Only its resource
    split changes to the research-specific Crytite-heavy weighting.
    """
    r = int(rank or 0)
    if r not in ASCENSION_RESOURCE_WEIGHTS:
        return 0, 0
    gate = required_level_for_rank(r)
    from .buildings import get_upgrade_cost

    # Same endgame Ascension anchor as the mine system: 25% of the canonical
    # upgrade spend across the 40 levels ending at the rank milestone.
    total_upgrade_spend = 0
    for target_level in range(max(1, gate - 39), gate + 1):
        metal_cost, crystal_cost = get_upgrade_cost("research_lab", target_level - 1)
        total_upgrade_spend += int(metal_cost) + int(crystal_cost)
    total = total_upgrade_spend // 4
    metal_pct, _crystal_pct = ASCENSION_RESOURCE_WEIGHTS[r]
    # Positive integer half-up rounding; crystal receives the exact remainder.
    metal = (total * int(metal_pct) + 50) // 100
    crystal = total - metal
    return int(metal), int(crystal)


def get_planet_ascension_rank(planet_id: int, *, conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn):
            return 0
        row = conn.execute(
            "SELECT rank FROM research_lab_ascension WHERE planet_id = ? LIMIT 1;",
            (int(planet_id),),
        ).fetchone()
        if not row:
            return 0
        return max(0, min(MAX_ASCENSION_RANK, int(row["rank"] or 0)))
    finally:
        if own:
            conn.close()


def _configured_queue_limit(settings: Dict[str, Any]) -> int:
    raw = settings.get("research_queue_limit", BASE_SLOT_FLOOR)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            value = BASE_SLOT_FLOOR
    return max(1, value)


def _best_lab_row(user_id: int, *, conn) -> Dict[str, int]:
    """One empire read: select the single lab with the greatest prestige capacity."""
    uid = int(user_id)
    if schema_ready(conn):
        row = conn.execute(
            """
            SELECT p.id AS planet_id,
                   COALESCE(pb.research_lab, 0) AS lab_level,
                   COALESCE(rla.rank, 0) AS ascension_rank
            FROM planets p
            INNER JOIN planet_buildings pb ON pb.planet_id = p.id
            LEFT JOIN research_lab_ascension rla ON rla.planet_id = p.id
            WHERE p.player_id = ?
            ORDER BY
                (CASE
                    WHEN COALESCE(pb.research_lab, 0) >= 50 THEN 5
                    WHEN COALESCE(pb.research_lab, 0) >= 40 THEN 4
                    WHEN COALESCE(pb.research_lab, 0) >= 30 THEN 3
                    ELSE 2
                 END + COALESCE(rla.rank, 0)) DESC,
                COALESCE(pb.research_lab, 0) DESC,
                COALESCE(rla.rank, 0) DESC,
                p.id ASC
            LIMIT 1;
            """,
            (uid,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT p.id AS planet_id, COALESCE(pb.research_lab, 0) AS lab_level
            FROM planets p
            INNER JOIN planet_buildings pb ON pb.planet_id = p.id
            WHERE p.player_id = ?
            ORDER BY COALESCE(pb.research_lab, 0) DESC, p.id ASC
            LIMIT 1;
            """,
            (uid,),
        ).fetchone()
    if not row:
        return {"planet_id": 0, "lab_level": 0, "ascension_rank": 0}
    return {
        "planet_id": int(row["planet_id"] or 0),
        "lab_level": max(0, int(row["lab_level"] or 0)),
        "ascension_rank": max(
            0,
            min(MAX_ASCENSION_RANK, int(row["ascension_rank"] or 0))
            if "ascension_rank" in row.keys()
            else 0,
        ),
    }


def research_queue_capacity(
    user_id: int,
    *,
    conn=None,
    settings: Optional[Dict[str, Any]] = None,
    include_external_bonus: bool = True,
) -> Dict[str, Any]:
    """Canonical account research capacity resolver.

    Base prestige is capped at 10 (5 lab + 5 ascension). Existing universe
    overrides remain floors and Galactic Directive slots stay additive.
    """
    own = conn is None
    if own:
        conn = db()
    try:
        best = _best_lab_row(int(user_id), conn=conn)
        level = int(best["lab_level"])
        rank = int(best["ascension_rank"])
        base = base_slots_for_lab_level(level)
        prestige_limit = min(PRESTIGE_SLOT_CAP, base + rank)

        if settings is None:
            try:
                settings = get_game_settings(conn=conn)
            except TypeError:
                settings = get_game_settings()
        configured = _configured_queue_limit(settings or {})
        effective = max(BASE_SLOT_FLOOR, configured, prestige_limit)

        external_bonus = 0
        if include_external_bonus:
            try:
                from .galactic_directives.mechanics import get_directive_queue_limit_bonus

                hw = get_homeworld(int(user_id), conn=conn) or {}
                galaxy = int(hw.get("galaxy") or 0)
                if galaxy > 0:
                    external_bonus = max(
                        0,
                        int(get_directive_queue_limit_bonus(galaxy, "research", conn=conn) or 0),
                    )
            except Exception:
                external_bonus = 0
        limit = effective + external_bonus

        next_unlock: Optional[Dict[str, Any]] = None
        if level < 30:
            next_unlock = {"kind": "lab", "lab_level": 30, "slots": 3}
        elif level < 40:
            next_unlock = {"kind": "lab", "lab_level": 40, "slots": 4}
        elif level < 50:
            next_unlock = {"kind": "lab", "lab_level": 50, "slots": 5}
        elif rank < MAX_ASCENSION_RANK:
            next_rank = rank + 1
            gate = required_level_for_rank(next_rank)
            next_unlock = {
                "kind": "ascension",
                "rank": next_rank,
                "roman": roman_rank(next_rank),
                "lab_level": gate,
                "slots": min(PRESTIGE_SLOT_CAP, BASE_SLOT_CAP + next_rank),
                "ready": level >= gate,
            }

        next_tribute_metal = 0
        next_tribute_crystal = 0
        if next_unlock and next_unlock.get("kind") == "ascension":
            next_tribute_metal, next_tribute_crystal = tribute_cost_for_rank(
                int(next_unlock.get("rank") or 0)
            )

        return {
            "base": int(base),
            "lab_level": int(level),
            "ascension_rank": int(rank),
            "ascension_roman": roman_rank(rank) if rank > 0 else "",
            "ascension_bonus": int(rank),
            "prestige_limit": int(prestige_limit),
            "configured_limit": int(configured),
            "external_bonus": int(external_bonus),
            "limit": int(limit),
            "best_planet_id": int(best["planet_id"]),
            "research_speed_bonus_pct": int(rank * 2),
            "next_tribute_metal": int(next_tribute_metal),
            "next_tribute_crystal": int(next_tribute_crystal),
            "next_unlock": next_unlock,
        }
    finally:
        if own:
            conn.close()


def panel_fields(
    user_id: int,
    planet_id: int,
    level: int,
    *,
    conn=None,
) -> Dict[str, Any]:
    """Building-card fields for one Research Lab."""
    rank = get_planet_ascension_rank(int(planet_id), conn=conn)
    next_rank = rank + 1
    gate = required_level_for_rank(next_rank)
    tribute_m, tribute_c = tribute_cost_for_rank(next_rank)
    local_prestige_capacity = min(
        PRESTIGE_SLOT_CAP,
        base_slots_for_lab_level(int(level or 0)) + int(rank),
    )
    return {
        "research_lab_ascension": True,
        "research_queue_capacity": int(local_prestige_capacity),
        "research_queue_prestige_capacity": int(local_prestige_capacity),
        "research_lab_ascension_rank": int(rank),
        "research_lab_ascension_roman": roman_rank(rank) if rank else "",
        "research_lab_next_rank": int(next_rank) if next_rank <= MAX_ASCENSION_RANK else 0,
        "research_lab_next_roman": roman_rank(next_rank) if next_rank <= MAX_ASCENSION_RANK else "",
        "research_lab_ascension_required_level": int(gate),
        "research_lab_ascension_ready": bool(gate and int(level or 0) >= gate),
        "research_lab_ascension_max_level": int(max_lab_level_for_rank(rank)),
        "research_lab_ascension_speed_bonus_pct": int(rank * 2),
        "research_lab_ascension_tribute_metal": int(tribute_m),
        "research_lab_ascension_tribute_crystal": int(tribute_c),
    }


def ascend_research_lab(
    user_id: int,
    planet: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Atomically ascend the context planet Research Lab by one rank."""
    uid = int(user_id)
    planet_id = int(planet.get("id") or 0)
    if planet_id <= 0 or int(planet.get("player_id") or 0) != uid:
        return False, "forbidden", {}

    from .options import vacation_blocks_outbound

    conn = db()
    try:
        ok_vacation, vac_reason = vacation_blocks_outbound(uid, conn=conn)
        if not ok_vacation:
            return False, vac_reason, {}

        begin_write_transaction(conn)
        lock_player_for_update(conn, uid)
        lock_planet_for_update(conn, planet_id)
        if not schema_ready(conn):
            rollback(conn)
            return False, "schema_missing", {}

        now = int(time.time())
        from .queue_engine import finish_due_work

        finish_due_work(
            player_id=uid,
            planet_id=planet_id,
            now=float(now),
            conn=conn,
            source="action",
            recalc_ranks=False,
        )

        buildings = get_planet_buildings(planet_id, conn=conn)
        level = int(buildings.get("research_lab", 0) or 0)
        rank = get_planet_ascension_rank(planet_id, conn=conn)
        if rank >= MAX_ASCENSION_RANK:
            rollback(conn)
            return False, "max_ascension", {"rank": rank, "level": level}

        next_rank = rank + 1
        required = required_level_for_rank(next_rank)
        if level < required:
            rollback(conn)
            return False, "level_too_low", {
                "rank": rank,
                "level": level,
                "required": required,
            }

        pending = [
            r for r in get_build_queue_rows(planet_id, conn=conn)
            if str(r["building_type"]) == "research_lab"
        ]
        if pending:
            rollback(conn)
            return False, "queue_pending", {"pending": len(pending)}

        tribute_m, tribute_c = tribute_cost_for_rank(next_rank)
        if not try_spend_resources_conn(conn, planet_id, int(tribute_m), int(tribute_c)):
            rollback(conn)
            return False, "insufficient_resources", {
                "cost_metal": int(tribute_m),
                "cost_crystal": int(tribute_c),
                "rank": rank,
            }

        # Planet row lock serializes this state transition on Postgres; SQLite's
        # BEGIN IMMEDIATE serializes the writer. The update remains conditional so
        # any unexpected stale rank rolls the entire transaction back with no debit.
        if rank <= 0:
            cur = conn.execute(
                """
                INSERT INTO research_lab_ascension (planet_id, rank, ascended_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(planet_id) DO NOTHING;
                """,
                (planet_id, next_rank, now, now),
            )
        else:
            cur = conn.execute(
                """
                UPDATE research_lab_ascension
                SET rank = ?, ascended_at = ?, updated_at = ?
                WHERE planet_id = ? AND rank = ?;
                """,
                (next_rank, now, now, planet_id, rank),
            )
        if int(cur.rowcount or 0) != 1:
            rollback(conn)
            return False, "ascension_race", {"rank": rank}

        commit(conn)
        capacity = research_queue_capacity(uid, conn=conn)
        return True, "ok", {
            "planet_id": planet_id,
            "level": level,
            "ascension_rank": next_rank,
            "ascension_roman": roman_rank(next_rank),
            "research_speed_bonus_pct": next_rank * 2,
            "max_lab_level": max_lab_level_for_rank(next_rank),
            "tribute_metal": int(tribute_m),
            "tribute_crystal": int(tribute_c),
            "capacity": capacity,
        }
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        conn.close()
