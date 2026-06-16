"""World-native fleet target model (GC-590A) — places, not coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

import sqlite3

from .fleet_defs import EXPEDITION_POSITION

WORLD_NATIVE_TARGET_TYPES = frozenset(
    {
        "planet",
        "world_colony",
        "expedition_world",
        "anomaly",
        "wreckage",
        "enemy_colony",
    }
)


@dataclass(frozen=True)
class NormalizedFleetTarget:
    target_galaxy: int
    target_system: int
    target_position: int
    world_key: Optional[str]
    target_planet_id: Optional[int]
    world_native_type: Optional[str]
    target_world_x: Optional[float]
    target_world_y: Optional[float]


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        if raw is None or raw == "":
            return int(default)
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(raw: Any) -> Optional[float]:
    try:
        if raw is None or raw == "":
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _load_planet_row(planet_id: int, *, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, player_id, name, galaxy, system, position,
               world_key, world_x, world_y, planet_role, is_homeworld
        FROM planets
        WHERE id = ?
        LIMIT 1;
        """,
        (int(planet_id),),
    ).fetchone()
    return dict(row) if row else None


def _resolve_world_key_from_coords(
    world_x: float,
    world_y: float,
    *,
    world_type: Optional[str] = None,
) -> str:
    from .planet_evolution.world_colonization import build_world_key

    return build_world_key(float(world_x), float(world_y), world_type=world_type)


def infer_world_native_target_type(
    *,
    legacy_target_type: str,
    world_key: Optional[str],
    world_type: Optional[str],
    owner_player_id: Optional[int],
    viewer_player_id: int,
    planet_id: Optional[int],
) -> str:
    from .planet_evolution.world_colonization import (
        is_colonizable_world_type,
        is_expedition_world_type,
        is_prepared_expedition_world_type,
        is_salvage_world_type,
    )

    owner_id = int(owner_player_id) if owner_player_id is not None else None
    viewer_id = int(viewer_player_id)
    wt = str(world_type or "").strip()

    if world_key and owner_id is not None:
        if owner_id == viewer_id:
            return "world_colony"
        return "enemy_colony"

    if wt:
        if is_salvage_world_type(wt):
            return "wreckage"
        if is_prepared_expedition_world_type(wt):
            return "anomaly"
        if is_expedition_world_type(wt):
            return "expedition_world"
        if is_colonizable_world_type(wt):
            return "world_colony"

    legacy = str(legacy_target_type or "").strip()
    if legacy == "strategic_world":
        if wt and is_salvage_world_type(wt):
            return "wreckage"
        if wt and is_expedition_world_type(wt):
            return "expedition_world"
        return "world_colony"
    if legacy == "expedition_slot":
        return "expedition_world"
    if legacy == "foreign_planet":
        return "enemy_colony" if world_key else "planet"
    if legacy in ("own_planet", "ally_planet"):
        return "world_colony" if world_key else "planet"
    if planet_id and world_key:
        return "world_colony"
    return "planet"


def _resolve_target_name(
    target_info: Mapping[str, Any],
    *,
    conn: sqlite3.Connection,
) -> Tuple[Optional[str], Optional[str]]:
    sw = target_info.get("strategic_world") or {}
    name_key = sw.get("name_key")
    if name_key:
        return str(name_key), None
    legacy = str(target_info.get("target_type") or "").strip()
    if legacy == "expedition_slot" and not target_info.get("world_key"):
        return "fleet_target_expedition_label", None
    planet_id = target_info.get("target_planet_id")
    if planet_id:
        row = _load_planet_row(int(planet_id), conn=conn)
        if row:
            return None, str(row.get("name") or "")
    coords = str(target_info.get("coords") or "").strip()
    if coords:
        return None, coords
    return None, None


def build_world_target_payload(
    target_info: Mapping[str, Any],
    *,
    player_id: int,
    conn: sqlite3.Connection,
    explicit_native_type: Optional[str] = None,
    legacy_coords: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """Build GC-590A world_target block for preview/send responses."""
    info = dict(target_info or {})
    world_key = str(info.get("world_key") or (info.get("strategic_world") or {}).get("world_key") or "").strip() or None
    world_x = info.get("world_x")
    world_y = info.get("world_y")
    if world_key and (world_x is None or world_y is None):
        try:
            from .planet_evolution.world_colonization import parse_world_key

            parsed = parse_world_key(world_key)
            world_x = parsed.get("world_x")
            world_y = parsed.get("world_y")
        except Exception:
            pass
    planet_role = str(info.get("planet_role") or (info.get("strategic_world") or {}).get("world_type") or "")
    native_type = str(explicit_native_type or "").strip().lower()
    if native_type not in WORLD_NATIVE_TARGET_TYPES:
        native_type = infer_world_native_target_type(
            legacy_target_type=str(info.get("target_type") or ""),
            world_key=world_key,
            world_type=planet_role or None,
            owner_player_id=info.get("target_player_id"),
            viewer_player_id=int(player_id),
            planet_id=info.get("target_planet_id"),
        )
    name_key, display_name = _resolve_target_name(info, conn=conn)
    payload: Dict[str, Any] = {
        "target_type": native_type,
        "target_world_key": world_key,
        "target_world_x": float(world_x) if world_x is not None else None,
        "target_world_y": float(world_y) if world_y is not None else None,
        "planet_role": planet_role or None,
        "target_name_key": name_key,
        "target_name": display_name,
        "legacy_target_type": str(info.get("target_type") or "") or None,
        "target_planet_id": info.get("target_planet_id"),
    }
    if legacy_coords:
        payload["legacy_coords"] = {
            "galaxy": int(legacy_coords.get("galaxy") or 0),
            "system": int(legacy_coords.get("system") or 0),
            "position": int(legacy_coords.get("position") or 0),
        }
    return payload


def attach_world_target(
    target_info: Dict[str, Any],
    *,
    player_id: int,
    conn: sqlite3.Connection,
    explicit_native_type: Optional[str] = None,
    legacy_coords: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    if not target_info:
        return target_info
    target_info["world_target"] = build_world_target_payload(
        target_info,
        player_id=int(player_id),
        conn=conn,
        explicit_native_type=explicit_native_type,
        legacy_coords=legacy_coords,
    )
    return target_info


def parse_fleet_target_request(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract world-native + legacy target fields from API payload."""
    native = str(data.get("target_type") or "").strip().lower() or None
    if native and native not in WORLD_NATIVE_TARGET_TYPES:
        native = None
    world_key = str(data.get("target_world_key") or data.get("world_key") or "").strip() or None
    planet_id_raw = data.get("target_planet_id", data.get("planet_id"))
    planet_id = _safe_int(planet_id_raw, 0) or None
    return {
        "target_type": native,
        "world_key": world_key,
        "target_world_x": _safe_float(data.get("target_world_x")),
        "target_world_y": _safe_float(data.get("target_world_y")),
        "target_planet_id": planet_id,
        "target_galaxy": _safe_int(data.get("target_galaxy"), 0) or None,
        "target_system": _safe_int(data.get("target_system"), 0) or None,
        "target_position": _safe_int(data.get("target_position"), 0) or None,
    }


def normalize_fleet_target_request(
    player_id: int,
    mission: str,
    *,
    target_type: Optional[str] = None,
    world_key: Optional[str] = None,
    target_world_x: Optional[float] = None,
    target_world_y: Optional[float] = None,
    target_planet_id: Optional[int] = None,
    target_galaxy: Optional[int] = None,
    target_system: Optional[int] = None,
    target_position: Optional[int] = None,
    origin_planet: Optional[Mapping[str, Any]] = None,
    conn: sqlite3.Connection,
) -> NormalizedFleetTarget:
    """
    Unify world-native and legacy coordinate inputs.

    Priority: target_planet_id → world_key → target_world_x/y → legacy G:S:P.
    """
    from .planet_evolution.world_colonization import WorldKeyError, parse_world_key

    mission_l = str(mission or "").strip().lower()
    native = str(target_type or "").strip().lower() or None
    wk = str(world_key or "").strip() or None
    wx = target_world_x
    wy = target_world_y
    pid = int(target_planet_id) if target_planet_id else None
    tg = target_galaxy
    ts = target_system
    tp = target_position

    if pid:
        planet = _load_planet_row(pid, conn=conn)
        if not planet:
            raise ValueError("invalid_target_planet")
        tg = int(planet["galaxy"])
        ts = int(planet["system"])
        tp = int(planet["position"])
        if planet.get("world_key"):
            wk = str(planet["world_key"])
            wx = float(planet["world_x"]) if planet.get("world_x") is not None else wx
            wy = float(planet["world_y"]) if planet.get("world_y") is not None else wy
        if not native:
            if int(planet.get("player_id") or 0) == int(player_id):
                native = "world_colony" if wk else "planet"
            else:
                native = "enemy_colony" if wk else "planet"

    if not wk and wx is not None and wy is not None:
        wk = _resolve_world_key_from_coords(wx, wy)

    if wk:
        try:
            parsed = parse_world_key(wk)
            wx = float(parsed["world_x"])
            wy = float(parsed["world_y"])
        except WorldKeyError:
            wk = None

    if tg is None or ts is None or tp is None:
        og = origin_planet or {}
        tg = int(tg if tg is not None else og.get("galaxy") or 1)
        ts = int(ts if ts is not None else og.get("system") or 1)
        tp = int(tp if tp is not None else og.get("position") or 1)

    if mission_l == "expedition" and not wk and int(tp) != EXPEDITION_POSITION:
        tp = EXPEDITION_POSITION

    if not native and wk:
        try:
            parsed = parse_world_key(wk)
            native = infer_world_native_target_type(
                legacy_target_type="strategic_world",
                world_key=wk,
                world_type=str(parsed.get("world_type") or ""),
                owner_player_id=None,
                viewer_player_id=int(player_id),
                planet_id=pid,
            )
        except WorldKeyError:
            native = None

    return NormalizedFleetTarget(
        target_galaxy=int(tg),
        target_system=int(ts),
        target_position=int(tp),
        world_key=wk,
        target_planet_id=pid,
        world_native_type=native,
        target_world_x=wx,
        target_world_y=wy,
    )
