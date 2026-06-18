"""Read-only UI banner payload for active galactic directives (GC-720F)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..db import db
from .definitions import schema_ready
from .state import get_active_directives_for_galaxy, normalize_galaxy


def _directive_chip(
    directive_key: str,
    definition: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    key = str(directive_key or "").strip().lower()
    defn = definition if isinstance(definition, dict) else {}
    return {
        "key": key,
        "label_key": str(defn.get("label_key") or f"gd_dir_{key}_title"),
        "description_key": str(defn.get("description_key") or f"gd_dir_{key}_desc"),
    }


def build_galactic_directive_banner(
    galaxy: Any,
    *,
    conn=None,
) -> Dict[str, Any]:
    """
    Server-side banner context for overview / galaxy templates.

    Returns ``{"visible": False}`` when schema is missing or galaxy is invalid.
    """
    if normalize_galaxy(galaxy, conn=conn) is None:
        return {"visible": False}

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return {"visible": False}

        active = get_active_directives_for_galaxy(galaxy, conn=conn)
        if not active:
            return {"visible": False}

        primary = _directive_chip(
            str(active.get("primary") or ""),
            active.get("primary_definition"),
        )
        if not primary.get("key"):
            return {"visible": False}

        secondary_raw = active.get("secondary")
        secondary_def = active.get("secondary_definition")
        secondary = None
        if secondary_raw:
            chip = _directive_chip(str(secondary_raw), secondary_def)
            if chip.get("key"):
                secondary = chip

        return {
            "visible": True,
            "galaxy": int(active["galaxy"]),
            "primary": primary,
            "secondary": secondary,
            "source": str(active.get("source") or "state"),
        }
    finally:
        if own_conn:
            conn.close()
