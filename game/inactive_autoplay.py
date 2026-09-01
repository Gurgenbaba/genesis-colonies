"""Inactive autoplay — living dormant empires (EPIC-26 / GC-2601).

GC-INACTIVE-SHIFT-001 — Day Shift: a small shift crew (2–3) stays visibly
online; after a fixed tenure they rotate back to the dormant queue. Human Play
V5 adds sparse canonical shipyard and expedition decisions without another loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

from .auto_empire import (
    AUTOPLAY_STANDING_IDLE_CHANCE,
    personality_for_player,
    plan_passive_planet_tick,
)
from .db import begin_write_transaction, column_exists, commit, in_transaction, rollback
from .ranking import RANKING_INACTIVE_AFTER_SEC
from .presence_store import effective_last_seen_scalar_sql, touch_presence_bulk
from .runtime_state import get_runtime_value, set_runtime_value

logger = logging.getLogger(__name__)

ENABLED_RUNTIME_KEY = "inactive_autoplay_enabled"
WORKER_LAST_KEY = "inactive_autoplay_worker_last"
ECONOMY_LAST_KEY = "inactive_autoplay_economy_last"
ROSTER_KEY = "inactive_autoplay_roster"
SESSIONS_KEY = "inactive_autoplay_sessions"  # legacy merge
CURSOR_KEY = "inactive_autoplay_cursor"
TICK_CURSOR_KEY = "inactive_autoplay_tick_cursor"
# GC-PERF-AUTOPLAY-001: cross-process overlap guard (same pattern as ranking_worker).
BUSY_KEY = "inactive_autoplay_busy"
BUSY_STALE_SEC = 900.0

# Soft caps so queues turn over on fleet-cron cadence (still slower than pirate 90s).
INACTIVE_BUILD_DURATION_CAP = 900  # 15 min
INACTIVE_RESEARCH_DURATION_CAP = 1200  # 20 min
# GC-PERF-AUTOPLAY-003: no same-tick force-complete chains (was 2).
INACTIVE_CHAIN_LIMIT = 1

# GC-2621 — Living Universe V3. One dormant commander decision starts at most
# one progression domain. Per-player cadence breaks ranking lockstep without
# increasing the global SQLite writer budget.
INACTIVE_ACTION_DOMAINS = ("building", "research", "ships", "defense", "expedition")
INACTIVE_ACTION_WEIGHTS = {
    "economy": {"building": 55, "research": 20, "ships": 10, "defense": 8, "expedition": 7},
    "aggressive": {"building": 30, "research": 15, "ships": 30, "defense": 15, "expedition": 10},
    "turtle": {"building": 35, "research": 10, "ships": 12, "defense": 35, "expedition": 8},
    "spy": {"building": 25, "research": 35, "ships": 12, "defense": 8, "expedition": 20},
    "swarm": {"building": 30, "research": 15, "ships": 35, "defense": 10, "expedition": 10},
    "elite": {"building": 28, "research": 25, "ships": 27, "defense": 10, "expedition": 10},
}
INACTIVE_ACTION_PACE_RANGES_SEC = {
    "aggressive": (5 * 60, 14 * 60),
    "swarm": (6 * 60, 16 * 60),
    "elite": (8 * 60, 20 * 60),
    "economy": (10 * 60, 24 * 60),
    "spy": (12 * 60, 28 * 60),
    "turtle": (15 * 60, 35 * 60),
}
# Permanent empire ambition: equal personalities still develop different ceilings.
INACTIVE_AMBITION_BASE = {
    "economy": 1.16,
    "aggressive": 1.02,
    "turtle": 1.08,
    "spy": 0.96,
    "swarm": 1.04,
    "elite": 1.12,
}
# Longer strategic phases shift priorities without extra polling or workers.
INACTIVE_STRATEGIC_PHASES = ("growth", "research", "fortification", "balanced")
INACTIVE_PHASE_DOMAIN_MULT = {
    "growth": {"building": 1.75, "research": 0.70, "ships": 0.85, "defense": 0.55, "expedition": 0.75},
    "research": {"building": 0.70, "research": 1.85, "ships": 0.75, "defense": 0.55, "expedition": 0.90},
    "fortification": {"building": 0.70, "research": 0.65, "ships": 1.15, "defense": 1.90, "expedition": 0.65},
    "balanced": {"building": 1.00, "research": 1.00, "ships": 1.00, "defense": 1.00, "expedition": 1.00},
}
INACTIVE_WORLD_BOSS_SAFE_HP_RATIO = 0.05
INACTIVE_EXPEDITION_SHIP_PREFERENCE = ("solar_skiff", "eclipse_runner")

# Soft floor so empty dormant empires can enqueue (far below pirate seed).
INACTIVE_RESOURCE_FLOOR = {
    "metal": 75_000,
    "crystal": 50_000,
    "fuel_cells": 15_000,
}

# Revisit: cooldown after shift eviction before re-eligible (queue "back").
DEFAULT_REVISIT_SEC = 12 * 3600  # GC-INACTIVE-SHIFT-001: 12h (was 36h)
DEFAULT_WAKE_INTERVAL_SEC = 15 * 60  # GC-INACTIVE-SHIFT-001: 15 min
# GC-PERF-AUTOPLAY-003: standing RR economy gated off fleet-due storms.
DEFAULT_ECONOMY_INTERVAL_SEC = 5 * 60  # 5 min between standing economies
# GC-INACTIVE-SHIFT-001: shift crew = visible online (2–3), not mass sticky builders.
DEFAULT_BATCH = 1
DEFAULT_MAX_ROSTER = 3
DEFAULT_SESSION_TENURE_SEC = 3 * 3600  # 3h on shift, then rotate out
# GC-PERF-AUTOPLAY-002: one heavy economy per cron by default (was 3) so
# sticky-roster bursts do not serialize SQLite against human HTTP writers.
DEFAULT_TICK_PER_CRON = 1
# Yield between short-TX player economies so gunicorn can grab the writer.
DEFAULT_YIELD_MS = 50
# Abort further standing RR economies once wall time exceeds this budget.
DEFAULT_TICK_BUDGET_MS = 800
MIN_ROSTER_CAP = 2
MAX_ROSTER_CAP = 4
# Europe day band for natural "daytime" presence (GC-INACTIVE-SHIFT-001).
DAY_SHIFT_TZ = "Europe/Berlin"
DAY_SHIFT_START_HOUR = 8
DAY_SHIFT_END_HOUR = 23  # exclusive — 23:00+ is night target
DAY_TARGET_ONLINE = 3
NIGHT_TARGET_ONLINE = 2
# Deprecated GC-2617 percent wall — kept for import/compat only.
DEFAULT_ONLINE_PERCENT = 0.0
MIN_ONLINE_VISIBLE = 2
MAX_ONLINE_VISIBLE = 4

ENABLED_ENV = "GC_INACTIVE_AUTOPLAY_ENABLED"
BATCH_ENV = "GC_INACTIVE_AUTOPLAY_BATCH"
INTERVAL_ENV = "GC_INACTIVE_AUTOPLAY_INTERVAL_SEC"
ECONOMY_INTERVAL_ENV = "GC_INACTIVE_AUTOPLAY_ECONOMY_INTERVAL_SEC"
REVISIT_ENV = "GC_INACTIVE_AUTOPLAY_REVISIT_SEC"
MAX_ROSTER_ENV = "GC_INACTIVE_AUTOPLAY_MAX_SESSIONS"  # keep env name for ops
TICK_ENV = "GC_INACTIVE_AUTOPLAY_TICK_PER_CRON"
YIELD_ENV = "GC_INACTIVE_AUTOPLAY_YIELD_MS"
BUDGET_ENV = "GC_INACTIVE_AUTOPLAY_TICK_BUDGET_MS"
ONLINE_PERCENT_ENV = "GC_INACTIVE_AUTOPLAY_ONLINE_PERCENT"  # deprecated / ignored
SESSION_ENV = "GC_INACTIVE_AUTOPLAY_SESSION_SEC"  # shift tenure (GC-INACTIVE-SHIFT-001)


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


def economy_interval_sec() -> float:
    """GC-PERF-AUTOPLAY-003: min seconds between standing RR economies."""
    return float(
        max(60, min(3600, _env_int(ECONOMY_INTERVAL_ENV, DEFAULT_ECONOMY_INTERVAL_SEC)))
    )


def session_tenure_sec() -> float:
    """GC-INACTIVE-SHIFT-001: how long a player stays on the shift roster."""
    return float(max(600, _env_int(SESSION_ENV, DEFAULT_SESSION_TENURE_SEC)))


def session_duration_sec() -> float:
    """Alias for session_tenure_sec (legacy name kept for callers/tests)."""
    return session_tenure_sec()


def revisit_sec() -> float:
    return float(max(3600, _env_int(REVISIT_ENV, DEFAULT_REVISIT_SEC)))


def max_concurrent_sessions() -> int:
    """Ops hard ceiling for shift size (env name MAX_SESSIONS for compatibility).

    GC-INACTIVE-SHIFT-001: clamp 2–4 (default 3). Live shift size is
    ``shift_cap()`` = min(this, day_target()).
    """
    return max(MIN_ROSTER_CAP, min(MAX_ROSTER_CAP, _env_int(MAX_ROSTER_ENV, DEFAULT_MAX_ROSTER)))


def day_target(*, now: Optional[float] = None) -> int:
    """Visible shift size for Europe/Berlin day vs night (GC-INACTIVE-SHIFT-001)."""
    ts = float(now if now is not None else _now())
    try:
        local = datetime.fromtimestamp(ts, tz=ZoneInfo(DAY_SHIFT_TZ))
        hour = int(local.hour)
    except Exception:
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    if DAY_SHIFT_START_HOUR <= hour < DAY_SHIFT_END_HOUR:
        return int(DAY_TARGET_ONLINE)
    return int(NIGHT_TARGET_ONLINE)


def shift_cap(*, now: Optional[float] = None, conn=None) -> int:
    """Live roster/online size: day target capped by ops max sessions."""
    del conn  # reserved for future knobs; keep signature stable for callers
    return max(
        MIN_ROSTER_CAP,
        min(max_concurrent_sessions(), day_target(now=now)),
    )


def tick_per_cron() -> int:
    return max(1, min(20, _env_int(TICK_ENV, DEFAULT_TICK_PER_CRON)))


def yield_ms() -> int:
    """GC-PERF-AUTOPLAY-002: pause between short-TX player economies."""
    return max(0, min(250, _env_int(YIELD_ENV, DEFAULT_YIELD_MS)))


def tick_budget_ms() -> int:
    """GC-PERF-AUTOPLAY-002: wall-time budget for standing RR economies."""
    return max(200, min(5000, _env_int(BUDGET_ENV, DEFAULT_TICK_BUDGET_MS)))


def online_percent() -> float:
    """Deprecated GC-INACTIVE-SHIFT-001 — percent wall ignored; use day_target()."""
    raw = os.environ.get(ONLINE_PERCENT_ENV)
    if raw not in (None, ""):
        try:
            return max(0.0, min(50.0, float(raw)))
        except (TypeError, ValueError):
            pass
    return float(DEFAULT_ONLINE_PERCENT)


def online_visible_cap(*, conn=None, now: Optional[float] = None) -> int:
    """GC-INACTIVE-SHIFT-001: shift size (== visible online)."""
    return shift_cap(now=now, conn=conn)


def _stable_roll(player_id: int, namespace: str, sequence: int, modulo: int) -> int:
    """Process-stable deterministic roll; Python's salted hash() is forbidden here."""
    cap = max(1, int(modulo))
    raw = f"inactive:{namespace}:{int(player_id)}:{int(sequence)}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return int(digest[:16], 16) % cap


def _ambition_scale(player_id: int, personality: str) -> float:
    base = float(INACTIVE_AMBITION_BASE.get(str(personality), 1.0))
    personal_pct = 84 + _stable_roll(player_id, "ambition", 0, 43)  # 0.84..1.26
    return round(max(0.72, min(1.55, base * (float(personal_pct) / 100.0))), 3)


def _strategic_phase_for_player(player_id: int, action_seq: int) -> str:
    span = 36 + _stable_roll(player_id, "phase-span", 0, 37)  # 36..72 decisions
    offset = _stable_roll(player_id, "phase-offset", 0, len(INACTIVE_STRATEGIC_PHASES))
    idx = ((max(0, int(action_seq)) // max(1, int(span))) + int(offset)) % len(
        INACTIVE_STRATEGIC_PHASES
    )
    return INACTIVE_STRATEGIC_PHASES[idx]


def _action_domain_for_player(player_id: int, personality: str, action_seq: int) -> str:
    base_weights = INACTIVE_ACTION_WEIGHTS.get(str(personality)) or INACTIVE_ACTION_WEIGHTS["economy"]
    phase = _strategic_phase_for_player(player_id, action_seq)
    phase_mult = INACTIVE_PHASE_DOMAIN_MULT.get(phase) or INACTIVE_PHASE_DOMAIN_MULT["balanced"]
    weights = {
        key: max(0, int(round(float(base_weights.get(key) or 0) * float(phase_mult.get(key) or 1.0))))
        for key in INACTIVE_ACTION_DOMAINS
    }
    total = sum(max(0, int(weights.get(key) or 0)) for key in INACTIVE_ACTION_DOMAINS)
    if total <= 0:
        return "building"
    roll = _stable_roll(player_id, f"domain:{phase}", action_seq, total)
    cursor = 0
    for domain in INACTIVE_ACTION_DOMAINS:
        cursor += max(0, int(weights.get(domain) or 0))
        if roll < cursor:
            return domain
    return "building"


def _next_action_delay_sec(player_id: int, personality: str, action_seq: int) -> int:
    """Human-shaped cadence: short bursts interrupted by longer breaks."""
    low, high = INACTIVE_ACTION_PACE_RANGES_SEC.get(
        str(personality), INACTIVE_ACTION_PACE_RANGES_SEC["economy"]
    )
    low_i, high_i = max(60, int(low)), max(int(low), int(high))
    seq = max(0, int(action_seq))
    cycle = seq // 8
    burst_len = 3 + _stable_roll(player_id, "session-span", cycle, 5)
    if seq > 0 and seq % burst_len == 0:
        return 45 * 60 + _stable_roll(
            player_id, "session-break", seq, 3 * 3600 + 1
        )

    quick_chance = {
        "aggressive": 55,
        "swarm": 50,
        "elite": 45,
        "spy": 40,
        "economy": 35,
        "turtle": 25,
    }.get(str(personality), 35)
    if _stable_roll(player_id, "quick-return", seq, 100) < quick_chance:
        return 3 * 60 + _stable_roll(
            player_id, "quick-gap", seq, 8 * 60 + 1
        )
    return low_i + _stable_roll(
        player_id, "pace", seq, high_i - low_i + 1
    )


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


def _try_acquire_tick_busy(*, conn, now: float) -> bool:
    """Cross-process overlap guard via runtime_state (stale after BUSY_STALE_SEC)."""
    raw = get_runtime_value(BUSY_KEY, conn=conn)
    if raw and str(raw).strip() not in {"", "0"}:
        try:
            started = float(raw)
            if (now - started) < BUSY_STALE_SEC:
                return False
        except (TypeError, ValueError):
            pass
    set_runtime_value(BUSY_KEY, str(now), conn=conn)
    return True


def _release_tick_busy(*, conn) -> None:
    set_runtime_value(BUSY_KEY, "0", conn=conn)


def _write_step(conn, short_tx: bool, fn):
    """Run ``fn`` under a short write TX when the tick owns transaction boundaries.

    When ``short_tx`` is False the caller already holds BEGIN IMMEDIATE (tests /
    legacy nested callers) — ``fn`` runs in that outer transaction without
    mid-tick commits.
    """
    if not short_tx:
        return fn()
    begin_write_transaction(conn)
    try:
        out = fn()
        commit(conn)
        return out
    except Exception:
        rollback(conn)
        raise


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


def _touch_presence_bulk(conn, player_ids: Sequence[int], *, now: float) -> None:
    """Batched shift-roster presence through the canonical backend store."""
    ids = sorted({int(pid) for pid in player_ids if int(pid) > 0})
    if not ids:
        return
    try:
        touch_presence_bulk(conn, ids, now=int(now))
    except Exception:
        logger.exception("inactive autoplay bulk presence touch failed")


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
        "COALESCE(p.vacation_mode_active, 0)"
        if column_exists(conn, "players", "vacation_mode_active")
        else "0"
    )
    last_seen_expr = effective_last_seen_scalar_sql(player_alias="p")
    cur = conn.execute(
        f"""
        SELECT p.id AS player_id,
               {last_seen_expr} AS last_seen,
               {vac_select} AS vacation_mode_active
        FROM players p
        WHERE {last_seen_expr} < ?
        ORDER BY last_seen ASC, p.id ASC
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
            roster.append(
                {
                    "player_id": pid,
                    "joined_at": item.get("joined_at"),
                    "last_ticked_at": item.get("last_ticked_at"),
                    "last_action": item.get("last_action"),
                    "builds_done": int(item.get("builds_done") or 0),
                    "research_done": int(item.get("research_done") or 0),
                    "defense_done": int(item.get("defense_done") or 0),
                "action_seq": int(item.get("action_seq") or 0),
                "next_action_at": item.get("next_action_at"),
                }
            )

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
                    "last_ticked_at": None,
                    "last_action": None,
                    "builds_done": 0,
                    "research_done": 0,
                    "defense_done": 0,
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
        kept.append(
            {
                "player_id": pid,
                "joined_at": item.get("joined_at"),
                "last_ticked_at": item.get("last_ticked_at"),
                "last_action": item.get("last_action"),
                "builds_done": int(item.get("builds_done") or 0),
                "research_done": int(item.get("research_done") or 0),
                "defense_done": int(item.get("defense_done") or 0),
                "action_seq": int(item.get("action_seq") or 0),
                "next_action_at": item.get("next_action_at"),
            }
        )
    return kept


def _trim_roster_to_cap(
    conn,
    roster: List[Dict[str, Any]],
    *,
    now: Optional[float] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Immediately LRU-evict excess above live ``shift_cap``.

    Deploy-safe shrink when the stored roster still holds a pre-shift size
    (e.g. 6 → 3). Uses the same inbox report owner as tenure eviction.
    """
    cap = shift_cap(now=now, conn=conn)
    if len(roster) <= cap:
        return roster, 0
    roster = list(roster)
    roster.sort(
        key=lambda item: float(
            item.get("last_ticked_at") or item.get("joined_at") or 0
        )
    )
    excess = len(roster) - cap
    to_evict = roster[:excess]
    kept = roster[excess:]
    for evicted_item in to_evict:
        _send_autoplay_report(conn, evicted_item)
    return kept, excess


def _ensure_resource_floor(conn, planet_id: int) -> Dict[str, int]:
    """Raise home stockpile to a soft floor when empty (GC-2607)."""
    row = conn.execute(
        """
        SELECT COALESCE(metal, 0) AS metal,
               COALESCE(crystal, 0) AS crystal,
               COALESCE(fuel_cells, 0) AS fuel_cells
        FROM planets WHERE id = ? LIMIT 1;
        """,
        (int(planet_id),),
    ).fetchone()
    if not row:
        return {}
    farm_mult = 1.0
    try:
        from .server_events import active_inactive_farm_mult

        farm_mult = max(1.0, float(active_inactive_farm_mult(conn=conn) or 1.0))
    except Exception:
        farm_mult = 1.0
    floor_metal = float(INACTIVE_RESOURCE_FLOOR["metal"]) * farm_mult
    floor_crystal = float(INACTIVE_RESOURCE_FLOOR["crystal"]) * farm_mult
    floor_fuel = float(INACTIVE_RESOURCE_FLOOR["fuel_cells"]) * farm_mult
    metal = max(float(row["metal"] or 0), floor_metal)
    crystal = max(float(row["crystal"] or 0), floor_crystal)
    fuel = max(float(row["fuel_cells"] or 0), floor_fuel)
    raised = (
        metal > float(row["metal"] or 0)
        or crystal > float(row["crystal"] or 0)
        or fuel > float(row["fuel_cells"] or 0)
    )
    if raised:
        conn.execute(
            """
            UPDATE planets
            SET metal = ?, crystal = ?, fuel_cells = ?
            WHERE id = ?;
            """,
            (metal, crystal, fuel, int(planet_id)),
        )
    return {
        "metal": int(metal),
        "crystal": int(crystal),
        "fuel_cells": int(fuel),
        "raised": int(raised),
        "farm_mult": float(farm_mult),
    }


def _describe_last_action(results: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """Human-readable summary of the most recent enqueue for admin/report display."""
    for res in reversed(list(results)):
        build = res.get("build")
        if build:
            return f"{build.get('building_type')} -> Lvl {build.get('target_level')}"
        research = res.get("research")
        if research:
            return f"{research.get('tech_key')} -> Lvl {research.get('target_level')}"
        defense = res.get("defense")
        if defense:
            return f"{defense.get('defense_key')} x{defense.get('amount')}"
        ships = res.get("ships")
        if ships:
            return f"{ships.get('ship_key')} x{ships.get('amount')}"
    return None


def _weakest_combat_ship_for_player(conn, player_id: int) -> Optional[Dict[str, Any]]:
    """Find one weakest combat-capable ship across the commander's empire."""
    from .combat_models import combat_stats_for_ship

    rows = conn.execute(
        """
        SELECT ps.planet_id, ps.ship_key, ps.amount
        FROM planet_ships ps
        JOIN planets p ON p.id = ps.planet_id
        WHERE p.player_id = ? AND COALESCE(ps.amount, 0) > 0;
        """,
        (int(player_id),),
    ).fetchall()
    best: Optional[Tuple[int, str, int]] = None
    for row in rows:
        stats = combat_stats_for_ship(str(row["ship_key"]))
        if stats is None or int(stats.attack or 0) <= 0:
            continue
        candidate = (int(stats.attack or 0), str(row["ship_key"]), int(row["planet_id"]))
        if best is None or candidate < best:
            best = candidate
    if best is None:
        return None
    return {"planet_id": best[2], "ships": {best[1]: 1}}


def _maybe_join_world_boss(conn, player_id: int, *, now: float) -> Dict[str, Any]:
    """One tiny canonical instant strike per boss, never during the final 5% HP."""
    try:
        from .world_boss import can_player_attack_boss, execute_instant_attack, list_active_events

        token_force = _weakest_combat_ship_for_player(conn, int(player_id))
        if not token_force:
            return {"ok": True, "joined": False, "reason": "no_combat_ships"}
        for event in list_active_events(conn=conn, now=float(now), limit=3):
            max_hp = max(1, int(event.get("max_hp") or 1))
            hp_ratio = float(event.get("current_hp") or 0) / float(max_hp)
            if hp_ratio <= INACTIVE_WORLD_BOSS_SAFE_HP_RATIO:
                continue
            ok, _reason, meta = can_player_attack_boss(
                int(player_id),
                int(event["id"]),
                conn=conn,
                now=float(now),
                enforce_cooldown=False,
                check_inflight=False,
            )
            if not ok or int((meta or {}).get("waves") or 0) > 0:
                continue
            strike = execute_instant_attack(
                int(player_id),
                int(event["id"]),
                token_force["ships"],
                planet_id=int(token_force["planet_id"]),
                conn=conn,
                now=float(now),
                auto_select=False,
                hit_mult=1,
            )
            if strike.get("ok"):
                return {
                    "ok": True,
                    "joined": True,
                    "event_id": int(event["id"]),
                    "damage": int(strike.get("damage") or 0),
                    "ships": dict(token_force["ships"]),
                }
        return {"ok": True, "joined": False, "reason": "no_eligible_boss"}
    except Exception:
        logger.exception("inactive autoplay world boss participation failed player=%s", player_id)
        return {"ok": False, "joined": False, "reason": "world_boss_error"}

def _stockpile_snapshot(conn, planet_id: int) -> Dict[str, int]:
    """Read the real stockpile; Human Play V5 never injects resources."""
    row = conn.execute(
        """
        SELECT COALESCE(metal, 0) AS metal,
               COALESCE(crystal, 0) AS crystal,
               COALESCE(fuel_cells, 0) AS fuel_cells
        FROM planets WHERE id = ? LIMIT 1;
        """,
        (int(planet_id),),
    ).fetchone()
    if not row:
        return {}
    return {
        "metal": int(float(row["metal"] or 0)),
        "crystal": int(float(row["crystal"] or 0)),
        "fuel_cells": int(float(row["fuel_cells"] or 0)),
        "raised": 0,
    }


def _pick_progression_planet(
    player_id: int,
    planets: Sequence[Mapping[str, Any]],
    *,
    action_seq: int,
) -> Optional[Dict[str, Any]]:
    """Spread local decisions across the commander's owned planets."""
    candidates = [dict(p) for p in planets if int(p.get("id") or 0) > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda p: int(p.get("id") or 0))
    if len(candidates) == 1:
        return candidates[0]
    idx = _stable_roll(player_id, "planet-choice", action_seq, len(candidates))
    return candidates[idx]


def _sync_planet_for_decision(
    conn,
    player_id: int,
    planet: Mapping[str, Any],
    *,
    now: float,
    is_home: bool,
    personality: str,
    ambition_scale: float,
) -> Dict[str, Any]:
    """Finish due work/update production without starting a new action."""
    return plan_passive_planet_tick(
        conn,
        player_id=int(player_id),
        planet=planet,
        now=float(now),
        is_home=bool(is_home),
        allow_buildings=False,
        allow_research=False,
        allow_ships=False,
        allow_defense=False,
        personality=str(personality),
        build_duration_cap=INACTIVE_BUILD_DURATION_CAP,
        research_duration_cap=INACTIVE_RESEARCH_DURATION_CAP,
        target_scale=float(ambition_scale),
        source="inactive_autoplay",
        update_scores=True,
        chain_limit=INACTIVE_CHAIN_LIMIT,
        idle_chance=0.0,
    )


def _pick_expedition_force(
    conn,
    player_id: int,
    *,
    action_seq: int,
) -> Optional[Dict[str, Any]]:
    """Pick one real expedition-capable ship from an owned planet."""
    from .fleet import get_planet_ships
    from .models import get_planets_by_player

    planets = [
        dict(p)
        for p in (get_planets_by_player(int(player_id), conn=conn) or [])
    ]
    if not planets:
        return None
    planets.sort(key=lambda p: int(p.get("id") or 0))
    start = _stable_roll(
        player_id, "expedition-origin", action_seq, len(planets)
    )
    ordered = planets[start:] + planets[:start]
    ship_order = list(INACTIVE_EXPEDITION_SHIP_PREFERENCE)
    if _stable_roll(player_id, "expedition-hull", action_seq, 2):
        ship_order.reverse()
    for planet in ordered:
        planet_id = int(planet.get("id") or 0)
        hangar = get_planet_ships(planet_id, conn=conn)
        for ship_key in ship_order:
            if int(hangar.get(ship_key) or 0) >= 1:
                return {
                    "planet": planet,
                    "planet_id": planet_id,
                    "galaxy": int(planet.get("galaxy") or 1),
                    "system": int(planet.get("system") or 1),
                    "ships": {ship_key: 1},
                }
    return None


def _maybe_send_expedition(
    conn,
    player_id: int,
    *,
    now: float,
    action_seq: int,
    home_id: int,
    personality: str,
    ambition_scale: float,
) -> Dict[str, Any]:
    """Send one canonical expedition when hull, slot and fuel permit it."""
    force = _pick_expedition_force(
        conn, int(player_id), action_seq=int(action_seq)
    )
    if not force:
        return {"ok": True, "sent": False, "reason": "no_expedition_ship"}

    planet = dict(force["planet"])
    _sync_planet_for_decision(
        conn,
        int(player_id),
        planet,
        now=float(now),
        is_home=int(force["planet_id"]) == int(home_id),
        personality=str(personality),
        ambition_scale=float(ambition_scale),
    )

    from .fleet import send_fleet
    from .fleet_defs import EXPEDITION_POSITION

    hours = 1 + _stable_roll(player_id, "expedition-hours", action_seq, 4)
    ok, reason, meta = send_fleet(
        player_id=int(player_id),
        origin_planet_id=int(force["planet_id"]),
        mission_type="expedition",
        target_galaxy=int(force["galaxy"]),
        target_system=int(force["system"]),
        target_position=int(EXPEDITION_POSITION),
        ships=dict(force["ships"]),
        resources={},
        speed_percent=100,
        expedition_hours=int(hours),
        conn=conn,
    )
    if not ok:
        return {
            "ok": True,
            "sent": False,
            "reason": str(reason or "blocked"),
            "planet_id": int(force["planet_id"]),
        }
    return {
        "ok": True,
        "sent": True,
        "fleet_id": int((meta or {}).get("fleet", {}).get("id") or 0),
        "planet_id": int(force["planet_id"]),
        "ships": dict(force["ships"]),
        "expedition_hours": int(hours),
    }


def _run_player_economy(
    conn,
    player_id: int,
    *,
    now: float,
    is_wake: bool = False,
    action_seq: int = 0,
    next_action_at: Optional[float] = None,
) -> Dict[str, Any]:
    """Execute one human-shaped decision through canonical game systems."""
    from .auto_empire import try_build_defense, try_build_ships
    from .models import get_homeworld, get_planets_by_player

    home = get_homeworld(player_id, conn=conn)
    if not home:
        return {"ok": False, "error": "no_homeworld", "player_id": player_id}
    home = dict(home)
    home_id = int(home["id"])
    stockpile = _stockpile_snapshot(conn, home_id)
    planets = [
        dict(p)
        for p in (get_planets_by_player(player_id, conn=conn) or [home])
    ]
    personality = personality_for_player(player_id)
    seq = max(0, int(action_seq or 0))
    strategic_phase = _strategic_phase_for_player(player_id, seq)
    ambition_scale = _ambition_scale(player_id, personality)
    personal_cooldown = bool(
        not is_wake
        and next_action_at is not None
        and float(now) < float(next_action_at)
    )
    action_domain = (
        "building"
        if is_wake
        else None
        if personal_cooldown
        else _action_domain_for_player(player_id, personality, seq)
    )
    should_idle = bool(
        not is_wake
        and not personal_cooldown
        and _stable_roll(player_id, "idle", seq, 1000)
        < int(AUTOPLAY_STANDING_IDLE_CHANCE * 1000)
    )

    results: List[Dict[str, Any]] = []
    home_synced = False
    target_planet: Optional[Dict[str, Any]] = None
    if action_domain == "research" or is_wake:
        target_planet = home
    elif action_domain in {"building", "ships", "defense"}:
        target_planet = _pick_progression_planet(
            player_id, planets, action_seq=seq
        )

    if target_planet is not None:
        is_home = int(target_planet["id"]) == home_id or bool(
            target_planet.get("is_homeworld")
        )
        if action_domain in {"building", "research"}:
            try:
                planned = plan_passive_planet_tick(
                    conn,
                    player_id=player_id,
                    planet=target_planet,
                    now=now,
                    is_home=is_home,
                    allow_buildings=action_domain == "building",
                    allow_research=action_domain == "research",
                    allow_ships=False,
                    allow_defense=False,
                    personality=personality,
                    build_duration_cap=INACTIVE_BUILD_DURATION_CAP,
                    research_duration_cap=INACTIVE_RESEARCH_DURATION_CAP,
                    target_scale=ambition_scale,
                    source="inactive_autoplay",
                    update_scores=True,
                    chain_limit=INACTIVE_CHAIN_LIMIT,
                    idle_chance=(
                        1.0 if personal_cooldown or should_idle else 0.0
                    ),
                )
                results.append(planned)
                home_synced = bool(is_home)
            except Exception:
                logger.exception(
                    "inactive autoplay economy failed player=%s planet=%s",
                    player_id,
                    target_planet.get("id"),
                )
        elif not personal_cooldown and not should_idle:
            try:
                sync = _sync_planet_for_decision(
                    conn,
                    player_id,
                    target_planet,
                    now=now,
                    is_home=is_home,
                    personality=personality,
                    ambition_scale=ambition_scale,
                )
                home_synced = bool(is_home)
                if action_domain == "ships":
                    direct_action = try_build_ships(
                        conn,
                        player_id=player_id,
                        planet_id=int(target_planet["id"]),
                        personality=personality,
                    )
                    if direct_action.get("ok"):
                        sync["ships"] = direct_action
                elif action_domain == "defense":
                    direct_action = try_build_defense(
                        conn,
                        player_id=player_id,
                        planet_id=int(target_planet["id"]),
                        personality=personality,
                        target_scale=ambition_scale,
                    )
                    if direct_action.get("ok"):
                        sync["defense"] = direct_action
                results.append(sync)
            except Exception:
                logger.exception(
                    "inactive autoplay local action failed player=%s planet=%s",
                    player_id,
                    target_planet.get("id"),
                )

    expedition = {"ok": True, "sent": False, "reason": "not_selected"}
    if (
        action_domain == "expedition"
        and not personal_cooldown
        and not should_idle
    ):
        try:
            expedition = _maybe_send_expedition(
                conn,
                player_id,
                now=now,
                action_seq=seq,
                home_id=home_id,
                personality=personality,
                ambition_scale=ambition_scale,
            )
            if int(expedition.get("planet_id") or 0) == home_id:
                home_synced = True
        except Exception:
            logger.exception(
                "inactive autoplay expedition failed player=%s", player_id
            )
            expedition = {
                "ok": False,
                "sent": False,
                "reason": "exception",
            }

    # A human may idle, use a colony, or fail to launch a fleet. Due homeworld
    # work must still complete so old queues do not freeze between sessions.
    if not home_synced:
        try:
            results.append(
                _sync_planet_for_decision(
                    conn,
                    player_id,
                    home,
                    now=now,
                    is_home=True,
                    personality=personality,
                    ambition_scale=ambition_scale,
                )
            )
            home_synced = True
        except Exception:
            logger.exception(
                "inactive autoplay home sync failed player=%s", player_id
            )

    enqueued = any(
        r.get("build")
        or r.get("research")
        or r.get("ships")
        or r.get("defense")
        or r.get("builds")
        or r.get("researches")
        for r in results
    ) or bool(expedition.get("sent"))
    finished_any = any((r.get("finished") or {}) for r in results)
    finished_totals = {
        "buildings": 0,
        "research": 0,
        "defense": 0,
        "shipyard": 0,
    }
    for result in results:
        finished = result.get("finished") or {}
        for key in finished_totals:
            try:
                finished_totals[key] += int(finished.get(key) or 0)
            except (TypeError, ValueError):
                continue

    boss_participation = _maybe_join_world_boss(conn, player_id, now=now)
    next_seq = seq if personal_cooldown else seq + 1
    next_at = (
        float(next_action_at)
        if personal_cooldown and next_action_at is not None
        else None
    )
    next_delay = None
    if not personal_cooldown:
        next_delay = _next_action_delay_sec(player_id, personality, seq)
        next_at = float(now) + float(next_delay)

    last_action = _describe_last_action(results)
    if not last_action and expedition.get("sent"):
        last_action = "expedition"
    return {
        "ok": True,
        "player_id": player_id,
        "economy": results,
        "enqueued": enqueued,
        "finished": finished_any,
        "finished_totals": finished_totals,
        "last_action": last_action,
        "resource_floor": stockpile,
        "action_domain": action_domain,
        "action_seq": next_seq,
        "next_action_delay_sec": next_delay,
        "next_action_at": next_at,
        "personal_cooldown": personal_cooldown,
        "strategic_phase": strategic_phase,
        "ambition_scale": ambition_scale,
        "expedition": expedition,
        "boss_participation": boss_participation,
    }


def get_roster_snapshot(*, conn=None) -> List[Dict[str, Any]]:
    """Public accessor for admin/API surfaces (GC-2608) — do not mutate."""
    return _load_roster(conn=conn)


def player_on_inactive_autoplay_roster(player_id: int, *, conn=None) -> bool:
    """Read-only: True when this account is on the sticky autoplay roster (GC-2619)."""
    if not is_inactive_autoplay_enabled(conn=conn):
        return False
    pid = int(player_id)
    if pid <= 0:
        return False
    return any(int(item.get("player_id") or 0) == pid for item in _load_roster(conn=conn))


def get_last_worker_run(*, conn=None) -> Dict[str, Any]:
    """Public accessor for the last `run_inactive_autoplay_tick` snapshot (GC-2608)."""
    data = _load_json(WORKER_LAST_KEY, conn=conn)
    return data if isinstance(data, dict) else {}


def _apply_economy_result_to_roster_item(
    item: Dict[str, Any], result: Mapping[str, Any]
) -> None:
    """GC-2615: accumulate what a roster member actually did while sticky."""
    totals = result.get("finished_totals") or {}
    item["builds_done"] = int(item.get("builds_done") or 0) + int(
        totals.get("buildings") or 0
    )
    item["research_done"] = int(item.get("research_done") or 0) + int(
        totals.get("research") or 0
    )
    item["defense_done"] = int(item.get("defense_done") or 0) + int(
        totals.get("defense") or 0
    )
    if result.get("action_seq") is not None:
        item["action_seq"] = max(0, int(result.get("action_seq") or 0))
    if result.get("next_action_at") is not None:
        item["next_action_at"] = float(result["next_action_at"])
    action = result.get("last_action")
    if action:
        item["last_action"] = action


def _send_autoplay_report(conn, item: Mapping[str, Any]) -> None:
    """GC-2615: one inbox message per roster session — visible activity instead
    of a silent tick. Reuses the canonical Inbox owner (`messages.create_message`,
    same pattern as `alliance._notify_alliance_members`); no parallel feed.
    """
    pid = int(item.get("player_id") or 0)
    builds = int(item.get("builds_done") or 0)
    research = int(item.get("research_done") or 0)
    defense = int(item.get("defense_done") or 0)
    if pid <= 0 or (builds <= 0 and research <= 0 and defense <= 0):
        return
    try:
        from .i18n import get_player_locale, tr
        from .messages import create_message

        loc = get_player_locale(pid, conn=conn)
        lines = []
        if builds > 0:
            lines.append(
                tr(
                    "inactive_autoplay_report_line_builds",
                    "- %(count)s Gebäude-Ausbauten abgeschlossen",
                    locale=loc,
                    count=builds,
                )
            )
        if research > 0:
            lines.append(
                tr(
                    "inactive_autoplay_report_line_research",
                    "- %(count)s Forschungen abgeschlossen",
                    locale=loc,
                    count=research,
                )
            )
        if defense > 0:
            lines.append(
                tr(
                    "inactive_autoplay_report_line_defense",
                    "- %(count)s Verteidigungsanlagen gebaut",
                    locale=loc,
                    count=defense,
                )
            )
        intro = tr(
            "inactive_autoplay_report_intro",
            "Während deiner Abwesenheit hat die Kolonieverwaltung den laufenden Betrieb fortgesetzt:",
            locale=loc,
        )
        subject = tr(
            "inactive_autoplay_report_subject",
            "Kolonie-Betriebsbericht",
            locale=loc,
        )
        sender = tr(
            "inactive_autoplay_report_sender",
            "Kolonieverwaltung",
            locale=loc,
        )
        body = intro + "\n\n" + "\n".join(lines)
        create_message(
            pid,
            subject,
            body,
            category="system",
            sender_name=sender,
            metadata={
                "kind": "inactive_autoplay_report",
                "builds_done": builds,
                "research_done": research,
                "defense_done": defense,
            },
            conn=conn,
        )
    except Exception:
        logger.exception("inactive autoplay report send failed player=%s", pid)


def release_active_player_from_roster(player_id: int, *, conn) -> bool:
    """GC-2619: instant full control back the moment a real human is seen.

    Called from `models.touch_player_online` — the single canonical signal
    for "a real authenticated request just happened" (`require_login` /
    `require_admin` / `require_login_api`). GC-PERF-LOCK-001: release runs on
    every successful touch TX, including when the throttled ``last_seen`` UPDATE
    writes 0 rows (so humans regain control without waiting 30s).
    immediately instead of waiting for LRU eviction to eventually rotate
    them off — the very next autoplay tick will no longer enqueue anything
    on their account. They only rejoin the roster once they go dormant again
    and get picked up by the normal wake-candidate selection
    (`list_dormant_candidates`), same as any other inactive account.

    Sends the same "what happened while you were away" report used on
    eviction (`_send_autoplay_report`) — no separate message/feed owner.
    No-op (single JSON read, no writes) when autoplay is off or the account
    was never on the roster.
    """
    if not is_inactive_autoplay_enabled(conn=conn):
        return False
    pid = int(player_id)
    roster = _load_roster(conn=conn)
    match = next(
        (item for item in roster if int(item.get("player_id") or 0) == pid), None
    )
    if match is None:
        return False
    remaining = [item for item in roster if int(item.get("player_id") or 0) != pid]
    _save_roster(remaining, conn=conn)
    _send_autoplay_report(conn, match)
    logger.info("inactive autoplay released player=%s (real login)", pid)
    return True


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


def seconds_until_economy_allowed(*, now: Optional[float] = None, conn=None) -> float:
    """GC-PERF-AUTOPLAY-003: standing RR gate (independent of wake + fleet due)."""
    data = _load_json(ECONOMY_LAST_KEY, conn=conn)
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
    return max(0.0, (last_at + economy_interval_sec()) - ts)


def run_inactive_autoplay_tick(
    conn,
    *,
    now: Optional[float] = None,
    force: bool = False,
    source: str = "fleet_worker",
) -> Dict[str, Any]:
    """Day-shift roster: tenure rotate, fill to shift_cap, RR economy + presence.

    GC-INACTIVE-SHIFT-001:
    1. Trim oversize to live ``shift_cap`` (deploy-safe).
    2. On wake waves: evict at most one tenure-expired member, then fill
       empty slots (batch default 1). Fresh ``last_seen`` + revisit window
       parks evicted accounts at the back of the dormant queue.
    3. Standing RR economy (``tick_per_cron=1``) + presence = full shift roster.

    GC-PERF-AUTOPLAY-001/002/003: short write TXs, busy lease, yield, budget;
    standing economy gated by ``economy_interval_sec`` (not every fleet tick).
    """
    ts = float(now if now is not None else _now())
    tick_t0 = time.perf_counter()
    write_commits = 0
    budget_stopped = False
    if not is_inactive_autoplay_enabled(conn=conn):
        return {
            "ok": False,
            "error": "disabled",
            "woke": [],
            "sessions": [],
            "hold_ms": 0,
            "write_commits": 0,
            "budget_stopped": False,
        }

    wait_wake = 0.0 if force else seconds_until_wake_allowed(now=ts, conn=conn)
    wait_economy = 0.0 if force else seconds_until_economy_allowed(now=ts, conn=conn)
    wake_due = force or wait_wake <= 0.0
    economy_due = force or wait_economy <= 0.0
    if not wake_due and not economy_due:
        return {
            "ok": True,
            "source": source,
            "skipped_interval": True,
            "woke": [],
            "woke_count": 0,
            "evicted_count": 0,
            "expired_count": 0,
            "sessions": [],
            "session_ticks": 0,
            "enqueued": 0,
            "hold_ms": int((time.perf_counter() - tick_t0) * 1000),
            "write_commits": 0,
            "budget_stopped": False,
            "wait_sec": wait_wake,
            "wait_economy_sec": wait_economy,
            "economy_interval_sec": economy_interval_sec(),
            "economy_ran": False,
            "chain_limit": INACTIVE_CHAIN_LIMIT,
        }

    short_tx = not in_transaction(conn)
    pause_ms = yield_ms() if short_tx else 0
    budget_ms = tick_budget_ms()
    tenure_sec = session_tenure_sec()
    live_cap = shift_cap(now=ts, conn=conn)

    def _hold_ms() -> int:
        return int((time.perf_counter() - tick_t0) * 1000)

    def _budget_exceeded() -> bool:
        return short_tx and _hold_ms() >= budget_ms

    def _yield_writer() -> None:
        if pause_ms > 0:
            time.sleep(pause_ms / 1000.0)

    def _mark_budget_stop(*, phase: str, ticks: int) -> None:
        nonlocal budget_stopped
        budget_stopped = True
        logger.info(
            "inactive autoplay budget_stop hold_ms=%s ticks=%s phase=%s",
            _hold_ms(),
            ticks,
            phase,
        )

    def _step(fn):
        nonlocal write_commits
        out = _write_step(conn, short_tx, fn)
        if short_tx:
            write_commits += 1
        return out

    acquired = _step(lambda: _try_acquire_tick_busy(conn=conn, now=ts))
    if not acquired:
        return {
            "ok": False,
            "error": "busy",
            "woke": [],
            "sessions": [],
            "hold_ms": _hold_ms(),
            "write_commits": write_commits,
            "budget_stopped": False,
        }

    try:
        roster = _prune_roster(conn, _load_roster(conn=conn))

        def _trim():
            nonlocal roster
            roster, trimmed = _trim_roster_to_cap(conn, roster, now=ts)
            return trimmed

        trimmed_count = int(_step(_trim) or 0)
        woke: List[Dict[str, Any]] = []
        evicted_count = int(trimmed_count)
        expired_count = 0
        wait = wait_wake

        if wake_due:
            batch = wake_batch_size()
            # Tenure-evict at most `batch` oldest-expired members (default 1).
            expired = [
                item
                for item in roster
                if (ts - float(item.get("joined_at") or ts)) >= tenure_sec
            ]
            if expired:
                expired.sort(
                    key=lambda item: float(
                        item.get("joined_at") or item.get("last_ticked_at") or 0
                    )
                )
                to_evict = expired[: min(batch, len(expired))]
                evict_ids = {int(item["player_id"]) for item in to_evict}
                roster = [
                    item
                    for item in roster
                    if int(item["player_id"]) not in evict_ids
                ]
                evicted_count += len(to_evict)
                expired_count += len(to_evict)
                for evicted_item in to_evict:
                    _step(lambda item=evicted_item: _send_autoplay_report(conn, item))

            room = max(0, live_cap - len(roster))
            if room > 0:
                wake_n = min(batch, room)
                active_ids = {int(s["player_id"]) for s in roster}
                candidates = list_dormant_candidates(
                    conn, now=ts, exclude_ids=active_ids, limit=400
                )

                def _pick_wake():
                    return _round_robin_pick(
                        conn, candidates, count=wake_n, cursor_key=CURSOR_KEY
                    )

                picks = _step(_pick_wake)
                for cand in picks:
                    if _budget_exceeded():
                        _mark_budget_stop(phase="wake", ticks=len(woke))
                        break
                    pid = int(cand["player_id"])
                    new_item: Dict[str, Any] = {
                        "player_id": pid,
                        "joined_at": ts,
                        "last_ticked_at": ts,
                        "last_action": None,
                        "builds_done": 0,
                        "research_done": 0,
                        "defense_done": 0,
                    }
                    roster.append(new_item)

                    def _wake_one(player_id=pid, item=new_item):
                        res = _run_player_economy(
                            conn, player_id, now=ts, is_wake=True
                        )
                        _apply_economy_result_to_roster_item(item, res)
                        return res

                    try:
                        woke.append(_step(_wake_one))
                        _yield_writer()
                    except Exception:
                        logger.exception(
                            "inactive autoplay wake failed player=%s", pid
                        )
            _step(
                lambda: _save_json(
                    WORKER_LAST_KEY,
                    {
                        "ok": True,
                        "at": ts,
                        "source": source,
                        "woke": len(woke),
                        "evicted": evicted_count,
                    },
                    conn=conn,
                )
            )

        # GC-PERF-AUTOPLAY-003: standing RR only on economy interval (or force).
        woke_ids = {int(w["player_id"]) for w in woke}
        session_results: List[Dict[str, Any]] = list(woke)
        ticked_ids: Set[int] = set(woke_ids)
        economy_ran = False
        if economy_due:
            tick_n = min(tick_per_cron(), len(roster))

            def _pick_tick():
                return _round_robin_pick(
                    conn, roster, count=tick_n, cursor_key=TICK_CURSOR_KEY
                )

            to_tick = _step(_pick_tick) if tick_n > 0 else []
            for item in to_tick:
                pid = int(item["player_id"])
                if pid in woke_ids:
                    continue
                if _budget_exceeded():
                    _mark_budget_stop(phase="standing", ticks=len(session_results))
                    break

                def _tick_one(player_id=pid, roster_item=item):
                    res = _run_player_economy(
                        conn,
                        player_id,
                        now=ts,
                        action_seq=int(roster_item.get("action_seq") or 0),
                        next_action_at=roster_item.get("next_action_at"),
                    )
                    _apply_economy_result_to_roster_item(roster_item, res)
                    return res

                try:
                    session_results.append(_step(_tick_one))
                    ticked_ids.add(pid)
                    _yield_writer()
                except Exception:
                    logger.exception(
                        "inactive autoplay roster tick failed player=%s", pid
                    )
            economy_ran = True
            _step(
                lambda: _save_json(
                    ECONOMY_LAST_KEY,
                    {
                        "ok": True,
                        "at": ts,
                        "source": source,
                        "ticks": len(session_results) - len(woke),
                    },
                    conn=conn,
                )
            )

        if ticked_ids:
            for item in roster:
                if int(item["player_id"]) in ticked_ids:
                    item["last_ticked_at"] = ts

        # Shift roster == visible online set.
        presence_ids: Set[int] = {int(item["player_id"]) for item in roster}

        def _flush_roster_presence():
            _touch_presence_bulk(conn, presence_ids, now=ts)
            _save_roster(roster, conn=conn)

        _step(_flush_roster_presence)

        hold_ms = _hold_ms()
        return {
            "ok": True,
            "source": source,
            "woke": woke,
            "woke_count": len(woke),
            "evicted_count": evicted_count,
            "expired_count": expired_count,
            "active_sessions": len(roster),
            "roster_size": len(roster),
            "session_ticks": len(session_results),
            "enqueued": sum(1 for r in session_results if r.get("enqueued")),
            "presence_visible_now": len(presence_ids),
            "online_visible_cap": live_cap,
            "day_target": day_target(now=ts),
            "shift_cap": live_cap,
            "tenure_sec": tenure_sec,
            "wait_sec": wait,
            "wait_economy_sec": wait_economy,
            "economy_interval_sec": economy_interval_sec(),
            "economy_ran": economy_ran,
            "revisit_sec": revisit_sec(),
            "tick_per_cron": tick_per_cron(),
            "inactive_threshold_sec": float(RANKING_INACTIVE_AFTER_SEC),
            "build_duration_cap": INACTIVE_BUILD_DURATION_CAP,
            "chain_limit": INACTIVE_CHAIN_LIMIT,
            "hold_ms": hold_ms,
            "write_commits": write_commits if short_tx else 0,
            "short_tx": short_tx,
            "budget_stopped": budget_stopped,
            "yield_ms": pause_ms,
            "tick_budget_ms": budget_ms,
        }
    finally:
        try:
            _step(lambda: _release_tick_busy(conn=conn))
        except Exception:
            logger.exception("inactive autoplay busy release failed")


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
