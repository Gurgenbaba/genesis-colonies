"""Influence territory blob for Command Map — visual only (GC-566)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

HUB_INFLUENCE_RADIUS_PCT = 12.5
COLONY_INFLUENCE_RADIUS_PCT = 9.5
HUB_INFLUENCE_RADIUS_WORLD = 42.0
COLONY_INFLUENCE_RADIUS_WORLD = 30.0
_WORLD_PCT_SCALE = 40.0
_ENVELOPE_ANGLES_DEG = tuple(range(0, 360, 30))
_HULL_PAD_PCT = 2.4
_SMOOTH_CTRL = 0.22


def _is_own_colony_node(node: Dict[str, Any]) -> bool:
    if str(node.get("node_kind") or "colony") != "colony":
        return False
    return bool(node.get("is_own", True))


def select_influence_nodes(nodes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Colony nodes that contribute to the player's influence blob."""
    selected = [_influence_point_row(n) for n in nodes if _is_own_colony_node(n)]
    selected.sort(
        key=lambda row: (
            0 if row.get("is_homeworld") else 1,
            str(row.get("node_key") or ""),
        )
    )
    return selected


def _influence_point_row(node: Dict[str, Any]) -> Dict[str, Any]:
    is_homeworld = bool(node.get("is_homeworld")) or str(node.get("empire_role_key") or "") == "homeworld"
    if node.get("world_x") is not None and node.get("world_y") is not None:
        x = float(node["world_x"])
        y = float(node["world_y"])
        radius = HUB_INFLUENCE_RADIUS_WORLD if is_homeworld else COLONY_INFLUENCE_RADIUS_WORLD
        coord_max = 4000.0
    else:
        x = float(node.get("layout_x_pct") or 50)
        y = float(node.get("layout_y_pct") or 52)
        radius = HUB_INFLUENCE_RADIUS_PCT if is_homeworld else COLONY_INFLUENCE_RADIUS_PCT
        coord_max = 98.0
    return {
        "node_key": str(node.get("node_key") or ""),
        "planet_id": node.get("planet_id"),
        "is_own": True,
        "is_homeworld": is_homeworld,
        "empire_role_key": str(node.get("empire_role_key") or "general"),
        "x_pct": x,
        "y_pct": y,
        "radius_pct": radius,
        "coord_max": coord_max,
    }


def _cross(o: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    unique = sorted(set((round(x, 4), round(y, 4)) for x, y in points))
    if len(unique) <= 1:
        return list(unique)

    lower: List[Tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: List[Tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    return lower[:-1] + upper[:-1]


def _expand_hull(
    hull: Sequence[Tuple[float, float]],
    *,
    pad_pct: float,
    coord_min: float = 2.0,
    coord_max: float = 98.0,
) -> List[Tuple[float, float]]:
    if len(hull) < 2:
        return list(hull)
    cx = sum(x for x, _ in hull) / len(hull)
    cy = sum(y for _, y in hull) / len(hull)
    expanded: List[Tuple[float, float]] = []
    for x, y in hull:
        dx = x - cx
        dy = y - cy
        length = math.hypot(dx, dy) or 1.0
        expanded.append(
            (
                round(max(coord_min, min(coord_max, x + pad_pct * dx / length)), 2),
                round(max(coord_min, min(coord_max, y + pad_pct * dy / length)), 2),
            )
        )
    return expanded


def _circle_path(x: float, y: float, radius: float) -> str:
    return (
        f"M {x - radius:.2f} {y:.2f} "
        f"A {radius:.2f} {radius:.2f} 0 1 0 {x + radius:.2f} {y:.2f} "
        f"A {radius:.2f} {radius:.2f} 0 1 0 {x - radius:.2f} {y:.2f} Z"
    )


def _smooth_hull_path(hull: Sequence[Tuple[float, float]]) -> str:
    if len(hull) == 0:
        return ""
    if len(hull) == 1:
        x, y = hull[0]
        return _circle_path(x, y, HUB_INFLUENCE_RADIUS_PCT)
    if len(hull) == 2:
        (x1, y1), (x2, y2) = hull
        mx = (x1 + x2) / 2.0
        my = (y1 + y2) / 2.0
        span = math.hypot(x2 - x1, y2 - y1) / 2.0 + COLONY_INFLUENCE_RADIUS_PCT
        return _circle_path(mx, my, span)

    parts = [f"M {hull[0][0]:.2f} {hull[0][1]:.2f}"]
    count = len(hull)
    for index in range(count):
        p0 = hull[(index - 1) % count]
        p1 = hull[index]
        p2 = hull[(index + 1) % count]
        cx = p1[0] + (p2[0] - p0[0]) * _SMOOTH_CTRL
        cy = p1[1] + (p2[1] - p0[1]) * _SMOOTH_CTRL
        parts.append(f"Q {cx:.2f} {cy:.2f} {p2[0]:.2f} {p2[1]:.2f}")
    parts.append("Z")
    return " ".join(parts)


def _envelope_points(points: Sequence[Dict[str, Any]]) -> List[Tuple[float, float]]:
    envelope: List[Tuple[float, float]] = []
    for row in points:
        x = float(row["x_pct"])
        y = float(row["y_pct"])
        radius = float(row["radius_pct"])
        for bearing in _ENVELOPE_ANGLES_DEG:
            rad = math.radians(bearing)
            envelope.append((x + radius * math.sin(rad), y - radius * math.cos(rad)))
    return envelope


def build_influence_payload(nodes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """SVG influence blob derived from own colony positions only."""
    influence_nodes = select_influence_nodes(nodes)
    if not influence_nodes:
        return {
            "visible": False,
            "svg_path": "",
            "node_keys": [],
            "points": [],
        }

    if len(influence_nodes) == 1:
        row = influence_nodes[0]
        svg_path = _circle_path(float(row["x_pct"]), float(row["y_pct"]), float(row["radius_pct"]))
    else:
        coord_max = float(influence_nodes[0].get("coord_max") or 98.0)
        pad = _HULL_PAD_PCT * (_WORLD_PCT_SCALE if coord_max > 100 else 1.0)
        hull = _convex_hull(_envelope_points(influence_nodes))
        hull = _expand_hull(hull, pad_pct=pad, coord_min=0.0, coord_max=coord_max)
        svg_path = _smooth_hull_path(hull)

    return {
        "visible": True,
        "svg_path": svg_path,
        "node_keys": [str(row["node_key"]) for row in influence_nodes if row.get("node_key")],
        "points": influence_nodes,
    }
