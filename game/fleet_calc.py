"""Fleet flight calculations — backend source of truth."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, TypedDict

from .fleet_defs import (
    ACTIVE_SHIP_KEYS,
    DEFAULT_HOLD_SECONDS,
    FLEET_FUEL_RESOURCE,
    canonical_ship_key,
    get_ship,
    is_known_ship_key,
    ship_has_role,
)
from .effects.effect_resolver import FUEL_EFFICIENCY_PER_LEVEL, EffectResolver

# OGame-style flight-time divisor (seconds scale with distance and slowest hull speed).
FLIGHT_TIME_DIVISOR = 35000.0
FUEL_DISTANCE_DIVISOR = 35000.0


def fuel_efficiency_factor(fuel_efficiency_level: int) -> float:
    return EffectResolver.fuel_efficiency_factor_for_level(fuel_efficiency_level)


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
    *,
    admin_speed_multiplier: float = 1.0,
) -> int:
    """OGame-style leg duration: (35000 / speed) * sqrt(distance / 10) adjusted by speed %."""
    if distance <= 0 or slowest_ship_speed <= 0:
        return 0
    pct = max(10, min(100, int(speed_percent)))
    speed_factor = pct / 100.0
    dist = max(1.0, float(distance))
    base = (FLIGHT_TIME_DIVISOR / float(slowest_ship_speed)) * math.sqrt(dist / 10.0)
    admin_mult = max(0.01, float(admin_speed_multiplier or 1.0))
    seconds = base / speed_factor / admin_mult
    return max(1, int(math.ceil(seconds)))


def _movement_return_leg_seconds(movement: Mapping[str, Any]) -> int:
    return max(1, int(movement.get("flight_seconds") or movement.get("duration_seconds") or 0))


def _target_stay_seconds(movement: Mapping[str, Any]) -> int:
    mission = str(movement.get("mission_type") or "").strip().lower()
    if mission == "hold":
        return DEFAULT_HOLD_SECONDS
    if mission == "expedition":
        # Canonical stay owner: fleet.expedition_stay_seconds (includes server events).
        from .fleet import expedition_stay_seconds

        resources = movement.get("resources") or {}
        return expedition_stay_seconds(resources.get("expedition_hours"))
    return 0


def movement_home_at(movement: Mapping[str, Any]) -> int:
    """Absolute unix timestamp when the fleet is back at origin (0 if not applicable)."""
    mission = str(movement.get("mission_type") or "").strip().lower()
    if mission == "deploy":
        return 0

    status = str(movement.get("status") or "").strip().lower()
    return_leg = _movement_return_leg_seconds(movement)
    persisted = max(0, int(movement.get("return_at") or movement.get("return_arrival_at") or 0))

    if status == "returning":
        return persisted

    if status == "holding":
        holding_until = max(0, int(movement.get("holding_until") or 0))
        if holding_until > 0:
            return holding_until + return_leg
        return persisted

    if status == "outbound":
        arrival_at = max(0, int(movement.get("arrival_at") or 0))
        if arrival_at <= 0:
            return 0
        return arrival_at + _target_stay_seconds(movement) + return_leg

    return persisted


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
    remaining_seconds = max(0, int(math.ceil(countdown_at - ts))) if countdown_at > 0 else 0
    home_at = movement_home_at(out)
    home_remaining_seconds = max(0, int(math.ceil(home_at - ts))) if home_at > 0 else 0

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
            "home_at": home_at,
            "home_remaining_seconds": home_remaining_seconds,
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
    fuel_efficiency_factor_override: float | None = None,
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
    if fuel_efficiency_factor_override is not None:
        factor = max(0.0, float(fuel_efficiency_factor_override))
    else:
        factor = fuel_efficiency_factor(fuel_efficiency_level)
    return max(0, int(math.ceil(base * factor)))


def calculate_total_cargo(
    ships: Mapping[str, int],
    *,
    cargo_multiplier: float = 1.0,
) -> int:
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
    mult = max(0.0, float(cargo_multiplier or 1.0))
    if abs(mult - 1.0) > 1e-9:
        total = int(math.floor(total * mult + 1e-9))
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
    # Same int truncation as planet_resource_stock / route planning — float dust
    # must not flip loaded==stock into not_enough_resources.
    metal_have_i = max(0, int(float(metal_have or 0)))
    crystal_have_i = max(0, int(float(crystal_have or 0)))
    fuel_cells_have_i = max(0, int(float(fuel_cells_have or 0)))

    if loaded["metal"] > metal_have_i or loaded["crystal"] > crystal_have_i:
        return False, "not_enough_resources"
    if loaded["fuel_cells"] > fuel_cells_have_i:
        return False, "not_enough_resources"

    if FLEET_FUEL_RESOURCE == "fuel_cells":
        if loaded["fuel_cells"] + fuel > fuel_cells_have_i:
            return False, "not_enough_fuel"
    elif FLEET_FUEL_RESOURCE == "crystal":
        crystal_needed = loaded["crystal"] + fuel
        if crystal_needed > crystal_have_i:
            if loaded["crystal"] <= crystal_have_i and fuel > crystal_have_i - loaded["crystal"]:
                return False, "not_enough_fuel"
            return False, "not_enough_resources"
    elif FLEET_FUEL_RESOURCE == "metal":
        metal_needed = loaded["metal"] + fuel
        if metal_needed > metal_have_i:
            if loaded["metal"] <= metal_have_i and fuel > metal_have_i - loaded["metal"]:
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
    speed_bonus_pct: int = 0,
    cargo_bonus_pct: int = 0,
    fuel_bonus_pct: int = 0,
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
        "speed_bonus_pct": int(speed_bonus_pct or 0),
        "cargo_bonus_pct": int(cargo_bonus_pct or 0),
        "fuel_bonus_pct": int(fuel_bonus_pct or 0),
    }


class CollectRouteLeg(TypedDict):
    """One collect transport leg: source → hub with cargo locked at send."""

    origin_planet_id: int
    planet_id: int
    galaxy: int
    system: int
    position: int
    ships: Dict[str, int]
    resources: Dict[str, int]


def normalize_collect_source_planet_ids(
    origin_planet_id: int,
    source_planet_ids: Sequence[int],
) -> List[int]:
    """Dedupe collect sources, exclude origin, preserve first-seen order before galaxy sort."""
    origin = int(origin_planet_id or 0)
    out: List[int] = []
    seen: set[int] = set()
    for raw in source_planet_ids or []:
        pid = int(raw or 0)
        if pid <= 0 or pid == origin or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def collect_route_sort_key(
    *,
    galaxy: int,
    system: int,
    position: int,
    planet_id: int,
) -> Tuple[int, int, int, int]:
    """Deterministic galaxy order for multi-colony collect legs."""
    return (int(galaxy), int(system), int(position), int(planet_id))


def validate_collect_source_planet(
    planet_row: Mapping[str, Any] | None,
    *,
    player_id: int,
) -> Tuple[bool, str, Optional[Dict[str, int]]]:
    """Planet must exist, belong to player, and have valid galaxy coordinates."""
    if planet_row is None:
        return False, "planet_not_found", None
    if int(planet_row.get("player_id") or 0) != int(player_id):
        return False, "planet_not_owned", None
    from .galaxy import GalaxyCoordinateError, get_planet_coordinates

    try:
        coords = get_planet_coordinates(dict(planet_row))
    except GalaxyCoordinateError:
        return False, "invalid_planet_coordinates", None
    return True, "", {
        "galaxy": int(coords["galaxy"]),
        "system": int(coords["system"]),
        "position": int(coords["position"]),
    }


def planet_resource_stock(planet_row: Mapping[str, Any] | None) -> Dict[str, int]:
    """Metal / crystal / fuel_cells stock from a planet row."""
    if not planet_row:
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    return {
        "metal": max(0, int(float(planet_row.get("metal") or 0))),
        "crystal": max(0, int(float(planet_row.get("crystal") or 0))),
        "fuel_cells": max(0, int(float(planet_row.get("fuel_cells") or 0))),
    }


def planet_resource_total(planet_row: Mapping[str, Any] | None) -> int:
    """Sum metal + crystal + fuel_cells on a planet row (collect auto-cargo demand)."""
    stock = planet_resource_stock(planet_row)
    return int(stock["metal"]) + int(stock["crystal"]) + int(stock["fuel_cells"])


def cargo_ship_count(ships: Mapping[str, int] | None) -> int:
    """Total units of cargo-role hulls in a ship map."""
    return sum(int(v) for v in filter_available_cargo_ships(ships).values())


def cargo_hulls_by_capacity_desc() -> List[str]:
    """Active cargo-role hulls, largest cargo first (stable key tie-break)."""
    keys: List[str] = []
    for key in ACTIVE_SHIP_KEYS:
        if ship_has_role(str(key), "cargo"):
            keys.append(str(key))
    keys.sort(key=lambda k: (-int((get_ship(k) or {}).get("cargo") or 0), k))
    return keys


def filter_available_cargo_ships(available_ships: Mapping[str, int] | None) -> Dict[str, int]:
    """Keep only cargo-role hulls with positive stock."""
    out: Dict[str, int] = {}
    for key, qty in normalize_ships(available_ships).items():
        if ship_has_role(key, "cargo") and int((get_ship(key) or {}).get("cargo") or 0) > 0:
            out[key] = int(qty)
    return out


def allocate_auto_cargo_ships(
    available_ships: Mapping[str, int] | None,
    cargo_needed: int,
) -> Dict[str, int]:
    """
    Pick free cargo hulls (largest first) until ``cargo_needed`` is covered.

    If stock cannot cover demand, returns **all** available cargo ships so the
    job can still launch as a partial collect/distribute.
    """
    stock = filter_available_cargo_ships(available_ships)
    if not stock:
        return {}
    needed = max(0, int(cargo_needed))
    if needed <= 0:
        return {}

    selected: Dict[str, int] = {}
    remaining = needed
    for key in cargo_hulls_by_capacity_desc():
        have = int(stock.get(key, 0))
        if have <= 0:
            continue
        per = int((get_ship(key) or {}).get("cargo") or 0)
        if per <= 0:
            continue
        if remaining <= 0:
            break
        take = min(have, int(math.ceil(remaining / float(per))))
        if take > 0:
            selected[key] = take
            remaining -= take * per

    if remaining > 0:
        for key in cargo_hulls_by_capacity_desc():
            have = int(stock.get(key, 0))
            already = int(selected.get(key, 0))
            left = have - already
            if left > 0:
                selected[key] = already + left

    return normalize_ships(selected)


def allocate_auto_cargo_ships_for_targets(
    available_ships: Mapping[str, int] | None,
    cargo_needed: int,
    target_count: int,
) -> Dict[str, int]:
    """
    Auto-cargo for multi-target distribute: reserve enough hulls per leg so an
    equal resource split fits each leg's cargo when stock allows.
    """
    stock = filter_available_cargo_ships(available_ships)
    if not stock:
        return {}
    n = max(1, int(target_count))
    needed = max(0, int(cargo_needed))
    if needed <= 0:
        return {}

    per_leg = int(math.ceil(needed / float(n)))
    selected: Dict[str, int] = {}
    remaining_stock = dict(stock)
    for _ in range(n):
        leg = allocate_auto_cargo_ships(remaining_stock, per_leg)
        if not leg:
            break
        for key, qty in leg.items():
            selected[key] = int(selected.get(key, 0)) + int(qty)
            left = int(remaining_stock.get(key, 0)) - int(qty)
            if left > 0:
                remaining_stock[key] = left
            else:
                remaining_stock.pop(key, None)

    if not selected:
        return allocate_auto_cargo_ships(stock, needed)
    return normalize_ships(selected)


def build_collect_route(
    *,
    origin_planet_id: int,
    source_planet_ids: Sequence[int],
    planet_rows_by_id: Mapping[int, Mapping[str, Any]],
    ships_stock_by_source: Mapping[int, Mapping[str, int]],
    free_fleet_slots: int,
    player_id: int,
    ships_selection_mode: str = "auto_cargo",
    manual_ships: Mapping[str, int] | None = None,
    speed_percent: int = 100,
    skip_empty_ship_legs: bool = False,
    skip_invalid_planets: bool = False,
) -> Tuple[bool, str, Optional[List[CollectRouteLeg]]]:
    """
    Plan source→hub transport legs.

    Freighters and cargo are taken from each **source** colony; hub is the
    delivery target. Resources are locked at plan time (debit happens on send).
    """
    from .resources import load_resources_up_to_cargo

    hub_id = int(origin_planet_id or 0)
    sources = normalize_collect_source_planet_ids(hub_id, source_planet_ids)
    if not sources:
        return False, "no_planets", None

    mode = str(ships_selection_mode or "").strip().lower() or "auto_cargo"
    manual_n = normalize_ships(manual_ships)
    if mode == "manual":
        if not manual_n:
            return False, "no_ships", None
        ok_cargo, cargo_reason = fleet_ships_are_cargo_only(manual_n)
        if not ok_cargo:
            return False, cargo_reason, None

    hub_row = planet_rows_by_id.get(hub_id)
    ok_hub, hub_reason, hub_coords = validate_collect_source_planet(
        hub_row,
        player_id=int(player_id),
    )
    if not ok_hub or not hub_coords:
        return False, hub_reason or "origin_not_found", None

    hub_target = (
        int(hub_coords["galaxy"]),
        int(hub_coords["system"]),
        int(hub_coords["position"]),
    )
    pct = max(10, min(100, int(speed_percent or 100)))

    entries: List[Dict[str, Any]] = []
    for pid in sources:
        ok, reason, coords = validate_collect_source_planet(
            planet_rows_by_id.get(int(pid)),
            player_id=int(player_id),
        )
        if not ok or not coords:
            if skip_invalid_planets:
                continue
            return False, reason or "planet_not_found", None
        entries.append(
            {
                "planet_id": int(pid),
                "galaxy": int(coords["galaxy"]),
                "system": int(coords["system"]),
                "position": int(coords["position"]),
            }
        )

    if not entries:
        return False, "no_planets", None

    entries.sort(
        key=lambda e: collect_route_sort_key(
            galaxy=int(e["galaxy"]),
            system=int(e["system"]),
            position=int(e["position"]),
            planet_id=int(e["planet_id"]),
        )
    )

    slots_free = int(free_fleet_slots)
    if slots_free <= 0:
        return False, "fleet_slots_full", None
    if len(entries) > slots_free:
        entries = entries[:slots_free]

    legs: List[CollectRouteLeg] = []
    saw_no_ships = False
    saw_no_resources = False

    for entry in entries:
        sid = int(entry["planet_id"])
        source_row = planet_rows_by_id.get(sid)
        stock = filter_available_cargo_ships(ships_stock_by_source.get(sid) or {})
        res_stock = planet_resource_stock(source_row)
        res_total = planet_resource_total(source_row)

        if mode == "auto_cargo":
            if res_total <= 0:
                saw_no_resources = True
                if skip_empty_ship_legs:
                    continue
                return False, "no_resources_on_sources", None
            ships_n = allocate_auto_cargo_ships(stock, res_total)
        else:
            ships_n = {}
            for key, need in manual_n.items():
                have = int(stock.get(key, 0))
                take = min(have, int(need))
                if take > 0:
                    ships_n[key] = take
            ships_n = normalize_ships(ships_n)

        if not ships_n or calculate_total_cargo(ships_n) <= 0:
            saw_no_ships = True
            if skip_empty_ship_legs:
                continue
            return False, "no_ships_on_sources", None

        origin_coords = (
            int(entry["galaxy"]),
            int(entry["system"]),
            int(entry["position"]),
        )
        distance = calculate_distance(origin_coords, hub_target)
        fuel_cost = calculate_fuel_cost(ships_n, distance, pct)
        cargo_cap = calculate_total_cargo(ships_n)
        loadable = {
            "metal": int(res_stock["metal"]),
            "crystal": int(res_stock["crystal"]),
            "fuel_cells": max(0, int(res_stock["fuel_cells"]) - int(fuel_cost)),
        }
        resources = load_resources_up_to_cargo(loadable, cargo_cap)
        if loaded_resource_total(resources) <= 0:
            saw_no_resources = True
            if skip_empty_ship_legs:
                continue
            return False, "no_deliverable_resources", None

        legs.append(
            {
                "origin_planet_id": sid,
                "planet_id": sid,
                "galaxy": int(hub_target[0]),
                "system": int(hub_target[1]),
                "position": int(hub_target[2]),
                "ships": dict(ships_n),
                "resources": dict(resources),
            }
        )

    if not legs:
        if saw_no_ships:
            return False, "no_ships_on_sources", None
        if saw_no_resources:
            return False, "no_resources_on_sources", None
        return False, "no_deliverable_resources", None

    return True, "", legs


def fleet_ships_are_cargo_only(ships: Mapping[str, int]) -> tuple[bool, str]:
    """Logistics bulk jobs require cargo-role hulls only."""
    ships_n = normalize_ships(ships)
    if not ships_n:
        return False, "no_ships"
    for key in ships_n:
        if not ship_has_role(str(key), "cargo"):
            return False, "no_cargo_ships"
        if int((get_ship(str(key)) or {}).get("cargo") or 0) <= 0:
            return False, "no_cargo_ships"
    return True, ""


def split_ships_across_targets(ships: Mapping[str, int], target_count: int) -> list[Dict[str, int]]:
    """Split fleet evenly; per-type remainder goes to the last target."""
    if target_count < 1:
        return []
    ships_n = normalize_ships(ships)
    parts: list[Dict[str, int]] = [{} for _ in range(target_count)]
    for key, total in ships_n.items():
        base, rem = divmod(int(total), target_count)
        for i in range(target_count - 1):
            if base > 0:
                parts[i][key] = base
        last_qty = base + rem
        if last_qty > 0:
            parts[target_count - 1][key] = last_qty
    return [normalize_ships(p) for p in parts]


def split_ships_by_weights(
    ships: Mapping[str, int],
    weights: Sequence[int],
) -> list[Dict[str, int]]:
    """Split fleet proportionally by weights (largest-remainder per hull type)."""
    n = len(weights)
    if n < 1:
        return []
    ships_n = normalize_ships(ships)
    w = [max(0, int(x)) for x in weights]
    total_w = sum(w)
    if total_w <= 0:
        return split_ships_across_targets(ships_n, n)

    parts: list[Dict[str, int]] = [{} for _ in range(n)]
    for key, total in ships_n.items():
        qty = int(total)
        if qty <= 0:
            continue
        exact = [(qty * wi) / float(total_w) for wi in w]
        floors = [int(math.floor(v)) for v in exact]
        assigned = sum(floors)
        rem = qty - assigned
        order = sorted(
            range(n),
            key=lambda i: (-(exact[i] - floors[i]), i),
        )
        for i in range(n):
            if floors[i] > 0:
                parts[i][key] = floors[i]
        for j in range(rem):
            i = order[j % n]
            parts[i][key] = int(parts[i].get(key, 0)) + 1
    return [normalize_ships(p) for p in parts]


def split_resources_evenly(resources: Mapping[str, Any], target_count: int) -> list[Dict[str, int]]:
    """Split resource totals evenly; per-type remainder goes to the last target."""
    if target_count < 1:
        return []
    loaded = calculate_loaded_resources(resources)
    parts: list[Dict[str, int]] = [
        {"metal": 0, "crystal": 0, "fuel_cells": 0} for _ in range(target_count)
    ]
    for key in ("metal", "crystal", "fuel_cells"):
        total = int(loaded.get(key, 0))
        base, rem = divmod(total, target_count)
        for i in range(target_count - 1):
            parts[i][key] = base
        parts[target_count - 1][key] = base + rem
    return [calculate_loaded_resources(p) for p in parts]


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
