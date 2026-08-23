"""
Galactic ranking service — arbitrary-precision public owner.

GC-SCORE-BIGNUM keeps the established ranking implementation in the private
``_ranking_core`` module while this canonical owner hardens score semantics,
persistence, ordering and JSON transport for values beyond int64 / JS Number.

Progression ``total_score`` = buildings + research + fleet + defense + evolution.
Liquid resources remain available as ``resource_score`` but do not increase the
main progression rank. Combat destruction remains a military/prestige dimension.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from . import _ranking_core as _core

# Preserve the full existing public surface. Overrides below remain the canonical
# implementations for score math / persistence / ordering.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

JS_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_SQL_ALL_ROWS_LIMIT = 2_147_483_647


def _safe_int(value: Any, *, default: int = 0) -> int:
    """Parse a non-negative score with no gameplay ceiling."""
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0, n)


def _sanitize_scores(scores: Dict[str, Any]) -> Dict[str, int]:
    """Normalize score components and derive the progression-only total."""
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
    destroyed_raw = _safe_int(scores.get("destroyed_raw", scores.get("score_destroyed_raw", 0)))
    total = building + research + fleet + defense + evolution
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


def _score_db_value(value: Any) -> str:
    """Canonical arbitrary-precision persistence representation."""
    return str(_safe_int(value))


def _score_json_value(value: Any) -> int | str:
    """Keep ergonomic small ints; stringify values JS cannot represent exactly."""
    n = _safe_int(value)
    return n if n <= JS_MAX_SAFE_INTEGER else str(n)


def _json_safe_bigints(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return value if -JS_MAX_SAFE_INTEGER <= value <= JS_MAX_SAFE_INTEGER else str(value)
    if isinstance(value, list):
        return [_json_safe_bigints(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_json_safe_bigints(item) for item in value)
    if isinstance(value, dict):
        return {key: _json_safe_bigints(item) for key, item in value.items()}
    return value


def format_scores_for_playercard(normalized: Dict[str, int]) -> Dict[str, Any]:
    """PlayerCard/API score map with lossless JS transport for huge values."""
    values = {
        "score_total": normalized.get("total_score", 0),
        "score_resources": normalized.get("resource_score", 0),
        "score_buildings": normalized.get("building_score", 0),
        "score_research": normalized.get("research_score", 0),
        "score_fleet": normalized.get("fleet_score", 0),
        "score_defense": normalized.get("defense_score", 0),
        "score_combat": normalized.get("combat_score", 0),
        "score_destroyed": normalized.get("destroyed_score", 0),
        "score_military": normalized.get("military_score", 0),
        "score_planet_evolution": normalized.get("evolution_score", 0),
        "total_score": normalized.get("total_score", 0),
        "resource_score": normalized.get("resource_score", 0),
        "building_score": normalized.get("building_score", 0),
        "research_score": normalized.get("research_score", 0),
        "fleet_score": normalized.get("fleet_score", 0),
        "defense_score": normalized.get("defense_score", 0),
        "combat_score": normalized.get("combat_score", 0),
        "destroyed_score": normalized.get("destroyed_score", 0),
        "military_score": normalized.get("military_score", 0),
        "evolution_score": normalized.get("evolution_score", 0),
    }
    return {key: _score_json_value(value) for key, value in values.items()}


def _total_score_sql(conn) -> str:
    """Selector only: score TEXT must never be added/coerced numerically in SQL."""
    return "COALESCE(ps.score_total, '0')"


def upsert_player_scores(player_id: int, scores: Dict[str, int], conn=None) -> None:
    """Persist score components as decimal TEXT, avoiding sqlite3 int64 binding."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    clean = _sanitize_scores(scores)
    stored = {key: _score_db_value(value) for key, value in clean.items()}
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total=excluded.score_total, score_resources=excluded.score_resources,
                score_buildings=excluded.score_buildings, score_research=excluded.score_research,
                score_fleet=excluded.score_fleet, score_defense=excluded.score_defense,
                score_planet_evolution=excluded.score_planet_evolution,
                score_destroyed_raw=excluded.score_destroyed_raw,
                score_combat=excluded.score_combat, score_destroyed=excluded.score_destroyed,
                updated_at=excluded.updated_at
            """,
            (
                int(player_id), stored["total_score"], stored["resource_score"],
                stored["building_score"], stored["research_score"], stored["fleet_score"],
                stored["defense_score"], stored["evolution_score"], stored["destroyed_raw"],
                stored["combat_score"], stored["destroyed_score"],
            ),
        )
    elif has_extended and has_evolution and has_combat:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_buildings, score_research, score_fleet,
                score_defense, score_planet_evolution, score_destroyed_raw,
                score_combat, score_destroyed, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total=excluded.score_total, score_buildings=excluded.score_buildings,
                score_research=excluded.score_research, score_fleet=excluded.score_fleet,
                score_defense=excluded.score_defense,
                score_planet_evolution=excluded.score_planet_evolution,
                score_destroyed_raw=excluded.score_destroyed_raw,
                score_combat=excluded.score_combat, score_destroyed=excluded.score_destroyed,
                updated_at=excluded.updated_at
            """,
            (
                int(player_id), stored["total_score"], stored["building_score"],
                stored["research_score"], stored["fleet_score"], stored["defense_score"],
                stored["evolution_score"], stored["destroyed_raw"], stored["combat_score"],
                stored["destroyed_score"],
            ),
        )
    elif has_extended and has_evolution:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_buildings, score_research,
                score_fleet, score_defense, score_planet_evolution, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total=excluded.score_total, score_buildings=excluded.score_buildings,
                score_research=excluded.score_research, score_fleet=excluded.score_fleet,
                score_defense=excluded.score_defense,
                score_planet_evolution=excluded.score_planet_evolution,
                updated_at=excluded.updated_at
            """,
            (
                int(player_id), stored["total_score"], stored["building_score"],
                stored["research_score"], stored["fleet_score"], stored["defense_score"],
                stored["evolution_score"],
            ),
        )
    elif has_extended:
        cur.execute(
            """
            INSERT INTO player_scores (
                player_id, score_total, score_buildings, score_research,
                score_fleet, score_defense, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET
                score_total=excluded.score_total, score_buildings=excluded.score_buildings,
                score_research=excluded.score_research, score_fleet=excluded.score_fleet,
                score_defense=excluded.score_defense, updated_at=excluded.updated_at
            """,
            (
                int(player_id), stored["total_score"], stored["building_score"],
                stored["research_score"], stored["fleet_score"], stored["defense_score"],
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
            VALUES (?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(player_id) DO UPDATE SET score_total=excluded.score_total,
                score_buildings=excluded.score_buildings, score_research=excluded.score_research,
                updated_at=excluded.updated_at
            """,
            (int(player_id), stored["total_score"], stored["building_score"], stored["research_score"]),
        )

    if owns_conn:
        conn.commit()
        conn.close()


def _all_score_rows_exact(conn) -> List[Dict[str, Any]]:
    """Read normalized scores once; all ordering thereafter is Python-int exact."""
    return _core._fetch_all_score_rows(conn)


def get_sorted_ranking_entries(limit: int = 100, offset: int = 0, conn=None) -> List[Dict[str, Any]]:
    """Player ranking with exact arbitrary-precision ordering."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        # Reuse the mature social/AI enrichment path, but fetch the complete set
        # because SQL TEXT order is intentionally not authoritative anymore.
        rows = _ORIGINAL_SORTED_PLAYERS(limit=_SQL_ALL_ROWS_LIMIT, offset=0, conn=conn)
        rows.sort(
            key=lambda r: (
                -_safe_int(r.get("total_score")),
                -_safe_int(r.get("building_score")),
                -_safe_int(r.get("research_score")),
                int(r.get("player_id") or 0),
            )
        )
        for idx, row in enumerate(rows, start=1):
            row["rank"] = idx
        start = max(0, int(offset))
        stop = start + max(0, int(limit))
        return rows[start:stop]
    finally:
        if owns_conn:
            conn.close()


def get_player_rank_from_snapshot(player_id: int, conn=None) -> Tuple[Optional[int], int]:
    """Exact live total rank; never compares decimal score TEXT in SQL."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        rows = _all_score_rows_exact(conn)
        rows.sort(
            key=lambda r: (-r["total_score"], -r["building_score"], -r["research_score"], r["player_id"])
        )
        pid = int(player_id)
        for idx, row in enumerate(rows, start=1):
            if row["player_id"] == pid:
                return idx, len(rows)
        return None, len(rows)
    finally:
        if owns_conn:
            conn.close()


def get_player_category_ranks(
    player_id: int,
    conn=None,
    *,
    skip_live_total: bool = False,
) -> Dict[str, Any]:
    """Exact category ranks from normalized Python integers."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        rows = _all_score_rows_exact(conn)
        pid = int(player_id)
        if not any(row["player_id"] == pid for row in rows):
            return {"total_players": len(rows)}
        ranks: Dict[str, Any] = {"total_players": len(rows)}

        def assign(name: str, key) -> None:
            ordered = sorted(rows, key=key)
            for idx, row in enumerate(ordered, start=1):
                if row["player_id"] == pid:
                    ranks[name] = idx
                    return

        assign("building", lambda r: (-r["building_score"], -r["research_score"], r["player_id"]))
        assign("research", lambda r: (-r["research_score"], -r["building_score"], r["player_id"]))
        assign("fleet", lambda r: (-r["fleet_score"], -r["building_score"], r["player_id"]))
        assign("defense", lambda r: (-r["defense_score"], r["player_id"]))
        assign("combat", lambda r: (-r.get("combat_score", 0), -r["fleet_score"], r["player_id"]))
        assign("destroyed", lambda r: (-r.get("destroyed_score", 0), -r["fleet_score"], r["player_id"]))
        assign("military", lambda r: (-r.get("military_score", 0), -r["fleet_score"], r["player_id"]))
        assign("evolution", lambda r: (-r.get("evolution_score", 0), r["player_id"]))
        if not skip_live_total:
            assign("total", lambda r: (-r["total_score"], -r["building_score"], -r["research_score"], r["player_id"]))
        return ranks
    finally:
        if owns_conn:
            conn.close()


def get_sorted_alliance_ranking_entries(
    limit: int = 100,
    offset: int = 0,
    conn=None,
) -> List[Dict[str, Any]]:
    """Alliance ranking with exact member score aggregation in Python."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        if not (
            table_exists(conn, "alliances")
            and table_exists(conn, "alliance_members")
            and table_exists(conn, "player_scores")
        ):
            return []
        raw_rows = conn.execute(
            """
            SELECT a.id AS alliance_id, a.tag AS alliance_tag, a.name AS alliance_name,
                   am.player_id, COALESCE(ps.score_total, '0') AS score_total
            FROM alliances a
            INNER JOIN alliance_members am ON am.alliance_id = a.id
            LEFT JOIN player_scores ps ON ps.player_id = am.player_id
            ORDER BY a.id ASC, am.player_id ASC
            """
        ).fetchall()
        grouped: Dict[int, Dict[str, Any]] = {}
        for raw in raw_rows:
            d = dict(raw)
            aid = int(d["alliance_id"])
            item = grouped.setdefault(
                aid,
                {
                    "alliance_id": aid,
                    "alliance_tag": str(d.get("alliance_tag") or "").strip(),
                    "alliance_name": str(d.get("alliance_name") or "").strip(),
                    "member_count": 0,
                    "alliance_score": 0,
                    "is_current_alliance": False,
                },
            )
            item["member_count"] += 1
            item["alliance_score"] += _safe_int(d.get("score_total"))
        ordered = sorted(grouped.values(), key=lambda row: (-row["alliance_score"], row["alliance_id"]))
        for idx, row in enumerate(ordered, start=1):
            row["rank"] = idx
        start = max(0, int(offset))
        return ordered[start : start + max(0, int(limit))]
    finally:
        if owns_conn:
            conn.close()


def get_player_alliance_ranking_snapshot(player_id: int, conn=None) -> Dict[str, Any]:
    """Current player's alliance snapshot from exact Python aggregation."""
    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        empty = {
            "alliance_id": None,
            "alliance_tag": "",
            "alliance_name": "",
            "alliance_score": 0,
            "alliance_rank": None,
            "total_alliances": 0,
            "member_count": 0,
        }
        if not (table_exists(conn, "alliances") and table_exists(conn, "alliance_members")):
            return empty
        mine = conn.execute(
            """SELECT a.id AS alliance_id FROM alliance_members am
               INNER JOIN alliances a ON a.id = am.alliance_id
               WHERE am.player_id = ? ORDER BY a.id ASC LIMIT 1""",
            (int(player_id),),
        ).fetchone()
        all_rows = get_sorted_alliance_ranking_entries(limit=_SQL_ALL_ROWS_LIMIT, offset=0, conn=conn)
        if not mine:
            return {**empty, "total_alliances": len(all_rows)}
        aid = int(mine["alliance_id"])
        match = next((row for row in all_rows if row["alliance_id"] == aid), None)
        if not match:
            return {**empty, "alliance_id": aid, "total_alliances": len(all_rows)}
        return {
            "alliance_id": aid,
            "alliance_tag": match["alliance_tag"],
            "alliance_name": match["alliance_name"],
            "alliance_score": match["alliance_score"],
            "alliance_rank": match["rank"],
            "total_alliances": len(all_rows),
            "member_count": match["member_count"],
        }
    finally:
        if owns_conn:
            conn.close()


def build_ranking_api_payload(current_player_id: int, limit: int = 100, refresh: bool = False) -> Dict[str, Any]:
    """Canonical ranking API with lossless transport for JS-unsafe integers."""
    # Core implementation remains responsible for the mature payload shape;
    # its function globals are rebound below to the exact big-score paths.
    return _json_safe_bigints(_ORIGINAL_BUILD_PAYLOAD(current_player_id, limit=limit, refresh=refresh))


# Capture mature implementations before rebinding their module globals.
_ORIGINAL_SORTED_PLAYERS = _core.get_sorted_ranking_entries
_ORIGINAL_BUILD_PAYLOAD = _core.build_ranking_api_payload

# All legacy/core functions resolve these names dynamically from their module.
# Rebinding here makes the entire existing call graph use one canonical big-score truth.
_core._safe_int = _safe_int
_core._sanitize_scores = _sanitize_scores
_core.format_scores_for_playercard = format_scores_for_playercard
_core._total_score_sql = _total_score_sql
_core.upsert_player_scores = upsert_player_scores
_core.get_sorted_ranking_entries = get_sorted_ranking_entries
_core.get_player_rank_from_snapshot = get_player_rank_from_snapshot
_core.get_player_category_ranks = get_player_category_ranks
_core.get_sorted_alliance_ranking_entries = get_sorted_alliance_ranking_entries
_core.get_player_alliance_ranking_snapshot = get_player_alliance_ranking_snapshot

# Public wrapper overrides must win over the generic re-export performed above.
globals().update(
    {
        "_safe_int": _safe_int,
        "_sanitize_scores": _sanitize_scores,
        "format_scores_for_playercard": format_scores_for_playercard,
        "_total_score_sql": _total_score_sql,
        "upsert_player_scores": upsert_player_scores,
        "get_sorted_ranking_entries": get_sorted_ranking_entries,
        "get_player_rank_from_snapshot": get_player_rank_from_snapshot,
        "get_player_category_ranks": get_player_category_ranks,
        "get_sorted_alliance_ranking_entries": get_sorted_alliance_ranking_entries,
        "get_player_alliance_ranking_snapshot": get_player_alliance_ranking_snapshot,
        "build_ranking_api_payload": build_ranking_api_payload,
    }
)
