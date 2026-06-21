"""Planet visuals — landscape + hero card + accent theme keyed by galaxy slot (position 1–15)."""

from __future__ import annotations

from typing import Any, Dict, TypedDict


class PlanetIdentity(TypedDict):
    landscape: str
    herocard: str
    label_key: str
    theme_key: str
    theme_group: str
    accent_color: str
    secondary_color: str
    effect: str


DEFAULT_LANDSCAPE = "normaltempplanet01-h.jpg"
DEFAULT_HEROCARD = "herocard_08.png"
DEFAULT_LABEL_KEY = "planet_slot_08"
DEFAULT_THEME_KEY = "temperate-highlands"
DEFAULT_THEME_GROUP = "living"

_DEFAULT_IDENTITY: PlanetIdentity = {
    "landscape": DEFAULT_LANDSCAPE,
    "herocard": DEFAULT_HEROCARD,
    "label_key": DEFAULT_LABEL_KEY,
    "theme_key": DEFAULT_THEME_KEY,
    "theme_group": DEFAULT_THEME_GROUP,
    "accent_color": "#5fd4a8",
    "secondary_color": "#9ef0cc",
    "effect": "temperate",
}

# Position 1 = warmest galaxy slot, 15 = coldest — aligned with landscapes + hero cards.
_TEMPERATURE_BY_POSITION: Dict[int, tuple[int, int]] = {
    1: (350, 520),
    2: (260, 400),
    3: (190, 310),
    4: (130, 230),
    5: (85, 170),
    6: (55, 115),
    7: (35, 75),
    8: (5, 35),
    9: (-8, 22),
    10: (-15, 15),
    11: (-28, 5),
    12: (-60, -15),
    13: (-100, -45),
    14: (-165, -90),
    15: (-240, -175),
}
_DEFAULT_TEMPERATURE = _TEMPERATURE_BY_POSITION[8]

# Position 1 = warmest galaxy slot, 15 = coldest — same order as landscapes + hero cards.
_PLANET_IDENTITY_BY_POSITION: Dict[int, PlanetIdentity] = {
    1: {
        "landscape": "trockenplanet01-h.jpg",
        "herocard": "herocard_01.png",
        "label_key": "planet_slot_01",
        "theme_key": "inferno",
        "theme_group": "hot",
        "accent_color": "#ff6830",
        "secondary_color": "#ffaa66",
        "effect": "volcanic",
    },
    2: {
        "landscape": "trockenplanet04-h.jpg",
        "herocard": "herocard_02.png",
        "label_key": "planet_slot_02",
        "theme_key": "magma",
        "theme_group": "hot",
        "accent_color": "#ff8040",
        "secondary_color": "#ffb080",
        "effect": "volcanic",
    },
    3: {
        "landscape": "trockenplanet06-h.jpg",
        "herocard": "herocard_03.png",
        "label_key": "planet_slot_03",
        "theme_key": "ash",
        "theme_group": "hot",
        "accent_color": "#b88870",
        "secondary_color": "#d8b8a0",
        "effect": "ash",
    },
    4: {
        "landscape": "trockenplanet08-h.jpg",
        "herocard": "herocard_04.png",
        "label_key": "planet_slot_04",
        "theme_key": "barren-fireland",
        "theme_group": "arid",
        "accent_color": "#e87840",
        "secondary_color": "#ffa868",
        "effect": "desert",
    },
    5: {
        "landscape": "normaltempplanet04-h.jpg",
        "herocard": "herocard_05.png",
        "label_key": "planet_slot_05",
        "theme_key": "crimson-desert",
        "theme_group": "arid",
        "accent_color": "#e04060",
        "secondary_color": "#ff8090",
        "effect": "desert",
    },
    6: {
        "landscape": "normaltempplanet03-h.jpg",
        "herocard": "herocard_06.png",
        "label_key": "planet_slot_06",
        "theme_key": "golden-desert",
        "theme_group": "arid",
        "accent_color": "#e8b04a",
        "secondary_color": "#ffd878",
        "effect": "desert",
    },
    7: {
        "landscape": "normaltempplanet01-h.jpg",
        "herocard": "herocard_07.png",
        "label_key": "planet_slot_07",
        "theme_key": "arid-frontier",
        "theme_group": "arid",
        "accent_color": "#c4a35a",
        "secondary_color": "#e8d4a0",
        "effect": "desert",
    },
    8: {
        "landscape": "wasserplanet07-h.jpg",
        "herocard": "herocard_08.png",
        "label_key": "planet_slot_08",
        "theme_key": "temperate-highlands",
        "theme_group": "living",
        "accent_color": "#5fd4a8",
        "secondary_color": "#9ef0cc",
        "effect": "temperate",
    },
    9: {
        "landscape": "wasserplanet08-h.jpg",
        "herocard": "herocard_09.png",
        "label_key": "planet_slot_09",
        "theme_key": "forest-world",
        "theme_group": "living",
        "accent_color": "#4ecf7a",
        "secondary_color": "#8ef5a8",
        "effect": "forest",
    },
    10: {
        "landscape": "dschungelplanet08-h.jpg",
        "herocard": "herocard_10.png",
        "label_key": "planet_slot_10",
        "theme_key": "jungle-prime",
        "theme_group": "living",
        "accent_color": "#38c96a",
        "secondary_color": "#7ef5a0",
        "effect": "jungle",
    },
    11: {
        "landscape": "dschungelplanet07-h.jpg",
        "herocard": "herocard_11.png",
        "label_key": "planet_slot_11",
        "theme_key": "ocean-world",
        "theme_group": "living",
        "accent_color": "#3aa8ff",
        "secondary_color": "#7fd4ff",
        "effect": "ocean",
    },
    12: {
        "landscape": "gasplanet05-h.jpg",
        "herocard": "herocard_12.png",
        "label_key": "planet_slot_12",
        "theme_key": "tundra-world",
        "theme_group": "frozen",
        "accent_color": "#9ec8e0",
        "secondary_color": "#cce8f8",
        "effect": "tundra",
    },
    13: {
        "landscape": "eisplanet04-h.jpg",
        "herocard": "herocard_13.png",
        "label_key": "planet_slot_13",
        "theme_key": "glacier-world",
        "theme_group": "frozen",
        "accent_color": "#6ee8ff",
        "secondary_color": "#a8f4ff",
        "effect": "frost",
    },
    14: {
        "landscape": "eisplanet06-h.jpg",
        "herocard": "herocard_14.png",
        "label_key": "planet_slot_14",
        "theme_key": "deep-frost",
        "theme_group": "frozen",
        "accent_color": "#4ad8ff",
        "secondary_color": "#88e8ff",
        "effect": "glacier",
    },
    15: {
        "landscape": "eisplanet09-h.jpg",
        "herocard": "herocard_15.png",
        "label_key": "planet_slot_15",
        "theme_key": "absolute-zero",
        "theme_group": "frozen",
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
    """Landscape + hero card + accent palette + hero effect for galaxy slot 1–15."""
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


def temperature_range_for_position(position: Any) -> Dict[str, Any]:
    """Surface temperature band keyed by galaxy slot (1 = hottest, 15 = coldest)."""
    pos = _normalize_position(position)
    lo, hi = _TEMPERATURE_BY_POSITION.get(pos, _DEFAULT_TEMPERATURE) if pos else _DEFAULT_TEMPERATURE
    return {
        "min_c": lo,
        "max_c": hi,
        "display": f"{lo}°C … {hi}°C",
        "position": pos or 0,
    }


def herocard_static_relpath(position: int) -> str:
    """Relative static path for overview hero card art (position 1–15)."""
    fn = get_planet_identity_for_position(position)["herocard"]
    return f"img/herocards/{fn}"


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


def herocard_webp_relpath(position: int) -> str:
    """WebP hero card path for galaxy slot 1–15."""
    return raster_webp_relpath(herocard_static_relpath(position))


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
        pos = 0
    else:
        position = planet.get("position")
        if position is None or position == "":
            ident = dict(_DEFAULT_IDENTITY)
            pos = 0
        else:
            pos = int(position)
            ident = get_planet_identity_for_position(pos)

    herocard_rel = herocard_static_relpath(pos) if pos else f"img/herocards/{DEFAULT_HEROCARD}"
    landscape_rel = landscape_static_relpath(pos) if pos else f"img/landscapes/{DEFAULT_LANDSCAPE}"
    return {
        "position": pos,
        "accent_color": ident["accent_color"],
        "secondary_color": ident["secondary_color"],
        "glow_color": ident["accent_color"],
        "effect": ident["effect"],
        "theme_key": ident["theme_key"],
        "theme_group": ident["theme_group"],
        "landscape": ident["landscape"],
        "landscape_relpath": landscape_rel,
        "herocard": ident["herocard"],
        "herocard_relpath": herocard_rel,
        "herocard_webp_relpath": raster_webp_relpath(herocard_rel),
        "label_key": ident["label_key"],
    }
