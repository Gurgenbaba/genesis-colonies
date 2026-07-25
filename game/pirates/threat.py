"""Player threat meter (EPIC-21 / GC-P06)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from ..db import table_exists

logger = logging.getLogger(__name__)

THREAT_TABLE = "player_threat"


def _now() -> float:
    return time.time()


def threat_schema_ready(conn) -> bool:
    return table_exists(conn, THREAT_TABLE)


def get_player_threat(player_id: int, *, conn) -> Dict[str, Any]:
    if not threat_schema_ready(conn):
        return {"player_id": int(player_id), "threat": 0, "components": {}}
    cur = conn.execute(
        """
        SELECT threat, components_json, updated_at
        FROM player_threat WHERE player_id = ? LIMIT 1;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    if not row:
        return {"player_id": int(player_id), "threat": 0, "components": {}}
    try:
        components = json.loads(row["components_json"] or "{}")
    except Exception:
        components = {}
    return {
        "player_id": int(player_id),
        "threat": int(row["threat"] or 0),
        "components": components if isinstance(components, dict) else {},
        "updated_at": float(row["updated_at"]) if row["updated_at"] else None,
    }


def recompute_player_threat(player_id: int, *, conn) -> Dict[str, Any]:
    """Derive 0–100 threat from ranking / combat prestige signals."""
    if not threat_schema_ready(conn):
        return get_player_threat(player_id, conn=conn)

    pid = int(player_id)
    components: Dict[str, float] = {}

    cur = conn.execute(
        """
        SELECT score_total, score_fleet, score_defense,
               COALESCE(score_destroyed, 0) AS score_destroyed
        FROM player_scores WHERE player_id = ? LIMIT 1;
        """,
        (pid,),
    )
    row = cur.fetchone()
    if row:
        total = float(row["score_total"] or 0)
        fleet = float(row["score_fleet"] or 0)
        defense = float(row["score_defense"] or 0)
        destroyed = float(row["score_destroyed"] or 0)
        # Soft log scales so midgame players climb without instantly hitting 100.
        import math

        components["empire"] = min(35.0, math.log10(max(1.0, total)) * 8.0)
        components["fleet"] = min(25.0, math.log10(max(1.0, fleet)) * 6.0)
        components["defense"] = min(15.0, math.log10(max(1.0, defense)) * 4.0)
        components["combat"] = min(25.0, math.log10(max(1.0, destroyed)) * 5.0)

    # Boss damage participation
    if table_exists(conn, "world_boss_contributions"):
        cur = conn.execute(
            "SELECT COALESCE(SUM(damage), 0) AS d FROM world_boss_contributions WHERE player_id = ?;",
            (pid,),
        )
        boss_dmg = float((cur.fetchone() or {"d": 0})["d"] or 0)
        import math

        components["boss"] = min(15.0, math.log10(max(1.0, boss_dmg)) * 3.0)

    # Pirate base kills
    if table_exists(conn, "pirate_base_claims"):
        cur = conn.execute(
            """
            SELECT COUNT(*) AS c FROM pirate_base_claims
            WHERE player_id = ? AND tier_key = 'destroy_share';
            """,
            (pid,),
        )
        kills = int((cur.fetchone() or {"c": 0})["c"] or 0)
        components["pirate_hunter"] = min(20.0, float(kills) * 4.0)

    threat = int(max(0, min(100, round(sum(components.values())))))
    now = _now()
    conn.execute(
        """
        INSERT INTO player_threat (player_id, threat, components_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            threat = excluded.threat,
            components_json = excluded.components_json,
            updated_at = excluded.updated_at;
        """,
        (pid, threat, json.dumps(components, separators=(",", ":")), now),
    )
    return {"player_id": pid, "threat": threat, "components": components, "updated_at": now}
