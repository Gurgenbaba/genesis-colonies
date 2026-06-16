"""Command Map graph payload — spatial star map (GC-564B), gates, chokepoints, influence, landmarks."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import sqlite3

from .chokepoints import gate_chain_for_region, list_chokepoints_for_map
from .empire_identity import build_colonies_identity, role_payload
from .expansion_gates import build_expansion_summary, list_expansion_sites_for_player
from .imperium_regions import MAP_HUB_CX_PCT, MAP_HUB_CY_PCT, build_regions_payload
from .influence_layer import build_influence_payload
from .command_center import attach_command_centers_to_nodes
from .location_actions import build_location_actions
from .region_landmarks import list_landmarks_for_map
from .repository import get_trade_routes

# GC-571F — world-unit radii from hub on 4000×4000 canvas (not local pct scale).
ROLE_SPATIAL_WORLD: Dict[str, Tuple[float, float]] = {
    "homeworld": (0.0, 0.0),
    "mining": (225.0, 300.0),
    "research": (315.0, 300.0),
    "shipyard": (90.0, 380.0),
    "fortress": (180.0, 340.0),
    "trade": (270.0, 300.0),
    "frontier": (200.0, 360.0),
    "general": (135.0, 300.0),
}

_BEARING_SPREAD_DEG = 14.0


def _node_key(node: Dict[str, Any]) -> str:
    kind = str(node.get("node_kind") or "")
    if kind == "expansion_site":
        return f"site:{node.get('site_key')}"
    if kind == "chokepoint":
        return f"chokepoint:{node.get('chokepoint_key')}"
    if kind == "landmark":
        return f"landmark:{node.get('landmark_key')}"
    return f"planet:{int(node.get('planet_id') or 0)}"


def _polar_to_pct(
    bearing_deg: float,
    radius_pct: float,
    *,
    cx: float = MAP_HUB_CX_PCT,
    cy: float = MAP_HUB_CY_PCT,
) -> Tuple[float, float]:
    rad = math.radians(bearing_deg)
    x = cx + radius_pct * math.sin(rad)
    y = cy - radius_pct * math.cos(rad)
    return round(max(4.0, min(96.0, x)), 2), round(max(4.0, min(96.0, y)), 2)


def _layout_colony_nodes(
    colonies: List[Dict[str, Any]],
    *,
    is_own: bool = True,
    include_actions: bool = True,
    cluster_kind: str = "own_cluster",
) -> List[Dict[str, Any]]:
    role_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in colonies:
        role_key = str(row.get("empire_role_key") or "general")
        role_groups[role_key].append(dict(row))

    nodes: List[Dict[str, Any]] = []
    for role_key, group in role_groups.items():
        bearing, radius_world = ROLE_SPATIAL_WORLD.get(role_key, ROLE_SPATIAL_WORLD["general"])
        total = len(group)
        for index, row in enumerate(group):
            if role_key == "homeworld" or radius_world <= 0:
                bearing_deg = 0.0
                layout_radius_world = 0.0
                x_pct, y_pct = MAP_HUB_CX_PCT, MAP_HUB_CY_PCT
                layout_slot = "hub"
            else:
                bearing_deg = bearing + (index - (total - 1) / 2.0) * _BEARING_SPREAD_DEG
                layout_radius_world = radius_world
                x_pct, y_pct = MAP_HUB_CX_PCT, MAP_HUB_CY_PCT
                layout_slot = role_key
            node = dict(row)
            node["node_kind"] = "colony"
            node["region_key"] = "genesis_core"
            node["is_own"] = bool(is_own)
            node["cluster_kind"] = cluster_kind
            node["layout_slot"] = layout_slot
            node["layout_index"] = index
            node["layout_bearing_deg"] = round(bearing_deg, 2)
            node["layout_radius_world"] = layout_radius_world
            node["layout_x_pct"] = x_pct
            node["layout_y_pct"] = y_pct
            node["node_key"] = _node_key(node)
            role_key = str(row.get("empire_role_key") or "general")
            if include_actions:
                node["actions"] = build_location_actions(
                    role_key,
                    is_homeworld=bool(row.get("is_homeworld")) or role_key == "homeworld",
                )
            nodes.append(node)

    nodes.sort(
        key=lambda n: (
            0 if n.get("layout_slot") == "hub" else 1,
            str(n.get("layout_slot") or ""),
            int(n.get("layout_index") or 0),
            int(n.get("planet_id") or 0),
        )
    )
    return nodes


def _layout_chokepoint_nodes(chokepoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for row in chokepoints:
        bearing = float(row.get("layout_bearing_deg") or 0)
        radius_world = float(row.get("layout_radius_world") or 480)
        node = dict(row)
        node["node_kind"] = "chokepoint"
        node["layout_slot"] = "gate"
        node["layout_index"] = 0
        node["layout_bearing_deg"] = bearing
        node["layout_radius_world"] = radius_world
        node["layout_x_pct"] = MAP_HUB_CX_PCT
        node["layout_y_pct"] = MAP_HUB_CY_PCT
        node["node_key"] = _node_key(node)
        nodes.append(node)

    nodes.sort(key=lambda n: float(n.get("layout_radius_world") or 0))
    return nodes


def _layout_landmark_nodes(landmarks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for row in landmarks:
        bearing = float(row.get("layout_bearing_deg") or 0)
        radius_world = float(row.get("layout_radius_world") or 1100)
        node = dict(row)
        node["node_kind"] = "landmark"
        node["layout_slot"] = "landmark"
        node["layout_index"] = 0
        node["layout_bearing_deg"] = bearing
        node["layout_radius_world"] = radius_world
        node["layout_x_pct"] = MAP_HUB_CX_PCT
        node["layout_y_pct"] = MAP_HUB_CY_PCT
        node["node_key"] = _node_key(node)
        nodes.append(node)

    nodes.sort(key=lambda n: (str(n.get("region_key") or ""), str(n.get("landmark_key") or "")))
    return nodes


def _layout_expansion_nodes(expansion_sites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for row in expansion_sites:
        bearing = float(row.get("layout_bearing_deg") or 0)
        radius_world = float(row.get("layout_radius_world") or 720)
        node = dict(row)
        node["node_kind"] = "expansion_site"
        node["layout_slot"] = str(row.get("layout_slot") or "center")
        node["layout_index"] = 0
        node["layout_bearing_deg"] = bearing
        node["layout_radius_world"] = radius_world
        node["layout_x_pct"] = MAP_HUB_CX_PCT
        node["layout_y_pct"] = MAP_HUB_CY_PCT
        node["node_key"] = _node_key(node)
        nodes.append(node)

    nodes.sort(key=lambda n: (str(n.get("region_key") or ""), str(n.get("site_key") or "")))
    return nodes


def _split_colonies_by_world_binding(
    colonies: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cluster: List[Dict[str, Any]] = []
    world_bound: List[Dict[str, Any]] = []
    for row in colonies:
        if (
            row.get("world_key")
            and row.get("world_x") is not None
            and row.get("world_y") is not None
            and not bool(row.get("is_homeworld"))
        ):
            world_bound.append(row)
        else:
            cluster.append(row)
    return cluster, world_bound


def _layout_world_bound_colony_nodes(
    colonies: List[Dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
) -> List[Dict[str, Any]]:
    """Place map-founded colonies at strategic world coordinates (GC-582D)."""
    from .strategic_worlds import STRATEGIC_WORLD_TYPE_DEFS, empire_role_key_for_planet_role
    from .world_colonization import WorldKeyError, get_claim_by_world_key, is_newly_colonized_world
    from .world_map import world_to_layout_pct

    nodes: List[Dict[str, Any]] = []
    for row in colonies:
        planet_role = str(row.get("planet_role") or "")
        empire_role = empire_role_key_for_planet_role(planet_role)
        meta = STRATEGIC_WORLD_TYPE_DEFS.get(planet_role, {})
        wx = float(row["world_x"])
        wy = float(row["world_y"])
        x_pct, y_pct = world_to_layout_pct(wx, wy)
        identity = role_payload(empire_role)
        if meta.get("role_icon"):
            identity["empire_role_icon"] = meta["role_icon"]
        node = dict(row)
        node.update(identity)
        node["node_kind"] = "colony"
        node["cluster_kind"] = "own_cluster"
        node["region_key"] = "genesis_core"
        node["is_own"] = True
        node["world_map_bound"] = True
        node["layout_slot"] = "world_colony"
        node["layout_index"] = 0
        node["layout_bearing_deg"] = 0.0
        node["layout_radius_world"] = 0.0
        node["layout_x_pct"] = x_pct
        node["layout_y_pct"] = y_pct
        node["_world_x"] = wx
        node["_world_y"] = wy
        node["strategic_type_key"] = meta.get("type_key") or ""
        origin_key = str(row.get("origin_world_key") or row.get("world_key") or "").strip()
        if origin_key:
            try:
                from .strategic_worlds import build_strategic_world_presentation_from_key

                origin = build_strategic_world_presentation_from_key(origin_key)
                node["origin_world_key"] = origin_key
                node["origin_world_name_key"] = origin.get("name_key") or ""
                node["origin_world_type_key"] = origin.get("type_key") or ""
            except WorldKeyError:
                pass
        claim = get_claim_by_world_key(str(row.get("world_key") or ""), conn=conn) if conn else None
        if claim and claim.get("claimed_at"):
            node["claimed_at"] = float(claim["claimed_at"])
            node["is_newly_colonized"] = is_newly_colonized_world(claim["claimed_at"])
        else:
            node["is_newly_colonized"] = False
        node["node_key"] = _node_key(node)
        node["actions"] = build_location_actions(
            empire_role,
            is_homeworld=bool(row.get("is_homeworld")),
        )
        nodes.append(node)

    nodes.sort(key=lambda n: int(n.get("planet_id") or 0))
    return nodes


def _assign_layout(
    colonies: List[Dict[str, Any]],
    expansion_sites: List[Dict[str, Any]],
    chokepoints: List[Dict[str, Any]],
    landmarks: List[Dict[str, Any]],
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    cluster_colonies, world_colonies = _split_colonies_by_world_binding(colonies)
    return (
        _layout_colony_nodes(cluster_colonies)
        + _layout_world_bound_colony_nodes(world_colonies, conn=conn)
        + _layout_chokepoint_nodes(chokepoints)
        + _layout_landmark_nodes(landmarks)
        + _layout_expansion_nodes(expansion_sites)
    )


def _find_hub_key(nodes: List[Dict[str, Any]]) -> Optional[str]:
    for n in nodes:
        if str(n.get("node_kind") or "") != "colony":
            continue
        if str(n.get("empire_role_key") or "") == "homeworld" or n.get("layout_slot") == "hub":
            return _node_key(n)
    return None


def _build_edges(nodes: List[Dict[str, Any]], *, player_id: int, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    node_by_key = {_node_key(n): n for n in nodes}
    hub_key = _find_hub_key(nodes)

    edges: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str, str]] = set()

    def _append_edge(source: Dict[str, Any], target: Dict[str, Any], edge_type: str, resource_key: str = "") -> None:
        sk = _node_key(source)
        tk = _node_key(target)
        if sk == tk:
            return
        dedupe = (min(sk, tk), max(sk, tk), edge_type)
        if dedupe in seen:
            return
        seen.add(dedupe)
        edges.append(
            {
                "source_key": sk,
                "target_key": tk,
                "source_planet_id": source.get("planet_id"),
                "target_planet_id": target.get("planet_id"),
                "edge_type": edge_type,
                "resource_key": resource_key,
                "source_x_pct": source["layout_x_pct"],
                "source_y_pct": source["layout_y_pct"],
                "target_x_pct": target["layout_x_pct"],
                "target_y_pct": target["layout_y_pct"],
            }
        )

    for route in get_trade_routes(int(player_id), conn=conn):
        src_id = int(route.get("source_planet_id") or 0)
        tgt_id = int(route.get("target_planet_id") or 0)
        src = node_by_key.get(f"planet:{src_id}")
        tgt = node_by_key.get(f"planet:{tgt_id}")
        if src and tgt:
            _append_edge(src, tgt, "trade_route", str(route.get("resource_key") or ""))

    if hub_key and hub_key in node_by_key:
        hub = node_by_key[hub_key]
        linked_planets = {
            e["source_planet_id"] if e.get("target_planet_id") == hub.get("planet_id") else e["target_planet_id"]
            for e in edges
            if hub.get("planet_id") in (e.get("source_planet_id"), e.get("target_planet_id"))
        }
        chokepoint_by_key = {
            str(n.get("chokepoint_key") or ""): n
            for n in nodes
            if str(n.get("node_kind") or "") == "chokepoint"
        }

        for n in nodes:
            if _node_key(n) == hub_key:
                continue
            if str(n.get("node_kind") or "") == "expansion_site":
                region_key = str(n.get("region_key") or "outer_rim")
                gate_keys = gate_chain_for_region(region_key)
                path: List[Dict[str, Any]] = [hub]
                for gate_key in gate_keys:
                    gate_node = chokepoint_by_key.get(gate_key)
                    if gate_node:
                        path.append(gate_node)
                path.append(n)
                for index in range(len(path) - 1):
                    source = path[index]
                    target = path[index + 1]
                    if str(target.get("node_kind") or "") == "expansion_site":
                        edge_type = "expansion_unlocked" if target.get("is_unlocked") else "expansion_locked"
                    else:
                        edge_type = "chokepoint_link"
                    _append_edge(source, target, edge_type)
                continue
            if str(n.get("region_key") or "") != "genesis_core":
                continue
            pid = int(n.get("planet_id") or 0)
            if pid and pid not in linked_planets:
                _append_edge(hub, n, "hub_link")

    return edges


def build_command_map_payload(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Graph nodes + edges + regions for /galaxy?view=command_map."""
    colonies = build_colonies_identity(int(player_id), conn=conn)
    expansion_sites = list_expansion_sites_for_player(int(player_id), conn=conn)
    chokepoints = list_chokepoints_for_map()
    landmarks = list_landmarks_for_map()
    nodes = _assign_layout(colonies, expansion_sites, chokepoints, landmarks, conn=conn)
    edges = _build_edges(nodes, player_id=int(player_id), conn=conn)
    influence = build_influence_payload(nodes)
    expansion = build_expansion_summary(int(player_id), conn=conn)
    regions = build_regions_payload(
        expansion_sites=expansion_sites,
        colony_count=len(colonies),
    )
    payload = {
        "nodes": nodes,
        "edges": edges,
        "expansion": expansion,
        "regions": regions,
        "chokepoints": chokepoints,
        "landmarks": landmarks,
        "influence": influence,
    }
    from .world_map import apply_shared_world_layout

    return apply_shared_world_layout(payload, int(player_id), conn=conn)
