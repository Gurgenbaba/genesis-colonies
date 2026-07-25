"""Timed pirate infiltrations (EPIC-21 / GC-P14)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..db import table_exists
from .log import log_pirate_action

TABLE = "pirate_infiltrations"
DEFAULT_TTL_SEC = 6 * 3600
PROD_DEBUFF = 0.08  # documented magnitude; consumer via EffectResolver later


def _now() -> float:
    return time.time()


def schema_ready(conn) -> bool:
    return table_exists(conn, TABLE)


def start_infiltration(
    conn,
    *,
    planet_id: int,
    faction_key: str,
    effect_key: str = "prod_sabotage",
    magnitude: float = PROD_DEBUFF,
    ttl_sec: int = DEFAULT_TTL_SEC,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    if not schema_ready(conn):
        return {"ok": False, "error": "schema_not_ready"}
    ts = float(now if now is not None else _now())
    expires = ts + max(1, int(ttl_sec))
    cur = conn.execute(
        """
        INSERT INTO pirate_infiltrations (
            planet_id, faction_key, effect_key, magnitude, started_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (
            int(planet_id),
            str(faction_key),
            str(effect_key),
            float(magnitude),
            ts,
            expires,
        ),
    )
    infil_id = int(cur.lastrowid)
    log_pirate_action(
        conn,
        kind="infiltration_start",
        faction_key=str(faction_key),
        message=f"infiltration planet={planet_id} effect={effect_key}",
        payload={
            "infiltration_id": infil_id,
            "planet_id": int(planet_id),
            "effect_key": effect_key,
            "magnitude": float(magnitude),
            "expires_at": expires,
        },
    )
    return {
        "ok": True,
        "id": infil_id,
        "planet_id": int(planet_id),
        "expires_at": expires,
    }


def expire_due_infiltrations(conn, *, now: Optional[float] = None) -> List[int]:
    if not schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    cur = conn.execute(
        "SELECT id FROM pirate_infiltrations WHERE expires_at <= ?;",
        (ts,),
    )
    ids = [int(r["id"]) for r in cur.fetchall()]
    if ids:
        conn.execute(
            "DELETE FROM pirate_infiltrations WHERE expires_at <= ?;",
            (ts,),
        )
        for iid in ids:
            log_pirate_action(
                conn,
                kind="infiltration_expire",
                message=f"infiltration expired id={iid}",
                payload={"infiltration_id": iid},
            )
    return ids


def list_active_infiltrations(conn, *, limit: int = 50) -> List[Dict[str, Any]]:
    if not schema_ready(conn):
        return []
    limit = max(1, min(200, int(limit)))
    cur = conn.execute(
        """
        SELECT id, planet_id, faction_key, effect_key, magnitude, started_at, expires_at
        FROM pirate_infiltrations
        ORDER BY expires_at ASC
        LIMIT ?;
        """,
        (limit,),
    )
    return [dict(r) for r in cur.fetchall()]


def active_infiltration_magnitude(conn, planet_id: int, *, now: Optional[float] = None) -> float:
    """Max active sabotage magnitude for a planet (0 if none)."""
    if not schema_ready(conn):
        return 0.0
    ts = float(now if now is not None else _now())
    cur = conn.execute(
        """
        SELECT COALESCE(MAX(magnitude), 0) AS m
        FROM pirate_infiltrations
        WHERE planet_id = ? AND expires_at > ?;
        """,
        (int(planet_id), ts),
    )
    row = cur.fetchone()
    return float((row["m"] if row else 0) or 0)
