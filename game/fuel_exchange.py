"""Trader Hub fuel cell exchange — premium dual-resource purchase."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Optional, Tuple

from .db import begin_write_transaction, commit, db, lock_planet_for_update, rollback
from .models import get_game_settings, get_planet_buildings, get_research_levels
from .resources import get_storage_capacity

DAY_SECONDS = 86400

_FUEL_EXCHANGE_DEFAULTS = {
    "fuel_exchange_enabled": "1",
    "fuel_exchange_metal_per_unit": "45",
    "fuel_exchange_crystal_per_unit": "28",
    "fuel_exchange_min_units": "10",
    "fuel_exchange_daily_units": "5000",
}


def fuel_exchange_schema_ready(conn) -> bool:
    from .models import column_exists, table_exists

    return table_exists(conn, "planets") and column_exists(conn, "planets", "fuel_cells")


def _float_setting(settings: Dict[str, Any], key: str, default: str) -> float:
    raw = settings.get(key, _FUEL_EXCHANGE_DEFAULTS.get(key, default))
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _int_setting(settings: Dict[str, Any], key: str, default: str) -> int:
    return max(0, int(_float_setting(settings, key, default)))


def get_fuel_exchange_config(conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        settings = get_game_settings(conn=conn)
        enabled = str(settings.get("fuel_exchange_enabled", "1")).strip() not in ("0", "false", "False")
        return {
            "enabled": enabled,
            "metal_per_unit": _int_setting(settings, "fuel_exchange_metal_per_unit", "45"),
            "crystal_per_unit": _int_setting(settings, "fuel_exchange_crystal_per_unit", "28"),
            "min_units": _int_setting(settings, "fuel_exchange_min_units", "10"),
            "daily_units_limit": _int_setting(settings, "fuel_exchange_daily_units", "5000"),
        }
    finally:
        if own and conn is not None:
            conn.close()


def _storage_caps(planet_id: int, player_id: int, conn) -> Dict[str, int]:
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    research = get_research_levels(user_id=int(player_id), conn=conn)
    return get_storage_capacity(buildings, research=research)


def get_fuel_exchange_status(player_id: int, planet_id: int, *, conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        cfg = get_fuel_exchange_config(conn=conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT metal, crystal, fuel_cells, fuel_exchange_daily_used, fuel_exchange_daily_reset_at "
            "FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        row = cur.fetchone()
        if not row:
            return {"enabled": False, "ready": False}
        planet = dict(row)
        now = time.time()
        reset_at = float(planet.get("fuel_exchange_daily_reset_at") or 0)
        used = float(planet.get("fuel_exchange_daily_used") or 0)
        if now >= reset_at:
            used = 0.0
        daily_remaining = max(0, cfg["daily_units_limit"] - int(used))
        return {
            "ready": True,
            "enabled": cfg["enabled"],
            "metal_per_unit": cfg["metal_per_unit"],
            "crystal_per_unit": cfg["crystal_per_unit"],
            "min_units": cfg["min_units"],
            "daily_units_limit": cfg["daily_units_limit"],
            "daily_units_remaining": daily_remaining,
            "planet_resources": {
                "metal": int(float(planet["metal"] or 0)),
                "crystal": int(float(planet["crystal"] or 0)),
                "fuel_cells": int(float(planet["fuel_cells"] or 0)),
            },
        }
    finally:
        if own and conn is not None:
            conn.close()


def preview_fuel_purchase(units: int, *, conn=None) -> Dict[str, int]:
    cfg = get_fuel_exchange_config(conn=conn)
    u = max(0, int(units))
    return {
        "units": u,
        "metal_cost": u * cfg["metal_per_unit"],
        "crystal_cost": u * cfg["crystal_per_unit"],
    }


def buy_fuel_cells(
    *,
    player_id: int,
    planet_id: int,
    units: int,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    cfg = get_fuel_exchange_config(conn=conn)
    if not cfg["enabled"]:
        return False, "fuel_exchange_disabled", None
    try:
        qty = int(units)
    except (TypeError, ValueError):
        return False, "invalid_amount", None
    if qty < cfg["min_units"]:
        return False, "below_minimum", None

    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT metal, crystal, fuel_cells, fuel_exchange_daily_used, fuel_exchange_daily_reset_at
            FROM planets WHERE id = ? AND player_id = ? LIMIT 1;
            """,
            (int(planet_id), int(player_id)),
        )
        row = cur.fetchone()
        if not row:
            rollback(conn)
            return False, "planet_not_found", None
        planet = dict(row)
        now = time.time()
        reset_at = float(planet.get("fuel_exchange_daily_reset_at") or 0)
        used = float(planet.get("fuel_exchange_daily_used") or 0)
        if now >= reset_at:
            used = 0.0
            reset_at = float(int(now // DAY_SECONDS) * DAY_SECONDS + DAY_SECONDS)
        if used + qty > cfg["daily_units_limit"]:
            rollback(conn)
            return False, "daily_limit", None

        metal_cost = qty * cfg["metal_per_unit"]
        crystal_cost = qty * cfg["crystal_per_unit"]
        metal_have = float(planet["metal"] or 0)
        crystal_have = float(planet["crystal"] or 0)
        if metal_have < metal_cost or crystal_have < crystal_cost:
            rollback(conn)
            return False, "not_enough_resources", None

        cur.execute(
            """
            UPDATE planets
            SET metal = metal - ?,
                crystal = crystal - ?,
                fuel_cells = fuel_cells + ?,
                fuel_exchange_daily_used = ?,
                fuel_exchange_daily_reset_at = ?
            WHERE id = ? AND metal >= ? AND crystal >= ?;
            """,
            (
                metal_cost,
                crystal_cost,
                float(qty),
                used + qty,
                reset_at,
                int(planet_id),
                metal_cost,
                crystal_cost,
            ),
        )
        if cur.rowcount != 1:
            rollback(conn)
            return False, "not_enough_resources", None

        commit(conn)

        return True, "", {
            "units": qty,
            "metal_cost": metal_cost,
            "crystal_cost": crystal_cost,
            "resources": {
                "metal": int(metal_have - metal_cost),
                "crystal": int(crystal_have - crystal_cost),
                "fuel_cells": int(float(planet["fuel_cells"] or 0) + qty),
            },
            "daily_units_remaining": max(0, cfg["daily_units_limit"] - int(used + qty)),
        }
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()
