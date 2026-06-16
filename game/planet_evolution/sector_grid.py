"""Procedural sector grid for Command Map geography (GC-580A). Display only."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

SECTOR_SIZE = 2000
SECTOR_VIEWPORT_PAD = 2000.0
MAX_CHUNKS_PER_REQUEST = 196
DEFAULT_SECTOR_SEED = 1


class SectorBoundsTooLargeError(ValueError):
    """Requested viewport bounds cover too many sector chunks."""

SECTOR_TYPE_DEFS: Dict[str, Dict[str, str]] = {
    "genesis_core": {"label_key": "galaxy_sector_genesis_core", "tone": "core"},
    "outer_rim": {"label_key": "galaxy_sector_outer_rim", "tone": "rim"},
    "ancient_sector": {"label_key": "galaxy_sector_ancient_sector", "tone": "ancient"},
    "dark_expanse": {"label_key": "galaxy_sector_dark_expanse", "tone": "dark"},
    "nebula": {"label_key": "galaxy_sector_nebula", "tone": "nebula"},
    "void": {"label_key": "galaxy_sector_void", "tone": "void"},
    "crystal_belt": {"label_key": "galaxy_sector_crystal_belt", "tone": "crystal"},
    "dead_zone": {"label_key": "galaxy_sector_dead_zone", "tone": "dead"},
}

SECTOR_TYPE_ORDER: Tuple[str, ...] = tuple(SECTOR_TYPE_DEFS.keys())


def normalize_world_bounds(
    min_wx: float,
    min_wy: float,
    max_wx: float,
    max_wy: float,
) -> Tuple[float, float, float, float]:
    lo_x, lo_y = float(min_wx), float(min_wy)
    hi_x, hi_y = float(max_wx), float(max_wy)
    if lo_x > hi_x:
        lo_x, hi_x = hi_x, lo_x
    if lo_y > hi_y:
        lo_y, hi_y = hi_y, lo_y
    return lo_x, lo_y, hi_x, hi_y


def expand_world_bounds(
    min_wx: float,
    min_wy: float,
    max_wx: float,
    max_wy: float,
    *,
    pad: float = SECTOR_VIEWPORT_PAD,
) -> Tuple[float, float, float, float]:
    lo_x, lo_y, hi_x, hi_y = normalize_world_bounds(min_wx, min_wy, max_wx, max_wy)
    return lo_x - pad, lo_y - pad, hi_x + pad, hi_y + pad


def visible_world_bounds_from_viewport(
    pan_x: float,
    pan_y: float,
    zoom: float,
    viewport_w: float,
    viewport_h: float,
    *,
    pad: float = SECTOR_VIEWPORT_PAD,
) -> Tuple[float, float, float, float]:
    """Convert screen viewport pan/zoom into world-space bounds (GC-580B)."""
    z = max(float(zoom), 0.001)
    vp_w = max(float(viewport_w), 1.0)
    vp_h = max(float(viewport_h), 1.0)
    min_wx = (0.0 - float(pan_x)) / z - pad
    min_wy = (0.0 - float(pan_y)) / z - pad
    max_wx = (vp_w - float(pan_x)) / z + pad
    max_wy = (vp_h - float(pan_y)) / z + pad
    return normalize_world_bounds(min_wx, min_wy, max_wx, max_wy)


def count_sectors_in_bounds(
    min_wx: float,
    min_wy: float,
    max_wx: float,
    max_wy: float,
) -> int:
    lo_x, lo_y, hi_x, hi_y = normalize_world_bounds(min_wx, min_wy, max_wx, max_wy)
    min_sx, min_sy = sector_coords(lo_x, lo_y)
    max_sx, max_sy = sector_coords(hi_x, hi_y)
    return (max_sx - min_sx + 1) * (max_sy - min_sy + 1)


def dedupe_chunks_by_id(chunks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in chunks:
        chunk_id = str(row.get("id") or "")
        if chunk_id:
            by_id[chunk_id] = dict(row)
    return list(by_id.values())


def build_sector_chunks_for_request(
    min_wx: float,
    min_wy: float,
    max_wx: float,
    max_wy: float,
    *,
    seed: int = DEFAULT_SECTOR_SEED,
    pad: float = 0.0,
) -> List[Dict[str, Any]]:
    """Build sector chunks for API/viewport requests with optional extra padding."""
    if pad > 0:
        min_wx, min_wy, max_wx, max_wy = expand_world_bounds(min_wx, min_wy, max_wx, max_wy, pad=pad)
    else:
        min_wx, min_wy, max_wx, max_wy = normalize_world_bounds(min_wx, min_wy, max_wx, max_wy)
    if count_sectors_in_bounds(min_wx, min_wy, max_wx, max_wy) > MAX_CHUNKS_PER_REQUEST:
        raise SectorBoundsTooLargeError("sector viewport bounds too large")
    return dedupe_chunks_by_id(build_sector_chunks_for_world(min_wx, min_wy, max_wx, max_wy, seed=seed))


def sector_coords(world_x: float, world_y: float) -> Tuple[int, int]:
    """Map world coordinates to sector grid indices."""
    sx = int(math.floor(float(world_x) / SECTOR_SIZE))
    sy = int(math.floor(float(world_y) / SECTOR_SIZE))
    return sx, sy


def _stable_mix(*parts: int) -> int:
    h = 2166136261
    for part in parts:
        h ^= int(part) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def sector_type(sector_x: int, sector_y: int, *, seed: int = 1) -> str:
    """Deterministic sector biome from grid coordinates."""
    h = _stable_mix(sector_x, sector_y, seed, 580)
    return SECTOR_TYPE_ORDER[h % len(SECTOR_TYPE_ORDER)]


def _corner_jitter(sector_x: int, sector_y: int, *, seed: int, corner: int) -> Tuple[float, float]:
    h = _stable_mix(sector_x, sector_y, seed, corner, 901)
    hx = ((h >> 8) & 0xFFFF) / 65535.0
    hy = (h & 0xFF) / 255.0
    return (hx - 0.5) * 90.0, (hy - 0.5) * 90.0


def _sector_path(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    sector_x: int,
    sector_y: int,
    seed: int,
) -> str:
    """Slightly organic sector polygon in world units."""
    jtl = _corner_jitter(sector_x, sector_y, seed=seed, corner=0)
    jtr = _corner_jitter(sector_x, sector_y, seed=seed, corner=1)
    jbr = _corner_jitter(sector_x, sector_y, seed=seed, corner=2)
    jbl = _corner_jitter(sector_x, sector_y, seed=seed, corner=3)
    x0, y0 = x + jtl[0], y + jtl[1]
    x1, y1 = x + width + jtr[0], y + jtr[1]
    x2, y2 = x + width + jbr[0], y + height + jbr[1]
    x3, y3 = x + jbl[0], y + height + jbl[1]
    mx = x + width * 0.5
    my = y + height * 0.5
    return (
        f"M {x0:.1f} {y0:.1f} "
        f"Q {x + width * 0.5 + jtr[0] * 0.35:.1f} {y + jtr[1] * 0.5:.1f} {x1:.1f} {y1:.1f} "
        f"Q {x + width + jtr[0] * 0.5:.1f} {y + height * 0.5 + jbr[1] * 0.35:.1f} {x2:.1f} {y2:.1f} "
        f"Q {mx + jbl[0] * 0.35:.1f} {y + height + jbl[1] * 0.5:.1f} {x3:.1f} {y3:.1f} "
        f"Q {x + jtl[0] * 0.5:.1f} {my + jtl[1] * 0.35:.1f} {x0:.1f} {y0:.1f} Z"
    )


def _sector_bounds(sector_x: int, sector_y: int) -> Tuple[float, float, float, float]:
    x = float(sector_x * SECTOR_SIZE)
    y = float(sector_y * SECTOR_SIZE)
    return x, y, float(SECTOR_SIZE), float(SECTOR_SIZE)


def build_sector_chunks_for_world(
    min_wx: float,
    min_wy: float,
    max_wx: float,
    max_wy: float,
    *,
    seed: int = 1,
) -> List[Dict[str, Any]]:
    """Build visible sector chunks for a world-space bounding box."""
    lo_x, lo_y = float(min_wx), float(min_wy)
    hi_x, hi_y = float(max_wx), float(max_wy)
    if lo_x > hi_x:
        lo_x, hi_x = hi_x, lo_x
    if lo_y > hi_y:
        lo_y, hi_y = hi_y, lo_y

    min_sx, min_sy = sector_coords(lo_x, lo_y)
    max_sx, max_sy = sector_coords(hi_x, hi_y)

    chunks: List[Dict[str, Any]] = []
    for sy in range(min_sy, max_sy + 1):
        for sx in range(min_sx, max_sx + 1):
            stype = sector_type(sx, sy, seed=seed)
            meta = SECTOR_TYPE_DEFS.get(stype, SECTOR_TYPE_DEFS["outer_rim"])
            x, y, width, height = _sector_bounds(sx, sy)
            chunks.append(
                {
                    "id": f"sector_{sx}_{sy}",
                    "sector_x": sx,
                    "sector_y": sy,
                    "type": stype,
                    "label_key": meta["label_key"],
                    "tone": meta["tone"],
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "width": width,
                    "height": height,
                    "center_x": round(x + width / 2.0, 2),
                    "center_y": round(y + height / 2.0, 2),
                    "path": _sector_path(x, y, width, height, sector_x=sx, sector_y=sy, seed=seed),
                }
            )

    chunks.sort(key=lambda row: (int(row["sector_y"]), int(row["sector_x"])))
    return chunks


def sector_types_in_range(
    min_sx: int,
    min_sy: int,
    max_sx: int,
    max_sy: int,
    *,
    seed: int = 1,
) -> List[str]:
    seen: List[str] = []
    for sy in range(min_sy, max_sy + 1):
        for sx in range(min_sx, max_sx + 1):
            stype = sector_type(sx, sy, seed=seed)
            if stype not in seen:
                seen.append(stype)
    return seen
