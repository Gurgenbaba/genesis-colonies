"""Instant resource exchange (Ferronit <-> Crytite) on the active colony."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional, Tuple

from .db import begin_write_transaction, commit, db, lock_planet_for_update, lock_player_for_update, rollback
from .models import column_exists, get_game_settings, get_planet_buildings, get_research_levels, table_exists
from .resources import get_storage_capacity

DAY_SECONDS = 86400

_EXCHANGE_SETTING_DEFAULTS = {
    "exchange_enabled": "1",
    "exchange_rate_metal_to_crystal": "0.8",
    "exchange_rate_crystal_to_metal": "0.8",
    "exchange_daily_limit": "500000000",
    "exchange_min_amount": "100",
}


def exchange_schema_ready(conn) -> bool:
    return table_exists(conn, "exchange_log") and column_exists(conn, "players", "exchange_daily_used")


def _float_setting(settings: Dict[str, Any], key: str, default: str) -> float:
    raw = settings.get(key, _EXCHANGE_SETTING_DEFAULTS.get(key, default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _int_setting(settings: Dict[str, Any], key: str, default: str) -> int:
    return max(0, int(_float_setting(settings, key, default)))


def get_exchange_config(conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        settings = get_game_settings(conn=conn)
        enabled = str(settings.get("exchange_enabled", "1")).strip() not in ("0", "false", "False")
        return {
            "enabled": enabled,
            "rate_metal_to_crystal": _float_setting(settings, "exchange_rate_metal_to_crystal", "0.8"),
            "rate_crystal_to_metal": _float_setting(settings, "exchange_rate_crystal_to_metal", "0.8"),
            "daily_limit": _int_setting(settings, "exchange_daily_limit", "500000000"),
            "min_amount": _int_setting(settings, "exchange_min_amount", "100"),
        }
    finally:
        if own:
            conn.close()


def _next_daily_reset(now: float) -> float:
    return float(int(now // DAY_SECONDS) * DAY_SECONDS + DAY_SECONDS)


def _daily_used(player_row: Dict[str, Any], now: float) -> float:
    reset_at = float(player_row.get("exchange_daily_reset_at") or 0)
    used = float(player_row.get("exchange_daily_used") or 0)
    if now >= reset_at:
        return 0.0
    return max(0.0, used)


def _preview_receive(amount: int, rate: float) -> int:
    return max(0, int(math.floor(float(amount) * float(rate))))


def _storage_caps(planet_id: int, player_id: int, conn) -> Dict[str, int]:
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    research = get_research_levels(user_id=int(player_id), conn=conn)
    return get_storage_capacity(buildings, research=research)


def get_exchange_status(
    *,
    player_id: int,
    planet_id: int,
    metal: float,
    crystal: float,
    conn=None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        cfg = get_exchange_config(conn=conn)
        now = time.time()
        cur = conn.cursor()
        cur.execute(
            "SELECT exchange_daily_used, exchange_daily_reset_at FROM players WHERE id = ? LIMIT 1;",
            (int(player_id),),
        )
        row = cur.fetchone()
        player_row = dict(row) if row else {}
        used = _daily_used(player_row, now)
        remaining = max(0, int(cfg["daily_limit"] - used))
        caps = _storage_caps(planet_id, player_id, conn)
        return {
            "enabled": cfg["enabled"],
            "rate_metal_to_crystal": cfg["rate_metal_to_crystal"],
            "rate_crystal_to_metal": cfg["rate_crystal_to_metal"],
            "daily_limit": cfg["daily_limit"],
            "daily_used": int(used),
            "daily_remaining": remaining,
            "min_amount": cfg["min_amount"],
            "balances": {
                "metal": max(0, int(metal)),
                "crystal": max(0, int(crystal)),
            },
            "storage": caps,
            "reset_at": int(_next_daily_reset(now)),
        }
    finally:
        if own:
            conn.close()


def execute_exchange(
    *,
    player_id: int,
    planet_id: int,
    from_resource: str,
    amount: int,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    resource = str(from_resource or "").strip().lower()
    if resource not in ("metal", "crystal"):
        return False, "invalid_resource", None

    try:
        give_amount = int(amount)
    except (TypeError, ValueError):
        return False, "invalid_amount", None

    if give_amount <= 0:
        return False, "invalid_amount", None

    own = conn is None
    if own:
        conn = db()
    try:
        if not exchange_schema_ready(conn):
            return False, "exchange_unavailable", None

        cfg = get_exchange_config(conn=conn)
        if not cfg["enabled"]:
            return False, "exchange_disabled", None

        if give_amount < int(cfg["min_amount"]):
            return False, "below_minimum", {"min_amount": int(cfg["min_amount"])}

        rate = (
            cfg["rate_metal_to_crystal"]
            if resource == "metal"
            else cfg["rate_crystal_to_metal"]
        )
        receive_resource = "crystal" if resource == "metal" else "metal"
        receive_amount = _preview_receive(give_amount, rate)
        if receive_amount <= 0:
            return False, "amount_too_small", None

        now = time.time()
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        lock_player_for_update(conn, int(player_id))

        cur = conn.cursor()
        cur.execute(
            "SELECT id, player_id, metal, crystal FROM planets WHERE id = ? LIMIT 1;",
            (int(planet_id),),
        )
        planet = cur.fetchone()
        if not planet or int(planet["player_id"]) != int(player_id):
            rollback(conn)
            return False, "planet_not_found", None

        cur.execute(
            "SELECT exchange_daily_used, exchange_daily_reset_at FROM players WHERE id = ? LIMIT 1;",
            (int(player_id),),
        )
        player_row = dict(cur.fetchone() or {})
        used = _daily_used(player_row, now)
        if used + give_amount > float(cfg["daily_limit"]):
            rollback(conn)
            return False, "daily_limit_exceeded", {
                "daily_limit": int(cfg["daily_limit"]),
                "daily_used": int(used),
                "daily_remaining": max(0, int(cfg["daily_limit"] - used)),
            }

        current_metal = float(planet["metal"] or 0)
        current_crystal = float(planet["crystal"] or 0)
        if resource == "metal" and current_metal < give_amount:
            rollback(conn)
            return False, "insufficient_balance", None
        if resource == "crystal" and current_crystal < give_amount:
            rollback(conn)
            return False, "insufficient_balance", None

        caps = _storage_caps(planet_id, player_id, conn)
        if receive_resource == "metal":
            free = max(0, int(caps.get("metal", 0) or 0) - int(current_metal))
        else:
            free = max(0, int(caps.get("crystal", 0) or 0) - int(current_crystal))

        if receive_amount > free:
            rollback(conn)
            return False, "storage_full", {"receive_resource": receive_resource}

        new_metal = current_metal
        new_crystal = current_crystal
        if resource == "metal":
            new_metal -= give_amount
            new_crystal += receive_amount
        else:
            new_crystal -= give_amount
            new_metal += receive_amount

        cur.execute(
            """
            UPDATE planets
            SET metal = ?, crystal = ?, last_update = ?
            WHERE id = ?;
            """,
            (max(0.0, new_metal), max(0.0, new_crystal), now, int(planet_id)),
        )

        next_reset = _next_daily_reset(now)
        cur.execute(
            """
            UPDATE players
            SET exchange_daily_used = ?, exchange_daily_reset_at = ?
            WHERE id = ?;
            """,
            (used + float(give_amount), next_reset, int(player_id)),
        )

        cur.execute(
            """
            INSERT INTO exchange_log (
                player_id, planet_id, give_resource, give_amount,
                receive_resource, receive_amount, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(player_id),
                int(planet_id),
                resource,
                float(give_amount),
                receive_resource,
                float(receive_amount),
                now,
            ),
        )

        commit(conn)
        return True, "ok", {
            "from": resource,
            "give_amount": give_amount,
            "receive_resource": receive_resource,
            "receive_amount": receive_amount,
            "rate": rate,
            "balances": {
                "metal": max(0, int(new_metal)),
                "crystal": max(0, int(new_crystal)),
            },
        }
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()
