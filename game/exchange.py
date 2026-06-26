"""Unified resource trader (Ferronit, Crytite, Brennzellen) on the active colony."""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

from .db import begin_write_transaction, commit, db, lock_planet_for_update, lock_player_for_update, rollback
from .models import column_exists, get_game_settings, get_planet_buildings, get_research_levels, table_exists
from .resources import get_storage_capacity

DAY_SECONDS = 86400

EXCHANGE_RESOURCES = ("metal", "crystal", "fuel_cells")

_SAFE_FERRONITE_COST_PER_CRYTITE_BUY = 2.0
_SAFE_FERRONITE_RETURN_PER_CRYTITE_SELL = 1.0

_EXCHANGE_SETTING_DEFAULTS = {
    "exchange_enabled": "1",
    # Ferronite cost per 1 Crytite (buy) — divide input by this rate.
    "exchange_rate_metal_to_crystal": "2",
    # Ferronite return per 1 Crytite (sell) — multiply input by this rate.
    "exchange_rate_crystal_to_metal": "1",
    "exchange_daily_limit_pct": "80",
    "exchange_daily_limit_min": "500000",
    "exchange_min_amount": "100",
    "fuel_exchange_enabled": "1",
    "fuel_exchange_metal_per_unit": "20",
    "fuel_exchange_crystal_per_unit": "14",
    "fuel_exchange_min_units": "10",
}

_VALID_ROUTES = frozenset(
    {
        ("metal", "crystal"),
        ("crystal", "metal"),
        ("metal", "fuel_cells"),
        ("crystal", "fuel_cells"),
        ("fuel_cells", "metal"),
        ("fuel_cells", "crystal"),
    }
)


def exchange_schema_ready(conn) -> bool:
    return (
        table_exists(conn, "exchange_log")
        and column_exists(conn, "players", "exchange_daily_used")
        and column_exists(conn, "planets", "fuel_cells")
    )


def _float_setting(settings: Dict[str, Any], key: str, default: str) -> float:
    raw = settings.get(key, _EXCHANGE_SETTING_DEFAULTS.get(key, default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _int_setting(settings: Dict[str, Any], key: str, default: str) -> int:
    return max(0, int(_float_setting(settings, key, default)))


def validate_exchange_rates(buy_cost: float, sell_return: float) -> Tuple[bool, Optional[str]]:
    """Ensure Crytite buy cost exceeds sell return (no roundtrip profit)."""
    try:
        buy = float(buy_cost)
        sell = float(sell_return)
    except (TypeError, ValueError):
        return False, "exchange_invalid_rate"
    if buy <= 0 or sell <= 0:
        return False, "exchange_invalid_rate"
    if buy <= sell:
        return False, "exchange_arbitrage_risk"
    return True, None


def would_roundtrip_profit(amount: int, buy_cost: float, sell_return: float) -> bool:
    """Return True when Ferronite → Crytite → Ferronite yields more Ferronite."""
    start = max(0, int(amount))
    if start <= 0:
        return False
    buy = max(0.001, float(buy_cost))
    sell = max(0.0, float(sell_return))
    crytite = int(math.floor(start / buy))
    ferronite_back = int(math.floor(crytite * sell))
    return ferronite_back > start


def _sanitize_metal_crystal_rates(buy_cost: float, sell_return: float) -> Tuple[float, float, bool]:
    ok, _ = validate_exchange_rates(buy_cost, sell_return)
    if ok:
        return float(buy_cost), float(sell_return), False
    logger.warning(
        "[exchange] corrected unsafe exchange rates buy_cost=%s sell_return=%s -> buy_cost=%s sell_return=%s",
        buy_cost,
        sell_return,
        _SAFE_FERRONITE_COST_PER_CRYTITE_BUY,
        _SAFE_FERRONITE_RETURN_PER_CRYTITE_SELL,
    )
    return _SAFE_FERRONITE_COST_PER_CRYTITE_BUY, _SAFE_FERRONITE_RETURN_PER_CRYTITE_SELL, True


def get_exchange_config(conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        settings = get_game_settings(conn=conn)
        enabled = str(settings.get("exchange_enabled", "1")).strip() not in ("0", "false", "False")
        fuel_enabled = str(settings.get("fuel_exchange_enabled", "1")).strip() not in ("0", "false", "False")
        raw_buy = _float_setting(settings, "exchange_rate_metal_to_crystal", "2")
        raw_sell = _float_setting(settings, "exchange_rate_crystal_to_metal", "1")
        buy_cost, sell_return, corrected = _sanitize_metal_crystal_rates(raw_buy, raw_sell)
        rates_ok, rates_reason = validate_exchange_rates(buy_cost, sell_return)
        return {
            "enabled": enabled,
            "fuel_enabled": fuel_enabled,
            "rate_metal_to_crystal": buy_cost,
            "rate_crystal_to_metal": sell_return,
            "ferronite_cost_per_crytite_buy": buy_cost,
            "ferronite_return_per_crytite_sell": sell_return,
            "rates_valid": rates_ok,
            "rates_block_reason": rates_reason or "",
            "rates_corrected": corrected,
            "daily_limit_pct": _float_setting(settings, "exchange_daily_limit_pct", "80"),
            "daily_limit_min": _int_setting(settings, "exchange_daily_limit_min", "25000000"),
            "min_amount": _int_setting(settings, "exchange_min_amount", "100"),
            "fuel_metal_per_unit": _float_setting(settings, "fuel_exchange_metal_per_unit", "20"),
            "fuel_crystal_per_unit": _float_setting(settings, "fuel_exchange_crystal_per_unit", "14"),
            "fuel_min_units": _int_setting(settings, "fuel_exchange_min_units", "10"),
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


def _fuel_unit_cost(cfg: Dict[str, Any], from_resource: str) -> float:
    key = "fuel_metal_per_unit" if from_resource == "metal" else "fuel_crystal_per_unit"
    return max(0.001, float(cfg.get(key, 1) or 1))


def _preview_receive(from_resource: str, to_resource: str, amount: int, cfg: Dict[str, Any]) -> int:
    give_amount = int(amount)
    if give_amount <= 0:
        return 0
    if from_resource == "metal" and to_resource == "crystal":
        buy_cost = max(0.001, float(cfg["rate_metal_to_crystal"]))
        return max(0, int(math.floor(give_amount / buy_cost)))
    if from_resource == "crystal" and to_resource == "metal":
        sell_return = max(0.0, float(cfg["rate_crystal_to_metal"]))
        return max(0, int(math.floor(give_amount * sell_return)))
    if from_resource == "metal" and to_resource == "fuel_cells":
        per = _fuel_unit_cost(cfg, "metal")
        return max(0, int(math.floor(give_amount / per)))
    if from_resource == "crystal" and to_resource == "fuel_cells":
        per = _fuel_unit_cost(cfg, "crystal")
        return max(0, int(math.floor(give_amount / per)))
    if from_resource == "fuel_cells" and to_resource == "metal":
        return max(0, int(math.floor(give_amount * _fuel_unit_cost(cfg, "metal"))))
    if from_resource == "fuel_cells" and to_resource == "crystal":
        return max(0, int(math.floor(give_amount * _fuel_unit_cost(cfg, "crystal"))))
    return 0


def _route_rate(from_resource: str, to_resource: str, cfg: Dict[str, Any]) -> float:
    if from_resource == "metal" and to_resource == "crystal":
        return max(0.001, float(cfg["rate_metal_to_crystal"]))
    if from_resource == "crystal" and to_resource == "metal":
        return max(0.0, float(cfg["rate_crystal_to_metal"]))
    if from_resource == "metal" and to_resource == "fuel_cells":
        return 1.0 / _fuel_unit_cost(cfg, "metal")
    if from_resource == "crystal" and to_resource == "fuel_cells":
        return 1.0 / _fuel_unit_cost(cfg, "crystal")
    if from_resource == "fuel_cells" and to_resource == "metal":
        return _fuel_unit_cost(cfg, "metal")
    if from_resource == "fuel_cells" and to_resource == "crystal":
        return _fuel_unit_cost(cfg, "crystal")
    return 0.0


def _route_enabled(from_resource: str, to_resource: str, cfg: Dict[str, Any]) -> bool:
    if not cfg["enabled"]:
        return False
    if "fuel_cells" in (from_resource, to_resource) and not cfg["fuel_enabled"]:
        return False
    return True


def _min_give_amount(from_resource: str, to_resource: str, cfg: Dict[str, Any]) -> int:
    if from_resource == "fuel_cells":
        return max(1, int(cfg["fuel_min_units"]))
    if to_resource == "fuel_cells":
        if from_resource == "metal":
            return max(int(cfg["min_amount"]), int(math.ceil(_fuel_unit_cost(cfg, "metal"))))
        if from_resource == "crystal":
            return max(int(cfg["min_amount"]), int(math.ceil(_fuel_unit_cost(cfg, "crystal"))))
    return max(1, int(cfg["min_amount"]))


def _normalize_route(
    from_resource: str,
    to_resource: Optional[str],
    direction: str = "",
) -> Tuple[Optional[str], Optional[str]]:
    give = str(from_resource or "").strip().lower()
    receive = str(to_resource or "").strip().lower() if to_resource else ""
    dir_key = str(direction or "").strip().lower()

    if not receive and dir_key:
        dir_map = {
            "metal_to_crystal": ("metal", "crystal"),
            "crystal_to_metal": ("crystal", "metal"),
            "metal_to_fuel_cells": ("metal", "fuel_cells"),
            "crystal_to_fuel_cells": ("crystal", "fuel_cells"),
            "fuel_cells_to_metal": ("fuel_cells", "metal"),
            "fuel_cells_to_crystal": ("fuel_cells", "crystal"),
        }
        mapped = dir_map.get(dir_key)
        if mapped:
            return mapped

    if give and not receive:
        if give == "metal":
            receive = "crystal"
        elif give == "crystal":
            receive = "metal"

    if give not in EXCHANGE_RESOURCES or receive not in EXCHANGE_RESOURCES:
        return None, None
    if give == receive:
        return None, None
    if (give, receive) not in _VALID_ROUTES:
        return None, None
    return give, receive


def _storage_caps(planet_id: int, player_id: int, conn) -> Dict[str, int]:
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    research = get_research_levels(user_id=int(player_id), conn=conn)
    return get_storage_capacity(buildings, research=research)


def resolve_exchange_daily_limit(player_id: int, *, conn=None) -> Dict[str, Any]:
    """GC-732 — Trader limit = empire 24h production × pct (optional min floor)."""
    from .empire_page import get_empire_production_aggregate

    own = conn is None
    if own:
        conn = db()
    try:
        cfg = get_exchange_config(conn=conn)
        prod = get_empire_production_aggregate(int(player_id), conn=conn)
        pct = float(cfg["daily_limit_pct"])
        min_lim = int(cfg["daily_limit_min"])
        empire_day_total = int(prod["total_per_day"])
        scaled = int(empire_day_total * pct / 100.0)
        final = max(min_lim, scaled) if min_lim > 0 else scaled
        return {
            "daily_limit": int(final),
            "daily_limit_scaled": int(scaled),
            "empire_production_day_total": empire_day_total,
            "empire_production_day": {
                "metal": int(prod["metal_per_day"]),
                "crystal": int(prod["crystal_per_day"]),
                "fuel_cells": int(prod["fuel_cells_per_day"]),
            },
            "limit_pct": pct,
            "limit_min": min_lim,
        }
    finally:
        if own:
            conn.close()


def get_exchange_status(
    *,
    player_id: int,
    planet_id: int,
    metal: float,
    crystal: float,
    fuel_cells: float = 0,
    conn=None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        cfg = get_exchange_config(conn=conn)
        limit_block = resolve_exchange_daily_limit(int(player_id), conn=conn)
        daily_limit = int(limit_block["daily_limit"])
        now = time.time()
        cur = conn.cursor()
        cur.execute(
            "SELECT exchange_daily_used, exchange_daily_reset_at FROM players WHERE id = ? LIMIT 1;",
            (int(player_id),),
        )
        row = cur.fetchone()
        player_row = dict(row) if row else {}
        used = _daily_used(player_row, now)
        remaining = max(0, int(daily_limit - used))
        caps = _storage_caps(planet_id, player_id, conn)
        routes = {}
        for give, receive in _VALID_ROUTES:
            key = f"{give}_to_{receive}"
            routes[key] = {
                "enabled": _route_enabled(give, receive, cfg),
                "rate": _route_rate(give, receive, cfg),
                "min_amount": _min_give_amount(give, receive, cfg),
            }
        return {
            "enabled": cfg["enabled"],
            "fuel_enabled": cfg["fuel_enabled"],
            "rate_metal_to_crystal": cfg["rate_metal_to_crystal"],
            "rate_crystal_to_metal": cfg["rate_crystal_to_metal"],
            "fuel_metal_per_unit": cfg["fuel_metal_per_unit"],
            "fuel_crystal_per_unit": cfg["fuel_crystal_per_unit"],
            "fuel_min_units": cfg["fuel_min_units"],
            "routes": routes,
            "daily_limit": daily_limit,
            "daily_used": int(used),
            "daily_remaining": remaining,
            "daily_limit_pct": limit_block["limit_pct"],
            "daily_limit_min": limit_block["limit_min"],
            "empire_production_day_total": limit_block["empire_production_day_total"],
            "empire_production_day": limit_block["empire_production_day"],
            "min_amount": cfg["min_amount"],
            "balances": {
                "metal": max(0, int(metal)),
                "crystal": max(0, int(crystal)),
                "fuel_cells": max(0, int(fuel_cells)),
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
    to_resource: Optional[str] = None,
    direction: str = "",
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    give_resource, receive_resource = _normalize_route(from_resource, to_resource, direction)
    if not give_resource or not receive_resource:
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

        from .options import vacation_blocks_outbound

        ok_vacation, vac_reason = vacation_blocks_outbound(int(player_id), conn=conn)
        if not ok_vacation:
            return False, vac_reason, None

        cfg = get_exchange_config(conn=conn)
        limit_block = resolve_exchange_daily_limit(int(player_id), conn=conn)
        daily_limit = int(limit_block["daily_limit"])
        if not _route_enabled(give_resource, receive_resource, cfg):
            return False, "exchange_disabled", None

        if {give_resource, receive_resource} == {"metal", "crystal"}:
            buy_cost = float(cfg["rate_metal_to_crystal"])
            sell_return = float(cfg["rate_crystal_to_metal"])
            ok_rates, rate_reason = validate_exchange_rates(buy_cost, sell_return)
            if not ok_rates:
                logger.warning(
                    "[exchange] blocked trade: invalid metal/crystal rates buy=%s sell=%s reason=%s",
                    buy_cost,
                    sell_return,
                    rate_reason,
                )
                return False, "exchange_arbitrage_disabled", None
            if would_roundtrip_profit(give_amount, buy_cost, sell_return):
                logger.warning(
                    "[exchange] blocked trade: roundtrip profit possible buy=%s sell=%s amount=%s",
                    buy_cost,
                    sell_return,
                    give_amount,
                )
                return False, "exchange_arbitrage_disabled", None

        min_give = _min_give_amount(give_resource, receive_resource, cfg)
        if give_amount < min_give:
            return False, "below_minimum", {"min_amount": min_give}

        receive_amount = _preview_receive(give_resource, receive_resource, give_amount, cfg)
        if receive_amount <= 0:
            return False, "amount_too_small", None

        rate = _route_rate(give_resource, receive_resource, cfg)
        now = time.time()
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        lock_player_for_update(conn, int(player_id))

        cur = conn.cursor()
        cur.execute(
            "SELECT id, player_id, metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
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
        if used + give_amount > float(daily_limit):
            rollback(conn)
            return False, "daily_limit_exceeded", {
                "daily_limit": int(daily_limit),
                "daily_used": int(used),
                "daily_remaining": max(0, int(daily_limit - used)),
            }

        current_metal = float(planet["metal"] or 0)
        current_crystal = float(planet["crystal"] or 0)
        current_fuel = float(planet["fuel_cells"] or 0)

        balances = {
            "metal": current_metal,
            "crystal": current_crystal,
            "fuel_cells": current_fuel,
        }
        if balances[give_resource] < give_amount:
            rollback(conn)
            return False, "insufficient_balance", None

        new_metal = current_metal
        new_crystal = current_crystal
        new_fuel = current_fuel

        if give_resource == "metal":
            new_metal -= give_amount
        elif give_resource == "crystal":
            new_crystal -= give_amount
        else:
            new_fuel -= give_amount

        if receive_resource == "metal":
            new_metal += receive_amount
        elif receive_resource == "crystal":
            new_crystal += receive_amount
        else:
            new_fuel += receive_amount

        cur.execute(
            """
            UPDATE planets
            SET metal = ?, crystal = ?, fuel_cells = ?, last_update = ?
            WHERE id = ?;
            """,
            (
                max(0.0, new_metal),
                max(0.0, new_crystal),
                max(0.0, new_fuel),
                now,
                int(planet_id),
            ),
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
                give_resource,
                float(give_amount),
                receive_resource,
                float(receive_amount),
                now,
            ),
        )

        commit(conn)
        return True, "ok", {
            "from": give_resource,
            "to": receive_resource,
            "give_amount": give_amount,
            "receive_resource": receive_resource,
            "receive_amount": receive_amount,
            "rate": rate,
            "balances": {
                "metal": max(0, int(new_metal)),
                "crystal": max(0, int(new_crystal)),
                "fuel_cells": max(0, int(new_fuel)),
            },
        }
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own:
            conn.close()
