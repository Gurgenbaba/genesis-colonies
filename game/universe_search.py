"""
Universe Search (GC-880) — player / planet / alliance discovery.

Owner for public name→coords lookup. Player results expose homeworld only;
colonies appear only via planet-name search. Reuses galaxy coord helpers and
alliance member homeworld payload.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .alliance import alliance_hub_schema_ready, get_alliance_members
from .db import db, table_exists
from .galaxy import format_coordinates, galaxy_view_href, parse_coordinate_query

SEARCH_TYPES = frozenset({"player", "planet", "alliance"})
MIN_QUERY_LEN = 2
RESULT_LIMIT = 25


def _escape_like(raw: str) -> str:
    return str(raw).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _prefix_like(raw: str) -> str:
    return _escape_like(raw) + "%"


def _contains_like(raw: str) -> str:
    return "%" + _escape_like(raw) + "%"


def _coords_payload(
    *,
    galaxy: Any,
    system: Any,
    position: Any,
    name: Any = None,
    planet_id: Any = None,
) -> Optional[Dict[str, Any]]:
    if galaxy is None or system is None or position is None:
        return None
    try:
        g, s, p = int(galaxy), int(system), int(position)
        coords = format_coordinates(g, s, p)
    except Exception:
        return None
    out: Dict[str, Any] = {
        "galaxy": g,
        "system": s,
        "position": p,
        "coords": coords,
    }
    if name is not None:
        out["name"] = str(name or "")
    if planet_id is not None:
        try:
            out["id"] = int(planet_id)
        except (TypeError, ValueError):
            pass
    return out


def _coord_jump_meta(query: str) -> Optional[Dict[str, Any]]:
    parsed = parse_coordinate_query(query)
    if not parsed:
        return None
    galaxy = int(parsed["galaxy"])
    system = int(parsed["system"])
    position = parsed.get("position")
    if position is not None:
        try:
            coords = format_coordinates(galaxy, system, int(position))
        except Exception:
            coords = f"[{galaxy}:{system}:{int(position)}]"
        href = galaxy_view_href(coords) or f"/galaxy?q={galaxy}:{system}:{int(position)}"
    else:
        coords = f"[{galaxy}:{system}]"
        href = galaxy_view_href(f"{galaxy}:{system}") or f"/galaxy?q={galaxy}:{system}"
    return {
        "galaxy": galaxy,
        "system": system,
        "position": int(position) if position is not None else None,
        "coords": coords,
        "href": href,
    }


def _ban_clause_sql(alias: str = "p") -> str:
    return f"({alias}.banned_until IS NULL OR {alias}.banned_until <= ?)"


def _search_players(conn, query: str, *, now: int, limit: int) -> List[Dict[str, Any]]:
    like = _prefix_like(query)
    cur = conn.cursor()
    has_alliance = table_exists(conn, "alliance_members") and table_exists(conn, "alliances")
    if has_alliance:
        sql = f"""
            SELECT p.id AS player_id, p.name AS player_name,
                   a.id AS alliance_id, a.tag AS alliance_tag,
                   hw.id AS homeworld_id, hw.name AS homeworld_name,
                   hw.galaxy AS homeworld_galaxy, hw.system AS homeworld_system,
                   hw.position AS homeworld_position
            FROM players p
            LEFT JOIN alliance_members am ON am.player_id = p.id
            LEFT JOIN alliances a ON a.id = am.alliance_id
            LEFT JOIN planets hw
              ON hw.player_id = p.id AND COALESCE(hw.is_homeworld, 0) = 1
            WHERE p.name LIKE ? ESCAPE '\\'
              AND {_ban_clause_sql('p')}
            ORDER BY p.name ASC
            LIMIT ?;
        """
    else:
        sql = f"""
            SELECT p.id AS player_id, p.name AS player_name,
                   NULL AS alliance_id, NULL AS alliance_tag,
                   hw.id AS homeworld_id, hw.name AS homeworld_name,
                   hw.galaxy AS homeworld_galaxy, hw.system AS homeworld_system,
                   hw.position AS homeworld_position
            FROM players p
            LEFT JOIN planets hw
              ON hw.player_id = p.id AND COALESCE(hw.is_homeworld, 0) = 1
            WHERE p.name LIKE ? ESCAPE '\\'
              AND {_ban_clause_sql('p')}
            ORDER BY p.name ASC
            LIMIT ?;
        """
    cur.execute(sql, (like, int(now), int(limit)))
    results: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        d = dict(row)
        homeworld = _coords_payload(
            galaxy=d.get("homeworld_galaxy"),
            system=d.get("homeworld_system"),
            position=d.get("homeworld_position"),
            name=d.get("homeworld_name"),
            planet_id=d.get("homeworld_id"),
        )
        results.append(
            {
                "type": "player",
                "player_id": int(d["player_id"]),
                "name": str(d.get("player_name") or ""),
                "alliance_id": int(d["alliance_id"]) if d.get("alliance_id") is not None else None,
                "alliance_tag": str(d.get("alliance_tag") or "") or None,
                "homeworld": homeworld,
            }
        )
    return results


def _search_planets(conn, query: str, *, now: int, limit: int) -> List[Dict[str, Any]]:
    like = _contains_like(query)
    cur = conn.cursor()
    has_alliance = table_exists(conn, "alliance_members") and table_exists(conn, "alliances")
    if has_alliance:
        sql = f"""
            SELECT pl.id AS planet_id, pl.name AS planet_name,
                   pl.galaxy, pl.system, pl.position,
                   COALESCE(pl.is_homeworld, 0) AS is_homeworld,
                   p.id AS owner_id, p.name AS owner_name,
                   a.id AS alliance_id, a.tag AS alliance_tag
            FROM planets pl
            JOIN players p ON p.id = pl.player_id
            LEFT JOIN alliance_members am ON am.player_id = p.id
            LEFT JOIN alliances a ON a.id = am.alliance_id
            WHERE pl.name LIKE ? ESCAPE '\\'
              AND {_ban_clause_sql('p')}
            ORDER BY pl.name ASC
            LIMIT ?;
        """
    else:
        sql = f"""
            SELECT pl.id AS planet_id, pl.name AS planet_name,
                   pl.galaxy, pl.system, pl.position,
                   COALESCE(pl.is_homeworld, 0) AS is_homeworld,
                   p.id AS owner_id, p.name AS owner_name,
                   NULL AS alliance_id, NULL AS alliance_tag
            FROM planets pl
            JOIN players p ON p.id = pl.player_id
            WHERE pl.name LIKE ? ESCAPE '\\'
              AND {_ban_clause_sql('p')}
            ORDER BY pl.name ASC
            LIMIT ?;
        """
    cur.execute(sql, (like, int(now), int(limit)))
    results: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        d = dict(row)
        coords = _coords_payload(
            galaxy=d.get("galaxy"),
            system=d.get("system"),
            position=d.get("position"),
            name=d.get("planet_name"),
            planet_id=d.get("planet_id"),
        )
        results.append(
            {
                "type": "planet",
                "planet_id": int(d["planet_id"]),
                "planet_name": str(d.get("planet_name") or ""),
                "is_homeworld": bool(int(d.get("is_homeworld") or 0)),
                "owner_id": int(d["owner_id"]),
                "owner_name": str(d.get("owner_name") or ""),
                "alliance_id": int(d["alliance_id"]) if d.get("alliance_id") is not None else None,
                "alliance_tag": str(d.get("alliance_tag") or "") or None,
                "coords": coords,
            }
        )
    return results


def _member_search_shape(member: Dict[str, Any]) -> Dict[str, Any]:
    homeworld = member.get("homeworld")
    return {
        "player_id": int(member["player_id"]),
        "player_name": str(member.get("player_name") or ""),
        "role": str(member.get("role") or "member"),
        "homeworld": homeworld if isinstance(homeworld, dict) else None,
    }


def _search_alliances(conn, query: str, *, limit: int) -> List[Dict[str, Any]]:
    if not alliance_hub_schema_ready(conn):
        return []
    like = _contains_like(query)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT a.id, a.tag, a.name,
               (SELECT COUNT(*) FROM alliance_members am WHERE am.alliance_id = a.id) AS member_count
        FROM alliances a
        WHERE a.tag LIKE ? ESCAPE '\\' OR a.name LIKE ? ESCAPE '\\'
        ORDER BY a.tag ASC
        LIMIT ?;
        """,
        (like, like, int(limit)),
    )
    results: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        d = dict(row)
        aid = int(d["id"])
        members = get_alliance_members(aid, conn=conn)
        results.append(
            {
                "type": "alliance",
                "alliance_id": aid,
                "tag": str(d.get("tag") or ""),
                "name": str(d.get("name") or ""),
                "member_count": int(d.get("member_count") or len(members)),
                "members": [_member_search_shape(m) for m in members],
            }
        )
    return results


def search_universe(
    query: str,
    search_type: str = "player",
    *,
    limit: int = RESULT_LIMIT,
    conn=None,
) -> Dict[str, Any]:
    """
    Run a universe search.

    Returns ``{ ok, error, results, meta }``. ``meta.coord_jump`` is set when
    the raw query parses as galaxy coordinates.
    """
    q = str(query or "").strip()
    stype = str(search_type or "player").strip().lower()
    if stype not in SEARCH_TYPES:
        return {
            "ok": False,
            "error": "invalid_search_type",
            "results": [],
            "meta": {"query": q, "type": stype, "coord_jump": None},
        }

    coord_jump = _coord_jump_meta(q)
    meta: Dict[str, Any] = {
        "query": q,
        "type": stype,
        "limit": int(limit),
        "coord_jump": coord_jump,
    }

    if not q:
        return {"ok": True, "error": None, "results": [], "meta": meta}

    # Pure coordinate query → jump meta only (no LIKE name search).
    if coord_jump is not None:
        return {"ok": True, "error": None, "results": [], "meta": meta}

    if len(q) < MIN_QUERY_LEN:
        return {
            "ok": False,
            "error": "query_too_short",
            "results": [],
            "meta": meta,
        }

    own = conn is None
    if own:
        conn = db()
    try:
        now = int(time.time())
        lim = max(1, min(int(limit or RESULT_LIMIT), RESULT_LIMIT))
        if stype == "player":
            results = _search_players(conn, q, now=now, limit=lim)
        elif stype == "planet":
            results = _search_planets(conn, q, now=now, limit=lim)
        else:
            results = _search_alliances(conn, q, limit=lim)
        return {"ok": True, "error": None, "results": results, "meta": meta}
    finally:
        if own:
            conn.close()
