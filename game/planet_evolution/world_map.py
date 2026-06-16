"""Shared world map — all empires on one canvas (GC-571 / GC-571B). Display only."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import sqlite3

from ..galaxy import GalaxyCoordinateError, get_planet_coordinates
from .empire_identity import build_colonies_identity, role_payload
from .imperium_regions import MAP_HUB_CX_PCT, MAP_HUB_CY_PCT

# Fixed virtual world — viewport pans/zooms through this space (GC-571B).
WORLD_WIDTH = 4000.0
WORLD_HEIGHT = 4000.0
MIN_CLUSTER_DISTANCE = 420.0
CLUSTER_LOCAL_RADIUS = 118.0
_FOREIGN_CLUSTER_RADIUS = 88.0
VIEWER_HOME_X = 2000.0
VIEWER_HOME_Y = 2000.0
_GOLDEN_ANGLE = 2.399963229728653
_WORLD_EDGE_PAD = 140.0
_FOREIGN_MAX_SATELLITES = 6
_FREE_FIELD_GRID_STEP = 480
_FREE_FIELD_MIN_EMPIRE_DIST = 260.0
_FREE_FIELD_MIN_FIELD_DIST = 180.0
_FREE_FIELD_MAX = 24


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(float(bx) - float(ax), float(by) - float(ay))


def compute_empire_seed(galaxy: int, system: int, player_id: int) -> Tuple[float, float]:
    """Deterministic seed slot before collision resolution."""
    g = max(1, int(galaxy))
    s = max(1, int(system))
    pid = int(player_id)
    span_x = WORLD_WIDTH - 2 * _WORLD_EDGE_PAD
    span_y = WORLD_HEIGHT - 2 * _WORLD_EDGE_PAD
    seed_x = _WORLD_EDGE_PAD + (g * 317 + s * 43 + pid * 19) % int(span_x)
    seed_y = _WORLD_EDGE_PAD + (g * 73 + s * 211 + pid * 29) % int(span_y)
    return float(seed_x), float(seed_y)


def compute_empire_world_center(galaxy: int, system: int, player_id: int) -> Tuple[float, float]:
    """Legacy helper — returns resolved center for a lone empire (tests / callers)."""
    return compute_empire_seed(galaxy, system, player_id)


def resolve_empire_center(
    seed_x: float,
    seed_y: float,
    placed: Sequence[Tuple[float, float]],
) -> Tuple[float, float]:
    """Spiral fallback when seed collides with an existing cluster."""
    x = float(seed_x)
    y = float(seed_y)
    if not placed:
        return x, y

    step = 0
    while any(_dist(x, y, px, py) < MIN_CLUSTER_DISTANCE for px, py in placed):
        step += 1
        angle = step * _GOLDEN_ANGLE
        radius = MIN_CLUSTER_DISTANCE * (0.55 + step * 0.38)
        x = seed_x + math.cos(angle) * radius
        y = seed_y + math.sin(angle) * radius
        x = max(_WORLD_EDGE_PAD, min(WORLD_WIDTH - _WORLD_EDGE_PAD, x))
        y = max(_WORLD_EDGE_PAD, min(WORLD_HEIGHT - _WORLD_EDGE_PAD, y))
        if step > 64:
            break
    return round(x, 2), round(y, 2)


def build_empire_center_map(
    homeworlds: Sequence[Mapping[str, Any]],
    viewer_player_id: int,
) -> Dict[int, Tuple[float, float]]:
    viewer_id = int(viewer_player_id)
    centers: Dict[int, Tuple[float, float]] = {}
    placed: List[Tuple[float, float]] = []

    centers[viewer_id] = (VIEWER_HOME_X, VIEWER_HOME_Y)
    placed.append((VIEWER_HOME_X, VIEWER_HOME_Y))

    for hw in sorted(homeworlds, key=lambda row: int(row["player_id"])):
        owner_id = int(hw["player_id"])
        if owner_id == viewer_id:
            continue
        seed_x, seed_y = compute_empire_seed(
            int(hw.get("galaxy") or 1),
            int(hw.get("system") or 1),
            owner_id,
        )
        cx, cy = resolve_empire_center(seed_x, seed_y, placed)
        centers[owner_id] = (cx, cy)
        placed.append((cx, cy))

    return centers


def polar_to_world(
    center_wx: float,
    center_wy: float,
    bearing_deg: float,
    radius_world: float,
) -> Tuple[float, float]:
    """Place a node on the shared canvas by bearing (north=0°) and world-unit radius."""
    if radius_world <= 0:
        return center_wx, center_wy
    rad = math.radians(bearing_deg)
    return (
        center_wx + radius_world * math.sin(rad),
        center_wy - radius_world * math.cos(rad),
    )


def _resolve_own_node_world(
    node: Dict[str, Any],
    center_wx: float,
    center_wy: float,
) -> Tuple[float, float]:
    if node.get("world_map_bound"):
        return float(node.get("_world_x") or node.get("world_x") or center_wx), float(
            node.get("_world_y") or node.get("world_y") or center_wy
        )
    if node.get("layout_radius_world") is not None:
        radius_world = float(node.get("layout_radius_world") or 0)
        if (
            radius_world <= 0
            or node.get("layout_slot") == "hub"
            or str(node.get("empire_role_key") or "") == "homeworld"
        ):
            return center_wx, center_wy
        bearing = float(node.get("layout_bearing_deg") or 0)
        return polar_to_world(center_wx, center_wy, bearing, radius_world)
    return local_pct_to_world(
        float(node.get("layout_x_pct") or MAP_HUB_CX_PCT),
        float(node.get("layout_y_pct") or MAP_HUB_CY_PCT),
        center_wx,
        center_wy,
    )


def _sync_edge_endpoints_from_nodes(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> None:
    by_key = {str(n.get("node_key") or ""): n for n in nodes if n.get("node_key")}
    for edge in edges:
        src = by_key.get(str(edge.get("source_key") or ""))
        tgt = by_key.get(str(edge.get("target_key") or ""))
        if src and src.get("world_x") is not None and src.get("world_y") is not None:
            edge["source_world_x"] = round(float(src["world_x"]), 2)
            edge["source_world_y"] = round(float(src["world_y"]), 2)
            edge["source_x_pct"], edge["source_y_pct"] = world_to_layout_pct(
                edge["source_world_x"], edge["source_world_y"]
            )
        if tgt and tgt.get("world_x") is not None and tgt.get("world_y") is not None:
            edge["target_world_x"] = round(float(tgt["world_x"]), 2)
            edge["target_world_y"] = round(float(tgt["world_y"]), 2)
            edge["target_x_pct"], edge["target_y_pct"] = world_to_layout_pct(
                edge["target_world_x"], edge["target_world_y"]
            )


def local_pct_to_world(
    local_x_pct: float,
    local_y_pct: float,
    center_wx: float,
    center_wy: float,
    *,
    cluster_radius: float = CLUSTER_LOCAL_RADIUS,
) -> Tuple[float, float]:
    lx = (float(local_x_pct) - MAP_HUB_CX_PCT) * (cluster_radius / MAP_HUB_CX_PCT)
    ly = (float(local_y_pct) - MAP_HUB_CY_PCT) * (cluster_radius / MAP_HUB_CY_PCT)
    return center_wx + lx, center_wy + ly


def world_to_layout_pct(world_x: float, world_y: float) -> Tuple[float, float]:
    x_pct = float(world_x) / WORLD_WIDTH * 100.0
    y_pct = float(world_y) / WORLD_HEIGHT * 100.0
    return round(x_pct, 3), round(y_pct, 3)


def apply_world_coords(node: Dict[str, Any]) -> None:
    wx = float(node.pop("_world_x"))
    wy = float(node.pop("_world_y"))
    node["world_x"] = round(wx, 2)
    node["world_y"] = round(wy, 2)
    node["layout_x_pct"], node["layout_y_pct"] = world_to_layout_pct(wx, wy)


def apply_edge_world_coords(edge: Dict[str, Any]) -> None:
    swx = edge.pop("_source_world_x", None)
    swy = edge.pop("_source_world_y", None)
    twx = edge.pop("_target_world_x", None)
    twy = edge.pop("_target_world_y", None)
    if swx is not None and swy is not None:
        edge["source_world_x"] = round(float(swx), 2)
        edge["source_world_y"] = round(float(swy), 2)
        edge["source_x_pct"], edge["source_y_pct"] = world_to_layout_pct(float(swx), float(swy))
    if twx is not None and twy is not None:
        edge["target_world_x"] = round(float(twx), 2)
        edge["target_world_y"] = round(float(twy), 2)
        edge["target_x_pct"], edge["target_y_pct"] = world_to_layout_pct(float(twx), float(twy))


def list_occupied_homeworlds(*, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            p.id AS planet_id,
            p.player_id,
            p.name,
            p.galaxy,
            p.system,
            p.position,
            u.username AS owner_username
        FROM planets p
        INNER JOIN users u ON u.id = p.player_id
        WHERE p.is_homeworld = 1
        ORDER BY p.player_id ASC;
        """
    )
    return [dict(row) for row in cur.fetchall()]


def _homeworld_coords(row: Mapping[str, Any]) -> str:
    try:
        return get_planet_coordinates(dict(row))["formatted"]
    except (GalaxyCoordinateError, TypeError, KeyError):
        return ""


def _layout_foreign_satellites(
    colonies: Sequence[Mapping[str, Any]],
    *,
    center_wx: float,
    center_wy: float,
    owner_player_id: int,
    owner_username: str,
    homeworld_planet_id: int,
) -> List[Dict[str, Any]]:
    from .command_map import _layout_colony_nodes

    satellites = [
        dict(row)
        for row in colonies
        if not bool(row.get("is_homeworld"))
        and int(row.get("planet_id") or 0) != int(homeworld_planet_id)
        and not (
            row.get("world_key")
            and row.get("world_x") is not None
            and row.get("world_y") is not None
        )
    ]
    if not satellites:
        return []

    trimmed = satellites[:_FOREIGN_MAX_SATELLITES]
    local_nodes = _layout_colony_nodes(
        trimmed,
        is_own=False,
        include_actions=False,
        cluster_kind="foreign_cluster",
    )
    for node in local_nodes:
        node["node_kind"] = "foreign_colony"
        node["owner_player_id"] = int(owner_player_id)
        node["owner_username"] = str(owner_username or "")
        node.pop("actions", None)
        wx, wy = local_pct_to_world(
            float(node["layout_x_pct"]),
            float(node["layout_y_pct"]),
            center_wx,
            center_wy,
            cluster_radius=_FOREIGN_CLUSTER_RADIUS,
        )
        node["_world_x"] = wx
        node["_world_y"] = wy
    return local_nodes


def _build_foreign_empire_hub(
    homeworld: Mapping[str, Any],
    *,
    center_wx: float,
    center_wy: float,
    colony_count: int,
) -> Dict[str, Any]:
    owner_id = int(homeworld["player_id"])
    planet_id = int(homeworld["planet_id"])
    username = str(homeworld.get("owner_username") or "")
    coords = _homeworld_coords(homeworld)
    identity = role_payload("homeworld")

    node: Dict[str, Any] = {
        "node_kind": "foreign_empire",
        "cluster_kind": "foreign_cluster",
        "is_own": False,
        "owner_player_id": owner_id,
        "owner_username": username,
        "planet_id": planet_id,
        "name": str(homeworld.get("name") or username or "Empire"),
        "coordinates_formatted": coords,
        "colony_count": max(0, int(colony_count)),
        "layout_slot": "hub",
        "layout_index": 0,
        "region_key": "genesis_core",
        "layout_x_pct": MAP_HUB_CX_PCT,
        "layout_y_pct": MAP_HUB_CY_PCT,
        "node_key": f"foreign:{owner_id}",
        "is_homeworld": True,
        "is_active": False,
        **identity,
    }
    node["_world_x"] = center_wx
    node["_world_y"] = center_wy
    return node


def build_foreign_cluster_nodes(
    homeworld: Mapping[str, Any],
    *,
    center_wx: float,
    center_wy: float,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    owner_id = int(homeworld["player_id"])
    colonies = build_colonies_identity(owner_id, conn=conn)
    colony_count = max(0, len(colonies) - 1)

    hub = _build_foreign_empire_hub(
        homeworld,
        center_wx=center_wx,
        center_wy=center_wy,
        colony_count=colony_count,
    )
    satellites = _layout_foreign_satellites(
        colonies,
        center_wx=center_wx,
        center_wy=center_wy,
        owner_player_id=owner_id,
        owner_username=str(homeworld.get("owner_username") or ""),
        homeworld_planet_id=int(homeworld["planet_id"]),
    )
    return [hub] + satellites


def _foreign_hub_links(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hub = next((n for n in nodes if str(n.get("node_kind") or "") == "foreign_empire"), None)
    if not hub:
        return []
    hub_key = str(hub.get("node_key") or "")
    edges: List[Dict[str, Any]] = []
    for node in nodes:
        if str(node.get("node_kind") or "") != "foreign_colony":
            continue
        edges.append(
            {
                "source_key": hub_key,
                "target_key": str(node.get("node_key") or ""),
                "source_planet_id": hub.get("planet_id"),
                "target_planet_id": node.get("planet_id"),
                "edge_type": "foreign_hub_link",
                "resource_key": "",
                "_source_world_x": hub.get("_world_x"),
                "_source_world_y": hub.get("_world_y"),
                "_target_world_x": node.get("_world_x"),
                "_target_world_y": node.get("_world_y"),
            }
        )
    return edges


def generate_free_field_nodes(
    empire_centers: Mapping[int, Tuple[float, float]],
) -> List[Dict[str, Any]]:
    """Neutral strategic worlds between empire clusters — inspector only (GC-571B / GC-581)."""
    from .strategic_worlds import build_strategic_world_field

    centers = list(empire_centers.values())
    nodes: List[Dict[str, Any]] = []
    placed: List[Tuple[float, float]] = []

    for gx in range(int(_WORLD_EDGE_PAD), int(WORLD_WIDTH - _WORLD_EDGE_PAD), _FREE_FIELD_GRID_STEP):
        for gy in range(int(_WORLD_EDGE_PAD), int(WORLD_HEIGHT - _WORLD_EDGE_PAD), _FREE_FIELD_GRID_STEP):
            jitter_x = ((gx * 17 + gy * 31) % 120) - 60
            jitter_y = ((gx * 23 + gy * 13) % 120) - 60
            wx = float(gx + jitter_x)
            wy = float(gy + jitter_y)

            if any(_dist(wx, wy, cx, cy) < _FREE_FIELD_MIN_EMPIRE_DIST for cx, cy in centers):
                continue
            if any(_dist(wx, wy, px, py) < _FREE_FIELD_MIN_FIELD_DIST for px, py in placed):
                continue

            nodes.append(build_strategic_world_field(wx, wy))
            placed.append((wx, wy))
            if len(nodes) >= _FREE_FIELD_MAX:
                return nodes
    return nodes


def _offset_own_cluster(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    *,
    center_wx: float,
    center_wy: float,
) -> None:
    for node in nodes:
        node.setdefault("cluster_kind", "own_cluster")
        node["is_own"] = True
        wx, wy = _resolve_own_node_world(node, center_wx, center_wy)
        node["_world_x"] = wx
        node["_world_y"] = wy

    for edge in edges:
        edge["_source_world_x"], edge["_source_world_y"] = _resolve_own_node_world(
            {
                "layout_x_pct": edge.get("source_x_pct"),
                "layout_y_pct": edge.get("source_y_pct"),
            },
            center_wx,
            center_wy,
        )
        edge["_target_world_x"], edge["_target_world_y"] = _resolve_own_node_world(
            {
                "layout_x_pct": edge.get("target_x_pct"),
                "layout_y_pct": edge.get("target_y_pct"),
            },
            center_wx,
            center_wy,
        )


def _filter_claimed_world_fields(
    nodes: List[Dict[str, Any]],
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """Drop strategic world fields that became colonies (GC-582D)."""
    from .world_colonization import is_world_claimed, world_colonization_schema_ready

    if not world_colonization_schema_ready(conn=conn):
        return nodes
    filtered: List[Dict[str, Any]] = []
    for node in nodes:
        if str(node.get("node_kind") or "") != "world_field":
            filtered.append(node)
            continue
        world_key = str(node.get("world_key") or "").strip()
        if world_key and is_world_claimed(world_key, conn=conn):
            continue
        filtered.append(node)
    return filtered


def build_foreign_world_colony_nodes(
    viewer_player_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """Other players' map-founded colonies at strategic coordinates (GC-582D)."""
    from .strategic_worlds import STRATEGIC_WORLD_TYPE_DEFS, empire_role_key_for_planet_role
    from .world_colonization import world_colonization_schema_ready

    if not world_colonization_schema_ready(conn=conn):
        return []

    rows = conn.execute(
        """
        SELECT
            p.id AS planet_id,
            p.player_id,
            p.name,
            p.world_key,
            p.world_x,
            p.world_y,
            p.planet_role,
            p.galaxy,
            p.system,
            p.position,
            u.username AS owner_username,
            (
                SELECT COUNT(*)
                FROM planets pc
                WHERE pc.player_id = p.player_id AND pc.is_homeworld = 0
            ) AS colony_count
        FROM planets p
        INNER JOIN users u ON u.id = p.player_id
        WHERE p.player_id != ?
          AND p.world_key IS NOT NULL
          AND p.world_x IS NOT NULL
          AND p.world_y IS NOT NULL
          AND p.is_homeworld = 0
        ORDER BY p.id ASC;
        """,
        (int(viewer_player_id),),
    ).fetchall()

    nodes: List[Dict[str, Any]] = []
    for row in rows:
        planet_role = str(row["planet_role"] or "")
        empire_role = empire_role_key_for_planet_role(planet_role)
        meta = STRATEGIC_WORLD_TYPE_DEFS.get(planet_role, {})
        wx = float(row["world_x"])
        wy = float(row["world_y"])
        x_pct, y_pct = world_to_layout_pct(wx, wy)
        identity = role_payload(empire_role)
        if meta.get("role_icon"):
            identity["empire_role_icon"] = meta["role_icon"]

        coords_formatted = ""
        try:
            coords_formatted = get_planet_coordinates(dict(row))["formatted"]
        except (GalaxyCoordinateError, TypeError, KeyError):
            coords_formatted = ""

        world_key = str(row["world_key"])
        node: Dict[str, Any] = {
            **identity,
            "node_kind": "foreign_world_colony",
            "cluster_kind": "neutral",
            "is_own": False,
            "world_map_bound": True,
            "owner_player_id": int(row["player_id"]),
            "owner_username": str(row["owner_username"] or ""),
            "planet_id": int(row["planet_id"]),
            "name": str(row["name"] or ""),
            "coordinates_formatted": coords_formatted,
            "world_key": world_key,
            "planet_role": planet_role,
            "strategic_type_key": meta.get("type_key") or "",
            "colony_count": max(0, int(row["colony_count"] or 0)),
            "layout_slot": "world_colony",
            "layout_index": 0,
            "region_key": "genesis_core",
            "layout_x_pct": x_pct,
            "layout_y_pct": y_pct,
            "_world_x": wx,
            "_world_y": wy,
            "node_key": f"foreign_world:{world_key}",
            "is_active": False,
        }
        nodes.append(node)
    return nodes


def apply_shared_world_layout(
    payload: Dict[str, Any],
    viewer_player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Place own empire + foreign clusters + free fields on fixed 4000×4000 world."""
    viewer_id = int(viewer_player_id)
    homeworlds = list_occupied_homeworlds(conn=conn)
    own_hw = next((row for row in homeworlds if int(row["player_id"]) == viewer_id), None)
    if own_hw is None:
        payload["world"] = {"mode": "solo", "empire_count": len(homeworlds)}
        return payload

    empire_centers = build_empire_center_map(homeworlds, viewer_id)
    own_center_wx, own_center_wy = empire_centers[viewer_id]

    nodes: List[Dict[str, Any]] = list(payload.get("nodes") or [])
    edges: List[Dict[str, Any]] = list(payload.get("edges") or [])

    _offset_own_cluster(nodes, edges, center_wx=own_center_wx, center_wy=own_center_wy)

    for hw in homeworlds:
        owner_id = int(hw["player_id"])
        if owner_id == viewer_id:
            continue
        center_wx, center_wy = empire_centers[owner_id]
        cluster_nodes = build_foreign_cluster_nodes(
            hw,
            center_wx=center_wx,
            center_wy=center_wy,
            conn=conn,
        )
        nodes.extend(cluster_nodes)
        edges.extend(_foreign_hub_links(cluster_nodes))

    nodes.extend(generate_free_field_nodes(empire_centers))
    nodes = _filter_claimed_world_fields(nodes, conn=conn)
    nodes.extend(build_foreign_world_colony_nodes(viewer_id, conn=conn))

    from .world_expedition_activity import (
        attach_world_expedition_activity,
        build_world_expedition_activity_map,
    )

    attach_world_expedition_activity(
        nodes,
        build_world_expedition_activity_map(viewer_id, conn=conn),
    )

    from .world_progress import attach_world_location_progress, build_world_progress_map

    attach_world_location_progress(nodes, build_world_progress_map(viewer_id, conn=conn))

    for node in nodes:
        if "_world_x" in node:
            apply_world_coords(node)
    for edge in edges:
        if edge.get("_source_world_x") is not None or edge.get("_target_world_x") is not None:
            apply_edge_world_coords(edge)

    _sync_edge_endpoints_from_nodes(nodes, edges)

    hub_node = next(
        (
            n
            for n in nodes
            if str(n.get("cluster_kind") or "") == "own_cluster"
            and (str(n.get("empire_role_key") or "") == "homeworld" or n.get("layout_slot") == "hub")
        ),
        None,
    )

    payload["nodes"] = nodes
    payload["edges"] = edges
    from .influence_layer import build_influence_payload

    payload["influence"] = build_influence_payload(nodes)
    payload["world"] = {
        "mode": "shared",
        "empire_count": len(homeworlds),
        "world_width": WORLD_WIDTH,
        "world_height": WORLD_HEIGHT,
        "default_scale": 0.62,
        "viewer_center": {"world_x": round(own_center_wx, 2), "world_y": round(own_center_wy, 2)},
        "hub_world_x": round(float(hub_node["world_x"]), 2) if hub_node else round(own_center_wx, 2),
        "hub_world_y": round(float(hub_node["world_y"]), 2) if hub_node else round(own_center_wy, 2),
        "hub_layout_x_pct": float(hub_node["layout_x_pct"]) if hub_node else world_to_layout_pct(own_center_wx, own_center_wy)[0],
        "hub_layout_y_pct": float(hub_node["layout_y_pct"]) if hub_node else world_to_layout_pct(own_center_wx, own_center_wy)[1],
    }

    from .sector_grid import DEFAULT_SECTOR_SEED, SECTOR_SIZE, SECTOR_VIEWPORT_PAD

    payload["sector_grid"] = {
        "seed": DEFAULT_SECTOR_SEED,
        "sector_size": SECTOR_SIZE,
        "viewport_pad": SECTOR_VIEWPORT_PAD,
    }

    from .fleet_routes import build_fleet_routes_payload

    payload["fleet_routes"] = build_fleet_routes_payload(viewer_id, nodes, conn=conn)

    from .command_center import attach_command_centers_to_nodes

    attach_command_centers_to_nodes(nodes, viewer_id, conn=conn)
    payload["nodes"] = nodes
    return payload
