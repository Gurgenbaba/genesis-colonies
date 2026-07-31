"""
Galactic ranking service – single source of truth for scores and ranks.

Score persistence is refreshed live after gameplay mutations (``score_events``) and
periodically by ``ranking_worker`` (10-minute safety net). Gameplay reads ``player_scores`` snapshots only.

Wealth score (``total_score``) = resources + buildings + research + fleet + defense + evolution
(computed via ``game.resource_score`` — canonical 1500/1000/500 divisors).

``destroyed_score`` = lifetime combat prestige — **excluded** from ``total_score``.
``combat_score`` = fleet_score + defense_score (active military).
``military_score`` = combat_score + destroyed_score (display / military tab only).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .db import begin_write_transaction, column_exists, commit, db, rollback, table_exists

logger = logging.getLogger(__name__)

RANKING_INACTIVE_AFTER_SEC = 3 * 24 * 3600

# player_id -> (timestamp, normalized score dict)
_CACHE: Dict[int, Tuple[float, Dict[str, int]]] = {}
CACHE_TTL_SECONDS: float = 2.0

# Serialize full rank snapshots (SQLite write safety under parallel requests).
_RANKING_LOCK = threading.RLock()

# Max stored score (JSON / int64-safe for clients).
MAX_SCORE = 9_000_000_000_000_000


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 0:
        return 0
    if n > MAX_SCORE:
        return MAX_SCORE
    return n


def _sanitize_scores(scores: Dict[str, Any]) -> Dict[str, int]:
    resources = _safe_int(scores.get("resource_score", scores.get("score_resources", 0)))
    building = _safe_int(scores.get("building_score", scores.get("score_buildings", 0)))
    research = _safe_int(scores.get("research_score", scores.get("score_research", 0)))
    fleet = _safe_int(scores.get("fleet_score", scores.get("score_fleet", 0)))
    defense = _safe_int(scores.get("defense_score", scores.get("score_defense", 0)))
    destroyed = _safe_int(scores.get("destroyed_score", scores.get("score_destroyed", 0)))
    evolution = _safe_int(scores.get("evolution_score", scores.get("score_planet_evolution", 0)))
    from .scoring import compute_combat_score, compute_military_score

    combat = _safe_int(
        scores.get("combat_score", scores.get("score_combat", compute_combat_score(fleet, defense)))
    )
    total = _safe_int(resources + building + research + fleet + defense + evolution)
    destroyed_raw = _safe_int(scores.get("destroyed_raw", scores.get("score_destroyed_raw", 0)))

    return {
        "total_score": total,
        "resource_score": resources,
        "building_score": building,
        "research_score": research,
        "fleet_score": fleet,
        "defense_score": defense,
        "combat_score": combat,
        "destroyed_score": destroyed,
        "destroyed_raw": destroyed_raw,
        "military_score": compute_military_score(fleet, defense, destroyed),
        "evolution_score": evolution,
    }


def invalidate_player_score_cache(player_id: int) -> None:
    try:
        _CACHE.pop(int(player_id), None)
    except Exception:
        pass


def invalidate_all_score_cache() -> None:
    try:
        _CACHE.clear()
    except Exception:
        pass


def _zero_scores() -> Dict[str, int]:
    return _sanitize_scores({})


def _compute_fleet_score(player_id: int, conn) -> int:
    """Fleet wealth score from hull build costs (canonical resource_score)."""
    from .fleet import get_player_owned_ship_counts
    from .resource_score import score_from_cost_dict
    from .shipyard import _unit_build_cost

    total = 0
    for ship_key, qty in get_player_owned_ship_counts(int(player_id), conn=conn).items():
        count = int(qty or 0)
        if count <= 0:
            continue
        unit = score_from_cost_dict(_unit_build_cost(str(ship_key)))
        if unit <= 0:
            continue
        total += unit * count
    return _safe_int(total)


def _compute_defense_score(player_id: int, conn) -> int:
    """Defense wealth score from unit build costs (canonical resource_score)."""
    from .defense_defs import unit_build_cost
    from .models import get_player_defense_counts
    from .resource_score import score_from_cost_dict

    total = 0
    for defense_key, qty in get_player_defense_counts(int(player_id), conn=conn).items():
        count = int(qty or 0)
        if count <= 0:
            continue
        unit = score_from_cost_dict(unit_build_cost(str(defense_key)))
        if unit <= 0:
            continue
        total += unit * count
    return _safe_int(total)


def _compute_building_score(player_id: int, conn) -> int:
    from .buildings import BUILDING_ORDER
    from .economy_balance import cumulative_upgrade_resource_totals
    from .models import get_planet_buildings, get_planets_by_player
    from .resource_score import score_from_cost_dict

    total_metal = 0
    total_crystal = 0
    total_fuel = 0
    for planet in get_planets_by_player(int(player_id), conn=conn):
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        for key in BUILDING_ORDER:
            level = int(buildings.get(key, 0) or 0)
            if level <= 0:
                continue
            totals = cumulative_upgrade_resource_totals(key, level)
            total_metal += int(totals.get("metal") or 0)
            total_crystal += int(totals.get("crystal") or 0)
            total_fuel += int(totals.get("fuel_cells") or 0)
    return score_from_cost_dict(
        {"metal": total_metal, "crystal": total_crystal, "fuel_cells": total_fuel}
    )


def _compute_research_score(player_id: int, conn) -> int:
    from .models import get_research_levels
    from .research import RESEARCH_TECHS, cumulative_research_resource_totals
    from .resource_score import score_from_cost_dict

    total_metal = 0
    total_crystal = 0
    total_fuel = 0
    levels = get_research_levels(int(player_id), conn=conn)
    for tech_key in RESEARCH_TECHS:
        level = int(levels.get(tech_key, 0) or 0)
        if level <= 0:
            continue
        totals = cumulative_research_resource_totals(tech_key, level)
        total_metal += int(totals.get("metal") or 0)
        total_crystal += int(totals.get("crystal") or 0)
        total_fuel += int(totals.get("fuel_cells") or 0)
    return score_from_cost_dict(
        {"metal": total_metal, "crystal": total_crystal, "fuel_cells": total_fuel}
    )


def _compute_resources_score(player_id: int, conn) -> int:
    from .models import get_planets_by_player
    from .resource_score import score_from_resources

    total_metal = 0
    total_crystal = 0
    total_fuel = 0
    for planet in get_planets_by_player(int(player_id), conn=conn):
        total_metal += int(float(planet.get("metal") or 0))
        total_crystal += int(float(planet.get("crystal") or 0))
        total_fuel += int(float(planet.get("fuel_cells") or 0))
    return score_from_resources(total_metal, total_crystal, total_fuel)


def compute_player_scores(
    player_id: int,
    conn=None,
) -> Dict[str, int]:
    """
    Central score calculation. Returns component scores and total_score as their sum.
    """
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    try:
        from .scoring import compute_combat_score, get_destroyed_raw

        resource_score = _compute_resources_score(int(player_id), conn)
        building_score = _compute_building_score(int(player_id), conn)
        research_score = _compute_research_score(int(player_id), conn)
        fleet_score = _compute_fleet_score(int(player_id), conn)
        defense_score = _compute_defense_score(int(player_id), conn)
        destroyed_raw = get_destroyed_raw(int(player_id), conn=conn)
        destroyed_score = _safe_int(destroyed_raw)
        combat_score = compute_combat_score(fleet_score, defense_score)
        evolution_score = 0
        try:
            from .planet_evolution.scoring import compute_player_evolution_score

            evolution_score = compute_player_evolution_score(int(player_id), conn)
        except Exception:
            evolution_score = 0

        return _sanitize_scores(
            {
                "resource_score": resource_score,
                "building_score": building_score,
                "research_score": research_score,
                "fleet_score": fleet_score,
                "defense_score": defense_score,
                "combat_score": combat_score,
                "destroyed_score": destroyed_score,
                "destroyed_raw": destroyed_raw,
                "evolution_score": evolution_score,
            }
        )
    finally:
        if owns_conn:
            conn.close()


def _normalize_db_row(row: Optional[dict]) -> Dict[str, int]:
    if not row:
        return _zero_scores()
    keys = row.keys() if hasattr(row, "keys") else ()
    building = _safe_int(row.get("score_buildings", 0))
    research = _safe_int(row.get("score_research", 0))
    resources = (
        _safe_int(row.get("score_resources", 0)) if "score_resources" in keys else 0
    )
    fleet = _safe_int(row.get("score_fleet", 0)) if "score_fleet" in keys else 0
    defense = _safe_int(row.get("score_defense", 0)) if "score_defense" in keys else 0
    evolution = (
        _safe_int(row.get("score_planet_evolution", 0))
        if "score_planet_evolution" in keys
        else 0
    )
    destroyed = _safe_int(row.get("score_destroyed", 0)) if "score_destroyed" in keys else 0
    combat = _safe_int(row.get("score_combat", 0)) if "score_combat" in keys else 0
    destroyed_raw = (
        _safe_int(row.get("score_destroyed_raw", 0)) if "score_destroyed_raw" in keys else 0
    )
    result = _sanitize_scores(
        {
            "resource_score": resources,
            "building_score": building,
            "research_score": research,
            "fleet_score": fleet,
            "defense_score": defense,
            "combat_score": combat,
            "destroyed_score": destroyed,
            "destroyed_raw": destroyed_raw,
            "evolution_score": evolution,
        }
    )
    return result


def format_scores_for_playercard(normalized: Dict[str, int]) -> Dict[str, int]:
    """Map internal normalized scores to PlayerCard template/API field names."""
    fleet = int(normalized.get("fleet_score", 0) or 0)
    defense = int(normalized.get("defense_score", 0) or 0)
    destroyed = int(normalized.get("destroyed_score", 0) or 0)
    combat = int(normalized.get("combat_score", 0) or 0)
    military = int(normalized.get("military_score", 0) or 0)
    return {
        "score_total": int(normalized.get("total_score", 0) or 0),
        "score_resources": int(normalized.get("resource_score", 0) or 0),
        "score_buildings": int(normalized.get("building_score", 0) or 0),
        "score_research": int(normalized.get("research_score", 0) or 0),
        "score_fleet": fleet,
        "score_defense": defense,
        "score_combat": combat,
        "score_destroyed": destroyed,
        "score_military": military,
        "score_planet_evolution": int(normalized.get("evolution_score", 0) or 0),
        # Backward-compatible aliases (ranking/HUD internals)
        "total_score": int(normalized.get("total_score", 0) or 0),
        "resource_score": int(normalized.get("resource_score", 0) or 0),
        "building_score": int(normalized.get("building_score", 0) or 0),
        "research_score": int(normalized.get("research_score", 0) or 0),
        "fleet_score": fleet,
        "defense_score": defense,
        "combat_score": combat,
        "destroyed_score": destroyed,
        "military_score": military,
        "evolution_score": int(normalized.get("evolution_score", 0) or 0),
    }


def _normalize_payload(data: Optional[dict]) -> Dict[str, int]:
    if not data:
        return _zero_scores()
    if "total_score" in data or "building_score" in data:
        return _sanitize_scores(data)
    return _sanitize_scores(
        {
            "building_score": data.get("score_buildings", 0),
            "research_score": data.get("score_research", 0),
            "fleet_score": data.get("score_fleet", 0),
            "defense_score": data.get("score_defense", 0),
        }
    )


def _total_score_sql(conn) -> str:
    parts = []
    if column_exists(conn, "player_scores", "score_resources"):
        parts.append("COALESCE(ps.score_resources, 0)")
    parts.extend(
        [
            "COALESCE(ps.score_buildings, 0)",
            "COALESCE(ps.score_research, 0)",
        ]
    )
    if column_exists(conn, "player_scores", "score_fleet"):
        parts.append("COALESCE(ps.score_fleet, 0)")
        parts.append("COALESCE(ps.score_defense, 0)")
    if column_exists(conn, "player_scores", "score_planet_evolution"):
        parts.append("COALESCE(ps.score_planet_evolution, 0)")
    return "(" + " + ".join(parts) + ")"


def upsert_player_scores(
    player_id: int,
    scores: Dict[str, int],
    conn=None,
) -> None:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    clean = _sanitize_scores(scores)
    cur = conn.cursor()
    has_extended = column_exists(conn, "player_scores", "score_fleet")
    has_evolution = column_exists(conn, "player_scores", "score_planet_evolution")
    has_combat = column_exists(conn, "player_scores", "score_combat")
    has_resources = column_exists(conn, "player_scores", "score_resources")

    if has_extended and has_evolution and has_combat and has_resources:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_resources, score_buildings, score_research,
                score_fleet, score_defense, score_planet_evolution,
                score_destroyed_raw, score_combat, score_destroyed, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total = excluded.score_total,
                score_resources = excluded.score_resources,
                score_buildings = excluded.score_buildings,
                score_research = excluded.score_research,
                score_fleet = excluded.score_fleet,
                score_defense = excluded.score_defense,
                score_planet_evolution = excluded.score_planet_evolution,
                score_destroyed_raw = excluded.score_destroyed_raw,
                score_combat = excluded.score_combat,
                score_destroyed = excluded.score_destroyed,
                updated_at = excluded.updated_at
            """,
            (
                int(player_id),
                clean["total_score"],
                clean["resource_score"],
                clean["building_score"],
                clean["research_score"],
                clean["fleet_score"],
                clean["defense_score"],
                clean["evolution_score"],
                clean.get("destroyed_raw", 0),
                clean["combat_score"],
                clean["destroyed_score"],
            ),
        )
    elif has_extended and has_evolution and has_combat:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_buildings, score_research,
                score_fleet, score_defense, score_planet_evolution,
                score_destroyed_raw, score_combat, score_destroyed, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total = excluded.score_total,
                score_buildings = excluded.score_buildings,
                score_research = excluded.score_research,
                score_fleet = excluded.score_fleet,
                score_defense = excluded.score_defense,
                score_planet_evolution = excluded.score_planet_evolution,
                score_destroyed_raw = excluded.score_destroyed_raw,
                score_combat = excluded.score_combat,
                score_destroyed = excluded.score_destroyed,
                updated_at = excluded.updated_at
            """,
            (
                int(player_id),
                clean["total_score"],
                clean["building_score"],
                clean["research_score"],
                clean["fleet_score"],
                clean["defense_score"],
                clean["evolution_score"],
                clean.get("destroyed_raw", 0),
                clean["combat_score"],
                clean["destroyed_score"],
            ),
        )
    elif has_extended and has_evolution:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_buildings, score_research,
                score_fleet, score_defense, score_planet_evolution, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total = excluded.score_total,
                score_buildings = excluded.score_buildings,
                score_research = excluded.score_research,
                score_fleet = excluded.score_fleet,
                score_defense = excluded.score_defense,
                score_planet_evolution = excluded.score_planet_evolution,
                updated_at = excluded.updated_at
            """,
            (
                int(player_id),
                clean["total_score"],
                clean["building_score"],
                clean["research_score"],
                clean["fleet_score"],
                clean["defense_score"],
                clean["evolution_score"],
            ),
        )
    elif has_extended:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_buildings, score_research,
                score_fleet, score_defense, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total = excluded.score_total,
                score_buildings = excluded.score_buildings,
                score_research = excluded.score_research,
                score_fleet = excluded.score_fleet,
                score_defense = excluded.score_defense,
                updated_at = excluded.updated_at
            """,
            (
                int(player_id),
                clean["total_score"],
                clean["building_score"],
                clean["research_score"],
                clean["fleet_score"],
                clean["defense_score"],
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
            VALUES (?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total = excluded.score_total,
                score_buildings = excluded.score_buildings,
                score_research = excluded.score_research,
                updated_at = excluded.updated_at
            """,
            (
                int(player_id),
                clean["total_score"],
                clean["building_score"],
                clean["research_score"],
            ),
        )

    if owns_conn:
        conn.commit()
        conn.close()


def refresh_player_score(player_id: int, conn=None) -> Dict[str, int]:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    try:
        scores = compute_player_scores(int(player_id), conn=conn)
        upsert_player_scores(int(player_id), scores, conn=conn)
        invalidate_player_score_cache(int(player_id))
        return scores
    finally:
        if owns_conn:
            conn.close()


def repair_player_score_totals(player_id: int, conn=None) -> bool:
    """
    Fix legacy score_total (e.g. old weighted formula) without recomputing components.
    Returns True if a row was repaired.
    """
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM player_scores WHERE player_id = ?", (int(player_id),))
        row = cur.fetchone()
        if not row:
            return False
        row_dict = dict(row)
        keys = row_dict.keys() if hasattr(row_dict, "keys") else ()
        building = _safe_int(row_dict.get("score_buildings", 0))
        research = _safe_int(row_dict.get("score_research", 0))
        resources = (
            _safe_int(row_dict.get("score_resources", 0)) if "score_resources" in keys else 0
        )
        fleet = _safe_int(row_dict.get("score_fleet", 0)) if "score_fleet" in keys else 0
        defense = _safe_int(row_dict.get("score_defense", 0)) if "score_defense" in keys else 0
        evolution = (
            _safe_int(row_dict.get("score_planet_evolution", 0))
            if "score_planet_evolution" in keys
            else 0
        )
        destroyed_raw = (
            _safe_int(row_dict.get("score_destroyed_raw", 0))
            if "score_destroyed_raw" in keys
            else 0
        )
        from .scoring import compute_combat_score

        combat = compute_combat_score(fleet, defense)
        destroyed_score = _safe_int(destroyed_raw)
        computed = _sanitize_scores(
            {
                "resource_score": resources,
                "building_score": building,
                "research_score": research,
                "fleet_score": fleet,
                "defense_score": defense,
                "combat_score": combat,
                "destroyed_score": destroyed_score,
                "destroyed_raw": destroyed_raw,
                "evolution_score": evolution,
            }
        )
        stored_total = _safe_int(row["score_total"])
        if stored_total == computed["total_score"]:
            return False
        upsert_player_scores(int(player_id), computed, conn=conn)
        if owns_conn:
            conn.commit()
        return True
    finally:
        if owns_conn:
            conn.close()


def on_player_score_changed(player_id: int, conn=None) -> Dict[str, int]:
    """
    Legacy gameplay hook — no live score recompute (ranking worker every 10 min).

    Invalidates in-process cache only; returns last persisted snapshot.
    Admin / worker use ``recompute_and_upsert_score`` or ``recalculate_all_rankings``.
    """
    invalidate_player_score_cache(int(player_id))
    return read_player_scores(int(player_id), conn=conn)


def _ensure_score_rows(conn) -> int:
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(
        """
        INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
        SELECT p.id, 0, 0, 0, ?
        FROM players p
        WHERE NOT EXISTS (SELECT 1 FROM player_scores s WHERE s.player_id = p.id)
        """,
        (now,),
    )
    return int(cur.rowcount or 0)


def ensure_player_score_row(player_id: int, conn=None) -> None:
    """Ensure a single player has a zeroed player_scores row (e.g. after registration)."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
            VALUES (?, 0, 0, 0, ?)
            ON CONFLICT(player_id) DO NOTHING;
            """,
            (int(player_id), int(time.time())),
        )
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def _resources_score_select(conn) -> str:
    if column_exists(conn, "player_scores", "score_resources"):
        return "COALESCE(ps.score_resources, 0) AS score_resources"
    return "0 AS score_resources"


def _fleet_defense_select(conn) -> str:
    if column_exists(conn, "player_scores", "score_fleet"):
        return "COALESCE(ps.score_fleet, 0) AS score_fleet, COALESCE(ps.score_defense, 0) AS score_defense"
    return "0 AS score_fleet, 0 AS score_defense"


def _evolution_score_select(conn) -> str:
    if column_exists(conn, "player_scores", "score_planet_evolution"):
        return "COALESCE(ps.score_planet_evolution, 0) AS score_planet_evolution"
    return "0 AS score_planet_evolution"


def _vacation_mode_select(conn) -> str:
    if column_exists(conn, "players", "vacation_mode_active"):
        return "COALESCE(p.vacation_mode_active, 0) AS vacation_mode_active"
    return "0 AS vacation_mode_active"


def _last_seen_select(conn) -> str:
    if column_exists(conn, "players", "last_seen"):
        return "COALESCE(p.last_seen, 0) AS last_seen"
    return "0 AS last_seen"


def ranking_inactive_from_last_seen(last_seen: int, *, now: Optional[int] = None) -> bool:
    """True when player has no recent activity (3+ days since last_seen)."""
    seen = int(last_seen or 0)
    if seen <= 0:
        return True
    now_i = int(now if now is not None else time.time())
    return (now_i - seen) >= RANKING_INACTIVE_AFTER_SEC


def is_player_inactive(
    player_row: Any,
    *,
    now: Optional[int] = None,
) -> bool:
    """True when player row has no recent activity (ranking/galaxy inactive threshold)."""
    if player_row is None:
        return True
    if isinstance(player_row, (int, float)):
        last_seen = int(player_row)
    elif isinstance(player_row, dict):
        last_seen = int(player_row.get("last_seen") or 0)
    else:
        last_seen = int(getattr(player_row, "last_seen", 0) or 0)
    return ranking_inactive_from_last_seen(last_seen, now=now)


def is_player_id_inactive(player_id: int, *, conn, now: Optional[int] = None) -> bool:
    """Server-side inactive check for a player id (uses ``players.last_seen``)."""
    row = conn.execute(
        "SELECT last_seen FROM players WHERE id = ? LIMIT 1;",
        (int(player_id),),
    ).fetchone()
    if not row:
        return True
    return is_player_inactive(dict(row), now=now)


def _combat_ranking_select(conn) -> str:
    if column_exists(conn, "player_scores", "score_combat"):
        return (
            "COALESCE(ps.score_combat, 0) AS score_combat, "
            "COALESCE(ps.score_destroyed, 0) AS score_destroyed"
        )
    return "0 AS score_combat, 0 AS score_destroyed"


def _fetch_all_score_rows(conn) -> List[Dict[str, Any]]:
    _ensure_score_rows(conn)
    cur = conn.cursor()
    extra = _fleet_defense_select(conn)
    resources_sel = _resources_score_select(conn)
    evo = _evolution_score_select(conn)
    combat_sel = _combat_ranking_select(conn)
    cur.execute(
        f"""
        SELECT
            p.id AS player_id,
            p.name AS commander_name,
            COALESCE(ps.score_total, 0) AS score_total,
            {resources_sel},
            COALESCE(ps.score_buildings, 0) AS score_buildings,
            COALESCE(ps.score_research, 0) AS score_research,
            {extra},
            {evo},
            {combat_sel}
        FROM players p
        LEFT JOIN player_scores ps ON ps.player_id = p.id
        ORDER BY p.id ASC
        """
    )
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        scores = _normalize_db_row(d)
        rows.append(
            {
                "player_id": int(d["player_id"]),
                "commander_name": d.get("commander_name") or "—",
                **scores,
            }
        )
    return rows


def recalculate_ranks(conn=None) -> int:
    """Assign rank_total / rank_building / rank_research from current score columns (atomic)."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    if not column_exists(conn, "player_scores", "rank_total"):
        if owns_conn:
            conn.close()
        return 0

    def _apply() -> int:
        rows = _fetch_all_score_rows(conn)
        total_sorted = sorted(
            rows,
            key=lambda r: (
                -r["total_score"],
                -r["building_score"],
                -r["research_score"],
                r["player_id"],
            ),
        )
        building_sorted = sorted(
            rows,
            key=lambda r: (-r["building_score"], -r["research_score"], r["player_id"]),
        )
        research_sorted = sorted(
            rows,
            key=lambda r: (-r["research_score"], -r["building_score"], r["player_id"]),
        )
        fleet_sorted = sorted(
            rows,
            key=lambda r: (-r["fleet_score"], -r["building_score"], r["player_id"]),
        )
        combat_sorted = sorted(
            rows,
            key=lambda r: (-r.get("combat_score", 0), -r["fleet_score"], r["player_id"]),
        )
        destroyed_sorted = sorted(
            rows,
            key=lambda r: (-r.get("destroyed_score", 0), -r["fleet_score"], r["player_id"]),
        )
        military_sorted = sorted(
            rows,
            key=lambda r: (-r.get("military_score", 0), -r["fleet_score"], r["player_id"]),
        )

        rank_total_map = {r["player_id"]: idx for idx, r in enumerate(total_sorted, start=1)}
        rank_building_map = {r["player_id"]: idx for idx, r in enumerate(building_sorted, start=1)}
        rank_research_map = {r["player_id"]: idx for idx, r in enumerate(research_sorted, start=1)}
        rank_fleet_map = {r["player_id"]: idx for idx, r in enumerate(fleet_sorted, start=1)}
        rank_combat_map = {r["player_id"]: idx for idx, r in enumerate(combat_sorted, start=1)}
        rank_destroyed_map = {r["player_id"]: idx for idx, r in enumerate(destroyed_sorted, start=1)}
        rank_military_map = {r["player_id"]: idx for idx, r in enumerate(military_sorted, start=1)}

        has_rank_fleet = column_exists(conn, "player_scores", "rank_fleet")
        has_rank_combat = column_exists(conn, "player_scores", "rank_combat")
        cur = conn.cursor()
        for row in rows:
            pid = row["player_id"]
            if has_rank_combat:
                cur.execute(
                    """
                    UPDATE player_scores
                    SET rank_total = ?, rank_building = ?, rank_research = ?, rank_fleet = ?,
                        rank_combat = ?, rank_destroyed = ?, rank_military = ?
                    WHERE player_id = ?
                    """,
                    (
                        rank_total_map.get(pid),
                        rank_building_map.get(pid),
                        rank_research_map.get(pid),
                        rank_fleet_map.get(pid),
                        rank_combat_map.get(pid),
                        rank_destroyed_map.get(pid),
                        rank_military_map.get(pid),
                        pid,
                    ),
                )
            elif has_rank_fleet:
                cur.execute(
                    """
                    UPDATE player_scores
                    SET rank_total = ?, rank_building = ?, rank_research = ?, rank_fleet = ?
                    WHERE player_id = ?
                    """,
                    (
                        rank_total_map.get(pid),
                        rank_building_map.get(pid),
                        rank_research_map.get(pid),
                        rank_fleet_map.get(pid),
                        pid,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE player_scores
                    SET rank_total = ?, rank_building = ?, rank_research = ?
                    WHERE player_id = ?
                    """,
                    (
                        rank_total_map.get(pid),
                        rank_building_map.get(pid),
                        rank_research_map.get(pid),
                        pid,
                    ),
                )
        return len(rows)

    try:
        with _RANKING_LOCK:
            if owns_conn:
                begin_write_transaction(conn)
            count = _apply()
            if owns_conn:
                commit(conn)
            return count
    except Exception:
        if owns_conn:
            rollback(conn)
        raise
    finally:
        if owns_conn:
            conn.close()


def recalculate_all_rankings(
    *,
    refresh_scores: bool = True,
    conn=None,
) -> Dict[str, Any]:
    """
    Recompute all player scores (optional) and refresh rank columns.
    Admin/debug entry point; cron-ready.
    """
    started = time.perf_counter()
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    errors: List[str] = []
    players_updated = 0

    try:
        with _RANKING_LOCK:
            if owns_conn:
                begin_write_transaction(conn)

            _ensure_score_rows(conn)
            cur = conn.cursor()
            cur.execute("SELECT id FROM players ORDER BY id ASC")
            player_ids = [int(r[0]) for r in cur.fetchall()]

            if refresh_scores:
                for pid in player_ids:
                    try:
                        refresh_player_score(pid, conn=conn)
                        players_updated += 1
                    except Exception as exc:
                        errors.append(f"player {pid}: {exc}")
                        logger.exception("ranking refresh failed for player %s", pid)
            else:
                for pid in player_ids:
                    try:
                        if repair_player_score_totals(pid, conn=conn):
                            players_updated += 1
                    except Exception as exc:
                        errors.append(f"player {pid}: {exc}")

            rank_count = recalculate_ranks(conn=conn)
            invalidate_all_score_cache()

            if owns_conn:
                commit(conn)

        duration_ms = int((time.perf_counter() - started) * 1000)
        result = {
            "ok": len(errors) == 0,
            "players_updated": players_updated,
            "ranks_assigned": rank_count,
            "duration_ms": duration_ms,
            "errors": errors,
        }
        logger.info(
            "recalculate_all_rankings: players=%s ranks=%s duration_ms=%s errors=%s",
            players_updated,
            rank_count,
            duration_ms,
            len(errors),
        )
        return result
    except Exception as exc:
        if owns_conn:
            try:
                rollback(conn)
            except Exception:
                pass
        logger.exception("recalculate_all_rankings failed")
        return {
            "ok": False,
            "players_updated": players_updated,
            "ranks_assigned": 0,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "errors": [str(exc)],
        }
    finally:
        if owns_conn:
            conn.close()


def backfill_player_score_rows(conn=None) -> int:
    """
    Idempotent INSERT for players missing player_scores rows.
    Call from migrations, init_db, registration — never from ranking GET / player-card GET.
    """
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        inserted = _ensure_score_rows(conn)
        if owns_conn:
            conn.commit()
        return inserted
    finally:
        if owns_conn:
            conn.close()


def ensure_ranking_snapshot(
    conn=None,
    *,
    current_player_id: Optional[int] = None,
    write: bool = False,
) -> None:
    """
    Legacy name — ranking GET must stay read-only (write=False, default).

    write=True: admin/cron maintenance (seed rows, recalc missing ranks, optional repair).
    """
    if not write:
        return

    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    try:
        _ensure_score_rows(conn)
        if owns_conn:
            conn.commit()
        if column_exists(conn, "player_scores", "rank_total"):
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM player_scores WHERE rank_total IS NULL")
            missing = int(cur.fetchone()[0])
            if missing > 0:
                recalculate_ranks(conn=conn)
        if current_player_id is not None:
            repair_player_score_totals(int(current_player_id), conn=conn)
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def get_player_score_row(player_id: int, conn=None) -> Optional[Dict[str, Any]]:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    cur = conn.cursor()
    cur.execute("SELECT * FROM player_scores WHERE player_id = ?", (int(player_id),))
    row = cur.fetchone()
    if owns_conn:
        conn.close()
    return dict(row) if row else None


def get_player_score_cached(
    player_id: int,
    force_recompute: bool = False,
    *,
    read_only: bool = False,
) -> Dict[str, int]:
    """
    Cached score read for HUD/header. Keys: total, buildings, research (+ fleet/defense when present).
    """
    if not player_id:
        return {
            "total": 0,
            "resources": 0,
            "buildings": 0,
            "research": 0,
            "fleet": 0,
            "defense": 0,
            "combat": 0,
            "destroyed": 0,
            "military": 0,
            "evolution": 0,
        }

    pid = int(player_id)
    now = time.time()

    def _to_legacy(s: Dict[str, int]) -> Dict[str, int]:
        return {
            "total": int(s.get("total_score", 0)),
            "resources": int(s.get("resource_score", 0)),
            "buildings": int(s.get("building_score", 0)),
            "research": int(s.get("research_score", 0)),
            "fleet": int(s.get("fleet_score", 0)),
            "defense": int(s.get("defense_score", 0)),
            "combat": int(s.get("combat_score", 0)),
            "destroyed": int(s.get("destroyed_score", 0)),
            "military": int(s.get("military_score", 0)),
            "evolution": int(s.get("evolution_score", 0)),
        }

    if force_recompute:
        invalidate_player_score_cache(pid)
        out = _to_legacy(refresh_player_score(pid))
        _CACHE[pid] = (now, out)
        return out

    cached = _CACHE.get(pid)
    if cached:
        ts, data = cached
        if (now - ts) <= CACHE_TTL_SECONDS:
            return data

    row = get_player_score_row(pid, conn=None)
    if not row:
        out = _to_legacy(_zero_scores())
    else:
        out = _to_legacy(_normalize_db_row(row))

    _CACHE[pid] = (now, out)
    return out


def _ranking_social_select_and_join(conn) -> Tuple[str, str]:
    """Extra SELECT columns + JOIN clauses for player cards and alliances (single query)."""
    select_parts: List[str] = []
    join_parts: List[str] = []

    if table_exists(conn, "player_cards"):
        select_parts.extend(
            [
                "pc.avatar_url AS card_avatar_url",
                "COALESCE(pc.updated_at, 0) AS card_updated_at",
                "pc.title AS card_title",
                "pc.theme AS card_theme",
                "COALESCE(pc.is_public, 1) AS card_is_public",
                "pc.selected_badge_1 AS card_badge_1",
                "pc.selected_badge_2 AS card_badge_2",
                "pc.selected_badge_3 AS card_badge_3",
            ]
        )
        if column_exists(conn, "player_cards", "name_style"):
            select_parts.append("COALESCE(pc.name_style, 'none') AS card_name_style")
        else:
            select_parts.append("'none' AS card_name_style")
        join_parts.append("LEFT JOIN player_cards pc ON pc.player_id = p.id")
        if table_exists(conn, "player_card_badges"):
            select_parts.extend(
                [
                    "b1.badge_key AS badge1_badge_key",
                    "b1.rarity AS badge1_rarity",
                    "b1.name_i18n_key AS badge1_key",
                    "b2.badge_key AS badge2_badge_key",
                    "b2.rarity AS badge2_rarity",
                    "b2.name_i18n_key AS badge2_key",
                    "b3.badge_key AS badge3_badge_key",
                    "b3.rarity AS badge3_rarity",
                    "b3.name_i18n_key AS badge3_key",
                ]
            )
            join_parts.extend(
                [
                    "LEFT JOIN player_card_badges b1 ON b1.id = pc.selected_badge_1 AND b1.is_active = 1",
                    "LEFT JOIN player_card_badges b2 ON b2.id = pc.selected_badge_2 AND b2.is_active = 1",
                    "LEFT JOIN player_card_badges b3 ON b3.id = pc.selected_badge_3 AND b3.is_active = 1",
                ]
            )
        else:
            select_parts.extend(
                [
                    "NULL AS badge1_badge_key", "NULL AS badge1_rarity", "NULL AS badge1_key",
                    "NULL AS badge2_badge_key", "NULL AS badge2_rarity", "NULL AS badge2_key",
                    "NULL AS badge3_badge_key", "NULL AS badge3_rarity", "NULL AS badge3_key",
                ]
            )
    else:
        select_parts.extend(
            [
                "NULL AS card_avatar_url",
                "NULL AS card_title",
                "NULL AS card_theme",
                "1 AS card_is_public",
                "'none' AS card_name_style",
                "NULL AS card_badge_1",
                "NULL AS card_badge_2",
                "NULL AS card_badge_3",
                "NULL AS badge1_badge_key", "NULL AS badge1_rarity", "NULL AS badge1_key",
                "NULL AS badge2_badge_key", "NULL AS badge2_rarity", "NULL AS badge2_key",
                "NULL AS badge3_badge_key", "NULL AS badge3_rarity", "NULL AS badge3_key",
            ]
        )

    if table_exists(conn, "alliance_members") and table_exists(conn, "alliances"):
        select_parts.extend(
            [
                "a.id AS alliance_id",
                "a.tag AS alliance_tag",
                "a.name AS alliance_name",
            ]
        )
        join_parts.extend(
            [
                """LEFT JOIN (
                    SELECT player_id, MIN(alliance_id) AS alliance_id
                    FROM alliance_members
                    GROUP BY player_id
                ) am ON am.player_id = p.id""",
                "LEFT JOIN alliances a ON a.id = am.alliance_id",
            ]
        )
    else:
        select_parts.extend(
            [
                "NULL AS alliance_id",
                "NULL AS alliance_tag",
                "NULL AS alliance_name",
            ]
        )

    return ",\n            ".join(select_parts), "\n        ".join(join_parts)


def _avatar_initial_from_name(name: Any) -> str:
    from .player_display import commander_display_name

    label = commander_display_name(str(name or ""))
    if not label:
        return "?"
    return label[0].upper()


def _badge_from_row(raw: Dict[str, Any], slot: int) -> Optional[Dict[str, str]]:
    badge_key = raw.get(f"badge{slot}_badge_key")
    name_key = raw.get(f"badge{slot}_key")
    if not badge_key and not name_key:
        return None
    from .playercard import badge_image_static_path

    key = str(badge_key or "")
    return {
        "badge_key": key,
        "image_url": badge_image_static_path(key) if key else "",
        "rarity": str(raw.get(f"badge{slot}_rarity") or "common"),
        "name_key": str(name_key or ""),
    }


def enrich_ranking_social_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize player-card and alliance fields for ranking API / templates.
    Avatar URL is only exposed when the profile is public and passes validation.
    """
    from .playercard import resolve_avatar_display, sanitize_text_field, validate_theme, TITLE_MAX, validate_name_style

    from .player_display import commander_display_name, commander_lookup_name

    lookup = commander_lookup_name(raw.get("commander_name"))
    name = commander_display_name(lookup)
    initial = _avatar_initial_from_name(lookup)
    pub_raw = raw.get("card_is_public")
    is_public = bool(int(pub_raw)) if pub_raw is not None else True
    card_updated_at = int(raw.get("card_updated_at") or 0)

    avatar_url = ""
    show_avatar = False
    if is_public:
        raw_url = str(raw.get("card_avatar_url") or "").strip()
        if raw_url:
            try:
                pid = int(raw.get("player_id") or 0)
            except (TypeError, ValueError):
                pid = 0
            avatar_url, show_avatar = resolve_avatar_display(
                raw_url,
                card_updated_at,
                player_id=pid if pid > 0 else None,
            )

    title = sanitize_text_field(raw.get("card_title"), TITLE_MAX) if is_public else ""
    theme = validate_theme(raw.get("card_theme")) if raw.get("card_theme") is not None else "cyan"
    # Name style is a social status signal — always exposed (even if card is private).
    name_style = validate_name_style(raw.get("card_name_style"))

    alliance_id: Optional[int] = None
    try:
        if raw.get("alliance_id") is not None:
            alliance_id = int(raw["alliance_id"])
            if alliance_id <= 0:
                alliance_id = None
    except (TypeError, ValueError):
        alliance_id = None

    alliance_tag = str(raw.get("alliance_tag") or "").strip() if alliance_id else ""
    alliance_name = str(raw.get("alliance_name") or "").strip() if alliance_id else ""

    badges: List[Dict[str, str]] = []
    if is_public:
        for slot in (1, 2, 3):
            badge = _badge_from_row(raw, slot)
            if badge:
                badges.append(badge)

    return {
        "avatar_url": avatar_url,
        "avatar_initial": initial,
        "show_avatar": show_avatar,
        "title": title,
        "theme": theme,
        "name_style": name_style,
        "profile_is_public": is_public,
        "alliance_id": alliance_id,
        "alliance_tag": alliance_tag,
        "alliance_name": alliance_name,
        "badges": badges,
    }


def get_sorted_ranking_entries(
    limit: int = 100,
    offset: int = 0,
    conn=None,
) -> List[Dict[str, Any]]:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    cur = conn.cursor()
    extra = _fleet_defense_select(conn)
    resources_sel = _resources_score_select(conn)
    evo = _evolution_score_select(conn)
    combat_sel = _combat_ranking_select(conn)
    vacation_sel = _vacation_mode_select(conn)
    last_seen_sel = _last_seen_select(conn)
    total_expr = _total_score_sql(conn)
    social_select, social_join = _ranking_social_select_and_join(conn)
    rank_select = ""
    if column_exists(conn, "player_scores", "rank_total"):
        rank_select = ", ps.rank_total, ps.rank_building, ps.rank_research"
        if column_exists(conn, "player_scores", "rank_fleet"):
            rank_select += ", ps.rank_fleet"
    cur.execute(
        f"""
        SELECT
            p.id AS player_id,
            p.name AS commander_name,
            COALESCE(ps.score_total, 0) AS score_total,
            {resources_sel},
            COALESCE(ps.score_buildings, 0) AS score_buildings,
            COALESCE(ps.score_research, 0) AS score_research,
            {extra},
            {evo},
            {combat_sel},
            {vacation_sel},
            {last_seen_sel},
            COALESCE(ps.updated_at, 0) AS score_updated_at{rank_select},
            {social_select}
        FROM players p
        LEFT JOIN player_scores ps ON ps.player_id = p.id
        {social_join}
        WHERE NOT EXISTS (
            SELECT 1 FROM users u
            WHERE u.id = p.id
              AND u.username IN ('gc_combat_bot_alpha', 'gc_combat_bot_beta')
        )
        ORDER BY {total_expr} DESC,
                 COALESCE(ps.score_buildings, 0) DESC,
                 COALESCE(ps.score_research, 0) DESC,
                 p.id ASC
        LIMIT ? OFFSET ?
        """,
        (int(limit), int(offset)),
    )
    rows = cur.fetchall()

    out: List[Dict[str, Any]] = []
    base_rank = int(offset)
    now_i = int(time.time())
    for idx, raw in enumerate(rows, start=1):
        d = dict(raw)
        scores = _normalize_db_row(d)
        rank = base_rank + idx
        social = enrich_ranking_social_fields(d)
        from .player_display import commander_display_name, commander_lookup_name

        raw_name = d.get("commander_name") or "—"
        last_seen = int(d.get("last_seen") or 0)
        out.append(
            {
                "rank": rank,
                "player_id": int(d["player_id"]),
                "commander_name": commander_lookup_name(raw_name),
                "commander_display": commander_display_name(raw_name),
                "is_current_player": False,
                "rank_total": int(d["rank_total"]) if d.get("rank_total") is not None else None,
                "rank_building": int(d["rank_building"]) if d.get("rank_building") is not None else None,
                "rank_research": int(d["rank_research"]) if d.get("rank_research") is not None else None,
                "rank_fleet": int(d["rank_fleet"]) if d.get("rank_fleet") is not None else None,
                "vacation_active": bool(int(d.get("vacation_mode_active") or 0)),
                "last_seen": last_seen,
                "inactive": ranking_inactive_from_last_seen(last_seen, now=now_i),
                **scores,
                **social,
            }
        )
    try:
        from .pirates.accounts import pirate_ai_profiles_by_ids

        profiles = pirate_ai_profiles_by_ids([e["player_id"] for e in out], conn=conn)
    except Exception:
        profiles = {}
    for e in out:
        ai = profiles.get(int(e["player_id"]))
        if not ai:
            e["is_ai"] = False
            continue
        e["is_ai"] = True
        e["inactive"] = False
        e["player_mode"] = ai.get("player_mode")
        e["ai_kind"] = ai.get("ai_kind")
        e["ai_faction_key"] = ai.get("faction_key")
        e["ai_personality"] = ai.get("personality")
        e["ai_mode_key"] = ai.get("mode_key")
        e["ai_badge_key"] = ai.get("badge_key")
        e["ai_badge_title_key"] = ai.get("badge_title_key")
        e["title"] = e.get("title") or "AI"
    if owns_conn:
        conn.close()
    return out


def get_player_rank_from_snapshot(player_id: int, conn=None) -> Tuple[Optional[int], int]:
    """
    Live rank lookup using the same ordering as get_sorted_ranking_entries.
    Never trusts stale rank_total columns — rank is derived from effective totals.
    """
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM players")
    total_players = int(cur.fetchone()["cnt"])

    total_expr = _total_score_sql(conn)
    cur.execute(
        f"""
        SELECT {total_expr} AS eff_total,
               COALESCE(ps.score_buildings, 0) AS score_buildings,
               COALESCE(ps.score_research, 0) AS score_research
        FROM players p
        LEFT JOIN player_scores ps ON ps.player_id = p.id
        WHERE p.id = ?
        """,
        (int(player_id),),
    )
    me = cur.fetchone()
    if not me:
        if owns_conn:
            conn.close()
        return None, total_players

    my_total = _safe_int(me["eff_total"])
    my_build = _safe_int(me["score_buildings"])
    my_res = _safe_int(me["score_research"])

    cur.execute(
        f"""
        SELECT COUNT(*) AS better
        FROM players p
        LEFT JOIN player_scores ps ON ps.player_id = p.id
        WHERE ({total_expr} > ?)
           OR ({total_expr} = ? AND COALESCE(ps.score_buildings, 0) > ?)
           OR ({total_expr} = ? AND COALESCE(ps.score_buildings, 0) = ? AND COALESCE(ps.score_research, 0) > ?)
           OR ({total_expr} = ? AND COALESCE(ps.score_buildings, 0) = ? AND COALESCE(ps.score_research, 0) = ?
               AND p.id < ?)
        """,
        (
            my_total,
            my_total,
            my_build,
            my_total,
            my_build,
            my_res,
            my_total,
            my_build,
            my_res,
            int(player_id),
        ),
    )
    better = int(cur.fetchone()["better"])
    if owns_conn:
        conn.close()
    return better + 1, total_players


def get_playercard_ranking_snapshot(
    player_id: int,
    conn=None,
) -> Dict[str, Any]:
    """
    Single read-only snapshot for PlayerCard: scores + rank from canonical ranking logic.
    """
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        scores = format_scores_for_playercard(read_player_scores(int(player_id), conn=conn))
        category_ranks = get_player_category_ranks(int(player_id), conn=conn)
        rank = category_ranks.get("total")
        total_players = int(category_ranks.get("total_players") or 0)
        if rank is None:
            try:
                rank, total_players = get_player_rank_from_snapshot(int(player_id), conn=conn)
            except sqlite3.OperationalError:
                logger.debug(
                    "playercard ranking snapshot rank unavailable (player_id=%s)",
                    player_id,
                    exc_info=True,
                )
                rank = None
        return {
            "rank": rank,
            "total_players": total_players,
            **scores,
            "rank_defense": category_ranks.get("defense"),
            "rank_fleet": category_ranks.get("fleet"),
            "rank_military": category_ranks.get("military"),
        }
    finally:
        if owns_conn:
            conn.close()


def get_player_category_ranks(
    player_id: int,
    conn=None,
    *,
    skip_live_total: bool = False,
) -> Dict[str, Any]:
    """Return snapshot ranks per score category for the current player."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM player_scores")
    total_players = int(cur.fetchone()["cnt"])
    ranks: Dict[str, Any] = {"total_players": total_players}

    has_fleet = column_exists(conn, "player_scores", "score_fleet")
    has_evo = column_exists(conn, "player_scores", "score_planet_evolution")
    if has_fleet and has_evo:
        cur.execute(
            "SELECT score_buildings, score_research, score_fleet, score_defense, score_planet_evolution FROM player_scores WHERE player_id = ?",
            (int(player_id),),
        )
    elif has_fleet:
        cur.execute(
            "SELECT score_buildings, score_research, score_fleet, score_defense FROM player_scores WHERE player_id = ?",
            (int(player_id),),
        )
    elif has_evo:
        cur.execute(
            "SELECT score_buildings, score_research, score_planet_evolution FROM player_scores WHERE player_id = ?",
            (int(player_id),),
        )
    else:
        cur.execute(
            "SELECT score_buildings, score_research FROM player_scores WHERE player_id = ?",
            (int(player_id),),
        )
    score_row = cur.fetchone()
    if not score_row:
        if owns_conn:
            conn.close()
        return ranks

    keys = score_row.keys() if hasattr(score_row, "keys") else ()
    my_build = _safe_int(score_row["score_buildings"])
    my_res = _safe_int(score_row["score_research"])
    my_fleet = _safe_int(score_row["score_fleet"]) if "score_fleet" in keys else 0
    my_def = _safe_int(score_row["score_defense"]) if "score_defense" in keys else 0
    my_combat = _safe_int(score_row["score_combat"]) if "score_combat" in keys else 0
    my_destroyed = _safe_int(score_row["score_destroyed"]) if "score_destroyed" in keys else 0
    my_evo = _safe_int(score_row["score_planet_evolution"]) if "score_planet_evolution" in keys else 0

    cur.execute(
        """
        SELECT COUNT(*) AS better
        FROM players p
        LEFT JOIN player_scores ps ON ps.player_id = p.id
        WHERE COALESCE(ps.score_buildings, 0) > ?
           OR (COALESCE(ps.score_buildings, 0) = ? AND COALESCE(ps.score_research, 0) > ?)
           OR (COALESCE(ps.score_buildings, 0) = ? AND COALESCE(ps.score_research, 0) = ? AND p.id < ?)
        """,
        (my_build, my_build, my_res, my_build, my_res, int(player_id)),
    )
    ranks["building"] = int(cur.fetchone()["better"]) + 1

    cur.execute(
        """
        SELECT COUNT(*) AS better
        FROM players p
        LEFT JOIN player_scores ps ON ps.player_id = p.id
        WHERE COALESCE(ps.score_research, 0) > ?
           OR (COALESCE(ps.score_research, 0) = ? AND COALESCE(ps.score_buildings, 0) > ?)
           OR (COALESCE(ps.score_research, 0) = ? AND COALESCE(ps.score_buildings, 0) = ? AND p.id < ?)
        """,
        (my_res, my_res, my_build, my_res, my_build, int(player_id)),
    )
    ranks["research"] = int(cur.fetchone()["better"]) + 1

    if column_exists(conn, "player_scores", "score_fleet"):
        cur.execute(
            """
            SELECT COUNT(*) AS better
            FROM players p
            LEFT JOIN player_scores ps ON ps.player_id = p.id
            WHERE COALESCE(ps.score_fleet, 0) > ?
               OR (COALESCE(ps.score_fleet, 0) = ? AND COALESCE(ps.score_buildings, 0) > ?)
               OR (COALESCE(ps.score_fleet, 0) = ? AND COALESCE(ps.score_buildings, 0) = ? AND p.id < ?)
            """,
            (my_fleet, my_fleet, my_build, my_fleet, my_build, int(player_id)),
        )
        ranks["fleet"] = int(cur.fetchone()["better"]) + 1

    if not skip_live_total:
        try:
            live_total_rank, live_total_players = get_player_rank_from_snapshot(
                int(player_id), conn=conn
            )
            if live_total_rank is not None:
                ranks["total"] = int(live_total_rank)
            ranks["total_players"] = int(live_total_players)
        except sqlite3.OperationalError:
            logger.debug(
                "category rank live total unavailable (player_id=%s)",
                player_id,
                exc_info=True,
            )

    if column_exists(conn, "player_scores", "score_defense"):
        cur.execute(
            """
            SELECT COUNT(*) AS better FROM player_scores
            WHERE COALESCE(score_defense, 0) > ?
               OR (COALESCE(score_defense, 0) = ? AND player_id < ?)
            """,
            (my_def, my_def, int(player_id)),
        )
        ranks["defense"] = int(cur.fetchone()["better"]) + 1

    if column_exists(conn, "player_scores", "score_combat"):
        cur.execute(
            """
            SELECT COUNT(*) AS better FROM player_scores
            WHERE COALESCE(score_combat, 0) > ?
               OR (COALESCE(score_combat, 0) = ? AND player_id < ?)
            """,
            (my_combat, my_combat, int(player_id)),
        )
        ranks["combat"] = int(cur.fetchone()["better"]) + 1

    if column_exists(conn, "player_scores", "score_destroyed"):
        cur.execute(
            """
            SELECT COUNT(*) AS better FROM player_scores
            WHERE COALESCE(score_destroyed, 0) > ?
               OR (COALESCE(score_destroyed, 0) = ? AND player_id < ?)
            """,
            (my_destroyed, my_destroyed, int(player_id)),
        )
        ranks["destroyed"] = int(cur.fetchone()["better"]) + 1

    if column_exists(conn, "player_scores", "rank_military"):
        cur.execute(
            "SELECT rank_military FROM player_scores WHERE player_id = ?",
            (int(player_id),),
        )
        row = cur.fetchone()
        if row and row["rank_military"] is not None:
            ranks["military"] = int(row["rank_military"])
    elif column_exists(conn, "player_scores", "score_combat") and column_exists(
        conn, "player_scores", "score_destroyed"
    ):
        my_mil = my_combat + my_destroyed
        cur.execute(
            """
            SELECT COUNT(*) AS better FROM player_scores
            WHERE (COALESCE(score_combat, 0) + COALESCE(score_destroyed, 0)) > ?
               OR (
                    (COALESCE(score_combat, 0) + COALESCE(score_destroyed, 0)) = ?
                    AND player_id < ?
                  )
            """,
            (my_mil, my_mil, int(player_id)),
        )
        ranks["military"] = int(cur.fetchone()["better"]) + 1
    elif column_exists(conn, "player_scores", "score_fleet") and column_exists(
        conn, "player_scores", "score_defense"
    ):
        my_mil = my_fleet + my_def
        cur.execute(
            """
            SELECT COUNT(*) AS better FROM player_scores
            WHERE (COALESCE(score_fleet, 0) + COALESCE(score_defense, 0)) > ?
               OR (
                    (COALESCE(score_fleet, 0) + COALESCE(score_defense, 0)) = ?
                    AND player_id < ?
                  )
            """,
            (my_mil, my_mil, int(player_id)),
        )
        ranks["military"] = int(cur.fetchone()["better"]) + 1

    if column_exists(conn, "player_scores", "score_planet_evolution"):
        cur.execute(
            """
            SELECT COUNT(*) AS better FROM player_scores
            WHERE COALESCE(score_planet_evolution, 0) > ?
               OR (COALESCE(score_planet_evolution, 0) = ? AND player_id < ?)
            """,
            (my_evo, my_evo, int(player_id)),
        )
        ranks["evolution"] = int(cur.fetchone()["better"]) + 1

    if owns_conn:
        conn.close()
    return ranks


def _current_player_payload(
    current_player_id: int,
    top_players: List[Dict[str, Any]],
) -> Dict[str, Any]:
    pid = int(current_player_id)
    my_scores = get_player_score_cached(pid, read_only=True)
    in_top = next((r for r in top_players if int(r["player_id"]) == pid), None)

    conn = db()
    try:
        category_ranks = get_player_category_ranks(
            pid, conn=conn, skip_live_total=in_top is not None
        )
        if in_top is not None:
            my_rank = int(in_top["rank"])
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM players")
            total_players = int(cur.fetchone()["cnt"])
            category_ranks = {
                **category_ranks,
                "total": my_rank,
                "total_players": total_players,
            }
            return {
                "rank": my_rank,
                "total_players": total_players,
                "total_score": int(in_top["total_score"]),
                "building_score": int(in_top["building_score"]),
                "research_score": int(in_top["research_score"]),
                "fleet_score": int(in_top["fleet_score"]),
                "defense_score": int(in_top["defense_score"]),
                "combat_score": int(in_top.get("combat_score", 0)),
                "destroyed_score": int(in_top.get("destroyed_score", 0)),
                "military_score": int(in_top.get("military_score", 0)),
                "evolution_score": int(in_top.get("evolution_score", 0)),
                "ranks": category_ranks,
            }

        my_rank = category_ranks.get("total")
        total_players = int(category_ranks.get("total_players") or 0)
        if my_rank is None:
            my_rank, total_players = get_player_rank_from_snapshot(pid, conn=conn)
            total_players = int(total_players or 0)
            category_ranks = {
                **category_ranks,
                "total": my_rank,
                "total_players": total_players,
            }

        return {
            "rank": my_rank,
            "total_players": total_players,
            "total_score": int(my_scores.get("total", 0)),
            "building_score": int(my_scores.get("buildings", 0)),
            "research_score": int(my_scores.get("research", 0)),
            "fleet_score": int(my_scores.get("fleet", 0)),
            "defense_score": int(my_scores.get("defense", 0)),
            "combat_score": int(my_scores.get("combat", 0)),
            "destroyed_score": int(my_scores.get("destroyed", 0)),
            "military_score": int(my_scores.get("military", 0)),
            "evolution_score": int(my_scores.get("evolution", 0)),
            "ranks": category_ranks,
        }
    finally:
        conn.close()


def _log_ranking_top_debug(top: List[Dict[str, Any]], *, limit: int = 20) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    for row in top[:limit]:
        logger.debug(
            "ranking top: rank=%s player=%s total_score=%s rank_total=%s",
            row.get("rank"),
            row.get("commander_name"),
            row.get("total_score"),
            row.get("rank_total"),
        )


def build_ranking_api_payload(
    current_player_id: int,
    *,
    limit: int = 100,
    refresh: bool = False,
) -> Dict[str, Any]:
    """
    Single payload for /api/ranking and server-rendered fallback.

    refresh=False (default): read snapshot from DB, no full universe recompute.
    refresh=True: admin/cron – full recompute via recalculate_all_rankings().
    """
    if refresh:
        recalculate_all_rankings(refresh_scores=True)
    # Normal GET: read-only snapshot (LEFT JOIN players); no _ensure_score_rows here.

    top = get_sorted_ranking_entries(limit=limit, offset=0)
    _log_ranking_top_debug(top)
    for row in top:
        row["is_current_player"] = int(row["player_id"]) == int(current_player_id)

    current = _current_player_payload(int(current_player_id), top)

    return {
        "ok": True,
        "current_player": current,
        "top_players": top,
        "server_time": int(time.time()),
    }


# Backward-compatible aliases for legacy imports
def get_ranking_rows(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    entries = get_sorted_ranking_entries(limit=limit, offset=offset)
    legacy: List[Dict[str, Any]] = []
    for e in entries:
        legacy.append(
            {
                "player_id": e["player_id"],
                "nickname": e["commander_name"],
                "score_total": e["total_score"],
                "score_buildings": e["building_score"],
                "score_research": e["research_score"],
            }
        )
    return legacy


def get_player_rank(
    player_id: int,
    conn=None,
) -> Tuple[Optional[int], int]:
    """
    Read-only rank lookup. Never seeds player_scores (no _ensure_score_rows).
  On SQLite lock, returns (None, total_players) instead of raising.
    """
    try:
        return get_player_rank_from_snapshot(int(player_id), conn=conn)
    except sqlite3.OperationalError:
        logger.warning(
            "get_player_rank skipped (database locked), player_id=%s",
            player_id,
            exc_info=True,
        )
        owns_conn = False
        if conn is None:
            conn = db()
            owns_conn = True
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS cnt FROM players")
            total = int(cur.fetchone()["cnt"])
            return None, total
        except Exception:
            return None, 0
        finally:
            if owns_conn and conn is not None:
                conn.close()


def read_player_scores(
    player_id: int,
    conn=None,
) -> Dict[str, int]:
    """Read score components without creating rows or recomputing (normalized keys)."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT
                COALESCE(ps.score_total, 0) AS score_total,
                COALESCE(ps.score_buildings, 0) AS score_buildings,
                COALESCE(ps.score_research, 0) AS score_research,
                {_fleet_defense_select(conn)},
                {_evolution_score_select(conn)}
            FROM players p
            LEFT JOIN player_scores ps ON ps.player_id = p.id
            WHERE p.id = ?
            LIMIT 1;
            """,
            (int(player_id),),
        )
        row = cur.fetchone()
        if not row:
            return _zero_scores()
        return _normalize_db_row(dict(row))
    finally:
        if owns_conn:
            conn.close()


def read_player_scores_for_playercard(
    player_id: int,
    conn=None,
) -> Dict[str, int]:
    """Read-only scores using PlayerCard field names (score_total, score_buildings, …)."""
    return format_scores_for_playercard(read_player_scores(int(player_id), conn=conn))


def recompute_and_upsert_score(
    player_id: int,
    conn=None,
    *,
    recalc_ranks: bool = True,
) -> Dict[str, int]:
    scores = refresh_player_score(int(player_id), conn=conn)
    if recalc_ranks:
        recalculate_ranks(conn=conn)
    invalidate_player_score_cache(int(player_id))
    return {
        "score_total": scores["total_score"],
        "score_buildings": scores["building_score"],
        "score_research": scores["research_score"],
        "score_fleet": scores["fleet_score"],
        "score_defense": scores["defense_score"],
        "score_military": scores["military_score"],
    }
