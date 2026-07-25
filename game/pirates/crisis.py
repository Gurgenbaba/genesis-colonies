"""Pirate war crisis sync with Galactic Diplomacy (EPIC-21 / GC-P11–P12)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .heat import HEAT_THRESHOLDS, get_galaxy_heat, schema_ready as heat_schema_ready
from .log import log_pirate_action
from .settings import is_pirates_ai_enabled

logger = logging.getLogger(__name__)

PIRATE_WAR_KEY = "pirate_war"


def maybe_sync_pirate_war(conn, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Start ``pirate_war`` when heat ≥ crisis; no-op if AI off or already active."""
    started: list[int] = []
    skipped: list[int] = []
    if not is_pirates_ai_enabled(conn=conn):
        return {"started": started, "skipped": skipped, "ai_enabled": False}
    if not heat_schema_ready(conn):
        return {"started": started, "skipped": skipped, "ai_enabled": True}

    try:
        from ..galactic_diplomacy import get_active_emergency, set_active_emergency
    except Exception:
        logger.exception("galactic_diplomacy unavailable for pirate_war")
        return {"started": started, "skipped": skipped, "error": "diplomacy_unavailable"}

    crisis = int(HEAT_THRESHOLDS["crisis"])
    cur = conn.execute(
        """
        SELECT galaxy_id, heat FROM galaxy_heat
        WHERE heat >= ?
        ORDER BY heat DESC
        LIMIT 20;
        """,
        (crisis,),
    )
    for row in cur.fetchall():
        gid = int(row["galaxy_id"])
        heat = int(row["heat"] or 0)
        try:
            active = get_active_emergency(gid, conn=conn)
        except Exception:
            active = None
        if active and str(active.get("emergency_key") or "") == PIRATE_WAR_KEY:
            skipped.append(gid)
            continue
        if active and str(active.get("emergency_key") or ""):
            # Do not stomp unrelated emergencies.
            skipped.append(gid)
            continue
        try:
            set_active_emergency(
                gid,
                PIRATE_WAR_KEY,
                payload={"source": "galaxy_heat", "heat": heat},
                conn=conn,
            )
            started.append(gid)
            log_pirate_action(
                conn,
                kind="pirate_war_started",
                galaxy_id=gid,
                message=f"pirate_war emergency started heat={heat}",
                severity="warn",
                payload={"heat": heat},
            )
        except Exception:
            logger.exception("pirate_war start failed galaxy=%s", gid)
    return {"started": started, "skipped": skipped, "ai_enabled": True}


def galaxy_in_pirate_war(conn, galaxy_id: int) -> bool:
    try:
        from ..galactic_diplomacy import get_active_emergency

        active = get_active_emergency(int(galaxy_id), conn=conn)
    except Exception:
        return False
    return bool(active) and str(active.get("emergency_key") or "") == PIRATE_WAR_KEY
