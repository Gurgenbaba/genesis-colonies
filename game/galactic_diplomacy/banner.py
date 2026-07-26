"""Read-only UI banner payload for galactic diplomacy layers (GC-721I)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..db import db
from .blocs import normalize_galaxy
from .definitions import schema_ready
from .emergencies import get_active_emergency
from .personality import get_galaxy_personality
from .resolutions import get_active_resolution


def _diplomacy_chip(
    chip_type: str,
    item_key: str,
    definition: Optional[Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    key = str(item_key or "").strip().lower()
    if not key:
        return None
    defn = definition if isinstance(definition, dict) else {}
    fallback_prefix = {
        "personality": "gdp_trait",
        "resolution": "gdp_res",
        "emergency": "gdp_emergency",
    }.get(chip_type, "gdp")
    return {
        "type": chip_type,
        "key": key,
        "label_key": str(defn.get("label_key") or f"{fallback_prefix}_{key}_title"),
        "description_key": str(defn.get("description_key") or f"{fallback_prefix}_{key}_desc"),
    }


def _chip_label_key(chip_type: str) -> str:
    return {
        "personality": "gdp_banner_personality_label",
        "resolution": "gdp_banner_resolution_label",
        "emergency": "gdp_banner_emergency_label",
    }.get(chip_type, "gdp_banner_chip_label")


def build_galactic_diplomacy_banner(
    galaxy: Any,
    *,
    conn=None,
) -> Dict[str, Any]:
    """
    Server-side banner context for galaxy status templates.

    Returns ``{"visible": False}`` when schema is missing, galaxy is invalid,
    or no personality / resolution / emergency is active.
    """
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return {"visible": False}

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return {"visible": False}

        personality = None
        resolution = None
        emergency = None

        try:
            personality_state = get_galaxy_personality(galaxy_id, conn=conn)
            personality = _diplomacy_chip(
                "personality",
                str(personality_state.get("personality_key") or ""),
                personality_state.get("definition"),
            )
        except (ValueError, TypeError, RuntimeError):
            personality = None

        try:
            resolution_state = get_active_resolution(galaxy_id, conn=conn)
            if resolution_state:
                resolution = _diplomacy_chip(
                    "resolution",
                    str(resolution_state.get("resolution_key") or ""),
                    resolution_state.get("definition"),
                )
        except (ValueError, TypeError, RuntimeError):
            resolution = None

        try:
            emergency_state = get_active_emergency(galaxy_id, conn=conn)
            if emergency_state:
                emergency = _diplomacy_chip(
                    "emergency",
                    str(emergency_state.get("emergency_key") or ""),
                    emergency_state.get("definition"),
                )
        except (ValueError, TypeError, RuntimeError):
            emergency = None

        if not any((personality, resolution, emergency)):
            return {"visible": False}

        chips = []
        for chip in (personality, resolution, emergency):
            if chip:
                chip["chip_label_key"] = _chip_label_key(chip["type"])
                chips.append(chip)

        desc_chip = emergency or resolution or personality
        description_key = str(desc_chip.get("description_key") or "") if desc_chip else ""

        return {
            "visible": True,
            "galaxy": int(galaxy_id),
            "personality": personality,
            "resolution": resolution,
            "emergency": emergency,
            "chips": chips,
            "description_key": description_key,
        }
    finally:
        if own_conn:
            conn.close()
