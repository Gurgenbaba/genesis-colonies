"""Admin KPIs + kill-switch payload for Inactive Autoplay (EPIC-26 / GC-2608).

Mirrors the pirate admin pattern (`game/pirates/admin.py`) instead of introducing
a new admin pattern: same runtime_state Soft-On/Off kill-switch, same "last
worker run" snapshot idea, just backed by `game.inactive_autoplay`.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from .inactive_autoplay import (
    INACTIVE_BUILD_DURATION_CAP,
    INACTIVE_CHAIN_LIMIT,
    INACTIVE_RESEARCH_DURATION_CAP,
    day_target,
    get_last_worker_run,
    get_roster_snapshot,
    is_inactive_autoplay_enabled,
    max_concurrent_sessions,
    online_visible_cap,
    revisit_sec,
    run_inactive_autoplay_tick,
    seconds_until_wake_allowed,
    session_tenure_sec,
    set_inactive_autoplay_enabled,
    shift_cap,
    tick_per_cron,
    wake_batch_size,
    wake_interval_sec,
)


def build_admin_inactive_autoplay_payload(conn) -> Dict[str, Any]:
    enabled = is_inactive_autoplay_enabled(conn=conn)
    roster = get_roster_snapshot(conn=conn)
    last = get_last_worker_run(conn=conn)

    from .fleet_worker import get_stage_skip_streak
    from .models import ONLINE_WINDOW_SEC, get_registered_player_count

    skip_streak = get_stage_skip_streak("inactive_autoplay", conn=conn)

    # GC-2617: live count of roster members currently inside the online
    # window — the number that actually matters for "does this look
    # realistic", independent of total roster size.
    presence_visible_now = 0
    if roster:
        ids = [int(item["player_id"]) for item in roster]
        placeholders = ",".join("?" * len(ids))
        cutoff = time.time() - ONLINE_WINDOW_SEC
        try:
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS c FROM players
                WHERE id IN ({placeholders}) AND last_seen >= ?;
                """,
                [*ids, cutoff],
            ).fetchone()
            presence_visible_now = int(row["c"] or 0) if row else 0
        except Exception:
            presence_visible_now = 0

    now_ts = time.time()
    tenure = session_tenure_sec()
    live_shift = shift_cap(now=now_ts, conn=conn)
    live_day = day_target(now=now_ts)

    roster_rows: List[Dict[str, Any]] = []
    if roster:
        ids = [int(item["player_id"]) for item in roster[:100]]
        placeholders = ",".join("?" * len(ids))
        info_by_id: Dict[int, Any] = {}
        try:
            # GC-2614: username lives on `users`, not `players` (players.name is
            # the in-game display name) — join like every other admin/list
            # surface already does (e.g. game/vote_rewards.py admin stats, game/pirates/accounts.py).
            cur = conn.execute(
                f"""
                SELECT p.id AS id, u.username AS username, p.last_seen AS last_seen
                FROM players p
                JOIN users u ON u.id = p.id
                WHERE p.id IN ({placeholders});
                """,
                ids,
            )
            for row in cur.fetchall():
                info_by_id[int(row["id"])] = row
        except Exception:
            info_by_id = {}
        for item in roster[:100]:
            pid = int(item["player_id"])
            row = info_by_id.get(pid)
            joined_at = float(item.get("joined_at") or 0) or None
            remaining = None
            if joined_at is not None:
                remaining = max(0.0, tenure - (now_ts - joined_at))
            roster_rows.append(
                {
                    "player_id": pid,
                    "username": row["username"] if row else None,
                    "last_seen": float(row["last_seen"]) if row and row["last_seen"] else None,
                    "joined_at": item.get("joined_at"),
                    "last_ticked_at": item.get("last_ticked_at"),
                    "last_action": item.get("last_action"),
                    "builds_done": int(item.get("builds_done") or 0),
                    "research_done": int(item.get("research_done") or 0),
                    "defense_done": int(item.get("defense_done") or 0),
                    "tenure_remaining_sec": (
                        round(remaining, 1) if remaining is not None else None
                    ),
                }
            )

    return {
        "ok": True,
        "enabled": enabled,
        "roster_size": len(roster),
        "roster": roster_rows,
        "worker_last": {
            "ok": bool(last.get("ok")),
            "at": last.get("at"),
            "source": last.get("source"),
            "woke": int(last.get("woke") or 0),
        },
        "kpis": {
            "roster_size": len(roster),
            "woke_last_cycle": int(last.get("woke") or 0),
            "evicted_last_cycle": int(last.get("evicted") or 0),
            "wait_sec": round(seconds_until_wake_allowed(conn=conn), 1),
            "post_maint_skip_streak": skip_streak,
            "presence_visible_now": presence_visible_now,
            "shift_cap": live_shift,
            "day_target": live_day,
            "tenure_sec": tenure,
        },
        "config": {
            "batch": wake_batch_size(),
            "interval_sec": wake_interval_sec(),
            "revisit_sec": revisit_sec(),
            "max_roster": max_concurrent_sessions(),
            "shift_cap": live_shift,
            "day_target": live_day,
            "tenure_sec": tenure,
            "tick_per_cron": tick_per_cron(),
            "build_duration_cap": INACTIVE_BUILD_DURATION_CAP,
            "research_duration_cap": INACTIVE_RESEARCH_DURATION_CAP,
            "chain_limit": INACTIVE_CHAIN_LIMIT,
            "online_visible_cap": online_visible_cap(conn=conn, now=now_ts),
            "real_player_count": int(get_registered_player_count(conn=conn)),
        },
    }


def admin_set_inactive_autoplay(conn, enabled: bool) -> Dict[str, Any]:
    set_inactive_autoplay_enabled(bool(enabled), conn=conn)
    return {
        "ok": True,
        "enabled": is_inactive_autoplay_enabled(conn=conn),
    }


def admin_force_tick_inactive_autoplay(conn) -> Dict[str, Any]:
    """GC-2613: LiveOps — run one roster tick immediately, bypassing the wake-interval guard.

    Reuses the canonical `run_inactive_autoplay_tick` owner (same function the
    fleet-worker cron calls) with `force=True`; no parallel wake/tick logic.
    Lets admins see "2-3 accounts wake up now" on demand instead of waiting for
    the next embedded-cron/fleet-worker pass (which is off by default outside
    production, see `game.config.is_embedded_cron_enabled`).
    """
    result = run_inactive_autoplay_tick(conn, force=True, source="admin")
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "woke_count": int(result.get("woke_count") or 0),
        "evicted_count": int(result.get("evicted_count") or 0),
        "session_ticks": int(result.get("session_ticks") or 0),
        "enqueued": int(result.get("enqueued") or 0),
        "roster_size": int(result.get("roster_size") or 0),
        "woke": [
            {"player_id": int(w.get("player_id"))}
            for w in (result.get("woke") or [])
            if w.get("player_id") is not None
        ],
    }
