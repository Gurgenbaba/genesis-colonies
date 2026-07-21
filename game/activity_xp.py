"""
Activity XP — small planet evolution rewards for routine gameplay actions.

Credits ``planet_xp`` today; structured so ``account_xp`` / battlepass can hook in later.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, Mapping, Optional

from .models import get_homeworld

SOURCE_EXPEDITION = "expedition"
SOURCE_EXPEDITION_BONUS = "expedition_bonus"
SOURCE_SPY = "spy"
SOURCE_RECYCLE = "recycle"
SOURCE_COLONIZE = "colonize"
SOURCE_BUILDING_FINISH = "building_finish"
SOURCE_ACCOUNT_RESEARCH_FINISH = "account_research_finish"
SOURCE_SHIPYARD_FINISH = "shipyard_finish"
SOURCE_DEFENSE_FINISH = "defense_finish"

EXPEDITION_BONUS_EVERY = 10
EXPEDITION_BONUS_AMOUNT = 25

_SOURCE_CONFIG: Dict[str, Dict[str, Any]] = {
    SOURCE_EXPEDITION: {"amount": 5, "daily_cap": None},
    SOURCE_EXPEDITION_BONUS: {"amount": EXPEDITION_BONUS_AMOUNT, "daily_cap": None},
    SOURCE_SPY: {"amount": 2, "daily_cap": 20},
    SOURCE_RECYCLE: {"amount": 3, "daily_cap": 30},
    SOURCE_COLONIZE: {"amount": 100, "daily_cap": None},
    SOURCE_BUILDING_FINISH: {"amount": 1, "daily_cap": 30},
    SOURCE_ACCOUNT_RESEARCH_FINISH: {"amount": 10, "daily_cap": None},
    SOURCE_SHIPYARD_FINISH: {"amount": 1, "daily_cap": 30},
    SOURCE_DEFENSE_FINISH: {"amount": 1, "daily_cap": 30},
}


def day_bucket(ts: Optional[float] = None) -> int:
    return int(float(ts if ts is not None else time.time()) // 86400)


def _table_ready(conn: sqlite3.Connection) -> bool:
    from .db import table_exists

    return bool(table_exists(conn, "activity_xp_log"))


def _resolve_idempotency_key(
    source_key: str,
    metadata: Optional[Mapping[str, Any]],
    explicit: Optional[str],
) -> Optional[str]:
    if explicit:
        return str(explicit).strip() or None
    if not metadata:
        return None
    for key in ("idempotency_key", "fleet_id", "movement_id", "queue_job_id", "job_id"):
        if key in metadata and metadata[key] is not None:
            val = metadata[key]
            if key in ("fleet_id", "movement_id"):
                return f"{source_key}:fleet:{int(val)}"
            if key in ("queue_job_id", "job_id"):
                return f"{source_key}:job:{int(val)}"
    return None


def _daily_granted(conn: sqlite3.Connection, player_id: int, source_key: str, bucket: int) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM activity_xp_log
        WHERE player_id = ? AND source_key = ? AND day_bucket = ?;
        """,
        (int(player_id), str(source_key), int(bucket)),
    )
    row = cur.fetchone()
    return int(row["total"] if row else 0)


def _planet_owned_by(player_id: int, planet_id: int, conn: sqlite3.Connection) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (int(planet_id), int(player_id)),
    )
    return cur.fetchone() is not None


def _apply_planet_xp(planet_id: int, amount: int, conn: sqlite3.Connection, *, reason: str) -> Dict[str, Any]:
    from .planet_evolution.planet_level import add_planet_xp

    return add_planet_xp(int(planet_id), int(amount), conn, reason=reason, skip_diversity=True)


def _apply_account_xp(_player_id: int, _amount: int, *, conn: sqlite3.Connection) -> None:
    """Future hook: players.account_xp / battlepass_xp."""
    del _player_id, _amount, conn


def grant_activity_xp(
    player_id: int,
    planet_id: int,
    source_key: str,
    amount: Optional[int] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    *,
    conn: sqlite3.Connection,
    idempotency_key: Optional[str] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Grant Activity XP to a planet if caps/idempotency allow.

    Returns dict with ``granted`` (bool), ``reason``, ``amount``, optional ``planet_xp`` payload.
    """
    src = str(source_key or "").strip()
    cfg = _SOURCE_CONFIG.get(src)
    if not cfg:
        return {"granted": False, "reason": "unknown_source", "amount": 0, "source_key": src}

    if not _table_ready(conn):
        return {"granted": False, "reason": "table_missing", "amount": 0, "source_key": src}

    pid = int(player_id)
    plid = int(planet_id)
    if not _planet_owned_by(pid, plid, conn):
        return {"granted": False, "reason": "planet_not_owned", "amount": 0, "source_key": src}

    grant_amount = int(cfg["amount"] if amount is None else amount)
    if grant_amount <= 0:
        return {"granted": False, "reason": "zero_amount", "amount": 0, "source_key": src}

    ts = float(now if now is not None else time.time())
    bucket = day_bucket(ts)
    idem = _resolve_idempotency_key(src, metadata, idempotency_key)
    meta = dict(metadata or {})

    cur = conn.cursor()
    if idem:
        cur.execute(
            "SELECT id FROM activity_xp_log WHERE idempotency_key = ? LIMIT 1;",
            (idem,),
        )
        if cur.fetchone():
            return {
                "granted": False,
                "reason": "idempotent_duplicate",
                "amount": 0,
                "source_key": src,
                "idempotency_key": idem,
            }

    daily_cap = cfg.get("daily_cap")
    if daily_cap is not None:
        already = _daily_granted(conn, pid, src, bucket)
        if already >= int(daily_cap):
            return {
                "granted": False,
                "reason": "daily_cap",
                "amount": 0,
                "source_key": src,
                "daily_cap": int(daily_cap),
                "daily_granted": already,
            }
        grant_amount = min(grant_amount, int(daily_cap) - already)
        if grant_amount <= 0:
            return {
                "granted": False,
                "reason": "daily_cap",
                "amount": 0,
                "source_key": src,
                "daily_cap": int(daily_cap),
                "daily_granted": already,
            }

    reason = f"activity_xp:{src}"
    planet_result = _apply_planet_xp(plid, grant_amount, conn, reason=reason)
    _apply_account_xp(pid, grant_amount, conn=conn)

    meta_json = json.dumps(meta, separators=(",", ":"), sort_keys=True) if meta else None
    cur.execute(
        """
        INSERT INTO activity_xp_log
            (player_id, planet_id, source_key, amount, metadata_json, idempotency_key, day_bucket, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (pid, plid, src, int(grant_amount), meta_json, idem, int(bucket), ts),
    )

    result: Dict[str, Any] = {
        "granted": True,
        "reason": "ok",
        "amount": int(grant_amount),
        "source_key": src,
        "planet_xp": planet_result,
        "idempotency_key": idem,
        "day_bucket": bucket,
    }

    if src == SOURCE_EXPEDITION:
        bonus = _maybe_grant_expedition_bonus(pid, plid, conn, bucket=bucket, now=ts)
        if bonus.get("granted"):
            result["expedition_bonus"] = bonus

    return result


def _maybe_grant_expedition_bonus(
    player_id: int,
    planet_id: int,
    conn: sqlite3.Connection,
    *,
    bucket: int,
    now: float,
) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM activity_xp_log
        WHERE player_id = ? AND source_key = ? AND day_bucket = ?;
        """,
        (int(player_id), SOURCE_EXPEDITION, int(bucket)),
    )
    count = int(cur.fetchone()["c"])
    if count <= 0 or count % EXPEDITION_BONUS_EVERY != 0:
        return {"granted": False, "reason": "no_bonus", "expedition_count": count}

    milestone = count // EXPEDITION_BONUS_EVERY
    idem = f"{SOURCE_EXPEDITION_BONUS}:{player_id}:{bucket}:{milestone}"
    return grant_activity_xp(
        int(player_id),
        int(planet_id),
        SOURCE_EXPEDITION_BONUS,
        metadata={"expedition_count": count, "milestone": milestone},
        conn=conn,
        idempotency_key=idem,
        now=now,
    )


def grant_fleet_activity_xp(
    player_id: int,
    planet_id: int,
    source_key: str,
    movement_id: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    return grant_activity_xp(
        int(player_id),
        int(planet_id),
        str(source_key),
        metadata={"fleet_id": int(movement_id)},
        conn=conn,
        now=now,
    )


def grant_queue_job_activity_xp(
    player_id: int,
    planet_id: int,
    source_key: str,
    job_id: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    return grant_activity_xp(
        int(player_id),
        int(planet_id),
        str(source_key),
        metadata={"job_id": int(job_id)},
        conn=conn,
        now=now,
    )


def grant_account_research_activity_xp(
    player_id: int,
    job_id: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    hw = get_homeworld(int(player_id), conn=conn) or {}
    planet_id = int(hw.get("id") or 0)
    if not planet_id:
        return {"granted": False, "reason": "no_homeworld", "amount": 0}
    return grant_queue_job_activity_xp(
        int(player_id),
        planet_id,
        SOURCE_ACCOUNT_RESEARCH_FINISH,
        int(job_id),
        conn=conn,
        now=now,
    )


def get_activity_xp_dashboard(
    player_id: int,
    planet_id: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Player-facing summary for Planet Evolution UI."""
    if not _table_ready(conn):
        return {"visible": False}

    ts = float(now if now is not None else time.time())
    bucket = day_bucket(ts)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM activity_xp_log
        WHERE planet_id = ? AND day_bucket = ?;
        """,
        (int(planet_id), int(bucket)),
    )
    today_on_planet = int(cur.fetchone()["total"])

    cur.execute(
        """
        SELECT COUNT(*) AS c FROM activity_xp_log
        WHERE player_id = ? AND source_key = ? AND day_bucket = ?;
        """,
        (int(player_id), SOURCE_EXPEDITION, int(bucket)),
    )
    expedition_count = int(cur.fetchone()["c"])
    mod = expedition_count % EXPEDITION_BONUS_EVERY
    expedition_progress = mod if mod else (EXPEDITION_BONUS_EVERY if expedition_count else 0)

    return {
        "visible": True,
        "today_earned": today_on_planet,
        "expedition_count_today": expedition_count,
        "expedition_progress": expedition_progress,
        "expedition_bonus_every": EXPEDITION_BONUS_EVERY,
        "day_bucket": bucket,
    }
