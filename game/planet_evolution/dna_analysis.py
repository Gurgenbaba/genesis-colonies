"""Paid, bounded planet DNA analysis. Never modifies or rerolls planetary traits.

The existing planet XP/level system is the sole owner of DNA reveal milestones.
An analysis awards ordinary planet XP, at most once per colony per rolling day.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from ..db import begin_write_transaction, commit, lock_planet_for_update, rollback
from ..models import db, try_spend_resources_conn
from ..ranking import invalidate_player_score_cache
from .planet_level import add_planet_xp
from .repository import get_planet_row

SCAN_COOLDOWN_SECONDS = 24 * 60 * 60
SCAN_REWARD_XP = 120
SCAN_MIN_LEVEL = 3
SCAN_MAX_LEVEL = 30


def scan_cost(level: int) -> Dict[str, int]:
    """Linear, predictable resource price. No premium currency."""
    lvl = max(SCAN_MIN_LEVEL, min(SCAN_MAX_LEVEL, int(level)))
    return {"metal": lvl * 10_000, "crystal": lvl * 5_000}


def scan_status(planet_id: int, *, conn: sqlite3.Connection, now: Optional[float] = None) -> dict:
    """Owner-independent internal read; callers must authorize player first."""
    planet = get_planet_row(int(planet_id), conn=conn)
    if not planet:
        return {"visible": False, "reason": "planet_not_found"}
    level = int(planet.get("planet_level") or 1)
    tier = int(planet.get("dna_reveal_tier") or 0)
    if tier < 1:
        return {"visible": False, "reason": "dna_not_revealed"}
    if level >= SCAN_MAX_LEVEL:
        return {"visible": False, "reason": "max_level"}
    cur = conn.execute(
        "SELECT last_scan_at, scan_count FROM planet_dna_analysis WHERE planet_id = ?;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    last = float(row["last_scan_at"] or 0) if row else 0.0
    timestamp = float(time.time() if now is None else now)
    ready_at = last + SCAN_COOLDOWN_SECONDS if last > 0 else 0
    remaining = max(0, int(ready_at - timestamp + 0.999999))
    return {
        "visible": True,
        "ready": remaining == 0,
        "ready_at": ready_at,
        "remaining_seconds": remaining,
        "scan_count": int(row["scan_count"] or 0) if row else 0,
        "reward_xp": SCAN_REWARD_XP,
        "cost": scan_cost(level),
    }


def perform_scan(
    planet_id: int,
    *,
    player_id: int,
    now: Optional[float] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, dict]:
    """Atomic, owner-checked and cooldown-protected paid analysis action.

    Two concurrent requests serialize on the canonical planet row. All writes,
    including resources, XP and cooldown receipt, commit together or roll back.
    """
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        # Authorize through this same locked connection, not the request session
        # or a cached owner lookup. A planet switch never authorizes another owner.
        row = conn.execute(
            "SELECT id, player_id, planet_level, dna_reveal_tier FROM planets WHERE id = ?;",
            (int(planet_id),),
        ).fetchone()
        if not row or int(row["player_id"]) != int(player_id):
            rollback(conn)
            return False, "not_owner", {}
        level = int(row["planet_level"] or 1)
        if int(row["dna_reveal_tier"] or 0) < 1 or level < SCAN_MIN_LEVEL:
            rollback(conn)
            return False, "dna_not_revealed", {}
        if level >= SCAN_MAX_LEVEL:
            rollback(conn)
            return False, "max_level", {}
        timestamp = float(time.time() if now is None else now)
        receipt = conn.execute(
            "SELECT last_scan_at FROM planet_dna_analysis WHERE planet_id = ?;",
            (int(planet_id),),
        ).fetchone()
        last = float(receipt["last_scan_at"] or 0) if receipt else 0.0
        if last > 0 and timestamp < last + SCAN_COOLDOWN_SECONDS:
            rollback(conn)
            return False, "cooldown", {"ready_at": last + SCAN_COOLDOWN_SECONDS}
        cost = scan_cost(level)
        if not try_spend_resources_conn(conn, int(planet_id), cost["metal"], cost["crystal"]):
            rollback(conn)
            return False, "not_enough_resources", {"cost": cost}

        conn.execute(
            """INSERT INTO planet_dna_analysis(planet_id, last_scan_at, scan_count, last_xp_awarded)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(planet_id) DO UPDATE SET
                   last_scan_at = excluded.last_scan_at,
                   scan_count = planet_dna_analysis.scan_count + 1,
                   last_xp_awarded = excluded.last_xp_awarded;""",
            (int(planet_id), timestamp, SCAN_REWARD_XP),
        )
        # Only the canonical XP owner may cross L15/reveal DNA. No direct
        # UPDATE planet_dna or dna_reveal_tier, and no random rewards.
        result = add_planet_xp(
            int(planet_id), SCAN_REWARD_XP, conn, reason="dna_analysis", skip_diversity=True
        )
        commit(conn)
        invalidate_player_score_cache(int(player_id))
        return True, "ok", {
            "xp_gained": int(result["xp_gained"]),
            "planet_level": int(result["planet_level"]),
            "next_ready_at": timestamp + SCAN_COOLDOWN_SECONDS,
            "cost": cost,
        }
    except Exception:
        rollback(conn)
        raise
    finally:
        if own:
            conn.close()
