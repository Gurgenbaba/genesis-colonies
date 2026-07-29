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

from .auto_empire import (
    AUTOPLAY_STANDING_IDLE_CHANCE,
    personality_for_player,
    plan_passive_planet_tick,
)
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
PRESENCE_CURSOR_KEY = "inactive_autoplay_presence_cursor"

# Soft caps so queues turn over on fleet-cron cadence (still slower than pirate 90s).
INACTIVE_BUILD_DURATION_CAP = 900  # 15 min
INACTIVE_RESEARCH_DURATION_CAP = 1200  # 20 min
INACTIVE_CHAIN_LIMIT = 3

# Soft floor so empty dormant empires can enqueue (far below pirate seed).
INACTIVE_RESOURCE_FLOOR = {
    "metal": 75_000,
    "crystal": 50_000,
    "fuel_cells": 15_000,
}

# Revisit: pull stale accounts onto sticky roster.
DEFAULT_REVISIT_SEC = 36 * 3600  # 36h — stay under 3-day inactive badge
DEFAULT_WAKE_INTERVAL_SEC = 10 * 60
# GC-2620: small concurrent sticky roster (5–8 band); slow wake + economy cadence.
DEFAULT_BATCH = 1
DEFAULT_MAX_ROSTER = 6
DEFAULT_TICK_PER_CRON = 3
MIN_ROSTER_CAP = 4
MAX_ROSTER_CAP = 12
# GC-2617: how many roster members may look "online" (fresh last_seen) at the
# same instant, as a percent of the real registered player base — keeps a
# small server from ever showing an implausible wall of simultaneous logins.
DEFAULT_ONLINE_PERCENT = 15.0
MIN_ONLINE_VISIBLE = 2
MAX_ONLINE_VISIBLE = 40

ENABLED_ENV = "GC_INACTIVE_AUTOPLAY_ENABLED"
BATCH_ENV = "GC_INACTIVE_AUTOPLAY_BATCH"
INTERVAL_ENV = "GC_INACTIVE_AUTOPLAY_INTERVAL_SEC"
REVISIT_ENV = "GC_INACTIVE_AUTOPLAY_REVISIT_SEC"
MAX_ROSTER_ENV = "GC_INACTIVE_AUTOPLAY_MAX_SESSIONS"  # keep env name for ops
TICK_ENV = "GC_INACTIVE_AUTOPLAY_TICK_PER_CRON"
ONLINE_PERCENT_ENV = "GC_INACTIVE_AUTOPLAY_ONLINE_PERCENT"
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
    """Roster size cap (env name kept as MAX_SESSIONS for ops compatibility).

    GC-2620: hard clamp 4–12 so ops cannot reopen a mass concurrent roster.
    """
    return max(MIN_ROSTER_CAP, min(MAX_ROSTER_CAP, _env_int(MAX_ROSTER_ENV, DEFAULT_MAX_ROSTER)))


def tick_per_cron() -> int:
    return max(1, min(20, _env_int(TICK_ENV, DEFAULT_TICK_PER_CRON)))


def online_percent() -> float:
    """GC-2617: max share of the real registered player base that may look
    'online' from inactive-autoplay presence at any single instant."""
    raw = os.environ.get(ONLINE_PERCENT_ENV)
    try:
        val = float(raw) if raw not in (None, "") else DEFAULT_ONLINE_PERCENT
    except (TypeError, ValueError):
        val = DEFAULT_ONLINE_PERCENT
    return max(1.0, min(50.0, val))


def online_visible_cap(*, conn=None) -> int:
    """GC-2617: how many sticky-roster accounts may be presence-touched (i.e.
    look 'online') in the same tick. Scaled to the real registered player
    count instead of the roster cap, so a small universe never shows an
    implausible wall of simultaneous logins regardless of roster size.
    """
    if conn is None:
        return MIN_ONLINE_VISIBLE
    try:
        from .models import get_registered_player_count

        real = int(get_registered_player_count(conn=conn))
    except Exception:
        return MIN_ONLINE_VISIBLE
    dynamic = int(round(real * online_percent() / 100.0))
    return max(MIN_ONLINE_VISIBLE, min(MAX_ONLINE_VISIBLE, dynamic))


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


def _touch_presence_bulk(conn, player_ids: Sequence[int], *, now: float) -> None:
    """Batched `last_seen` refresh for a set of roster members in one query.

    GC-2614 originally touched the *entire* sticky roster here every cron tick
    ("always online"), but that let the visible online count grow with the
    roster cap (up to 60+) regardless of how many real players the universe
    actually has — implausible on a small server. GC-2617: callers now pass a
    small, dynamically-sized rotating subset (`online_visible_cap`, percent of
    the real player base) instead of the whole roster, so only that bounded
    subset ever looks "online" at once while the rest of the roster keeps
    building silently in the background until its own turn comes up.
    """
    ids = sorted({int(pid) for pid in player_ids if int(pid) > 0})
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    try:
        conn.execute(
            f"UPDATE players SET last_seen = ? WHERE id IN ({placeholders});",
            [float(now), *ids],
        )
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
            roster.append(
                {
                    "player_id": pid,
                    "joined_at": item.get("joined_at"),
                    "last_ticked_at": item.get("last_ticked_at"),
                    "last_action": item.get("last_action"),
                    "builds_done": int(item.get("builds_done") or 0),
                    "research_done": int(item.get("research_done") or 0),
                    "defense_done": int(item.get("defense_done") or 0),
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
            }
        )
    return kept


def _trim_roster_to_cap(
    conn, roster: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int]:
    """GC-2620: immediately LRU-evict excess above max_concurrent_sessions.

    Deploy-safe shrink when the stored roster still holds a pre-cap size
    (e.g. 60 → 6). Uses the same inbox report owner as wake-wave LRU eviction.
    """
    cap = max_concurrent_sessions()
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
    metal = max(float(row["metal"] or 0), float(INACTIVE_RESOURCE_FLOOR["metal"]))
    crystal = max(float(row["crystal"] or 0), float(INACTIVE_RESOURCE_FLOOR["crystal"]))
    fuel = max(float(row["fuel_cells"] or 0), float(INACTIVE_RESOURCE_FLOOR["fuel_cells"]))
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


def _run_player_economy(
    conn,
    player_id: int,
    *,
    now: float,
    is_wake: bool = False,
) -> Dict[str, Any]:
    """Run one economy tick for a sticky-roster account.

    `is_wake` (GC-2618): True only for the exact tick a dormant account joins
    the roster — that tick must stay deterministic (a "just logged in" moment
    always does something, matching `test_inactive_autoplay_wake_touches_...`).
    Standing RR ticks (`is_wake=False`, the default) pass
    `AUTOPLAY_STANDING_IDLE_CHANCE` so an established account occasionally
    idles for a round instead of a perfectly monotonic staircase every cycle.
    """
    from .models import get_homeworld, get_planets_by_player

    home = get_homeworld(player_id, conn=conn)
    if not home:
        return {"ok": False, "error": "no_homeworld", "player_id": player_id}

    home_id = int(home["id"])
    floor = _ensure_resource_floor(conn, home_id)
    planets = get_planets_by_player(player_id, conn=conn) or [home]
    personality = personality_for_player(player_id)
    idle_chance = 0.0 if is_wake else AUTOPLAY_STANDING_IDLE_CHANCE
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
                    personality=personality,
                    build_duration_cap=INACTIVE_BUILD_DURATION_CAP,
                    research_duration_cap=INACTIVE_RESEARCH_DURATION_CAP,
                    source="inactive_autoplay",
                    update_scores=True,
                    chain_limit=INACTIVE_CHAIN_LIMIT,
                    idle_chance=idle_chance,
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
    finished_any = any((r.get("finished") or {}) for r in results)
    finished_totals = {"buildings": 0, "research": 0, "defense": 0, "shipyard": 0}
    for r in results:
        fin = r.get("finished") or {}
        for key in finished_totals:
            try:
                finished_totals[key] += int(fin.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return {
        "ok": True,
        "player_id": player_id,
        "economy": results,
        "enqueued": enqueued,
        "finished": finished_any,
        "finished_totals": finished_totals,
        "last_action": _describe_last_action(results),
        "resource_floor": floor,
    }


def get_roster_snapshot(*, conn=None) -> List[Dict[str, Any]]:
    """Public accessor for admin/API surfaces (GC-2608) — do not mutate."""
    return _load_roster(conn=conn)


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
            "Während du offline warst, hat die Kolonieverwaltung deine Kolonie automatisch weitergeführt:",
            locale=loc,
        )
        subject = tr(
            "inactive_autoplay_report_subject",
            "Automatisierter Betriebsbericht",
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
    `require_admin` / `require_login_api`) — whenever it actually touches a
    player's `last_seen` (throttled to once/30s there). If that player is
    currently on the inactive-autoplay sticky roster, they are removed
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


def run_inactive_autoplay_tick(
    conn,
    *,
    now: Optional[float] = None,
    force: bool = False,
    source: str = "fleet_worker",
) -> Dict[str, Any]:
    """Grow sticky roster; round-robin economy+presence every fleet cron.

    GC-2609: once the roster hits its cap, the `batch`-oldest members (by
    `last_ticked_at`) are evicted back to the dormant pool before new accounts
    join (LRU rotation) — so coverage cycles through the *entire* dormant
    pool over time instead of the first N accounts holding the roster forever.

    GC-2620: after prune, immediately LRU-trim any stored oversize down to
    `max_concurrent_sessions()` so a deploy that lowers the cap does not keep
    a mass concurrent roster until many wake-wave batch replacements finish.
    """
    ts = float(now if now is not None else _now())
    if not is_inactive_autoplay_enabled(conn=conn):
        return {"ok": False, "error": "disabled", "woke": [], "sessions": []}

    roster = _prune_roster(conn, _load_roster(conn=conn))
    roster, trimmed_count = _trim_roster_to_cap(conn, roster)
    woke: List[Dict[str, Any]] = []
    evicted_count = int(trimmed_count)
    wait = 0.0 if force else seconds_until_wake_allowed(now=ts, conn=conn)

    if wait <= 0:
        batch = wake_batch_size()
        room = max_concurrent_sessions() - len(roster)
        if room <= 0:
            evict_n = min(batch, len(roster))
            if evict_n > 0:
                roster.sort(
                    key=lambda item: float(
                        item.get("last_ticked_at") or item.get("joined_at") or 0
                    )
                )
                to_evict = roster[:evict_n]
                roster = roster[evict_n:]
                evicted_count += evict_n
                room = evict_n
                for evicted_item in to_evict:
                    _send_autoplay_report(conn, evicted_item)
        if room > 0:
            batch = min(batch, room)
            active_ids = {int(s["player_id"]) for s in roster}
            candidates = list_dormant_candidates(
                conn, now=ts, exclude_ids=active_ids, limit=400
            )
            picks = _round_robin_pick(conn, candidates, count=batch, cursor_key=CURSOR_KEY)
            for cand in picks:
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
                try:
                    res = _run_player_economy(conn, pid, now=ts, is_wake=True)
                    woke.append(res)
                    _apply_economy_result_to_roster_item(new_item, res)
                except Exception:
                    logger.exception("inactive autoplay wake failed player=%s", pid)
            _save_json(
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

    # Always tick a RR slice of the sticky roster (autonomous building).
    tick_n = min(tick_per_cron(), len(roster))
    to_tick = _round_robin_pick(
        conn, roster, count=tick_n, cursor_key=TICK_CURSOR_KEY
    )
    # Avoid double-running just-woke players in the same tick.
    woke_ids = {int(w["player_id"]) for w in woke}
    session_results: List[Dict[str, Any]] = list(woke)
    ticked_ids: Set[int] = set(woke_ids)
    for item in to_tick:
        pid = int(item["player_id"])
        if pid in woke_ids:
            continue
        try:
            res = _run_player_economy(conn, pid, now=ts)
            session_results.append(res)
            _apply_economy_result_to_roster_item(item, res)
            ticked_ids.add(pid)
        except Exception:
            logger.exception("inactive autoplay roster tick failed player=%s", pid)

    if ticked_ids:
        for item in roster:
            if int(item["player_id"]) in ticked_ids:
                item["last_ticked_at"] = ts

    # GC-2617: presence ("online") is bounded independently of roster size,
    # but freshly-woken accounts are always touched immediately — that one
    # exception is required so a just-woken account instantly clears the
    # multi-day ranking-inactive flag (`RANKING_INACTIVE_AFTER_SEC`) instead
    # of waiting for its turn in the rotation. Ongoing RR economy ticks
    # (`ticked_ids`) do NOT force a presence touch — the whole roster keeps
    # building in the background regardless of who currently "looks online".
    # On top of the wake exception, a small, independently-rotating subset of
    # the roster (its own cursor, sized by `online_visible_cap` = percent of
    # the *real* player base) gets touched each tick — that rotation is what
    # actually bounds the simultaneous "online" count on a small server,
    # instead of it scaling with the roster cap, and it still cycles every
    # standing member through "online" often enough to stay well under the
    # multi-day ranking threshold.
    presence_ids: Set[int] = set(woke_ids)
    online_room = online_visible_cap(conn=conn) - len(presence_ids)
    if online_room > 0 and roster:
        extra = _round_robin_pick(
            conn, roster, count=online_room, cursor_key=PRESENCE_CURSOR_KEY
        )
        presence_ids.update(int(item["player_id"]) for item in extra)
    _touch_presence_bulk(conn, presence_ids, now=ts)

    _save_roster(roster, conn=conn)

    return {
        "ok": True,
        "source": source,
        "woke": woke,
        "woke_count": len(woke),
        "evicted_count": evicted_count,
        "expired_count": 0,
        "active_sessions": len(roster),
        "roster_size": len(roster),
        "session_ticks": len(session_results),
        "enqueued": sum(1 for r in session_results if r.get("enqueued")),
        "presence_visible_now": len(presence_ids),
        "online_visible_cap": online_visible_cap(conn=conn),
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
