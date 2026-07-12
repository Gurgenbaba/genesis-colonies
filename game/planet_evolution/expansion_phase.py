"""Derived expansion lifecycle phase (GC-920) — read-only resolver.

See docs/EXPANSION_PROTOCOL.md and CORE_ARCHITECTURE.md Regel 18.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Mapping, Optional

from ..db import table_exists
from ..fleet_defs import ACTIVE_FLEET_STATUSES
from ..models import get_planet_buildings
from .expansion_gates import EXPANSION_SITES
from .repository import get_planet_row
from .world_colonization import (
    CLAIM_STATUS_CLAIMED,
    CLAIM_STATUS_RESERVED,
    WORLD_KEY_PREFIX,
    get_claim_by_world_key,
    world_colonization_schema_ready,
)

EXPANSION_PHASE_SITE = "expansion_site"
EXPANSION_PHASE_CLAIM = "claim"
EXPANSION_PHASE_EN_ROUTE = "en_route"
EXPANSION_PHASE_OUTPOST = "frontier_outpost"
EXPANSION_PHASE_COLONY = "colony"
EXPANSION_PHASE_STRATEGIC = "strategic_world"
EXPANSION_PHASE_UNKNOWN = "unknown"

PHASE_LABEL_KEYS: Dict[str, str] = {
    EXPANSION_PHASE_SITE: "expansion_phase_expansion_site",
    EXPANSION_PHASE_CLAIM: "expansion_phase_claim",
    EXPANSION_PHASE_EN_ROUTE: "expansion_phase_en_route",
    EXPANSION_PHASE_OUTPOST: "expansion_phase_frontier_outpost",
    EXPANSION_PHASE_COLONY: "expansion_phase_colony",
    EXPANSION_PHASE_STRATEGIC: "expansion_phase_strategic_world",
    EXPANSION_PHASE_UNKNOWN: "expansion_phase_unknown",
}

_MILESTONE_BUILDING_LABEL_KEYS: Dict[str, str] = {
    "command_center": "building_command_center",
    "solar_plant": "building_solar_plant",
    "radar_array": "building_radar_array",
}


def _milestone_building_fields(spec: Mapping[str, Any]) -> Dict[str, Any]:
    building = str(spec.get("building") or "").strip()
    if not building:
        return {}
    min_level = max(1, int(spec.get("min_level") or 1))
    return {
        "building_key": building,
        "building_label_key": _MILESTONE_BUILDING_LABEL_KEYS.get(building) or f"building_{building}",
        "min_level": min_level,
    }


ESTABLISHMENT_MILESTONE_DEFS: tuple[Dict[str, Any], ...] = (
    {
        "key": "habitat",
        "label_key": "expansion_milestone_habitat",
        "building": "command_center",
        "min_level": 1,
        "required": True,
    },
    {
        "key": "energy",
        "label_key": "expansion_milestone_energy",
        "building": "solar_plant",
        "min_level": 1,
        "required": True,
    },
    {
        "key": "communication",
        "label_key": "expansion_milestone_communication",
        "building": "radar_array",
        "min_level": 1,
        "required": True,
    },
    {
        "key": "first_population",
        "label_key": "expansion_milestone_first_population",
        "required": False,
        "placeholder": True,
    },
)


def _phase_label_key(phase: str) -> str:
    return str(PHASE_LABEL_KEYS.get(str(phase or "").strip(), PHASE_LABEL_KEYS[EXPANSION_PHASE_UNKNOWN]))


def _fleet_schema_ready(conn: sqlite3.Connection) -> bool:
    return table_exists(conn, "fleet_movements")


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def is_expansion_site_key(key: str | None) -> bool:
    return str(key or "").strip() in EXPANSION_SITES


def get_establishment_milestones(
    planet_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """Establishment checklist — building-level proxies until GC-923 queue exists."""
    pid = int(planet_id)
    if pid <= 0:
        return []

    try:
        buildings = get_planet_buildings(pid, conn=conn) or {}
    except Exception:
        buildings = {}

    out: List[Dict[str, Any]] = []
    for spec in ESTABLISHMENT_MILESTONE_DEFS:
        key = str(spec.get("key") or "")
        required = bool(spec.get("required", True))
        if spec.get("placeholder"):
            met = False
        else:
            building = str(spec.get("building") or "")
            min_level = max(1, int(spec.get("min_level") or 1))
            met = int(buildings.get(building) or 0) >= min_level
        row: Dict[str, Any] = {
            "key": key,
            "label_key": str(spec.get("label_key") or key),
            "met": bool(met),
            "required": required,
        }
        row.update(_milestone_building_fields(spec))
        out.append(row)
    return out


def is_establishment_complete(
    planet_id: int,
    *,
    conn: sqlite3.Connection,
) -> bool:
    milestones = get_establishment_milestones(planet_id, conn=conn)
    required = [m for m in milestones if m.get("required", True)]
    return bool(required) and all(bool(m.get("met")) for m in required)


def _specialization_picked(planet: Mapping[str, Any] | None) -> bool:
    if not planet:
        return False
    spec_key = str(planet.get("specialization_key") or "").strip()
    return bool(spec_key)


def _get_planet_by_world_key(
    world_key: str,
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    wk = str(world_key or "").strip()
    if not wk or int(player_id) <= 0:
        return None
    if not table_exists(conn, "planets"):
        return None
    cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(planets);").fetchall()}
    if "world_key" not in cols:
        return None
    row = conn.execute(
        """
        SELECT * FROM planets
        WHERE world_key = ? AND player_id = ?
        LIMIT 1;
        """,
        (wk, int(player_id)),
    ).fetchone()
    return dict(row) if row else None


def _get_player_claim(
    world_key: str,
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    if not world_colonization_schema_ready(conn=conn):
        return None
    claim = get_claim_by_world_key(world_key, conn=conn)
    if not claim:
        return None
    if int(claim.get("player_id") or 0) != int(player_id):
        return None
    return claim


def _has_active_seed_ark_colonize(
    world_key: str,
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> bool:
    wk = str(world_key or "").strip()
    if not wk or not _fleet_schema_ready(conn):
        return False
    placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)
    rows = conn.execute(
        f"""
        SELECT ships_json, resources_json
        FROM fleet_movements
        WHERE player_id = ?
          AND mission_type = 'colonize'
          AND status IN ({placeholders});
        """,
        (int(player_id), *ACTIVE_FLEET_STATUSES),
    ).fetchall()
    for row in rows:
        ships = _json_loads(row["ships_json"], {})
        resources = _json_loads(row["resources_json"], {})
        if str(resources.get("world_key") or "").strip() != wk:
            continue
        if int(ships.get("seed_ark") or 0) >= 1:
            return True
    return False


def _resolve_planet_phase(
    planet: Mapping[str, Any],
    *,
    conn: sqlite3.Connection,
) -> str:
    pid = int(planet.get("id") or 0)
    if pid <= 0:
        return EXPANSION_PHASE_UNKNOWN
    if _specialization_picked(planet):
        return EXPANSION_PHASE_STRATEGIC
    if is_establishment_complete(pid, conn=conn):
        return EXPANSION_PHASE_COLONY
    return EXPANSION_PHASE_OUTPOST


def _empty_source() -> Dict[str, bool]:
    return {
        "has_claim": False,
        "has_active_seed_ark": False,
        "has_planet": False,
        "establishment_complete": False,
        "specialization_picked": False,
    }


def resolve_expansion_phase(
    *,
    player_id: int,
    world_key: str | None = None,
    planet_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, Any]:
    """Derive expansion lifecycle phase — read-only, no mutations."""
    from ..models import db

    own = conn is None
    if own:
        conn = db()
    assert conn is not None

    try:
        pid = int(planet_id) if planet_id is not None else 0
        wk = str(world_key or "").strip() or None
        uid = int(player_id)
        source = _empty_source()
        requirements: List[Dict[str, Any]] = []

        planet: Optional[Dict[str, Any]] = None
        if pid > 0:
            planet = get_planet_row(pid, conn=conn)
            if planet and int(planet.get("player_id") or 0) != uid:
                planet = None
        if planet is None and wk:
            planet = _get_planet_by_world_key(wk, uid, conn=conn)
            if planet:
                pid = int(planet["id"])

        if planet and not wk:
            wk = str(planet.get("world_key") or "").strip() or None

        if planet:
            source["has_planet"] = True
            source["establishment_complete"] = is_establishment_complete(int(planet["id"]), conn=conn)
            source["specialization_picked"] = _specialization_picked(planet)
            requirements = get_establishment_milestones(int(planet["id"]), conn=conn)
            phase = _resolve_planet_phase(planet, conn=conn)
            if bool(planet.get("is_homeworld")) and phase == EXPANSION_PHASE_OUTPOST:
                phase = EXPANSION_PHASE_COLONY
            return _build_phase_result(phase, requirements=requirements, source=source)

        if wk:
            if _has_active_seed_ark_colonize(wk, uid, conn=conn):
                source["has_active_seed_ark"] = True
                return _build_phase_result(EXPANSION_PHASE_EN_ROUTE, requirements=[], source=source)

            claim = _get_player_claim(wk, uid, conn=conn)
            if claim:
                source["has_claim"] = True
                status = str(claim.get("status") or "").strip().lower()
                if status in (CLAIM_STATUS_RESERVED, CLAIM_STATUS_CLAIMED) and not claim.get("planet_id"):
                    return _build_phase_result(EXPANSION_PHASE_CLAIM, requirements=[], source=source)

            if is_expansion_site_key(wk) or wk.startswith(f"{WORLD_KEY_PREFIX}:"):
                return _build_phase_result(EXPANSION_PHASE_SITE, requirements=[], source=source)

        return _build_phase_result(EXPANSION_PHASE_UNKNOWN, requirements=[], source=source)
    finally:
        if own and conn is not None:
            conn.close()


def _build_phase_result(
    phase: str,
    *,
    requirements: List[Dict[str, Any]],
    source: Mapping[str, bool],
) -> Dict[str, Any]:
    phase_norm = str(phase or EXPANSION_PHASE_UNKNOWN)
    return {
        "phase": phase_norm,
        "phase_label_key": _phase_label_key(phase_norm),
        "is_colony": phase_norm == EXPANSION_PHASE_COLONY,
        "is_outpost": phase_norm == EXPANSION_PHASE_OUTPOST,
        "is_strategic_world": phase_norm == EXPANSION_PHASE_STRATEGIC,
        "requirements": list(requirements),
        "source": dict(source),
    }


def compact_expansion_phase_payload(resolved: Mapping[str, Any]) -> Dict[str, Any]:
    """Minimal inspector slice — backend only."""
    return {
        "phase": str(resolved.get("phase") or EXPANSION_PHASE_UNKNOWN),
        "phase_label_key": str(
            resolved.get("phase_label_key") or _phase_label_key(str(resolved.get("phase") or ""))
        ),
        "requirements": list(resolved.get("requirements") or []),
        "is_colony": bool(resolved.get("is_colony")),
        "is_outpost": bool(resolved.get("is_outpost")),
        "is_strategic_world": bool(resolved.get("is_strategic_world")),
    }

