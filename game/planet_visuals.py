"""Planet visuals — landscape backgrounds keyed by galaxy slot (position 1–15)."""

from __future__ import annotations

from typing import Dict

DEFAULT_LANDSCAPE = "normaltempplanet01-h.jpg"

_LANDSCAPE_BY_POSITION: Dict[int, str] = {
    1: "trockenplanet01-h.jpg",
    2: "trockenplanet04-h.jpg",
    3: "trockenplanet06-h.jpg",
    4: "trockenplanet08-h.jpg",
    5: "normaltempplanet04-h.jpg",
    6: "normaltempplanet03-h.jpg",
    7: "normaltempplanet01-h.jpg",
    8: "wasserplanet07-h.jpg",
    9: "wasserplanet08-h.jpg",
    10: "dschungelplanet08-h.jpg",
    11: "dschungelplanet07-h.jpg",
    12: "gasplanet05-h.jpg",
    13: "eisplanet04-h.jpg",
    14: "eisplanet06-h.jpg",
    15: "eisplanet09-h.jpg",
}


def get_landscape_for_position(position: int) -> str:
    """Return landscape filename for galaxy slot 1–15; fallback for invalid values."""
    try:
        pos = int(position)
    except (TypeError, ValueError):
        return DEFAULT_LANDSCAPE
    if pos < 1 or pos > 15:
        return DEFAULT_LANDSCAPE
    return _LANDSCAPE_BY_POSITION.get(pos, DEFAULT_LANDSCAPE)


def landscape_static_relpath(position: int) -> str:
    """Relative static path under ``static/`` for the given galaxy slot."""
    return f"img/landscapes/{get_landscape_for_position(position)}"


def landscape_filename_for_planet(planet: dict | None) -> str:
    """Resolve landscape filename from a planet row (uses ``position`` when present)."""
    if not planet:
        return DEFAULT_LANDSCAPE
    position = planet.get("position")
    if position is None or position == "":
        return DEFAULT_LANDSCAPE
    return get_landscape_for_position(int(position))
