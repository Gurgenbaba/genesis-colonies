"""Galactic diplomacy mechanics merge — personality, resolution, emergency (GC-721G)."""

from __future__ import annotations

import copy
import sqlite3
from typing import Any, Dict, List, Optional

from ..galactic_directives.mechanics import merge_mechanics
from .blocs import normalize_galaxy
from .emergencies import get_active_emergency
from .personality import get_galaxy_personality
from .resolutions import get_active_resolution


def merge_diplomacy_mechanics(*mechanics_maps: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge diplomacy mechanics maps in order; earlier maps win non-numeric conflicts."""
    merged: Dict[str, Any] = {}
    for chunk in mechanics_maps:
        if not chunk:
            continue
        merged = merge_mechanics(merged or None, chunk)
    return merged


def _mechanics_from_definition(defn: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not defn:
        return {}
    raw = defn.get("mechanics")
    if not isinstance(raw, dict):
        return {}
    return copy.deepcopy(raw)


def get_galaxy_diplomacy_mechanics(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Resolved diplomacy mechanics for a galaxy (personality → resolution → emergency)."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return {"galaxy": 0, "mechanics": {}, "sources": []}

    sources: List[Dict[str, str]] = []
    maps: List[Dict[str, Any]] = []

    try:
        personality = get_galaxy_personality(galaxy_id, conn=conn)
        personality_key = str(personality.get("personality_key") or "").strip()
        if personality_key:
            maps.append(_mechanics_from_definition(personality.get("definition")))
            sources.append({"type": "personality", "key": personality_key})
    except (ValueError, TypeError, RuntimeError):
        pass

    try:
        resolution = get_active_resolution(galaxy_id, conn=conn)
        if resolution:
            resolution_key = str(resolution.get("resolution_key") or "").strip()
            if resolution_key:
                maps.append(_mechanics_from_definition(resolution.get("definition")))
                sources.append({"type": "resolution", "key": resolution_key})
    except (ValueError, TypeError, RuntimeError):
        pass

    try:
        emergency = get_active_emergency(galaxy_id, conn=conn)
        if emergency:
            emergency_key = str(emergency.get("emergency_key") or "").strip()
            if emergency_key:
                maps.append(_mechanics_from_definition(emergency.get("definition")))
                sources.append({"type": "emergency", "key": emergency_key})
    except (ValueError, TypeError, RuntimeError):
        pass

    mechanics = merge_diplomacy_mechanics(*maps) if maps else {}

    return {
        "galaxy": galaxy_id,
        "mechanics": mechanics,
        "sources": sources,
    }
