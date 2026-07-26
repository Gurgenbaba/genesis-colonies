"""
EPIC-22 / GC-981–982 — 30-day login attendance calendar (server-authoritative).

Grants via grant_inventory_item + optional timekeeper.credit.
Missed UTC day → streak reset to day 1. No catch-up in Phase 1.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import table_exists
from .inventory import grant_inventory_item, inventory_schema_ready
from .inventory_catalog import item_catalog_entry, is_known_item_key

LOGIN_CYCLE_DAYS = 30
SOURCE_PREFIX = "login_reward"


def day_bucket(ts: Optional[float] = None) -> int:
    return int(float(ts if ts is not None else time.time()) // 86400)


def schema_ready(conn) -> bool:
    return bool(
        table_exists(conn, "login_reward_progress")
        and table_exists(conn, "login_reward_claims")
    )


def _new_cycle_id() -> str:
    return f"lr_{secrets.token_hex(8)}"


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _item(item_key: str, amount: int = 1) -> Dict[str, Any]:
    return {"item_key": str(item_key), "amount": int(amount)}


def _day(
    day: int,
    *,
    items: Optional[List[Dict[str, Any]]] = None,
    timekeeper_sec: int = 0,
    milestone: bool = False,
) -> Dict[str, Any]:
    return {
        "day": int(day),
        "items": list(items or []),
        "timekeeper_sec": max(0, int(timekeeper_sec or 0)),
        "milestone": bool(milestone),
    }


# Canonical 30-day catalog (server-only). Meta items only (GC-864).
LOGIN_REWARD_CATALOG: Tuple[Dict[str, Any], ...] = (
    _day(1, items=[_item("container_basic"), _item("booster_build_5m")], timekeeper_sec=300, milestone=False),
    _day(2, items=[_item("booster_research_5m"), _item("booster_build_5m")]),
    _day(3, items=[_item("container_basic"), _item("booster_research_15m")]),
    _day(4, items=[_item("booster_build_15m")]),
    _day(5, items=[_item("container_basic"), _item("booster_research_15m")]),
    _day(6, items=[_item("booster_build_15m"), _item("booster_shipyard_15m")]),
    _day(
        7,
        items=[
            _item("container_rare"),
            _item("booster_build_1h"),
            _item("booster_research_1h"),
        ],
        milestone=True,
    ),
    _day(8, items=[_item("booster_production_25")]),
    _day(9, items=[_item("booster_build_15m"), _item("booster_research_30m")]),
    _day(10, items=[_item("container_rare")]),
    _day(11, items=[_item("booster_research_pct_2_24h")]),
    _day(12, items=[_item("booster_build_1h")]),
    _day(13, items=[_item("booster_shipyard_1h"), _item("booster_research_15m")]),
    _day(
        14,
        items=[_item("container_epic"), _item("booster_build_6h")],
        timekeeper_sec=1800,
        milestone=True,
    ),
    _day(15, items=[_item("booster_research_1h")]),
    _day(16, items=[_item("booster_expedition_loot_25_24h")]),
    _day(17, items=[_item("container_research_cache"), _item("booster_build_15m")]),
    _day(18, items=[_item("booster_production_50")]),
    _day(19, items=[_item("booster_shipyard_1h"), _item("booster_research_1h")]),
    _day(20, items=[_item("booster_container_luck_24h")]),
    _day(
        21,
        items=[
            _item("container_relic"),
            _item("booster_build_6h"),
            _item("booster_research_6h"),
        ],
        milestone=True,
    ),
    _day(22, items=[_item("booster_fleet_speed_25_24h")]),
    _day(23, items=[_item("container_military_cache"), _item("booster_build_1h")]),
    _day(24, items=[_item("booster_research_6h")]),
    _day(25, items=[_item("container_epic"), _item("booster_production_50")]),
    _day(26, items=[_item("booster_build_6h"), _item("booster_shipyard_1h")]),
    _day(27, items=[_item("booster_research_24h")]),
    _day(28, items=[_item("container_rare"), _item("booster_build_24h")]),
    _day(29, items=[_item("booster_container_luck_24h"), _item("booster_research_6h")]),
    _day(
        30,
        items=[
            _item("container_mythic"),
            _item("booster_build_24h"),
            _item("booster_research_24h"),
            _item("booster_production_100"),
        ],
        timekeeper_sec=7200,
        milestone=True,
    ),
)

assert len(LOGIN_REWARD_CATALOG) == LOGIN_CYCLE_DAYS
assert all(int(d["day"]) == i + 1 for i, d in enumerate(LOGIN_REWARD_CATALOG))


def catalog_day(day_index: int) -> Optional[Dict[str, Any]]:
    idx = int(day_index)
    if idx < 1 or idx > LOGIN_CYCLE_DAYS:
        return None
    return dict(LOGIN_REWARD_CATALOG[idx - 1])


def _reward_preview(entry: Mapping[str, Any]) -> Dict[str, Any]:
    items_out: List[Dict[str, Any]] = []
    for raw in entry.get("items") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("item_key") or "").strip()
        amount = max(0, int(raw.get("amount") or 0))
        if not key or amount <= 0:
            continue
        spec = item_catalog_entry(key) or {}
        items_out.append(
            {
                "item_key": key,
                "amount": amount,
                "name_key": spec.get("name_key") or key,
                "icon": spec.get("icon") or "",
                "rarity": spec.get("rarity") or "common",
                "image": spec.get("image") or "",
            }
        )
    return {
        "day": int(entry.get("day") or 0),
        "items": items_out,
        "timekeeper_sec": max(0, int(entry.get("timekeeper_sec") or 0)),
        "milestone": bool(entry.get("milestone")),
    }


def _fetch_progress(player_id: int, *, conn) -> Optional[Any]:
    return conn.execute(
        """
        SELECT player_id, cycle_id, cycle_started_at, current_day,
               last_claim_day_bucket, updated_at
        FROM login_reward_progress
        WHERE player_id = ?
        LIMIT 1;
        """,
        (int(player_id),),
    ).fetchone()


def _insert_progress(player_id: int, *, conn, now: float) -> Dict[str, Any]:
    cycle_id = _new_cycle_id()
    conn.execute(
        """
        INSERT INTO login_reward_progress (
            player_id, cycle_id, cycle_started_at, current_day,
            last_claim_day_bucket, updated_at
        ) VALUES (?, ?, ?, 0, NULL, ?);
        """,
        (int(player_id), cycle_id, float(now), float(now)),
    )
    return {
        "player_id": int(player_id),
        "cycle_id": cycle_id,
        "cycle_started_at": float(now),
        "current_day": 0,
        "last_claim_day_bucket": None,
        "updated_at": float(now),
    }


def _row_to_progress(row: Any) -> Dict[str, Any]:
    last_bucket = row["last_claim_day_bucket"]
    return {
        "player_id": int(row["player_id"]),
        "cycle_id": str(row["cycle_id"]),
        "cycle_started_at": float(row["cycle_started_at"] or 0),
        "current_day": int(row["current_day"] or 0),
        "last_claim_day_bucket": int(last_bucket) if last_bucket is not None else None,
        "updated_at": float(row["updated_at"] or 0),
    }


def _reset_cycle(player_id: int, *, conn, now: float, keep_last_bucket: Optional[int]) -> Dict[str, Any]:
    cycle_id = _new_cycle_id()
    conn.execute(
        """
        UPDATE login_reward_progress
        SET cycle_id = ?, cycle_started_at = ?, current_day = 0,
            last_claim_day_bucket = ?, updated_at = ?
        WHERE player_id = ?;
        """,
        (cycle_id, float(now), keep_last_bucket, float(now), int(player_id)),
    )
    return {
        "player_id": int(player_id),
        "cycle_id": cycle_id,
        "cycle_started_at": float(now),
        "current_day": 0,
        "last_claim_day_bucket": keep_last_bucket,
        "updated_at": float(now),
    }


def ensure_progress(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Load progress; apply streak reset if a UTC day was missed."""
    ts = float(now if now is not None else time.time())
    bucket = day_bucket(ts)
    row = _fetch_progress(int(player_id), conn=conn)
    if not row:
        return _insert_progress(int(player_id), conn=conn, now=ts)

    progress = _row_to_progress(row)
    last = progress["last_claim_day_bucket"]
    if last is not None and bucket > int(last) + 1:
        # Missed at least one day → streak break, new cycle, can claim day 1 today.
        return _reset_cycle(
            int(player_id),
            conn=conn,
            now=ts,
            keep_last_bucket=None,
        )
    return progress


def _seconds_until_next_bucket(ts: float) -> int:
    bucket = day_bucket(ts)
    next_start = (bucket + 1) * 86400
    return max(0, int(next_start - ts))


def claim_status(progress: Mapping[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
    ts = float(now if now is not None else time.time())
    bucket = day_bucket(ts)
    current_day = int(progress.get("current_day") or 0)
    last = progress.get("last_claim_day_bucket")
    next_day = current_day + 1

    if next_day > LOGIN_CYCLE_DAYS:
        # Should not happen after day-30 reset; treat as unavailable until reset.
        return {
            "available": False,
            "reason": "cycle_complete",
            "next_day": None,
            "next_unlock_in_sec": _seconds_until_next_bucket(ts),
        }

    if last is not None and int(last) == bucket:
        return {
            "available": False,
            "reason": "already_claimed_today",
            "next_day": next_day,
            "next_unlock_in_sec": _seconds_until_next_bucket(ts),
        }

    if last is not None and bucket > int(last) + 1:
        # ensure_progress should have reset; defensive.
        return {
            "available": True,
            "reason": "ok",
            "next_day": 1,
            "next_unlock_in_sec": 0,
        }

    return {
        "available": True,
        "reason": "ok",
        "next_day": next_day,
        "next_unlock_in_sec": 0,
    }


def _grant_day_rewards(
    player_id: int,
    entry: Mapping[str, Any],
    *,
    conn,
    source: str,
) -> Tuple[bool, List[str], int]:
    granted: List[str] = []
    if not inventory_schema_ready(conn):
        return False, granted, 0

    for raw in entry.get("items") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("item_key") or "").strip()
        amount = max(0, int(raw.get("amount") or 0))
        if not key or amount <= 0:
            continue
        if not is_known_item_key(key):
            return False, granted, 0
        ok = grant_inventory_item(
            int(player_id),
            key,
            amount,
            conn=conn,
            metadata={"source": source, "kind": "login_reward"},
        )
        if not ok:
            return False, granted, 0
        granted.append(key)

    tk_sec = max(0, int(entry.get("timekeeper_sec") or 0))
    if tk_sec > 0:
        from .timekeeper import credit, schema_ready as tk_ready

        if tk_ready(conn):
            credit(int(player_id), tk_sec, source, conn=conn)
            granted.append(f"timekeeper:{tk_sec}")
    return True, granted, tk_sec


def claim_login_reward(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "login_rewards_unavailable", None

    pid = int(player_id)
    if pid <= 0:
        return False, "invalid_player", None

    ts = float(now if now is not None else time.time())
    bucket = day_bucket(ts)
    progress = ensure_progress(pid, conn=conn, now=ts)
    status = claim_status(progress, now=ts)
    if not status["available"]:
        return False, str(status["reason"]), None

    next_day = int(status["next_day"] or 0)
    entry = catalog_day(next_day)
    if not entry:
        return False, "invalid_day", None

    source = f"{SOURCE_PREFIX}:day_{next_day}"
    ok, granted, tk_sec = _grant_day_rewards(pid, entry, conn=conn, source=source)
    if not ok:
        return False, "grant_failed", None

    reward_payload = {
        "day": next_day,
        "items": list(entry.get("items") or []),
        "timekeeper_sec": tk_sec,
        "granted": granted,
        "milestone": bool(entry.get("milestone")),
    }

    try:
        conn.execute(
            """
            INSERT INTO login_reward_claims (
                player_id, cycle_id, day_index, reward_json, claimed_at
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (pid, str(progress["cycle_id"]), next_day, _json_dumps(reward_payload), ts),
        )
    except Exception:
        return False, "already_claimed", None

    new_current = next_day
    keep_bucket = bucket
    if new_current >= LOGIN_CYCLE_DAYS:
        # Finish cycle; next claim (tomorrow) starts day 1 of a new cycle.
        _reset_cycle(pid, conn=conn, now=ts, keep_last_bucket=keep_bucket)
    else:
        conn.execute(
            """
            UPDATE login_reward_progress
            SET current_day = ?, last_claim_day_bucket = ?, updated_at = ?
            WHERE player_id = ?;
            """,
            (new_current, keep_bucket, ts, pid),
        )

    state = serialize_for_client(pid, conn=conn, now=ts, include_calendar=True)
    return True, "ok", {
        "day": next_day,
        "reward": _reward_preview(entry),
        "granted": granted,
        "login_rewards": state,
    }


def serialize_for_client(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
    include_calendar: bool = False,
) -> Dict[str, Any]:
    if not schema_ready(conn):
        return {"ready": False, "available": False}

    ts = float(now if now is not None else time.time())
    progress = ensure_progress(int(player_id), conn=conn, now=ts)
    status = claim_status(progress, now=ts)
    out: Dict[str, Any] = {
        "ready": True,
        "available": bool(status["available"]),
        "reason": str(status.get("reason") or ""),
        "current_day": int(progress["current_day"]),
        "next_day": status.get("next_day"),
        "next_unlock_in_sec": int(status.get("next_unlock_in_sec") or 0),
        "cycle_id": str(progress["cycle_id"]),
        "cycle_started_at": float(progress["cycle_started_at"]),
    }
    if include_calendar:
        claimed_days = {
            int(r["day_index"])
            for r in conn.execute(
                """
                SELECT day_index FROM login_reward_claims
                WHERE player_id = ? AND cycle_id = ?;
                """,
                (int(player_id), str(progress["cycle_id"])),
            ).fetchall()
        }
        days: List[Dict[str, Any]] = []
        for entry in LOGIN_REWARD_CATALOG:
            d = int(entry["day"])
            preview = _reward_preview(entry)
            if d in claimed_days:
                preview["status"] = "claimed"
            elif status.get("available") and int(status.get("next_day") or 0) == d:
                preview["status"] = "claimable"
            elif d <= int(progress["current_day"]):
                preview["status"] = "claimed"
            else:
                preview["status"] = "locked"
            days.append(preview)
        out["days"] = days
    return out
