"""
Galactic ranking service – single source of truth for scores and ranks.

total_score = weighted(building) + weighted(research) + fleet + defense + evolution
Component weights from game_settings: score_weight_buildings, score_weight_research.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .db import column_exists, db, table_exists

logger = logging.getLogger(__name__)

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
    building = _safe_int(scores.get("building_score", scores.get("score_buildings", 0)))
    research = _safe_int(scores.get("research_score", scores.get("score_research", 0)))
    fleet = _safe_int(scores.get("fleet_score", scores.get("score_fleet", 0)))
    defense = _safe_int(scores.get("defense_score", scores.get("score_defense", 0)))
    evolution = _safe_int(scores.get("evolution_score", scores.get("score_planet_evolution", 0)))
    total = _safe_int(building + research + fleet + defense + evolution)
    return {
        "total_score": total,
        "building_score": building,
        "research_score": research,
        "fleet_score": fleet,
        "defense_score": defense,
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


def _sum_costs_up_to_level(base_m: int, base_c: int, factor: float, level: int) -> int:
    if level <= 0:
        return 0
    total = 0
    for lv in range(1, level + 1):
        mult = factor ** (lv - 1)
        total += int(base_m * mult) + int(base_c * mult)
    return _safe_int(total)


def _score_exponent(conn) -> float:
    from .models import get_game_settings

    settings = get_game_settings(conn=conn) or {}
    try:
        return float(settings.get("score_cost_exponent", 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def _score_weights(conn) -> Tuple[float, float]:
    from .models import get_game_settings

    settings = get_game_settings(conn=conn) or {}
    try:
        w_build = float(settings.get("score_weight_buildings", 1.0) or 1.0)
    except (TypeError, ValueError):
        w_build = 1.0
    try:
        w_research = float(settings.get("score_weight_research", 1.0) or 1.0)
    except (TypeError, ValueError):
        w_research = 1.0
    return max(0.0, w_build), max(0.0, w_research)


def compute_player_scores(
    player_id: int,
    conn=None,
) -> Dict[str, int]:
    """
    Central score calculation. Returns component scores and total_score as their sum.
    """
    from .models import get_planet_buildings, get_planets_by_player, get_research_levels

    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    try:
        exp = _score_exponent(conn)
        w_build, w_research = _score_weights(conn)
        from .buildings import BASE_COST, BUILDING_ORDER, COST_FACTOR
        from .research import RESEARCH_TECHS

        planets = get_planets_by_player(int(player_id), conn=conn)
        building_sum_costs = 0
        for p in planets:
            b = get_planet_buildings(int(p["id"]), conn=conn)
            for key in BUILDING_ORDER:
                lvl = int(b.get(key, 0) or 0)
                if lvl <= 0:
                    continue
                base = BASE_COST.get(key, (0, 0))
                fac = float(COST_FACTOR.get(key, 1.5))
                building_sum_costs += _sum_costs_up_to_level(
                    int(base[0]), int(base[1]), fac, lvl
                )

        building_score = _safe_int(
            ((building_sum_costs**exp) * w_build) if building_sum_costs > 0 else 0
        )

        levels = get_research_levels(int(player_id), conn=conn)
        research_sum_costs = 0
        for tech_key, cfg in RESEARCH_TECHS.items():
            lvl = int(levels.get(tech_key, 0) or 0)
            if lvl <= 0:
                continue
            base_m = int(cfg.get("base_cost_m", 0) or 0)
            base_c = int(cfg.get("base_cost_c", 0) or 0)
            fac = float(cfg.get("cost_factor", 1.6) or 1.6)
            research_sum_costs += _sum_costs_up_to_level(base_m, base_c, fac, lvl)

        research_score = _safe_int(
            ((research_sum_costs**exp) * w_research) if research_sum_costs > 0 else 0
        )

        fleet_score = 0
        defense_score = 0
        evolution_score = 0
        try:
            from .planet_evolution.scoring import compute_player_evolution_score

            evolution_score = compute_player_evolution_score(int(player_id), conn)
        except Exception:
            evolution_score = 0

        return _sanitize_scores(
            {
                "building_score": building_score,
                "research_score": research_score,
                "fleet_score": fleet_score,
                "defense_score": defense_score,
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
    fleet = _safe_int(row.get("score_fleet", 0)) if "score_fleet" in keys else 0
    defense = _safe_int(row.get("score_defense", 0)) if "score_defense" in keys else 0
    evolution = (
        _safe_int(row.get("score_planet_evolution", 0))
        if "score_planet_evolution" in keys
        else 0
    )
    result = _sanitize_scores(
        {
            "building_score": building,
            "research_score": research,
            "fleet_score": fleet,
            "defense_score": defense,
            "evolution_score": evolution,
        }
    )
    if "score_total" in keys:
        result["total_score"] = _safe_int(row.get("score_total", result["total_score"]))
    return result


def format_scores_for_playercard(normalized: Dict[str, int]) -> Dict[str, int]:
    """Map internal normalized scores to PlayerCard template/API field names."""
    return {
        "score_total": int(normalized.get("total_score", 0) or 0),
        "score_buildings": int(normalized.get("building_score", 0) or 0),
        "score_research": int(normalized.get("research_score", 0) or 0),
        "score_fleet": int(normalized.get("fleet_score", 0) or 0),
        "score_defense": int(normalized.get("defense_score", 0) or 0),
        "score_planet_evolution": int(normalized.get("evolution_score", 0) or 0),
        # Backward-compatible aliases (ranking/HUD internals)
        "total_score": int(normalized.get("total_score", 0) or 0),
        "building_score": int(normalized.get("building_score", 0) or 0),
        "research_score": int(normalized.get("research_score", 0) or 0),
        "fleet_score": int(normalized.get("fleet_score", 0) or 0),
        "defense_score": int(normalized.get("defense_score", 0) or 0),
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
    if column_exists(conn, "player_scores", "score_fleet"):
        return (
            "(COALESCE(ps.score_buildings, 0) + COALESCE(ps.score_research, 0) + "
            "COALESCE(ps.score_fleet, 0) + COALESCE(ps.score_defense, 0))"
        )
    return "(COALESCE(ps.score_buildings, 0) + COALESCE(ps.score_research, 0))"


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

    if has_extended and has_evolution:
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
        fleet = _safe_int(row_dict.get("score_fleet", 0)) if "score_fleet" in keys else 0
        defense = _safe_int(row_dict.get("score_defense", 0)) if "score_defense" in keys else 0
        evolution = (
            _safe_int(row_dict.get("score_planet_evolution", 0))
            if "score_planet_evolution" in keys
            else 0
        )
        computed = _sanitize_scores(
            {
                "building_score": building,
                "research_score": research,
                "fleet_score": fleet,
                "defense_score": defense,
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
    Incremental hook: refresh one player + rebuild rank snapshot.
    Call after building/research/fleet/defense changes.
    """
    return recompute_and_upsert_score(int(player_id), conn=conn)


def _ensure_score_rows(conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
        SELECT p.id, 0, 0, 0, CAST(strftime('%s','now') AS INTEGER)
        FROM players p
        WHERE NOT EXISTS (SELECT 1 FROM player_scores s WHERE s.player_id = p.id)
        """
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
            VALUES (?, 0, 0, 0, CAST(strftime('%s','now') AS INTEGER))
            ON CONFLICT(player_id) DO NOTHING;
            """,
            (int(player_id),),
        )
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def _fleet_defense_select(conn) -> str:
    if column_exists(conn, "player_scores", "score_fleet"):
        return "COALESCE(ps.score_fleet, 0) AS score_fleet, COALESCE(ps.score_defense, 0) AS score_defense"
    return "0 AS score_fleet, 0 AS score_defense"


def _evolution_score_select(conn) -> str:
    if column_exists(conn, "player_scores", "score_planet_evolution"):
        return "COALESCE(ps.score_planet_evolution, 0) AS score_planet_evolution"
    return "0 AS score_planet_evolution"


def _fetch_all_score_rows(conn) -> List[Dict[str, Any]]:
    _ensure_score_rows(conn)
    cur = conn.cursor()
    extra = _fleet_defense_select(conn)
    cur.execute(
        f"""
        SELECT
            p.id AS player_id,
            p.name AS commander_name,
            COALESCE(ps.score_total, 0) AS score_total,
            COALESCE(ps.score_buildings, 0) AS score_buildings,
            COALESCE(ps.score_research, 0) AS score_research,
            {extra}
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

        rank_total_map = {r["player_id"]: idx for idx, r in enumerate(total_sorted, start=1)}
        rank_building_map = {r["player_id"]: idx for idx, r in enumerate(building_sorted, start=1)}
        rank_research_map = {r["player_id"]: idx for idx, r in enumerate(research_sorted, start=1)}

        cur = conn.cursor()
        for row in rows:
            pid = row["player_id"]
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
                conn.execute("BEGIN IMMEDIATE")
            count = _apply()
            if owns_conn:
                conn.commit()
            return count
    except Exception:
        if owns_conn:
            conn.rollback()
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
                conn.execute("BEGIN IMMEDIATE")

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
                conn.commit()

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
                conn.rollback()
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
        return {"total": 0, "buildings": 0, "research": 0, "fleet": 0, "defense": 0, "evolution": 0}

    pid = int(player_id)
    now = time.time()

    def _to_legacy(s: Dict[str, int]) -> Dict[str, int]:
        return {
            "total": int(s.get("total_score", 0)),
            "buildings": int(s.get("building_score", 0)),
            "research": int(s.get("research_score", 0)),
            "fleet": int(s.get("fleet_score", 0)),
            "defense": int(s.get("defense_score", 0)),
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
        if read_only:
            out = _to_legacy(_zero_scores())
        else:
            out = _to_legacy(refresh_player_score(pid))
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
        join_parts.append("LEFT JOIN player_cards pc ON pc.player_id = p.id")
        if table_exists(conn, "player_card_badges"):
            select_parts.extend(
                [
                    "b1.icon AS badge1_icon",
                    "b1.rarity AS badge1_rarity",
                    "b1.name_i18n_key AS badge1_key",
                    "b2.icon AS badge2_icon",
                    "b2.rarity AS badge2_rarity",
                    "b2.name_i18n_key AS badge2_key",
                    "b3.icon AS badge3_icon",
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
                    "NULL AS badge1_icon", "NULL AS badge1_rarity", "NULL AS badge1_key",
                    "NULL AS badge2_icon", "NULL AS badge2_rarity", "NULL AS badge2_key",
                    "NULL AS badge3_icon", "NULL AS badge3_rarity", "NULL AS badge3_key",
                ]
            )
    else:
        select_parts.extend(
            [
                "NULL AS card_avatar_url",
                "NULL AS card_title",
                "NULL AS card_theme",
                "1 AS card_is_public",
                "NULL AS card_badge_1",
                "NULL AS card_badge_2",
                "NULL AS card_badge_3",
                "NULL AS badge1_icon", "NULL AS badge1_rarity", "NULL AS badge1_key",
                "NULL AS badge2_icon", "NULL AS badge2_rarity", "NULL AS badge2_key",
                "NULL AS badge3_icon", "NULL AS badge3_rarity", "NULL AS badge3_key",
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
                "LEFT JOIN alliance_members am ON am.player_id = p.id",
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
    icon = raw.get(f"badge{slot}_icon")
    if not icon:
        return None
    return {
        "icon": str(icon),
        "rarity": str(raw.get(f"badge{slot}_rarity") or "common"),
        "name_key": str(raw.get(f"badge{slot}_key") or ""),
    }


def enrich_ranking_social_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize player-card and alliance fields for ranking API / templates.
    Avatar URL is only exposed when the profile is public and passes validation.
    """
    from .playercard import avatar_url_for_client, sanitize_text_field, validate_avatar_url, validate_theme, TITLE_MAX

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
            ok, validated = validate_avatar_url(raw_url)
            if ok and validated:
                avatar_url = avatar_url_for_client(validated, card_updated_at)
                show_avatar = True

    title = sanitize_text_field(raw.get("card_title"), TITLE_MAX) if is_public else ""
    theme = validate_theme(raw.get("card_theme")) if raw.get("card_theme") is not None else "cyan"

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
    evo = _evolution_score_select(conn)
    total_expr = _total_score_sql(conn)
    social_select, social_join = _ranking_social_select_and_join(conn)
    rank_select = ""
    if column_exists(conn, "player_scores", "rank_total"):
        rank_select = ", ps.rank_total, ps.rank_building, ps.rank_research"
    cur.execute(
        f"""
        SELECT
            p.id AS player_id,
            p.name AS commander_name,
            COALESCE(ps.score_total, 0) AS score_total,
            COALESCE(ps.score_buildings, 0) AS score_buildings,
            COALESCE(ps.score_research, 0) AS score_research,
            {extra},
            {evo},
            COALESCE(ps.updated_at, 0) AS score_updated_at{rank_select},
            {social_select}
        FROM players p
        LEFT JOIN player_scores ps ON ps.player_id = p.id
        {social_join}
        ORDER BY {total_expr} DESC,
                 COALESCE(ps.score_buildings, 0) DESC,
                 COALESCE(ps.score_research, 0) DESC,
                 p.id ASC
        LIMIT ? OFFSET ?
        """,
        (int(limit), int(offset)),
    )
    rows = cur.fetchall()
    if owns_conn:
        conn.close()

    out: List[Dict[str, Any]] = []
    base_rank = int(offset)
    for idx, raw in enumerate(rows, start=1):
        d = dict(raw)
        scores = _normalize_db_row(d)
        rank = base_rank + idx
        social = enrich_ranking_social_fields(d)
        from .player_display import commander_display_name, commander_lookup_name

        raw_name = d.get("commander_name") or "—"
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
                **scores,
                **social,
            }
        )
    return out


def get_player_rank_from_snapshot(player_id: int, conn=None) -> Tuple[Optional[int], int]:
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS cnt FROM players")
    total_players = int(cur.fetchone()["cnt"])

    if column_exists(conn, "player_scores", "rank_total"):
        cur.execute(
            "SELECT rank_total FROM player_scores WHERE player_id = ?",
            (int(player_id),),
        )
        row = cur.fetchone()
        if row and row["rank_total"] is not None:
            snap_rank = int(row["rank_total"])
            if snap_rank >= 1:
                if owns_conn:
                    conn.close()
                return snap_rank, total_players

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


def get_player_category_ranks(player_id: int, conn=None) -> Dict[str, Any]:
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
    my_evo = _safe_int(score_row["score_planet_evolution"]) if "score_planet_evolution" in keys else 0

    if column_exists(conn, "player_scores", "rank_total"):
        cur.execute(
            "SELECT rank_total, rank_building, rank_research FROM player_scores WHERE player_id = ?",
            (int(player_id),),
        )
        row = cur.fetchone()
        if row:
            if row["rank_total"] is not None:
                ranks["total"] = int(row["rank_total"])
            if row["rank_building"] is not None:
                ranks["building"] = int(row["rank_building"])
            if row["rank_research"] is not None:
                ranks["research"] = int(row["rank_research"])

    if column_exists(conn, "player_scores", "score_fleet"):
        cur.execute(
            """
            SELECT COUNT(*) AS better FROM player_scores
            WHERE COALESCE(score_fleet, 0) > ?
               OR (COALESCE(score_fleet, 0) = ? AND player_id < ?)
            """,
            (my_fleet, my_fleet, int(player_id)),
        )
        ranks["fleet"] = int(cur.fetchone()["better"]) + 1

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
    my_scores = get_player_score_cached(pid)
    category_ranks = get_player_category_ranks(pid)
    my_rank = category_ranks.get("total")
    total_players = int(category_ranks.get("total_players") or 0)

    current = {
        "rank": my_rank,
        "total_players": total_players,
        "total_score": int(my_scores.get("total", 0)),
        "building_score": int(my_scores.get("buildings", 0)),
        "research_score": int(my_scores.get("research", 0)),
        "fleet_score": int(my_scores.get("fleet", 0)),
        "defense_score": int(my_scores.get("defense", 0)),
        "evolution_score": int(my_scores.get("evolution", 0)),
        "ranks": category_ranks,
    }

    in_top = next((r for r in top_players if int(r["player_id"]) == pid), None)
    if in_top is not None:
        current["rank"] = in_top["rank"]
        current["total_score"] = in_top["total_score"]
        current["building_score"] = in_top["building_score"]
        current["research_score"] = in_top["research_score"]
        current["fleet_score"] = in_top["fleet_score"]
        current["defense_score"] = in_top["defense_score"]
        current["evolution_score"] = in_top.get("evolution_score", 0)

    return current


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
    }
