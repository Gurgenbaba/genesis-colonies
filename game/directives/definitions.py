"""Directive definition catalog and DB loader (GC-911A)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional

from ..db import table_exists

DAILY_DIRECTIVE_COUNT = 3
WEEKLY_DIRECTIVE_COUNT = 1

CADENCE_DAILY = "daily"
CADENCE_WEEKLY = "weekly"
CADENCE_BOTH = "both"

CATEGORIES = frozenset({"economy", "science", "fleet", "military", "exploration"})

OBJECTIVE_COUNT = "count"
OBJECTIVE_ACCUMULATE = "accumulate"

STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_CLAIMED = "claimed"
STATUS_EXPIRED = "expired"

RARITIES = ("common", "rare", "epic", "legendary")
RARITY_ORDER = {name: idx for idx, name in enumerate(RARITIES)}

RARITY_WEIGHTS_DAILY: Dict[str, int] = {
    "common": 55,
    "rare": 30,
    "epic": 13,
    "legendary": 2,
}

RARITY_WEIGHTS_WEEKLY: Dict[str, int] = {
    "common": 15,
    "rare": 40,
    "epic": 30,
    "legendary": 15,
}

RARITY_TARGET_MULTIPLIER: Dict[str, float] = {
    "common": 0.85,
    "rare": 1.0,
    "epic": 1.2,
    "legendary": 1.45,
}

_JSON_COLS = ("filters_json",)


def directives_schema_ready(conn) -> bool:
    return table_exists(conn, "directive_definitions") and table_exists(conn, "player_directives")


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _parse_row(row: sqlite3.Row | Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    raw_filters = data.pop("filters_json", "{}")
    data["filters"] = _json_loads(raw_filters, {})
    data["key"] = str(data.get("key") or "").strip()
    data["category"] = str(data.get("category") or "").strip().lower()
    data["cadence"] = str(data.get("cadence") or CADENCE_DAILY).strip().lower()
    data["objective_kind"] = str(data.get("objective_kind") or OBJECTIVE_COUNT).strip().lower()
    data["scale_profile"] = str(data.get("scale_profile") or "count_light").strip()
    data["base_target"] = int(data.get("base_target") or 1)
    # weight 0 = disabled from roll pool (keep definition for progress/claim)
    raw_weight = data.get("weight")
    if raw_weight is None:
        data["weight"] = 1
    else:
        data["weight"] = max(0, int(raw_weight))
    data["min_rarity"] = str(data.get("min_rarity") or "common").strip().lower()
    data["max_rarity"] = str(data.get("max_rarity") or "legendary").strip().lower()
    data["title_key"] = str(data.get("title_key") or "")
    data["description_key"] = str(data.get("description_key") or "")
    data["sort_order"] = int(data.get("sort_order") or 0)
    return data


def _clamp_rarity(value: str, *, min_rarity: str, max_rarity: str) -> str:
    rarity = str(value or "common").strip().lower()
    if rarity not in RARITY_ORDER:
        rarity = "common"
    lo = RARITY_ORDER.get(min_rarity, 0)
    hi = RARITY_ORDER.get(max_rarity, len(RARITIES) - 1)
    idx = max(lo, min(hi, RARITY_ORDER[rarity]))
    return RARITIES[idx]


def list_definitions(conn, *, cadence: str) -> List[Dict[str, Any]]:
    """All definitions eligible for the given cadence (daily or weekly)."""
    if not directives_schema_ready(conn):
        return []

    want = str(cadence or CADENCE_DAILY).strip().lower()
    rows = conn.execute(
        """
        SELECT key, category, cadence, objective_kind, base_target, scale_profile,
               weight, min_rarity, max_rarity, filters_json, title_key, description_key, sort_order
        FROM directive_definitions
        ORDER BY sort_order ASC, key ASC;
        """
    ).fetchall()

    out: List[Dict[str, Any]] = []
    for row in rows:
        parsed = _parse_row(row)
        raw_cadence = parsed["cadence"]
        if raw_cadence != want and raw_cadence != CADENCE_BOTH:
            continue
        if parsed["category"] not in CATEGORIES:
            continue
        if int(parsed.get("weight") or 0) <= 0:
            continue
        out.append(parsed)
    return out


def list_definitions_for_cadence(cadence: str, *, conn) -> List[Dict[str, Any]]:
    return list_definitions(conn, cadence=cadence)


def definition_is_rollable(definition: Mapping[str, Any] | None) -> bool:
    """True when a definition may appear in new daily/weekly rolls."""
    if not definition:
        return False
    return int(definition.get("weight") or 0) > 0


def get_definition(key: str, *, conn) -> Optional[Dict[str, Any]]:
    if not directives_schema_ready(conn):
        return None
    row = conn.execute(
        """
        SELECT key, category, cadence, objective_kind, base_target, scale_profile,
               weight, min_rarity, max_rarity, filters_json, title_key, description_key, sort_order
        FROM directive_definitions
        WHERE key = ?
        LIMIT 1;
        """,
        (str(key or "").strip(),),
    ).fetchone()
    if not row:
        return None
    return _parse_row(row)


def rarity_for_roll(
    rolled: str,
    *,
    min_rarity: str,
    max_rarity: str,
    cadence: str,
) -> str:
    """Clamp rolled rarity to definition bounds; weekly enforces at least rare when min is common."""
    rarity = _clamp_rarity(rolled, min_rarity=min_rarity, max_rarity=max_rarity)
    if str(cadence).strip().lower() == CADENCE_WEEKLY:
        min_r = str(min_rarity or "common").strip().lower()
        if min_r == "common" and RARITY_ORDER[rarity] < RARITY_ORDER["rare"]:
            rarity = "rare"
    return rarity


def effective_base_target(definition: Mapping[str, Any], rarity: str) -> int:
    base = max(1, int(definition.get("base_target") or 1))
    mult = float(RARITY_TARGET_MULTIPLIER.get(str(rarity).strip().lower(), 1.0))
    kind = str(definition.get("objective_kind") or OBJECTIVE_COUNT).strip().lower()
    scaled = base * mult
    if kind == OBJECTIVE_COUNT:
        return max(1, int(round(scaled)))
    return max(1, int(scaled))
