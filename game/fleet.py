"""Fleet system — ships, movements, presets, tick processing, and APIs."""

from __future__ import annotations

import json
import logging
import math
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, TypedDict

from .db import (
    begin_write_transaction,
    commit,
    db,
    is_sqlite_lock_error,
    lock_planet_for_update,
    rollback,
    table_exists,
)
from .fleet_calc import (
    allocate_auto_cargo_ships_for_targets,
    apply_departure_deduction,
    build_collect_route,
    build_flight_preview_payload,
    build_outbound_timing,
    build_return_timing,
    calculate_distance,
    calculate_fleet_speed,
    calculate_flight_seconds,
    calculate_fuel_cost,
    calculate_loaded_resources,
    calculate_total_cargo,
    enrich_movement_timing,
    fleet_ships_are_cargo_only,
    loaded_resource_total,
    collect_route_sort_key,
    normalize_collect_source_planet_ids,
    normalize_ships,
    split_resources_evenly,
    split_ships_across_targets,
    validate_collect_source_planet,
    validate_departure_balances,
)
from .fleet_defs import (
    ACTIVE_FLEET_STATUSES,
    BATCH_STATUSES,
    BATCH_TYPES,
    DEFAULT_EXPEDITION_STAY_HOURS,
    DEFAULT_HOLD_SECONDS,
    DEV_SEED_SHIPS,
    EXPEDITION_POSITION,
    EXPEDITION_STAY_HOUR_SECONDS,
    EXPEDITION_STAY_HOURS_MAX,
    EXPEDITION_STAY_HOURS_MIN,
    FLEET_FUEL_RESOURCE,
    FLEET_MISSION_ORDER,
    FLEET_SPEED_HOLD_MISSIONS,
    FLEET_SPEED_WAR_MISSIONS,
    MASS_EXPEDITION_SLOT_RESERVE,
    MASS_EXPEDITION_STAGGER_SECONDS,
    MISSION_TYPES,
    PRESET_TYPES,
    all_ship_keys,
    canonical_ship_key,
    is_known_ship_key,
    ships_for_fleet_ui,
)
from .galaxy import (
    GalaxyCoordinateError,
    format_coordinates,
    get_planet_coordinates,
    validate_coordinates,
)
from .expedition_events import (
    build_expedition_fleet_rating,
    build_expedition_report,
    calculate_expedition_loot_cap,
    count_expedition_ships,
    expedition_daily_efficiency_multiplier,
    expedition_daily_status,
    get_expedition_daily_count,
    grant_expedition_lootboxes,
    record_expedition_daily_value,
    resolve_expedition_outcome,
)
from .messages import (
    notify_combat,
    notify_espionage,
    notify_expedition,
    notify_logistics_fleet_report,
    notify_transport,
    _notify_player_idempotent_fleet,
)
from .models import get_planets_by_player, get_research_levels
from .spy import (
    SPY_INTEL_TIER_ACTIVITY,
    SPY_INTEL_TIER_BUILDINGS,
    SPY_INTEL_TIER_DEFENSE,
    SPY_INTEL_TIER_FLEET,
    SPY_INTEL_TIER_FUEL,
    SPY_INTEL_TIER_RESOURCES,
    SPY_INTEL_TIER_TARGET,
    SPY_REPORT_VERSION,
    build_spy_report_body as _build_spy_report_body,
    probe_count as _spy_probe_count,
    target_planet_snapshot as _target_planet_snapshot,
)

logger = logging.getLogger(__name__)

TARGET_TYPES = frozenset(
    {
        "own_planet",
        "ally_planet",
        "foreign_planet",
        "empty_slot",
        "expedition_slot",
        "strategic_world",
        "world_colony",
        "enemy_colony",
        "expedition_world",
        "anomaly",
        "wreckage",
        "planet",
        "world_boss",
        "asteroid",
        "pirate_base",
    }
)

# Canonical mission × target-type matrix (hold on allies when alliance schema exists).
_BASE_ALLOWED_MISSIONS: Dict[str, Set[str]] = {
    "own_planet": {"transport", "collect", "deploy", "spy"},
    "ally_planet": {"transport", "spy"},
    "foreign_planet": {"spy", "attack"},
    "empty_slot": {"colonize"},
    "strategic_world": {"colonize"},
    "expedition_slot": {"expedition"},
    "world_colony": {"transport", "collect", "deploy", "spy"},
    "enemy_colony": {"spy", "attack"},
    "expedition_world": {"expedition"},
    "anomaly": {"expedition"},
    "wreckage": {"recycle", "expedition"},
    "planet": {"transport", "collect", "deploy", "spy"},
    "world_boss": {"attack"},
    "asteroid": {"recycle"},
    "pirate_base": {"attack"},
}

# Recycle is intentionally excluded: it targets debris/asteroid slots, not planets.
_MISSIONS_REQUIRING_PLANET = frozenset(
    {"transport", "deploy", "spy", "attack", "hold", "collect"}
)

_MISSION_BLOCK_REASONS: Dict[str, Dict[str, str]] = {
    "own_planet": {
        "attack": "mission_blocked_own_planet",
        "hold": "mission_blocked_own_planet",
        "expedition": "mission_blocked_not_expedition_slot",
        "colonize": "mission_blocked_occupied",
    },
    "ally_planet": {
        "deploy": "mission_blocked_ally_planet",
        "attack": "mission_blocked_ally_planet",
        "collect": "mission_blocked_ally_planet",
        "expedition": "mission_blocked_not_expedition_slot",
        "colonize": "mission_blocked_occupied",
        "hold": "mission_blocked_no_alliance",
    },
    "foreign_planet": {
        "transport": "mission_blocked_foreign_planet",
        "deploy": "mission_blocked_foreign_planet",
        "hold": "mission_blocked_foreign_planet",
        "collect": "mission_blocked_foreign_planet",
        "expedition": "mission_blocked_not_expedition_slot",
        "colonize": "mission_blocked_occupied",
    },
    "empty_slot": {
        "transport": "mission_blocked_empty_slot",
        "deploy": "mission_blocked_empty_slot",
        "spy": "mission_blocked_empty_slot",
        "attack": "mission_blocked_empty_slot",
        "hold": "mission_blocked_empty_slot",
        "collect": "mission_blocked_empty_slot",
        "expedition": "mission_blocked_not_expedition_slot",
    },
    "expedition_slot": {
        "transport": "mission_blocked_expedition_slot",
        "deploy": "mission_blocked_expedition_slot",
        "spy": "mission_blocked_expedition_slot",
        "attack": "mission_blocked_expedition_slot",
        "hold": "mission_blocked_expedition_slot",
        "collect": "mission_blocked_expedition_slot",
        "colonize": "mission_blocked_expedition_slot",
        "recycle": "mission_blocked_expedition_slot",
    },
    "world_boss": {
        "transport": "mission_blocked_world_boss",
        "deploy": "mission_blocked_world_boss",
        "spy": "mission_blocked_world_boss",
        "hold": "mission_blocked_world_boss",
        "collect": "mission_blocked_world_boss",
        "expedition": "mission_blocked_not_expedition_slot",
        "colonize": "mission_blocked_world_boss",
        "recycle": "mission_blocked_world_boss",
    },
    "asteroid": {
        "transport": "mission_blocked_asteroid",
        "deploy": "mission_blocked_asteroid",
        "spy": "mission_blocked_asteroid",
        "attack": "mission_blocked_asteroid",
        "hold": "mission_blocked_asteroid",
        "collect": "mission_blocked_asteroid",
        "expedition": "mission_blocked_not_expedition_slot",
        "colonize": "mission_blocked_asteroid",
    },
    "pirate_base": {
        "transport": "mission_blocked_pirate_base",
        "deploy": "mission_blocked_pirate_base",
        "spy": "mission_blocked_pirate_base",
        "hold": "mission_blocked_pirate_base",
        "collect": "mission_blocked_pirate_base",
        "expedition": "mission_blocked_not_expedition_slot",
        "colonize": "mission_blocked_pirate_base",
        "recycle": "mission_blocked_pirate_base",
    },
}


def _target_with_debris_recycle(
    info: Dict[str, Any],
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
) -> Dict[str, Any]:
    """Attach debris snapshot and allow recycle when the field has resources."""
    from .combat import get_debris_at_field

    out = dict(info)
    debris = get_debris_at_field(int(galaxy), int(system), int(position), conn=conn)
    out["debris"] = debris
    total = int(debris.get("metal") or 0) + int(debris.get("crystal") or 0)
    if total > 0:
        allowed = set(out.get("allowed_missions") or [])
        allowed.add("recycle")
        out["allowed_missions"] = sorted(allowed)
    return out


def _maybe_world_boss_target(
    info: Dict[str, Any],
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
) -> Dict[str, Any]:
    """Override empty/occupied slot to world_boss when an active event sits here."""
    try:
        from .world_boss import get_active_event_at

        event = get_active_event_at(int(galaxy), int(system), int(position), conn=conn)
    except Exception:
        return info
    if not event:
        return info
    out = dict(info)
    out["target_type"] = "world_boss"
    out["target_planet_id"] = None
    out["target_player_id"] = None
    out["target_owner_name"] = str(event.get("boss_key") or "World Boss")
    out["allowed_missions"] = sorted(_BASE_ALLOWED_MISSIONS["world_boss"])
    out["reason_if_blocked"] = None
    out["world_boss"] = {
        "event_id": int(event["id"]),
        "boss_key": event["boss_key"],
        "current_hp": int(event["current_hp"]),
        "max_hp": int(event["max_hp"]),
        "hp_ratio": event.get("hp_ratio"),
        "ends_at": event.get("ends_at"),
    }
    return out


def _maybe_pirate_base_target(
    info: Dict[str, Any],
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
) -> Dict[str, Any]:
    """Override empty slot to pirate_base when an active hideout sits here."""
    if str(info.get("target_type") or "") == "world_boss":
        return info
    try:
        from .pirates.bases import get_active_base_at

        base = get_active_base_at(int(galaxy), int(system), int(position), conn=conn)
    except Exception:
        return info
    if not base:
        return info
    out = dict(info)
    out["target_type"] = "pirate_base"
    out["target_planet_id"] = None
    out["target_player_id"] = None
    out["target_owner_name"] = str(base.get("faction_key") or "Pirate Base")
    out["allowed_missions"] = sorted(_BASE_ALLOWED_MISSIONS["pirate_base"])
    out["reason_if_blocked"] = None
    out["pirate_base"] = {
        "base_id": int(base["id"]),
        "faction_key": base.get("faction_key"),
        "name_key": base.get("name_key"),
        "current_hp": int(base["current_hp"]),
        "max_hp": int(base["max_hp"]),
        "strength": int(base.get("strength") or 1),
        "activity": int(base.get("activity") or 0),
        "expires_at": base.get("expires_at"),
    }
    return out


def _maybe_asteroid_target(
    info: Dict[str, Any],
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
) -> Dict[str, Any]:
    """Override slot to asteroid when an active belt field sits here (before debris)."""
    if str(info.get("target_type") or "") in ("world_boss", "pirate_base"):
        return info
    try:
        from .asteroids import get_active_asteroid_at

        asteroid = get_active_asteroid_at(
            int(galaxy), int(system), int(position), conn=conn
        )
    except Exception:
        return info
    if not asteroid:
        return info
    out = dict(info)
    out["target_type"] = "asteroid"
    out["target_planet_id"] = None
    out["target_player_id"] = None
    out["target_owner_name"] = str(asteroid.get("asteroid_key") or "asteroid")
    out["allowed_missions"] = sorted(_BASE_ALLOWED_MISSIONS["asteroid"])
    out["reason_if_blocked"] = None
    out["asteroid"] = {
        "id": int(asteroid["id"]),
        "asteroid_key": asteroid.get("asteroid_key"),
        "name_key": asteroid.get("name_key"),
        "metal": int(asteroid.get("metal") or 0),
        "crystal": int(asteroid.get("crystal") or 0),
        "fuel_cells": int(asteroid.get("fuel_cells") or 0),
        "total": int(asteroid.get("total") or 0),
        "expires_at": asteroid.get("expires_at"),
        "recycler_slots_needed": int(asteroid.get("recycler_slots_needed") or 0),
    }
    return out


def _now() -> float:
    return time.time()


def _fleet_mission_locks_for_client(conn) -> Dict[str, Dict[str, Any]]:
    from .fleet_mission_locks import get_active_fleet_mission_locks_for_client

    return get_active_fleet_mission_locks_for_client(conn=conn)


def fleet_schema_ready(conn) -> bool:
    return (
        table_exists(conn, "planet_ships")
        and table_exists(conn, "fleet_movements")
        and table_exists(conn, "fleet_presets")
        and table_exists(conn, "fleet_batches")
    )


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        if raw is None or raw == "":
            return int(default)
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _row_to_movement(row: Any) -> Dict[str, Any]:
    ships = _json_loads(row["ships_json"], {}) or {}
    resources = _json_loads(row["resources_json"], {}) or {}
    tg = _safe_int(row["target_galaxy"])
    ts = _safe_int(row["target_system"])
    tp = _safe_int(row["target_position"])
    if tp == EXPEDITION_POSITION:
        target_coords = f"[{tg}:{ts}:{EXPEDITION_POSITION}]"
    else:
        target_coords = format_coordinates(tg, ts, tp)
    return {
        "id": _safe_int(row["id"]),
        "player_id": _safe_int(row["player_id"]),
        "origin_planet_id": _safe_int(row["origin_planet_id"]),
        "target_planet_id": _safe_int(row["target_planet_id"]) if row["target_planet_id"] else None,
        "target_galaxy": tg,
        "target_system": ts,
        "target_position": tp,
        "target_coords": target_coords,
        "mission_type": str(row["mission_type"]),
        "status": str(row["status"]),
        "departure_at": _safe_int(row["departure_at"]),
        "arrival_at": _safe_int(row["arrival_at"]),
        "return_at": _safe_int(row["return_at"]) if row["return_at"] else None,
        "holding_until": _safe_int(row["holding_until"]) if row["holding_until"] else None,
        "ships": ships,
        "resources": resources,
        "fuel_cost": _safe_int(row["fuel_cost"]),
        "speed_percent": _safe_int(row["speed_percent"], 100),
        "distance": _safe_int(row["distance"]),
        "flight_seconds": _safe_int(row["flight_seconds"]),
        "preset_id": _safe_int(row["preset_id"]) if row["preset_id"] else None,
        "parent_batch_id": _safe_int(row["parent_batch_id"]) if row["parent_batch_id"] else None,
        "created_at": _safe_int(row["created_at"]),
        "updated_at": _safe_int(row["updated_at"]),
    }


def _row_to_preset(row: Any) -> Dict[str, Any]:
    return {
        "id": _safe_int(row["id"]),
        "player_id": _safe_int(row["player_id"]),
        "name": str(row["name"]),
        "preset_type": str(row["preset_type"]),
        "ships": _json_loads(row["ships_json"], {}) or {},
        "resources": _json_loads(row["resources_json"], None),
        "speed_percent": _safe_int(row["speed_percent"], 100),
        "mission_type": str(row["mission_type"]) if row["mission_type"] else None,
        "target_galaxy": _safe_int(row["target_galaxy"]) if row["target_galaxy"] is not None else None,
        "target_system": _safe_int(row["target_system"]) if row["target_system"] is not None else None,
        "target_position": _safe_int(row["target_position"]) if row["target_position"] is not None else None,
        "created_at": _safe_int(row["created_at"]),
        "updated_at": _safe_int(row["updated_at"]),
    }


def get_max_fleet_slots(player_id: int, *, conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    try:
        from .research import NAVIGATION_TECH_KEY, fleet_slots_for_navigation_level

        levels = get_research_levels(user_id=int(player_id), conn=conn)
        nav_level = int(levels.get(NAVIGATION_TECH_KEY, 0) or 0)
        base = fleet_slots_for_navigation_level(nav_level)
        return base + _directive_expedition_slot_bonus(int(player_id), conn=conn)
    finally:
        if own and conn is not None:
            conn.close()


def _directive_expedition_slot_bonus(player_id: int, *, conn) -> int:
    """GC-EXPO-DIR: exploration directive may grant extra fleet slots."""
    try:
        from .galactic_directives.mechanics import get_directive_flags_for_galaxy
        from .models import get_homeworld

        hw = get_homeworld(int(player_id), conn=conn) or {}
        galaxy = int(hw.get("galaxy") or 0)
        if galaxy <= 0:
            cur = conn.cursor()
            cur.execute(
                "SELECT galaxy FROM planets WHERE player_id = ? ORDER BY id ASC LIMIT 1;",
                (int(player_id),),
            )
            row = cur.fetchone()
            galaxy = int(row["galaxy"]) if row and row["galaxy"] is not None else 0
        if galaxy <= 0:
            return 0
        flags = get_directive_flags_for_galaxy(galaxy, conn=conn) or {}
        return max(0, int(flags.get("expedition_slot_bonus") or 0))
    except Exception:
        return 0


def count_active_fleet_slots(player_id: int, *, conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return 0
        placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)
        cur = conn.cursor()
        # World Boss attacks do not consume normal fleet slots (mass-expo reserve stays usable).
        wb_exclude = ""
        if table_exists(conn, "world_boss_events"):
            wb_exclude = """
              AND NOT (
                mission_type = 'attack'
                AND EXISTS (
                  SELECT 1 FROM world_boss_events e
                  WHERE e.galaxy = fleet_movements.target_galaxy
                    AND e.system = fleet_movements.target_system
                    AND e.position = fleet_movements.target_position
                )
              )
            """
        cur.execute(
            f"""
            SELECT COUNT(*) AS c FROM fleet_movements
            WHERE player_id = ? AND status IN ({placeholders})
            {wb_exclude};
            """,
            (int(player_id), *ACTIVE_FLEET_STATUSES),
        )
        return _safe_int(cur.fetchone()["c"])
    finally:
        if own and conn is not None:
            conn.close()


def get_fleet_slot_status(player_id: int, *, conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        from .research import NAVIGATION_TECH_KEY, fleet_slots_for_navigation_level, next_navigation_fleet_slot_unlock

        active = count_active_fleet_slots(player_id, conn=conn)
        levels = get_research_levels(user_id=int(player_id), conn=conn)
        nav_level = int(levels.get(NAVIGATION_TECH_KEY, 0) or 0)
        maximum = fleet_slots_for_navigation_level(nav_level) + _directive_expedition_slot_bonus(
            int(player_id), conn=conn
        )
        status: Dict[str, Any] = {
            "active": active,
            "max": maximum,
            "free": max(0, maximum - active),
            "navigation_level": nav_level,
        }
        next_unlock = next_navigation_fleet_slot_unlock(nav_level)
        if next_unlock:
            status["next_unlock"] = next_unlock
        return status
    finally:
        if own and conn is not None:
            conn.close()


def get_planet_ships(planet_id: int, *, conn=None) -> Dict[str, int]:
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return {}
        cur = conn.cursor()
        cur.execute(
            "SELECT ship_key, amount FROM planet_ships WHERE planet_id = ? AND amount > 0;",
            (int(planet_id),),
        )
        return {str(r["ship_key"]): _safe_int(r["amount"]) for r in cur.fetchall()}
    finally:
        if own and conn is not None:
            conn.close()


def resolve_galaxy_quick_spy_ships(
    player_id: int,
    origin_planet_id: int,
    *,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """GC-977A — min(configured probes, available veil_probe) for Galaxy quick spy."""
    from .options import get_spy_probe_settings

    pid = int(player_id or 0)
    origin_id = int(origin_planet_id or 0)
    if pid <= 0 or origin_id <= 0:
        return False, "origin_not_found", None

    own = conn is None
    if own:
        conn = db()
    try:
        configured = int(get_spy_probe_settings(pid, conn=conn)["default_spy_probes"])
        available = int(get_planet_ships(origin_id, conn=conn).get("veil_probe", 0))
        sent = min(configured, available)
        meta = {
            "configured_count": configured,
            "available_count": available,
            "sent_count": sent,
            "reduced": sent < configured,
        }
        if sent <= 0:
            return False, "no_spy_probes_available", meta
        meta["ships"] = {"veil_probe": sent}
        return True, "", meta
    finally:
        if own and conn is not None:
            conn.close()


def resolve_world_boss_auto_attack_ships(
    player_id: int,
    origin_planet_id: int,
    *,
    target_galaxy: int,
    target_system: int,
    target_position: int,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """GC-WB-AUTO-ATTACK-001 — trim combat hangar to max achievable WB wave HP damage."""
    from .world_boss import (
        defender_ships_for_event,
        get_active_event_at,
        select_world_boss_auto_attack_ships,
    )

    pid = int(player_id or 0)
    origin_id = int(origin_planet_id or 0)
    if pid <= 0 or origin_id <= 0:
        return False, "origin_not_found", None

    own = conn is None
    if own:
        conn = db()
    try:
        event = get_active_event_at(
            int(target_galaxy),
            int(target_system),
            int(target_position),
            conn=conn,
        )
        if not event:
            return False, "world_boss_inactive", None

        defender_ships = defender_ships_for_event(event, conn=conn)
        hangar = get_planet_ships(origin_id, conn=conn)
        ships, meta = select_world_boss_auto_attack_ships(
            hangar,
            defender_ships=defender_ships,
            max_hp=int(event.get("max_hp") or 0),
            event_id=int(event.get("id") or 0),
            conn=conn,
        )
        meta = dict(meta or {})
        meta["event_id"] = int(event.get("id") or 0)
        if int(meta.get("sent_count") or 0) <= 0 or not ships:
            return False, "no_combat_ships_available", meta
        return True, "", meta
    finally:
        if own and conn is not None:
            conn.close()


def is_galaxy_attack_preset(preset: Mapping[str, Any] | None) -> bool:
    """GC-977B — preset eligible for Galaxy quick attack (raid/farm or explicit attack)."""
    if not preset:
        return False
    pt = str(preset.get("preset_type") or "").strip().lower()
    mt = str(preset.get("mission_type") or "").strip().lower()
    if pt in ("raid", "farm"):
        return True
    return mt == "attack"


def filter_galaxy_attack_presets(
    presets: Sequence[Mapping[str, Any]] | None,
) -> List[Dict[str, Any]]:
    """GC-977B — attack-eligible presets with at least one ship."""
    out: List[Dict[str, Any]] = []
    for preset in presets or []:
        if not is_galaxy_attack_preset(preset):
            continue
        ships = preset.get("ships") or {}
        if not isinstance(ships, dict) or not any(int(v or 0) > 0 for v in ships.values()):
            continue
        out.append(dict(preset))
    return out


def resolve_galaxy_quick_attack(
    player_id: int,
    preset_id: int,
    *,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """GC-977B — ships/speed from owned attack preset for Galaxy quick attack."""
    pid = int(player_id or 0)
    pr_id = int(preset_id or 0)
    if pid <= 0:
        return False, "not_logged_in", None
    if pr_id <= 0:
        return False, "preset_not_found", None

    own = conn is None
    if own:
        conn = db()
    try:
        preset = get_preset(pr_id, pid, conn=conn)
        if not preset:
            return False, "preset_not_found", None
        if not is_galaxy_attack_preset(preset):
            return False, "invalid_preset_type", None
        ships = normalize_ships(preset.get("ships") or {})
        if not ships:
            return False, "preset_no_ships", None
        pct = int(preset.get("speed_percent") or 100)
        if pct < 10 or pct > 100:
            pct = 100
        meta = {
            "preset_id": pr_id,
            "preset_name": str(preset.get("name") or ""),
            "preset_type": str(preset.get("preset_type") or ""),
            "ships": ships,
            "resources": {},
            "speed_percent": pct,
        }
        return True, "", meta
    finally:
        if own and conn is not None:
            conn.close()


def get_player_owned_ship_counts(player_id: int, *, conn=None) -> Dict[str, int]:
    """All hulls owned by a player: planet hangars plus active fleet movements."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return {}
        totals: Dict[str, int] = {}
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ship_key, SUM(amount) AS amt
            FROM planet_ships
            WHERE player_id = ? AND amount > 0
            GROUP BY ship_key;
            """,
            (int(player_id),),
        )
        for row in cur.fetchall():
            sk = canonical_ship_key(str(row["ship_key"]))
            if not is_known_ship_key(sk):
                continue
            totals[sk] = totals.get(sk, 0) + _safe_int(row["amt"])

        if table_exists(conn, "fleet_movements"):
            placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)
            cur.execute(
                f"""
                SELECT ships_json
                FROM fleet_movements
                WHERE player_id = ? AND status IN ({placeholders});
                """,
                (int(player_id), *ACTIVE_FLEET_STATUSES),
            )
            for row in cur.fetchall():
                ships = _json_loads(row["ships_json"], {}) or {}
                for key, amount in ships.items():
                    sk = canonical_ship_key(str(key))
                    if not is_known_ship_key(sk):
                        continue
                    qty = max(0, _safe_int(amount))
                    if qty <= 0:
                        continue
                    totals[sk] = totals.get(sk, 0) + qty
        return totals
    finally:
        if own and conn is not None:
            conn.close()


def set_planet_ships(
    planet_id: int,
    player_id: int,
    ships: Mapping[str, int],
    *,
    conn,
) -> None:
    now = _now()
    cur = conn.cursor()
    for key in all_ship_keys():
        qty = max(0, int(ships.get(key, 0) or 0))
        cur.execute(
            "SELECT id, amount FROM planet_ships WHERE planet_id = ? AND ship_key = ? LIMIT 1;",
            (int(planet_id), key),
        )
        row = cur.fetchone()
        if qty <= 0:
            if row:
                cur.execute("DELETE FROM planet_ships WHERE id = ?;", (int(row["id"]),))
            continue
        if row:
            cur.execute(
                "UPDATE planet_ships SET amount = ?, updated_at = ? WHERE id = ?;",
                (qty, now, int(row["id"])),
            )
        else:
            cur.execute(
                """
                INSERT INTO planet_ships (player_id, planet_id, ship_key, amount, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (int(player_id), int(planet_id), key, qty, now, now),
            )


def add_planet_ships(
    planet_id: int,
    player_id: int,
    ships: Mapping[str, int],
    *,
    conn,
) -> None:
    current = get_planet_ships(planet_id, conn=conn)
    merged = dict(current)
    for key, amount in ships.items():
        sk = canonical_ship_key(str(key))
        if not is_known_ship_key(sk):
            continue
        merged[sk] = max(0, int(merged.get(sk, 0)) + int(amount))
    set_planet_ships(planet_id, player_id, merged, conn=conn)


def deduct_planet_ships(
    planet_id: int,
    ships: Mapping[str, int],
    *,
    conn,
) -> Tuple[bool, str]:
    current = get_planet_ships(planet_id, conn=conn)
    for key, amount in ships.items():
        sk = str(key)
        need = int(amount)
        if need <= 0:
            continue
        have = int(current.get(sk, 0))
        if have < need:
            return False, "not_enough_ships"
    updated = dict(current)
    for key, amount in ships.items():
        sk = str(key)
        need = int(amount)
        if need <= 0:
            continue
        updated[sk] = int(updated.get(sk, 0)) - need
        if updated[sk] <= 0:
            updated.pop(sk, None)
    cur = conn.cursor()
    cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    row = cur.fetchone()
    if not row:
        return False, "planet_not_found"
    set_planet_ships(planet_id, int(row["player_id"]), updated, conn=conn)
    return True, ""


def _fleet_galactic_modifiers(
    player_id: int,
    conn,
    *,
    galaxy: int | None = None,
) -> Dict[str, float]:
    """Fleet-related EffectResolver modifiers scoped to origin galaxy (GC-720E2)."""
    try:
        from .effects.effect_resolver import EffectResolver

        research = get_research_levels(user_id=int(player_id), conn=conn)
        galaxy_id = int(galaxy) if galaxy is not None else None
        resolver = EffectResolver(
            buildings={},
            research=research,
            player_id=int(player_id),
            galaxy_id=galaxy_id,
            conn=conn,
        )
        mods = resolver.get_modifiers()
        return {
            "fleet_speed_multiplier": float(mods.get("fleet_speed_multiplier", 1.0) or 1.0),
            "fuel_efficiency_factor": float(mods.get("fuel_efficiency_factor", 1.0) or 1.0),
        }
    except Exception:
        return {
            "fleet_speed_multiplier": 1.0,
            "fuel_efficiency_factor": 1.0,
        }


def _fleet_speed_multiplier(
    player_id: int,
    conn,
    *,
    galaxy: int | None = None,
) -> float:
    return _fleet_galactic_modifiers(player_id, conn, galaxy=galaxy)["fleet_speed_multiplier"]


def admin_fleet_speed_multiplier(mission_type: str) -> float:
    """Admin balance knob: higher multiplier = shorter flight legs."""
    from .models import get_game_settings

    mission = str(mission_type or "").strip().lower()
    if mission in FLEET_SPEED_WAR_MISSIONS:
        key = "fleet_speed_war"
    elif mission in FLEET_SPEED_HOLD_MISSIONS:
        key = "fleet_speed_holding"
    else:
        key = "fleet_speed_peaceful"
    settings = get_game_settings() or {}
    try:
        return max(0.01, float(settings.get(key, 1.0) or 1.0))
    except (TypeError, ValueError):
        return 1.0


def normalize_expedition_hours(raw: Any) -> int:
    try:
        hours = int(raw or 0)
    except (TypeError, ValueError):
        hours = DEFAULT_EXPEDITION_STAY_HOURS
    if hours <= 0:
        hours = DEFAULT_EXPEDITION_STAY_HOURS
    return max(EXPEDITION_STAY_HOURS_MIN, min(EXPEDITION_STAY_HOURS_MAX, hours))


def expedition_stay_seconds(hours: int | None = None) -> int:
    return normalize_expedition_hours(hours) * EXPEDITION_STAY_HOUR_SECONDS


def _expedition_hours_from_movement(movement: Mapping[str, Any]) -> int:
    resources = movement.get("resources") or {}
    return normalize_expedition_hours(resources.get("expedition_hours"))


def _fuel_efficiency_factor_for_fleet(
    player_id: int,
    conn,
    *,
    galaxy: int | None = None,
) -> float:
    return _fleet_galactic_modifiers(player_id, conn, galaxy=galaxy)["fuel_efficiency_factor"]


def _validate_target_coords(
    mission: str,
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
) -> Tuple[bool, str]:
    try:
        if mission == "expedition":
            if position == EXPEDITION_POSITION:
                validate_coordinates(galaxy, system, 15, conn=conn)
                return True, ""
            validate_coordinates(galaxy, system, position, conn=conn)
            return True, ""
        validate_coordinates(galaxy, system, position, conn=conn)
        return True, ""
    except GalaxyCoordinateError:
        return False, "invalid_target"


def _resolve_planet_at_coords(
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
) -> Optional[int]:
    if position == EXPEDITION_POSITION:
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM planets
        WHERE galaxy = ? AND system = ? AND position = ?
        LIMIT 1;
        """,
        (int(galaxy), int(system), int(position)),
    )
    row = cur.fetchone()
    return int(row["id"]) if row else None


def are_players_allied(player_id: int, other_player_id: int, *, conn=None) -> bool:
    """Delegate to alliance module — same-alliance check for fleet targets."""
    from .alliance import are_players_allied as _allied

    return _allied(int(player_id), int(other_player_id), conn=conn)


def _hold_mission_enabled(*, conn) -> bool:
    from .db import table_exists

    return table_exists(conn, "alliance_members")


def allowed_missions_for_target_type(target_type: str, *, hold_enabled: bool) -> Set[str]:
    """Central allowed-mission set for a resolved target type."""
    allowed = set(_BASE_ALLOWED_MISSIONS.get(str(target_type or ""), set()))
    if target_type == "ally_planet" and hold_enabled:
        allowed.add("hold")
    return allowed


def merge_world_native_allowed_missions(target_info: Dict[str, Any]) -> None:
    """Merge world-native target missions into legacy target payloads (GC-590B P0)."""
    if not target_info:
        return
    wt = target_info.get("world_target") or {}
    native = str(wt.get("target_type") or "").strip()
    if not native or native not in _BASE_ALLOWED_MISSIONS:
        return
    allowed = set(_BASE_ALLOWED_MISSIONS[native])
    allowed.update(target_info.get("allowed_missions") or [])
    target_info["allowed_missions"] = sorted(allowed)


def resolve_fleet_target(
    player_id: int,
    galaxy: int,
    system: int,
    position: int,
    *,
    conn=None,
) -> Dict[str, Any]:
    """
    Resolve fleet target coordinates to type, owner, and allowed missions.

    Returns dict with keys:
      target_type, target_planet_id, target_player_id, target_owner_name,
      coords, allowed_missions, reason_if_blocked
    """
    own = conn is None
    if own:
        conn = db()
    try:
        g, s, p = int(galaxy), int(system), int(position)
        if p == EXPEDITION_POSITION:
            try:
                validate_coordinates(g, s, 15, conn=conn)
            except GalaxyCoordinateError:
                return {
                    "target_type": "expedition_slot",
                    "target_planet_id": None,
                    "target_player_id": None,
                    "target_owner_name": None,
                    "coords": format_coordinates(g, s, EXPEDITION_POSITION),
                    "allowed_missions": [],
                    "reason_if_blocked": "invalid_target",
                }
            return _target_with_debris_recycle(
                {
                    "target_type": "expedition_slot",
                    "target_planet_id": None,
                    "target_player_id": None,
                    "target_owner_name": None,
                    "coords": format_coordinates(g, s, EXPEDITION_POSITION),
                    "allowed_missions": sorted(_BASE_ALLOWED_MISSIONS["expedition_slot"]),
                    "reason_if_blocked": None,
                },
                g,
                s,
                EXPEDITION_POSITION,
                conn=conn,
            )

        try:
            validate_coordinates(g, s, p, conn=conn)
            coords = format_coordinates(g, s, p)
        except GalaxyCoordinateError:
            return {
                "target_type": "empty_slot",
                "target_planet_id": None,
                "target_player_id": None,
                "target_owner_name": None,
                "coords": f"[{g}:{s}:{p}]",
                "allowed_missions": [],
                "reason_if_blocked": "invalid_target",
            }

        planet_id = _resolve_planet_at_coords(g, s, p, conn=conn)
        if planet_id is None:
            return _maybe_world_boss_target(
                _maybe_pirate_base_target(
                    _maybe_asteroid_target(
                        _target_with_debris_recycle(
                            {
                                "target_type": "empty_slot",
                                "target_planet_id": None,
                                "target_player_id": None,
                                "target_owner_name": None,
                                "coords": coords,
                                "allowed_missions": sorted(_BASE_ALLOWED_MISSIONS["empty_slot"]),
                                "reason_if_blocked": None,
                            },
                            g,
                            s,
                            p,
                            conn=conn,
                        ),
                        g,
                        s,
                        p,
                        conn=conn,
                    ),
                    g,
                    s,
                    p,
                    conn=conn,
                ),
                g,
                s,
                p,
                conn=conn,
            )

        cur = conn.cursor()
        cur.execute(
            """
            SELECT p.id, p.player_id, pl.name AS owner_name
            FROM planets p
            INNER JOIN players pl ON pl.id = p.player_id
            WHERE p.id = ?
            LIMIT 1;
            """,
            (int(planet_id),),
        )
        row = cur.fetchone()
        if not row:
            return {
                "target_type": "empty_slot",
                "target_planet_id": None,
                "target_player_id": None,
                "target_owner_name": None,
                "coords": coords,
                "allowed_missions": [],
                "reason_if_blocked": "invalid_target",
            }

        owner_id = int(row["player_id"])
        owner_name = str(row["owner_name"] or "")
        if owner_id == int(player_id):
            target_type = "own_planet"
        elif are_players_allied(int(player_id), owner_id, conn=conn):
            target_type = "ally_planet"
        else:
            target_type = "foreign_planet"

        allowed = allowed_missions_for_target_type(
            target_type,
            hold_enabled=_hold_mission_enabled(conn=conn),
        )

        return _target_with_debris_recycle(
            {
                "target_type": target_type,
                "target_planet_id": int(planet_id),
                "target_player_id": owner_id,
                "target_owner_name": owner_name,
                "coords": coords,
                "allowed_missions": sorted(allowed),
                "reason_if_blocked": None,
            },
            g,
            s,
            p,
            conn=conn,
        )
    finally:
        if own and conn is not None:
            conn.close()


def mission_allowed_for_target(mission: str, target: Mapping[str, Any]) -> Tuple[bool, str]:
    """Check whether mission is allowed for resolved target."""
    m = str(mission or "").strip().lower()
    if m not in MISSION_TYPES:
        return False, "invalid_mission"
    target_type = str(target.get("target_type") or "")
    if target_type not in TARGET_TYPES:
        return False, "invalid_target"
    if m == "recycle":
        if str(target.get("target_type") or "") == "asteroid":
            asteroid = target.get("asteroid") or {}
            total = (
                int(asteroid.get("metal") or 0)
                + int(asteroid.get("crystal") or 0)
                + int(asteroid.get("fuel_cells") or 0)
            )
            if total <= 0:
                return False, "no_asteroid_at_target"
            return True, ""
        debris = target.get("debris") or {}
        if int(debris.get("metal") or 0) + int(debris.get("crystal") or 0) <= 0:
            return False, "no_debris_at_target"
        return True, ""
    allowed = set(target.get("allowed_missions") or [])
    if m in allowed:
        return True, ""
    block_map = _MISSION_BLOCK_REASONS.get(target_type, {})
    return False, block_map.get(m, "mission_not_allowed")


def evaluate_fleet_mission_target(
    player_id: int,
    mission: str,
    target_galaxy: int,
    target_system: int,
    target_position: int,
    *,
    conn,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Single server gate for mission + coordinates (resolve-target, preview, send).

    Returns (ok, reason_key, target_info).
    """
    m = str(mission or "").strip().lower()
    if m not in MISSION_TYPES:
        return False, "invalid_mission", {}

    g, s, p = int(target_galaxy), int(target_system), int(target_position)
    target_info = resolve_fleet_target(player_id, g, s, p, conn=conn)

    if m == "expedition" and p != EXPEDITION_POSITION:
        return False, "mission_blocked_not_expedition_slot", target_info

    if m == "colonize" and target_info.get("target_type") not in ("empty_slot", "strategic_world"):
        return False, "coordinate_occupied", target_info

    ok_mission, m_reason = mission_allowed_for_target(m, target_info)
    if not ok_mission:
        return False, m_reason, target_info

    if m in _MISSIONS_REQUIRING_PLANET and not target_info.get("target_planet_id"):
        ttype = str(target_info.get("target_type") or "")
        if ttype not in ("world_boss", "asteroid", "pirate_base"):
            return False, "invalid_target", target_info

    return True, "", target_info


def _colonize_fleet_target(
    player_id: int,
    target_galaxy: int,
    target_system: int,
    target_position: int,
    *,
    world_key: str | None,
    conn,
) -> Tuple[bool, str, Tuple[int, int, int], Dict[str, Any]]:
    """Resolve colonize target — classic empty slot (G:S:P) or optional world_key (GC-593A)."""
    from .planet_evolution.world_colonization import check_colony_limit_available

    wk = str(world_key or "").strip() or None
    if not wk:
        tg, ts, tp = int(target_galaxy), int(target_system), int(target_position)
        ok_target, t_reason, target_info = evaluate_fleet_mission_target(
            int(player_id),
            "colonize",
            tg,
            ts,
            tp,
            conn=conn,
        )
        if not ok_target:
            return False, t_reason, (tg, ts, tp), target_info
        ok_limit, limit_reason = check_colony_limit_available(int(player_id), conn=conn)
        if not ok_limit:
            return False, limit_reason, (tg, ts, tp), target_info
        return True, "", (tg, ts, tp), target_info

    from .planet_evolution.world_colonization import validate_world_colonize_target
    from .galaxy import assign_free_coordinates

    ok_w, w_reason, target_info = validate_world_colonize_target(wk, conn=conn)
    if not ok_w:
        return False, w_reason, (0, 0, 0), target_info
    parsed_type = None
    try:
        from .planet_evolution.world_colonization import parse_world_key

        parsed_type = str(parse_world_key(wk).get("world_type") or "")
    except Exception:
        parsed_type = None
    ok_limit, limit_reason = check_colony_limit_available(
        int(player_id),
        conn=conn,
        world_key=wk,
        world_type=parsed_type or None,
    )
    if not ok_limit:
        return False, limit_reason, (0, 0, 0), target_info
    g, s, p = assign_free_coordinates(conn)
    return True, "", (int(g), int(s), int(p)), target_info


def _expedition_fleet_target(
    player_id: int,
    target_galaxy: int,
    target_system: int,
    target_position: int,
    *,
    world_key: str | None,
    conn,
) -> Tuple[bool, str, Tuple[int, int, int], Dict[str, Any]]:
    """Resolve expedition target for classic slot 16 or strategic world (GC-583A)."""
    wk = str(world_key or "").strip() or None
    if wk:
        from .planet_evolution.world_colonization import (
            validate_world_expedition_target,
            validate_world_salvage_target,
        )

        ok_w, w_reason, target_info = validate_world_expedition_target(wk, conn=conn)
        if not ok_w:
            ok_s, s_reason, target_info = validate_world_salvage_target(wk, conn=conn)
            if not ok_s:
                return False, w_reason or s_reason, (0, 0, 0), target_info
        tg = int(target_galaxy)
        ts = int(target_system)
        return True, "", (tg, ts, EXPEDITION_POSITION), target_info

    ok_target, t_reason, target_info = evaluate_fleet_mission_target(
        int(player_id),
        "expedition",
        int(target_galaxy),
        int(target_system),
        int(target_position),
        conn=conn,
    )
    if not ok_target:
        return False, t_reason, (0, 0, 0), target_info
    return True, "", (int(target_galaxy), int(target_system), EXPEDITION_POSITION), target_info


def validate_fleet_send(
    *,
    player_id: int,
    origin_planet_id: int,
    target_galaxy: int,
    target_system: int,
    target_position: int,
    mission_type: str,
    ships: Mapping[str, int],
    resources: Mapping[str, Any] | None,
    speed_percent: int,
    conn,
    world_key: str | None = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Full pre-send validation including target resolution and balances preview."""
    mission = str(mission_type or "").strip().lower()
    ships_n = normalize_ships(ships)
    resources_n = calculate_loaded_resources(resources)
    pct = int(speed_percent)
    wk = str(world_key or "").strip() or None

    if mission not in MISSION_TYPES:
        return False, "invalid_mission", None

    from .fleet_mission_locks import is_fleet_mission_locked

    locked, lock_info = is_fleet_mission_locked(mission, conn=conn)
    if locked:
        return False, "mission_locked", {"mission_lock": lock_info}
    if not ships_n:
        return False, "no_ships", None
    if pct < 10 or pct > 100:
        return False, "invalid_speed_percent", None

    from .options import vacation_blocks_incoming_attack, vacation_blocks_outbound

    ok_vacation, vac_reason = vacation_blocks_outbound(int(player_id), conn=conn)
    if not ok_vacation:
        return False, vac_reason, None

    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (int(origin_planet_id), int(player_id)),
    )
    origin_row = cur.fetchone()
    if not origin_row:
        return False, "origin_not_found", None
    # Tick production so balance checks match accrued stock (logistics preview + send).
    from .resources import update_planet_resources

    origin_planet, *_rest = update_planet_resources(
        dict(origin_row),
        conn=conn,
        skip_queue_finish=True,
    )

    origin = _origin_coords(origin_planet)
    if mission == "colonize":
        ok_target, t_reason, target, target_info = _colonize_fleet_target(
            player_id,
            target_galaxy,
            target_system,
            target_position,
            world_key=wk,
            conn=conn,
        )
        if not ok_target:
            return False, t_reason, {"target": target_info}
    elif mission == "expedition" and wk:
        ok_target, t_reason, target, target_info = _expedition_fleet_target(
            player_id,
            target_galaxy,
            target_system,
            target_position,
            world_key=wk,
            conn=conn,
        )
        if not ok_target:
            return False, t_reason, {"target": target_info}
    elif origin == (int(target_galaxy), int(target_system), int(target_position)) and mission not in (
        "expedition",
        "recycle",
    ):
        return False, "same_origin_target", None
    else:
        target = (int(target_galaxy), int(target_system), int(target_position))
        if mission == "expedition":
            target = (int(target_galaxy), int(target_system), EXPEDITION_POSITION)
        ok_target, t_reason, target_info = evaluate_fleet_mission_target(
            player_id,
            mission,
            target_galaxy,
            target_system,
            target_position,
            conn=conn,
        )
        if not ok_target:
            return False, t_reason, {"target": target_info}

    if mission in ("attack", "spy") and target_info:
        target_pid = target_info.get("target_player_id")
        if target_pid and vacation_blocks_incoming_attack(int(target_pid), conn=conn):
            return False, "vacation_target_protected", {"target": target_info}

    attack_limit_info: Optional[Dict[str, Any]] = None
    noob_protection_info: Optional[Dict[str, Any]] = None
    if mission == "attack" and target_info:
        if str(target_info.get("target_type") or "") == "world_boss":
            from .world_boss import can_player_attack_boss

            wb = target_info.get("world_boss") or {}
            event_id = int(wb.get("event_id") or 0)
            if event_id <= 0:
                return False, "world_boss_inactive", {"target": target_info}
            ok_wb, wb_reason, wb_meta = can_player_attack_boss(
                int(player_id),
                event_id,
                conn=conn,
                enforce_cooldown=True,
                check_inflight=True,
            )
            if not ok_wb:
                return False, wb_reason, {"target": target_info, **(wb_meta or {})}
        elif str(target_info.get("target_type") or "") == "pirate_base":
            from .pirates.bases import can_player_attack_base

            pb = target_info.get("pirate_base") or {}
            base_id = int(pb.get("base_id") or 0)
            if base_id <= 0:
                return False, "pirate_base_inactive", {"target": target_info}
            ok_pb, pb_reason, pb_meta = can_player_attack_base(
                int(player_id),
                base_id,
                conn=conn,
                enforce_cooldown=True,
                check_inflight=True,
            )
            if not ok_pb:
                return False, pb_reason, {"target": target_info, **(pb_meta or {})}
        else:
            target_planet_id = target_info.get("target_planet_id")
            target_player_id = target_info.get("target_player_id")
            bot_fight = False
            if target_player_id:
                from .combat_balance_bots import is_bot_versus_bot_fight, is_combat_balance_bot_player

                atk_bot = is_combat_balance_bot_player(int(player_id), conn=conn)
                def_bot = is_combat_balance_bot_player(int(target_player_id), conn=conn)
                if atk_bot and not def_bot:
                    return False, "combat_bot_target_forbidden", {"target": target_info}
                if def_bot and not atk_bot:
                    return False, "combat_bot_attacker_forbidden", {"target": target_info}
                bot_fight = is_bot_versus_bot_fight(
                    int(player_id), int(target_player_id), conn=conn
                )
            if target_player_id and not bot_fight:
                ok_np, noob_protection_info = check_noob_protection(
                    int(player_id),
                    int(target_player_id),
                    conn=conn,
                )
                if not ok_np:
                    return False, "noob_protection_blocked", {
                        "target": target_info,
                        "noob_protection": noob_protection_info,
                    }
            if target_planet_id and not bot_fight:
                ok_limit, attack_limit_info = check_attack_limit(
                    int(player_id),
                    int(target_planet_id),
                    conn=conn,
                )
                if not ok_limit:
                    return False, "attack_limit_reached", {
                        "target": target_info,
                        "attack_limit": attack_limit_info,
                    }

    if mission == "expedition":
        target = (int(target_galaxy), int(target_system), EXPEDITION_POSITION)

    ok_ship_mission, ship_reason = _mission_allowed(mission, ships_n, resources_n)
    if not ok_ship_mission:
        return False, ship_reason, {"target": target_info}

    cargo = calculate_total_cargo(ships_n)
    loaded_total = loaded_resource_total(resources_n)
    if loaded_total > 0 and loaded_total > cargo:
        return False, "not_enough_cargo", {"target": target_info}

    preview = preview_fleet_flight(
        origin_planet=origin_planet,
        target_galaxy=target[0],
        target_system=target[1],
        target_position=target[2],
        ships=ships_n,
        resources=resources_n,
        speed_percent=pct,
        player_id=player_id,
        mission_type=mission,
        conn=conn,
    )
    fuel_cost = int(preview["fuel_cost"])
    metal_have = float(origin_planet.get("metal") or 0)
    crystal_have = float(origin_planet.get("crystal") or 0)
    fuel_cells_have = float(origin_planet.get("fuel_cells") or 0)

    ok_bal, bal_reason = validate_departure_balances(
        metal_have, crystal_have, fuel_cells_have, resources_n, fuel_cost
    )
    if not ok_bal:
        return False, bal_reason, {"target": target_info, "preview": preview}

    slots = get_fleet_slot_status(player_id, conn=conn)
    # World Boss attacks are event overflow: never blocked by fleet_slots_full /
    # the 3 slots mass-expedition reserves for normal ops.
    is_world_boss_attack = (
        mission == "attack"
        and str((target_info or {}).get("target_type") or "") == "world_boss"
    )
    if slots["free"] <= 0 and not is_world_boss_attack:
        return False, "fleet_slots_full", {"target": target_info, "preview": preview}

    if mission == "colonize" and int(ships_n.get("seed_ark") or 0) < 1:
        return False, "colonize_requires_ark", {"target": target_info, "preview": preview}

    out: Dict[str, Any] = {
        "target": target_info,
        "preview": preview,
        "origin_planet": origin_planet,
        "resolved_target": target,
    }
    if attack_limit_info is not None:
        out["attack_limit"] = attack_limit_info
    if noob_protection_info is not None:
        out["noob_protection"] = noob_protection_info
    return True, "", out


def build_fleet_send_preview(
    *,
    player_id: int,
    origin_planet: Dict[str, Any],
    target_galaxy: int,
    target_system: int,
    target_position: int,
    mission_type: str,
    ships: Mapping[str, int],
    resources: Mapping[str, Any] | None,
    speed_percent: int,
    conn=None,
    world_key: str | None = None,
    target_type: str | None = None,
    target_planet_id: int | None = None,
    target_world_x: float | None = None,
    target_world_y: float | None = None,
    expedition_hours: int | None = None,
) -> Dict[str, Any]:
    """Flight preview enriched with target resolution and send eligibility."""
    own = conn is None
    if own:
        conn = db()
    try:
        from .fleet_target import attach_world_target, normalize_fleet_target_request
        from .fleet_mission_locks import is_fleet_mission_locked

        mission = str(mission_type or "").strip().lower()
        ships_n = normalize_ships(ships)
        resources_n = calculate_loaded_resources(resources)
        mission_locked, mission_lock_info = is_fleet_mission_locked(mission, conn=conn)
        try:
            norm = normalize_fleet_target_request(
                int(player_id),
                mission,
                target_type=target_type,
                world_key=world_key,
                target_world_x=target_world_x,
                target_world_y=target_world_y,
                target_planet_id=target_planet_id,
                target_galaxy=int(target_galaxy),
                target_system=int(target_system),
                target_position=int(target_position),
                origin_planet=origin_planet,
                conn=conn,
            )
        except ValueError:
            return {
                "target": {},
                "mission_type": mission,
                "mission_allowed": False,
                "mission_block_reason": "invalid_target_planet",
                "can_send": False,
                "block_reason": "invalid_target_planet",
                "departure_at": None,
                "arrival_at": None,
                "countdown_at": None,
                "duration_seconds": 0,
            }
        tg, ts, tp = norm.target_galaxy, norm.target_system, norm.target_position
        wk = norm.world_key
        explicit_native = norm.world_native_type
        if mission == "colonize":
            mission_ok, mission_reason, resolved, target_info = _colonize_fleet_target(
                player_id,
                tg,
                ts,
                tp,
                world_key=wk,
                conn=conn,
            )
            if mission_ok:
                tg, ts, tp = resolved
        elif mission == "expedition" and wk:
            mission_ok, mission_reason, resolved, target_info = _expedition_fleet_target(
                player_id,
                tg,
                ts,
                tp,
                world_key=wk,
                conn=conn,
            )
            if mission_ok:
                tg, ts, tp = resolved
        else:
            target_info = resolve_fleet_target(
                player_id,
                tg,
                ts,
                tp,
                conn=conn,
            )
            mission_ok, mission_reason, _ = evaluate_fleet_mission_target(
                player_id,
                mission,
                tg,
                ts,
                tp,
                conn=conn,
            )
        if mission_locked:
            mission_ok = False
            mission_reason = "mission_locked"
        flight_tp = EXPEDITION_POSITION if mission == "expedition" else tp
        flight = preview_fleet_flight(
            origin_planet=origin_planet,
            target_galaxy=tg,
            target_system=ts,
            target_position=flight_tp,
            ships=ships_n,
            resources=resources_n,
            speed_percent=int(speed_percent),
            player_id=player_id,
            mission_type=mission,
            conn=conn,
        )
        now = _now()
        flight_seconds = int(flight.get("flight_seconds") or 0)
        expo_hours = normalize_expedition_hours(expedition_hours) if mission == "expedition" else 0
        expo_stay_seconds = expedition_stay_seconds(expo_hours) if mission == "expedition" else 0
        outbound = build_outbound_timing(departure_at=now, duration_seconds=flight_seconds)
        arrival_at = outbound["arrival_at"] if ships_n else None

        can_send = False
        block_reason = mission_reason if not mission_ok else ""
        mission_lock_payload = mission_lock_info if mission_locked else None
        attack_limit_payload: Optional[Dict[str, Any]] = None
        noob_protection_payload: Optional[Dict[str, Any]] = None
        if mission_locked:
            block_reason = "mission_locked"
        elif ships_n and mission_ok:
            ok, reason, _extra = validate_fleet_send(
                player_id=player_id,
                origin_planet_id=int(origin_planet["id"]),
                target_galaxy=tg,
                target_system=ts,
                target_position=tp,
                mission_type=mission,
                ships=ships_n,
                resources=resources_n,
                speed_percent=int(speed_percent),
                conn=conn,
                world_key=wk,
            )
            can_send = ok
            block_reason = reason or ""
            if (_extra or {}).get("mission_lock"):
                mission_lock_payload = _extra["mission_lock"]
            if (_extra or {}).get("attack_limit"):
                attack_limit_payload = _extra["attack_limit"]
            if (_extra or {}).get("noob_protection"):
                noob_protection_payload = _extra["noob_protection"]
        elif mission == "attack" and mission_ok and target_info:
            if target_info.get("target_planet_id"):
                attack_limit_payload = get_attack_limit_status(
                    int(player_id),
                    int(target_info["target_planet_id"]),
                    conn=conn,
                    now=now,
                )
            if target_info.get("target_player_id"):
                _, noob_protection_payload = check_noob_protection(
                    int(player_id),
                    int(target_info["target_player_id"]),
                    conn=conn,
                )

        if target_info:
            attach_world_target(
                target_info,
                player_id=int(player_id),
                conn=conn,
                explicit_native_type=explicit_native,
                legacy_coords={"galaxy": tg, "system": ts, "position": tp},
            )
            merge_world_native_allowed_missions(target_info)

        payload = {
            **flight,
            "target": target_info,
            "mission_type": mission,
            "mission_allowed": mission_ok,
            "mission_block_reason": mission_reason if not mission_ok else "",
            "can_send": can_send,
            "block_reason": block_reason,
            "departure_at": outbound["departure_at"] if ships_n else None,
            "arrival_at": arrival_at,
            "countdown_at": arrival_at,
            "duration_seconds": outbound["duration_seconds"] if ships_n else 0,
            "expedition_hours": expo_hours if mission == "expedition" else None,
            "expedition_stay_seconds": expo_stay_seconds if mission == "expedition" else None,
            "expedition_total_seconds": (
                (flight_seconds * 2) + expo_stay_seconds if mission == "expedition" and ships_n else None
            ),
        }
        if mission_lock_payload:
            payload["mission_lock"] = mission_lock_payload
        if attack_limit_payload:
            payload["attack_limit"] = attack_limit_payload
        if noob_protection_payload:
            payload["noob_protection"] = noob_protection_payload
        if mission == "expedition":
            payload["expedition_daily"] = expedition_daily_status(player_id, conn=conn)
            if ships_n:
                payload["expedition_rating"] = build_expedition_fleet_rating(ships_n)
        return payload
    finally:
        if own and conn is not None:
            conn.close()


def _planet_owned_by(player_id: int, planet_id: int, *, conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (int(planet_id), int(player_id)),
    )
    return cur.fetchone() is not None


def _movement_origin_snapshot(movement: Mapping[str, Any], *, conn) -> Tuple[str, str]:
    """Return ``(origin_coords, origin_planet_name)`` for combat report metadata."""
    oid = movement.get("origin_planet_id")
    if not oid:
        return "", ""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT name, galaxy, system, position
        FROM planets
        WHERE id = ?
        LIMIT 1;
        """,
        (int(oid),),
    )
    row = cur.fetchone()
    if not row:
        return "", ""
    try:
        coords = format_coordinates(
            _safe_int(row["galaxy"]),
            _safe_int(row["system"]),
            _safe_int(row["position"]),
        )
    except GalaxyCoordinateError:
        coords = ""
    return coords, str(row["name"] or "")


def _origin_coords(origin_planet: Dict[str, Any]) -> Tuple[int, int, int]:
    coords = get_planet_coordinates(origin_planet)
    return (coords["galaxy"], coords["system"], coords["position"])


def _fleet_has_role(ships: Mapping[str, int], role: str) -> bool:
    from .fleet_defs import ship_has_role

    for key, amount in ships.items():
        try:
            qty = int(amount)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        if ship_has_role(str(key), role):
            return True
    return False


def _mission_allowed(mission: str, ships: Mapping[str, int], resources: Mapping[str, Any]) -> Tuple[bool, str]:
    m = str(mission).strip().lower()
    if m not in MISSION_TYPES:
        return False, "invalid_mission"
    has_any = sum(int(v) for v in ships.values()) > 0
    if not has_any:
        return False, "no_ships"
    if m == "spy":
        if not _fleet_has_role(ships, "spy"):
            return False, "spy_requires_probe"
    if m in ("transport", "deploy", "collect"):
        if loaded_resource_total(resources) > 0 and calculate_total_cargo(ships) <= 0:
            return False, "cargo_required_for_resources"
    if m == "collect":
        if calculate_total_cargo(ships) <= 0:
            return False, "cargo_required_for_collect"
    if m == "expedition" and not _fleet_has_role(ships, "expedition"):
        if calculate_total_cargo(ships) <= 0 and not _fleet_has_role(ships, "combat"):
            pass
    if m == "colonize":
        ark = int(ships.get("seed_ark") or 0)
        if ark < 1:
            return False, "colonize_requires_ark"
        if loaded_resource_total(resources) > 0:
            return False, "colonize_no_cargo"
    if m == "recycle":
        if not _fleet_has_role(ships, "recycle"):
            return False, "recycle_requires_reclaimer"
        if calculate_total_cargo(ships) <= 0:
            return False, "cargo_required_for_recycle"
        if loaded_resource_total(resources) > 0:
            return False, "recycle_no_departure_cargo"
    return True, ""


def preview_fleet_flight(
    *,
    origin_planet: Dict[str, Any],
    target_galaxy: int,
    target_system: int,
    target_position: int,
    ships: Mapping[str, int],
    resources: Mapping[str, Any] | None,
    speed_percent: int,
    player_id: int,
    mission_type: str = "transport",
    conn=None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        origin = _origin_coords(origin_planet)
        target = (int(target_galaxy), int(target_system), int(target_position))
        distance = calculate_distance(origin, target)
        origin_galaxy = int(origin_planet.get("galaxy") or origin[0] or 0) or None
        speed_mult = _fleet_speed_multiplier(player_id, conn, galaxy=origin_galaxy)
        fleet_speed = calculate_fleet_speed(ships, speed_multiplier=speed_mult)
        admin_speed = admin_fleet_speed_multiplier(mission_type)
        flight_seconds = calculate_flight_seconds(
            distance,
            fleet_speed,
            speed_percent,
            admin_speed_multiplier=admin_speed,
        )
        fuel_eff_factor = _fuel_efficiency_factor_for_fleet(
            player_id, conn, galaxy=origin_galaxy
        )
        fuel_cost = calculate_fuel_cost(
            ships,
            distance,
            speed_percent,
            fuel_efficiency_factor_override=fuel_eff_factor,
        )
        mission = str(mission_type or "").strip().lower()
        cargo_total = (
            calculate_expedition_loot_cap(ships)
            if mission == "expedition"
            else calculate_total_cargo(ships)
        )
        fuel_cells_have = float(origin_planet.get("fuel_cells") or 0)
        return build_flight_preview_payload(
            distance=distance,
            fleet_speed=fleet_speed,
            flight_seconds=flight_seconds,
            fuel_cost=fuel_cost,
            cargo_total=cargo_total,
            resources=resources,
            fuel_cells_have=fuel_cells_have,
        )
    finally:
        if own and conn is not None:
            conn.close()


def mission_safe_expedition(target: Tuple[int, int, int]) -> bool:
    return int(target[2]) == EXPEDITION_POSITION


def build_expedition_slot(galaxy: int, system: int) -> Dict[str, Any]:
    """Synthetic galaxy slot for expedition position 16."""
    g, s = int(galaxy), int(system)
    coords = format_coordinates(g, s, EXPEDITION_POSITION)
    return {
        "position": EXPEDITION_POSITION,
        "occupied": False,
        "is_expedition_slot": True,
        "player_id": None,
        "commander_name": None,
        "planet_id": None,
        "planet_name": None,
        "coordinates": {
            "galaxy": g,
            "system": s,
            "position": EXPEDITION_POSITION,
        },
        "coordinates_formatted": coords,
        "planet_class": None,
        "planet_class_label_key": None,
        "temperature_display": None,
        "planet_score": None,
        "is_own_planet": False,
        "is_ally_planet": False,
        "is_active_planet": False,
        "is_highlighted": False,
        "colony_target": False,
    }


def _enrich_movement_world_target(
    mv: Dict[str, Any],
    player_id: int,
    *,
    conn,
) -> Dict[str, Any]:
    """Attach world_target for fleet UI named destinations (GC-590B)."""
    from .fleet_target import attach_world_target, _load_planet_row

    tg = int(mv.get("target_galaxy") or 0)
    ts = int(mv.get("target_system") or 0)
    tp = int(mv.get("target_position") or 0)
    target_info = resolve_fleet_target(int(player_id), tg, ts, tp, conn=conn)
    if mv.get("target_planet_id"):
        target_info["target_planet_id"] = mv["target_planet_id"]

    resources = mv.get("resources") or {}
    wk = str(resources.get("world_key") or "").strip() or None
    if wk:
        target_info["world_key"] = wk
        try:
            from .planet_evolution.strategic_worlds import build_strategic_world_presentation_from_key

            target_info["strategic_world"] = build_strategic_world_presentation_from_key(wk)
        except Exception:
            pass
    elif target_info.get("target_planet_id"):
        row = _load_planet_row(int(target_info["target_planet_id"]), conn=conn)
        if row:
            if row.get("world_key"):
                target_info["world_key"] = str(row["world_key"])
            if row.get("planet_role"):
                target_info["planet_role"] = str(row["planet_role"])
            if row.get("name"):
                target_info["target_owner_name"] = str(row["name"])

    attach_world_target(
        target_info,
        player_id=int(player_id),
        conn=conn,
        legacy_coords={"galaxy": tg, "system": ts, "position": tp},
    )
    wt = target_info.get("world_target")
    if wt:
        mv["world_target"] = wt
    return mv


def list_active_movements(player_id: int, *, conn=None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return []
        placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT fm.*, op.name AS origin_name, op.galaxy AS og, op.system AS os, op.position AS opos
            FROM fleet_movements fm
            JOIN planets op ON op.id = fm.origin_planet_id
            WHERE fm.player_id = ? AND fm.status IN ({placeholders})
            ORDER BY fm.arrival_at ASC;
            """,
            (int(player_id), *ACTIVE_FLEET_STATUSES),
        )
        out: List[Dict[str, Any]] = []
        for row in cur.fetchall():
            mv = _row_to_movement(row)
            mv["origin_name"] = str(row["origin_name"] or "")
            try:
                mv["origin_coords"] = format_coordinates(
                    _safe_int(row["og"]), _safe_int(row["os"]), _safe_int(row["opos"])
                )
            except GalaxyCoordinateError:
                mv["origin_coords"] = ""
            mv = enrich_movement_timing(mv, now=_now())
            out.append(_enrich_movement_world_target(mv, int(player_id), conn=conn))
        return out
    finally:
        if own and conn is not None:
            conn.close()


def list_admin_fleet_movements(
    *,
    player_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    conn,
) -> List[Dict[str, Any]]:
    """Non-completed fleet movements for admin panel (GC-621G)."""
    if not fleet_schema_ready(conn):
        return []
    lim = max(1, min(int(limit or 100), 200))
    status_filter = str(status or "all").strip().lower()
    clauses = ["fm.status IN (" + ",".join("?" for _ in ACTIVE_FLEET_STATUSES) + ")"]
    params: List[Any] = list(ACTIVE_FLEET_STATUSES)
    if player_id is not None:
        clauses.append("fm.player_id = ?")
        params.append(int(player_id))
    if status_filter and status_filter not in ("all", ""):
        clauses = ["fm.status = ?"]
        params = [status_filter]
        if player_id is not None:
            clauses.append("fm.player_id = ?")
            params.append(int(player_id))
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT fm.*, pl.name AS player_name, op.name AS origin_name
        FROM fleet_movements fm
        JOIN players pl ON pl.id = fm.player_id
        JOIN planets op ON op.id = fm.origin_planet_id
        WHERE {' AND '.join(clauses)}
        ORDER BY fm.updated_at DESC, fm.id DESC
        LIMIT ?;
        """,
        (*params, lim),
    )
    now = _now()
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        mv = _row_to_movement(row)
        mv["player_name"] = str(row["player_name"] or "")
        mv["origin_name"] = str(row["origin_name"] or "")
        mv = enrich_movement_timing(mv, now=now)
        loaded = _movement_loaded_resources(mv)
        out.append(
            {
                "id": int(mv["id"]),
                "player_id": int(mv["player_id"]),
                "player_name": mv["player_name"],
                "mission_type": str(mv.get("mission_type") or ""),
                "status": str(mv.get("status") or ""),
                "target_coords": str(mv.get("target_coords") or ""),
                "origin_planet_id": int(mv.get("origin_planet_id") or 0),
                "origin_name": mv["origin_name"],
                "ship_count": _movement_ship_count(mv),
                "remaining_seconds": int(mv.get("remaining_seconds") or 0),
                "resources": loaded,
                "arrival_at": mv.get("arrival_at"),
                "holding_until": mv.get("holding_until"),
                "return_at": mv.get("return_at"),
            }
        )
    return out


def admin_advance_fleet_movement(
    movement_id: int,
    *,
    conn,
    now: float | None = None,
    complete: bool = False,
) -> Dict[str, Any]:
    """Force-advance one fleet movement via due timestamps + process_fleet_tick (GC-621G)."""
    if not fleet_schema_ready(conn):
        return {"ok": False, "error": "fleet_unavailable"}

    mid = int(movement_id)
    ts = float(now if now is not None else _now())
    max_steps = 8 if complete else 1
    steps = 0
    tick_snapshots: List[Dict[str, Any]] = []
    status_before = ""

    cur = conn.cursor()
    cur.execute("SELECT status FROM fleet_movements WHERE id = ? LIMIT 1;", (mid,))
    first = cur.fetchone()
    if not first:
        return {"ok": False, "error": "not_found", "movement_id": mid}
    status_before = str(first["status"] or "")

    for _ in range(max_steps):
        cur.execute("SELECT * FROM fleet_movements WHERE id = ? LIMIT 1;", (mid,))
        row = cur.fetchone()
        if not row:
            break
        status = str(row["status"] or "")
        if status in ("completed", "failed"):
            break

        player_id = int(row["player_id"])
        if status == "outbound":
            cur.execute(
                "UPDATE fleet_movements SET arrival_at = ? WHERE id = ? AND status = 'outbound';",
                (ts - 1, mid),
            )
        elif status == "holding":
            cur.execute(
                "UPDATE fleet_movements SET holding_until = ? WHERE id = ? AND status = 'holding';",
                (ts - 1, mid),
            )
        elif status == "returning":
            cur.execute(
                "UPDATE fleet_movements SET return_at = ? WHERE id = ? AND status = 'returning';",
                (ts - 1, mid),
            )
        else:
            return {
                "ok": False,
                "error": "unsupported_status",
                "status": status,
                "movement_id": mid,
            }

        tick_result = process_fleet_tick(player_id=player_id, now=ts, conn=conn)
        tick_snapshots.append(dict(tick_result))
        steps += 1

        if not complete:
            break

    cur.execute("SELECT status FROM fleet_movements WHERE id = ? LIMIT 1;", (mid,))
    final_row = cur.fetchone()
    status_after = str(final_row["status"] if final_row else "")

    return {
        "ok": True,
        "movement_id": mid,
        "status_before": status_before,
        "status_after": status_after,
        "steps": steps,
        "complete": bool(complete),
        "tick": tick_snapshots[-1] if tick_snapshots else {},
    }


FLEET_DRAWER_VISIBLE_LIMIT = 1


def _movement_ship_count(movement: Mapping[str, Any]) -> int:
    return sum(max(0, int(v or 0)) for v in (movement.get("ships") or {}).values())


def _movement_ships_breakdown(movement: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key, qty in sorted((movement.get("ships") or {}).items(), key=lambda kv: str(kv[0])):
        count = max(0, int(qty or 0))
        if count <= 0:
            continue
        ship_key = str(key)
        out.append(
            {
                "key": ship_key,
                "label_key": f"fleet_ship_{ship_key}",
                "count": count,
            }
        )
    return out


def _movement_loaded_resources(movement: Mapping[str, Any]) -> Dict[str, int]:
    res = movement.get("resources") or {}
    return {
        "metal": max(0, int(res.get("metal") or 0)),
        "crystal": max(0, int(res.get("crystal") or 0)),
        "fuel_cells": max(0, int(res.get("fuel_cells") or 0)),
    }


def _movement_progress_pct(movement: Mapping[str, Any]) -> int:
    """Display-only leg progress for drawer flight animation (GC-654B)."""
    status = str(movement.get("status") or "").strip().lower()
    if status == "holding":
        return 50
    remaining = max(0, int(movement.get("remaining_seconds") or 0))
    total = max(1, int(movement.get("duration_seconds") or movement.get("flight_seconds") or 0))
    elapsed = max(0, total - remaining)
    return max(0, min(100, int(round(elapsed * 100 / total))))


def _movement_target_display_name(movement: Mapping[str, Any]) -> str:
    wt = movement.get("world_target") or {}
    if wt.get("target_name"):
        return str(wt["target_name"])
    name_key = str(wt.get("target_name_key") or "").strip()
    if name_key:
        from .i18n import tr

        return tr(name_key, name_key)
    return str(movement.get("target_coords") or "")


def format_movement_drawer_item(movement: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact fleet drawer row for /api/game-state active_fleets.items (GC-654)."""
    mv = dict(movement)
    status = str(mv.get("status") or "").strip().lower()
    mission = str(mv.get("mission_type") or "transport").strip().lower()
    can_recall = status in ("outbound", "holding")
    can_cancel = status == "outbound"
    if status == "outbound":
        action_label_key = "fleet_drawer_action_cancel"
    elif status == "holding":
        action_label_key = "fleet_drawer_action_recall"
    else:
        action_label_key = ""
    cancel_reason = ""
    if status == "returning":
        cancel_reason = "fleet_recall_not_allowed"
    item = {
        **mv,
        "movement_id": int(mv.get("id") or 0),
        "mission": mission,
        "mission_label_key": f"fleet_mission_{mission}",
        "status": status,
        "status_label": str(mv.get("status_label") or mv.get("leg_label_key") or ""),
        "origin_name": str(mv.get("origin_name") or ""),
        "origin_coords": str(mv.get("origin_coords") or ""),
        "target_name": _movement_target_display_name(mv),
        "target_coords": str(mv.get("target_coords") or ""),
        "ship_count": _movement_ship_count(mv),
        "ships_breakdown": _movement_ships_breakdown(mv),
        "loaded_resources": _movement_loaded_resources(mv),
        "total_seconds": max(0, int(mv.get("duration_seconds") or mv.get("flight_seconds") or 0)),
        "progress_pct": _movement_progress_pct(mv),
        "remaining_seconds": max(0, int(mv.get("remaining_seconds") or 0)),
        "countdown_at": mv.get("countdown_at"),
        "holding_until": mv.get("holding_until"),
        "home_at": mv.get("home_at"),
        "arrival_at": mv.get("arrival_at"),
        "return_at": mv.get("return_at"),
        "can_recall": can_recall,
        "can_cancel": can_cancel,
        "action_label_key": action_label_key,
        "cancel_reason": cancel_reason,
    }
    return item


def build_active_fleets_payload(
    player_id: int,
    *,
    conn=None,
    visible_limit: int = FLEET_DRAWER_VISIBLE_LIMIT,
) -> Dict[str, Any]:
    """Player-wide active fleet block for global drawer (GC-654)."""
    movements = list_active_movements(int(player_id), conn=conn)
    items = [format_movement_drawer_item(mv) for mv in movements]
    next_remaining = 0
    if items:
        next_remaining = min(int(i.get("remaining_seconds") or 0) for i in items)
    count = len(items)
    return {
        "count": count,
        "active_fleet_count": count,
        "fleets_confirmed_empty": count == 0,
        "visible_limit": max(1, int(visible_limit)),
        "next_remaining_seconds": next_remaining,
        "items": items,
    }


ATTACK_LIMIT_MAX_PER_TARGET = 5
ATTACK_LIMIT_WINDOW_SEC = 24 * 60 * 60
ATTACK_LIMIT_COUNT_STATUSES = ("outbound", "returning", "completed", "holding")

# Fair-attack / noob protection — attacks only when both scores within this factor (GC-XXX).
NOOB_PROTECTION_FACTOR = 5


def _player_score_total(player_id: int, *, conn) -> int:
    from .ranking import get_player_score_row

    row = get_player_score_row(int(player_id), conn=conn)
    if not row:
        return 0
    return max(0, int(row.get("score_total") or 0))


def get_noob_protection_status(
    attacker_player_id: int,
    defender_player_id: int,
    *,
    conn,
    factor: int | None = None,
) -> Dict[str, Any]:
    """Score-gap gate for attack missions — symmetric factor on ``score_total``."""
    fac = max(1, int(factor if factor is not None else NOOB_PROTECTION_FACTOR))
    atk_id = int(attacker_player_id)
    def_id = int(defender_player_id)
    empty = {
        "factor": fac,
        "attacker_score": 0,
        "defender_score": 0,
        "min_defender_score": 0,
        "max_defender_score": 0,
        "allowed": True,
    }
    if atk_id <= 0 or def_id <= 0 or atk_id == def_id:
        return dict(empty)

    from .ranking import is_player_id_inactive

    atk_score = _player_score_total(atk_id, conn=conn)
    def_score = _player_score_total(def_id, conn=conn)
    min_def = int(math.ceil(atk_score / fac)) if atk_score > 0 else 0
    max_def = int(atk_score * fac)
    defender_inactive = is_player_id_inactive(def_id, conn=conn)
    allowed = defender_inactive or (min_def <= def_score <= max_def)
    return {
        "factor": fac,
        "attacker_score": atk_score,
        "defender_score": def_score,
        "min_defender_score": min_def,
        "max_defender_score": max_def,
        "defender_inactive": defender_inactive,
        "allowed": allowed,
    }


def check_noob_protection(
    attacker_player_id: int,
    defender_player_id: int,
    *,
    conn,
) -> Tuple[bool, Dict[str, Any]]:
    info = get_noob_protection_status(
        int(attacker_player_id),
        int(defender_player_id),
        conn=conn,
    )
    return bool(info.get("allowed")), info


def get_attack_limit_status(
    attacker_player_id: int,
    target_planet_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Rolling 24h attack count per attacker account + target planet (GC-FLEET-ATTACK-LIMIT).

    Counts by ``player_id`` + ``target_planet_id`` only — ``origin_planet_id`` is ignored
    so colony hopping cannot bypass the limit.
    """
    max_attacks = ATTACK_LIMIT_MAX_PER_TARGET
    pid = int(attacker_player_id)
    tid = int(target_planet_id)
    empty = {
        "max": max_attacks,
        "used": 0,
        "remaining": max_attacks,
        "resets_at": None,
    }
    if pid <= 0 or tid <= 0 or not fleet_schema_ready(conn):
        return dict(empty)

    ts = float(now if now is not None else _now())
    window_start = ts - float(ATTACK_LIMIT_WINDOW_SEC)
    placeholders = ",".join("?" for _ in ATTACK_LIMIT_COUNT_STATUSES)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT COUNT(*) AS used, MIN(created_at) AS oldest_created
        FROM fleet_movements
        WHERE player_id = ?
          AND target_planet_id = ?
          AND mission_type = 'attack'
          AND created_at >= ?
          AND status IN ({placeholders});
        """,
        (pid, tid, window_start, *ATTACK_LIMIT_COUNT_STATUSES),
    )
    row = cur.fetchone()
    used = int(row["used"] or 0) if row else 0
    remaining = max(0, max_attacks - used)
    resets_at: Optional[int] = None
    if used >= max_attacks and row and row["oldest_created"] is not None:
        try:
            resets_at = int(float(row["oldest_created"]) + ATTACK_LIMIT_WINDOW_SEC)
        except (TypeError, ValueError):
            resets_at = None
    return {
        "max": max_attacks,
        "used": used,
        "remaining": remaining,
        "resets_at": resets_at,
    }


def check_attack_limit(
    attacker_player_id: int,
    target_planet_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, Dict[str, Any]]:
    info = get_attack_limit_status(
        int(attacker_player_id),
        int(target_planet_id),
        conn=conn,
        now=now,
    )
    return info["remaining"] > 0, info


def build_fleet_incoming_attack_alerts(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Inbound enemy attack slice for /api/game-state fleet_alerts (GC-FLEET-ALERT)."""
    empty: Dict[str, Any] = {
        "incoming_attack_count": 0,
        "next_attack_arrival": None,
        "has_incoming_attack": False,
        "alert_key": "",
        "incoming_attacks": [],
    }
    if not fleet_schema_ready(conn):
        return dict(empty)

    pid = int(player_id)
    if pid <= 0:
        return dict(empty)

    ts = float(now if now is not None else _now())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT fm.id AS movement_id,
               fm.player_id AS attacker_id,
               fm.target_planet_id,
               fm.arrival_at
        FROM fleet_movements fm
        INNER JOIN planets tp ON tp.id = fm.target_planet_id
        WHERE tp.player_id = ?
          AND fm.player_id != ?
          AND fm.mission_type = 'attack'
          AND fm.status = 'outbound'
          AND fm.arrival_at > ?
        ORDER BY fm.arrival_at ASC, fm.id ASC;
        """,
        (pid, pid, ts),
    )
    rows = cur.fetchall()
    if not rows:
        return dict(empty)

    count = len(rows)
    if count <= 0:
        return dict(empty)

    movement_ids = sorted(int(row["movement_id"]) for row in rows)
    alert_key = "m:" + ",".join(str(mid) for mid in movement_ids)

    next_attack_arrival: Optional[int] = None
    try:
        next_attack_arrival = int(float(rows[0]["arrival_at"]))
    except (TypeError, ValueError):
        next_attack_arrival = None

    incoming_attacks: List[Dict[str, Any]] = []
    for row in rows:
        try:
            arrival_at = int(float(row["arrival_at"]))
        except (TypeError, ValueError):
            arrival_at = None
        incoming_attacks.append(
            {
                "movement_id": int(row["movement_id"]),
                "attacker_id": int(row["attacker_id"]),
                "target_planet_id": int(row["target_planet_id"]),
                "arrival_at": arrival_at,
            }
        )

    return {
        "incoming_attack_count": count,
        "next_attack_arrival": next_attack_arrival,
        "has_incoming_attack": True,
        "alert_key": alert_key,
        "incoming_attacks": incoming_attacks,
    }


def recall_fleet_movement(
    player_id: int,
    movement_id: int,
    *,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Recall or cancel an active fleet movement (outbound/holding → returning)."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None
        uid = int(player_id)
        mid = int(movement_id)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM fleet_movements WHERE id = ? AND player_id = ? LIMIT 1;",
            (mid, uid),
        )
        row = cur.fetchone()
        if not row:
            return False, "fleet_not_found", None
        mv = _row_to_movement(row)
        status = str(mv.get("status") or "").strip().lower()
        if status not in ("outbound", "holding"):
            return False, "fleet_recall_not_allowed", None
        outbound_recall = status == "outbound"
        # Claim return before fleet tick — otherwise overdue arrivals (transport/spy/…)
        # auto-transition to returning/completed and recall appears to do nothing.
        if _start_return(mv, conn=conn, now=now, outbound_recall=outbound_recall):
            return True, "fleet_recall_ok", {"movement_id": mid, "status": "returning"}
        process_fleet_tick(player_id=uid, conn=conn)
        cur.execute(
            "SELECT * FROM fleet_movements WHERE id = ? AND player_id = ? LIMIT 1;",
            (mid, uid),
        )
        row = cur.fetchone()
        if not row:
            return False, "fleet_not_found", None
        mv = _row_to_movement(row)
        status = str(mv.get("status") or "").strip().lower()
        if status == "returning":
            return True, "fleet_recall_ok", {"movement_id": mid, "status": "returning"}
        if status not in ("outbound", "holding"):
            return False, "fleet_recall_not_allowed", None
        outbound_recall = status == "outbound"
        if not _start_return(mv, conn=conn, now=now, outbound_recall=outbound_recall):
            return False, "fleet_recall_failed", None
        return True, "fleet_recall_ok", {"movement_id": mid, "status": "returning"}
    finally:
        if own and conn is not None:
            conn.close()


def list_presets(player_id: int, *, conn=None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM fleet_presets WHERE player_id = ? ORDER BY updated_at DESC;",
            (int(player_id),),
        )
        return [_row_to_preset(r) for r in cur.fetchall()]
    finally:
        if own and conn is not None:
            conn.close()


def get_preset(preset_id: int, player_id: int, *, conn=None) -> Optional[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM fleet_presets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(preset_id), int(player_id)),
        )
        row = cur.fetchone()
        return _row_to_preset(row) if row else None
    finally:
        if own and conn is not None:
            conn.close()


def create_preset(
    player_id: int,
    *,
    name: str,
    preset_type: str,
    ships_json: Mapping[str, Any],
    resources_json: Mapping[str, Any] | None = None,
    speed_percent: int = 100,
    mission_type: str | None = None,
    target_galaxy: int | None = None,
    target_system: int | None = None,
    target_position: int | None = None,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    name_n = str(name or "").strip()
    if not name_n:
        return False, "preset_name_required", None
    pt = str(preset_type or "").strip().lower()
    if pt not in PRESET_TYPES:
        return False, "invalid_preset_type", None
    ships = normalize_ships(ships_json)
    for key in (ships_json or {}):
        if not is_known_ship_key(str(key)):
            return False, "unknown_ship", None
    if not ships and any(int(v or 0) > 0 for v in (ships_json or {}).values()):
        return False, "unknown_ship", None
    pct = int(speed_percent)
    if pct < 10 or pct > 100:
        return False, "invalid_speed_percent", None
    if mission_type and str(mission_type) not in MISSION_TYPES:
        return False, "invalid_mission", None

    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None
        now = _now()
        if own:
            begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO fleet_presets (
                player_id, name, preset_type, ships_json, resources_json,
                speed_percent, mission_type, target_galaxy, target_system, target_position,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(player_id),
                name_n[:64],
                pt,
                _json_dumps(ships),
                _json_dumps(resources_json if resources_json is not None else {}),
                pct,
                mission_type,
                target_galaxy,
                target_system,
                target_position,
                now,
                now,
            ),
        )
        preset_id = int(cur.lastrowid)
        if own:
            commit(conn)
        preset = get_preset(preset_id, player_id, conn=conn)
        return True, "", preset
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def update_preset(
    preset_id: int,
    player_id: int,
    fields: Mapping[str, Any],
    *,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        existing = get_preset(preset_id, player_id, conn=conn)
        if not existing:
            return False, "preset_not_found", None

        updates: Dict[str, Any] = {}
        if "name" in fields:
            name_n = str(fields["name"] or "").strip()
            if not name_n:
                return False, "preset_name_required", None
            updates["name"] = name_n[:64]
        if "preset_type" in fields:
            pt = str(fields["preset_type"]).strip().lower()
            if pt not in PRESET_TYPES:
                return False, "invalid_preset_type", None
            updates["preset_type"] = pt
        if "ships_json" in fields:
            for key in fields["ships_json"] or {}:
                if not is_known_ship_key(str(key)):
                    return False, "unknown_ship", None
            ships = normalize_ships(fields["ships_json"])
            updates["ships_json"] = _json_dumps(ships)
        if "resources_json" in fields:
            updates["resources_json"] = _json_dumps(
                fields["resources_json"] if fields["resources_json"] is not None else {}
            )
        if "speed_percent" in fields:
            pct = int(fields["speed_percent"])
            if pct < 10 or pct > 100:
                return False, "invalid_speed_percent", None
            updates["speed_percent"] = pct
        if "mission_type" in fields:
            mt = fields["mission_type"]
            if mt and str(mt) not in MISSION_TYPES:
                return False, "invalid_mission", None
            updates["mission_type"] = mt
        for coord_key in ("target_galaxy", "target_system", "target_position"):
            if coord_key in fields:
                updates[coord_key] = fields[coord_key]

        if not updates:
            return True, "", existing

        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [int(preset_id), int(player_id)]

        if own:
            begin_write_transaction(conn)
        conn.execute(
            f"UPDATE fleet_presets SET {set_clause} WHERE id = ? AND player_id = ?;",
            vals,
        )
        if own:
            commit(conn)
        return True, "", get_preset(preset_id, player_id, conn=conn)
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def delete_preset(preset_id: int, player_id: int, *, conn=None) -> Tuple[bool, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        if own:
            begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM fleet_presets WHERE id = ? AND player_id = ?;",
            (int(preset_id), int(player_id)),
        )
        deleted = cur.rowcount > 0
        if own:
            commit(conn)
        return (True, "") if deleted else (False, "preset_not_found")
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def send_fleet(
    *,
    player_id: int,
    origin_planet_id: int,
    target_galaxy: int,
    target_system: int,
    target_position: int,
    mission_type: str,
    ships: Mapping[str, int],
    resources: Mapping[str, Any] | None = None,
    speed_percent: int = 100,
    preset_id: int | None = None,
    batch_id: int | None = None,
    colony_name: str | None = None,
    world_key: str | None = None,
    target_type: str | None = None,
    target_planet_id: int | None = None,
    target_world_x: float | None = None,
    target_world_y: float | None = None,
    expedition_hours: int | None = None,
    departure_at: int | None = None,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    mission = str(mission_type or "").strip().lower()
    if mission not in MISSION_TYPES:
        return False, "invalid_mission", None

    from .fleet_mission_locks import is_fleet_mission_locked

    locked, lock_info = is_fleet_mission_locked(mission, conn=conn)
    if locked:
        return False, "mission_locked", None

    for key in ships:
        if not is_known_ship_key(str(key)):
            return False, "unknown_ship", None
    ships_n = normalize_ships(ships)
    resources_n = calculate_loaded_resources(resources)
    pct = int(speed_percent)
    if not ships_n:
        return False, "no_ships", None
    if pct < 10 or pct > 100:
        return False, "invalid_speed_percent", None

    own = conn is None
    if own:
        conn = db()
    try:
        from .fleet_target import normalize_fleet_target_request

        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None

        if own:
            begin_write_transaction(conn)

        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(origin_planet_id), int(player_id)),
        )
        origin_row = cur.fetchone()
        if not origin_row:
            if own:
                rollback(conn)
            return False, "origin_not_found", None
        origin_planet = dict(origin_row)
        lock_planet_for_update(conn, int(origin_planet_id))
        raw_wk = str(world_key or "").strip() or None
        if mission == "expedition" and not raw_wk and int(target_position) != EXPEDITION_POSITION:
            if own:
                rollback(conn)
            return False, "mission_blocked_not_expedition_slot", None
        try:
            norm = normalize_fleet_target_request(
                int(player_id),
                mission,
                target_type=target_type,
                world_key=world_key,
                target_world_x=target_world_x,
                target_world_y=target_world_y,
                target_planet_id=target_planet_id,
                target_galaxy=int(target_galaxy),
                target_system=int(target_system),
                target_position=int(target_position),
                origin_planet=origin_planet,
                conn=conn,
            )
        except ValueError:
            if own:
                rollback(conn)
            return False, "invalid_target_planet", None
        wk = norm.world_key
        target_galaxy = norm.target_galaxy
        target_system = norm.target_system
        target_position = norm.target_position

        if not (mission == "colonize" and wk) and not (mission == "expedition" and wk):
            ok_coords, reason = _validate_target_coords(
                mission, target_galaxy, target_system, target_position, conn=conn
            )
            if not ok_coords:
                if own:
                    rollback(conn)
                return False, reason, None

        if mission == "expedition" and int(target_position) != EXPEDITION_POSITION and not wk:
            if own:
                rollback(conn)
            return False, "mission_blocked_not_expedition_slot", None

        target = (int(target_galaxy), int(target_system), int(target_position))
        if mission == "expedition":
            target = (int(target_galaxy), int(target_system), EXPEDITION_POSITION)
            target_position = EXPEDITION_POSITION

        ok_send, send_reason, send_ctx = validate_fleet_send(
            player_id=player_id,
            origin_planet_id=int(origin_planet_id),
            target_galaxy=target[0],
            target_system=target[1],
            target_position=int(target_position),
            mission_type=mission,
            ships=ships_n,
            resources=resources_n,
            speed_percent=pct,
            conn=conn,
            world_key=wk,
        )
        if not ok_send:
            if own:
                rollback(conn)
            extra = send_ctx if isinstance(send_ctx, dict) else None
            return False, send_reason, extra

        origin_planet = send_ctx["origin_planet"]
        preview = send_ctx["preview"]
        target_info = send_ctx["target"]
        target_planet_id = target_info.get("target_planet_id")
        resolved_target = send_ctx.get("resolved_target")
        if resolved_target:
            target = tuple(resolved_target)
            target_position = int(target[2])

        ok_deduct, d_reason = deduct_planet_ships(int(origin_planet_id), ships_n, conn=conn)
        if not ok_deduct:
            if own:
                rollback(conn)
            return False, d_reason, None

        metal_have = float(origin_planet.get("metal") or 0)
        crystal_have = float(origin_planet.get("crystal") or 0)
        fuel_cells_have = float(origin_planet.get("fuel_cells") or 0)
        fuel_cost = int(preview["fuel_cost"])
        new_metal, new_crystal, new_fuel_cells = apply_departure_deduction(
            metal_have, crystal_have, fuel_cells_have, resources_n, fuel_cost
        )
        if new_metal < 0 or new_crystal < 0 or new_fuel_cells < 0:
            if own:
                rollback(conn)
            return False, "not_enough_resources", None

        cur.execute(
            "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
            (new_metal, new_crystal, new_fuel_cells, int(origin_planet_id)),
        )

        resources_store = dict(resources_n)
        if mission == "colonize":
            name = str(colony_name or "").strip()
            if not name:
                cur.execute(
                    "SELECT name FROM planets WHERE id = ? LIMIT 1;",
                    (int(origin_planet_id),),
                )
                orow = cur.fetchone()
                base = str(orow["name"] if orow else "Colony")
                name = f"{base} Outpost"
            resources_store["colony_name"] = name[:64]
            if wk:
                resources_store["world_key"] = wk
        if mission == "expedition" and wk:
            resources_store["world_key"] = wk
        if mission == "expedition":
            resources_store["expedition_hours"] = normalize_expedition_hours(expedition_hours)
        if (
            mission == "recycle"
            and str(target_info.get("target_type") or "") == "asteroid"
        ):
            ast = target_info.get("asteroid") or {}
            aid = int(ast.get("id") or 0)
            if aid > 0:
                resources_store["asteroid_id"] = aid
                resources_store["asteroid_key"] = str(ast.get("asteroid_key") or "")
                try:
                    from .asteroids import record_asteroid_engagement

                    record_asteroid_engagement(int(player_id), aid, conn=conn)
                except Exception:
                    logger.exception(
                        "asteroid engagement record failed player=%s asteroid=%s",
                        player_id,
                        aid,
                    )

        now = _now()
        flight_seconds = int(preview["flight_seconds"])
        dep_ts = int(departure_at if departure_at is not None else now)
        outbound = build_outbound_timing(departure_at=dep_ts, duration_seconds=flight_seconds)
        arrival_at = outbound["arrival_at"]

        cur.execute(
            """
            INSERT INTO fleet_movements (
                player_id, origin_planet_id, target_planet_id,
                target_galaxy, target_system, target_position,
                mission_type, status, departure_at, arrival_at, return_at, holding_until,
                ships_json, resources_json, fuel_cost, speed_percent, distance, flight_seconds,
                preset_id, parent_batch_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'outbound', ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(player_id),
                int(origin_planet_id),
                target_planet_id,
                target[0],
                target[1],
                target[2],
                mission,
                outbound["departure_at"],
                arrival_at,
                _json_dumps(ships_n),
                _json_dumps(resources_store),
                fuel_cost,
                pct,
                int(preview["distance"]),
                flight_seconds,
                preset_id,
                batch_id,
                now,
                now,
            ),
        )
        fleet_id = int(cur.lastrowid)

        if str(target_info.get("target_type") or "") == "world_boss" and mission == "attack":
            from .world_boss import note_attack_dispatched

            wb = target_info.get("world_boss") or {}
            wb_event_id = int(wb.get("event_id") or 0)
            if wb_event_id > 0:
                note_attack_dispatched(
                    int(player_id),
                    wb_event_id,
                    conn=conn,
                    now=now,
                )

        if str(target_info.get("target_type") or "") == "pirate_base" and mission == "attack":
            from .pirates.bases import note_attack_dispatched as note_pirate_attack

            pb = target_info.get("pirate_base") or {}
            pb_id = int(pb.get("base_id") or 0)
            if pb_id > 0:
                note_pirate_attack(
                    int(player_id),
                    pb_id,
                    conn=conn,
                    now=now,
                )

        # GC-P23: inbound attack on living AI → panic fleet-save.
        if mission == "attack" and target_planet_id:
            try:
                from .pirates.ambush import maybe_fleet_save_on_inbound_attack

                maybe_fleet_save_on_inbound_attack(
                    conn,
                    attacker_id=int(player_id),
                    target_planet_id=int(target_planet_id),
                    now=now,
                )
            except Exception:
                logger.exception(
                    "pirate fleet-save inbound hook failed target_planet=%s",
                    target_planet_id,
                )

        if own:
            commit(conn)

        try:
            from .directives.progress import emit_fleet_mission_sent

            emit_fleet_mission_sent(
                int(player_id),
                mission=mission,
                fleet_id=fleet_id,
                conn=conn,
                now=now,
            )
            if own:
                conn.commit()
        except Exception:
            logger.exception(
                "imperial_directives fleet send progress failed player=%s fleet=%s",
                player_id,
                fleet_id,
            )

        result = {
            "fleet": enrich_movement_timing(
                _row_to_movement(
                    conn.execute("SELECT * FROM fleet_movements WHERE id = ?;", (fleet_id,)).fetchone()
                )
            ),
            "updated_ships": get_planet_ships(int(origin_planet_id), conn=conn),
            "updated_resources": {
                "metal": int(new_metal),
                "crystal": int(new_crystal),
                "fuel_cells": int(new_fuel_cells),
            },
            "active_slots": get_fleet_slot_status(player_id, conn=conn),
            "fuel_cost": fuel_cost,
        }
        return True, "", result
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def _fail_outbound_movement(conn, movement_id: int, now: float) -> bool:
    """Mark a stuck outbound movement as failed (idempotent; safe to call twice)."""
    return _claim_movement_status(
        conn,
        int(movement_id),
        ("outbound",),
        "failed",
        now,
    )


def _fail_returning_movement(conn, movement_id: int, now: float) -> bool:
    """Mark a stuck returning movement as failed (idempotent)."""
    return _claim_movement_status(
        conn,
        int(movement_id),
        ("returning",),
        "failed",
        now,
    )


def _claim_movement_status(
    conn,
    movement_id: int,
    from_statuses: tuple[str, ...] | list[str],
    to_status: str,
    now: float,
    *,
    extra_sql: str = "",
    extra_params: tuple[Any, ...] = (),
) -> bool:
    """Atomically transition movement status; False if already processed (idempotent tick)."""
    placeholders = ",".join("?" for _ in from_statuses)
    sql = (
        f"UPDATE fleet_movements SET status = ?, updated_at = ?{extra_sql} "
        f"WHERE id = ? AND status IN ({placeholders});"
    )
    params: tuple[Any, ...] = (to_status, now, *extra_params, int(movement_id), *from_statuses)
    cur = conn.execute(sql, params)
    return int(cur.rowcount or 0) > 0


def _return_leg_seconds(movement: Mapping[str, Any]) -> int:
    return max(1, int(movement.get("flight_seconds") or movement.get("duration_seconds") or 0))


def _outbound_elapsed_recall_seconds(movement: Mapping[str, Any], *, now: float) -> int:
    """Return leg duration after player recall from outbound = time already flown."""
    full = _return_leg_seconds(movement)
    try:
        dep = float(movement.get("departure_at") or now)
    except (TypeError, ValueError):
        dep = float(now)
    elapsed = max(0, int(now) - int(dep))
    return max(1, min(elapsed, full))


def _return_timing_from_now(
    movement: Mapping[str, Any],
    *,
    now: float,
    delay_seconds: int = 0,
    duration_seconds: int | None = None,
) -> Dict[str, int]:
    """Build return timing. Positive delay defers start; negative delay shortens duration (GC-620J-B)."""
    delay = int(delay_seconds)
    base_duration = max(
        1, int(duration_seconds if duration_seconds is not None else _return_leg_seconds(movement))
    )
    if delay < 0:
        duration = max(1, base_duration + delay)
        started = int(now)
    else:
        started = int(now) + delay
        duration = base_duration
    return build_return_timing(return_started_at=started, duration_seconds=duration)


def _bounce_inbound_vacation_protected(
    movement: Dict[str, Any],
    *,
    conn,
    now: float,
    sender_locale: str | None = None,
) -> bool:
    """Return attack/spy fleets without combat when the target is in vacation mode."""
    from .options import vacation_blocks_incoming_attack

    movement_id = int(movement["id"])
    player_id = int(movement["player_id"])
    target_id = movement.get("target_planet_id")
    coords = str(movement.get("target_coords") or "")
    mission = str(movement.get("mission_type") or "").strip().lower()
    if mission not in ("attack", "spy") or not target_id:
        return False

    snapshot = _target_planet_snapshot(int(target_id), conn=conn)
    defender_id = int(snapshot.get("owner_id") or 0)
    if defender_id <= 0 or not vacation_blocks_incoming_attack(defender_id, conn=conn):
        return False

    if not _start_return(movement, conn=conn, now=now):
        return False

    from .i18n import get_player_locale, tr

    locale = sender_locale or get_player_locale(player_id, conn=conn)
    defender_name = str(snapshot.get("owner_name") or _player_name(defender_id, conn=conn))
    _notify_player_idempotent_fleet(
        player_id,
        tr(
            "fleet_vacation_bounce_subject",
            "Fleet recalled — vacation mode",
            locale=locale,
            coords=coords,
        ),
        tr(
            "fleet_vacation_bounce_body",
            "Your %(mission)s fleet at %(coords)s was recalled: %(target)s is in vacation mode and cannot be attacked.",
            locale=locale,
            mission=tr(f"fleet_mission_{mission}", mission, locale=locale),
            coords=coords,
            target=defender_name,
        ),
        metadata={
            "fleet_id": movement_id,
            "mission_type": mission,
            "target_coords": coords,
            "target_player_id": defender_id,
            "report_phase": "vacation_bounce",
            "direction": "outbound",
        },
        conn=conn,
    )
    return True


def _start_return(
    movement: Dict[str, Any],
    *,
    conn,
    now: float,
    remaining_resources: Mapping[str, Any] | None = None,
    delay_seconds: int = 0,
    outbound_recall: bool = False,
) -> bool:
    resources = remaining_resources if remaining_resources is not None else movement.get("resources") or {}
    duration = (
        _outbound_elapsed_recall_seconds(movement, now=now)
        if outbound_recall
        else _return_leg_seconds(movement)
    )
    timing = _return_timing_from_now(
        movement,
        now=now,
        delay_seconds=delay_seconds,
        duration_seconds=duration,
    )
    return_at = timing["return_at"]
    from .asteroids import merge_asteroid_resource_meta

    stored = merge_asteroid_resource_meta(
        calculate_loaded_resources(resources),
        resources if isinstance(resources, Mapping) else {},
    )
    return _claim_movement_status(
        conn,
        int(movement["id"]),
        ("outbound", "holding"),
        "returning",
        now,
        extra_sql=", return_at = ?, resources_json = ?",
        extra_params=(return_at, _json_dumps(stored)),
    )


def _complete_movement(movement_id: int, *, conn, now: float, from_status: str = "returning") -> bool:
    return _claim_movement_status(conn, int(movement_id), (from_status,), "completed", now)


def _credit_planet_resources(planet_id: int, resources: Mapping[str, Any], *, conn) -> None:
    loaded = calculate_loaded_resources(resources)
    if loaded["metal"] <= 0 and loaded["crystal"] <= 0 and loaded["fuel_cells"] <= 0:
        return
    lock_planet_for_update(conn, int(planet_id))
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (
            float(row["metal"]) + loaded["metal"],
            float(row["crystal"]) + loaded["crystal"],
            float(row["fuel_cells"] or 0) + loaded["fuel_cells"],
            int(planet_id),
        ),
    )


def _debit_planet_resources(planet_id: int, resources: Mapping[str, Any], *, conn) -> bool:
    from .resources import debit_planet_resources

    return debit_planet_resources(planet_id, resources, conn=conn)


def _calculate_collect_load(
    available: Mapping[str, Any],
    remaining_cap: int,
) -> Dict[str, int]:
    """Load resources from a planet up to remaining cargo (metal → crystal → fuel_cells)."""
    from .resources import load_resources_up_to_cargo

    return load_resources_up_to_cargo(available, remaining_cap)


def _player_name(player_id: int, *, conn) -> str:
    cur = conn.cursor()
    cur.execute("SELECT name FROM players WHERE id = ? LIMIT 1;", (int(player_id),))
    row = cur.fetchone()
    return str(row["name"] if row else f"Player {player_id}")


def _apply_attack_combat_to_planet(
    *,
    planet_id: int,
    owner_id: int,
    ships_before: Mapping[str, int],
    defense_before: Mapping[str, int],
    defender_losses: Mapping[str, int],
    conn,
) -> Dict[str, int]:
    """Persist defender ship/defense stock after combat; returns remaining ships on planet."""
    from .combat import remaining_stock, split_defender_losses
    from .models import defense_schema_ready, set_planet_defense

    ship_losses, defense_losses = split_defender_losses(defender_losses)
    remaining_ships = remaining_stock(ships_before, ship_losses, canonical_ship_keys=True)
    remaining_defense = remaining_stock(defense_before, defense_losses)
    if int(owner_id) > 0:
        set_planet_ships(int(planet_id), int(owner_id), remaining_ships, conn=conn)
        if defense_schema_ready(conn):
            set_planet_defense(int(planet_id), remaining_defense, conn=conn)
    return remaining_ships


def _handle_pirate_base_attack_arrival(movement: Dict[str, Any], *, conn, now: float) -> bool:
    """Resolve EPIC-21 pirate-base attack arrival via ``pirates.bases.resolve_attack_arrival``."""
    movement_id = int(movement["id"])
    player_id = int(movement["player_id"])
    ships = movement.get("ships") or {}
    try:
        from .pirates.bases import resolve_attack_arrival

        result = resolve_attack_arrival(
            movement=movement,
            ships=ships,
            player_id=player_id,
            conn=conn,
            now=float(now),
        )
        return_ships = {
            k: v
            for k, v in dict(result.get("return_ships") or ships).items()
            if int(v or 0) > 0
        }
        resources = dict(movement.get("resources") or {})
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, ships_json = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(return_ships), _json_dumps(resources)),
        )
        return bool(claimed)
    except Exception:
        logger.exception("pirate_base attack arrival failed movement_id=%s", movement_id)
        try:
            _claim_movement_status(conn, movement_id, ("outbound",), "failed", now)
        except Exception:
            pass
        return False


def _handle_world_boss_attack_arrival(movement: Dict[str, Any], *, conn, now: float) -> bool:
    """Resolve EPIC-20 world-boss attack arrival via ``world_boss.resolve_attack_arrival``."""
    movement_id = int(movement["id"])
    player_id = int(movement["player_id"])
    ships = movement.get("ships") or {}
    try:
        from .world_boss import resolve_attack_arrival

        result = resolve_attack_arrival(
            movement=movement,
            ships=ships,
            player_id=player_id,
            conn=conn,
            now=float(now),
        )
        return_ships = {
            k: v
            for k, v in dict(result.get("return_ships") or ships).items()
            if int(v or 0) > 0
        }
        resources = dict(movement.get("resources") or {})
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, ships_json = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(return_ships), _json_dumps(resources)),
        )
        return bool(claimed)
    except Exception:
        logger.exception("world_boss attack arrival failed movement_id=%s", movement_id)
        try:
            _claim_movement_status(conn, movement_id, ("outbound",), "failed", now)
        except Exception:
            pass
        return False


def _handle_attack_arrival(movement: Dict[str, Any], *, conn, now: float) -> bool:
    """
    Resolve attack combat, loot, debris, ranking, and return flight.

    On failure after partial combat, marks the movement ``failed`` so the tick does not
    retry (avoids duplicate debris, loot, scores, or reports).
    """
    movement_id = int(movement["id"])
    player_id = int(movement["player_id"])
    target_id = movement.get("target_planet_id")
    ships = movement.get("ships") or {}
    coords = movement.get("target_coords") or ""
    from .i18n import get_player_locale

    sender_locale = get_player_locale(player_id, conn=conn)
    combat_applied = False

    # EPIC-20: world boss attack (no planet target).
    try:
        from .world_boss import get_active_event_at

        wb_event = get_active_event_at(
            int(movement.get("target_galaxy") or 0),
            int(movement.get("target_system") or 0),
            int(movement.get("target_position") or 0),
            conn=conn,
            now=float(now),
        )
    except Exception:
        wb_event = None

    if wb_event and not target_id:
        return _handle_world_boss_attack_arrival(movement, conn=conn, now=now)

    try:
        from .pirates.bases import get_active_base_at

        pirate_base = get_active_base_at(
            int(movement.get("target_galaxy") or 0),
            int(movement.get("target_system") or 0),
            int(movement.get("target_position") or 0),
            conn=conn,
            now=float(now),
        )
    except Exception:
        pirate_base = None

    if pirate_base and not target_id:
        return _handle_pirate_base_attack_arrival(movement, conn=conn, now=now)

    try:
        snapshot = _target_planet_snapshot(int(target_id), conn=conn) if target_id else {}
        defender_id = int(snapshot.get("owner_id") or 0)
        if defender_id > 0:
            from .options import vacation_blocks_incoming_attack

            if vacation_blocks_incoming_attack(defender_id, conn=conn):
                return _bounce_inbound_vacation_protected(
                    movement,
                    conn=conn,
                    now=now,
                    sender_locale=sender_locale,
                )
        defender_name = str(snapshot.get("owner_name") or "")
        attacker_name = _player_name(player_id, conn=conn)
        defending_ships = dict(snapshot.get("ships") or {})
        defending_defense = dict((snapshot.get("defense") or {}).get("stock") or {})

        return_ships = dict(ships)
        combat_result = None
        if target_id:
            return_ships, combat_result = _resolve_attack_arrival(
                movement=movement,
                ships=ships,
                target_id=int(target_id),
                player_id=player_id,
                defender_id=defender_id,
                snapshot=snapshot,
                conn=conn,
            )
            combat_applied = True

        from .combat_balance_bots import finalize_combat_balance_run, is_bot_versus_bot_fight

        bot_fight = defender_id > 0 and is_bot_versus_bot_fight(
            int(player_id), int(defender_id), conn=conn
        )

        if combat_result is not None and not bot_fight:
            try:
                from .scoring import record_combat_outcome

                record_combat_outcome(
                    attacker_id=int(player_id),
                    defender_id=int(defender_id),
                    attacker_losses=combat_result.attacker_losses,
                    defender_losses=combat_result.defender_losses,
                    conn=conn,
                )
            except Exception:
                logger.exception("combat destruction score failed movement_id=%s", movement_id)

            try:
                from .pirates.hooks import safe_record_heat

                safe_record_heat(
                    conn,
                    int(movement.get("target_galaxy") or 0) or None,
                    "combat",
                )
            except Exception:
                logger.exception("pirate heat combat hook failed movement_id=%s", movement_id)

            score_players = {int(player_id)}
            if defender_id > 0:
                score_players.add(int(defender_id))
            try:
                from .score_events import apply_score_updates_for_players

                apply_score_updates_for_players(
                    score_players,
                    conn=conn,
                    reason="combat_attack",
                )
            except Exception:
                logger.exception("attack score refresh failed movement_id=%s", movement_id)

        resources = dict(movement.get("resources") or {})
        loot_taken: Dict[str, int] = {}
        if target_id and combat_result is not None:
            from .combat import apply_combat_loot

            loot_taken, resources = apply_combat_loot(
                winner=str(combat_result.winner),
                target_planet_id=int(target_id),
                return_ships=return_ships,
                existing_resources=resources,
                conn=conn,
            )

        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        return_ships = {k: v for k, v in return_ships.items() if int(v or 0) > 0}
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, ships_json = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(return_ships), _json_dumps(resources)),
        )
        if not claimed:
            return False
        from .combat import publish_attack_combat_report

        defender_locale = (
            get_player_locale(defender_id, conn=conn)
            if defender_id and defender_id != player_id
            else None
        )
        origin_coords, origin_planet_name = _movement_origin_snapshot(movement, conn=conn)
        report_out = publish_attack_combat_report(
            attacker_id=player_id,
            defender_id=defender_id,
            coords=coords,
            attacker_name=attacker_name,
            defender_name=defender_name,
            attacking_ships=ships,
            defending_ships=defending_ships,
            defending_defense=defending_defense,
            combat_result=combat_result,
            return_ships=return_ships,
            loot=loot_taken,
            fleet_id=movement_id,
            origin_coords=origin_coords,
            origin_planet_name=origin_planet_name,
            target_planet_name=str(snapshot.get("planet_name") or ""),
            attacker_planet_id=int(movement.get("origin_planet_id") or 0) or None,
            defender_planet_id=int(target_id) if target_id else None,
            conn=conn,
            attacker_locale=sender_locale,
            defender_locale=defender_locale,
        )
        if combat_result is not None:
            if not bot_fight:
                try:
                    from .directives.progress import emit_combat_directive_events

                    emit_combat_directive_events(
                        int(player_id),
                        movement_id=movement_id,
                        winner=str(combat_result.winner or ""),
                        defender_losses=combat_result.defender_losses,
                        conn=conn,
                        now=float(now),
                    )
                except Exception:
                    logger.exception(
                        "imperial_directives combat progress failed movement_id=%s",
                        movement_id,
                    )

            try:
                from .combat import calculate_combat_debris
                from .combat_hof import record_hof_battle

                debris_m, debris_c = calculate_combat_debris(
                    combat_result.attacker_losses,
                    combat_result.defender_losses,
                )
                record_hof_battle(
                    fleet_id=movement_id,
                    attacker_player_id=player_id,
                    defender_player_id=defender_id,
                    attacker_name=attacker_name,
                    defender_name=defender_name,
                    target_planet_id=int(target_id) if target_id else None,
                    target_name=str(snapshot.get("planet_name") or ""),
                    target_coords=coords,
                    winner=str(combat_result.winner or ""),
                    rounds=len(combat_result.rounds),
                    attacker_losses=combat_result.attacker_losses,
                    defender_losses=combat_result.defender_losses,
                    loot=loot_taken,
                    debris={"metal": int(debris_m), "crystal": int(debris_c)},
                    report_metadata=report_out.get("metadata") or {},
                    created_at=int(now),
                    conn=conn,
                )
            except Exception:
                logger.exception("combat hall of fame record failed movement_id=%s", movement_id)

            # GC-P24/P31: colony destroy (breaker + full wipe + non-homeworld).
            if target_id and not bot_fight:
                try:
                    from .pirates.destroy import (
                        maybe_destroy_colony_after_combat,
                        note_combat_vs_bot_bounty,
                    )

                    try:
                        note_combat_vs_bot_bounty(
                            conn,
                            attacker_id=int(player_id),
                            defender_id=int(defender_id),
                            now=float(now),
                        )
                    except Exception:
                        logger.exception("combat vs bot bounty failed")

                    wipe = maybe_destroy_colony_after_combat(
                        conn,
                        attacker_id=int(player_id),
                        defender_id=int(defender_id),
                        target_planet_id=int(target_id),
                        combat_result=combat_result,
                        return_ships=return_ships,
                        movement_id=movement_id,
                        now=float(now),
                    )
                    if wipe.get("ok") and wipe.get("return_ships") is not None:
                        return_ships = dict(wipe["return_ships"])
                        conn.execute(
                            "UPDATE fleet_movements SET ships_json = ?, updated_at = ? WHERE id = ?;",
                            (_json_dumps(return_ships), float(now), int(movement_id)),
                        )
                except Exception:
                    logger.exception(
                        "ai colony destroy hook failed movement_id=%s", movement_id
                    )

            if bot_fight:
                try:
                    finalize_combat_balance_run(
                        movement_id,
                        combat_result=combat_result,
                        loot=loot_taken,
                        conn=conn,
                        now=float(now),
                    )
                except Exception:
                    logger.exception(
                        "combat balance audit finalize failed movement_id=%s",
                        movement_id,
                    )
        return True
    except Exception:
        logger.exception(
            "attack arrival failed movement_id=%s combat_applied=%s",
            movement_id,
            combat_applied,
        )
        if _fail_outbound_movement(conn, movement_id, now):
            return False
        raise
    return False


def _resolve_attack_arrival(
    *,
    movement: Dict[str, Any],
    ships: Mapping[str, int],
    target_id: int,
    player_id: int,
    defender_id: int,
    snapshot: Mapping[str, Any],
    conn,
) -> Tuple[Dict[str, int], Any]:
    """Run combat for an attack arrival; return surviving outbound ships + CombatResult."""
    from .combat import (
        attacker_stacks_from_fleet,
        battle_rng_for_movement,
        defender_stacks_from_planet,
        make_combat_side,
        simulate_battle,
    )

    movement_id = int(movement["id"])
    origin_id = int(movement["origin_planet_id"])
    defending_ships = dict(snapshot.get("ships") or {})
    defending_defense = dict((snapshot.get("defense") or {}).get("stock") or {})

    atk_stacks = attacker_stacks_from_fleet(ships)
    def_stacks = defender_stacks_from_planet(defending_ships, defending_defense)
    combat_result = simulate_battle(
        make_combat_side("attacker", atk_stacks),
        make_combat_side("defender", def_stacks),
        rng=battle_rng_for_movement(movement_id),
        attacker_player_id=int(player_id),
        defender_player_id=int(defender_id) if defender_id > 0 else None,
        attacker_planet_id=origin_id,
        defender_planet_id=int(target_id),
        conn=conn,
    )

    from .combat import remaining_stock

    return_ships = remaining_stock(ships, combat_result.attacker_losses, canonical_ship_keys=True)
    if int(target_id) > 0 and defender_id > 0:
        _apply_attack_combat_to_planet(
            planet_id=int(target_id),
            owner_id=int(defender_id),
            ships_before=defending_ships,
            defense_before=defending_defense,
            defender_losses=combat_result.defender_losses,
            conn=conn,
        )
    if int(target_id) > 0:
        from .combat import spawn_combat_debris_at_planet

        spawn_combat_debris_at_planet(
            int(target_id),
            attacker_losses=combat_result.attacker_losses,
            defender_losses=combat_result.defender_losses,
            conn=conn,
        )
    return return_ships, combat_result


def _format_transport_cargo(resources: Mapping[str, Any], *, locale: str | None = None) -> str:
    from .i18n import fmt_int, tr

    def _t(key, default=None, **kw):
        return tr(key, default, locale=locale, **kw)

    loaded = calculate_loaded_resources(resources)
    parts: list[str] = []
    if loaded["metal"]:
        parts.append(f"{_t('resource_metal', 'Ferronit')}: {fmt_int(loaded['metal'])}")
    if loaded["crystal"]:
        parts.append(f"{_t('resource_crystal', 'Crytite')}: {fmt_int(loaded['crystal'])}")
    if loaded["fuel_cells"]:
        parts.append(f"{_t('resource_fuel_cells', 'Brennzellen')}: {fmt_int(loaded['fuel_cells'])}")
    if not parts:
        return _t("fleet_transport_report_cargo_empty", "keine Ressourcen")
    return ", ".join(parts)


def _format_transport_report(
    *,
    coords: str,
    origin_name: str,
    target_name: str,
    resources: Mapping[str, Any],
    incoming: bool,
    locale: str | None = None,
) -> str:
    from .i18n import tr

    cargo_txt = _format_transport_cargo(resources, locale=locale)
    if incoming:
        return tr(
            "fleet_transport_report_incoming",
            "Eingehender Transport bei %(coords)s von %(origin)s. Geliefert: %(cargo)s.",
            locale=locale,
            coords=coords,
            origin=origin_name,
            cargo=cargo_txt,
        )
    return tr(
        "fleet_transport_report_outbound",
        "Transport nach %(coords)s (%(target)s) abgeschlossen. Geliefert: %(cargo)s.",
        locale=locale,
        coords=coords,
        target=target_name,
        cargo=cargo_txt,
    )


def _format_recycle_report(
    *,
    coords: str,
    origin_name: str,
    collected: Mapping[str, Any],
    locale: str | None = None,
) -> str:
    from .i18n import tr

    cargo_txt = _format_transport_cargo(collected, locale=locale)
    if loaded_resource_total(collected) <= 0:
        return tr(
            "fleet_recycle_report_empty",
            "Recycle at %(coords)s — no debris collected. Fleet returning to %(origin)s.",
            locale=locale,
            coords=coords,
            origin=origin_name,
        )
    return tr(
        "fleet_recycle_report",
        "Recycle at %(coords)s: %(cargo)s loaded. Fleet returning to %(origin)s.",
        locale=locale,
        coords=coords,
        origin=origin_name,
        cargo=cargo_txt,
    )


def _format_asteroid_report(
    *,
    coords: str,
    origin_name: str,
    collected: Mapping[str, Any],
    missed: bool = False,
    expired: bool = False,
    locale: str | None = None,
) -> str:
    from .i18n import tr

    if expired:
        return tr(
            "fleet_asteroid_report_expired",
            "Asteroid at %(coords)s expired before arrival. Fleet returning empty to %(origin)s.",
            locale=locale,
            coords=coords,
            origin=origin_name,
        )
    if missed:
        return tr(
            "fleet_asteroid_report_missed",
            "Asteroid at %(coords)s already harvested. Fleet returning empty to %(origin)s.",
            locale=locale,
            coords=coords,
            origin=origin_name,
        )
    cargo_txt = _format_transport_cargo(collected, locale=locale)
    if loaded_resource_total(collected) <= 0:
        return tr(
            "fleet_asteroid_report_empty",
            "Asteroid at %(coords)s yielded nothing. Fleet returning to %(origin)s.",
            locale=locale,
            coords=coords,
            origin=origin_name,
        )
    return tr(
        "fleet_asteroid_report",
        "Asteroid harvest at %(coords)s: %(cargo)s loaded. Fleet returning to %(origin)s.",
        locale=locale,
        coords=coords,
        origin=origin_name,
        cargo=cargo_txt,
    )


def _format_collect_report(
    *,
    coords: str,
    origin_name: str,
    target_name: str,
    collected: Mapping[str, Any],
    total_cargo: Mapping[str, Any],
    locale: str | None = None,
) -> str:
    from .i18n import tr

    collected_txt = _format_transport_cargo(collected, locale=locale)
    total_txt = _format_transport_cargo(total_cargo, locale=locale)
    if loaded_resource_total(collected) <= 0:
        return tr(
            "fleet_collect_report_empty",
            "Collect at %(coords)s (%(target)s) — no resources loaded. Fleet returning to %(origin)s.",
            locale=locale,
            coords=coords,
            target=target_name,
            origin=origin_name,
        )
    if loaded_resource_total(total_cargo) > loaded_resource_total(collected):
        return tr(
            "fleet_collect_report_with_departure",
            "Collect at %(coords)s (%(target)s): %(collected)s loaded (total cargo: %(total)s). Returning to %(origin)s.",
            locale=locale,
            coords=coords,
            target=target_name,
            origin=origin_name,
            collected=collected_txt,
            total=total_txt,
        )
    return tr(
        "fleet_collect_report",
        "Collect at %(coords)s (%(target)s): %(cargo)s loaded. Fleet returning to %(origin)s.",
        locale=locale,
        coords=coords,
        target=target_name,
        origin=origin_name,
        cargo=collected_txt,
    )


def _movement_batch_type(movement: Mapping[str, Any], *, conn) -> str | None:
    batch_id = movement.get("parent_batch_id")
    if not batch_id:
        return None
    cur = conn.cursor()
    cur.execute(
        "SELECT batch_type FROM fleet_batches WHERE id = ? LIMIT 1;",
        (int(batch_id),),
    )
    row = cur.fetchone()
    return str(row["batch_type"]) if row else None


def _build_logistics_report_metadata(
    *,
    movement_id: int,
    report_phase: str,
    mission_type: str,
    coords: str,
    origin_planet_id: int,
    origin_name: str,
    target_planet_id: int | None,
    target_name: str,
    ships: Mapping[str, Any],
    resources: Mapping[str, Any],
    collected: Mapping[str, Any] | None,
    parent_batch_id: int | None,
    now: float,
) -> Dict[str, Any]:
    loaded = calculate_loaded_resources(resources)
    meta: Dict[str, Any] = {
        "fleet_id": int(movement_id),
        "report_phase": str(report_phase),
        "mission_type": str(mission_type),
        "timestamp": int(now),
        "origin_planet_id": int(origin_planet_id),
        "origin_name": str(origin_name),
        "target_planet_id": int(target_planet_id) if target_planet_id else None,
        "target_name": str(target_name),
        "target_coords": str(coords),
        "ships": normalize_ships(ships),
        "resources": loaded,
        "direction": str(report_phase),
    }
    if parent_batch_id:
        meta["parent_batch_id"] = int(parent_batch_id)
    if collected is not None:
        meta["collected"] = calculate_loaded_resources(collected)
    return meta


def _format_logistics_collect_arrival_report(
    *,
    coords: str,
    origin_name: str,
    target_name: str,
    collected: Mapping[str, Any],
    locale: str | None = None,
) -> str:
    from .i18n import tr

    cargo_txt = _format_transport_cargo(collected, locale=locale)
    if loaded_resource_total(collected) <= 0:
        return tr(
            "fleet_logistics_collect_arrival_empty",
            "Zusammenziehen bei %(coords)s (%(target)s) von %(origin)s — keine Ressourcen geliefert. Rückflug.",
            locale=locale,
            coords=coords,
            target=target_name,
            origin=origin_name,
        )
    return tr(
        "fleet_logistics_collect_arrival",
        "Zusammenziehen geliefert bei %(coords)s (%(target)s) von %(origin)s: %(cargo)s.",
        locale=locale,
        coords=coords,
        target=target_name,
        origin=origin_name,
        cargo=cargo_txt,
    )


def _format_logistics_collect_return_report(
    *,
    origin_name: str,
    resources: Mapping[str, Any],
    ships: Mapping[str, Any],
    locale: str | None = None,
) -> str:
    from .i18n import tr

    ships_txt = _format_fleet_ship_summary(ships, locale=locale)
    return tr(
        "fleet_logistics_collect_return",
        "Zusammenzieh-Flotte zurück auf %(origin)s. Schiffe: %(ships)s.",
        locale=locale,
        origin=origin_name,
        ships=ships_txt,
    )


def _format_logistics_distribute_arrival_report(
    *,
    coords: str,
    origin_name: str,
    target_name: str,
    resources: Mapping[str, Any],
    locale: str | None = None,
) -> str:
    from .i18n import tr

    cargo_txt = _format_transport_cargo(resources, locale=locale)
    return tr(
        "fleet_logistics_distribute_arrival",
        "Lieferung bei %(coords)s (%(target)s) von %(origin)s: %(cargo)s.",
        locale=locale,
        coords=coords,
        target=target_name,
        origin=origin_name,
        cargo=cargo_txt,
    )


def _format_logistics_distribute_return_report(
    *,
    origin_name: str,
    ships: Mapping[str, Any],
    locale: str | None = None,
) -> str:
    from .i18n import tr

    ships_txt = _format_fleet_ship_summary(ships, locale=locale)
    return tr(
        "fleet_logistics_distribute_return",
        "Logistik-Flotte zurück am Ursprung %(origin)s. Schiffe: %(ships)s.",
        locale=locale,
        origin=origin_name,
        ships=ships_txt,
    )


def _emit_logistics_fleet_report(
    player_id: int,
    *,
    subject: str,
    body: str,
    movement: Mapping[str, Any],
    movement_id: int,
    report_phase: str,
    mission_type: str,
    coords: str,
    origin_planet_id: int,
    origin_name: str,
    target_planet_id: int | None,
    target_name: str,
    ships: Mapping[str, Any],
    resources: Mapping[str, Any],
    collected: Mapping[str, Any] | None,
    now: float,
    locale: str | None,
    conn,
) -> None:
    meta = _build_logistics_report_metadata(
        movement_id=movement_id,
        report_phase=report_phase,
        mission_type=mission_type,
        coords=coords,
        origin_planet_id=origin_planet_id,
        origin_name=origin_name,
        target_planet_id=target_planet_id,
        target_name=target_name,
        ships=ships,
        resources=resources,
        collected=collected,
        parent_batch_id=_safe_int(movement.get("parent_batch_id")),
        now=now,
    )
    notify_logistics_fleet_report(
        player_id,
        subject,
        body,
        metadata=meta,
        locale=locale,
        conn=conn,
    )


def _ship_display_name(ship_key: str, *, locale: str | None = None) -> str:
    from .fleet_defs import ship_display_name

    return ship_display_name(ship_key, locale=locale)


def _format_fleet_ship_summary(ships: Mapping[str, Any], *, locale: str | None = None) -> str:
    from .i18n import fmt_int, tr

    parts: list[str] = []
    for key, qty in sorted((ships or {}).items()):
        amount = int(qty or 0)
        if amount > 0:
            parts.append(f"{_ship_display_name(key, locale=locale)} ×{fmt_int(amount)}")
    if not parts:
        return tr("fleet_deploy_report_ships_empty", "no ships", locale=locale)
    return ", ".join(parts)


def _format_deploy_report(
    *,
    coords: str,
    origin_name: str,
    target_name: str,
    ships: Mapping[str, Any],
    resources: Mapping[str, Any],
    locale: str | None = None,
) -> str:
    from .i18n import tr

    cargo_txt = _format_transport_cargo(resources, locale=locale)
    ships_txt = _format_fleet_ship_summary(ships, locale=locale)
    return tr(
        "fleet_deploy_report",
        "Deploy at %(coords)s (%(target)s) completed. Stationed: %(ships)s. Resources: %(cargo)s.",
        locale=locale,
        coords=coords,
        target=target_name,
        origin=origin_name,
        ships=ships_txt,
        cargo=cargo_txt,
    )


def _handle_arrival(movement: Dict[str, Any], *, conn, now: float) -> bool:
    mission = movement["mission_type"]
    player_id = int(movement["player_id"])
    target_id = movement.get("target_planet_id")
    ships = movement.get("ships") or {}
    resources = movement.get("resources") or {}
    movement_id = int(movement["id"])
    coords = movement.get("target_coords") or ""
    from .i18n import get_player_locale, tr

    sender_locale = get_player_locale(player_id, conn=conn)

    if mission in ("attack", "spy") and target_id:
        if _bounce_inbound_vacation_protected(
            movement,
            conn=conn,
            now=now,
            sender_locale=sender_locale,
        ):
            return True

    if mission == "recycle":
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        ships_n = normalize_ships(ships)
        cargo_total = calculate_total_cargo(ships_n)
        collected = {"metal": 0, "crystal": 0, "fuel_cells": 0}
        tg = int(movement.get("target_galaxy") or 0)
        ts = int(movement.get("target_system") or 0)
        tp = int(movement.get("target_position") or 0)
        asteroid_missed = False
        asteroid_harvested = False
        asteroid_expired = False
        asteroid_meta: Dict[str, Any] = {}
        prev_resources = movement.get("resources") or {}
        if not isinstance(prev_resources, Mapping):
            prev_resources = {}
        asteroid_stamp_id = int(prev_resources.get("asteroid_id") or 0)
        asteroid_stamp_key = str(prev_resources.get("asteroid_key") or "")
        from .asteroids import merge_asteroid_resource_meta

        # Claim movement first (idempotent), preserve hunt stamp in resources_json.
        stamp_seed = merge_asteroid_resource_meta({}, prev_resources)
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(stamp_seed)),
        )
        if not claimed:
            return False

        if cargo_total > 0:
            from .asteroids import try_claim_harvest

            claim = try_claim_harvest(
                tg,
                ts,
                tp,
                player_id=int(player_id),
                cargo_capacity=int(cargo_total),
                conn=conn,
                now=float(now),
            )
            status = str(claim.get("status") or "none")
            if status == "claimed":
                collected = dict(claim.get("harvested") or {})
                asteroid_harvested = True
                asteroid_meta = {
                    "asteroid_id": claim.get("asteroid_id") or asteroid_stamp_id,
                    "asteroid_key": claim.get("asteroid_key") or asteroid_stamp_key,
                    "pool": claim.get("pool") or {},
                }
            elif asteroid_stamp_id > 0:
                # Explicit asteroid hunt — never fall through to combat/world-boss debris.
                if status == "missed":
                    asteroid_missed = True
                else:
                    asteroid_expired = True
                asteroid_meta = {
                    "asteroid_id": claim.get("asteroid_id") or asteroid_stamp_id,
                    "asteroid_key": asteroid_stamp_key,
                }
            else:
                # Unstamped recycle (combat / world-boss debris): ignore asteroid history
                # at the same coords so WB debris is not reported as asteroid miss/expire.
                from .combat import get_debris_at_field, harvest_debris_at_field

                debris = get_debris_at_field(tg, ts, tp, conn=conn)
                pool = {
                    "metal": int(debris.get("metal") or 0),
                    "crystal": int(debris.get("crystal") or 0),
                    "fuel_cells": 0,
                }
                collected = _calculate_collect_load(pool, cargo_total)
                if loaded_resource_total(collected) > 0 and not harvest_debris_at_field(
                    tg, ts, tp, harvested=collected, conn=conn
                ):
                    collected = {"metal": 0, "crystal": 0, "fuel_cells": 0}

        final_resources = merge_asteroid_resource_meta(
            calculate_loaded_resources(collected),
            asteroid_meta or prev_resources,
        )
        conn.execute(
            """
            UPDATE fleet_movements
            SET resources_json = ?
            WHERE id = ?;
            """,
            (_json_dumps(final_resources), int(movement_id)),
        )

        origin_id = int(movement["origin_planet_id"])
        cur = conn.cursor()
        cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
        orow = cur.fetchone()
        origin_name = str(orow["name"] if orow else "")
        if asteroid_harvested or asteroid_missed or asteroid_expired:
            body = _format_asteroid_report(
                coords=coords,
                origin_name=origin_name,
                collected=collected,
                missed=asteroid_missed,
                expired=asteroid_expired,
                locale=sender_locale,
            )
            subject = tr(
                "fleet_asteroid_report_subject",
                "Asteroid report %(coords)s",
                locale=sender_locale,
                coords=coords,
            )
        else:
            body = _format_recycle_report(
                coords=coords,
                origin_name=origin_name,
                collected=collected,
                locale=sender_locale,
            )
            subject = tr(
                "fleet_recycle_report_subject",
                "Recycle report %(coords)s",
                locale=sender_locale,
                coords=coords,
            )
        asteroid_report_meta = {
            "fleet_id": movement_id,
            "mission_type": "recycle",
            "target_coords": coords,
            "collected": calculate_loaded_resources(collected),
            "resources": final_resources,
            "direction": "outbound",
            "asteroid_missed": asteroid_missed,
            "asteroid_harvested": asteroid_harvested,
            "asteroid_expired": asteroid_expired,
            **({"asteroid": asteroid_meta} if asteroid_meta else {}),
        }
        transport_res = notify_transport(
            player_id,
            subject,
            body,
            metadata=asteroid_report_meta,
            locale=sender_locale,
            conn=conn,
        )
        if asteroid_harvested or asteroid_missed or asteroid_expired:
            try:
                from .chronicle_entries import (
                    ENTRY_TYPE_ASTEROID,
                    record_chronicle_for_fleet_report,
                )

                msg_id = None
                if isinstance(transport_res, dict) and transport_res.get("ok"):
                    data = transport_res.get("data") or {}
                    if data.get("message_id") is not None:
                        msg_id = int(data["message_id"])
                record_chronicle_for_fleet_report(
                    player_id=int(player_id),
                    entry_type=ENTRY_TYPE_ASTEROID,
                    subject=subject,
                    metadata=asteroid_report_meta,
                    source_message_id=msg_id,
                    occurred_at=int(now),
                    conn=conn,
                )
            except Exception:
                logger.exception(
                    "asteroid chronicle persist failed movement_id=%s",
                    movement_id,
                )
        try:
            from .directives.progress import emit_recycle_complete_event

            emit_recycle_complete_event(
                int(player_id),
                movement_id=movement_id,
                conn=conn,
                now=float(now),
            )
        except Exception:
            logger.exception(
                "imperial_directives recycle progress failed movement_id=%s",
                movement_id,
            )
        try:
            from .activity_xp import SOURCE_RECYCLE, grant_fleet_activity_xp

            grant_fleet_activity_xp(
                player_id,
                int(movement["origin_planet_id"]),
                SOURCE_RECYCLE,
                movement_id,
                conn=conn,
                now=float(now),
            )
        except Exception:
            logger.exception("activity_xp recycle grant failed movement_id=%s", movement_id)
        return True

    if mission == "transport":
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        delivery = calculate_loaded_resources(resources)
        credited_target = False
        if target_id and loaded_resource_total(delivery) > 0:
            _credit_planet_resources(int(target_id), delivery, conn=conn)
            credited_target = True
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps({})),
        )
        if not claimed:
            if credited_target and target_id:
                _debit_planet_resources(int(target_id), delivery, conn=conn)
            return False
        if target_id:
            snapshot = _target_planet_snapshot(int(target_id), conn=conn)
            origin_id = int(movement["origin_planet_id"])
            cur = conn.cursor()
            cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
            orow = cur.fetchone()
            origin_name = str(orow["name"] if orow else "")
            target_name = str(snapshot.get("planet_name") or "")
            batch_type = _movement_batch_type(movement, conn=conn)
            if batch_type == "distribute_resources":
                dist_body = _format_logistics_distribute_arrival_report(
                    coords=coords,
                    origin_name=origin_name,
                    target_name=target_name,
                    resources=resources,
                    locale=sender_locale,
                )
                _emit_logistics_fleet_report(
                    player_id,
                    subject=tr(
                        "fleet_logistics_distribute_arrival_subject",
                        "Lieferung %(coords)s",
                        locale=sender_locale,
                        coords=coords,
                    ),
                    body=dist_body,
                    movement=movement,
                    movement_id=movement_id,
                    report_phase="logistics_distribute_arrival",
                    mission_type="distribute",
                    coords=coords,
                    origin_planet_id=origin_id,
                    origin_name=origin_name,
                    target_planet_id=int(target_id),
                    target_name=target_name,
                    ships=ships,
                    resources=resources,
                    collected=None,
                    now=now,
                    locale=sender_locale,
                    conn=conn,
                )
            elif batch_type == "collect_resources":
                collect_body = _format_logistics_collect_arrival_report(
                    coords=coords,
                    origin_name=origin_name,
                    target_name=target_name,
                    collected=resources,
                    locale=sender_locale,
                )
                _emit_logistics_fleet_report(
                    player_id,
                    subject=tr(
                        "fleet_logistics_collect_arrival_subject",
                        "Zusammenziehen %(coords)s",
                        locale=sender_locale,
                        coords=coords,
                    ),
                    body=collect_body,
                    movement=movement,
                    movement_id=movement_id,
                    report_phase="logistics_collect_arrival",
                    mission_type="collect",
                    coords=coords,
                    origin_planet_id=origin_id,
                    origin_name=origin_name,
                    target_planet_id=int(target_id),
                    target_name=target_name,
                    ships=ships,
                    resources=resources,
                    collected=calculate_loaded_resources(resources),
                    now=now,
                    locale=sender_locale,
                    conn=conn,
                )
            else:
                sender_body = _format_transport_report(
                    coords=coords,
                    origin_name=origin_name,
                    target_name=target_name,
                    resources=resources,
                    incoming=False,
                    locale=sender_locale,
                )

                notify_transport(
                    player_id,
                    tr(
                        "fleet_transport_report_subject",
                        "Transportbericht %(coords)s",
                        locale=sender_locale,
                        coords=coords,
                    ),
                    sender_body,
                    metadata={
                        "fleet_id": movement_id,
                        "target_coords": coords,
                        "resources": calculate_loaded_resources(resources),
                        "direction": "outbound",
                    },
                    locale=sender_locale,
                    conn=conn,
                )
            target_owner = int(snapshot.get("owner_id") or 0)
            if (
                target_owner
                and target_owner != player_id
                and batch_type not in ("distribute_resources", "collect_resources")
            ):
                target_locale = get_player_locale(target_owner, conn=conn)
                incoming_body = _format_transport_report(
                    coords=coords,
                    origin_name=_player_name(player_id, conn=conn),
                    target_name=str(snapshot.get("planet_name") or ""),
                    resources=resources,
                    incoming=True,
                    locale=target_locale,
                )
                notify_transport(
                    target_owner,
                    tr(
                        "fleet_transport_report_subject_incoming",
                        "Eingehender Transport %(coords)s",
                        locale=target_locale,
                        coords=coords,
                    ),
                    incoming_body,
                    metadata={
                        "fleet_id": movement_id,
                        "sender_id": player_id,
                        "target_coords": coords,
                        "resources": calculate_loaded_resources(resources),
                        "direction": "incoming",
                    },
                    locale=target_locale,
                    conn=conn,
                )
        return True

    if mission == "collect":
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        ships = normalize_ships(ships)
        current_loaded = calculate_loaded_resources(resources)
        cargo_total = calculate_total_cargo(ships)
        remaining_cap = max(0, cargo_total - loaded_resource_total(current_loaded))
        collected = {"metal": 0, "crystal": 0, "fuel_cells": 0}
        target_name = ""
        origin_name = ""

        if target_id and remaining_cap > 0:
            snapshot = _target_planet_snapshot(int(target_id), conn=conn)
            target_name = str(snapshot.get("planet_name") or "")
            owner_id = int(snapshot.get("owner_id") or 0)
            if owner_id == player_id:
                from .resources import get_planet_resource_stock

                available = get_planet_resource_stock(int(target_id), conn=conn)
                proposed = _calculate_collect_load(available, remaining_cap)
                if loaded_resource_total(proposed) > 0:
                    if _debit_planet_resources(int(target_id), proposed, conn=conn):
                        collected = proposed
                    else:
                        # Concurrent collect on same source: load only what debit allows.
                        retry_available = get_planet_resource_stock(int(target_id), conn=conn)
                        retry = _calculate_collect_load(retry_available, remaining_cap)
                        if loaded_resource_total(retry) > 0 and _debit_planet_resources(
                            int(target_id), retry, conn=conn
                        ):
                            collected = retry

        final_resources = calculate_loaded_resources(
            {
                "metal": current_loaded["metal"] + collected["metal"],
                "crystal": current_loaded["crystal"] + collected["crystal"],
                "fuel_cells": current_loaded["fuel_cells"] + collected["fuel_cells"],
            }
        )
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(final_resources)),
        )
        if not claimed:
            if target_id and loaded_resource_total(collected) > 0:
                _credit_planet_resources(int(target_id), collected, conn=conn)
            return False

        origin_id = int(movement["origin_planet_id"])
        cur = conn.cursor()
        cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
        orow = cur.fetchone()
        origin_name = str(orow["name"] if orow else "")
        if not target_name and target_id:
            snapshot = _target_planet_snapshot(int(target_id), conn=conn)
            target_name = str(snapshot.get("planet_name") or "")

        collect_body = _format_logistics_collect_arrival_report(
            coords=coords,
            origin_name=origin_name,
            target_name=target_name,
            collected=collected,
            locale=sender_locale,
        )
        _emit_logistics_fleet_report(
            player_id,
            subject=tr(
                "fleet_logistics_collect_arrival_subject",
                "Abholung %(coords)s",
                locale=sender_locale,
                coords=coords,
            ),
            body=collect_body,
            movement=movement,
            movement_id=movement_id,
            report_phase="logistics_collect_arrival",
            mission_type="collect",
            coords=coords,
            origin_planet_id=origin_id,
            origin_name=origin_name,
            target_planet_id=int(target_id) if target_id else None,
            target_name=target_name,
            ships=ships,
            resources=final_resources,
            collected=collected,
            now=now,
            locale=sender_locale,
            conn=conn,
        )
        return True

    if mission == "deploy":
        if not _claim_movement_status(conn, movement_id, ("outbound",), "completed", now):
            return False
        target_name = ""
        if target_id:
            _credit_planet_resources(int(target_id), resources, conn=conn)
            cur = conn.cursor()
            cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(target_id),))
            trow = cur.fetchone()
            owner = int(trow["player_id"]) if trow else player_id
            add_planet_ships(int(target_id), owner, ships, conn=conn)
            snapshot = _target_planet_snapshot(int(target_id), conn=conn)
            target_name = str(snapshot.get("planet_name") or "")
        origin_id = int(movement["origin_planet_id"])
        cur = conn.cursor()
        cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
        orow = cur.fetchone()
        origin_name = str(orow["name"] if orow else "")
        body = _format_deploy_report(
            coords=coords,
            origin_name=origin_name,
            target_name=target_name,
            ships=ships,
            resources=resources,
            locale=sender_locale,
        )
        notify_transport(
            player_id,
            tr(
                "fleet_deploy_report_subject",
                "Deploy report %(coords)s",
                locale=sender_locale,
                coords=coords,
            ),
            body,
            metadata={
                "fleet_id": movement_id,
                "mission_type": "deploy",
                "target_coords": coords,
                "resources": calculate_loaded_resources(resources),
                "ships": normalize_ships(ships),
                "direction": "arrival",
            },
            locale=sender_locale,
            conn=conn,
        )
        return True

    if mission == "spy":
        snapshot = _target_planet_snapshot(int(target_id), conn=conn) if target_id else {}
        probe_count = _spy_probe_count(ships)
        body, meta = _build_spy_report_body(
            snapshot,
            probe_count,
            viewer_id=player_id,
            conn=conn,
            locale=sender_locale,
        )
        meta["fleet_id"] = movement_id
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?",
            extra_params=(return_at,),
        )
        if not claimed:
            return False
        notify_espionage(
            player_id,
            tr(
                "fleet_report_spy_subject_coords",
                "Espionage report — %(coords)s",
                locale=sender_locale,
                coords=coords,
            ),
            body,
            metadata=meta,
            locale=sender_locale,
            conn=conn,
        )
        try:
            from .pirates.accounts import is_pirate_bot_player
            from .pirates.brain import ingest_spy_report_for_intel

            if is_pirate_bot_player(int(player_id), conn=conn):
                ingest_spy_report_for_intel(
                    conn,
                    bot_player_id=int(player_id),
                    meta=meta,
                    snapshot=snapshot,
                    now=float(now),
                )
        except Exception:
            logger.exception(
                "pirate spy intel ingest failed movement_id=%s", movement_id
            )
        try:
            from .activity_xp import SOURCE_SPY, grant_fleet_activity_xp

            grant_fleet_activity_xp(
                player_id,
                int(movement["origin_planet_id"]),
                SOURCE_SPY,
                movement_id,
                conn=conn,
                now=float(now),
            )
        except Exception:
            logger.exception("activity_xp spy grant failed movement_id=%s", movement_id)
        return True

    if mission == "attack":
        return _handle_attack_arrival(movement, conn=conn, now=now)

    if mission == "hold":
        holding_until = int(now) + DEFAULT_HOLD_SECONDS
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "holding",
            now,
            extra_sql=", holding_until = ?",
            extra_params=(holding_until,),
        )
        if not claimed:
            return False
        snapshot = _target_planet_snapshot(int(target_id), conn=conn) if target_id else {}
        target_label = str(snapshot.get("planet_name") or snapshot.get("owner_name") or "")
        _notify_player_idempotent_fleet(
            player_id,
            tr(
                "fleet_hold_report_subject",
                "Fleet holding %(coords)s",
                locale=sender_locale,
                coords=coords,
            ),
            tr(
                "fleet_hold_report_body",
                "Your fleet is holding position at %(coords)s (%(target)s) until %(until)s.",
                locale=sender_locale,
                coords=coords,
                target=target_label,
                until=holding_until,
            ),
            category="system",
            metadata={
                "fleet_id": movement_id,
                "mission_type": "hold",
                "target_coords": coords,
                "holding_until": holding_until,
                "direction": "arrival",
            },
            sender_name=tr("messages_sender_transport", "Transportbericht", locale=sender_locale),
            conn=conn,
        )
        return True

    if mission == "expedition":
        stay_seconds = expedition_stay_seconds(_expedition_hours_from_movement(movement))
        holding_until = int(now) + stay_seconds
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "holding",
            now,
            extra_sql=", holding_until = ?",
            extra_params=(holding_until,),
        )
        return bool(claimed)

    if mission == "colonize":
        from .planet_evolution.service import colonize_planet
        from .planet_evolution.world_colonization import (
            complete_world_claim,
            WorldKeyError,
            build_world_colonize_report,
            parse_world_key,
            release_world_claim,
            reserve_world_claim,
        )

        def _notify_world_colonize(
            *,
            success: bool,
            fail_reason: str | None = None,
            planet_id: int | None = None,
        ) -> None:
            if not world_key:
                return
            try:
                subject, body, meta = build_world_colonize_report(
                    world_key,
                    colony_name,
                    locale=sender_locale,
                    success=success,
                    fail_reason=fail_reason,
                )
            except WorldKeyError:
                return
            meta["fleet_id"] = movement_id
            if planet_id is not None:
                meta["planet_id"] = int(planet_id)
            notify_combat(
                player_id,
                subject,
                body,
                metadata=meta,
                locale=sender_locale,
                conn=conn,
            )

        coords = movement.get("target_coords") or ""
        raw_res = movement.get("resources") or {}
        colony_name = str(raw_res.get("colony_name") or "").strip() or f"Colony {coords}"
        world_key = str(raw_res.get("world_key") or "").strip()
        tg = int(movement.get("target_galaxy") or 0)
        ts = int(movement.get("target_system") or 0)
        tp = int(movement.get("target_position") or 0)
        return_ships = normalize_ships(ships)

        if return_ships:
            timing = _return_timing_from_now(movement, now=now)
            return_at = timing["return_at"]
            claimed = _claim_movement_status(
                conn,
                movement_id,
                ("outbound",),
                "returning",
                now,
                extra_sql=", return_at = ?, ships_json = ?, resources_json = ?",
                extra_params=(return_at, _json_dumps(return_ships), _json_dumps({})),
            )
        else:
            claimed = _complete_movement(movement_id, conn=conn, now=now, from_status="outbound")

        if not claimed:
            return False

        world_binding = None
        report_coords = coords
        if world_key:
            try:
                parsed = parse_world_key(world_key)
            except WorldKeyError:
                parsed = None
            if not parsed:
                release_world_claim(world_key, conn=conn, player_id=player_id)
                if not _notify_world_colonize(success=False, fail_reason="invalid_world_key"):
                    notify_combat(
                        player_id,
                        tr(
                            "fleet_report_colonize_failed_subject_coords",
                            "Colonization failed — %(coords)s",
                            locale=sender_locale,
                            coords=world_key,
                        ),
                        tr(
                            "fleet_report_colonize_failed_body",
                            "Could not establish colony at %(coords)s: %(reason)s.",
                            locale=sender_locale,
                            coords=world_key,
                            reason="invalid_world_key",
                        ),
                        metadata={"fleet_id": movement_id, "mission_type": "colonize", "reason": "invalid_world_key"},
                        locale=sender_locale,
                        conn=conn,
                    )
                return True
            ok_claim, claim_reason, claim_data = reserve_world_claim(
                player_id,
                parsed["world_x"],
                parsed["world_y"],
                world_type=parsed["world_type"],
                conn=conn,
            )
            if not ok_claim or not claim_data:
                fail = claim_reason or "world_already_claimed"
                if not _notify_world_colonize(success=False, fail_reason=fail):
                    notify_combat(
                        player_id,
                        tr(
                            "fleet_report_colonize_failed_subject_coords",
                            "Colonization failed — %(coords)s",
                            locale=sender_locale,
                            coords=world_key,
                        ),
                        tr(
                            "fleet_report_colonize_failed_body",
                            "Could not establish colony at %(coords)s: %(reason)s.",
                            locale=sender_locale,
                            coords=world_key,
                            reason=fail,
                        ),
                        metadata={
                            "fleet_id": movement_id,
                            "mission_type": "colonize",
                            "reason": fail,
                        },
                        locale=sender_locale,
                        conn=conn,
                    )
                return True
            world_binding = {
                "world_key": claim_data["world_key"],
                "world_x": claim_data["world_x"],
                "world_y": claim_data["world_y"],
                "sector_x": claim_data["sector_x"],
                "sector_y": claim_data["sector_y"],
                "planet_role": claim_data["planet_role"],
                "origin_world_key": claim_data["world_key"],
            }
            report_coords = world_key

        ok_col, reason, extra = colonize_planet(
            player_id,
            name=colony_name,
            galaxy=tg,
            system=ts,
            position=tp,
            world_key=world_key or None,
            world_binding=world_binding,
            source="player",
            conn=conn,
        )
        if not ok_col:
            if world_key:
                release_world_claim(world_key, conn=conn, player_id=player_id)
            fail_reason = reason
            if fail_reason in ("max_colonies", "colony_limit_reached", "max_colonies_reached"):
                fail_reason = "expansion_admin_ceiling_reached"
            if world_key:
                if _notify_world_colonize(success=False, fail_reason=fail_reason):
                    return True
            notify_combat(
                player_id,
                tr(
                    "fleet_report_colonize_failed_subject_coords",
                    "Colonization failed — %(coords)s",
                    locale=sender_locale,
                    coords=report_coords,
                ),
                tr(
                    "fleet_report_colonize_failed_body",
                    "Could not establish colony at %(coords)s: %(reason)s.",
                    locale=sender_locale,
                    coords=report_coords,
                    reason=fail_reason,
                ),
                metadata={"fleet_id": movement_id, "mission_type": "colonize", "reason": fail_reason},
                locale=sender_locale,
                conn=conn,
            )
            return True

        if world_key and extra:
            complete_world_claim(world_key, player_id, int(extra["planet_id"]), conn=conn)

        try:
            from .activity_xp import SOURCE_COLONIZE, grant_fleet_activity_xp

            new_pid = int(extra["planet_id"]) if extra and extra.get("planet_id") else int(movement["origin_planet_id"])
            grant_fleet_activity_xp(
                player_id,
                new_pid,
                SOURCE_COLONIZE,
                movement_id,
                conn=conn,
                now=float(now),
            )
        except Exception:
            logger.exception("activity_xp colonize grant failed movement_id=%s", movement_id)

        ark_used = min(1, int(return_ships.get("seed_ark") or 0))
        if ark_used:
            return_ships["seed_ark"] = int(return_ships.get("seed_ark") or 0) - ark_used
            if return_ships["seed_ark"] <= 0:
                return_ships.pop("seed_ark", None)
            return_ships = {k: v for k, v in return_ships.items() if int(v or 0) > 0}
            cur = conn.cursor()
            if return_ships:
                cur.execute(
                    "UPDATE fleet_movements SET ships_json = ? WHERE id = ?;",
                    (_json_dumps(return_ships), movement_id),
                )
            else:
                _complete_movement(movement_id, conn=conn, now=now, from_status="returning")

        if world_key:
            _notify_world_colonize(
                success=True,
                planet_id=int(extra["planet_id"]) if extra else None,
            )
        else:
            notify_combat(
                player_id,
                tr(
                    "fleet_report_colonize_success_subject_coords",
                    "Colony established — %(coords)s",
                    locale=sender_locale,
                    coords=report_coords,
                ),
                tr(
                    "fleet_report_colonize_success_body",
                    "New colony «%(colony_name)s» founded at %(coords)s.",
                    locale=sender_locale,
                    colony_name=colony_name,
                    coords=report_coords,
                ),
                metadata={
                    "fleet_id": movement_id,
                    "mission_type": "colonize",
                    "colony_name": colony_name,
                },
                locale=sender_locale,
                conn=conn,
            )
        try:
            from .pirates.hooks import safe_record_heat

            safe_record_heat(
                conn,
                int(movement.get("target_galaxy") or 0) or None,
                "colonize",
            )
        except Exception:
            logger.exception("pirate heat colonize hook failed movement_id=%s", movement_id)
        return True

    return False


def _handle_expedition_holding_end(movement: Dict[str, Any], *, conn, now: float) -> bool:
    """Resolve expedition loot after the stay phase, notify, then start return flight."""
    from .i18n import get_player_locale, tr

    movement_id = int(movement["id"])
    player_id = int(movement["player_id"])
    sender_locale = get_player_locale(player_id, conn=conn)
    ships = movement.get("ships") or {}
    coords = movement.get("target_coords") or ""
    raw_res = movement.get("resources") or {}
    world_key = str(raw_res.get("world_key") or "").strip()
    report_coords = world_key or coords
    world_context = None
    if world_key:
        from .planet_evolution.strategic_worlds import build_strategic_world_presentation_from_key
        from .planet_evolution.world_colonization import WorldKeyError, is_expedition_world_type

        try:
            world_context = build_strategic_world_presentation_from_key(world_key)
        except WorldKeyError:
            world_context = None
    cargo_total = calculate_expedition_loot_cap(ships)
    flight_seconds_base = int(movement.get("flight_seconds") or 1)
    origin_galaxy = int(movement.get("origin_galaxy") or movement.get("galaxy") or 0) or None
    if origin_galaxy is None:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT galaxy FROM planets WHERE id = ? LIMIT 1;",
                (int(movement.get("origin_planet_id") or 0),),
            )
            grow = cur.fetchone()
            if grow and grow["galaxy"] is not None:
                origin_galaxy = int(grow["galaxy"])
        except Exception:
            origin_galaxy = None
    directive_flags: Dict[str, Any] = {}
    if origin_galaxy:
        from .galactic_directives.mechanics import get_directive_flags_for_galaxy

        directive_flags = get_directive_flags_for_galaxy(origin_galaxy, conn=conn)
    try:
        from .inventory_boosters import get_expedition_booster_flags

        directive_flags = {**directive_flags, **get_expedition_booster_flags(player_id, conn=conn)}
    except Exception:
        pass
    try:
        from .alliance import get_alliance_effect_modifiers

        alliance_mods = get_alliance_effect_modifiers(player_id, conn=conn)
        alliance_mult = float(alliance_mods.get("expedition_loot_mult") or 1.0)
        alliance_event_bonus = float(alliance_mods.get("expedition_event_bonus") or 0.0)
        if alliance_mult > 1.0:
            directive_flags["expedition_loot_mult"] = float(
                directive_flags.get("expedition_loot_mult") or 1.0
            ) * alliance_mult
        if alliance_event_bonus > 0.0:
            directive_flags["expedition_event_bonus"] = float(
                directive_flags.get("expedition_event_bonus") or 0.0
            ) + alliance_event_bonus
    except Exception:
        pass
    from .empire_page import get_empire_production_aggregate

    empire_prod = get_empire_production_aggregate(player_id, conn=conn)
    empire_daily_total = int(empire_prod.get("total_per_day") or 0)
    daily_expedition_count = get_expedition_daily_count(player_id, conn=conn, ts=now)
    daily_efficiency_mult = expedition_daily_efficiency_multiplier(daily_expedition_count)
    familiarity_status = None
    if world_key:
        try:
            from .planet_evolution.world_progress import (
                familiarity_from_count,
                get_world_progress_row,
            )

            progress_row = get_world_progress_row(player_id, world_key, conn=conn)
            count = int((progress_row or {}).get("expedition_count") or 0)
            familiarity_status, _ = familiarity_from_count(count)
        except Exception:
            familiarity_status = None
    outcome = resolve_expedition_outcome(
        movement_id,
        cargo_total=cargo_total,
        expedition_ship_count=count_expedition_ships(ships),
        flight_seconds=flight_seconds_base,
        ships=ships,
        empire_daily_total=empire_daily_total,
        world_type=str(world_context.get("world_type") or "") if world_context else None,
        directive_flags=directive_flags,
        daily_efficiency_mult=daily_efficiency_mult,
        familiarity_status=familiarity_status,
    )
    rewards = dict(outcome["rewards"])
    if world_key:
        rewards["world_key"] = world_key
    rewards["expedition_hours"] = _expedition_hours_from_movement(movement)
    record_expedition_daily_value(
        player_id,
        movement_id,
        int(outcome.get("expo_value") or 0),
        conn=conn,
        ts=now,
    )
    try:
        from .pirates.hooks import safe_record_heat

        safe_record_heat(
            conn,
            int(movement.get("target_galaxy") or 0) or None,
            "expedition",
        )
    except Exception:
        logger.exception("pirate heat expedition hook failed movement_id=%s", movement_id)
    if outcome.get("event_key") == "pirate_encounter":
        try:
            from .pirates.ambush import on_expedition_pirate_ambush

            pc = outcome.get("pirate_combat") or {}
            on_expedition_pirate_ambush(
                conn,
                galaxy_id=int(movement.get("target_galaxy") or 0) or None,
                player_id=player_id,
                planet_id=int(movement.get("origin_planet_id") or 0) or None,
                won=bool(pc.get("won")),
                movement_id=movement_id,
            )
        except Exception:
            logger.exception(
                "pirate ambush hook failed movement_id=%s", movement_id
            )
    grant_expedition_lootboxes(
        player_id,
        outcome.get("lootboxes") or [],
        movement_id=movement_id,
        conn=conn,
    )
    delay_extra = int(outcome.get("delay_extra") or 0)
    timing = _return_timing_from_now(movement, now=now, delay_seconds=delay_extra)
    return_at = timing["return_at"]
    remaining_ships = dict(outcome.get("remaining_ships") or {})
    if remaining_ships:
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("holding",),
            "returning",
            now,
            extra_sql=", return_at = ?, ships_json = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(remaining_ships), _json_dumps(rewards)),
        )
    else:
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("holding",),
            "returning",
            now,
            extra_sql=", return_at = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(rewards)),
        )
    if not claimed:
        return False
    if world_key and world_context and is_expedition_world_type(str(world_context.get("world_type") or "")):
        from .planet_evolution.world_progress import record_world_expedition_progress

        record_world_expedition_progress(player_id, world_key, conn=conn)
    body, meta = build_expedition_report(
        report_coords,
        ships,
        outcome,
        locale=sender_locale,
        world_context=world_context,
    )
    meta["fleet_id"] = movement_id
    if world_key:
        meta["world_key"] = world_key

    try:
        from .world_boss import try_discover_world_boss_from_expedition
        import random as _wb_random

        discovery = try_discover_world_boss_from_expedition(
            int(player_id),
            conn=conn,
            now=now,
            rng=_wb_random.Random(int(movement_id) * 9176 + 424242),
        )
        if discovery.get("ok"):
            meta["world_boss_discovery"] = discovery
            coords = str(discovery.get("coords") or "")
            body = (
                f"{body}\n\n"
                + tr(
                    "wb_expo_discovery_report",
                    "World Boss entdeckt bei %(coords)s — angreifbar über World Boss / Galaxie.",
                    locale=sender_locale,
                    coords=coords,
                )
            )
    except Exception:
        logger.exception("world_boss expo discovery failed movement=%s", movement_id)

    if world_context and world_context.get("name_key"):
        is_salvage = str(world_context.get("world_type") or "") == "wreckage_field"
        notify_expedition(
            player_id,
            tr(
                "fleet_report_salvage_subject_world" if is_salvage else "fleet_report_expedition_subject_world",
                "Salvage report — %(world)s" if is_salvage else "Expedition report — %(world)s",
                locale=sender_locale,
                world=tr(str(world_context["name_key"]), str(world_context["name_key"]), locale=sender_locale),
            ),
            body,
            metadata=meta,
            locale=sender_locale,
            conn=conn,
        )
    else:
        notify_expedition(
            player_id,
            tr(
                "fleet_report_expedition_subject_coords",
                "Expedition report — %(coords)s",
                locale=sender_locale,
                coords=report_coords,
            ),
            body,
            metadata=meta,
            locale=sender_locale,
            conn=conn,
        )
    try:
        from .directives.progress import emit_expedition_complete_event

        emit_expedition_complete_event(
            int(player_id),
            movement_id=movement_id,
            outcome=outcome,
            conn=conn,
            now=float(now),
        )
    except Exception:
        logger.exception(
            "imperial_directives expedition progress failed movement_id=%s",
            movement_id,
        )
    try:
        from .activity_xp import SOURCE_EXPEDITION, grant_fleet_activity_xp

        grant_fleet_activity_xp(
            player_id,
            int(movement["origin_planet_id"]),
            SOURCE_EXPEDITION,
            movement_id,
            conn=conn,
            now=float(now),
        )
    except Exception:
        logger.exception("activity_xp expedition grant failed movement_id=%s", movement_id)
    return True


def _handle_holding_end(movement: Dict[str, Any], *, conn, now: float) -> bool:
    mission = str(movement.get("mission_type") or "")
    if mission == "expedition":
        return _handle_expedition_holding_end(movement, conn=conn, now=now)
    return _start_return(movement, conn=conn, now=now)


def _handle_return(movement: Dict[str, Any], *, conn, now: float) -> bool:
    from .i18n import get_player_locale, tr

    movement_id = int(movement["id"])
    player_id = int(movement["player_id"])
    sender_locale = get_player_locale(player_id, conn=conn)
    mission = str(movement.get("mission_type") or "")
    origin_id = int(movement["origin_planet_id"])
    target_id = _safe_int(movement.get("target_planet_id"))
    ships = movement.get("ships") or {}
    resources = movement.get("resources") or {}
    coords = movement.get("target_coords") or ""
    cur = conn.cursor()
    cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
    orow = cur.fetchone()
    origin_name = str(orow["name"] if orow else "")
    target_name = ""
    if target_id:
        snapshot = _target_planet_snapshot(int(target_id), conn=conn)
        target_name = str(snapshot.get("planet_name") or "")

    if mission == "collect" and loaded_resource_total(resources) > 0:
        return_body = _format_logistics_collect_return_report(
            origin_name=origin_name,
            resources=resources,
            ships=ships,
            locale=sender_locale,
        )
        _emit_logistics_fleet_report(
            player_id,
            subject=tr(
                "fleet_logistics_collect_return_subject",
                "Zusammenzieh-Flotte zurück",
                locale=sender_locale,
            ),
            body=return_body,
            movement=movement,
            movement_id=movement_id,
            report_phase="logistics_collect_return",
            mission_type="collect",
            coords=coords,
            origin_planet_id=origin_id,
            origin_name=origin_name,
            target_planet_id=int(target_id) if target_id else None,
            target_name=target_name,
            ships=ships,
            resources=resources,
            collected=None,
            now=now,
            locale=sender_locale,
            conn=conn,
        )
    elif _movement_batch_type(movement, conn=conn) == "collect_resources":
        return_body = _format_logistics_collect_return_report(
            origin_name=origin_name,
            resources={},
            ships=ships,
            locale=sender_locale,
        )
        _emit_logistics_fleet_report(
            player_id,
            subject=tr(
                "fleet_logistics_collect_return_subject",
                "Zusammenzieh-Flotte zurück",
                locale=sender_locale,
            ),
            body=return_body,
            movement=movement,
            movement_id=movement_id,
            report_phase="logistics_collect_return",
            mission_type="collect",
            coords=coords,
            origin_planet_id=origin_id,
            origin_name=origin_name,
            target_planet_id=int(target_id) if target_id else None,
            target_name=target_name,
            ships=ships,
            resources={},
            collected=None,
            now=now,
            locale=sender_locale,
            conn=conn,
        )
    elif _movement_batch_type(movement, conn=conn) == "distribute_resources":
        return_body = _format_logistics_distribute_return_report(
            origin_name=origin_name,
            ships=ships,
            locale=sender_locale,
        )
        _emit_logistics_fleet_report(
            player_id,
            subject=tr(
                "fleet_logistics_distribute_return_subject",
                "Logistik-Flotte zurück",
                locale=sender_locale,
            ),
            body=return_body,
            movement=movement,
            movement_id=movement_id,
            report_phase="logistics_distribute_return",
            mission_type="distribute",
            coords=coords,
            origin_planet_id=origin_id,
            origin_name=origin_name,
            target_planet_id=int(target_id) if target_id else None,
            target_name=target_name,
            ships=ships,
            resources={},
            collected=None,
            now=now,
            locale=sender_locale,
            conn=conn,
        )

    if not _complete_movement(movement_id, conn=conn, now=now, from_status="returning"):
        return False
    add_planet_ships(origin_id, player_id, ships, conn=conn)
    if loaded_resource_total(resources) > 0:
        _credit_planet_resources(origin_id, resources, conn=conn)
    return True


def process_fleet_tick(
    *,
    player_id: Optional[int] = None,
    now: Optional[float] = None,
    conn=None,
    manage_transaction: Optional[bool] = None,
) -> Dict[str, Any]:
    """Process due fleet arrivals and returns. Idempotent per movement status transition.

    GC-PERF-LOCK-001: when ``manage_transaction`` is True (fleet worker / own conn),
    each due movement runs in its own short ``BEGIN IMMEDIATE`` so HTTP writers are
    not blocked for the entire due set. Callers that already hold a write TX must
    pass ``manage_transaction=False`` (nested / test paths).
    """
    own = conn is None
    if own:
        conn = db()
    if now is None:
        now = _now()

    result = {
        "processed_arrivals": 0,
        "processed_returns": 0,
        "processed_holding": 0,
        "errors": [],
    }

    if not fleet_schema_ready(conn):
        if own and conn is not None:
            conn.close()
        return result

    if manage_transaction is None:
        manage_transaction = bool(own)

    try:
        if manage_transaction:
            _process_fleet_tick_short_tx(
                conn,
                player_id=player_id,
                now=float(now),
                result=result,
            )
        else:
            if own:
                begin_write_transaction(conn)
            _process_fleet_tick_shared_tx(
                conn,
                player_id=player_id,
                now=float(now),
                result=result,
            )
            if own:
                commit(conn)
    except Exception as exc:
        if own or manage_transaction:
            try:
                rollback(conn)
            except Exception:
                pass
        result["errors"].append(str(exc))
        logger.exception("process_fleet_tick failed")
        if not manage_transaction:
            raise
    finally:
        if own and conn is not None:
            conn.close()

    return result


def _fleet_due_ids(
    conn,
    *,
    status: str,
    time_col: str,
    now: float,
    player_id: Optional[int],
) -> List[int]:
    params: List[Any] = [str(status), float(now)]
    player_filter = ""
    if player_id is not None:
        player_filter = " AND player_id = ?"
        params.append(int(player_id))
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id FROM fleet_movements
        WHERE status = ? AND {time_col} <= ?{player_filter}
        ORDER BY {time_col} ASC, id ASC;
        """,
        params,
    )
    return [int(r["id"]) for r in cur.fetchall()]


def _load_movement_row(conn, movement_id: int) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT * FROM fleet_movements WHERE id = ? LIMIT 1;", (int(movement_id),))
    row = cur.fetchone()
    return _row_to_movement(row) if row else None


def _process_fleet_tick_shared_tx(
    conn,
    *,
    player_id: Optional[int],
    now: float,
    result: Dict[str, Any],
) -> None:
    """Legacy path: all due work on the caller's open write transaction."""
    cur = conn.cursor()
    params: List[Any] = [now]
    player_filter = ""
    if player_id is not None:
        player_filter = " AND player_id = ?"
        params.append(int(player_id))

    cur.execute(
        f"""
        SELECT * FROM fleet_movements
        WHERE status = 'outbound' AND arrival_at <= ?{player_filter}
        ORDER BY arrival_at ASC, id ASC;
        """,
        params,
    )
    for row in cur.fetchall():
        mv = _row_to_movement(row)
        try:
            if _handle_arrival(mv, conn=conn, now=now):
                result["processed_arrivals"] += 1
        except Exception as exc:
            result["errors"].append(f"arrival fleet={mv['id']}: {exc}")
            logger.exception("fleet arrival failed fleet=%s", mv["id"])
            if mv.get("mission_type") in ("attack", "expedition"):
                try:
                    _fail_outbound_movement(conn, int(mv["id"]), now)
                except Exception:
                    logger.exception(
                        "failed to mark %s movement failed fleet=%s",
                        mv.get("mission_type"),
                        mv["id"],
                    )

    hold_params: List[Any] = [now]
    if player_id is not None:
        hold_params.append(int(player_id))
    cur.execute(
        f"""
        SELECT * FROM fleet_movements
        WHERE status = 'holding' AND holding_until <= ?{player_filter}
        ORDER BY holding_until ASC, id ASC;
        """,
        hold_params,
    )
    for row in cur.fetchall():
        mv = _row_to_movement(row)
        try:
            if _handle_holding_end(mv, conn=conn, now=now):
                result["processed_holding"] += 1
        except Exception as exc:
            result["errors"].append(f"holding fleet={mv['id']}: {exc}")
            logger.exception("fleet holding end failed fleet=%s", mv["id"])

    ret_params: List[Any] = [now]
    if player_id is not None:
        ret_params.append(int(player_id))
    cur.execute(
        f"""
        SELECT * FROM fleet_movements
        WHERE status = 'returning' AND return_at <= ?{player_filter}
        ORDER BY return_at ASC, id ASC;
        """,
        ret_params,
    )
    for row in cur.fetchall():
        mv = _row_to_movement(row)
        try:
            if _handle_return(mv, conn=conn, now=now):
                result["processed_returns"] += 1
        except Exception as exc:
            result["errors"].append(f"return fleet={mv['id']}: {exc}")
            logger.exception("fleet return failed fleet=%s", mv["id"])
            try:
                _fail_returning_movement(conn, int(mv["id"]), now)
            except Exception:
                logger.exception(
                    "failed to mark returning movement failed fleet=%s",
                    mv["id"],
                )


def _run_one_movement_short_tx(
    conn,
    *,
    movement_id: int,
    expect_status: str,
    handler,
    now: float,
    fail_fn=None,
    fail_missions: Optional[Set[str]] = None,
) -> Tuple[bool, Optional[str]]:
    """BEGIN → handle one movement → COMMIT. Returns (handled, error_message)."""
    mid = int(movement_id)
    try:
        begin_write_transaction(conn)
        mv = _load_movement_row(conn, mid)
        if not mv or str(mv.get("status") or "") != expect_status:
            rollback(conn)
            return False, None
        try:
            ok = bool(handler(mv, conn=conn, now=now))
            commit(conn)
            return ok, None
        except Exception as exc:
            logger.exception("fleet %s failed fleet=%s", expect_status, mid)
            try:
                rollback(conn)
            except Exception:
                pass
            if fail_fn is not None and (
                not fail_missions or str(mv.get("mission_type") or "") in fail_missions
            ):
                try:
                    begin_write_transaction(conn)
                    fail_fn(conn, mid, now)
                    commit(conn)
                except Exception:
                    try:
                        rollback(conn)
                    except Exception:
                        pass
                    logger.exception(
                        "failed to mark %s movement failed fleet=%s",
                        expect_status,
                        mid,
                    )
            return False, f"{expect_status} fleet={mid}: {exc}"
    except Exception as exc:
        try:
            rollback(conn)
        except Exception:
            pass
        if is_sqlite_lock_error(exc):
            logger.warning("fleet short-tx locked status=%s fleet=%s", expect_status, mid)
            return False, f"{expect_status} fleet={mid}: database is locked"
        logger.exception("fleet short-tx failed status=%s fleet=%s", expect_status, mid)
        return False, f"{expect_status} fleet={mid}: {exc}"


def _process_fleet_tick_short_tx(
    conn,
    *,
    player_id: Optional[int],
    now: float,
    result: Dict[str, Any],
) -> None:
    """GC-PERF-LOCK-001: one short write TX per due movement."""
    # Snapshot IDs without holding a write lock across the whole set.
    outbound_ids = _fleet_due_ids(
        conn, status="outbound", time_col="arrival_at", now=now, player_id=player_id
    )
    holding_ids = _fleet_due_ids(
        conn, status="holding", time_col="holding_until", now=now, player_id=player_id
    )
    returning_ids = _fleet_due_ids(
        conn, status="returning", time_col="return_at", now=now, player_id=player_id
    )

    for mid in outbound_ids:
        handled, err = _run_one_movement_short_tx(
            conn,
            movement_id=mid,
            expect_status="outbound",
            handler=_handle_arrival,
            now=now,
            fail_fn=_fail_outbound_movement,
            fail_missions={"attack", "expedition"},
        )
        if handled:
            result["processed_arrivals"] += 1
        if err:
            result["errors"].append(err)

    for mid in holding_ids:
        handled, err = _run_one_movement_short_tx(
            conn,
            movement_id=mid,
            expect_status="holding",
            handler=_handle_holding_end,
            now=now,
        )
        if handled:
            result["processed_holding"] += 1
        if err:
            result["errors"].append(err)

    for mid in returning_ids:
        handled, err = _run_one_movement_short_tx(
            conn,
            movement_id=mid,
            expect_status="returning",
            handler=_handle_return,
            now=now,
            fail_fn=_fail_returning_movement,
        )
        if handled:
            result["processed_returns"] += 1
        if err:
            result["errors"].append(err)


def mass_expedition_available_slots(player_id: int, *, conn) -> int:
    """Free fleet slots mass expedition may use — always leaves MASS_EXPEDITION_SLOT_RESERVE free."""
    slots = get_fleet_slot_status(int(player_id), conn=conn)
    free = int(slots.get("free") or 0)
    return max(0, free - int(MASS_EXPEDITION_SLOT_RESERVE))


def compute_mass_expedition_slot_split(
    ships: Mapping[str, int],
    available_slots: int,
) -> Tuple[Dict[str, int], Dict[str, int], int]:
    """GC-981 — floor(selected / slots) per hull; leftovers stay on planet."""
    slots = max(0, int(available_slots or 0))
    normalized = normalize_ships(ships)
    if slots <= 0 or not normalized:
        return {}, dict(normalized), 0

    per_slot: Dict[str, int] = {}
    leftover: Dict[str, int] = {}
    for key, total in normalized.items():
        qty = int(total)
        if qty <= 0:
            continue
        per = qty // slots
        rem = qty % slots
        if per > 0:
            per_slot[key] = per
        if rem > 0:
            leftover[key] = rem
    return per_slot, leftover, slots


def validate_mass_expedition_per_slot_fleet(
    per_slot_ships: Mapping[str, int],
) -> Tuple[bool, str]:
    """Each expedition fleet must include at least one expedition-role hull."""
    from .expedition_events import count_expedition_ships

    if sum(int(v) for v in per_slot_ships.values()) <= 0:
        return False, "mass_expo_split_too_small"
    if int(count_expedition_ships(per_slot_ships)) <= 0:
        return False, "mass_expo_no_expedition_ships"
    return _mission_allowed("expedition", per_slot_ships, {})


def preview_mass_expedition_slot_split(
    *,
    player_id: int,
    origin_planet_id: int,
    ships: Mapping[str, int],
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """GC-981 — authoritative split preview for mass expedition UX."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None

        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(origin_planet_id), int(player_id)),
        )
        if not cur.fetchone():
            return False, "origin_not_found", None

        slots = get_fleet_slot_status(int(player_id), conn=conn)
        free_slots = int(slots.get("free") or 0)
        usable_slots = mass_expedition_available_slots(int(player_id), conn=conn)
        normalized = normalize_ships(ships)
        meta: Dict[str, Any] = {
            "free_slots": free_slots,
            "reserved_slots": int(MASS_EXPEDITION_SLOT_RESERVE),
            "usable_slots": usable_slots,
            "selected_ships": normalized,
            "per_fleet_ships": {},
            "leftover_ships": {},
            "started_count": 0,
            "expedition_daily": expedition_daily_status(int(player_id), conn=conn),
        }
        if free_slots <= 0:
            return False, "fleet_slots_full", meta
        if usable_slots <= 0:
            return False, "mass_expo_slots_reserved", meta
        if not normalized:
            return False, "no_ships", meta

        available = get_planet_ships(int(origin_planet_id), conn=conn)
        for key, need in normalized.items():
            if int(available.get(key, 0)) < int(need):
                return False, "not_enough_ships", meta

        per_slot, leftover, slot_count = compute_mass_expedition_slot_split(
            normalized, usable_slots
        )
        meta["per_fleet_ships"] = per_slot
        meta["leftover_ships"] = leftover
        meta["started_count"] = slot_count

        ok_fleet, fleet_reason = validate_mass_expedition_per_slot_fleet(per_slot)
        if not ok_fleet:
            return False, fleet_reason, meta

        # Fuel / send gates for one wave — keeps Start disabled when send would soft-fail.
        cur.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(origin_planet_id), int(player_id)),
        )
        origin_row = cur.fetchone()
        if origin_row:
            origin_planet = dict(origin_row)
            tg, ts, _ = _origin_coords(origin_planet)
            ok_send, send_reason, _send_ctx = validate_fleet_send(
                player_id=int(player_id),
                origin_planet_id=int(origin_planet_id),
                target_galaxy=int(tg),
                target_system=int(ts),
                target_position=int(EXPEDITION_POSITION),
                mission_type="expedition",
                ships=per_slot,
                resources={},
                speed_percent=100,
                conn=conn,
            )
            if not ok_send:
                meta["started_count"] = 0
                return False, send_reason or "send_failed", meta

        return True, "", meta
    finally:
        if own and conn is not None:
            conn.close()


def mass_expedition_from_ships(
    *,
    player_id: int,
    origin_planet_id: int,
    ships: Mapping[str, int],
    speed_percent: int = 100,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """GC-981 — split selected ships evenly across free expedition slots."""
    own = conn is None
    if own:
        conn = db()
    try:
        ok_prev, reason, preview = preview_mass_expedition_slot_split(
            player_id=player_id,
            origin_planet_id=origin_planet_id,
            ships=ships,
            conn=conn,
        )
        if not ok_prev:
            return False, reason, preview

        per_slot = dict(preview.get("per_fleet_ships") or {})
        leftover = dict(preview.get("leftover_ships") or {})
        slot_count = int(preview.get("started_count") or 0)
        pct = int(speed_percent)
        if pct < 10 or pct > 100:
            pct = 100

        slots = get_fleet_slot_status(int(player_id), conn=conn)
        max_start = mass_expedition_available_slots(int(player_id), conn=conn)

        if own:
            begin_write_transaction(conn)

        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO fleet_batches (player_id, batch_type, label, status, total_fleets, created_at, updated_at)
            VALUES (?, 'mass_expedition', ?, 'running', ?, ?, ?);
            """,
            (
                int(player_id),
                f"Mass expedition x{slot_count}",
                slot_count,
                now,
                now,
            ),
        )
        batch_id = int(cur.lastrowid)

        started: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        cur.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(origin_planet_id), int(player_id)),
        )
        origin_row = cur.fetchone()
        if not origin_row:
            if own:
                rollback(conn)
            return False, "origin_not_found", None
        origin_planet = dict(origin_row)
        origin_coords = _origin_coords(origin_planet)
        tg, ts, _ = origin_coords
        target_position = EXPEDITION_POSITION

        for wave in range(slot_count):
            if len(started) >= max_start:
                skipped.append({"wave": wave + 1, "reason": "fleet_slots_full"})
                continue

            available = get_planet_ships(int(origin_planet_id), conn=conn)
            can_send = True
            for sk, need in per_slot.items():
                if int(available.get(sk, 0)) < int(need):
                    can_send = False
                    break
            if not can_send:
                skipped.append({"wave": wave + 1, "reason": "not_enough_ships"})
                continue

            ok, send_reason, payload = send_fleet(
                player_id=player_id,
                origin_planet_id=origin_planet_id,
                target_galaxy=tg,
                target_system=ts,
                target_position=target_position,
                mission_type="expedition",
                ships=per_slot,
                resources={},
                speed_percent=pct,
                batch_id=batch_id,
                departure_at=int(now) + len(started) * MASS_EXPEDITION_STAGGER_SECONDS,
                conn=conn,
            )
            if ok and payload:
                started.append({"wave": wave + 1, "fleet_id": payload["fleet"]["id"]})
            else:
                skipped.append({"wave": wave + 1, "reason": send_reason or "send_failed"})

        if not started:
            # Mirror logistics: never soft-succeed with zero fleets launched.
            if own:
                rollback(conn)
            fail_reason = (
                str((skipped[0] or {}).get("reason") or "")
                if skipped
                else "send_failed"
            ) or "send_failed"
            return False, fail_reason, {
                "started": [],
                "skipped": skipped,
                "per_fleet_ships": per_slot,
                "leftover_ships": leftover,
                "started_count": 0,
                "active_slots": get_fleet_slot_status(player_id, conn=conn),
            }

        conn.execute(
            "UPDATE fleet_batches SET status = ?, total_fleets = ?, updated_at = ? WHERE id = ?;",
            ("completed", len(started), now, batch_id),
        )

        if own:
            commit(conn)

        cur.execute("SELECT * FROM fleet_batches WHERE id = ?;", (batch_id,))
        batch_row = dict(cur.fetchone())

        return True, "", {
            "batch": {
                "id": batch_id,
                "batch_type": batch_row["batch_type"],
                "status": batch_row["status"],
                "total_fleets": len(started),
                "label": batch_row["label"],
            },
            "started": started,
            "skipped": skipped,
            "per_fleet_ships": per_slot,
            "leftover_ships": leftover,
            "started_count": len(started),
            "active_slots": get_fleet_slot_status(player_id, conn=conn),
        }
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def mass_expedition(
    *,
    player_id: int,
    origin_planet_id: int,
    preset_id: int,
    waves: int,
    target_slots: int | None = None,
    speed_percent: int | None = None,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        preset = get_preset(int(preset_id), int(player_id), conn=conn)
        if not preset:
            return False, "preset_not_found", None
        ships = preset.get("ships") or {}
        if not ships:
            return False, "preset_no_ships", None

        pct = int(speed_percent if speed_percent is not None else preset.get("speed_percent") or 100)
        wave_count = max(1, int(waves))
        max_start = mass_expedition_available_slots(int(player_id), conn=conn)
        if max_start <= 0:
            return False, "mass_expo_slots_reserved", None
        if target_slots is not None:
            max_start = min(max_start, max(0, int(target_slots)))

        if own:
            begin_write_transaction(conn)

        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO fleet_batches (player_id, batch_type, label, status, total_fleets, created_at, updated_at)
            VALUES (?, 'mass_expedition', ?, 'running', ?, ?, ?);
            """,
            (int(player_id), f"Mass expedition x{wave_count}", wave_count, now, now),
        )
        batch_id = int(cur.lastrowid)

        started: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        cur.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(origin_planet_id), int(player_id)),
        )
        origin_row = cur.fetchone()
        if not origin_row:
            if own:
                rollback(conn)
            return False, "origin_not_found", None
        origin_planet = dict(origin_row)
        origin_coords = _origin_coords(origin_planet)
        tg, ts, _ = origin_coords
        target_position = EXPEDITION_POSITION

        for wave in range(wave_count):
            if len(started) >= max_start:
                skipped.append({"wave": wave + 1, "reason": "fleet_slots_full"})
                continue

            available = get_planet_ships(int(origin_planet_id), conn=conn)
            can_send = True
            for sk, need in ships.items():
                if int(available.get(sk, 0)) < int(need):
                    can_send = False
                    break
            if not can_send:
                skipped.append({"wave": wave + 1, "reason": "not_enough_ships"})
                continue

            ok, reason, payload = send_fleet(
                player_id=player_id,
                origin_planet_id=origin_planet_id,
                target_galaxy=tg,
                target_system=ts,
                target_position=target_position,
                mission_type="expedition",
                ships=ships,
                resources={},
                speed_percent=pct,
                preset_id=int(preset_id),
                batch_id=batch_id,
                departure_at=int(now) + len(started) * MASS_EXPEDITION_STAGGER_SECONDS,
                conn=conn,
            )
            if ok and payload:
                started.append({"wave": wave + 1, "fleet_id": payload["fleet"]["id"]})
            else:
                skipped.append({"wave": wave + 1, "reason": reason or "send_failed"})

        if not started:
            if own:
                rollback(conn)
            fail_reason = (
                str((skipped[0] or {}).get("reason") or "")
                if skipped
                else "send_failed"
            ) or "send_failed"
            return False, fail_reason, {
                "started": [],
                "skipped": skipped,
                "started_count": 0,
                "active_slots": get_fleet_slot_status(player_id, conn=conn),
            }

        conn.execute(
            "UPDATE fleet_batches SET status = ?, total_fleets = ?, updated_at = ? WHERE id = ?;",
            ("completed", len(started), now, batch_id),
        )

        if own:
            commit(conn)

        cur.execute("SELECT * FROM fleet_batches WHERE id = ?;", (batch_id,))
        batch_row = dict(cur.fetchone())

        return True, "", {
            "batch": {
                "id": batch_id,
                "batch_type": batch_row["batch_type"],
                "status": batch_row["status"],
                "total_fleets": len(started),
                "label": batch_row["label"],
            },
            "started": started,
            "skipped": skipped,
            "active_slots": get_fleet_slot_status(player_id, conn=conn),
        }
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


class DistributeRouteLeg(TypedDict, total=False):
    planet_id: int
    galaxy: int
    system: int
    position: int
    ships: Dict[str, int]
    resources: Dict[str, int]
    resources_requested: Dict[str, int]



def _parse_target_resources_map(
    raw: Any,
    *,
    allowed_planet_ids: Set[int],
) -> Optional[Dict[int, Dict[str, int]]]:
    """Explicit per-target cargo from API ``target_resources`` (custom distribute mode)."""
    if raw is None:
        return None
    out: Dict[int, Dict[str, int]] = {}
    if isinstance(raw, Mapping):
        items = raw.items()
    elif isinstance(raw, list):
        items = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            pid = int(entry.get("planet_id") or entry.get("target_planet_id") or 0)
            res = entry.get("resources") if isinstance(entry.get("resources"), Mapping) else entry
            items.append((pid, res))
    else:
        return None
    for key, value in items:
        try:
            pid = int(key)
        except (TypeError, ValueError):
            continue
        if pid not in allowed_planet_ids:
            continue
        out[pid] = calculate_loaded_resources(value if isinstance(value, Mapping) else {})
    return out or None


def build_distribute_route(
    *,
    origin_planet_id: int,
    target_planet_ids: Sequence[int],
    planet_rows_by_id: Mapping[int, Mapping[str, Any]],
    ships: Mapping[str, int],
    resources: Mapping[str, Any] | None,
    resources_mode: str,
    target_resources: Any = None,
    free_fleet_slots: int,
    player_id: int,
    conn,
    for_preview: bool = False,
    clamp_to_cargo: bool = False,
    skip_invalid_planets: bool = False,
) -> Tuple[bool, str, Optional[List[DistributeRouteLeg]], Optional[Dict[str, int]]]:
    """Validate distribute targets, compute per-leg cargo/ships, enforce slots and cargo caps."""
    origin = int(origin_planet_id or 0)
    targets = normalize_collect_source_planet_ids(origin, target_planet_ids)
    if not targets:
        return False, "no_planets", None, None

    ships_n = normalize_ships(ships)
    if not ships_n:
        return False, "no_ships", None, None
    ok_cargo, cargo_reason = fleet_ships_are_cargo_only(ships_n)
    if not ok_cargo:
        return False, cargo_reason, None, None

    entries: List[Dict[str, Any]] = []
    for pid in targets:
        ok, reason, coords = validate_collect_source_planet(
            planet_rows_by_id.get(int(pid)),
            player_id=int(player_id),
        )
        if not ok or not coords:
            if skip_invalid_planets:
                continue
            return False, reason or "planet_not_found", None, None
        entries.append(
            {
                "planet_id": int(pid),
                "galaxy": coords["galaxy"],
                "system": coords["system"],
                "position": coords["position"],
            }
        )

    if not entries:
        return False, "no_planets", None, None

    entries.sort(
        key=lambda e: collect_route_sort_key(
            galaxy=int(e["galaxy"]),
            system=int(e["system"]),
            position=int(e["position"]),
            planet_id=int(e["planet_id"]),
        )
    )

    # Logistics uses ALL free slots (no mass-expo reserve). Cap targets before
    # equal-split so the full cargo goes to the legs that actually launch.
    slots_free = int(free_fleet_slots)
    if slots_free <= 0:
        return False, "fleet_slots_full", None, None
    if len(entries) > slots_free:
        entries = entries[:slots_free]

    mode = str(resources_mode or "").strip().lower()
    allowed_ids = {int(e["planet_id"]) for e in entries}
    per_target: Dict[int, Dict[str, int]] = {}

    if mode == "custom":
        parsed = _parse_target_resources_map(target_resources, allowed_planet_ids=allowed_ids)
        if not parsed:
            return False, "invalid_target_resources", None, None
        per_target = parsed
    elif mode == "equal":
        requested = calculate_loaded_resources(resources)
        requested_total = loaded_resource_total(requested)
        if requested_total <= 0:
            if not for_preview:
                return False, "no_resources", None, None
            for entry in entries:
                per_target[int(entry["planet_id"])] = {
                    "metal": 0,
                    "crystal": 0,
                    "fuel_cells": 0,
                }
        else:
            shares = split_resources_evenly(requested, len(entries))
            for entry, share in zip(entries, shares):
                per_target[int(entry["planet_id"])] = share
    else:
        return False, "invalid_resources_mode", None, None

    legs: List[DistributeRouteLeg] = []
    for entry in entries:
        pid = int(entry["planet_id"])
        if mode == "custom" and pid not in per_target:
            continue
        share = per_target.get(pid) or {"metal": 0, "crystal": 0, "fuel_cells": 0}
        share_loaded = calculate_loaded_resources(share)
        if loaded_resource_total(share_loaded) <= 0 and not for_preview:
            continue
        leg: DistributeRouteLeg = {
            "planet_id": pid,
            "galaxy": int(entry["galaxy"]),
            "system": int(entry["system"]),
            "position": int(entry["position"]),
            "ships": {},
            "resources": share_loaded,
        }
        if for_preview:
            leg["resources_requested"] = share_loaded
        legs.append(leg)

    if not legs:
        return False, "no_deliverable_resources", None, None

    if clamp_to_cargo:
        total_units = sum(int(v) for v in ships_n.values())
        if total_units > 0 and len(legs) > total_units:
            legs = legs[:total_units]

    ship_allocs = split_ships_across_targets(ships_n, len(legs))
    kept: List[DistributeRouteLeg] = []
    for leg, alloc in zip(legs, ship_allocs):
        if not alloc or calculate_total_cargo(alloc) <= 0:
            if clamp_to_cargo:
                continue
            return False, "not_enough_ships", None, None
        cargo = (
            leg.get("resources_requested") or leg["resources"]
            if for_preview
            else leg["resources"]
        )
        cargo_cap = calculate_total_cargo(alloc)
        if loaded_resource_total(cargo) > cargo_cap:
            if clamp_to_cargo:
                from .resources import load_resources_up_to_cargo

                clamped = load_resources_up_to_cargo(cargo, cargo_cap)
                leg["resources"] = clamped
                if for_preview and "resources_requested" not in leg:
                    leg["resources_requested"] = calculate_loaded_resources(cargo)
            elif not for_preview:
                return False, "not_enough_cargo", None, None
        leg["ships"] = dict(alloc)
        if loaded_resource_total(leg["resources"]) <= 0 and not for_preview:
            continue
        kept.append(leg)

    legs = kept
    if not legs:
        return False, "no_deliverable_resources", None, None

    delivered_total = _sum_loaded_resources([leg["resources"] for leg in legs])
    return True, "", legs, delivered_total


def _sum_loaded_resources(items: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    total = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    for item in items:
        loaded = calculate_loaded_resources(item)
        total["metal"] += loaded["metal"]
        total["crystal"] += loaded["crystal"]
        total["fuel_cells"] += loaded["fuel_cells"]
    return calculate_loaded_resources(total)


def validate_logistics_planets(
    player_id: int,
    target_planet_ids: Sequence[int],
    source_planet_ids: Sequence[int] | None = None,
    *,
    conn=None,
) -> Tuple[bool, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        all_ids = set(int(x) for x in (target_planet_ids or []))
        if source_planet_ids:
            all_ids.update(int(x) for x in source_planet_ids)
        if not all_ids:
            return False, "no_planets"
        for pid in all_ids:
            if not _planet_owned_by(player_id, pid, conn=conn):
                return False, "planet_not_owned"
        return True, ""
    finally:
        if own and conn is not None:
            conn.close()


def _load_planet_rows_for_collect(
    planet_ids: Sequence[int],
    *,
    conn,
) -> Dict[int, Dict[str, Any]]:
    """
    Load planets by id and tick production (shared owner for Preview + Collect/Distribute).

    Returns ticked planet dicts so route planning matches accrued stock, not stale
    ``last_update`` balances. Caller should hold a write transaction when send/debit
    follows on the same connection.
    """
    from .resources import update_planet_resources

    ids = sorted({int(x) for x in planet_ids if int(x) > 0})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    cur = conn.cursor()
    cur.execute(
        f"SELECT * FROM planets WHERE id IN ({placeholders});",
        ids,
    )
    out: Dict[int, Dict[str, Any]] = {}
    for row in cur.fetchall():
        planet_live, *_rest = update_planet_resources(
            dict(row),
            conn=conn,
            skip_queue_finish=True,
        )
        out[int(planet_live["id"])] = dict(planet_live)
    return out


def validate_logistics_manual_ships(
    ships: Mapping[str, int],
) -> Tuple[bool, str, Dict[str, int]]:
    """Cargo-only ship selection for logistics collect/distribute (GC-533)."""
    ships_n = normalize_ships(ships)
    if not ships_n:
        return False, "no_ships", {}
    ok_cargo, cargo_reason = fleet_ships_are_cargo_only(ships_n)
    if not ok_cargo:
        return False, cargo_reason or "non_cargo_ships", {}
    return True, "", ships_n


def collect_resources(
    *,
    player_id: int,
    target_planet_id: int,
    source_planet_ids: Sequence[int],
    ships: Mapping[str, int],
    resources_mode: str = "all",
    resources: Mapping[str, Any] | None = None,
    ships_selection_mode: str = "manual",
    preset_id: int | None = None,
    speed_percent: int = 100,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Multi-colony collect: each source sends transport to hub under one batch."""
    hub_id = int(target_planet_id or 0)
    if hub_id <= 0:
        return False, "origin_not_found", None

    mode = str(ships_selection_mode or "").strip().lower() or "manual"
    if mode == "preset":
        return False, "invalid_ships_selection_mode", None
    if mode not in ("manual", "auto_cargo"):
        return False, "invalid_ships_selection_mode", None

    if str(resources_mode or "").strip().lower() != "all":
        return False, "invalid_resources_mode", None

    pct = int(speed_percent)
    if pct < 10 or pct > 100:
        return False, "invalid_speed_percent", None

    source_ids = normalize_collect_source_planet_ids(hub_id, source_planet_ids)
    if not source_ids:
        return False, "no_planets", None

    manual_ships: Dict[str, int] = {}
    if mode == "manual":
        ok_ships, ship_reason, manual_ships = validate_logistics_manual_ships(ships)
        if not ok_ships:
            return False, ship_reason, None

    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None

        # Tick source stocks inside the write txn so send_fleet re-reads accrued balances.
        if own:
            begin_write_transaction(conn)

        planet_rows = _load_planet_rows_for_collect([hub_id, *source_ids], conn=conn)
        hub_row = planet_rows.get(hub_id)
        if hub_row is None or int(hub_row.get("player_id") or 0) != int(player_id):
            if own:
                rollback(conn)
            return False, "origin_not_found", None

        ships_stock_by_source: Dict[int, Dict[str, int]] = {}
        for sid in source_ids:
            ships_stock_by_source[int(sid)] = get_planet_ships(int(sid), conn=conn)

        slots = get_fleet_slot_status(player_id, conn=conn)
        skip_empty = mode == "auto_cargo"
        ok_route, route_reason, legs = build_collect_route(
            origin_planet_id=hub_id,
            source_planet_ids=source_ids,
            planet_rows_by_id=planet_rows,
            ships_stock_by_source=ships_stock_by_source,
            free_fleet_slots=int(slots["free"]),
            player_id=int(player_id),
            ships_selection_mode=mode,
            manual_ships=manual_ships if mode == "manual" else None,
            speed_percent=pct,
            skip_empty_ship_legs=skip_empty,
            skip_invalid_planets=skip_empty,
        )
        if not ok_route or not legs:
            if own:
                rollback(conn)
            return False, route_reason or "no_planets", None

        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO fleet_batches (player_id, batch_type, label, status, total_fleets, created_at, updated_at)
            VALUES (?, 'collect_resources', ?, 'running', ?, ?, ?);
            """,
            (
                int(player_id),
                f"Collect resources x{len(legs)}",
                len(legs),
                now,
                now,
            ),
        )
        batch_id = int(cur.lastrowid)

        started: List[Dict[str, Any]] = []
        send_skipped: List[Dict[str, Any]] = []
        ships_used: Dict[str, int] = {}
        for leg in legs:
            ok_send, send_reason, payload = send_fleet(
                player_id=player_id,
                origin_planet_id=int(leg["origin_planet_id"]),
                target_galaxy=int(leg["galaxy"]),
                target_system=int(leg["system"]),
                target_position=int(leg["position"]),
                mission_type="transport",
                ships=leg["ships"],
                resources=leg["resources"],
                speed_percent=pct,
                preset_id=preset_id,
                batch_id=batch_id,
                conn=conn,
            )
            if not ok_send or not payload:
                if mode == "auto_cargo":
                    send_skipped.append(
                        {
                            "planet_id": int(leg["planet_id"]),
                            "reason": send_reason or "send_failed",
                        }
                    )
                    continue
                if own:
                    rollback(conn)
                return False, send_reason or "send_failed", None
            started.append(
                {
                    "source_planet_id": int(leg["planet_id"]),
                    "fleet_id": int(payload["fleet"]["id"]),
                }
            )
            for sk, qty in (leg["ships"] or {}).items():
                ships_used[str(sk)] = int(ships_used.get(str(sk), 0)) + int(qty)

        if not started:
            if own:
                rollback(conn)
            return False, (send_skipped[0]["reason"] if send_skipped else route_reason) or "send_failed", None

        batch_status = "completed"
        conn.execute(
            "UPDATE fleet_batches SET status = ?, total_fleets = ?, updated_at = ? WHERE id = ?;",
            (batch_status, len(started), now, batch_id),
        )

        if own:
            commit(conn)

        cur.execute("SELECT * FROM fleet_batches WHERE id = ?;", (batch_id,))
        batch_row = dict(cur.fetchone())

        launched_ids = {int(item["source_planet_id"]) for item in started}
        skipped = [int(sid) for sid in source_ids if int(sid) not in launched_ids]

        from .fleet_calc import planet_resource_stock

        fresh_rows = _load_planet_rows_for_collect([hub_id, *source_ids], conn=conn)
        colony_resources = {
            int(pid): planet_resource_stock(row) for pid, row in fresh_rows.items()
        }

        return True, "", {
            "batch": {
                "id": batch_id,
                "batch_type": batch_row["batch_type"],
                "status": batch_row["status"],
                "total_fleets": len(started),
                "label": batch_row["label"],
            },
            "started": started,
            "route": [
                {
                    "planet_id": int(leg["planet_id"]),
                    "origin_planet_id": int(leg["origin_planet_id"]),
                    "galaxy": int(leg["galaxy"]),
                    "system": int(leg["system"]),
                    "position": int(leg["position"]),
                    "ships": dict(leg["ships"]),
                    "resources": dict(leg["resources"]),
                }
                for leg in legs
                if int(leg["planet_id"]) in launched_ids
            ],
            "colony_resources": colony_resources,
            "skipped": skipped,
            "send_skipped": send_skipped,
            "ships_used": ships_used,
            "ships_selection_mode": mode,
            "active_slots": get_fleet_slot_status(player_id, conn=conn),
        }
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def distribute_resources(
    *,
    player_id: int,
    origin_planet_id: int,
    target_planet_ids: Sequence[int],
    ships: Mapping[str, int],
    resources_mode: str = "equal",
    resources: Mapping[str, Any] | None = None,
    target_resources: Any = None,
    ships_selection_mode: str = "manual",
    preset_id: int | None = None,
    speed_percent: int = 100,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Multi-colony distribute: hub origin, N× transport under one batch (GC-528)."""
    hub_id = int(origin_planet_id or 0)
    if hub_id <= 0:
        return False, "origin_not_found", None

    sel_mode = str(ships_selection_mode or "").strip().lower() or "manual"
    if sel_mode == "preset":
        return False, "invalid_ships_selection_mode", None
    if sel_mode not in ("manual", "auto_cargo"):
        return False, "invalid_ships_selection_mode", None

    res_mode = str(resources_mode or "").strip().lower()
    if res_mode not in ("equal", "custom"):
        return False, "invalid_resources_mode", None
    if res_mode == "equal" and loaded_resource_total(calculate_loaded_resources(resources)) <= 0:
        return False, "no_resources", None

    pct = int(speed_percent)
    if pct < 10 or pct > 100:
        return False, "invalid_speed_percent", None

    target_ids = normalize_collect_source_planet_ids(hub_id, target_planet_ids)
    if not target_ids:
        return False, "no_planets", None

    ships_n: Dict[str, int] = {}
    if sel_mode == "manual":
        ok_ships, ship_reason, ships_n = validate_logistics_manual_ships(ships)
        if not ok_ships:
            return False, ship_reason, None

    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None

        # Tick hub/target stocks inside the write txn so send_fleet sees accrued balances.
        if own:
            begin_write_transaction(conn)

        planet_rows = _load_planet_rows_for_collect([hub_id, *target_ids], conn=conn)
        hub_row = planet_rows.get(hub_id)
        if hub_row is None or int(hub_row.get("player_id") or 0) != int(player_id):
            if own:
                rollback(conn)
            return False, "origin_not_found", None

        if sel_mode == "auto_cargo":
            if res_mode == "equal":
                cargo_needed = loaded_resource_total(calculate_loaded_resources(resources))
            else:
                cargo_needed = 0
                parsed = target_resources or {}
                if isinstance(parsed, Mapping):
                    for raw in parsed.values():
                        cargo_needed += loaded_resource_total(calculate_loaded_resources(raw))
            available_stock = get_planet_ships(hub_id, conn=conn)
            slots = get_fleet_slot_status(player_id, conn=conn)
            # Use every free slot — never apply MASS_EXPEDITION_SLOT_RESERVE here.
            launchable = min(len(target_ids), max(0, int(slots["free"])))
            ships_n = allocate_auto_cargo_ships_for_targets(
                available_stock,
                cargo_needed,
                max(1, launchable),
            )
            if not ships_n:
                if own:
                    rollback(conn)
                return False, "no_ships", None
        else:
            slots = get_fleet_slot_status(player_id, conn=conn)

        ok_route, route_reason, legs, delivered_total = build_distribute_route(
            origin_planet_id=hub_id,
            target_planet_ids=target_ids,
            planet_rows_by_id=planet_rows,
            ships=ships_n,
            resources=resources,
            resources_mode=res_mode,
            target_resources=target_resources,
            free_fleet_slots=int(slots["free"]),
            player_id=int(player_id),
            conn=conn,
            clamp_to_cargo=(sel_mode == "auto_cargo"),
            skip_invalid_planets=(sel_mode == "auto_cargo"),
        )
        if not ok_route or not legs or not delivered_total:
            if own:
                rollback(conn)
            return False, route_reason or "no_deliverable_resources", None

        cur = conn.cursor()
        lock_planet_for_update(conn, hub_id)
        cur.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
            (hub_id,),
        )
        hub_res = cur.fetchone()
        if not hub_res:
            if own:
                rollback(conn)
            return False, "origin_not_found", None
        if (
            float(hub_res["metal"]) < delivered_total["metal"]
            or float(hub_res["crystal"]) < delivered_total["crystal"]
            or float(hub_res["fuel_cells"] or 0) < delivered_total["fuel_cells"]
        ):
            if own:
                rollback(conn)
            return False, "not_enough_resources", None

        available = get_planet_ships(hub_id, conn=conn)
        for sk, need in ships_n.items():
            if int(available.get(sk, 0)) < int(need):
                if own:
                    rollback(conn)
                return False, "not_enough_ships", None

        now = _now()
        cur.execute(
            """
            INSERT INTO fleet_batches (player_id, batch_type, label, status, total_fleets, created_at, updated_at)
            VALUES (?, 'distribute_resources', ?, 'running', ?, ?, ?);
            """,
            (
                int(player_id),
                f"Distribute resources x{len(legs)}",
                len(legs),
                now,
                now,
            ),
        )
        batch_id = int(cur.lastrowid)

        started: List[Dict[str, Any]] = []
        send_skipped: List[Dict[str, Any]] = []
        for leg in legs:
            ok_send, send_reason, payload = send_fleet(
                player_id=player_id,
                origin_planet_id=hub_id,
                target_galaxy=int(leg["galaxy"]),
                target_system=int(leg["system"]),
                target_position=int(leg["position"]),
                mission_type="transport",
                ships=leg["ships"],
                resources=leg["resources"],
                speed_percent=pct,
                preset_id=preset_id,
                batch_id=batch_id,
                conn=conn,
            )
            if not ok_send or not payload:
                if sel_mode == "auto_cargo":
                    send_skipped.append(
                        {
                            "planet_id": int(leg["planet_id"]),
                            "reason": send_reason or "send_failed",
                        }
                    )
                    continue
                if own:
                    rollback(conn)
                return False, send_reason or "send_failed", None
            started.append(
                {
                    "target_planet_id": int(leg["planet_id"]),
                    "fleet_id": int(payload["fleet"]["id"]),
                    "resources": calculate_loaded_resources(leg["resources"]),
                }
            )

        if not started:
            if own:
                rollback(conn)
            return False, (send_skipped[0]["reason"] if send_skipped else route_reason) or "send_failed", None

        batch_status = "completed"
        conn.execute(
            "UPDATE fleet_batches SET status = ?, total_fleets = ?, updated_at = ? WHERE id = ?;",
            (batch_status, len(started), now, batch_id),
        )

        if own:
            commit(conn)

        cur.execute("SELECT * FROM fleet_batches WHERE id = ?;", (batch_id,))
        batch_row = dict(cur.fetchone())

        launched_ids = {int(item["target_planet_id"]) for item in started}
        skipped = [int(tid) for tid in target_ids if int(tid) not in launched_ids]
        delivered_started = _sum_loaded_resources(
            [item.get("resources") or {} for item in started]
        )

        from .fleet_calc import planet_resource_stock

        fresh_rows = _load_planet_rows_for_collect([hub_id, *target_ids], conn=conn)
        colony_resources = {
            int(pid): planet_resource_stock(row) for pid, row in fresh_rows.items()
        }

        return True, "", {
            "batch": {
                "id": batch_id,
                "batch_type": batch_row["batch_type"],
                "status": batch_row["status"],
                "total_fleets": len(started),
                "label": batch_row["label"],
            },
            "started": started,
            "route": [
                {
                    "planet_id": int(leg["planet_id"]),
                    "galaxy": int(leg["galaxy"]),
                    "system": int(leg["system"]),
                    "position": int(leg["position"]),
                    "ships": dict(leg["ships"]),
                    "resources": calculate_loaded_resources(leg["resources"]),
                }
                for leg in legs
                if int(leg["planet_id"]) in launched_ids
            ],
            "colony_resources": colony_resources,
            "skipped": skipped,
            "send_skipped": send_skipped,
            "delivered_total": delivered_started or delivered_total,
            "ships_used": dict(ships_n),
            "ships_selection_mode": sel_mode,
            "active_slots": get_fleet_slot_status(player_id, conn=conn),
        }
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def build_logistics_page_context(
    *,
    player_id: int,
    planet_id: int,
    planet: Dict[str, Any],
    conn=None,
) -> Dict[str, Any]:
    """Logistics Collect UI (GC-900C) — colonies + cargo hulls; no parallel state."""
    from .live_state import current_ssr_perf

    ssr = current_ssr_perf()
    panel_t0 = time.perf_counter() if ssr is not None else 0.0

    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return {"ready": False}

        _finish_due_shipyard_on_planet(conn, int(planet_id), int(player_id))
        process_fleet_tick(player_id=int(player_id), conn=conn)

        from .fleet_calc import cargo_ship_count, filter_available_cargo_ships, planet_resource_stock
        from .resources import update_planet_resources

        colonies: List[Dict[str, Any]] = []
        hub_resources = {"metal": 0, "crystal": 0, "fuel_cells": 0}
        for p in get_planets_by_player(player_id, conn=conn):
            pid = int(p["id"])
            try:
                pc = get_planet_coordinates(p)
            except GalaxyCoordinateError:
                continue
            # Tick production so Collect cards match live stock (not stale last_update).
            planet_live, *_rest = update_planet_resources(
                dict(p),
                conn=conn,
                skip_queue_finish=True,
            )
            stock = planet_resource_stock(planet_live)
            ships = get_planet_ships(pid, conn=conn)
            cargo_ships = filter_available_cargo_ships(ships)
            is_hub = pid == int(planet_id)
            if is_hub:
                hub_resources = dict(stock)
            colonies.append(
                {
                    "planet_id": pid,
                    "name": str(p.get("name") or ""),
                    "coordinates": pc["formatted"],
                    "is_active": is_hub,
                    "ships": ships,
                    "cargo_ships": cargo_ships,
                    "cargo_ship_count": cargo_ship_count(ships),
                    "resources": dict(stock),
                }
            )

        cargo_defs = [s for s in ships_for_fleet_ui() if str(s.get("role") or "") == "cargo"]

        return {
            "ready": True,
            "planet_id": int(planet_id),
            "colonies": colonies,
            "hub_resources": hub_resources,
            "cargo_ship_defs": cargo_defs,
            "ships": get_planet_ships(planet_id, conn=conn),
            "fleet_slots": get_fleet_slot_status(player_id, conn=conn),
            "server_time": time.time(),
            "mission_locks": _fleet_mission_locks_for_client(conn=conn),
        }
    finally:
        if ssr is not None:
            ssr.add_logistics_panel_ms((time.perf_counter() - panel_t0) * 1000.0)
        if own and conn is not None:
            conn.close()


def seed_planet_ships_stack(
    planet_id: int,
    player_id: int,
    ships: Mapping[str, int] | None = None,
    *,
    replace: bool = False,
    conn=None,
) -> Tuple[bool, str, Dict[str, int]]:
    """Add (or replace) ships on a planet — used by admin/dev seed."""
    payload = dict(ships or DEV_SEED_SHIPS)
    for key in payload:
        if not is_known_ship_key(str(key)):
            return False, "unknown_ship", {}
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", {}
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        if not cur.fetchone():
            return False, "planet_not_found", {}
        if own:
            begin_write_transaction(conn)
        normalized = normalize_ships(payload)
        if replace:
            set_planet_ships(int(planet_id), int(player_id), normalized, conn=conn)
        else:
            add_planet_ships(int(planet_id), int(player_id), normalized, conn=conn)
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


def _finish_due_shipyard_on_planet(conn, planet_id: int, player_id: int) -> None:
    try:
        from .shipyard_queue import finish_due_shipyard_jobs_for_planet

        finish_due_shipyard_jobs_for_planet(conn, int(planet_id), int(player_id))
    except Exception:
        pass


def get_fleet_live_state(
    *,
    player_id: int,
    planet_id: int,
    conn=None,
) -> Dict[str, Any]:
    """Compact fleet state for client refresh after send/preset changes."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return {"ready": False}
        cur = conn.cursor()
        cur.execute("SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;", (int(planet_id), int(player_id)))
        row = cur.fetchone()
        if not row:
            return {"ready": False, "error": "planet_not_found"}
        planet = dict(row)
        _finish_due_shipyard_on_planet(conn, int(planet_id), int(player_id))
        process_fleet_tick(player_id=int(player_id), conn=conn)
        ships = get_planet_ships(planet_id, conn=conn)
        return {
            "ready": True,
            "planet_id": int(planet_id),
            "server_time": time.time(),
            "server_now": int(time.time()),
            "ships": ships,
            "has_ships": sum(int(v) for v in ships.values()) > 0,
            "resources": {
                "metal": int(float(planet.get("metal") or 0)),
                "crystal": int(float(planet.get("crystal") or 0)),
                "fuel_cells": int(float(planet.get("fuel_cells") or 0)),
            },
            "fleet_slots": get_fleet_slot_status(player_id, conn=conn),
            "active_fleets": build_active_fleets_payload(player_id, conn=conn),
            "presets": list_presets(player_id, conn=conn),
            "fuel_resource": FLEET_FUEL_RESOURCE,
            "mission_locks": _fleet_mission_locks_for_client(conn=conn),
        }
    finally:
        if own and conn is not None:
            conn.close()


def build_fleet_page_context(
    *,
    player_id: int,
    planet_id: int,
    planet: Dict[str, Any],
    conn=None,
    can_seed_test_ships: bool = False,
) -> Dict[str, Any]:
    from .live_state import current_ssr_perf

    ssr = current_ssr_perf()
    panel_t0 = time.perf_counter() if ssr is not None else 0.0

    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return {"ready": False}

        _finish_due_shipyard_on_planet(conn, int(planet_id), int(player_id))

        coords = get_planet_coordinates(planet)
        colonies: List[Dict[str, Any]] = []
        for p in get_planets_by_player(player_id, conn=conn):
            try:
                pc = get_planet_coordinates(p)
            except GalaxyCoordinateError:
                continue
            colonies.append(
                {
                    "planet_id": int(p["id"]),
                    "name": str(p.get("name") or ""),
                    "galaxy": pc["galaxy"],
                    "system": pc["system"],
                    "position": pc["position"],
                    "coordinates": pc["formatted"],
                    "is_active": int(p["id"]) == int(planet_id),
                }
            )

        ships = get_planet_ships(planet_id, conn=conn)
        presets = list_presets(player_id, conn=conn)
        process_fleet_tick(player_id=int(player_id), conn=conn)
        slots = get_fleet_slot_status(player_id, conn=conn)
        movements = list_active_movements(player_id, conn=conn)

        from .models import get_planet_buildings
        from .shipyard import get_shipyard_level, list_buildable_ships

        sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
        buildable = list_buildable_ships(player_id, planet_id, conn=conn)
        has_ships = sum(int(v) for v in ships.values()) > 0

        return {
            "ready": True,
            "planet_id": int(planet_id),
            "coordinates": coords,
            "ships": ships,
            "has_ships": has_ships,
            "ship_defs": ships_for_fleet_ui(),
            "resources": {
                "metal": int(float(planet.get("metal") or 0)),
                "crystal": int(float(planet.get("crystal") or 0)),
                "fuel_cells": int(float(planet.get("fuel_cells") or 0)),
            },
            "fleet_slots": slots,
            "active_fleets": movements,
            "presets": presets,
            "colonies": colonies,
            "missions": [m for m in FLEET_MISSION_ORDER if m in MISSION_TYPES],
            "preset_types": list(PRESET_TYPES),
            "expedition_position": EXPEDITION_POSITION,
            "fuel_resource": FLEET_FUEL_RESOURCE,
            "can_seed_test_ships": bool(can_seed_test_ships),
            "shipyard_level": sy_level,
            "orbital_shipyard_level": sy_level,
            "buildable_ships": buildable,
            "shipyard_url": "/shipyard",
            "speed_options": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
            "mission_locks": _fleet_mission_locks_for_client(conn=conn),
            "expedition_daily": expedition_daily_status(int(player_id), conn=conn),
        }
    finally:
        if ssr is not None:
            ssr.add_fleet_panel_ms((time.perf_counter() - panel_t0) * 1000.0)
        if own and conn is not None:
            conn.close()
