"""Orbital Shipyard — Phase 1 instant ship construction."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .db import begin_write_transaction, commit, in_transaction, rollback
from .fleet_calc import normalize_ships
from .fleet_defs import (
    ACTIVE_SHIP_KEYS,
    SHIPS,
    canonical_ship_key,
    get_ship,
    is_known_ship_key,
    ship_display_role,
    ship_icon_static_path,
    sort_ship_keys_by_role,
)
from .models import db, get_planet_buildings, lock_planet_for_update

BUILD_TIME_LEVEL_FACTOR = 0.975  # GC-863A — −2.5% ship build time per shipyard level above 1


def _shipyard_speed_multiplier(*, conn=None) -> float:
    """Universe-wide ship build speed from Admin → Balance (higher = faster)."""
    try:
        from .models import get_game_settings

        settings = get_game_settings(conn=conn) if conn is not None else get_game_settings()
        raw = float((settings or {}).get("shipyard_speed", 1.0) or 1.0)
        return max(0.1, min(10.0, raw))
    except (TypeError, ValueError):
        return 1.0


def get_shipyard_level(player_id: int, planet_id: int, *, conn=None) -> int:
    """Orbital Shipyard level for a player-owned planet."""
    return shipyard_level_for_planet(int(planet_id), conn=conn)


def shipyard_level_for_planet(planet_id: int, *, conn=None) -> int:
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    orbital = int(buildings.get("orbital_shipyard") or 0)
    legacy = int(buildings.get("shipyard") or 0)
    return max(0, orbital, legacy)


def orbital_production_batch_capacity(shipyard_level: int) -> int:
    """Parallel units built per production cycle (late-game quadratic-ish curve)."""
    lvl = max(1, int(shipyard_level or 1))
    return max(1, int(math.floor(1 + lvl * 5 + lvl**2.3)))


def shipyard_batch_capacity(shipyard_level: int) -> int:
    """Alias for yard parallel slots per build cycle."""
    return orbital_production_batch_capacity(shipyard_level)


def base_unit_seconds_for_ship(ship_key: str) -> int:
    """Intrinsic build time from ship defs (before yard level / speed modifiers)."""
    spec = get_ship(ship_key) or {}
    return max(1, int(spec.get("build_seconds") or 1))


def unit_batch_capacity(shipyard_level: int, base_unit_seconds: int | None = None) -> int:
    """Parallel units per build cycle (same for all ship types at this yard level)."""
    _ = base_unit_seconds  # legacy callers pass ship base seconds; capacity is yard-only
    return orbital_production_batch_capacity(shipyard_level)


PRODUCTION_TECH_EXAMPLE_BASE_SECONDS: Dict[str, int] = {
    "light": 30,
    "medium": 120,
    "heavy": 480,
}


def shipyard_level_from_buildings(buildings: Mapping[str, Any] | None) -> int:
    """Orbital shipyard level from planet building map (minimum 1 when yard exists)."""
    if not buildings:
        return 1
    orbital = int(buildings.get("orbital_shipyard") or 0)
    legacy = int(buildings.get("shipyard") or 0)
    lvl = max(orbital, legacy)
    return max(1, lvl) if lvl > 0 else 1


def production_metrics_at_yard(
    *,
    base_unit_seconds: int,
    shipyard_level: int,
    effective_unit_seconds: int | None = None,
) -> Dict[str, Any]:
    """Authoritative production snapshot for detail cards and building technical sheets."""
    lvl = max(1, int(shipyard_level or 1))
    base = max(1, int(base_unit_seconds))
    unit = max(1, int(effective_unit_seconds if effective_unit_seconds is not None else base))
    yard_cap = orbital_production_batch_capacity(lvl)
    reduction = (
        int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)) * 100)) if lvl > 1 else 0
    )
    samples: Dict[str, int] = {}
    cycle_samples: Dict[str, int] = {}
    for amt in (1, 10, 100, 1000):
        cycles = (amt + yard_cap - 1) // yard_cap
        cycle_samples[str(amt)] = cycles
        samples[str(amt)] = production_job_duration_seconds(
            unit_seconds=unit, amount=amt, batch_capacity=yard_cap
        )
    parallel_examples: Dict[str, int] = {
        tag: yard_cap for tag in PRODUCTION_TECH_EXAMPLE_BASE_SECONDS
    }
    return {
        "cycle_seconds": unit,
        "base_unit_seconds": base,
        "yard_batch_capacity": yard_cap,
        "effective_batch_capacity": yard_cap,
        "batch_capacity": yard_cap,
        "build_time_reduction_percent": reduction,
        "order_duration_samples": samples,
        "order_cycle_samples": cycle_samples,
        "parallel_examples": parallel_examples,
    }


def production_job_duration_seconds(
    *, unit_seconds: int, amount: int, batch_capacity: int
) -> int:
    """Order duration: ceil(amount / capacity) production cycles × unit_seconds."""
    unit = max(1, int(unit_seconds))
    cap = max(1, int(batch_capacity))
    amt = max(1, int(amount))
    batches = (amt + cap - 1) // cap
    return max(1, batches * unit)


def production_infer_total_units(
    *,
    remaining: int,
    scheduled_duration: int,
    unit_seconds: int,
    batch_capacity: int,
) -> int:
    """Recover original order size from remaining amount + scheduled batch duration."""
    rem = max(0, int(remaining))
    if rem <= 0:
        return 0
    unit = max(1, int(unit_seconds))
    cap = max(1, int(batch_capacity))
    batches = max(1, int(scheduled_duration) // unit)
    max_for_duration = batches * cap
    min_for_duration = (batches - 1) * cap + 1
    candidate = (batches - 1) * cap + rem
    if min_for_duration <= candidate <= max_for_duration:
        return candidate
    if rem <= max_for_duration:
        return rem
    return max_for_duration


def production_units_elapsed(
    *,
    started_at: float,
    now: float,
    unit_seconds: int,
    batch_capacity: int,
    total_units: int,
    epsilon: float = 0.0,
) -> int:
    """Units that should have been delivered by ``now`` (batch production)."""
    unit = max(1, int(unit_seconds))
    cap = max(1, int(batch_capacity))
    elapsed = float(now) + float(epsilon) - float(started_at)
    if elapsed < unit:
        return 0
    batches_done = int(elapsed // unit)
    return min(max(0, int(total_units)), batches_done * cap)


def production_progressive_units_to_deliver(
    *,
    remaining: int,
    total_units: int,
    started_at: float,
    finish_at: float,
    unit_seconds: int,
    batch_capacity: int,
    now: float,
    epsilon: float = 0.0,
) -> int:
    """How many units from an active job are due for delivery at ``now``."""
    rem = max(0, int(remaining))
    if rem <= 0:
        return 0
    if float(now) + float(epsilon) >= float(finish_at):
        return rem
    total = max(rem, int(total_units))
    already_delivered = total - rem
    units_elapsed = production_units_elapsed(
        started_at=started_at,
        now=now,
        unit_seconds=unit_seconds,
        batch_capacity=batch_capacity,
        total_units=total,
        epsilon=epsilon,
    )
    return max(0, min(rem, units_elapsed - already_delivered))


def production_next_batch_finish_at(
    *,
    started_at: float,
    delivered: int,
    unit_seconds: int,
    batch_capacity: int,
) -> float:
    """Unix time when the next production batch completes."""
    unit = max(1, int(unit_seconds))
    cap = max(1, int(batch_capacity))
    delivered_n = max(0, int(delivered))
    if delivered_n <= 0:
        next_batch = 1
    else:
        next_batch = (delivered_n + cap - 1) // cap + 1
    return float(started_at) + next_batch * unit


def production_active_order_remaining_seconds(
    *,
    remaining_amount: int,
    unit_seconds: int,
    batch_capacity: int,
    started_at: float,
    delivered: int,
    now: float,
) -> int:
    """Wall-clock seconds left on an active batch order (stable yard params).

    ``ceil(remaining / capacity)`` cycles, with the current cycle ending at
    ``production_next_batch_finish_at`` (preserves mid-cycle progress via started_at).
    """
    rem = max(0, int(remaining_amount))
    if rem <= 0:
        return 0
    unit = max(1, int(unit_seconds))
    cap = max(1, int(batch_capacity))
    batches_left = (rem + cap - 1) // cap
    next_at = production_next_batch_finish_at(
        started_at=float(started_at),
        delivered=max(0, int(delivered)),
        unit_seconds=unit,
        batch_capacity=cap,
    )
    first = max(0.0, float(next_at) - float(now))
    return max(0, int(math.ceil(first + max(0, batches_left - 1) * unit)))


def production_schedule_matches_live_params(
    *,
    scheduled_duration: int,
    total_units: int,
    unit_seconds: int,
    batch_capacity: int,
) -> bool:
    """True when stored finish-start duration matches current batch formula for total_units."""
    total = max(0, int(total_units))
    if total <= 0:
        return True
    unit = max(1, int(unit_seconds))
    expected = production_job_duration_seconds(
        unit_seconds=unit,
        amount=total,
        batch_capacity=batch_capacity,
    )
    return abs(int(scheduled_duration) - expected) <= 1


def production_live_order_remaining_seconds(
    *,
    remaining_amount: int,
    unit_seconds: int,
    batch_capacity: int,
    started_at: float,
    delivered: int,
    now: float,
    scheduled_duration: int | None = None,
    total_units: int | None = None,
) -> int:
    """Batch remaining seconds; falls back when yard level/speed drifted vs schedule."""
    rem = max(0, int(remaining_amount))
    if rem <= 0:
        return 0
    unit = max(1, int(unit_seconds))
    cap = max(1, int(batch_capacity))
    total = max(rem, int(total_units if total_units is not None else rem))
    if scheduled_duration is not None and not production_schedule_matches_live_params(
        scheduled_duration=int(scheduled_duration),
        total_units=total,
        unit_seconds=unit,
        batch_capacity=cap,
    ):
        # Params changed mid-job — recompute from remaining only (no stale delivered).
        return production_job_duration_seconds(
            unit_seconds=unit, amount=rem, batch_capacity=cap
        )
    return production_active_order_remaining_seconds(
        remaining_amount=rem,
        unit_seconds=unit,
        batch_capacity=cap,
        started_at=float(started_at),
        delivered=max(0, int(delivered)),
        now=float(now),
    )


def _directive_time_speed(
    planet_id: int | None,
    speed_key: str,
    *,
    conn=None,
) -> float:
    if not planet_id or not conn:
        return 1.0
    try:
        from .galactic_directives.mechanics import get_planet_directive_er_modifiers

        mods = get_planet_directive_er_modifiers(int(planet_id), conn=conn)
        return float(mods.get(speed_key, 1.0) or 1.0)
    except Exception:
        return 1.0


def _effective_build_seconds(
    ship_key: str,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
) -> int:
    spec = get_ship(ship_key)
    if not spec:
        return 0
    base = max(1, int(spec.get("build_seconds") or 1))
    lvl = max(1, int(shipyard_level or 1))
    seconds = max(1, int(math.ceil(base * (BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)))))
    speed = _shipyard_speed_multiplier(conn=conn) * _directive_time_speed(
        planet_id, "shipyard_time_speed", conn=conn
    )
    return max(1, int(math.ceil(seconds / speed)))


def unit_build_seconds(
    ship_key: str,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
) -> int:
    """Per-ship build time for one unit (progressive shipyard delivery)."""
    return _effective_build_seconds(
        ship_key, shipyard_level, conn=conn, planet_id=planet_id
    )


def _unit_build_cost(
    ship_key: str,
    *,
    planet_id: int | None = None,
    conn=None,
) -> Dict[str, int]:
    spec = get_ship(ship_key) or {}
    raw = spec.get("build_cost") or {}
    cost = {
        "metal": max(0, int(raw.get("metal") or 0)),
        "crystal": max(0, int(raw.get("crystal") or 0)),
        "fuel_cells": max(0, int(raw.get("fuel_cells") or 0)),
    }
    # GC-720J: expansion directive reduces Seed Ark (colonize) build cost.
    if str(ship_key) == "seed_ark" and planet_id is not None:
        try:
            from .galactic_directives.mechanics import get_directive_flags_for_galaxy

            row = None
            if conn is not None:
                row = conn.execute(
                    "SELECT galaxy FROM planets WHERE id = ? LIMIT 1;",
                    (int(planet_id),),
                ).fetchone()
            galaxy = int(row["galaxy"]) if row and row["galaxy"] is not None else 0
            if galaxy > 0:
                flags = get_directive_flags_for_galaxy(galaxy, conn=conn) or {}
                mult = float(flags.get("colonize_cost_mult") or 1.0)
                if mult != 1.0:
                    cost = {
                        "metal": max(0, int(cost["metal"] * mult)),
                        "crystal": max(0, int(cost["crystal"] * mult)),
                        "fuel_cells": max(0, int(cost["fuel_cells"] * mult)),
                    }
        except Exception:
            pass
    return cost


def ship_unlocked(
    ship_key: str,
    shipyard_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
) -> bool:
    spec = get_ship(ship_key)
    if not spec or spec.get("phase2_only"):
        return False
    need = int(spec.get("required_shipyard_level") or 99)
    if int(shipyard_level) < need:
        return False
    if player_id is not None and planet_id is not None:
        from .models import get_planet_buildings, get_research_levels
        from .ship_requirements import check_ship_requirements

        buildings = get_planet_buildings(int(planet_id), conn=conn)
        research = get_research_levels(user_id=int(player_id), conn=conn)
        ok, _ = check_ship_requirements(ship_key, buildings=buildings, research=research)
        return ok
    return True


def _ship_catalog_entry(
    ship_key: str,
    shipyard_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
) -> Dict[str, Any]:
    spec = get_ship(ship_key) or {}
    cost = _unit_build_cost(ship_key, planet_id=planet_id, conn=conn)
    unlocked = ship_unlocked(
        ship_key,
        shipyard_level,
        player_id=player_id,
        planet_id=planet_id,
        conn=conn,
    )
    max_qty = (
        max_build_amount_for_planet(0, 0, 0, ship_key, shipyard_level, player_id=player_id, planet_id=planet_id, conn=conn)
        if unlocked
        else 0
    )
    entry: Dict[str, Any] = {
        "ship_key": ship_key,
        "role": ship_display_role(ship_key),
        "attack": int(spec.get("attack", 0) or 0),
        "shield": int(spec.get("shield", 0) or 0),
        "hull": int(spec.get("hull", 0) or 0),
        "required_shipyard_level": int(spec.get("required_shipyard_level") or 99),
        "unlocked": unlocked,
        "cost_metal": cost["metal"],
        "cost_crystal": cost["crystal"],
        "cost_fuel_cells": cost["fuel_cells"],
        "build_seconds": _effective_build_seconds(ship_key, shipyard_level, conn=conn),
        "effective_batch_capacity": unit_batch_capacity(
            shipyard_level, base_unit_seconds_for_ship(ship_key)
        ),
        "max_build": max_qty,
        "can_build": False,
        "block_reason": "",
        "icon": ship_icon_static_path(ship_key),
        "owned_count": 0,
    }
    if player_id is not None and planet_id is not None:
        from .models import get_planet_buildings, get_research_levels
        from .ship_requirements import requirements_summary_for_client

        buildings = get_planet_buildings(int(planet_id), conn=conn)
        research = get_research_levels(user_id=int(player_id), conn=conn)
        entry["requirements"] = requirements_summary_for_client(
            ship_key, buildings=buildings, research=research
        )
    return entry


def list_buildable_ships(player_id: int, planet_id: int, *, conn=None) -> List[Dict[str, Any]]:
    sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
    metal, crystal, fuel = _planet_resources(planet_id, conn=conn)
    from .shipyard_queue import get_shipyard_queue_limit, queue_count, shipyard_queue_table_ready

    queue_full = False
    if shipyard_queue_table_ready(conn):
        queue_full = queue_count(planet_id, conn=conn) >= get_shipyard_queue_limit(conn=conn)
    ships_inv = get_ship_inventory(player_id, planet_id, conn=conn)
    out: List[Dict[str, Any]] = []
    for key in sort_ship_keys_by_role(ACTIVE_SHIP_KEYS):
        if not ship_unlocked(key, sy_level, player_id=player_id, planet_id=planet_id, conn=conn):
            continue
        entry = _ship_catalog_entry(
            key, sy_level, player_id=player_id, planet_id=planet_id, conn=conn
        )
        entry["max_build"] = max_build_amount_for_planet(
            metal, crystal, fuel, key, sy_level, player_id=player_id, planet_id=planet_id, conn=conn
        )
        if queue_full:
            entry["block_reason"] = "queue_full"
            entry["can_build"] = False
        elif entry["max_build"] <= 0:
            entry["block_reason"] = "not_enough_resources"
            entry["can_build"] = False
        else:
            entry["block_reason"] = ""
            entry["can_build"] = True
        entry["owned_count"] = int(ships_inv.get(key, 0) or 0)
        out.append(entry)
    return out


def cancel_shipyard_job(
    *,
    player_id: int,
    planet_id: int,
    job_id: int,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    own = conn is None
    if own:
        conn = db()
    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        lock_planet_for_update(conn, int(planet_id))
        sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
        from .shipyard_queue import cancel_queue_job

        ok, reason = cancel_queue_job(
            player_id=int(player_id),
            planet_id=int(planet_id),
            job_id=int(job_id),
            shipyard_level=sy_level,
            conn=conn,
        )
        if not ok:
            if own or began_tx:
                rollback(conn)
            return False, reason, None
        if own or began_tx:
            commit(conn)
        return True, "", build_shipyard_api_payload(int(player_id), int(planet_id), conn=conn)
    except Exception:
        if own or began_tx:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def move_shipyard_job(
    *,
    player_id: int,
    planet_id: int,
    job_id: int,
    direction: str,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    own = conn is None
    if own:
        conn = db()
    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        lock_planet_for_update(conn, int(planet_id))
        sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
        from .shipyard_queue import move_queue_job

        ok, reason = move_queue_job(
            player_id=int(player_id),
            planet_id=int(planet_id),
            job_id=int(job_id),
            direction=str(direction or "").strip().lower(),
            shipyard_level=sy_level,
            conn=conn,
        )
        if not ok:
            if own or began_tx:
                rollback(conn)
            return False, reason, None
        if own or began_tx:
            commit(conn)
        return True, "", build_shipyard_api_payload(int(player_id), int(planet_id), conn=conn)
    except Exception:
        if own or began_tx:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def list_locked_ships(player_id: int, planet_id: int, *, conn=None) -> List[Dict[str, Any]]:
    sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
    ships_inv = get_ship_inventory(player_id, planet_id, conn=conn)
    out: List[Dict[str, Any]] = []
    keys = sort_ship_keys_by_role(ACTIVE_SHIP_KEYS)
    for key in keys:
        if ship_unlocked(key, sy_level, player_id=player_id, planet_id=planet_id, conn=conn):
            continue
        entry = _ship_catalog_entry(key, sy_level, player_id=player_id, planet_id=planet_id, conn=conn)
        entry["owned_count"] = int(ships_inv.get(key, 0) or 0)
        out.append(entry)
    return out


def max_build_amount_for_planet(
    metal_have: float,
    crystal_have: float,
    fuel_have: float,
    ship_key: str,
    shipyard_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
) -> int:
    sk = canonical_ship_key(ship_key)
    if not ship_unlocked(
        sk, shipyard_level, player_id=player_id, planet_id=planet_id, conn=conn
    ):
        return 0
    cost = _unit_build_cost(sk, planet_id=planet_id, conn=conn)
    if cost["metal"] <= 0 and cost["crystal"] <= 0 and cost["fuel_cells"] <= 0:
        return 0
    limits: List[int] = []
    if cost["metal"] > 0:
        limits.append(int(metal_have) // cost["metal"])
    if cost["crystal"] > 0:
        limits.append(int(crystal_have) // cost["crystal"])
    if cost["fuel_cells"] > 0:
        limits.append(int(fuel_have) // cost["fuel_cells"])
    if not limits:
        return 0
    return max(0, min(limits))


def can_build_ship(
    player_id: int,
    planet_id: int,
    ship_key: str,
    amount: int,
    *,
    conn=None,
) -> Tuple[bool, str]:
    sk = canonical_ship_key(ship_key)
    if not is_known_ship_key(sk) or sk not in SHIPS:
        return False, "unknown_ship"
    from .number_format import parse_int_number

    qty = parse_int_number(amount, default=0)
    if qty <= 0:
        return False, "invalid_amount"

    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        if not cur.fetchone():
            return False, "planet_not_found"

        sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
        if sy_level <= 0:
            return False, "shipyard_required"
        spec = get_ship(sk) or {}
        need_sy = int(spec.get("required_shipyard_level") or 99)
        if sy_level < need_sy:
            return False, "shipyard_level_too_low"
        if not ship_unlocked(sk, sy_level, player_id=player_id, planet_id=planet_id, conn=conn):
            return False, "requirements"

        from .shipyard_queue import get_shipyard_queue_limit, queue_count, shipyard_queue_table_ready

        if shipyard_queue_table_ready(conn) and queue_count(planet_id, conn=conn) >= get_shipyard_queue_limit(
            conn=conn
        ):
            return False, "queue_full"

        metal, crystal, fuel = _planet_resources(planet_id, conn=conn)
        max_qty = max_build_amount_for_planet(metal, crystal, fuel, sk, sy_level)
        if qty > max_qty:
            return False, "not_enough_resources"
        return True, ""
    finally:
        if own and conn is not None:
            conn.close()


def _planet_resources(planet_id: int, *, conn) -> Tuple[float, float, float]:
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return 0.0, 0.0, 0.0
    return (
        float(row["metal"] or 0),
        float(row["crystal"] or 0),
        float(row["fuel_cells"] or 0),
    )


def _try_spend_build_resources(
    conn,
    planet_id: int,
    *,
    metal: int,
    crystal: int,
    fuel_cells: int,
) -> bool:
    if metal < 0 or crystal < 0 or fuel_cells < 0:
        raise ValueError("Costs must be >= 0")
    if metal == 0 and crystal == 0 and fuel_cells == 0:
        return True
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal = metal - ?,
            crystal = crystal - ?,
            fuel_cells = fuel_cells - ?
        WHERE id = ?
          AND metal >= ?
          AND crystal >= ?
          AND fuel_cells >= ?;
        """,
        (
            int(metal),
            int(crystal),
            float(fuel_cells),
            int(planet_id),
            int(metal),
            int(crystal),
            float(fuel_cells),
        ),
    )
    return cur.rowcount == 1


def build_ship(
    *,
    player_id: int,
    planet_id: int,
    ship_key: str,
    amount: int,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    """Enqueue ship construction (resources spent upfront; ships credited when job completes)."""
    return build_ships(
        player_id=player_id,
        planet_id=planet_id,
        ship_key=ship_key,
        amount=amount,
        conn=conn,
    )


def build_ships(
    *,
    player_id: int,
    planet_id: int,
    ship_key: str,
    amount: int,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    sk = canonical_ship_key(ship_key)
    ok_check, reason = can_build_ship(player_id, planet_id, sk, amount, conn=conn)
    if not ok_check:
        return False, reason, None

    from .number_format import parse_int_number

    qty = parse_int_number(amount, default=0)
    if qty <= 0:
        return False, "invalid_amount", None
    unit = _unit_build_cost(sk, planet_id=int(planet_id), conn=conn)
    total_m = unit["metal"] * qty
    total_c = unit["crystal"] * qty
    total_f = unit["fuel_cells"] * qty

    own = conn is None
    if own:
        conn = db()
    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        lock_planet_for_update(conn, int(planet_id))

        if not _try_spend_build_resources(
            conn, int(planet_id), metal=total_m, crystal=total_c, fuel_cells=total_f
        ):
            if own or began_tx:
                rollback(conn)
            return False, "not_enough_resources", None

        from .fleet import fleet_schema_ready
        from .shipyard_queue import enqueue_ship_build, shipyard_queue_table_ready

        if not fleet_schema_ready(conn):
            if own or began_tx:
                rollback(conn)
            return False, "fleet_unavailable", None

        sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
        if not shipyard_queue_table_ready(conn):
            if own or began_tx:
                rollback(conn)
            return False, "fleet_unavailable", None

        ok_q, reason_q, job_id = enqueue_ship_build(
            player_id=int(player_id),
            planet_id=int(planet_id),
            ship_key=sk,
            amount=qty,
            shipyard_level=sy_level,
            cost={"metal": total_m, "crystal": total_c, "fuel_cells": total_f},
            conn=conn,
        )
        if not ok_q:
            if own or began_tx:
                rollback(conn)
            return False, reason_q or "queue_full", None

        if own or began_tx:
            commit(conn)

        payload = build_shipyard_api_payload(
            int(player_id), int(planet_id), conn=conn
        )
        payload["ship_key"] = sk
        payload["amount"] = qty
        payload["job_id"] = job_id
        payload["cost"] = {"metal": total_m, "crystal": total_c, "fuel_cells": total_f}
        return True, "", payload
    except Exception:
        if own or began_tx:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def get_ship_inventory(player_id: int, planet_id: int, *, conn=None) -> Dict[str, int]:
    from .fleet import get_planet_ships

    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        if not cur.fetchone():
            return {}
        return get_planet_ships(int(planet_id), conn=conn)
    finally:
        if own and conn is not None:
            conn.close()


def add_ships_to_planet(
    player_id: int,
    planet_id: int,
    ship_key: str,
    amount: int,
    *,
    conn=None,
) -> Tuple[bool, str, Dict[str, int] | None]:
    sk = canonical_ship_key(ship_key)
    if not is_known_ship_key(sk):
        return False, "unknown_ship", None
    from .number_format import parse_int_number

    qty = parse_int_number(amount, default=0)
    if qty <= 0:
        return False, "invalid_amount", None

    from .fleet import add_planet_ships, fleet_schema_ready, get_planet_ships

    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        if not cur.fetchone():
            return False, "planet_not_found", None
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None
        if own:
            begin_write_transaction(conn)
        add_planet_ships(int(planet_id), int(player_id), {sk: qty}, conn=conn)
        if own:
            commit(conn)
        return True, "", get_planet_ships(int(planet_id), conn=conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def resolve_owned_planet_id(
    player_id: int,
    planet_id: int | None = None,
    *,
    conn,
) -> Tuple[int | None, str | None]:
    """Resolve a player-owned planet id (explicit or active context)."""
    if planet_id is not None:
        pid = int(planet_id)
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (pid, int(player_id)),
        )
        if not cur.fetchone():
            return None, "planet_not_found"
        return pid, None

    from .planet_evolution.repository import get_context_planet

    row = get_context_planet(int(player_id), conn=conn)
    return int(row["id"]), None


def _planet_meta(planet_id: int, *, conn) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, galaxy, system, position FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return {"planet_id": int(planet_id), "planet_name": "", "planet_coords": ""}
    coords = f"{int(row['galaxy'])}:{int(row['system'])}:{int(row['position'])}"
    name = str(row["name"] or "").strip() or coords
    return {
        "planet_id": int(row["id"]),
        "planet_name": name,
        "planet_coords": coords,
    }


def _resources_dict(planet_id: int, *, conn) -> Dict[str, int]:
    metal, crystal, fuel = _planet_resources(planet_id, conn=conn)
    return {
        "metal": int(metal),
        "crystal": int(crystal),
        "fuel_cells": int(fuel),
    }


def build_shipyard_api_payload(player_id: int, planet_id: int, *, conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
        resources = _resources_dict(planet_id, conn=conn)
        buildable = list_buildable_ships(player_id, planet_id, conn=conn)
        locked = list_locked_ships(player_id, planet_id, conn=conn)
        from .shipyard_queue import shipyard_queue_for_client

        ships = get_ship_inventory(player_id, planet_id, conn=conn)
        meta = _planet_meta(planet_id, conn=conn)
        queue = shipyard_queue_for_client(
            player_id, planet_id, sy_level, conn=conn
        )
        from .queue_card import (
            enrich_mini_queue_jobs_batch_size,
            group_card_jobs_by_owner_key,
            map_card_jobs_to_mini_queue_jobs,
            map_shipyard_queue_to_card_jobs,
        )

        card_jobs = map_shipyard_queue_to_card_jobs(queue)
        by_owner = group_card_jobs_by_owner_key(card_jobs)
        queue_payload = dict(queue)
        queue_payload["card_jobs_by_owner"] = by_owner
        queue_payload["mini_queue_jobs"] = enrich_mini_queue_jobs_batch_size(
            map_card_jobs_to_mini_queue_jobs(card_jobs, domain="shipyard"),
            domain="shipyard",
            shipyard_level=sy_level,
        )

        from .shipyard import orbital_production_batch_capacity

        return {
            "orbital_shipyard_level": sy_level,
            "production_batch_capacity": orbital_production_batch_capacity(sy_level),
            "buildable_ships": buildable,
            "locked_ships": locked,
            "current_ships": ships,
            "resources": resources,
            "fuel_cells": resources.get("fuel_cells", 0),
            "shipyard_queue": queue_payload,
            **meta,
        }
    finally:
        if own and conn is not None:
            conn.close()


def build_shipyard_page_context(player_id: int, planet: Mapping[str, Any], *, conn=None) -> Dict[str, Any]:
    planet_id = int(planet["id"])
    payload = build_shipyard_api_payload(player_id, planet_id, conn=conn)
    from .fleet_defs import ship_defs_for_client

    return {
        "ready": True,
        **payload,
        "planet_id": planet_id,
        "ship_defs": {row["key"]: row for row in ship_defs_for_client()},
    }


def _attach_queue_jobs_to_ship_rows(
    ships: List[Dict[str, Any]],
    jobs_by_key: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    """GC-536D: optional queue_job on each ship catalog row (presentation only)."""
    from .queue_card import card_queue_job_for_item

    for ship in ships:
        owner_key = str(ship.get("ship_key") or "")
        qj = card_queue_job_for_item(jobs_by_key, owner_key) if owner_key else None
        if qj:
            ship["queue_job"] = dict(qj)
        elif "queue_job" in ship:
            del ship["queue_job"]
