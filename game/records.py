"""Universe records — current #1 holder per category (GC-701)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .buildings import BUILDING_ORDER
from .db import table_exists
from .defense_defs import ACTIVE_DEFENSE_KEYS, DEFENSE_ORDER, DEFENSES
from .fleet_defs import ACTIVE_SHIP_KEYS, SHIPS, sort_ship_keys_by_role
from .galaxy import format_coordinates
from .models import BUILDING_KEYS
from .number_format import fmt_int
from .research import RESEARCH_TECHS
from .troop_defs import ACTIVE_TROOP_KEYS, TROOP_ORDER, TROOPS
from .world_boss_companions import COMPANION_FLAVOR

RECORD_BUILDING_KEYS: Tuple[str, ...] = tuple(BUILDING_ORDER)
RECORD_FLEET_KEYS: Tuple[str, ...] = tuple(sort_ship_keys_by_role(ACTIVE_SHIP_KEYS))
RECORD_DEFENSE_KEYS: Tuple[str, ...] = tuple(
    k for k in DEFENSE_ORDER if k in ACTIVE_DEFENSE_KEYS
)
RECORD_TROOP_KEYS: Tuple[str, ...] = tuple(k for k in TROOP_ORDER if k in ACTIVE_TROOP_KEYS)
RECORD_TITAN_KEYS: Tuple[str, ...] = tuple(sorted(COMPANION_FLAVOR.keys()))

EMPIRE_RECORD_KEYS: Tuple[Tuple[str, str], ...] = (
    ("planet_level", "records_empire_planet_level"),
    ("colonies", "records_empire_colonies"),
)

RECORD_ICON_DEFAULT = "img/buildings/default.png"

RECORD_EMPIRE_ICONS: Dict[str, str] = {
    "planet_level": "img/evo/specialization.png",
    "colonies": "img/buildings/command_center.png",
}

RECORD_TITAN_ICONS: Dict[str, str] = {
    "ancient_leviathan": "img/bosses/ancient_leviathan.png",
    "void_titan": "img/bosses/void_titan.png",
    "planet_eater": "img/bosses/planet_eater.png",
    "rogue_ai_nexus": "img/bosses/rogue_ai_nexus.png",
}


def record_icon(*, group: str, key: str) -> str:
    """Static asset path (relative to ``static/``) — same icons as buildings/research/defense UI."""
    if group == "buildings":
        from .buildings import get_building_icon

        return get_building_icon(key)
    if group == "research":
        icon_file = (RESEARCH_TECHS.get(key) or {}).get("icon") or "energieeffizienz.png"
        return f"img/research/{icon_file}"
    if group == "empire":
        return RECORD_EMPIRE_ICONS.get(key, RECORD_ICON_DEFAULT)
    if group == "fleet":
        return f"img/ships/{key}.png"
    if group == "defense":
        return f"img/defense/{key}.png"
    if group == "troops":
        return f"img/troops/{key}.png"
    if group == "titans":
        if key == "total_titans":
            return RECORD_TITAN_ICONS.get("void_titan", RECORD_ICON_DEFAULT)
        return RECORD_TITAN_ICONS.get(key, f"img/bosses/{key}.png")
    return RECORD_ICON_DEFAULT


def _finalize_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(record)
    out["icon"] = record_icon(group=str(out["group"]), key=str(out["key"]))
    return out


def _coords_from_row(row: Mapping[str, Any]) -> str:
    try:
        return format_coordinates(
            int(row["galaxy"]),
            int(row["system"]),
            int(row["position"]),
        )
    except (TypeError, ValueError, KeyError):
        return ""


def _empty_record(
    *,
    key: str,
    label_key: str,
    group: str,
) -> Dict[str, Any]:
    return _finalize_record(
        {
            "key": key,
            "label_key": label_key,
            "group": group,
            "value": 0,
            "value_fmt": "—",
            "player_id": None,
            "player_name": "",
            "planet_id": None,
            "planet_name": "",
            "coords": "",
            "has_holder": False,
        }
    )


def _record_from_planet_row(
    *,
    key: str,
    label_key: str,
    group: str,
    row: Any,
    value: int,
) -> Dict[str, Any]:
    val = max(0, int(value))
    if val <= 0 or row is None:
        return _empty_record(key=key, label_key=label_key, group=group)
    return _finalize_record(
        {
            "key": key,
            "label_key": label_key,
            "group": group,
            "value": val,
            "value_fmt": fmt_int(val),
            "player_id": int(row["player_id"]),
            "player_name": str(row["player_name"] or ""),
            "planet_id": int(row["planet_id"]),
            "planet_name": str(row["planet_name"] or ""),
            "coords": _coords_from_row(row),
            "has_holder": True,
        }
    )


def _top_building_record(conn, building_key: str) -> Dict[str, Any]:
    if building_key not in BUILDING_KEYS:
        return _empty_record(
            key=building_key,
            label_key=f"building_{building_key}",
            group="buildings",
        )

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            pb.planet_id,
            pb.{building_key} AS value,
            p.name AS planet_name,
            p.galaxy,
            p.system,
            p.position,
            p.player_id,
            pl.name AS player_name
        FROM planet_buildings pb
        INNER JOIN planets p ON p.id = pb.planet_id
        INNER JOIN players pl ON pl.id = p.player_id
        WHERE pb.{building_key} = (
            SELECT MAX({building_key}) FROM planet_buildings
        )
        ORDER BY pb.{building_key} DESC, pb.planet_id ASC
        LIMIT 1;
        """
    )
    row = cur.fetchone()
    value = int(row["value"] or 0) if row else 0
    return _record_from_planet_row(
        key=building_key,
        label_key=f"building_{building_key}",
        group="buildings",
        row=row,
        value=value,
    )


def _top_research_records(conn) -> List[Dict[str, Any]]:
    if not table_exists(conn, "research_levels"):
        return []

    out: List[Dict[str, Any]] = []
    cur = conn.cursor()
    for tech_key in RESEARCH_TECHS:
        cfg = RESEARCH_TECHS[tech_key]
        label_key = str(cfg.get("label_key") or tech_key)
        cur.execute(
            """
            SELECT
                rl.user_id AS player_id,
                rl.level AS value,
                pl.name AS player_name
            FROM research_levels rl
            INNER JOIN players pl ON pl.id = rl.user_id
            WHERE rl.tech_key = ?
              AND rl.level = (
                  SELECT MAX(level) FROM research_levels WHERE tech_key = ?
              )
            ORDER BY rl.level DESC, rl.user_id ASC
            LIMIT 1;
            """,
            (tech_key, tech_key),
        )
        row = cur.fetchone()
        val = int(row["value"] or 0) if row else 0
        if val <= 0 or not row:
            out.append(
                _empty_record(key=tech_key, label_key=label_key, group="research")
            )
            continue
        out.append(
            _finalize_record(
                {
                    "key": tech_key,
                    "label_key": label_key,
                    "group": "research",
                    "value": val,
                    "value_fmt": fmt_int(val),
                    "player_id": int(row["player_id"]),
                    "player_name": str(row["player_name"] or ""),
                    "planet_id": None,
                    "planet_name": "",
                    "coords": "",
                    "has_holder": True,
                }
            )
        )
    return out


def _top_planet_level_record(conn) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.id AS planet_id,
            p.planet_level AS value,
            p.name AS planet_name,
            p.galaxy,
            p.system,
            p.position,
            p.player_id,
            pl.name AS player_name
        FROM planets p
        INNER JOIN players pl ON pl.id = p.player_id
        WHERE p.planet_level = (SELECT MAX(planet_level) FROM planets)
        ORDER BY p.planet_level DESC, p.id ASC
        LIMIT 1;
        """
    )
    row = cur.fetchone()
    value = int(row["value"] or 0) if row else 0
    return _record_from_planet_row(
        key="planet_level",
        label_key="records_empire_planet_level",
        group="empire",
        row=row,
        value=value,
    )


def _top_colonies_record(conn) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.player_id,
            pl.name AS player_name,
            COUNT(*) AS value
        FROM planets p
        INNER JOIN players pl ON pl.id = p.player_id
        GROUP BY p.player_id, pl.name
        ORDER BY value DESC, p.player_id ASC
        LIMIT 1;
        """
    )
    row = cur.fetchone()
    val = int(row["value"] or 0) if row else 0
    if val <= 0 or not row:
        return _empty_record(
            key="colonies",
            label_key="records_empire_colonies",
            group="empire",
        )
    return _finalize_record(
        {
            "key": "colonies",
            "label_key": "records_empire_colonies",
            "group": "empire",
            "value": val,
            "value_fmt": fmt_int(val),
            "player_id": int(row["player_id"]),
            "player_name": str(row["player_name"] or ""),
            "planet_id": None,
            "planet_name": "",
            "coords": "",
            "has_holder": True,
        }
    )


def _player_account_record(
    *,
    key: str,
    label_key: str,
    group: str,
    row: Any,
    value: int,
) -> Dict[str, Any]:
    val = max(0, int(value))
    if val <= 0 or row is None:
        return _empty_record(key=key, label_key=label_key, group=group)
    return _finalize_record(
        {
            "key": key,
            "label_key": label_key,
            "group": group,
            "value": val,
            "value_fmt": fmt_int(val),
            "player_id": int(row["player_id"]),
            "player_name": str(row["player_name"] or ""),
            "planet_id": None,
            "planet_name": "",
            "coords": "",
            "has_holder": True,
        }
    )


def _top_fleet_records(conn) -> List[Dict[str, Any]]:
    if not table_exists(conn, "planet_ships"):
        return [
            _empty_record(
                key=sk,
                label_key=str((SHIPS.get(sk) or {}).get("name_key") or sk),
                group="fleet",
            )
            for sk in RECORD_FLEET_KEYS
        ]
    out: List[Dict[str, Any]] = []
    cur = conn.cursor()
    for ship_key in RECORD_FLEET_KEYS:
        label_key = str((SHIPS.get(ship_key) or {}).get("name_key") or ship_key)
        cur.execute(
            """
            SELECT
                ps.player_id,
                pl.name AS player_name,
                SUM(ps.amount) AS value
            FROM planet_ships ps
            INNER JOIN players pl ON pl.id = ps.player_id
            WHERE ps.ship_key = ?
            GROUP BY ps.player_id, pl.name
            HAVING SUM(ps.amount) > 0
            ORDER BY value DESC, ps.player_id ASC
            LIMIT 1;
            """,
            (ship_key,),
        )
        row = cur.fetchone()
        val = int(row["value"] or 0) if row else 0
        out.append(
            _player_account_record(
                key=ship_key,
                label_key=label_key,
                group="fleet",
                row=row,
                value=val,
            )
        )
    return out


def _top_defense_records(conn) -> List[Dict[str, Any]]:
    if not table_exists(conn, "planet_defense"):
        return [
            _empty_record(
                key=dk,
                label_key=str((DEFENSES.get(dk) or {}).get("name_key") or dk),
                group="defense",
            )
            for dk in RECORD_DEFENSE_KEYS
        ]
    out: List[Dict[str, Any]] = []
    cur = conn.cursor()
    for defense_key in RECORD_DEFENSE_KEYS:
        label_key = str((DEFENSES.get(defense_key) or {}).get("name_key") or defense_key)
        cur.execute(
            """
            SELECT
                p.player_id,
                pl.name AS player_name,
                SUM(pd.amount) AS value
            FROM planet_defense pd
            INNER JOIN planets p ON p.id = pd.planet_id
            INNER JOIN players pl ON pl.id = p.player_id
            WHERE pd.defense_key = ?
            GROUP BY p.player_id, pl.name
            HAVING SUM(pd.amount) > 0
            ORDER BY value DESC, p.player_id ASC
            LIMIT 1;
            """,
            (defense_key,),
        )
        row = cur.fetchone()
        val = int(row["value"] or 0) if row else 0
        out.append(
            _player_account_record(
                key=defense_key,
                label_key=label_key,
                group="defense",
                row=row,
                value=val,
            )
        )
    return out


def _top_troop_records(conn) -> List[Dict[str, Any]]:
    if not table_exists(conn, "planet_troops"):
        return [
            _empty_record(
                key=tk,
                label_key=str((TROOPS.get(tk) or {}).get("name_key") or tk),
                group="troops",
            )
            for tk in RECORD_TROOP_KEYS
        ]
    out: List[Dict[str, Any]] = []
    cur = conn.cursor()
    for troop_key in RECORD_TROOP_KEYS:
        label_key = str((TROOPS.get(troop_key) or {}).get("name_key") or troop_key)
        cur.execute(
            """
            SELECT
                p.player_id,
                pl.name AS player_name,
                SUM(pt.amount) AS value
            FROM planet_troops pt
            INNER JOIN planets p ON p.id = pt.planet_id
            INNER JOIN players pl ON pl.id = p.player_id
            WHERE pt.troop_key = ?
            GROUP BY p.player_id, pl.name
            HAVING SUM(pt.amount) > 0
            ORDER BY value DESC, p.player_id ASC
            LIMIT 1;
            """,
            (troop_key,),
        )
        row = cur.fetchone()
        val = int(row["value"] or 0) if row else 0
        out.append(
            _player_account_record(
                key=troop_key,
                label_key=label_key,
                group="troops",
                row=row,
                value=val,
            )
        )
    return out


def _top_titan_records(conn) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not table_exists(conn, "player_boss_companions"):
        out.append(
            _empty_record(
                key="total_titans",
                label_key="records_titans_total",
                group="titans",
            )
        )
        for boss_key in RECORD_TITAN_KEYS:
            out.append(
                _empty_record(
                    key=boss_key,
                    label_key=f"wb_boss_{boss_key}",
                    group="titans",
                )
            )
        return out

    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            c.player_id,
            pl.name AS player_name,
            COUNT(*) AS value
        FROM player_boss_companions c
        INNER JOIN players pl ON pl.id = c.player_id
        GROUP BY c.player_id, pl.name
        HAVING COUNT(*) > 0
        ORDER BY value DESC, c.player_id ASC
        LIMIT 1;
        """
    )
    total_row = cur.fetchone()
    total_val = int(total_row["value"] or 0) if total_row else 0
    out.append(
        _player_account_record(
            key="total_titans",
            label_key="records_titans_total",
            group="titans",
            row=total_row,
            value=total_val,
        )
    )
    for boss_key in RECORD_TITAN_KEYS:
        cur.execute(
            """
            SELECT
                c.player_id,
                pl.name AS player_name,
                1 AS value
            FROM player_boss_companions c
            INNER JOIN players pl ON pl.id = c.player_id
            WHERE c.boss_key = ?
            ORDER BY COALESCE(c.tamed_at, 0) ASC, c.player_id ASC
            LIMIT 1;
            """,
            (boss_key,),
        )
        row = cur.fetchone()
        out.append(
            _player_account_record(
                key=boss_key,
                label_key=f"wb_boss_{boss_key}",
                group="titans",
                row=row,
                value=int(row["value"] or 0) if row else 0,
            )
        )
    return out


def _group_payload(
    *,
    key: str,
    label_key: str,
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    items = [dict(r) for r in records]
    return {
        "key": key,
        "label_key": label_key,
        "records": items,
        "count": len(items),
        "holders": sum(1 for r in items if r.get("has_holder")),
    }


def build_records_payload(*, conn) -> Dict[str, Any]:
    """Server-authoritative universe record holders (one #1 per category)."""
    building_records = [_top_building_record(conn, key) for key in RECORD_BUILDING_KEYS]
    research_records = _top_research_records(conn)
    empire_records = [
        _top_planet_level_record(conn),
        _top_colonies_record(conn),
    ]
    fleet_records = _top_fleet_records(conn)
    defense_records = _top_defense_records(conn)
    troop_records = _top_troop_records(conn)
    titan_records = _top_titan_records(conn)

    groups = [
        _group_payload(
            key="buildings",
            label_key="records_group_buildings",
            records=building_records,
        ),
        _group_payload(
            key="research",
            label_key="records_group_research",
            records=research_records,
        ),
        _group_payload(
            key="empire",
            label_key="records_group_empire",
            records=empire_records,
        ),
        _group_payload(
            key="fleet",
            label_key="records_group_fleet",
            records=fleet_records,
        ),
        _group_payload(
            key="defense",
            label_key="records_group_defense",
            records=defense_records,
        ),
        _group_payload(
            key="troops",
            label_key="records_group_troops",
            records=troop_records,
        ),
        _group_payload(
            key="titans",
            label_key="records_group_titans",
            records=titan_records,
        ),
    ]
    return {
        "ok": True,
        "groups": groups,
        "group_count": len(groups),
    }
