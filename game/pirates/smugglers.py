"""Ephemeral smuggler contacts (EPIC-21 / GC-P15)."""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Optional

from ..db import table_exists
from .heat import HEAT_THRESHOLDS, schema_ready as heat_schema_ready
from .log import log_pirate_action
from .settings import is_pirates_ai_enabled

TABLE = "smuggler_contacts"
TTL_SEC = 4 * 3600
MAX_LIVE = 8


def _now() -> float:
    return time.time()


def schema_ready(conn) -> bool:
    return table_exists(conn, TABLE)


def list_live_smugglers(conn, *, limit: int = 40) -> List[Dict[str, Any]]:
    if not schema_ready(conn):
        return []
    limit = max(1, min(100, int(limit)))
    cur = conn.execute(
        """
        SELECT id, galaxy, system, position, status, offer_json, spawned_at, expires_at
        FROM smuggler_contacts
        WHERE status = 'active'
        ORDER BY spawned_at DESC
        LIMIT ?;
        """,
        (limit,),
    )
    out = []
    for row in cur.fetchall():
        try:
            offer = json.loads(row["offer_json"] or "{}")
        except Exception:
            offer = {}
        out.append(
            {
                "id": int(row["id"]),
                "galaxy": int(row["galaxy"]),
                "system": int(row["system"]),
                "position": int(row["position"]),
                "status": row["status"],
                "offer": offer if isinstance(offer, dict) else {},
                "spawned_at": float(row["spawned_at"]),
                "expires_at": float(row["expires_at"]),
            }
        )
    return out


def expire_due_smugglers(conn, *, now: Optional[float] = None) -> List[int]:
    if not schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    cur = conn.execute(
        """
        SELECT id FROM smuggler_contacts
        WHERE status = 'active' AND expires_at <= ?;
        """,
        (ts,),
    )
    ids = [int(r["id"]) for r in cur.fetchall()]
    if ids:
        conn.execute(
            """
            UPDATE smuggler_contacts SET status = 'expired'
            WHERE status = 'active' AND expires_at <= ?;
            """,
            (ts,),
        )
    return ids


def maybe_spawn_smugglers(conn, *, now: Optional[float] = None) -> List[int]:
    """Spawn up to 1 smuggler contact in a hot galaxy when AI is on."""
    if not schema_ready(conn) or not is_pirates_ai_enabled(conn=conn):
        return []
    if not heat_schema_ready(conn):
        return []
    ts = float(now if now is not None else _now())
    live = list_live_smugglers(conn, limit=MAX_LIVE + 1)
    if len(live) >= MAX_LIVE:
        return []
    cur = conn.execute(
        """
        SELECT galaxy_id, heat FROM galaxy_heat
        WHERE heat >= ?
        ORDER BY heat DESC
        LIMIT 5;
        """,
        (HEAT_THRESHOLDS["raids"],),
    )
    rows = cur.fetchall()
    if not rows:
        return []
    rng = random.Random(int(ts) ^ int(rows[0]["galaxy_id"]))
    row = rng.choice(rows)
    g = int(row["galaxy_id"])
    s = rng.randint(1, 499)
    p = rng.randint(1, 15)
    offer = {
        "metal": 25_000 + rng.randint(0, 50_000),
        "crystal": 15_000 + rng.randint(0, 30_000),
        "risk": "medium",
    }
    cur = conn.execute(
        """
        INSERT INTO smuggler_contacts (
            galaxy, system, position, status, offer_json, spawned_at, expires_at
        ) VALUES (?, ?, ?, 'active', ?, ?, ?);
        """,
        (g, s, p, json.dumps(offer, separators=(",", ":")), ts, ts + TTL_SEC),
    )
    sid = int(cur.lastrowid)
    log_pirate_action(
        conn,
        kind="smuggler_spawn",
        galaxy_id=g,
        message=f"smuggler [{g}:{s}:{p}]",
        payload={"smuggler_id": sid, "offer": offer},
    )
    return [sid]
