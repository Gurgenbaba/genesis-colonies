"""
GC-WB-TAME — World Boss companions (tame + overview missions).

Owner domain remains EPIC-20 / ``game/world_boss.py``. This module holds catch,
ownership, and Ark-Token mission helpers — no combat/fleet math.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Mapping, Optional

from .db import table_exists
from .story.free_shop import ARK_TOKEN_KEY

logger = logging.getLogger(__name__)

COMPANIONS_TABLE = "player_boss_companions"
CATCH_STATE_TABLE = "player_boss_catch_state"
MISSIONS_TABLE = "player_boss_missions"
CAPACITY_TABLE = "player_boss_capacity"

CATCH_CHANCE = 0.10
CATCH_COST_SEC = 10 * 3600  # 10h Timekeeper
CATCH_COOLDOWN_SEC = 3600  # 1h between attempts
MISSION_DURATION_SEC = 4 * 3600  # default = strike duration
BASE_COMPANION_CAPACITY = 1
MAX_COMPANION_CAPACITY = 4

MISSION_STATUS_IDLE = "idle"
MISSION_STATUS_AWAY = "away"
MISSION_STATUS_READY = "ready"

MISSION_OUTCOME_SUCCESS = "success"
MISSION_OUTCOME_FAIL = "fail"

# Always offer these three picks when idle (server-authored).
MISSION_VARIANTS: Dict[str, Dict[str, Any]] = {
    "patrol": {
        "variant_key": "patrol",
        "title_key": "titan_mission_patrol",
        "hint_key": "titan_mission_patrol_hint",
        "duration_sec": 2 * 3600,
        "fail_chance": 0.10,
        "reward_bonus": 0,
        "risk_key": "titan_mission_risk_low",
    },
    "strike": {
        "variant_key": "strike",
        "title_key": "titan_mission_strike",
        "hint_key": "titan_mission_strike_hint",
        "duration_sec": 4 * 3600,
        "fail_chance": 0.25,
        "reward_bonus": 2,
        "risk_key": "titan_mission_risk_mid",
    },
    "void_run": {
        "variant_key": "void_run",
        "title_key": "titan_mission_void_run",
        "hint_key": "titan_mission_void_run_hint",
        "duration_sec": 8 * 3600,
        "fail_chance": 0.40,
        "reward_bonus": 5,
        "risk_key": "titan_mission_risk_high",
    },
}

# Flavor stats for popover (display-only; no combat effect).
COMPANION_FLAVOR: Dict[str, Dict[str, Any]] = {
    "ancient_leviathan": {
        "power": 92,
        "endurance": 98,
        "cunning": 55,
        "reward_tokens": 3,
        "slot": 0,
        "left_pct": 22,
        "top_pct": 58,
    },
    "void_titan": {
        "power": 96,
        "endurance": 88,
        "cunning": 70,
        "reward_tokens": 4,
        "slot": 1,
        "left_pct": 41,
        "top_pct": 44,
    },
    "planet_eater": {
        "power": 90,
        "endurance": 94,
        "cunning": 62,
        "reward_tokens": 3,
        "slot": 2,
        "left_pct": 60,
        "top_pct": 56,
    },
    "rogue_ai_nexus": {
        "power": 84,
        "endurance": 72,
        "cunning": 99,
        "reward_tokens": 2,
        "slot": 3,
        "left_pct": 78,
        "top_pct": 42,
    },
}


def _now() -> float:
    return float(time.time())


def companions_schema_ready(conn) -> bool:
    return bool(
        table_exists(conn, COMPANIONS_TABLE)
        and table_exists(conn, CATCH_STATE_TABLE)
        and table_exists(conn, MISSIONS_TABLE)
    )


def capacity_schema_ready(conn) -> bool:
    return bool(table_exists(conn, CAPACITY_TABLE))


def owned_companion_count(player_id: int, *, conn) -> int:
    if not companions_schema_ready(conn):
        return 0
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM player_boss_companions WHERE player_id = ?;
        """,
        (int(player_id),),
    ).fetchone()
    return int(row["n"] or 0) if row else 0


def get_bonus_slots(player_id: int, *, conn) -> int:
    if not capacity_schema_ready(conn):
        return 0
    row = conn.execute(
        """
        SELECT bonus_slots FROM player_boss_capacity WHERE player_id = ? LIMIT 1;
        """,
        (int(player_id),),
    ).fetchone()
    return max(0, int(row["bonus_slots"] or 0)) if row else 0


def get_companion_capacity(player_id: int, *, conn) -> int:
    """Effective Titan companion slots (base + shop). Admins always get the max."""
    from .chat import is_admin

    if is_admin(int(player_id), conn):
        return int(MAX_COMPANION_CAPACITY)
    bonus = get_bonus_slots(int(player_id), conn=conn)
    return min(int(MAX_COMPANION_CAPACITY), int(BASE_COMPANION_CAPACITY) + bonus)


def grant_companion_slot(
    player_id: int,
    *,
    conn,
    source: str = "shop",
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Add +1 bonus companion slot (capped). Returns capacity state."""
    if not capacity_schema_ready(conn):
        return {"ok": False, "error": "capacity_unavailable"}
    pid = int(player_id)
    ts = float(now if now is not None else _now())
    before = get_companion_capacity(pid, conn=conn)
    if before >= int(MAX_COMPANION_CAPACITY):
        return {
            "ok": False,
            "error": "already_owned",
            "capacity": before,
            "bonus_slots": get_bonus_slots(pid, conn=conn),
            "max_capacity": int(MAX_COMPANION_CAPACITY),
        }
    conn.execute(
        """
        INSERT INTO player_boss_capacity (player_id, bonus_slots, updated_at)
        VALUES (?, 1, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            bonus_slots = MIN(
                ?,
                player_boss_capacity.bonus_slots + 1
            ),
            updated_at = excluded.updated_at;
        """,
        (
            pid,
            ts,
            int(MAX_COMPANION_CAPACITY) - int(BASE_COMPANION_CAPACITY),
        ),
    )
    after = get_companion_capacity(pid, conn=conn)
    logger.info(
        "companion_slot_granted player=%s source=%s capacity=%s→%s",
        pid,
        str(source or "shop")[:80],
        before,
        after,
    )
    return {
        "ok": True,
        "capacity": after,
        "bonus_slots": get_bonus_slots(pid, conn=conn),
        "max_capacity": int(MAX_COMPANION_CAPACITY),
        "granted": max(0, after - before),
    }


def mission_reward_tokens(
    boss_key: str,
    capacity: int = BASE_COMPANION_CAPACITY,
    *,
    variant_key: str = "strike",
) -> int:
    flavor = COMPANION_FLAVOR.get(str(boss_key) or "", {})
    base = int(flavor.get("reward_tokens") or 3)
    cap_bonus = max(0, int(capacity) - int(BASE_COMPANION_CAPACITY))
    variant = MISSION_VARIANTS.get(str(variant_key) or "strike") or MISSION_VARIANTS["strike"]
    return base + cap_bonus + int(variant.get("reward_bonus") or 0)


def get_mission_variant(variant_key: str) -> Optional[Dict[str, Any]]:
    key = str(variant_key or "").strip().lower()
    spec = MISSION_VARIANTS.get(key)
    return dict(spec) if spec else None


def list_mission_offers(boss_key: str, capacity: int) -> List[Dict[str, Any]]:
    """Three fixed server-authored mission picks for the overview popover."""
    offers: List[Dict[str, Any]] = []
    for key in ("patrol", "strike", "void_run"):
        spec = MISSION_VARIANTS[key]
        offers.append(
            {
                "variant_key": key,
                "title_key": spec["title_key"],
                "hint_key": spec["hint_key"],
                "risk_key": spec["risk_key"],
                "duration_sec": int(spec["duration_sec"]),
                "fail_chance": float(spec["fail_chance"]),
                "success_chance": round(1.0 - float(spec["fail_chance"]), 2),
                "reward_tokens": mission_reward_tokens(
                    boss_key, capacity, variant_key=key
                ),
            }
        )
    return offers


def _mission_columns_ready(conn) -> bool:
    from .db import column_exists

    return bool(
        column_exists(conn, MISSIONS_TABLE, "variant_key")
        and column_exists(conn, MISSIONS_TABLE, "fail_chance")
        and column_exists(conn, MISSIONS_TABLE, "outcome")
    )


def list_owned_companions(player_id: int, *, conn) -> List[Dict[str, Any]]:
    if not companions_schema_ready(conn):
        return []
    rows = conn.execute(
        """
        SELECT player_id, boss_key, tamed_at, tamed_event_id
        FROM player_boss_companions
        WHERE player_id = ?
        ORDER BY tamed_at ASC;
        """,
        (int(player_id),),
    ).fetchall()
    return [
        {
            "player_id": int(r["player_id"]),
            "boss_key": str(r["boss_key"]),
            "tamed_at": float(r["tamed_at"] or 0),
            "tamed_event_id": int(r["tamed_event_id"]) if r["tamed_event_id"] is not None else None,
        }
        for r in rows
    ]


def has_companion(player_id: int, boss_key: str, *, conn) -> bool:
    if not companions_schema_ready(conn):
        return False
    row = conn.execute(
        """
        SELECT 1 FROM player_boss_companions
        WHERE player_id = ? AND boss_key = ?
        LIMIT 1;
        """,
        (int(player_id), str(boss_key)),
    ).fetchone()
    return bool(row)


def get_catch_state(player_id: int, boss_key: str, *, conn) -> Dict[str, Any]:
    empty = {
        "boss_key": str(boss_key),
        "last_catch_at": None,
        "cooldown_until": 0.0,
        "attempt_count": 0,
        "on_cooldown": False,
    }
    if not companions_schema_ready(conn):
        return empty
    row = conn.execute(
        """
        SELECT last_catch_at, cooldown_until, attempt_count
        FROM player_boss_catch_state
        WHERE player_id = ? AND boss_key = ?
        LIMIT 1;
        """,
        (int(player_id), str(boss_key)),
    ).fetchone()
    if not row:
        return empty
    cd = float(row["cooldown_until"] or 0)
    return {
        "boss_key": str(boss_key),
        "last_catch_at": float(row["last_catch_at"]) if row["last_catch_at"] is not None else None,
        "cooldown_until": cd,
        "attempt_count": int(row["attempt_count"] or 0),
        "on_cooldown": cd > _now(),
    }


def _upsert_catch_attempt(
    player_id: int,
    boss_key: str,
    *,
    conn,
    now: float,
) -> float:
    cooldown_until = float(now) + float(CATCH_COOLDOWN_SEC)
    conn.execute(
        """
        INSERT INTO player_boss_catch_state (
            player_id, boss_key, last_catch_at, cooldown_until, attempt_count
        ) VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(player_id, boss_key) DO UPDATE SET
            last_catch_at = excluded.last_catch_at,
            cooldown_until = excluded.cooldown_until,
            attempt_count = player_boss_catch_state.attempt_count + 1;
        """,
        (int(player_id), str(boss_key), float(now), cooldown_until),
    )
    return cooldown_until


def build_catch_info_for_event(
    player_id: Optional[int],
    event: Mapping[str, Any],
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Server-authored catch CTA state for one event card."""
    from .world_boss import STATUS_ACTIVE, hp_phase_from_ratio

    ts = float(now if now is not None else _now())
    boss_key = str(event.get("boss_key") or "")
    max_hp = max(1, int(event.get("max_hp") or 1))
    current_hp = max(0, int(event.get("current_hp") or 0))
    phase = int(hp_phase_from_ratio(float(current_hp) / float(max_hp)))
    info: Dict[str, Any] = {
        "ready": companions_schema_ready(conn),
        "boss_key": boss_key,
        "phase": phase,
        "phase_ok": phase == 3 and str(event.get("status") or "") == STATUS_ACTIVE,
        "chance": float(CATCH_CHANCE),
        "cost_sec": int(CATCH_COST_SEC),
        "cooldown_sec": int(CATCH_COOLDOWN_SEC),
        "owned": False,
        "can_attempt": False,
        "block_reason": "",
        "cooldown_until": 0.0,
        "attempt_count": 0,
        "timekeeper_balance_sec": 0,
        "capacity": int(BASE_COMPANION_CAPACITY),
        "owned_count": 0,
        "slots_free": int(BASE_COMPANION_CAPACITY),
    }
    if player_id is None or not info["ready"] or not boss_key:
        info["block_reason"] = "unavailable"
        return info

    owned = has_companion(int(player_id), boss_key, conn=conn)
    info["owned"] = owned
    capacity = get_companion_capacity(int(player_id), conn=conn)
    owned_count = owned_companion_count(int(player_id), conn=conn)
    info["capacity"] = capacity
    info["owned_count"] = owned_count
    info["slots_free"] = max(0, capacity - owned_count)
    catch = get_catch_state(int(player_id), boss_key, conn=conn)
    info["cooldown_until"] = float(catch.get("cooldown_until") or 0)
    info["attempt_count"] = int(catch.get("attempt_count") or 0)

    from .timekeeper import get_balance

    bal = int(get_balance(int(player_id), conn=conn))
    info["timekeeper_balance_sec"] = bal

    if owned:
        info["block_reason"] = "already_tamed"
        return info
    if owned_count >= capacity:
        info["block_reason"] = "capacity_full"
        return info
    if str(event.get("status") or "") != STATUS_ACTIVE:
        info["block_reason"] = "inactive"
        return info
    if phase != 3:
        info["block_reason"] = "phase_locked"
        return info
    if float(info["cooldown_until"]) > ts:
        info["block_reason"] = "catch_cooldown"
        return info
    if bal < int(CATCH_COST_SEC):
        info["block_reason"] = "insufficient_timekeeper"
        return info
    info["can_attempt"] = True
    return info


def attempt_tame(
    player_id: int,
    event_id: int,
    *,
    conn,
    now: Optional[float] = None,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Spend TK, roll catch, optionally grant companion. Server RNG only."""
    from .timekeeper import InsufficientTimekeeperBalance, debit
    from .world_boss import STATUS_ACTIVE, get_event_by_id, hp_phase_from_ratio

    if not companions_schema_ready(conn):
        return {"ok": False, "error": "companions_unavailable"}

    ts = float(now if now is not None else _now())
    event = get_event_by_id(int(event_id), conn=conn)
    if not event:
        return {"ok": False, "error": "inactive"}

    boss_key = str(event.get("boss_key") or "")
    if not boss_key:
        return {"ok": False, "error": "invalid_boss"}

    if has_companion(int(player_id), boss_key, conn=conn):
        return {"ok": False, "error": "already_tamed"}

    if str(event.get("status") or "") != STATUS_ACTIVE:
        return {"ok": False, "error": "inactive"}

    capacity = get_companion_capacity(int(player_id), conn=conn)
    owned_count = owned_companion_count(int(player_id), conn=conn)
    if owned_count >= capacity:
        return {
            "ok": False,
            "error": "capacity_full",
            "capacity": capacity,
            "owned_count": owned_count,
        }

    max_hp = max(1, int(event.get("max_hp") or 1))
    current_hp = max(0, int(event.get("current_hp") or 0))
    phase = int(hp_phase_from_ratio(float(current_hp) / float(max_hp)))
    if phase != 3:
        return {"ok": False, "error": "phase_locked", "phase": phase}

    catch = get_catch_state(int(player_id), boss_key, conn=conn)
    cd_until = float(catch.get("cooldown_until") or 0)
    if cd_until > ts:
        return {
            "ok": False,
            "error": "catch_cooldown",
            "cooldown_until": cd_until,
        }

    try:
        new_bal = debit(
            int(player_id),
            int(CATCH_COST_SEC),
            f"world_boss_catch:{boss_key}",
            conn=conn,
        )
    except InsufficientTimekeeperBalance as exc:
        return {"ok": False, "error": str(exc) or "insufficient_timekeeper"}

    cooldown_until = _upsert_catch_attempt(int(player_id), boss_key, conn=conn, now=ts)
    roller = rng if rng is not None else random.Random()
    roll = float(roller.random())
    success = roll < float(CATCH_CHANCE)

    out: Dict[str, Any] = {
        "ok": True,
        "success": success,
        "roll": round(roll, 4),
        "chance": float(CATCH_CHANCE),
        "boss_key": boss_key,
        "event_id": int(event_id),
        "cost_sec": int(CATCH_COST_SEC),
        "timekeeper_balance_sec": int(new_bal),
        "cooldown_until": float(cooldown_until),
        "companion": None,
    }

    if success:
        conn.execute(
            """
            INSERT OR IGNORE INTO player_boss_companions (
                player_id, boss_key, tamed_at, tamed_event_id
            ) VALUES (?, ?, ?, ?);
            """,
            (int(player_id), boss_key, ts, int(event_id)),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO player_boss_missions (
                player_id, boss_key, status, started_at, ends_at,
                reward_tokens, request_id, updated_at
            ) VALUES (?, ?, ?, NULL, NULL, 0, NULL, ?);
            """,
            (int(player_id), boss_key, MISSION_STATUS_IDLE, ts),
        )
        out["companion"] = {
            "boss_key": boss_key,
            "tamed_at": ts,
            "tamed_event_id": int(event_id),
        }
        # Boss leaves the map; pay all damage contributors immediately.
        from .world_boss import (
            auto_distribute_world_boss_rewards,
            close_event_as_tamed,
        )

        closed = close_event_as_tamed(int(event_id), conn=conn, now=ts)
        payout = auto_distribute_world_boss_rewards(int(event_id), conn=conn, now=ts)
        out["event"] = closed
        out["event_status"] = str((closed or {}).get("status") or "")
        out["reward_distribution"] = payout

    out["catch"] = build_catch_info_for_event(
        int(player_id),
        (out.get("event") or event),
        conn=conn,
        now=ts,
    )
    return out


def _mission_row(player_id: int, boss_key: str, *, conn) -> Optional[Dict[str, Any]]:
    if not companions_schema_ready(conn):
        return None
    cols = "id, player_id, boss_key, status, started_at, ends_at, reward_tokens, request_id, updated_at"
    if _mission_columns_ready(conn):
        cols += ", variant_key, fail_chance, outcome"
    row = conn.execute(
        f"""
        SELECT {cols}
        FROM player_boss_missions
        WHERE player_id = ? AND boss_key = ?
        LIMIT 1;
        """,
        (int(player_id), str(boss_key)),
    ).fetchone()
    if not row:
        return None
    out = {
        "id": int(row["id"]),
        "player_id": int(row["player_id"]),
        "boss_key": str(row["boss_key"]),
        "status": str(row["status"] or MISSION_STATUS_IDLE),
        "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
        "ends_at": float(row["ends_at"]) if row["ends_at"] is not None else None,
        "reward_tokens": int(row["reward_tokens"] or 0),
        "request_id": str(row["request_id"]) if row["request_id"] else None,
        "updated_at": float(row["updated_at"] or 0),
        "variant_key": None,
        "fail_chance": 0.0,
        "outcome": None,
    }
    if _mission_columns_ready(conn):
        out["variant_key"] = str(row["variant_key"]) if row["variant_key"] else None
        out["fail_chance"] = float(row["fail_chance"] or 0)
        out["outcome"] = str(row["outcome"]) if row["outcome"] else None
    return out


def _ensure_mission_row(player_id: int, boss_key: str, *, conn, now: float) -> Dict[str, Any]:
    existing = _mission_row(int(player_id), str(boss_key), conn=conn)
    if existing:
        return existing
    conn.execute(
        """
        INSERT OR IGNORE INTO player_boss_missions (
            player_id, boss_key, status, started_at, ends_at,
            reward_tokens, request_id, updated_at
        ) VALUES (?, ?, ?, NULL, NULL, 0, NULL, ?);
        """,
        (int(player_id), str(boss_key), MISSION_STATUS_IDLE, float(now)),
    )
    return _mission_row(int(player_id), str(boss_key), conn=conn) or {
        "boss_key": str(boss_key),
        "status": MISSION_STATUS_IDLE,
        "started_at": None,
        "ends_at": None,
        "reward_tokens": 0,
        "variant_key": None,
        "fail_chance": 0.0,
        "outcome": None,
    }


def _resolve_away_to_ready(
    player_id: int,
    boss_key: str,
    *,
    conn,
    now: float,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Roll success/fail when a mission finishes; store outcome + final reward."""
    mission = _mission_row(int(player_id), str(boss_key), conn=conn)
    if not mission or mission.get("status") != MISSION_STATUS_AWAY:
        return mission or {"status": MISSION_STATUS_IDLE}
    if mission.get("ends_at") is None or float(mission["ends_at"]) > float(now):
        return mission

    roller = rng if rng is not None else random.Random()
    fail_chance = float(mission.get("fail_chance") or 0)
    if fail_chance <= 0 and mission.get("variant_key"):
        spec = get_mission_variant(str(mission["variant_key"]))
        fail_chance = float((spec or {}).get("fail_chance") or 0.25)
    success = float(roller.random()) >= fail_chance
    outcome = MISSION_OUTCOME_SUCCESS if success else MISSION_OUTCOME_FAIL
    reward = int(mission.get("reward_tokens") or 0) if success else 0

    if _mission_columns_ready(conn):
        conn.execute(
            """
            UPDATE player_boss_missions
            SET status = ?, outcome = ?, reward_tokens = ?, updated_at = ?
            WHERE player_id = ? AND boss_key = ? AND status = ?;
            """,
            (
                MISSION_STATUS_READY,
                outcome,
                reward,
                float(now),
                int(player_id),
                str(boss_key),
                MISSION_STATUS_AWAY,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE player_boss_missions
            SET status = ?, reward_tokens = ?, updated_at = ?
            WHERE player_id = ? AND boss_key = ? AND status = ?;
            """,
            (
                MISSION_STATUS_READY,
                reward,
                float(now),
                int(player_id),
                str(boss_key),
                MISSION_STATUS_AWAY,
            ),
        )
    return _mission_row(int(player_id), str(boss_key), conn=conn) or mission


def refresh_mission_status(
    player_id: int,
    boss_key: str,
    *,
    conn,
    now: Optional[float] = None,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """Mark away→ready when ends_at elapsed; rolls success/fail once."""
    ts = float(now if now is not None else _now())
    mission = _mission_row(int(player_id), str(boss_key), conn=conn)
    if not mission:
        return {"status": MISSION_STATUS_IDLE}
    if (
        mission["status"] == MISSION_STATUS_AWAY
        and mission.get("ends_at") is not None
        and float(mission["ends_at"]) <= ts
    ):
        mission = _resolve_away_to_ready(
            int(player_id), str(boss_key), conn=conn, now=ts, rng=rng
        )
    return mission


def claim_mission_reward(
    player_id: int,
    boss_key: str,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    from .inventory import grant_inventory_item

    ts = float(now if now is not None else _now())
    if not has_companion(int(player_id), str(boss_key), conn=conn):
        return {"ok": False, "error": "not_owned"}

    mission = refresh_mission_status(int(player_id), str(boss_key), conn=conn, now=ts)
    if str(mission.get("status") or "") != MISSION_STATUS_READY:
        return {"ok": False, "error": "not_ready", "mission": mission}

    outcome = str(mission.get("outcome") or MISSION_OUTCOME_SUCCESS)
    tokens = int(mission.get("reward_tokens") or 0)
    if outcome == MISSION_OUTCOME_FAIL:
        tokens = 0

    if tokens > 0:
        granted = grant_inventory_item(
            int(player_id),
            ARK_TOKEN_KEY,
            tokens,
            conn=conn,
            metadata={
                "source": "world_boss_companion_mission",
                "boss_key": str(boss_key),
                "variant_key": mission.get("variant_key"),
                "outcome": outcome,
            },
        )
        if not granted:
            return {"ok": False, "error": "grant_failed"}

    if _mission_columns_ready(conn):
        conn.execute(
            """
            UPDATE player_boss_missions
            SET status = ?, started_at = NULL, ends_at = NULL,
                reward_tokens = 0, request_id = NULL,
                variant_key = NULL, fail_chance = 0, outcome = NULL,
                updated_at = ?
            WHERE player_id = ? AND boss_key = ?;
            """,
            (MISSION_STATUS_IDLE, ts, int(player_id), str(boss_key)),
        )
    else:
        conn.execute(
            """
            UPDATE player_boss_missions
            SET status = ?, started_at = NULL, ends_at = NULL,
                reward_tokens = 0, request_id = NULL, updated_at = ?
            WHERE player_id = ? AND boss_key = ?;
            """,
            (MISSION_STATUS_IDLE, ts, int(player_id), str(boss_key)),
        )
    return {
        "ok": True,
        "boss_key": str(boss_key),
        "tokens_granted": tokens,
        "outcome": outcome,
        "success": outcome == MISSION_OUTCOME_SUCCESS,
        "item_key": ARK_TOKEN_KEY,
        "mission": _mission_row(int(player_id), str(boss_key), conn=conn),
    }


def start_companion_mission(
    player_id: int,
    boss_key: str,
    *,
    conn,
    variant_key: str = "strike",
    now: Optional[float] = None,
    request_id: Optional[str] = None,
) -> Dict[str, Any]:
    ts = float(now if now is not None else _now())
    key = str(boss_key or "")
    variant = get_mission_variant(variant_key)
    if not variant:
        return {"ok": False, "error": "invalid_variant"}
    if not companions_schema_ready(conn):
        return {"ok": False, "error": "companions_unavailable"}
    if not has_companion(int(player_id), key, conn=conn):
        return {"ok": False, "error": "not_owned"}

    # Auto-claim ready rewards before starting again.
    mission = refresh_mission_status(int(player_id), key, conn=conn, now=ts)
    if str(mission.get("status") or "") == MISSION_STATUS_READY:
        claimed = claim_mission_reward(int(player_id), key, conn=conn, now=ts)
        if not claimed.get("ok"):
            return claimed
        mission = claimed.get("mission") or _ensure_mission_row(
            int(player_id), key, conn=conn, now=ts
        )

    mission = _ensure_mission_row(int(player_id), key, conn=conn, now=ts)
    if str(mission.get("status") or "") == MISSION_STATUS_AWAY:
        return {"ok": False, "error": "already_away", "mission": mission}

    capacity = get_companion_capacity(int(player_id), conn=conn)
    reward = mission_reward_tokens(key, capacity, variant_key=str(variant["variant_key"]))
    duration = int(variant["duration_sec"])
    fail_chance = float(variant["fail_chance"])
    ends_at = ts + float(duration)

    if _mission_columns_ready(conn):
        conn.execute(
            """
            UPDATE player_boss_missions
            SET status = ?, started_at = ?, ends_at = ?,
                reward_tokens = ?, request_id = ?,
                variant_key = ?, fail_chance = ?, outcome = NULL,
                updated_at = ?
            WHERE player_id = ? AND boss_key = ?;
            """,
            (
                MISSION_STATUS_AWAY,
                ts,
                ends_at,
                int(reward),
                (str(request_id)[:80] if request_id else None),
                str(variant["variant_key"]),
                fail_chance,
                ts,
                int(player_id),
                key,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE player_boss_missions
            SET status = ?, started_at = ?, ends_at = ?,
                reward_tokens = ?, request_id = ?, updated_at = ?
            WHERE player_id = ? AND boss_key = ?;
            """,
            (
                MISSION_STATUS_AWAY,
                ts,
                ends_at,
                int(reward),
                (str(request_id)[:80] if request_id else None),
                ts,
                int(player_id),
                key,
            ),
        )
    return {
        "ok": True,
        "boss_key": key,
        "variant_key": str(variant["variant_key"]),
        "mission": _mission_row(int(player_id), key, conn=conn),
        "duration_sec": duration,
        "reward_tokens": int(reward),
        "fail_chance": fail_chance,
        "success_chance": round(1.0 - fail_chance, 2),
    }


def tick_companion_missions(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Resolve due away missions (roll outcome + mark ready)."""
    if not companions_schema_ready(conn):
        return {"ok": True, "marked_ready": 0}
    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT player_id, boss_key FROM player_boss_missions
        WHERE status = ? AND ends_at IS NOT NULL AND ends_at <= ?;
        """,
        (MISSION_STATUS_AWAY, ts),
    ).fetchall()
    marked = 0
    for row in rows:
        _resolve_away_to_ready(
            int(row["player_id"]),
            str(row["boss_key"]),
            conn=conn,
            now=ts,
        )
        marked += 1
    return {"ok": True, "marked_ready": marked}


def tick_companion_missions_for_player(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Resolve this player's due away missions (request-path, committed with live state)."""
    if not companions_schema_ready(conn):
        return {"ok": True, "marked_ready": 0}
    ts = float(now if now is not None else _now())
    rows = conn.execute(
        """
        SELECT boss_key FROM player_boss_missions
        WHERE player_id = ? AND status = ? AND ends_at IS NOT NULL AND ends_at <= ?;
        """,
        (int(player_id), MISSION_STATUS_AWAY, ts),
    ).fetchall()
    marked = 0
    for row in rows:
        _resolve_away_to_ready(
            int(player_id),
            str(row["boss_key"]),
            conn=conn,
            now=ts,
        )
        marked += 1
    return {"ok": True, "marked_ready": marked}


def sync_companion_mission(
    player_id: int,
    boss_key: str,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Idempotent away→ready sync for one companion (countdown-zero client refresh)."""
    if not companions_schema_ready(conn):
        return {"ok": False, "error": "companions_unavailable"}
    key = str(boss_key or "").strip()
    if not key:
        return {"ok": False, "error": "invalid_boss"}
    if not has_companion(int(player_id), key, conn=conn):
        return {"ok": False, "error": "not_owned"}
    ts = float(now if now is not None else _now())
    mission = refresh_mission_status(int(player_id), key, conn=conn, now=ts)
    return {
        "ok": True,
        "boss_key": key,
        "status": str((mission or {}).get("status") or MISSION_STATUS_IDLE),
        "mission": mission,
    }


def _boss_display_name(boss_key: str, *, locale: str = "de") -> str:
    from .i18n import tr

    key = f"wb_boss_{boss_key}"
    return tr(key, str(boss_key or "World Boss"), locale=locale)


def build_companion_slot(
    boss_key: str,
    *,
    player_id: int,
    conn,
    now: Optional[float] = None,
    locale: str = "de",
    capacity: Optional[int] = None,
    active_event_id: Optional[int] = None,
) -> Dict[str, Any]:
    ts = float(now if now is not None else _now())
    flavor = COMPANION_FLAVOR.get(boss_key, {})
    owned = has_companion(int(player_id), boss_key, conn=conn)
    cap = int(capacity if capacity is not None else get_companion_capacity(int(player_id), conn=conn))
    mission: Optional[Dict[str, Any]] = None
    if owned:
        mission = refresh_mission_status(int(player_id), boss_key, conn=conn, now=ts)
    status = "locked"
    if owned:
        mstat = str((mission or {}).get("status") or MISSION_STATUS_IDLE)
        status = mstat if mstat in (
            MISSION_STATUS_IDLE,
            MISSION_STATUS_AWAY,
            MISSION_STATUS_READY,
        ) else MISSION_STATUS_IDLE

    reward_preview = mission_reward_tokens(boss_key, cap, variant_key="strike")
    art_rel = f"img/bosses/{boss_key}.png"
    outcome = (mission or {}).get("outcome")
    offers = list_mission_offers(boss_key, cap) if owned and status == MISSION_STATUS_IDLE else []
    return {
        "boss_key": boss_key,
        "owned": owned,
        "status": status,
        "name_key": f"wb_boss_{boss_key}",
        "name": _boss_display_name(boss_key, locale=locale),
        "art_relpath": art_rel,
        "left_pct": float(flavor.get("left_pct") or 50),
        "top_pct": float(flavor.get("top_pct") or 50),
        "slot": int(flavor.get("slot") or 0),
        "active_event_id": int(active_event_id) if active_event_id else None,
        "stats": {
            "power": int(flavor.get("power") or 50),
            "endurance": int(flavor.get("endurance") or 50),
            "cunning": int(flavor.get("cunning") or 50),
        },
        "mission_offers": offers,
        "mission": {
            "status": status if owned else "locked",
            "started_at": (mission or {}).get("started_at"),
            "ends_at": (mission or {}).get("ends_at"),
            "reward_tokens": int(
                (mission or {}).get("reward_tokens") or reward_preview
            ),
            "duration_sec": int(
                (MISSION_VARIANTS.get(str((mission or {}).get("variant_key") or "strike")) or {}).get(
                    "duration_sec"
                )
                or MISSION_DURATION_SEC
            ),
            "variant_key": (mission or {}).get("variant_key"),
            "fail_chance": float((mission or {}).get("fail_chance") or 0),
            "outcome": outcome,
            "can_start": owned and status == MISSION_STATUS_IDLE,
            "can_claim": owned and status == MISSION_STATUS_READY,
        },
    }


def build_overview_companions(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
    locale: str = "de",
) -> Dict[str, Any]:
    ts = float(now if now is not None else _now())
    if not companions_schema_ready(conn):
        return {"ready": False, "slots": [], "owned_count": 0, "capacity": 0}

    from .world_boss import list_active_events, list_definitions

    defs = list_definitions(conn=conn, active_only=True)
    keys = [str(d["boss_key"]) for d in defs]
    # Stable catalog order for landscape slots.
    preferred = [
        "ancient_leviathan",
        "void_titan",
        "planet_eater",
        "rogue_ai_nexus",
    ]
    ordered = [k for k in preferred if k in keys]
    for k in keys:
        if k not in ordered:
            ordered.append(k)

    active_by_key: Dict[str, int] = {}
    try:
        for ev in list_active_events(conn=conn, now=ts, limit=MAX_COMPANION_CAPACITY + 5):
            bk = str(ev.get("boss_key") or "")
            if bk and bk not in active_by_key:
                active_by_key[bk] = int(ev["id"])
    except Exception:
        logger.exception("overview companions active events failed")

    capacity = get_companion_capacity(int(player_id), conn=conn)
    owned_count = owned_companion_count(int(player_id), conn=conn)
    slots = [
        build_companion_slot(
            k,
            player_id=int(player_id),
            conn=conn,
            now=ts,
            locale=locale,
            capacity=capacity,
            active_event_id=active_by_key.get(k),
        )
        for k in ordered
    ]
    return {
        "ready": True,
        "slots": slots,
        "owned_count": owned_count,
        "capacity": capacity,
        "slots_free": max(0, capacity - owned_count),
        "max_capacity": int(MAX_COMPANION_CAPACITY),
        "mission_duration_sec": int(MISSION_DURATION_SEC),
        "catch_cost_sec": int(CATCH_COST_SEC),
        "catch_chance": float(CATCH_CHANCE),
        "catch_cooldown_sec": int(CATCH_COOLDOWN_SEC),
    }
