"""Own fleet movement routes for the shared command map (GC-584)."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..fleet_defs import ACTIVE_FLEET_STATUSES, EXPEDITION_POSITION
from ..fleet_calc import enrich_movement_timing
from .world_colonization import WorldKeyError, parse_world_key
from .world_map import polar_to_world

_ROUTE_STATUSES = frozenset({"outbound", "returning", "holding"})


def _json_loads(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _node_world_xy(node: Mapping[str, Any]) -> Optional[Tuple[float, float]]:
    wx = node.get("world_x")
    wy = node.get("world_y")
    if wx is None or wy is None:
        return None
    return float(wx), float(wy)


def _build_node_indexes(
    nodes: List[Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, Any]], Optional[Tuple[float, float]]]:
    by_planet: Dict[int, Dict[str, Any]] = {}
    by_world_key: Dict[str, Dict[str, Any]] = {}
    hub_xy: Optional[Tuple[float, float]] = None

    for node in nodes:
        planet_id = node.get("planet_id")
        if planet_id is not None:
            by_planet[int(planet_id)] = node
        world_key = str(node.get("world_key") or "").strip()
        if world_key:
            by_world_key[world_key] = node
        if (
            str(node.get("empire_role_key") or "") == "homeworld"
            and str(node.get("cluster_kind") or "") in ("own_cluster", "")
            and str(node.get("node_kind") or "") == "colony"
        ):
            xy = _node_world_xy(node)
            if xy:
                hub_xy = xy

    return by_planet, by_world_key, hub_xy


def _resolve_world_key_target(
    world_key: str,
    *,
    by_world_key: Mapping[str, Mapping[str, Any]],
) -> Optional[Tuple[float, float]]:
    wk = str(world_key or "").strip()
    if not wk:
        return None
    node = by_world_key.get(wk)
    if node:
        return _node_world_xy(node)
    try:
        parsed = parse_world_key(wk)
        return float(parsed["world_x"]), float(parsed["world_y"])
    except WorldKeyError:
        return None


def _resolve_coords_target(
    galaxy: int,
    system: int,
    position: int,
    *,
    by_planet: Mapping[int, Mapping[str, Any]],
    hub_xy: Optional[Tuple[float, float]],
    conn: sqlite3.Connection,
) -> Optional[Tuple[float, float]]:
    row = conn.execute(
        """
        SELECT id, world_x, world_y
        FROM planets
        WHERE galaxy = ? AND system = ? AND position = ?
        LIMIT 1;
        """,
        (int(galaxy), int(system), int(position)),
    ).fetchone()
    if row:
        planet_id = int(row["id"])
        node = by_planet.get(planet_id)
        if node:
            xy = _node_world_xy(node)
            if xy:
                return xy
        if row["world_x"] is not None and row["world_y"] is not None:
            return float(row["world_x"]), float(row["world_y"])

    if hub_xy and int(position) == EXPEDITION_POSITION:
        return polar_to_world(hub_xy[0], hub_xy[1], 0.0, 520.0)

    if hub_xy:
        bearing = float((int(galaxy) * 41 + int(system) * 17 + int(position) * 9) % 360)
        radius = 180.0 + float((int(galaxy) + int(system) + int(position)) % 320)
        return polar_to_world(hub_xy[0], hub_xy[1], bearing, radius)

    return None


def _resolve_movement_endpoints(
    movement: Mapping[str, Any],
    *,
    by_planet: Mapping[int, Mapping[str, Any]],
    by_world_key: Mapping[str, Mapping[str, Any]],
    hub_xy: Optional[Tuple[float, float]],
    conn: sqlite3.Connection,
) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    resources = _json_loads(movement.get("resources_json"), {}) or movement.get("resources") or {}
    world_key = str(resources.get("world_key") or "").strip()

    origin_xy = None
    origin_planet_id = movement.get("origin_planet_id")
    if origin_planet_id is not None:
        origin_node = by_planet.get(int(origin_planet_id))
        if origin_node:
            origin_xy = _node_world_xy(origin_node)

    target_xy = None
    if world_key:
        target_xy = _resolve_world_key_target(world_key, by_world_key=by_world_key)

    if target_xy is None:
        target_planet_id = movement.get("target_planet_id")
        if target_planet_id is not None:
            target_node = by_planet.get(int(target_planet_id))
            if target_node:
                target_xy = _node_world_xy(target_node)

    if target_xy is None:
        target_xy = _resolve_coords_target(
            int(movement.get("target_galaxy") or 0),
            int(movement.get("target_system") or 0),
            int(movement.get("target_position") or 0),
            by_planet=by_planet,
            hub_xy=hub_xy,
            conn=conn,
        )

    return origin_xy, target_xy


def _route_progress_pct(movement: Mapping[str, Any], *, now: float) -> float:
    status = str(movement.get("status") or "").strip().lower()
    if status == "holding":
        return 100.0

    if status == "outbound":
        departure = max(0, int(movement.get("departure_at") or 0))
        arrival = max(0, int(movement.get("arrival_at") or 0))
        if arrival <= departure:
            return 0.0
        return min(100.0, max(0.0, (now - departure) / (arrival - departure) * 100.0))

    if status == "returning":
        started = max(0, int(movement.get("return_started_at") or 0))
        ret_at = max(0, int(movement.get("return_at") or 0))
        if ret_at <= started:
            return 0.0
        return min(100.0, max(0.0, (now - started) / (ret_at - started) * 100.0))

    return 0.0


def _route_phase(movement: Mapping[str, Any]) -> str:
    status = str(movement.get("status") or "").strip().lower()
    if status in _ROUTE_STATUSES:
        return status
    return "outbound"


def build_fleet_routes_payload(
    player_id: int,
    nodes: List[Dict[str, Any]],
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Active own fleet routes with world-map endpoints (GC-584)."""
    from ..db import table_exists

    if not table_exists(conn, "fleet_movements"):
        return []

    ts = float(now if now is not None else time.time())
    by_planet, by_world_key, hub_xy = _build_node_indexes(nodes)
    placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)
    rows = conn.execute(
        f"""
        SELECT *
        FROM fleet_movements
        WHERE player_id = ?
          AND status IN ({placeholders})
        ORDER BY id ASC;
        """,
        (int(player_id), *sorted(ACTIVE_FLEET_STATUSES)),
    ).fetchall()

    routes: List[Dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        if int(data.get("player_id") or 0) != int(player_id):
            continue
        status = str(data.get("status") or "").strip().lower()
        if status not in _ROUTE_STATUSES:
            continue

        enriched = enrich_movement_timing(
            {
                "id": int(data["id"]),
                "player_id": int(data["player_id"]),
                "origin_planet_id": int(data["origin_planet_id"]),
                "target_planet_id": data.get("target_planet_id"),
                "target_galaxy": int(data.get("target_galaxy") or 0),
                "target_system": int(data.get("target_system") or 0),
                "target_position": int(data.get("target_position") or 0),
                "mission_type": str(data.get("mission_type") or ""),
                "status": status,
                "departure_at": int(data.get("departure_at") or 0),
                "arrival_at": int(data.get("arrival_at") or 0),
                "return_at": int(data.get("return_at") or 0),
                "holding_until": int(data.get("holding_until") or 0),
                "flight_seconds": int(data.get("flight_seconds") or 0),
                "resources_json": data.get("resources_json"),
            },
            now=ts,
        )

        origin_xy, target_xy = _resolve_movement_endpoints(
            enriched,
            by_planet=by_planet,
            by_world_key=by_world_key,
            hub_xy=hub_xy,
            conn=conn,
        )
        if not origin_xy or not target_xy:
            continue

        phase = _route_phase(enriched)
        if phase == "returning":
            from_xy, to_xy = target_xy, origin_xy
        else:
            from_xy, to_xy = origin_xy, target_xy

        progress_pct = round(_route_progress_pct(enriched, now=ts), 2)
        fx, fy = from_xy
        tx, ty = to_xy
        t = max(0.0, min(1.0, progress_pct / 100.0))
        marker_x = round(fx + (tx - fx) * t, 2)
        marker_y = round(fy + (ty - fy) * t, 2)
        mission = str(enriched.get("mission_type") or "transport").strip().lower()
        resources = _json_loads(enriched.get("resources_json"), {}) or {}
        world_key = str(resources.get("world_key") or "").strip()

        routes.append(
            {
                "fleet_id": int(enriched["id"]),
                "mission": mission,
                "phase": phase,
                "from_world_x": round(fx, 2),
                "from_world_y": round(fy, 2),
                "to_world_x": round(tx, 2),
                "to_world_y": round(ty, 2),
                "marker_world_x": marker_x,
                "marker_world_y": marker_y,
                "progress_pct": progress_pct,
                "eta_at": float(enriched.get("countdown_at") or 0),
                "remaining_seconds": max(0, int(enriched.get("remaining_seconds") or 0)),
                "world_key": world_key or None,
            }
        )

    return routes
