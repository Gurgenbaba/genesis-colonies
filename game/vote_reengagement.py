"""
Staggered vote re-engagement for inactive universe players + admin vote statistics.

Active players vote via Vote Center / postbacks (channel ``player``).
Inactive players (ranking threshold) receive at most one provider vote per cron slot,
spread across the day so votes never arrive in a single burst.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import table_exists
from .runtime_state import get_runtime_value, set_runtime_value
from .ranking import RANKING_INACTIVE_AFTER_SEC, is_player_inactive
from .vote_rewards import (
    VOTE_CHANNEL_PLAYER,
    VOTE_CHANNEL_REENGAGEMENT,
    can_process_provider_vote,
    get_provider_cooldown_status,
    get_provider_vote_end,
    list_enabled_providers,
    process_provider_vote,
    vote_channel_column_ready,
    vote_system_ready,
)

logger = logging.getLogger(__name__)

REENGAGEMENT_SLOTS_PER_DAY = 48
DEFAULT_BATCH_SIZE = 12
MAX_BATCH_SIZE = 50
_SLOT_HASH = 2654435761
_PROVIDER_HASH = 1597334677

REENGAGEMENT_BATCH_ENV = "GC_VOTE_REENGAGEMENT_BATCH"
REENGAGEMENT_ENABLED_ENV = "GC_VOTE_REENGAGEMENT_ENABLED"

VOTE_REENGAGEMENT_WORKER_KEY = "vote_reengagement_worker_last"
VOTE_REENGAGEMENT_INTERVAL_SEC = 1800  # 30 minutes — piggybacks on ranking HTTP cron


def _load_last_run_record(conn=None) -> Optional[Dict[str, Any]]:
    raw = get_runtime_value(VOTE_REENGAGEMENT_WORKER_KEY, conn=conn)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def seconds_until_vote_reengagement_allowed(
    *,
    now: Optional[float] = None,
    conn=None,
) -> float:
    """Seconds until the next vote re-engagement run is allowed (0 = ready)."""
    data = _load_last_run_record(conn=conn)
    if not data:
        return 0.0
    if not data.get("ok"):
        return 0.0
    try:
        last_at = float(data.get("at") or 0)
    except (TypeError, ValueError):
        return 0.0
    if last_at <= 0:
        return 0.0
    now_f = float(now if now is not None else time.time())
    remaining = (last_at + VOTE_REENGAGEMENT_INTERVAL_SEC) - now_f
    return max(0.0, remaining)


def record_vote_reengagement_result(result: Dict[str, Any], *, source: str, conn=None) -> None:
    payload = {
        "at": int(time.time()),
        "source": str(source or "cron"),
        "ok": bool(result.get("ok", True)),
        "created": int(result.get("created") or 0),
        "duration_ms": int(result.get("duration_ms") or 0),
        "errors": list(result.get("errors") or []),
        "skipped_interval": bool(result.get("skipped_interval")),
    }
    set_runtime_value(
        VOTE_REENGAGEMENT_WORKER_KEY,
        json.dumps(payload, ensure_ascii=False),
        conn=conn,
    )


def vote_reengagement_enabled() -> bool:
    raw = os.environ.get(REENGAGEMENT_ENABLED_ENV, "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def reengagement_batch_size() -> int:
    try:
        n = int(os.environ.get(REENGAGEMENT_BATCH_ENV, DEFAULT_BATCH_SIZE))
    except (TypeError, ValueError):
        n = DEFAULT_BATCH_SIZE
    return max(1, min(n, MAX_BATCH_SIZE))


def _current_slot(now: int, *, slots_per_day: int = REENGAGEMENT_SLOTS_PER_DAY) -> int:
    seconds_in_day = int(now) % 86400
    return (seconds_in_day * slots_per_day) // 86400


def _player_slot(user_id: int, day: int, *, slots_per_day: int = REENGAGEMENT_SLOTS_PER_DAY) -> int:
    return (int(user_id) * _SLOT_HASH + int(day)) % slots_per_day


def player_in_reengagement_slot(
    user_id: int,
    *,
    now: Optional[int] = None,
    slots_per_day: int = REENGAGEMENT_SLOTS_PER_DAY,
) -> bool:
    """True when this inactive player is scheduled for the current half-hour slot."""
    ts = int(now if now is not None else time.time())
    day = ts // 86400
    return _player_slot(user_id, day, slots_per_day=slots_per_day) == _current_slot(ts, slots_per_day=slots_per_day)


def _rotated_providers(user_id: int, providers: Sequence[Mapping[str, Any]], *, week: int) -> List[Mapping[str, Any]]:
    items = list(providers)
    if len(items) <= 1:
        return items
    offset = (int(user_id) * _PROVIDER_HASH + int(week)) % len(items)
    return items[offset:] + items[:offset]


def _pick_voteable_provider(
    user_id: int,
    providers: Sequence[Mapping[str, Any]],
    *,
    conn,
    now: int,
) -> Optional[str]:
    week = int(now) // (86400 * 7)
    for provider in _rotated_providers(user_id, providers, week=week):
        if can_process_provider_vote(user_id, provider, conn=conn, now=now):
            return str(provider["provider_key"])
    return None


def _eligible_inactive_user_ids(conn, *, now: int) -> List[int]:
    cutoff = int(now) - int(RANKING_INACTIVE_AFTER_SEC)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.id AS user_id
        FROM players p
        JOIN users u ON u.id = p.id
        WHERE COALESCE(p.last_seen, 0) > 0
          AND COALESCE(p.last_seen, 0) <= ?
          AND COALESCE(p.banned_until, 0) <= ?
        ORDER BY p.last_seen ASC, p.id ASC;
        """,
        (cutoff, int(now)),
    )
    return [int(row["user_id"]) for row in cur.fetchall()]


def run_vote_reengagement(
    *,
    conn,
    now: Optional[int] = None,
    batch_size: Optional[int] = None,
    force: bool = False,
    persist: bool = True,
    source: str = "cron",
) -> Dict[str, Any]:
    """
    Process one batch of staggered votes for inactive players.

    When force=False, skips if the last successful run was within
    VOTE_REENGAGEMENT_INTERVAL_SEC (30 min). Intended to piggyback on the
    ranking HTTP cron (every 10 min) without a separate scheduler.

    Returns summary dict suitable for cron logs and admin manual runs.
    """
    started = time.time()
    ts = int(now if now is not None else time.time())
    limit = batch_size if batch_size is not None else reengagement_batch_size()
    result: Dict[str, Any] = {
        "ok": True,
        "source": str(source or "cron"),
        "created": 0,
        "skipped_not_ready": 0,
        "skipped_wrong_slot": 0,
        "skipped_no_provider": 0,
        "skipped_interval": False,
        "errors": [],
        "slot": _current_slot(ts),
        "batch_size": int(limit),
        "force": bool(force),
    }

    if not vote_reengagement_enabled():
        result["ok"] = True
        result["skipped_disabled"] = True
        result["duration_ms"] = int((time.time() - started) * 1000)
        return result

    if not force:
        wait = seconds_until_vote_reengagement_allowed(now=ts, conn=conn)
        if wait > 0:
            result["skipped_interval"] = True
            result["next_run_in_sec"] = int(wait)
            result["duration_ms"] = int((time.time() - started) * 1000)
            logger.info(
                "vote reengagement skip guard_recent wait_sec=%s source=%s",
                int(wait),
                source,
            )
            return result

    if not vote_system_ready(conn):
        result["ok"] = False
        result["errors"].append("vote_system_unavailable")
        result["duration_ms"] = int((time.time() - started) * 1000)
        return result

    providers = list_enabled_providers(conn=conn)
    if not providers:
        result["duration_ms"] = int((time.time() - started) * 1000)
        return result

    created = 0
    for user_id in _eligible_inactive_user_ids(conn, now=ts):
        if created >= limit:
            break
        if not force and not player_in_reengagement_slot(user_id, now=ts):
            result["skipped_wrong_slot"] += 1
            continue

        provider_key = _pick_voteable_provider(user_id, providers, conn=conn, now=ts)
        if not provider_key:
            result["skipped_no_provider"] += 1
            continue

        vote_result = process_provider_vote(
            provider_key,
            user_id,
            None,
            conn=conn,
            now=ts,
            vote_channel=VOTE_CHANNEL_REENGAGEMENT,
        )
        if not vote_result.get("success"):
            if vote_result.get("error") not in ("cooldown",):
                result["errors"].append(f"user={user_id}:{vote_result.get('error')}")
            result["skipped_not_ready"] += 1
            continue
        if vote_result.get("created"):
            created += 1
            result["created"] = created
        else:
            result["skipped_not_ready"] += 1

    result["duration_ms"] = int((time.time() - started) * 1000)
    if persist and result.get("ok") and not result.get("skipped_interval"):
        record_vote_reengagement_result(result, source=source, conn=conn)
    logger.info(
        "vote reengagement source=%s created=%s slot=%s skipped_slot=%s skipped_no_provider=%s duration_ms=%s",
        source,
        created,
        result["slot"],
        result["skipped_wrong_slot"],
        result["skipped_no_provider"],
        result["duration_ms"],
    )
    return result


def _channel_expr(conn) -> str:
    if vote_channel_column_ready(conn):
        return "COALESCE(vr.vote_channel, 'player')"
    return "'player'"


def build_admin_vote_stats(*, conn, now: Optional[int] = None) -> Dict[str, Any]:
    ts = int(now if now is not None else time.time())
    week_ago = ts - 7 * 86400
    day_ago = ts - 86400
    channel_expr = _channel_expr(conn)
    out: Dict[str, Any] = {
        "ready": vote_system_ready(conn),
        "reengagement_enabled": vote_reengagement_enabled(),
        "current_slot": _current_slot(ts),
        "slots_per_day": REENGAGEMENT_SLOTS_PER_DAY,
        "inactive_threshold_sec": int(RANKING_INACTIVE_AFTER_SEC),
        "summary": {
            "votes_7d": 0,
            "player_votes_7d": 0,
            "reengagement_votes_7d": 0,
            "votes_24h": 0,
            "player_votes_24h": 0,
            "reengagement_votes_24h": 0,
            "pending_rewards": 0,
            "players_voted_7d": 0,
            "inactive_players_voted_7d": 0,
            "active_players_voted_7d": 0,
            "inactive_voteable_now": 0,
            "active_voteable_now": 0,
        },
        "providers": [],
    }
    if not out["ready"]:
        return out

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS player_votes,
            SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS reengagement_votes
        FROM vote_rewards vr
        WHERE vr.voted_at >= ?;
        """,
        (week_ago,),
    )
    row = cur.fetchone()
    out["summary"]["votes_7d"] = int(row["total"] or 0)
    out["summary"]["player_votes_7d"] = int(row["player_votes"] or 0)
    out["summary"]["reengagement_votes_7d"] = int(row["reengagement_votes"] or 0)

    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS player_votes,
            SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS reengagement_votes
        FROM vote_rewards vr
        WHERE vr.voted_at >= ?;
        """,
        (day_ago,),
    )
    row24 = cur.fetchone()
    out["summary"]["votes_24h"] = int(row24["total"] or 0)
    out["summary"]["player_votes_24h"] = int(row24["player_votes"] or 0)
    out["summary"]["reengagement_votes_24h"] = int(row24["reengagement_votes"] or 0)

    cur.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE status = 'pending';")
    out["summary"]["pending_rewards"] = int(cur.fetchone()["c"] or 0)

    cur.execute(
        """
        SELECT COUNT(DISTINCT vr.user_id) AS c
        FROM vote_rewards vr
        WHERE vr.voted_at >= ?;
        """,
        (week_ago,),
    )
    out["summary"]["players_voted_7d"] = int(cur.fetchone()["c"] or 0)

    inactive_cutoff = ts - int(RANKING_INACTIVE_AFTER_SEC)
    cur.execute(
        """
        SELECT COUNT(DISTINCT vr.user_id) AS c
        FROM vote_rewards vr
        JOIN players p ON p.id = vr.user_id
        WHERE vr.voted_at >= ?
          AND COALESCE(p.last_seen, 0) <= ?;
        """,
        (week_ago, inactive_cutoff),
    )
    out["summary"]["inactive_players_voted_7d"] = int(cur.fetchone()["c"] or 0)
    out["summary"]["active_players_voted_7d"] = max(
        0,
        out["summary"]["players_voted_7d"] - out["summary"]["inactive_players_voted_7d"],
    )

    providers = list_enabled_providers(conn=conn)
    provider_stats: List[Dict[str, Any]] = []
    for provider in providers:
        key = str(provider["provider_key"])
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS player_votes,
                SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS reengagement_votes
            FROM vote_rewards vr
            WHERE vr.provider = ? AND vr.voted_at >= ?;
            """,
            (key, week_ago),
        )
        prow = cur.fetchone()
        provider_stats.append(
            {
                "provider_key": key,
                "display_name": str(provider["display_name"]),
                "votes_7d": int(prow["total"] or 0),
                "player_votes_7d": int(prow["player_votes"] or 0),
                "reengagement_votes_7d": int(prow["reengagement_votes"] or 0),
                "cooldown_sec": int(provider.get("cooldown_sec") or 0),
            }
        )
    out["providers"] = provider_stats

    cur.execute(
        """
        SELECT p.id AS user_id, COALESCE(p.last_seen, 0) AS last_seen
        FROM players p
        JOIN users u ON u.id = p.id
        WHERE COALESCE(p.banned_until, 0) <= ?;
        """,
        (ts,),
    )
    inactive_voteable = 0
    active_voteable = 0
    for prow in cur.fetchall():
        uid = int(prow["user_id"])
        inactive = is_player_inactive({"last_seen": int(prow["last_seen"] or 0)}, now=ts)
        voteable = any(
            can_process_provider_vote(uid, p, conn=conn, now=ts) for p in providers
        )
        if not voteable:
            continue
        if inactive:
            inactive_voteable += 1
        else:
            active_voteable += 1
    out["summary"]["inactive_voteable_now"] = inactive_voteable
    out["summary"]["active_voteable_now"] = active_voteable
    return out


def search_admin_vote_players(
    *,
    conn,
    q: str = "",
    activity: str = "all",
    limit: int = 50,
    offset: int = 0,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    ts = int(now if now is not None else time.time())
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    inactive_cutoff = ts - int(RANKING_INACTIVE_AFTER_SEC)
    channel_expr = _channel_expr(conn)

    where: List[str] = ["COALESCE(p.banned_until, 0) <= ?"]
    params: List[Any] = [ts]
    q_norm = str(q or "").strip()
    if q_norm:
        where.append("(u.username LIKE ? OR p.name LIKE ? OR CAST(p.id AS TEXT) = ?)")
        like = f"%{q_norm}%"
        params.extend([like, like, q_norm])

    activity_norm = str(activity or "all").strip().lower()
    if activity_norm == "active":
        where.append("COALESCE(p.last_seen, 0) > ?")
        params.append(inactive_cutoff)
    elif activity_norm == "inactive":
        where.append("(COALESCE(p.last_seen, 0) <= ? OR COALESCE(p.last_seen, 0) = 0)")
        params.append(inactive_cutoff)

    where_sql = " AND ".join(where)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM players p
        JOIN users u ON u.id = p.id
        WHERE {where_sql};
        """,
        tuple(params),
    )
    total = int(cur.fetchone()["c"] or 0)

    cur.execute(
        f"""
        SELECT p.id AS user_id, u.username, p.name AS player_name,
               COALESCE(p.last_seen, 0) AS last_seen
        FROM players p
        JOIN users u ON u.id = p.id
        WHERE {where_sql}
        ORDER BY p.last_seen DESC, p.id ASC
        LIMIT ? OFFSET ?;
        """,
        tuple(params) + (lim, off),
    )
    providers = list_enabled_providers(conn=conn)
    players: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        uid = int(row["user_id"])
        last_seen = int(row["last_seen"] or 0)
        inactive = is_player_inactive({"last_seen": last_seen}, now=ts)
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS player_votes,
                SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS reengagement_votes,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_rewards
            FROM vote_rewards vr
            WHERE vr.user_id = ?;
            """,
            (uid,),
        )
        vrow = cur.fetchone()
        provider_rows: List[Dict[str, Any]] = []
        for provider in providers:
            pkey = str(provider["provider_key"])
            cd = get_provider_cooldown_status(uid, provider, conn=conn, now=ts)
            cur.execute(
                f"""
                SELECT voted_at, {channel_expr} AS vote_channel
                FROM vote_rewards vr
                WHERE vr.user_id = ? AND vr.provider = ?
                ORDER BY vr.voted_at DESC
                LIMIT 1;
                """,
                (uid, pkey),
            )
            last = cur.fetchone()
            provider_rows.append(
                {
                    "provider_key": pkey,
                    "display_name": str(provider["display_name"]),
                    "last_vote_at": int(last["voted_at"]) if last and last["voted_at"] else None,
                    "last_channel": str(last["vote_channel"]) if last else None,
                    "next_vote_at": cd["next_vote_at"],
                    "can_vote": bool(cd["can_vote"]),
                    "cooldown_remaining_sec": int(cd["cooldown_remaining_sec"]),
                    "vote_end": cd.get("vote_end"),
                }
            )
        players.append(
            {
                "user_id": uid,
                "username": str(row["username"]),
                "player_name": str(row["player_name"] or row["username"]),
                "last_seen": last_seen,
                "activity": "inactive" if inactive else "active",
                "reengagement_slot": _player_slot(uid, ts // 86400),
                "total_votes": int(vrow["total"] or 0),
                "player_votes": int(vrow["player_votes"] or 0),
                "reengagement_votes": int(vrow["reengagement_votes"] or 0),
                "pending_rewards": int(vrow["pending_rewards"] or 0),
                "providers": provider_rows,
            }
        )

    return {
        "ok": True,
        "total": total,
        "limit": lim,
        "offset": off,
        "players": players,
        "current_slot": _current_slot(ts),
    }
