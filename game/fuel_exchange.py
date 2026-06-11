"""Deprecated — use game/exchange.py unified resource trader (GC-402)."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from .exchange import execute_exchange, exchange_schema_ready, get_exchange_config


def fuel_exchange_schema_ready(conn) -> bool:
    return exchange_schema_ready(conn)


def get_fuel_exchange_config(conn=None) -> Dict[str, Any]:
    cfg = get_exchange_config(conn=conn)
    return {
        "enabled": cfg["enabled"] and cfg["fuel_enabled"],
        "metal_per_unit": cfg["fuel_metal_per_unit"],
        "crystal_per_unit": cfg["fuel_crystal_per_unit"],
        "min_units": cfg["fuel_min_units"],
        "daily_units_limit": cfg["daily_limit_admin"],
    }


def get_fuel_exchange_status(*args, **kwargs) -> Dict[str, Any]:
    """Legacy stub — unified exchange status lives in get_exchange_status()."""
    return {"ready": False, "enabled": False, "deprecated": True}


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
    """Legacy API — maps fuel purchase to metal -> fuel_cells exchange."""
    try:
        qty = int(units)
    except (TypeError, ValueError):
        return False, "invalid_amount", None

    cfg = get_exchange_config(conn=conn)
    metal_amount = qty * max(1, int(cfg["fuel_metal_per_unit"]))
    return execute_exchange(
        player_id=player_id,
        planet_id=planet_id,
        from_resource="metal",
        to_resource="fuel_cells",
        amount=metal_amount,
        conn=conn,
    )
