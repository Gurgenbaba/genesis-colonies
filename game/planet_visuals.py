"""Planet visuals — landscape + hero card + accent theme keyed by galaxy slot (position 1–15)."""

from __future__ import annotations

from typing import Any, Dict, TypedDict


class ClimateEconomyModifiers(TypedDict):
    solar_output_factor: float
    metal_prod_factor: float
    crystal_prod_factor: float
    fuel_prod_factor: float
    label_key: str


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

# Slot 8 = baseline economy; slot 1 = hot (more solar/metal), slot 15 = cold (less solar, more crystal).
_CLIMATE_ECONOMY_BY_POSITION: Dict[int, ClimateEconomyModifiers] = {
    1: {"solar_output_factor": 1.42, "metal_prod_factor": 1.14, "crystal_prod_factor": 0.90, "fuel_prod_factor": 1.12, "label_key": "planet_slot_01"},
    2: {"solar_output_factor": 1.34, "metal_prod_factor": 1.10, "crystal_prod_factor": 0.92, "fuel_prod_factor": 1.08, "label_key": "planet_slot_02"},
    3: {"solar_output_factor": 1.26, "metal_prod_factor": 1.06, "crystal_prod_factor": 0.94, "fuel_prod_factor": 1.04, "label_key": "planet_slot_03"},
    4: {"solar_output_factor": 1.18, "metal_prod_factor": 1.08, "crystal_prod_factor": 0.96, "fuel_prod_factor": 1.00, "label_key": "planet_slot_04"},
    5: {"solar_output_factor": 1.12, "metal_prod_factor": 1.06, "crystal_prod_factor": 0.98, "fuel_prod_factor": 0.98, "label_key": "planet_slot_05"},
    6: {"solar_output_factor": 1.08, "metal_prod_factor": 1.04, "crystal_prod_factor": 1.00, "fuel_prod_factor": 0.96, "label_key": "planet_slot_06"},
    7: {"solar_output_factor": 1.04, "metal_prod_factor": 1.02, "crystal_prod_factor": 1.00, "fuel_prod_factor": 0.94, "label_key": "planet_slot_07"},
    8: {"solar_output_factor": 1.00, "metal_prod_factor": 1.00, "crystal_prod_factor": 1.00, "fuel_prod_factor": 1.00, "label_key": "planet_slot_08"},
    9: {"solar_output_factor": 0.98, "metal_prod_factor": 1.00, "crystal_prod_factor": 1.02, "fuel_prod_factor": 1.00, "label_key": "planet_slot_09"},
    10: {"solar_output_factor": 0.96, "metal_prod_factor": 0.98, "crystal_prod_factor": 1.04, "fuel_prod_factor": 1.02, "label_key": "planet_slot_10"},
    11: {"solar_output_factor": 0.94, "metal_prod_factor": 0.96, "crystal_prod_factor": 1.06, "fuel_prod_factor": 1.04, "label_key": "planet_slot_11"},
    12: {"solar_output_factor": 0.82, "metal_prod_factor": 0.94, "crystal_prod_factor": 1.08, "fuel_prod_factor": 0.90, "label_key": "planet_slot_12"},
    13: {"solar_output_factor": 0.72, "metal_prod_factor": 0.90, "crystal_prod_factor": 1.12, "fuel_prod_factor": 0.84, "label_key": "planet_slot_13"},
    14: {"solar_output_factor": 0.62, "metal_prod_factor": 0.86, "crystal_prod_factor": 1.16, "fuel_prod_factor": 0.78, "label_key": "planet_slot_14"},
    15: {"solar_output_factor": 0.50, "metal_prod_factor": 0.82, "crystal_prod_factor": 1.20, "fuel_prod_factor": 0.72, "label_key": "planet_slot_15"},
}
_DEFAULT_CLIMATE_ECONOMY = _CLIMATE_ECONOMY_BY_POSITION[8]

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


ORBIT_RING_HOT = "hot"
ORBIT_RING_TEMPERATE = "temperate"
ORBIT_RING_COLD = "cold"

_ORBIT_RING_RANGES: tuple[tuple[int, int, str], ...] = (
    (1, 4, ORBIT_RING_HOT),
    (5, 10, ORBIT_RING_TEMPERATE),
    (11, 15, ORBIT_RING_COLD),
)

# Reference radii (px) at 800px stage — GC-594F multi-ring layout
ORBIT_BAND_RADIUS_REF: Dict[str, int] = {
    ORBIT_RING_HOT: 182,
    ORBIT_RING_TEMPERATE: 275,
    ORBIT_RING_COLD: 365,
    "expedition": 378,
}
GALAXY_RING_STAGE_REF_PX = 800


def orbit_band_radius_ref(band: str) -> int:
    return int(ORBIT_BAND_RADIUS_REF.get(str(band or ""), ORBIT_BAND_RADIUS_REF["expedition"]))


def galaxy_ring_orbit_radii_payload() -> Dict[str, int]:
    """Canonical orbit radii for ring view layout (presentation only)."""
    return dict(ORBIT_BAND_RADIUS_REF)


def orbit_ring_for_position(position: Any) -> str:
    """Galaxy ring zone for classic system view (presentation only)."""
    pos = _normalize_position(position)
    if pos is None:
        return ORBIT_RING_TEMPERATE
    for lo, hi, ring in _ORBIT_RING_RANGES:
        if lo <= pos <= hi:
            return ring
    return ORBIT_RING_TEMPERATE


def temperature_band_for_position(position: Any) -> str:
    """Climate band alias — same zones as :func:`orbit_ring_for_position`."""
    return orbit_ring_for_position(position)


def orbit_layout_band_for_position(position: Any) -> str:
    """Ring tier for galaxy layout (1–5 inner, 6–10 middle, 11–15 outer)."""
    pos = _normalize_position(position)
    if pos is None:
        return ORBIT_RING_HOT
    if pos <= 5:
        return ORBIT_RING_HOT
    if pos <= 10:
        return ORBIT_RING_TEMPERATE
    return ORBIT_RING_COLD


def orbit_angle_for_position(position: Any) -> float:
    """Five slots per ring, 72° spacing, ring-specific start (-90° = top)."""
    pos = _normalize_position(position)
    if pos is None:
        return -90.0
    if pos <= 5:
        return float(-90.0 + (pos - 1) * 72.0)
    if pos <= 10:
        return float(-54.0 + (pos - 6) * 72.0)
    return float(-126.0 + (pos - 11) * 72.0)


def slot_galaxy_ring_presentation(
    position: Any,
    *,
    planet_row: dict | None = None,
    occupied: bool = False,
) -> Dict[str, Any]:
    """Presentation slice for classic galaxy ring view (GC-594B)."""
    pos = _normalize_position(position) or 0
    theme = planet_theme_for_planet(planet_row if planet_row else {"position": pos})
    ident = get_planet_identity_for_position(pos)
    temp = temperature_range_for_position(pos)
    ring = orbit_ring_for_position(pos)
    layout_band = orbit_layout_band_for_position(pos)
    if occupied:
        image_relpath = str(theme.get("herocard_relpath") or "")
        image_webp_relpath = str(theme.get("herocard_webp_relpath") or "")
    else:
        image_relpath = str(theme.get("landscape_relpath") or "")
        image_webp_relpath = raster_webp_relpath(image_relpath) if image_relpath else ""
    return {
        "temperature": {
            "min_c": int(temp["min_c"]),
            "max_c": int(temp["max_c"]),
            "display": str(temp["display"]),
        },
        "temperature_band": ring,
        "orbit_ring": ring,
        "orbit_layout_band": layout_band,
        "orbit_angle_deg": orbit_angle_for_position(pos),
        "orbit_radius_ref": orbit_band_radius_ref(layout_band),
        "visual_class": str(ident["effect"]),
        "visual_effect": str(ident["effect"]),
        "planet_theme": str(ident["theme_key"]),
        "theme_group": str(ident["theme_group"]),
        "accent_color": str(ident["accent_color"]),
        "secondary_color": str(ident["secondary_color"]),
        "planet_image_relpath": image_relpath,
        "planet_image_webp_relpath": image_webp_relpath,
        "landscape_relpath": str(theme.get("landscape_relpath") or ""),
        "herocard_relpath": str(theme.get("herocard_relpath") or ""),
    }


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


def climate_economy_modifiers_for_position(position: Any) -> ClimateEconomyModifiers:
    """Production/energy multipliers keyed by galaxy slot (EffectResolver climate layer)."""
    pos = _normalize_position(position)
    if pos is None:
        return dict(_DEFAULT_CLIMATE_ECONOMY)
    row = _CLIMATE_ECONOMY_BY_POSITION.get(pos)
    if not row:
        return dict(_DEFAULT_CLIMATE_ECONOMY)
    return dict(row)


def climate_economy_display_for_position(position: Any) -> Dict[str, int]:
    """Rounded bonus percentages for UI (relative to slot-8 baseline)."""
    mods = climate_economy_modifiers_for_position(position)

    def _pct(factor: float) -> int:
        return int(round((float(factor) - 1.0) * 100))

    return {
        "position": _normalize_position(position) or 0,
        "label_key": mods["label_key"],
        "solar_bonus_pct": _pct(mods["solar_output_factor"]),
        "metal_bonus_pct": _pct(mods["metal_prod_factor"]),
        "crystal_bonus_pct": _pct(mods["crystal_prod_factor"]),
        "fuel_bonus_pct": _pct(mods["fuel_prod_factor"]),
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
    """WebP hero card path for galaxy slot 1–15 (legacy md alias)."""
    return raster_webp_relpath(herocard_static_relpath(position))


# GC-860B/C — responsive overview hero variants (widths match compress_p0_assets.py)
HEROCARD_WEBP_VARIANTS: tuple[str, ...] = ("sm", "md", "lg")
HEROCARD_WEBP_WIDTHS: dict[str, int] = {"sm": 320, "md": 560, "lg": 840}
OVERVIEW_HEROCARD_SIZES = "(max-width: 768px) 100vw, (max-width: 1280px) 90vw, 1120px"
HEROCARD_FALLBACK_WIDTH = 560
HEROCARD_FALLBACK_HEIGHT = 373


def _herocard_stem_from_png_relpath(png_relpath: str) -> str:
    rel = str(png_relpath or "").strip().lstrip("/")
    return rel.rsplit(".", 1)[0] if "." in rel else rel


def herocard_variant_webp_relpath(position: int, variant: str) -> str:
    """WebP variant path for overview hero (``sm`` | ``md`` | ``lg``)."""
    stem = _herocard_stem_from_png_relpath(herocard_static_relpath(position))
    key = str(variant or "md").strip().lower()
    if key not in HEROCARD_WEBP_WIDTHS:
        key = "md"
    return f"{stem}-{key}.webp"


def herocard_webp_srcset_parts_for_position(position: int) -> tuple[tuple[str, int], ...]:
    """``(relpath, width)`` tuples for overview ``<source srcset>``."""
    if position and int(position) >= 1:
        png_rel = herocard_static_relpath(int(position))
    else:
        png_rel = f"img/herocards/{DEFAULT_HEROCARD}"
    stem = _herocard_stem_from_png_relpath(png_rel)
    return tuple(
        (f"{stem}-{variant}.webp", HEROCARD_WEBP_WIDTHS[variant])
        for variant in HEROCARD_WEBP_VARIANTS
    )


def format_static_srcset(
    parts: tuple[tuple[str, int], ...],
    static_url,
) -> str:
    """Build a ``srcset`` attribute from static relpaths and descriptor widths."""
    return ", ".join(
        f"{static_url('static', filename=rel)} {width}w" for rel, width in parts
    )


def herocard_webp_srcset_for_position(position: int, static_url) -> str:
    """Absolute URL ``srcset`` for overview hero WebP variants."""
    return format_static_srcset(herocard_webp_srcset_parts_for_position(position), static_url)


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
        "herocard_webp_srcset_parts": herocard_webp_srcset_parts_for_position(pos),
        "herocard_webp_sizes": OVERVIEW_HEROCARD_SIZES,
        "herocard_fallback_width": HEROCARD_FALLBACK_WIDTH,
        "herocard_fallback_height": HEROCARD_FALLBACK_HEIGHT,
        "label_key": ident["label_key"],
        "climate": climate_economy_display_for_position(pos),
    }
