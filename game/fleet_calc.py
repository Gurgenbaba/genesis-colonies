"""Fleet flight calculations — backend source of truth."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from .fleet_defs import FLEET_FUEL_RESOURCE, canonical_ship_key, get_ship, is_known_ship_key

# OGame-style flight-time divisor (seconds scale with distance and slowest hull speed).
FLIGHT_TIME_DIVISOR = 35000.0
FUEL_DISTANCE_DIVISOR = 35000.0
FUEL_EFFICIENCY_PER_LEVEL = 0.03
FUEL_EFFICIENCY_MIN_FACTOR = 0.5


def fuel_efficiency_factor(fuel_efficiency_level: int) -> float:
    lvl = max(0, int(fuel_efficiency_level or 0))
    return max(FUEL_EFFICIENCY_MIN_FACTOR, 1.0 - lvl * FUEL_EFFICIENCY_PER_LEVEL)


def calculate_distance(
    origin: Tuple[int, int, int],
    target: Tuple[int, int, int],
) -> int:
    """OGame-style simplified distance between two coordinates."""
    og, os, op = (int(origin[0]), int(origin[1]), int(origin[2]))
    tg, ts, tp = (int(target[0]), int(target[1]), int(target[2]))
    if (og, os, op) == (tg, ts, tp):
        return 0

    galaxy_dist = abs(og - tg) * 20000
    system_dist = abs(os - ts) * 95 + 2700
    position_dist = abs(op - tp) * 5 + 1000
    if og == tg and os == ts:
        position_dist = max(5, abs(op - tp) * 5)
        return max(1, position_dist)
    return max(1, galaxy_dist + system_dist + position_dist)


def calculate_fleet_speed(
    ships: Mapping[str, int],
    *,
    speed_multiplier: float = 1.0,
) -> int:
    """Slowest ship determines fleet speed."""
    speeds: list[int] = []
    for key, amount in ships.items():
        try:
            qty = int(amount)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        spec = get_ship(str(key))
        if spec:
            speeds.append(int(spec["speed"]))
    if not speeds:
        return 0
    base = min(speeds)
    mult = max(0.1, float(speed_multiplier or 1.0))
    return max(1, int(base * mult))


def calculate_flight_seconds(
    distance: int,
    slowest_ship_speed: int,
    speed_percent: int,
) -> int:
    """OGame-style leg duration: (35000 / speed) * sqrt(distance / 10) adjusted by speed %."""
    if distance <= 0 or slowest_ship_speed <= 0:
        return 0
    pct = max(10, min(100, int(speed_percent)))
    speed_factor = pct / 100.0
    dist = max(1.0, float(distance))
    base = (FLIGHT_TIME_DIVISOR / float(slowest_ship_speed)) * math.sqrt(dist / 10.0)
    seconds = base / speed_factor
    return max(1, int(math.ceil(seconds)))


def movement_countdown_end_at(movement: Mapping[str, Any]) -> int:
    """Absolute unix timestamp the client should count down to for this movement."""
    status = str(movement.get("status") or "").strip().lower()
    if status == "returning":
        return max(0, int(movement.get("return_at") or movement.get("return_arrival_at") or 0))
    if status == "holding":
        return max(0, int(movement.get("holding_until") or 0))
    if status == "outbound":
        return max(0, int(movement.get("arrival_at") or 0))
    return max(0, int(movement.get("countdown_at") or 0))


def enrich_movement_timing(
    movement: Mapping[str, Any],
    *,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Attach canonical timing fields for fleet UI, overview, and APIs."""
    ts = float(now if now is not None else time.time())
    out = dict(movement)
    status = str(movement.get("status") or "").strip().lower()
    departure_at = max(0, int(movement.get("departure_at") or movement.get("departed_at") or 0))
    arrival_at = max(0, int(movement.get("arrival_at") or 0))
    return_at = max(0, int(movement.get("return_at") or 0))
    holding_until = max(0, int(movement.get("holding_until") or 0))
    duration_seconds = max(0, int(movement.get("duration_seconds") or movement.get("flight_seconds") or 0))

    countdown_at = movement_countdown_end_at(out)
    remaining_seconds = max(0, int(countdown_at - ts)) if countdown_at > 0 else 0

    leg_phase = status if status in ("outbound", "returning", "holding") else ""
    leg_label_key = {
        "outbound": "fleet_leg_outbound",
        "returning": "fleet_leg_returning",
        "holding": "fleet_leg_holding",
    }.get(leg_phase, "")

    return_started_at = 0
    return_arrival_at = 0
    if status == "returning" and return_at > 0:
        return_arrival_at = return_at
        if duration_seconds > 0:
            return_started_at = max(0, return_at - duration_seconds)
        elif arrival_at > 0:
            return_started_at = arrival_at

    out.update(
        {
            "departed_at": departure_at,
            "departure_at": departure_at,
            "duration_seconds": duration_seconds,
            "flight_seconds": duration_seconds,
            "countdown_at": countdown_at,
            "remaining_seconds": remaining_seconds,
            "phase": leg_phase,
            "status_label": leg_label_key,
            "leg_phase": leg_phase,
            "leg_label_key": leg_label_key,
            "return_started_at": return_started_at,
            "return_arrival_at": return_arrival_at,
        }
    )
    return out


def build_outbound_timing(*, departure_at: float, duration_seconds: int) -> Dict[str, int]:
    """Outbound leg timestamps persisted on send."""
    dep = max(0, int(departure_at))
    dur = max(1, int(duration_seconds))
    return {
        "departure_at": dep,
        "departed_at": dep,
        "arrival_at": dep + dur,
        "duration_seconds": dur,
        "flight_seconds": dur,
    }


def build_return_timing(*, return_started_at: float, duration_seconds: int) -> Dict[str, int]:
    """Return leg timestamps set when a mission starts its return flight."""
    started = max(0, int(return_started_at))
    dur = max(1, int(duration_seconds))
    return_at = started + dur
    return {
        "return_started_at": started,
        "return_arrival_at": return_at,
        "return_at": return_at,
    }


def calculate_fuel_cost(
    ships: Mapping[str, int],
    distance: int,
    speed_percent: int,
    *,
    fuel_efficiency_level: int = 0,
) -> int:
    if distance <= 0:
        return 0
    pct = max(10, min(100, int(speed_percent)))
    consumption_factor = 0.5 + (pct / 200.0)
    total = 0.0
    for key, amount in ships.items():
        try:
            qty = int(amount)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        spec = get_ship(str(key))
        if not spec:
            continue
        fuel_per = float(spec.get("fuel") or 0)
        total += fuel_per * qty * float(distance) / FUEL_DISTANCE_DIVISOR * consumption_factor
    base = max(0, int(math.ceil(total)))
    return max(0, int(math.ceil(base * fuel_efficiency_factor(fuel_efficiency_level))))


def calculate_total_cargo(ships: Mapping[str, int]) -> int:
    total = 0
    for key, amount in ships.items():
        try:
            qty = int(amount)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        spec = get_ship(str(key))
        if spec:
            total += int(spec.get("cargo") or 0) * qty
    return max(0, total)


def calculate_loaded_resources(resources: Mapping[str, Any] | None) -> Dict[str, int]:
    raw = resources or {}
    metal = max(0, int(float(raw.get("metal") or 0)))
    crystal = max(0, int(float(raw.get("crystal") or 0)))
    fuel_cells = max(0, int(float(raw.get("fuel_cells") or 0)))
    return {"metal": metal, "crystal": crystal, "fuel_cells": fuel_cells}


def loaded_resource_total(resources: Mapping[str, Any] | None) -> int:
    loaded = calculate_loaded_resources(resources)
    return loaded["metal"] + loaded["crystal"] + loaded["fuel_cells"]


def validate_departure_balances(
    metal_have: float,
    crystal_have: float,
    fuel_cells_have: float,
    resources: Mapping[str, Any] | None,
    fuel_cost: int,
) -> tuple[bool, str]:
    """Validate loaded cargo + fuel cells against planet balances."""
    loaded = calculate_loaded_resources(resources)
    fuel = max(0, int(fuel_cost))

    if loaded["metal"] > metal_have or loaded["crystal"] > crystal_have:
        return False, "not_enough_resources"
    if loaded["fuel_cells"] > fuel_cells_have:
        return False, "not_enough_resources"

    if FLEET_FUEL_RESOURCE == "fuel_cells":
        if loaded["fuel_cells"] + fuel > fuel_cells_have:
            return False, "not_enough_fuel"
    elif FLEET_FUEL_RESOURCE == "crystal":
        crystal_needed = loaded["crystal"] + fuel
        if crystal_needed > crystal_have:
            if loaded["crystal"] <= crystal_have and fuel > crystal_have - loaded["crystal"]:
                return False, "not_enough_fuel"
            return False, "not_enough_resources"
    elif FLEET_FUEL_RESOURCE == "metal":
        metal_needed = loaded["metal"] + fuel
        if metal_needed > metal_have:
            if loaded["metal"] <= metal_have and fuel > metal_have - loaded["metal"]:
                return False, "not_enough_fuel"
            return False, "not_enough_resources"
    else:
        return False, "invalid_fuel_resource"

    return True, ""


def apply_departure_deduction(
    metal_have: float,
    crystal_have: float,
    fuel_cells_have: float,
    resources: Mapping[str, Any] | None,
    fuel_cost: int,
) -> tuple[float, float, float]:
    loaded = calculate_loaded_resources(resources)
    fuel = max(0, int(fuel_cost))
    new_metal = float(metal_have) - loaded["metal"]
    new_crystal = float(crystal_have) - loaded["crystal"]
    new_fuel_cells = float(fuel_cells_have) - loaded["fuel_cells"]
    if FLEET_FUEL_RESOURCE == "fuel_cells":
        new_fuel_cells -= fuel
    elif FLEET_FUEL_RESOURCE == "crystal":
        new_crystal -= fuel
    elif FLEET_FUEL_RESOURCE == "metal":
        new_metal -= fuel
    return new_metal, new_crystal, new_fuel_cells


def build_flight_preview_payload(
    *,
    distance: int,
    fleet_speed: int,
    flight_seconds: int,
    fuel_cost: int,
    cargo_total: int,
    resources: Mapping[str, Any] | None,
    fuel_cells_have: float = 0,
) -> Dict[str, Any]:
    loaded = calculate_loaded_resources(resources)
    loaded_total = loaded["metal"] + loaded["crystal"] + loaded["fuel_cells"]
    fuel = max(0, int(fuel_cost))
    available = max(0, int(float(fuel_cells_have)))
    fuel_needed = fuel
    if FLEET_FUEL_RESOURCE == "fuel_cells":
        fuel_needed = loaded["fuel_cells"] + fuel
    return {
        "distance": distance,
        "fleet_speed": fleet_speed,
        "flight_seconds": flight_seconds,
        "fuel_cost": fuel,
        "fuel_resource": FLEET_FUEL_RESOURCE,
        "fuel_available": available,
        "fuel_after_send": max(0, available - fuel_needed),
        "can_afford_fuel": available >= fuel_needed,
        "cargo_total": cargo_total,
        "cargo_free": max(0, cargo_total - loaded_total),
        "cargo_used": loaded_total,
        "resources": loaded,
    }


def normalize_ships(raw: Mapping[str, Any] | None) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not raw:
        return out
    for key, amount in raw.items():
        sk = canonical_ship_key(str(key or "").strip())
        if not sk or not is_known_ship_key(sk):
            continue
        try:
            qty = int(amount)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            out[sk] = out.get(sk, 0) + qty
    return out
