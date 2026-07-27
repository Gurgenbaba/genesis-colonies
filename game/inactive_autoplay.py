"""Inactive autoplay — living dormant empires (EPIC-26 / GC-2601).

Sticky roster: once woken, accounts keep building/researching/defense on every
fleet-cron slice (not only during a short session window). Presence stays fresh
so Ranking/Galaxy look alive. Never fleets or expeditions.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .auto_empire import plan_passive_planet_tick
from .db import column_exists
from .ranking import RANKING_INACTIVE_AFTER_SEC
from .runtime_state import get_runtime_value, set_runtime_value

logger = logging.getLogger(__name__)

ENABLED_RUNTIME_KEY = "inactive_autoplay_enabled"
WORKER_LAST_KEY = "inactive_autoplay_worker_last"
ROSTER_KEY = "inactive_autoplay_roster"
SESSIONS_KEY = "inactive_autoplay_sessions"  # legacy merge
CURSOR_KEY = "inactive_autoplay_cursor"
TICK_CURSOR_KEY = "inactive_autoplay_tick_cursor"

# Soft caps so queues turn over on fleet-cron cadence (still slower than pirate 90s).
INACTIVE_BUILD_DURATION_CAP = 900  # 15 min
INACTIVE_RESEARCH_DURATION_CAP = 1200  # 20 min
INACTIVE_CHAIN_LIMIT = 3

# Revisit: pull stale accounts onto sticky roster.
DEFAULT_REVISIT_SEC = 36 * 3600  # 36h — stay under 3-day inactive badge
DEFAULT_WAKE_INTERVAL_SEC = 10 * 60
DEFAULT_BATCH = 3
DEFAULT_MAX_ROSTER = 40
DEFAULT_TICK_PER_CRON = 8

ENABLED_ENV = "GC_INACTIVE_AUTOPLAY_ENABLED"
BATCH_ENV = "GC_INACTIVE_AUTOPLAY_BATCH"
INTERVAL_ENV = "GC_INACTIVE_AUTOPLAY_INTERVAL_SEC"
REVISIT_ENV = "GC_INACTIVE_AUTOPLAY_REVISIT_SEC"
MAX_ROSTER_ENV = "GC_INACTIVE_AUTOPLAY_MAX_SESSIONS"  # keep env name for ops
TICK_ENV = "GC_INACTIVE_AUTOPLAY_TICK_PER_CRON"
# Legacy env still accepted for docs; sessions are sticky now.
SESSION_ENV = "GC_INACTIVE_AUTOPLAY_SESSION_SEC"


def _now() -> float:
    return time.time()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def wake_batch_size() -> int:
    return max(1, min(8, _env_int(BATCH_ENV, DEFAULT_BATCH)))


def wake_interval_sec() -> float:
    return float(max(60, _env_int(INTERVAL_ENV, DEFAULT_WAKE_INTERVAL_SEC)))


def session_duration_sec() -> float:
    """Deprecated sticky model — kept for callers/tests."""
    return float(max(600, _env_int(SESSION_ENV, 24 * 3600)))


def revisit_sec() -> float:
    return float(max(3600, _env_int(REVISIT_ENV, DEFAULT_REVISIT_SEC)))


def max_concurrent_sessions() -> int:
    """Roster size cap (env name kept as MAX_SESSIONS for ops compatibility)."""
    return max(4, min(80, _env_int(MAX_ROSTER_ENV, DEFAULT_MAX_ROSTER)))


def tick_per_cron() -> int:
    return max(1, min(20, _env_int(TICK_ENV, DEFAULT_TICK_PER_CRON)))


def is_inactive_autoplay_enabled(*, conn=None) -> bool:
    """Soft-On via runtime_state; env GC_INACTIVE_AUTOPLAY_ENABLED=0 forces off."""
    env = os.environ.get(ENABLED_ENV)
    if env is not None and str(env).strip().lower() in {"0", "false", "no", "off"}:
        return False
    raw = get_runtime_value(ENABLED_RUNTIME_KEY, conn=conn)
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def set_inactive_autoplay_enabled(enabled: bool, *, conn=None) -> None:
    set_runtime_value(
        ENABLED_RUNTIME_KEY, "1" if enabled else "0", conn=conn
    )


def _load_json(key: str, *, conn=None) -> Any:
    raw = get_runtime_value(key, conn=conn)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _save_json(key: str, value: Any, *, conn=None) -> None:
    set_runtime_value(key, json.dumps(value), conn=conn)


def _touch_presence(conn, player_id: int, *, now: float) -> None:
    try:
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (float(now), int(player_id)),
        )
    except Exception:
        logger.exception("inactive autoplay last_seen touch failed player=%s", player_id)


def _is_excluded_ai(conn, player_id: int) -> bool:
    try:
        from .pirates.accounts import is_pirate_bot_player

        if is_pirate_bot_player(int(player_id), conn=conn):
            return True
    except Exception:
        pass
    try:
        from .combat_balance_bots import is_combat_balance_bot_player

        if is_combat_balance_bot_player(int(player_id), conn=conn):
            return True
    except Exception:
        pass
    return False


def _vacation_active(row: Mapping[str, Any]) -> bool:
    try:
        return bool(int(row["vacation_mode_active"] or 0))
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def _player_vacation(conn, player_id: int) -> bool:
    if not column_exists(conn, "players", "vacation_mode_active"):
        return False
    row = conn.execute(
        "SELECT COALESCE(vacation_mode_active, 0) AS v FROM players WHERE id = ?;",
        (int(player_id),),
    ).fetchone()
    if not row:
        return True
    return bool(int(row["v"] or 0))


def list_dormant_candidates(
    conn,
    *,
    now: Optional[float] = None,
    exclude_ids: Optional[Set[int]] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """Humans whose presence is stale (revisit window) or already inactive."""
    ts = float(now if now is not None else _now())
    cutoff = ts - revisit_sec()
    excluded = {int(x) for x in (exclude_ids or set())}
    vac_select = (
        "COALESCE(vacation_mode_active, 0)"
        if column_exists(conn, "players", "vacation_mode_active")
        else "0"
    )
    cur = conn.execute(
        f"""
        SELECT id AS player_id,
               last_seen,
               {vac_select} AS vacation_mode_active
        FROM players
        WHERE (last_seen IS NULL OR last_seen < ?)
        ORDER BY CASE WHEN last_seen IS NULL THEN 1 ELSE 0 END,
                 last_seen ASC,
                 id ASC
        LIMIT ?;
        """,
        (float(cutoff), int(max(1, limit))),
    )
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        pid = int(row["player_id"])
        if pid in excluded:
            continue
        if _vacation_active(row):
            continue
        if _is_excluded_ai(conn, pid):
            continue
        out.append(
            {
                "player_id": pid,
                "last_seen": row["last_seen"],
                "vacation_mode_active": int(row["vacation_mode_active"] or 0),
                "inactive": (
                    row["last_seen"] is None
                    or float(row["last_seen"] or 0)
                    < ts - float(RANKING_INACTIVE_AFTER_SEC)
                ),
            }
        )
    return out


def _round_robin_pick(
    conn,
    candidates: Sequence[Mapping[str, Any]],
    *,
    count: int,
    cursor_key: str = CURSOR_KEY,
) -> List[Mapping[str, Any]]:
    n = len(candidates)
    if n <= 0 or count <= 0:
        return []
    try:
        raw = get_runtime_value(cursor_key, conn=conn)
        start = int(float(raw or 0)) % n
    except Exception:
        start = 0
    limit = min(int(count), n)
    picked = [candidates[(start + i) % n] for i in range(limit)]
    try:
        set_runtime_value(cursor_key, str((start + limit) % n), conn=conn)
    except Exception:
        logger.exception("inactive autoplay cursor persist failed key=%s", cursor_key)
    return picked


def _load_roster(conn=None) -> List[Dict[str, Any]]:
    data = _load_json(ROSTER_KEY, conn=conn)
    roster: List[Dict[str, Any]] = []
    seen: Set[int] = set()
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                pid = int(item.get("player_id") or 0)
            except (TypeError, ValueError):
                continue
            if pid <= 0 or pid in seen:
                continue
            seen.add(pid)
            roster.append({"player_id": pid, "joined_at": item.get("joined_at")})

    # Migrate legacy short sessions into sticky roster once.
    legacy = _load_json(SESSIONS_KEY, conn=conn)
    if isinstance(legacy, list):
        changed = False
        for item in legacy:
            if not isinstance(item, dict):
                continue
            try:
                pid = int(item.get("player_id") or 0)
            except (TypeError, ValueError):
                continue
            if pid <= 0 or pid in seen:
                continue
            seen.add(pid)
            roster.append(
                {
                    "player_id": pid,
                    "joined_at": item.get("started_at") or item.get("joined_at"),
                }
            )
            changed = True
        if changed:
            _save_json(ROSTER_KEY, roster, conn=conn)
            _save_json(SESSIONS_KEY, [], conn=conn)
    return roster


def _save_roster(roster: Sequence[Mapping[str, Any]], *, conn=None) -> None:
    _save_json(ROSTER_KEY, list(roster), conn=conn)


def _prune_roster(conn, roster: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for item in roster:
        pid = int(item["player_id"])
        if _is_excluded_ai(conn, pid):
            continue
        if _player_vacation(conn, pid):
            continue
        # Drop vanished players.
        row = conn.execute(
            "SELECT 1 AS ok FROM players WHERE id = ? LIMIT 1;", (pid,)
        ).fetchone()
        if not row:
            continue
        kept.append({"player_id": pid, "joined_at": item.get("joined_at")})
    return kept


def _run_player_economy(
    conn,
    player_id: int,
    *,
    now: float,
) -> Dict[str, Any]:
    from .models import get_homeworld, get_planets_by_player

    _touch_presence(conn, player_id, now=now)
    home = get_homeworld(player_id, conn=conn)
    if not home:
        return {"ok": False, "error": "no_homeworld", "player_id": player_id}

    planets = get_planets_by_player(player_id, conn=conn) or [home]
    home_id = int(home["id"])
    results: List[Dict[str, Any]] = []
    for planet in planets:
        is_home = int(planet["id"]) == home_id or bool(planet.get("is_homeworld"))
        if not is_home and results:
            continue
        try:
            results.append(
                plan_passive_planet_tick(
                    conn,
                    player_id=player_id,
                    planet=planet,
                    now=now,
                    is_home=is_home,
                    allow_buildings=True,
                    allow_research=True,
                    allow_ships=False,
                    allow_defense=True,
                    personality="economy",
                    build_duration_cap=INACTIVE_BUILD_DURATION_CAP,
                    research_duration_cap=INACTIVE_RESEARCH_DURATION_CAP,
                    source="inactive_autoplay",
                    update_scores=True,
                    chain_limit=INACTIVE_CHAIN_LIMIT,
                )
            )
        except Exception:
            logger.exception(
                "inactive autoplay economy failed player=%s planet=%s",
                player_id,
                planet.get("id"),
            )
        if len(results) >= 2:
            break

    enqueued = any(
        r.get("build")
        or r.get("research")
        or r.get("defense")
        or r.get("builds")
        or r.get("researches")
        for r in results
    )
    return {
        "ok": True,
        "player_id": player_id,
        "economy": results,
        "enqueued": enqueued,
    }


def seconds_until_wake_allowed(*, now: Optional[float] = None, conn=None) -> float:
    data = _load_json(WORKER_LAST_KEY, conn=conn)
    if not isinstance(data, dict):
        return 0.0
    if not data.get("ok"):
        return 0.0
    try:
        last_at = float(data.get("at") or 0)
    except (TypeError, ValueError):
        return 0.0
    if last_at <= 0:
        return 0.0
    ts = float(now if now is not None else _now())
    return max(0.0, (last_at + wake_interval_sec()) - ts)


def run_inactive_autoplay_tick(
    conn,
    *,
    now: Optional[float] = None,
    force: bool = False,
    source: str = "fleet_worker",
) -> Dict[str, Any]:
    """Grow sticky roster; round-robin economy+presence every fleet cron."""
    ts = float(now if now is not None else _now())
    if not is_inactive_autoplay_enabled(conn=conn):
        return {"ok": False, "error": "disabled", "woke": [], "sessions": []}

    roster = _prune_roster(conn, _load_roster(conn=conn))
    woke: List[Dict[str, Any]] = []
    wait = 0.0 if force else seconds_until_wake_allowed(now=ts, conn=conn)
    room = max_concurrent_sessions() - len(roster)

    if wait <= 0 and room > 0:
        batch = min(wake_batch_size(), room)
        active_ids = {int(s["player_id"]) for s in roster}
        candidates = list_dormant_candidates(
            conn, now=ts, exclude_ids=active_ids, limit=400
        )
        picks = _round_robin_pick(conn, candidates, count=batch, cursor_key=CURSOR_KEY)
        for cand in picks:
            pid = int(cand["player_id"])
            roster.append({"player_id": pid, "joined_at": ts})
            try:
                res = _run_player_economy(conn, pid, now=ts)
                woke.append(res)
            except Exception:
                logger.exception("inactive autoplay wake failed player=%s", pid)
        _save_json(
            WORKER_LAST_KEY,
            {"ok": True, "at": ts, "source": source, "woke": len(woke)},
            conn=conn,
        )

    # Always tick a RR slice of the sticky roster (autonomous building).
    tick_n = min(tick_per_cron(), len(roster))
    to_tick = _round_robin_pick(
        conn, roster, count=tick_n, cursor_key=TICK_CURSOR_KEY
    )
    # Avoid double-running just-woke players in the same tick.
    woke_ids = {int(w["player_id"]) for w in woke}
    session_results: List[Dict[str, Any]] = list(woke)
    for item in to_tick:
        pid = int(item["player_id"])
        if pid in woke_ids:
            continue
        try:
            session_results.append(_run_player_economy(conn, pid, now=ts))
        except Exception:
            logger.exception("inactive autoplay roster tick failed player=%s", pid)

    _save_roster(roster, conn=conn)

    return {
        "ok": True,
        "source": source,
        "woke": woke,
        "woke_count": len(woke),
        "expired_count": 0,
        "active_sessions": len(roster),
        "roster_size": len(roster),
        "session_ticks": len(session_results),
        "enqueued": sum(1 for r in session_results if r.get("enqueued")),
        "wait_sec": wait,
        "revisit_sec": revisit_sec(),
        "tick_per_cron": tick_per_cron(),
        "inactive_threshold_sec": float(RANKING_INACTIVE_AFTER_SEC),
        "build_duration_cap": INACTIVE_BUILD_DURATION_CAP,
        "chain_limit": INACTIVE_CHAIN_LIMIT,
    }


def maybe_tick_inactive_autoplay(
    conn,
    *,
    now: Optional[float] = None,
    force: bool = False,
    source: str = "fleet_worker",
) -> Dict[str, Any]:
    """Safe wrapper for fleet/maintenance cron."""
    try:
        return run_inactive_autoplay_tick(
            conn, now=now, force=force, source=source
        )
    except Exception as exc:
        logger.exception("inactive autoplay tick failed")
        return {"ok": False, "error": str(exc)}
