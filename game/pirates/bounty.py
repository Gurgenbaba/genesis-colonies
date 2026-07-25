"""Per-faction player bounty (EPIC-21 / GC-P10).

Bounty rises when players damage or destroy pirate bases.
High bounty biases that faction's raid brain toward revenge.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..db import table_exists

BOUNTY_TABLE = "player_bounty"
DAMAGE_BOUNTY_PER_1K_HP = 25
DESTROY_BOUNTY_BASE = 500
DESTROY_BOUNTY_PER_STRENGTH = 400


def _now() -> float:
    return time.time()


def bounty_schema_ready(conn) -> bool:
    return table_exists(conn, BOUNTY_TABLE)


def get_player_bounty(
    player_id: int,
    faction_key: str,
    *,
    conn,
) -> Dict[str, Any]:
    if not bounty_schema_ready(conn):
        return {
            "player_id": int(player_id),
            "faction_key": str(faction_key),
            "credits": 0,
            "kills": 0,
        }
    cur = conn.execute(
        """
        SELECT credits, kills, updated_at
        FROM player_bounty
        WHERE player_id = ? AND faction_key = ?
        LIMIT 1;
        """,
        (int(player_id), str(faction_key)),
    )
    row = cur.fetchone()
    if not row:
        return {
            "player_id": int(player_id),
            "faction_key": str(faction_key),
            "credits": 0,
            "kills": 0,
        }
    return {
        "player_id": int(player_id),
        "faction_key": str(faction_key),
        "credits": int(row["credits"] or 0),
        "kills": int(row["kills"] or 0),
        "updated_at": float(row["updated_at"]) if row["updated_at"] else None,
    }


def list_player_bounties(player_id: int, *, conn) -> List[Dict[str, Any]]:
    if not bounty_schema_ready(conn):
        return []
    cur = conn.execute(
        """
        SELECT faction_key, credits, kills, updated_at
        FROM player_bounty
        WHERE player_id = ? AND credits > 0
        ORDER BY credits DESC;
        """,
        (int(player_id),),
    )
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        out.append(
            {
                "player_id": int(player_id),
                "faction_key": row["faction_key"],
                "credits": int(row["credits"] or 0),
                "kills": int(row["kills"] or 0),
                "updated_at": float(row["updated_at"]) if row["updated_at"] else None,
            }
        )
    return out


def add_player_bounty(
    conn,
    player_id: int,
    faction_key: str,
    *,
    credits: int = 0,
    kills: int = 0,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Increment bounty; creates row if missing. Returns new totals."""
    if not bounty_schema_ready(conn):
        return get_player_bounty(player_id, faction_key, conn=conn)
    pid = int(player_id)
    fk = str(faction_key)
    c_add = max(0, int(credits))
    k_add = max(0, int(kills))
    if c_add <= 0 and k_add <= 0:
        return get_player_bounty(pid, fk, conn=conn)
    ts = float(now if now is not None else _now())
    conn.execute(
        """
        INSERT INTO player_bounty (player_id, faction_key, credits, kills, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(player_id, faction_key) DO UPDATE SET
            credits = player_bounty.credits + excluded.credits,
            kills = player_bounty.kills + excluded.kills,
            updated_at = excluded.updated_at;
        """,
        (pid, fk, c_add, k_add, ts),
    )
    return get_player_bounty(pid, fk, conn=conn)


def bounty_for_damage(damage: int) -> int:
    dmg = max(0, int(damage))
    return int((dmg // 1000) * DAMAGE_BOUNTY_PER_1K_HP)


def bounty_for_destroy(strength: int, *, share: float = 1.0) -> int:
    s = max(1, int(strength))
    raw = DESTROY_BOUNTY_BASE + DESTROY_BOUNTY_PER_STRENGTH * s
    return max(0, int(round(raw * max(0.0, min(1.0, float(share))))))
