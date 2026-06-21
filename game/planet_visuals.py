"""Planet visuals — landscape + accent theme keyed by galaxy slot (position 1–15)."""

from __future__ import annotations

from typing import Any, Dict, TypedDict


class PlanetIdentity(TypedDict):
    landscape: str
    accent_color: str
    secondary_color: str
    effect: str


DEFAULT_LANDSCAPE = "normaltempplanet01-h.jpg"

_DEFAULT_IDENTITY: PlanetIdentity = {
    "landscape": DEFAULT_LANDSCAPE,
    "accent_color": "#46e5ff",
    "secondary_color": "#7fffd9",
    "effect": "temperate",
}

# Single source: position → landscape filename + accent palette + optional hero effect.
_PLANET_IDENTITY_BY_POSITION: Dict[int, PlanetIdentity] = {
    1: {
        "landscape": "trockenplanet01-h.jpg",
        "accent_color": "#c4a35a",
        "secondary_color": "#e8d4a0",
        "effect": "ancient",
    },
    2: {
        "landscape": "trockenplanet04-h.jpg",
        "accent_color": "#5fd4a8",
        "secondary_color": "#9ef0cc",
        "effect": "temperate",
    },
    3: {
        "landscape": "trockenplanet06-h.jpg",
        "accent_color": "#4ecf7a",
        "secondary_color": "#8ef5a8",
        "effect": "forest",
    },
    4: {
        "landscape": "trockenplanet08-h.jpg",
        "accent_color": "#3dd9b0",
        "secondary_color": "#7fffd4",
        "effect": "tropical",
    },
    5: {
        "landscape": "normaltempplanet04-h.jpg",
        "accent_color": "#38c96a",
        "secondary_color": "#7ef5a0",
        "effect": "jungle",
    },
    6: {
        "landscape": "normaltempplanet03-h.jpg",
        "accent_color": "#3aa8ff",
        "secondary_color": "#7fd4ff",
        "effect": "ocean",
    },
    7: {
        "landscape": "normaltempplanet01-h.jpg",
        "accent_color": "#e8b04a",
        "secondary_color": "#ffd878",
        "effect": "desert",
    },
    8: {
        "landscape": "wasserplanet07-h.jpg",
        "accent_color": "#a89888",
        "secondary_color": "#d4c8bc",
        "effect": "barren",
    },
    9: {
        "landscape": "wasserplanet08-h.jpg",
        "accent_color": "#ff6a3a",
        "secondary_color": "#ffaa66",
        "effect": "volcanic",
    },
    10: {
        "landscape": "dschungelplanet08-h.jpg",
        "accent_color": "#b88870",
        "secondary_color": "#d8b8a0",
        "effect": "ash",
    },
    11: {
        "landscape": "dschungelplanet07-h.jpg",
        "accent_color": "#9ec8e0",
        "secondary_color": "#cce8f8",
        "effect": "tundra",
    },
    12: {
        "landscape": "gasplanet05-h.jpg",
        "accent_color": "#9a6cff",
        "secondary_color": "#c8a8ff",
        "effect": "gas",
    },
    13: {
        "landscape": "eisplanet04-h.jpg",
        "accent_color": "#6ee8ff",
        "secondary_color": "#a8f4ff",
        "effect": "frost",
    },
    14: {
        "landscape": "eisplanet06-h.jpg",
        "accent_color": "#4ad8ff",
        "secondary_color": "#88e8ff",
        "effect": "glacier",
    },
    15: {
        "landscape": "eisplanet09-h.jpg",
        "accent_color": "#3ff8ff",
        "secondary_color": "#6ccfff",
        "effect": "ice",
    },
}


def _normalize_position(position: Any) -> int | None:
    try:
        pos = int(position)
    except (TypeError, ValueError):
        return None
    if pos < 1 or pos > 15:
        return None
    return pos


def get_planet_identity_for_position(position: Any) -> PlanetIdentity:
    """Landscape + accent palette + hero effect for galaxy slot 1–15."""
    pos = _normalize_position(position)
    if pos is None:
        return dict(_DEFAULT_IDENTITY)
    row = _PLANET_IDENTITY_BY_POSITION.get(pos)
    if not row:
        return dict(_DEFAULT_IDENTITY)
    return dict(row)


def get_landscape_for_position(position: int) -> str:
    """Return landscape filename for galaxy slot 1–15; fallback for invalid values."""
    return get_planet_identity_for_position(position)["landscape"]


def landscape_static_relpath(position: int) -> str:
    """Relative static path under ``static/`` for the given galaxy slot."""
    return f"img/landscapes/{get_landscape_for_position(position)}"


def raster_webp_relpath(relpath: str) -> str:
    """Sibling WebP path for ``img/.../file.png`` or ``.jpg`` (GC-555)."""
    rel = str(relpath or "").strip().lstrip("/")
    if not rel:
        return ""
    stem = rel.rsplit(".", 1)[0] if "." in rel else rel
    return f"{stem}.webp"


def landscape_webp_relpath(position: int) -> str:
    """WebP landscape path for galaxy slot 1–15."""
    return raster_webp_relpath(landscape_static_relpath(position))


def landscape_filename_for_planet(planet: dict | None) -> str:
    """Resolve landscape filename from a planet row (uses ``position`` when present)."""
    if not planet:
        return DEFAULT_LANDSCAPE
    position = planet.get("position")
    if position is None or position == "":
        return DEFAULT_LANDSCAPE
    return get_landscape_for_position(int(position))


def planet_theme_for_planet(planet: dict | None) -> Dict[str, Any]:
    """Theme slice for templates/API — same position source as landscape."""
    if not planet:
        ident = dict(_DEFAULT_IDENTITY)
        return {
            "position": 0,
            "accent_color": ident["accent_color"],
            "secondary_color": ident["secondary_color"],
            "effect": ident["effect"],
            "landscape": ident["landscape"],
        }
    position = planet.get("position")
    if position is None or position == "":
        ident = dict(_DEFAULT_IDENTITY)
        return {
            "position": 0,
            "accent_color": ident["accent_color"],
            "secondary_color": ident["secondary_color"],
            "effect": ident["effect"],
            "landscape": ident["landscape"],
        }
    pos = int(position)
    ident = get_planet_identity_for_position(pos)
    return {
        "position": pos,
        "accent_color": ident["accent_color"],
        "secondary_color": ident["secondary_color"],
        "effect": ident["effect"],
        "landscape": ident["landscape"],
    }
