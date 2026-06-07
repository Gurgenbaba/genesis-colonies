"""Overview / cross-page planet identity teaser payloads."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional

from .bootstrap import ensure_planet_evolution, planet_evolution_needs_bootstrap
from .dashboard import build_identity_teaser
from .repository import evolution_schema_ready, get_context_planet
from .specialization import eligible_specialization_keys


def get_overview_planet_teaser(
    player_id: int,
    *,
    metal: float = 0,
    crystal: float = 0,
    conn=None,
) -> Dict[str, Any]:
    """Lightweight planet-identity summary for the Overview page."""
    own = conn is None
    if own:
        from ..models import db

        conn = db()
    try:
        if not evolution_schema_ready(conn):
            return {"visible": False}

        planet = get_context_planet(int(player_id), conn=conn)
        planet_id = int(planet["id"])
        try:
            ensure_planet_evolution(planet_id, conn)
        except sqlite3.OperationalError:
            if planet_evolution_needs_bootstrap(planet_id, conn):
                raise
        eligible = eligible_specialization_keys(planet_id, conn=conn)

        from .planet_level import xp_threshold_for_level
        from .constants import MAX_PLANET_LEVEL
        from .scoring import compute_single_planet_score

        level = int(planet.get("planet_level") or 1)
        xp = int(planet.get("planet_xp") or 0)
        next_threshold = xp_threshold_for_level(level + 1) if level < MAX_PLANET_LEVEL else xp
        prev_threshold = xp_threshold_for_level(level)
        xp_in_level = max(0, xp - prev_threshold)
        xp_span = max(1, next_threshold - prev_threshold)
        xp_pct = max(0, min(100, int(round(100.0 * xp_in_level / xp_span))))

        teaser = build_identity_teaser(
            planet=planet,
            eligible_specs=eligible,
            xp_pct=xp_pct,
            planet_score=compute_single_planet_score(planet_id, conn=conn),
        )
        if teaser.get("visible"):
            teaser["balances"] = {
                "metal": max(0, int(metal)),
                "crystal": max(0, int(crystal)),
            }
        return teaser
    finally:
        if own:
            conn.close()
