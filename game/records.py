"""Universe records — current #1 holder per category (GC-701)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import table_exists
from .galaxy import format_coordinates
from .models import BUILDING_KEYS
from .number_format import fmt_int
from .research import RESEARCH_TECHS

RECORD_BUILDING_KEYS: Tuple[str, ...] = (
    "metal_mine",
    "crystal_mine",
    "research_lab",
    "orbital_shipyard",
    "defense_factory",
)

EMPIRE_RECORD_KEYS: Tuple[Tuple[str, str], ...] = (
    ("planet_level", "records_empire_planet_level"),
    ("colonies", "records_empire_colonies"),
)

MILITARY_RECORD_KEYS: Tuple[Tuple[str, str], ...] = (
    ("defense_units", "records_military_defense_units"),
)

RECORD_ICON_DEFAULT = "img/buildings/default.png"

RECORD_EMPIRE_ICONS: Dict[str, str] = {
    "planet_level": "img/evo/specialization.png",
    "colonies": "img/ships/seed_ark.png",
}

RECORD_MILITARY_ICONS: Dict[str, str] = {
    "defense_units": "img/defense/sentinel_turret.png",
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
    if group == "military":
        return RECORD_MILITARY_ICONS.get(key, RECORD_ICON_DEFAULT)
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
        GROUP BY p.player_id
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


def _top_defense_units_record(conn) -> Dict[str, Any]:
    if not table_exists(conn, "planet_defense"):
        return _empty_record(
            key="defense_units",
            label_key="records_military_defense_units",
            group="military",
        )

    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            pd.planet_id,
            SUM(pd.amount) AS value,
            p.name AS planet_name,
            p.galaxy,
            p.system,
            p.position,
            p.player_id,
            pl.name AS player_name
        FROM planet_defense pd
        INNER JOIN planets p ON p.id = pd.planet_id
        INNER JOIN players pl ON pl.id = p.player_id
        GROUP BY pd.planet_id
        HAVING value = (
            SELECT MAX(stock_total) FROM (
                SELECT SUM(amount) AS stock_total
                FROM planet_defense
                GROUP BY planet_id
            )
        )
        ORDER BY value DESC, pd.planet_id ASC
        LIMIT 1;
        """
    )
    row = cur.fetchone()
    value = int(row["value"] or 0) if row else 0
    return _record_from_planet_row(
        key="defense_units",
        label_key="records_military_defense_units",
        group="military",
        row=row,
        value=value,
    )


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
    military_records = [_top_defense_units_record(conn)]

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
            key="military",
            label_key="records_group_military",
            records=military_records,
        ),
    ]
    return {
        "ok": True,
        "groups": groups,
        "group_count": len(groups),
    }
