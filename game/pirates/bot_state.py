"""Faction bot playtime / personality state (EPIC-21 / GC-P09)."""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from ..db import table_exists

BOT_STATE_TABLE = "pirate_bot_state"

# Default windows (UTC minutes-of-day). Wrap supported when start > end.
FACTION_PLAYTIME: Dict[str, Dict[str, Any]] = {
    "crimson_corsairs": {
        "playtime_start_min": 0,
        "playtime_end_min": 1440,
        "skip_chance_pct": 8,
        "personality": "aggressive",
    },
    "iron_collective": {
        "playtime_start_min": 360,
        "playtime_end_min": 1200,
        "skip_chance_pct": 18,
        "personality": "turtle",
    },
    "void_cult": {
        "playtime_start_min": 1080,
        "playtime_end_min": 420,
        "skip_chance_pct": 12,
        "personality": "spy",
    },
    "nomad_swarm": {
        "playtime_start_min": 0,
        "playtime_end_min": 1440,
        "skip_chance_pct": 15,
        "personality": "swarm",
    },
    "ash_raiders": {
        "playtime_start_min": 0,
        "playtime_end_min": 1440,
        "skip_chance_pct": 10,
        "personality": "elite",
    },
    "salt_cartel": {
        "playtime_start_min": 300,
        "playtime_end_min": 1260,
        "skip_chance_pct": 14,
        "personality": "economy",
    },
}


def _now() -> float:
    return time.time()


def bot_state_schema_ready(conn) -> bool:
    return table_exists(conn, BOT_STATE_TABLE)


def utc_minute_of_day(now: Optional[float] = None) -> int:
    ts = float(now if now is not None else _now())
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return int(dt.hour * 60 + dt.minute)


def in_playtime_window(start_min: int, end_min: int, *, minute: int) -> bool:
    start = int(start_min) % 1440
    end = int(end_min) % 1440
    m = int(minute) % 1440
    if start == end:
        return True
    if start < end:
        return start <= m < end
    # wraps midnight
    return m >= start or m < end


def ensure_bot_state(
    conn,
    *,
    bot_player_id: int,
    faction_key: str,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Ensure pirate_bot_state row exists for a faction bot."""
    if not bot_state_schema_ready(conn):
        defaults = FACTION_PLAYTIME.get(str(faction_key), {})
        return {
            "bot_player_id": int(bot_player_id),
            "faction_key": str(faction_key),
            "personality": defaults.get("personality", "balanced"),
            "playtime_start_min": int(defaults.get("playtime_start_min", 0)),
            "playtime_end_min": int(defaults.get("playtime_end_min", 1440)),
            "skip_chance_pct": int(defaults.get("skip_chance_pct", 10)),
            "seed": int(bot_player_id),
            "next_action_at": None,
            "mood": {},
        }
    pid = int(bot_player_id)
    fk = str(faction_key)
    cur = conn.execute(
        "SELECT * FROM pirate_bot_state WHERE bot_player_id = ? LIMIT 1;",
        (pid,),
    )
    row = cur.fetchone()
    if row:
        return _row_to_state(row)

    defaults = FACTION_PLAYTIME.get(fk, {})
    ts = float(now if now is not None else _now())
    seed = (pid * 2654435761) & 0xFFFFFFFF
    conn.execute(
        """
        INSERT INTO pirate_bot_state (
            bot_player_id, faction_key, personality,
            playtime_start_min, playtime_end_min, skip_chance_pct,
            seed, next_action_at, mood_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '{}', ?);
        """,
        (
            pid,
            fk,
            str(defaults.get("personality", "balanced")),
            int(defaults.get("playtime_start_min", 0)),
            int(defaults.get("playtime_end_min", 1440)),
            int(defaults.get("skip_chance_pct", 10)),
            seed,
            ts,
        ),
    )
    cur = conn.execute(
        "SELECT * FROM pirate_bot_state WHERE bot_player_id = ? LIMIT 1;",
        (pid,),
    )
    return _row_to_state(cur.fetchone())


def _row_to_state(row: Mapping[str, Any]) -> Dict[str, Any]:
    import json

    try:
        mood = json.loads(row["mood_json"] or "{}")
    except Exception:
        mood = {}
    return {
        "bot_player_id": int(row["bot_player_id"]),
        "faction_key": row["faction_key"],
        "personality": row["personality"] or "balanced",
        "playtime_start_min": int(row["playtime_start_min"] or 0),
        "playtime_end_min": int(row["playtime_end_min"] or 1440),
        "skip_chance_pct": int(row["skip_chance_pct"] or 0),
        "seed": int(row["seed"] or 0),
        "next_action_at": float(row["next_action_at"]) if row["next_action_at"] else None,
        "mood": mood if isinstance(mood, dict) else {},
        "updated_at": float(row["updated_at"]) if row["updated_at"] else None,
    }


def bot_may_act(
    state: Mapping[str, Any],
    *,
    now: Optional[float] = None,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Playtime + skip_chance gate. Returns ``{ok, reason}``."""
    ts = float(now if now is not None else _now())
    minute = utc_minute_of_day(ts)
    if not in_playtime_window(
        int(state.get("playtime_start_min") or 0),
        int(state.get("playtime_end_min") or 1440),
        minute=minute,
    ):
        return {"ok": False, "reason": "outside_playtime", "minute": minute}

    next_at = state.get("next_action_at")
    if next_at is not None and float(next_at) > ts:
        return {"ok": False, "reason": "next_action_cooldown"}

    skip_pct = max(0, min(90, int(state.get("skip_chance_pct") or 0)))
    if skip_pct > 0:
        r = rng or random.Random(int(state.get("seed") or 0) ^ int(ts // 60))
        if r.randint(1, 100) <= skip_pct:
            return {"ok": False, "reason": "skip_chance"}
    return {"ok": True, "reason": "ok", "minute": minute}


def personality_raid_modifiers(personality_json: Mapping[str, Any]) -> Dict[str, float]:
    """Normalize faction personality_json into raid modifiers."""
    p = dict(personality_json or {})
    attack_bias = float(p.get("attack_bias", 0.6))
    spy_bias = float(p.get("spy_bias", 0.5))
    turtle = float(p.get("turtle", 0.2))
    attack_bias = max(0.15, min(1.0, attack_bias))
    spy_bias = max(0.0, min(1.0, spy_bias))
    turtle = max(0.0, min(1.0, turtle))
    # High attack_bias → lower opportunity floor; turtle raises floor vs defended targets.
    opportunity_floor = int(round(45 - 20 * attack_bias + 15 * turtle))
    opportunity_floor = max(20, min(55, opportunity_floor))
    fleet_fraction = 0.45 + 0.25 * attack_bias - 0.1 * turtle
    fleet_fraction = max(0.35, min(0.8, fleet_fraction))
    return {
        "attack_bias": attack_bias,
        "spy_bias": spy_bias,
        "turtle": turtle,
        "opportunity_floor": float(opportunity_floor),
        "fleet_fraction": fleet_fraction,
    }
