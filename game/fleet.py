"""Fleet system — ships, movements, presets, tick processing, and APIs."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .db import begin_write_transaction, commit, db, lock_planet_for_update, rollback, table_exists
from .fleet_calc import (
    apply_departure_deduction,
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
    loaded_resource_total,
    normalize_ships,
    validate_departure_balances,
)
from .fleet_defs import (
    ACTIVE_FLEET_STATUSES,
    BATCH_STATUSES,
    BATCH_TYPES,
    DEFAULT_HOLD_SECONDS,
    DEV_SEED_SHIPS,
    EXPEDITION_POSITION,
    FLEET_FUEL_RESOURCE,
    FLEET_MISSION_ORDER,
    MISSION_TYPES,
    PRESET_TYPES,
    all_ship_keys,
    canonical_ship_key,
    get_ship,
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
    build_expedition_report,
    calculate_expedition_loot_cap,
    count_expedition_ships,
    resolve_expedition_outcome,
)
from .messages import notify_combat, notify_espionage, notify_expedition, notify_player, notify_transport
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

FALLBACK_FLEET_SLOTS = 3
BASE_FLEET_SLOTS = 1
COMPUTER_TECH_KEY = "computer_tech"

TARGET_TYPES = frozenset(
    {"own_planet", "ally_planet", "foreign_planet", "empty_slot", "expedition_slot"}
)

# Default allowed missions per resolved target type (hold added dynamically for allies).
_BASE_ALLOWED_MISSIONS: Dict[str, Set[str]] = {
    "own_planet": {"transport", "collect", "deploy"},
    "ally_planet": {"transport"},
    "foreign_planet": {"spy", "attack"},
    "empty_slot": {"colonize"},
    "expedition_slot": {"expedition"},
}

_MISSION_BLOCK_REASONS: Dict[str, Dict[str, str]] = {
    "own_planet": {
        "attack": "mission_blocked_own_planet",
        "spy": "mission_blocked_own_planet",
        "hold": "mission_blocked_own_planet",
        "expedition": "mission_blocked_not_expedition_slot",
        "colonize": "mission_blocked_occupied",
    },
    "ally_planet": {
        "deploy": "mission_blocked_ally_planet",
        "spy": "mission_blocked_ally_planet",
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


def _now() -> float:
    return time.time()


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
        from .research import RESEARCH_TECHS

        if COMPUTER_TECH_KEY in RESEARCH_TECHS:
            levels = get_research_levels(user_id=int(player_id), conn=conn)
            return BASE_FLEET_SLOTS + max(0, int(levels.get(COMPUTER_TECH_KEY, 0)))
        return FALLBACK_FLEET_SLOTS
    finally:
        if own and conn is not None:
            conn.close()


def count_active_fleet_slots(player_id: int, *, conn=None) -> int:
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return 0
        placeholders = ",".join("?" for _ in ACTIVE_FLEET_STATUSES)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT COUNT(*) AS c FROM fleet_movements
            WHERE player_id = ? AND status IN ({placeholders});
            """,
            (int(player_id), *ACTIVE_FLEET_STATUSES),
        )
        return _safe_int(cur.fetchone()["c"])
    finally:
        if own and conn is not None:
            conn.close()


def get_fleet_slot_status(player_id: int, *, conn=None) -> Dict[str, int]:
    own = conn is None
    if own:
        conn = db()
    try:
        active = count_active_fleet_slots(player_id, conn=conn)
        maximum = get_max_fleet_slots(player_id, conn=conn)
        return {"active": active, "max": maximum, "free": max(0, maximum - active)}
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


def _fleet_speed_multiplier(player_id: int, conn) -> float:
    try:
        from .effects.effect_resolver import EffectResolver

        buildings = {}
        research = get_research_levels(user_id=int(player_id), conn=conn)
        resolver = EffectResolver(buildings=buildings, research=research)
        mods = resolver.resolve()
        return float(mods.get("fleet_speed_multiplier", 1.0) or 1.0)
    except Exception:
        return 1.0


def _fuel_efficiency_level(player_id: int, conn) -> int:
    try:
        research = get_research_levels(user_id=int(player_id), conn=conn)
        return max(0, int(research.get("fuel_efficiency") or 0))
    except Exception:
        return 0


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
            return _target_with_debris_recycle(
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

        allowed = set(_BASE_ALLOWED_MISSIONS.get(target_type, set()))
        if target_type == "ally_planet" and _hold_mission_enabled(conn=conn):
            allowed.add("hold")

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
        debris = target.get("debris") or {}
        if int(debris.get("metal") or 0) + int(debris.get("crystal") or 0) <= 0:
            return False, "no_debris_at_target"
        return True, ""
    allowed = set(target.get("allowed_missions") or [])
    if m in allowed:
        return True, ""
    block_map = _MISSION_BLOCK_REASONS.get(target_type, {})
    return False, block_map.get(m, "mission_not_allowed")


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
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Full pre-send validation including target resolution and balances preview."""
    mission = str(mission_type or "").strip().lower()
    ships_n = normalize_ships(ships)
    resources_n = calculate_loaded_resources(resources)
    pct = int(speed_percent)

    if mission not in MISSION_TYPES:
        return False, "invalid_mission", None
    if not ships_n:
        return False, "no_ships", None
    if pct < 10 or pct > 100:
        return False, "invalid_speed_percent", None

    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (int(origin_planet_id), int(player_id)),
    )
    origin_row = cur.fetchone()
    if not origin_row:
        return False, "origin_not_found", None
    origin_planet = dict(origin_row)

    target_info = resolve_fleet_target(
        player_id,
        target_galaxy,
        target_system,
        target_position,
        conn=conn,
    )

    origin = _origin_coords(origin_planet)
    target = (int(target_galaxy), int(target_system), int(target_position))
    if mission == "expedition":
        if int(target_position) != EXPEDITION_POSITION:
            return False, "mission_blocked_not_expedition_slot", {"target": target_info}
        target = (int(target_galaxy), int(target_system), EXPEDITION_POSITION)

    if origin == target and mission not in ("expedition", "recycle"):
        return False, "same_origin_target", {"target": target_info}

    ok_mission, m_reason = mission_allowed_for_target(mission, target_info)
    if not ok_mission:
        return False, m_reason, {"target": target_info}

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
    if slots["free"] <= 0:
        return False, "fleet_slots_full", {"target": target_info, "preview": preview}

    if mission == "colonize":
        if target_info["target_type"] != "empty_slot":
            return False, "coordinate_occupied", {"target": target_info, "preview": preview}
        if int(ships_n.get("seed_ark") or 0) < 1:
            return False, "colonize_requires_ark", {"target": target_info, "preview": preview}

    if mission in ("transport", "deploy", "spy", "attack", "hold", "collect"):
        if not target_info.get("target_planet_id"):
            return False, "invalid_target", {"target": target_info, "preview": preview}

    return True, "", {"target": target_info, "preview": preview, "origin_planet": origin_planet}


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
) -> Dict[str, Any]:
    """Flight preview enriched with target resolution and send eligibility."""
    own = conn is None
    if own:
        conn = db()
    try:
        mission = str(mission_type or "").strip().lower()
        ships_n = normalize_ships(ships)
        resources_n = calculate_loaded_resources(resources)
        target_info = resolve_fleet_target(
            player_id,
            target_galaxy,
            target_system,
            target_position,
            conn=conn,
        )
        tg, ts, tp = int(target_galaxy), int(target_system), int(target_position)
        if mission == "expedition" and tp != EXPEDITION_POSITION:
            tp = EXPEDITION_POSITION
        flight = preview_fleet_flight(
            origin_planet=origin_planet,
            target_galaxy=tg,
            target_system=ts,
            target_position=tp,
            ships=ships_n,
            resources=resources_n,
            speed_percent=int(speed_percent),
            player_id=player_id,
            conn=conn,
        )
        now = _now()
        flight_seconds = int(flight.get("flight_seconds") or 0)
        outbound = build_outbound_timing(departure_at=now, duration_seconds=flight_seconds)
        arrival_at = outbound["arrival_at"] if ships_n else None

        can_send = False
        block_reason = ""
        if ships_n:
            ok, reason, _extra = validate_fleet_send(
                player_id=player_id,
                origin_planet_id=int(origin_planet["id"]),
                target_galaxy=tg,
                target_system=ts,
                target_position=int(target_position),
                mission_type=mission,
                ships=ships_n,
                resources=resources_n,
                speed_percent=int(speed_percent),
                conn=conn,
            )
            can_send = ok
            block_reason = reason or ""

        mission_ok, mission_reason = mission_allowed_for_target(mission, target_info)
        return {
            **flight,
            "target": target_info,
            "mission_type": mission,
            "mission_allowed": mission_ok,
            "mission_block_reason": mission_reason if not mission_ok else "",
            "can_send": can_send and mission_ok,
            "block_reason": block_reason or (mission_reason if not mission_ok else ""),
            "departure_at": outbound["departure_at"] if ships_n else None,
            "arrival_at": arrival_at,
            "countdown_at": arrival_at,
            "duration_seconds": outbound["duration_seconds"] if ships_n else 0,
        }
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
    for key, amount in ships.items():
        try:
            qty = int(amount)
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        spec = get_ship(str(key))
        if spec and str(spec.get("role") or "") == role:
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
    conn=None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        origin = _origin_coords(origin_planet)
        target = (int(target_galaxy), int(target_system), int(target_position))
        distance = calculate_distance(origin, target)
        speed_mult = _fleet_speed_multiplier(player_id, conn)
        fleet_speed = calculate_fleet_speed(ships, speed_multiplier=speed_mult)
        flight_seconds = calculate_flight_seconds(distance, fleet_speed, speed_percent)
        fuel_eff = _fuel_efficiency_level(player_id, conn)
        fuel_cost = calculate_fuel_cost(
            ships, distance, speed_percent, fuel_efficiency_level=fuel_eff
        )
        cargo_total = calculate_total_cargo(ships)
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
            out.append(enrich_movement_timing(mv, now=_now()))
        return out
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
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    mission = str(mission_type or "").strip().lower()
    if mission not in MISSION_TYPES:
        return False, "invalid_mission", None
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
            return False, "origin_not_found", None
        origin_planet = dict(origin_row)
        lock_planet_for_update(conn, int(origin_planet_id))

        ok_coords, reason = _validate_target_coords(
            mission, target_galaxy, target_system, target_position, conn=conn
        )
        if not ok_coords:
            if own:
                rollback(conn)
            return False, reason, None

        if mission == "expedition" and int(target_position) != EXPEDITION_POSITION:
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
        )
        if not ok_send:
            if own:
                rollback(conn)
            return False, send_reason, None

        origin_planet = send_ctx["origin_planet"]
        preview = send_ctx["preview"]
        target_info = send_ctx["target"]
        target_planet_id = target_info.get("target_planet_id")

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

        now = _now()
        flight_seconds = int(preview["flight_seconds"])
        outbound = build_outbound_timing(departure_at=now, duration_seconds=flight_seconds)
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
                now,
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

        if own:
            commit(conn)

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


def _return_timing_from_now(
    movement: Mapping[str, Any],
    *,
    now: float,
    delay_seconds: int = 0,
) -> Dict[str, int]:
    started = int(now) + max(0, int(delay_seconds))
    return build_return_timing(return_started_at=started, duration_seconds=_return_leg_seconds(movement))


def _start_return(
    movement: Dict[str, Any],
    *,
    conn,
    now: float,
    remaining_resources: Mapping[str, Any] | None = None,
    delay_seconds: int = 0,
) -> bool:
    resources = remaining_resources if remaining_resources is not None else movement.get("resources") or {}
    timing = _return_timing_from_now(movement, now=now, delay_seconds=delay_seconds)
    return_at = timing["return_at"]
    return _claim_movement_status(
        conn,
        int(movement["id"]),
        ("outbound", "holding"),
        "returning",
        now,
        extra_sql=", return_at = ?, resources_json = ?",
        extra_params=(return_at, _json_dumps(calculate_loaded_resources(resources))),
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


def _planet_resources_for_collect_load(planet_id: int, *, conn) -> Dict[str, int]:
    """Tick target production, then return collectable resource amounts."""
    lock_planet_for_update(conn, int(planet_id))
    cur = conn.cursor()
    cur.execute("SELECT * FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    row = cur.fetchone()
    if not row:
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    from .resources import update_planet_resources

    planet, *_rest = update_planet_resources(
        dict(row),
        conn=conn,
        skip_queue_finish=True,
    )
    return {
        "metal": max(0, int(float(planet.get("metal") or 0))),
        "crystal": max(0, int(float(planet.get("crystal") or 0))),
        "fuel_cells": max(0, int(float(planet.get("fuel_cells") or 0))),
    }


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


def _handle_attack_arrival(movement: Dict[str, Any], *, conn, now: float) -> None:
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

    try:
        snapshot = _target_planet_snapshot(int(target_id), conn=conn) if target_id else {}
        defender_id = int(snapshot.get("owner_id") or 0)
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

        if combat_result is not None:
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

        score_players = {int(player_id)}
        if defender_id > 0:
            score_players.add(int(defender_id))
        try:
            from .score_events import apply_score_updates_for_players

            apply_score_updates_for_players(score_players, conn=conn)
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
            return
        from .combat import publish_attack_combat_report

        defender_locale = (
            get_player_locale(defender_id, conn=conn)
            if defender_id and defender_id != player_id
            else None
        )
        origin_coords, origin_planet_name = _movement_origin_snapshot(movement, conn=conn)
        publish_attack_combat_report(
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
    except Exception:
        logger.exception(
            "attack arrival failed movement_id=%s combat_applied=%s",
            movement_id,
            combat_applied,
        )
        if _fail_outbound_movement(conn, movement_id, now):
            return
        raise


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


def _handle_arrival(movement: Dict[str, Any], *, conn, now: float) -> None:
    mission = movement["mission_type"]
    player_id = int(movement["player_id"])
    target_id = movement.get("target_planet_id")
    ships = movement.get("ships") or {}
    resources = movement.get("resources") or {}
    movement_id = int(movement["id"])
    coords = movement.get("target_coords") or ""
    from .i18n import get_player_locale, tr

    sender_locale = get_player_locale(player_id, conn=conn)

    if mission == "recycle":
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
        ships_n = normalize_ships(ships)
        cargo_total = calculate_total_cargo(ships_n)
        collected = {"metal": 0, "crystal": 0, "fuel_cells": 0}
        tg = int(movement.get("target_galaxy") or 0)
        ts = int(movement.get("target_system") or 0)
        tp = int(movement.get("target_position") or 0)
        if cargo_total > 0:
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
        final_resources = calculate_loaded_resources(collected)
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
            return
        origin_id = int(movement["origin_planet_id"])
        cur = conn.cursor()
        cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
        orow = cur.fetchone()
        origin_name = str(orow["name"] if orow else "")
        body = _format_recycle_report(
            coords=coords,
            origin_name=origin_name,
            collected=collected,
            locale=sender_locale,
        )
        notify_transport(
            player_id,
            tr(
                "fleet_recycle_report_subject",
                "Recycle report %(coords)s",
                locale=sender_locale,
                coords=coords,
            ),
            body,
            metadata={
                "fleet_id": movement_id,
                "mission_type": "recycle",
                "target_coords": coords,
                "collected": calculate_loaded_resources(collected),
                "resources": final_resources,
                "direction": "outbound",
            },
            locale=sender_locale,
            conn=conn,
        )
        return

    if mission == "transport":
        timing = _return_timing_from_now(movement, now=now)
        return_at = timing["return_at"]
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
            return
        if target_id:
            _credit_planet_resources(int(target_id), resources, conn=conn)
            snapshot = _target_planet_snapshot(int(target_id), conn=conn)
            origin_id = int(movement["origin_planet_id"])
            cur = conn.cursor()
            cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
            orow = cur.fetchone()
            origin_name = str(orow["name"] if orow else "")
            sender_body = _format_transport_report(
                coords=coords,
                origin_name=origin_name,
                target_name=str(snapshot.get("planet_name") or ""),
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
            if target_owner and target_owner != player_id:
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
        return

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
                available = _planet_resources_for_collect_load(int(target_id), conn=conn)
                collected = _calculate_collect_load(available, remaining_cap)
                if loaded_resource_total(collected) > 0:
                    if not _debit_planet_resources(int(target_id), collected, conn=conn):
                        collected = {"metal": 0, "crystal": 0, "fuel_cells": 0}

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
            return

        origin_id = int(movement["origin_planet_id"])
        cur = conn.cursor()
        cur.execute("SELECT name FROM planets WHERE id = ? LIMIT 1;", (origin_id,))
        orow = cur.fetchone()
        origin_name = str(orow["name"] if orow else "")
        if not target_name and target_id:
            snapshot = _target_planet_snapshot(int(target_id), conn=conn)
            target_name = str(snapshot.get("planet_name") or "")

        body = _format_collect_report(
            coords=coords,
            origin_name=origin_name,
            target_name=target_name,
            collected=collected,
            total_cargo=final_resources,
            locale=sender_locale,
        )
        notify_transport(
            player_id,
            tr(
                "fleet_collect_report_subject",
                "Collect report %(coords)s",
                locale=sender_locale,
                coords=coords,
            ),
            body,
            metadata={
                "fleet_id": movement_id,
                "mission_type": "collect",
                "target_coords": coords,
                "collected": calculate_loaded_resources(collected),
                "resources": final_resources,
                "direction": "outbound",
            },
            locale=sender_locale,
            conn=conn,
        )
        return

    if mission == "deploy":
        if not _claim_movement_status(conn, movement_id, ("outbound",), "completed", now):
            return
        if target_id:
            _credit_planet_resources(int(target_id), resources, conn=conn)
            cur = conn.cursor()
            cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(target_id),))
            trow = cur.fetchone()
            owner = int(trow["player_id"]) if trow else player_id
            add_planet_ships(int(target_id), owner, ships, conn=conn)
        return

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
            return
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
        return

    if mission == "attack":
        _handle_attack_arrival(movement, conn=conn, now=now)
        return

    if mission == "hold":
        holding_until = now + DEFAULT_HOLD_SECONDS
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE fleet_movements
            SET status = 'holding', holding_until = ?, updated_at = ?
            WHERE id = ? AND status = 'outbound';
            """,
            (holding_until, now, movement_id),
        )
        if cur.rowcount and target_id:
            snapshot = _target_planet_snapshot(int(target_id), conn=conn)
            notify_player(
                player_id,
                f"Fleet holding {coords}",
                f"Your fleet is holding position at {coords} ({snapshot.get('owner_name', '')}).",
                category="system",
                metadata={"fleet_id": movement_id, "holding_until": holding_until},
                conn=conn,
            )
        return

    if mission == "expedition":
        cargo_total = calculate_expedition_loot_cap(ships)
        flight_seconds_base = int(movement.get("flight_seconds") or 1)
        outcome = resolve_expedition_outcome(
            movement_id,
            cargo_total=cargo_total,
            expedition_ship_count=count_expedition_ships(ships),
            flight_seconds=flight_seconds_base,
        )
        rewards = outcome["rewards"]
        delay_extra = int(outcome.get("delay_extra") or 0)
        timing = _return_timing_from_now(movement, now=now, delay_seconds=delay_extra)
        return_at = timing["return_at"]
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(rewards)),
        )
        if not claimed:
            return
        body, meta = build_expedition_report(coords, ships, outcome, locale=sender_locale)
        meta["fleet_id"] = movement_id

        notify_expedition(
            player_id,
            tr(
                "fleet_report_expedition_subject_coords",
                "Expedition report — %(coords)s",
                locale=sender_locale,
                coords=coords,
            ),
            body,
            metadata=meta,
            locale=sender_locale,
            conn=conn,
        )
        return

    if mission == "colonize":
        from .planet_evolution.service import colonize_planet

        coords = movement.get("target_coords") or ""
        raw_res = movement.get("resources") or {}
        colony_name = str(raw_res.get("colony_name") or "").strip() or f"Colony {coords}"
        tg = int(movement.get("target_galaxy") or 0)
        ts = int(movement.get("target_system") or 0)
        tp = int(movement.get("target_position") or 0)

        ok_col, reason, _extra = colonize_planet(
            player_id,
            name=colony_name,
            galaxy=tg,
            system=ts,
            position=tp,
            conn=conn,
        )
        if not ok_col:
            if not _start_return(movement, conn=conn, now=now):
                return
            notify_combat(
                player_id,
                tr(
                    "fleet_report_colonize_failed_subject_coords",
                    "Colonization failed — %(coords)s",
                    locale=sender_locale,
                    coords=coords,
                ),
                tr(
                    "fleet_report_colonize_failed_body",
                    "Could not establish colony at %(coords)s: %(reason)s.",
                    locale=sender_locale,
                    coords=coords,
                    reason=reason,
                ),
                metadata={"fleet_id": movement_id, "reason": reason},
                locale=sender_locale,
                conn=conn,
            )
            return

        return_ships = dict(ships)
        ark_used = min(1, int(return_ships.get("seed_ark") or 0))
        if ark_used:
            return_ships["seed_ark"] = int(return_ships.get("seed_ark") or 0) - ark_used
            if return_ships["seed_ark"] <= 0:
                return_ships.pop("seed_ark", None)
        return_ships = {k: v for k, v in return_ships.items() if int(v or 0) > 0}

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

        if claimed:
            notify_combat(
                player_id,
                tr(
                    "fleet_report_colonize_success_subject_coords",
                    "Colony established — %(coords)s",
                    locale=sender_locale,
                    coords=coords,
                ),
                tr(
                    "fleet_report_colonize_success_body",
                    "New colony «%(colony_name)s» founded at %(coords)s.",
                    locale=sender_locale,
                    colony_name=colony_name,
                    coords=coords,
                ),
                metadata={"fleet_id": movement_id, "colony_name": colony_name},
                locale=sender_locale,
                conn=conn,
            )
        return


def _handle_holding_end(movement: Dict[str, Any], *, conn, now: float) -> None:
    _start_return(movement, conn=conn, now=now)


def _handle_return(movement: Dict[str, Any], *, conn, now: float) -> None:
    movement_id = int(movement["id"])
    if not _complete_movement(movement_id, conn=conn, now=now, from_status="returning"):
        return
    origin_id = int(movement["origin_planet_id"])
    player_id = int(movement["player_id"])
    ships = movement.get("ships") or {}
    resources = movement.get("resources") or {}
    add_planet_ships(origin_id, player_id, ships, conn=conn)
    _credit_planet_resources(origin_id, resources, conn=conn)


def process_fleet_tick(
    *,
    player_id: Optional[int] = None,
    now: Optional[float] = None,
    conn=None,
) -> Dict[str, Any]:
    """Process due fleet arrivals and returns. Idempotent per movement status transition."""
    own = conn is None
    if own:
        conn = db()
    if now is None:
        now = _now()

    result = {"processed_arrivals": 0, "processed_returns": 0, "processed_holding": 0, "errors": []}

    if not fleet_schema_ready(conn):
        if own and conn is not None:
            conn.close()
        return result

    try:
        if own:
            begin_write_transaction(conn)

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
                _handle_arrival(mv, conn=conn, now=now)
                result["processed_arrivals"] += 1
            except Exception as exc:
                result["errors"].append(f"arrival fleet={mv['id']}: {exc}")
                logger.exception("fleet arrival failed fleet=%s", mv["id"])
                if mv.get("mission_type") == "attack":
                    try:
                        _fail_outbound_movement(conn, int(mv["id"]), now)
                    except Exception:
                        logger.exception(
                            "failed to mark attack movement failed fleet=%s",
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
                _handle_holding_end(mv, conn=conn, now=now)
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
                _handle_return(mv, conn=conn, now=now)
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

        if own:
            commit(conn)
    except Exception as exc:
        if own:
            rollback(conn)
        result["errors"].append(str(exc))
        logger.exception("process_fleet_tick failed")
        raise
    finally:
        if own and conn is not None:
            conn.close()

    return result


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
        slots = get_fleet_slot_status(player_id, conn=conn)
        max_start = slots["free"]
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
                conn=conn,
            )
            if ok and payload:
                started.append({"wave": wave + 1, "fleet_id": payload["fleet"]["id"]})
            else:
                skipped.append({"wave": wave + 1, "reason": reason or "send_failed"})

        batch_status = "completed" if started else "failed"
        conn.execute(
            "UPDATE fleet_batches SET status = ?, total_fleets = ?, updated_at = ? WHERE id = ?;",
            (batch_status, len(started), now, batch_id),
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


def _fleet_ships_are_cargo_only(ships: Mapping[str, int]) -> Tuple[bool, str]:
    ships_n = normalize_ships(ships)
    if not ships_n:
        return False, "no_ships"
    for key in ships_n:
        spec = get_ship(str(key))
        if not spec or str(spec.get("role") or "") != "cargo":
            return False, "no_cargo_ships"
    return True, ""


def _split_ships_across_targets(ships: Mapping[str, int], target_count: int) -> List[Dict[str, int]]:
    """Split fleet evenly; per-type remainder goes to the last target."""
    if target_count < 1:
        return []
    ships_n = normalize_ships(ships)
    parts: List[Dict[str, int]] = [{} for _ in range(target_count)]
    for key, total in ships_n.items():
        base, rem = divmod(int(total), target_count)
        for i in range(target_count - 1):
            if base > 0:
                parts[i][key] = base
        last_qty = base + rem
        if last_qty > 0:
            parts[target_count - 1][key] = last_qty
    return [normalize_ships(p) for p in parts]


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
    """Multi-colony collect: hub origin, N× send_fleet(mission=collect) under one batch (GC-900B)."""
    hub_id = int(target_planet_id or 0)
    if hub_id <= 0:
        return False, "origin_not_found", None

    raw_sources = [int(x) for x in (source_planet_ids or []) if int(x) > 0]
    sources = []
    seen: Set[int] = set()
    for sid in raw_sources:
        if sid == hub_id or sid in seen:
            continue
        seen.add(sid)
        sources.append(sid)
    if not sources:
        return False, "no_planets", None

    ok, reason = validate_logistics_planets(
        player_id, [hub_id], sources, conn=conn
    )
    if not ok:
        return False, reason, None

    mode = str(ships_selection_mode or "").strip().lower()
    if mode in ("auto_cargo", "preset"):
        return False, "logistics_not_implemented", None

    if str(resources_mode or "").strip().lower() != "all":
        return False, "logistics_not_implemented", None

    ships_n = normalize_ships(ships)
    if not ships_n:
        return False, "no_ships", None
    ok_cargo, cargo_reason = _fleet_ships_are_cargo_only(ships_n)
    if not ok_cargo:
        return False, cargo_reason, None

    pct = int(speed_percent)
    if pct < 10 or pct > 100:
        return False, "invalid_speed_percent", None

    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return False, "fleet_unavailable", None

        if own:
            begin_write_transaction(conn)

        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (hub_id, int(player_id)),
        )
        hub_row = cur.fetchone()
        if not hub_row:
            if own:
                rollback(conn)
            return False, "origin_not_found", None

        available = get_planet_ships(hub_id, conn=conn)
        for sk, need in ships_n.items():
            if int(available.get(sk, 0)) < int(need):
                if own:
                    rollback(conn)
                return False, "not_enough_ships", None

        allocations = _split_ships_across_targets(ships_n, len(sources))
        for alloc in allocations:
            if not alloc or calculate_total_cargo(alloc) <= 0:
                if own:
                    rollback(conn)
                return False, "not_enough_ships", None

        slots = get_fleet_slot_status(player_id, conn=conn)
        if int(slots["free"]) < len(sources):
            if own:
                rollback(conn)
            return False, "fleet_slots_full", None

        now = _now()
        cur.execute(
            """
            INSERT INTO fleet_batches (player_id, batch_type, label, status, total_fleets, created_at, updated_at)
            VALUES (?, 'collect_resources', ?, 'running', ?, ?, ?);
            """,
            (
                int(player_id),
                f"Collect resources x{len(sources)}",
                len(sources),
                now,
                now,
            ),
        )
        batch_id = int(cur.lastrowid)

        started: List[Dict[str, Any]] = []
        for source_id, alloc in zip(sources, allocations):
            cur.execute(
                "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
                (int(source_id), int(player_id)),
            )
            source_row = cur.fetchone()
            if not source_row:
                if own:
                    rollback(conn)
                return False, "planet_not_owned", None
            coords = get_planet_coordinates(dict(source_row))
            ok_send, send_reason, payload = send_fleet(
                player_id=player_id,
                origin_planet_id=hub_id,
                target_galaxy=int(coords["galaxy"]),
                target_system=int(coords["system"]),
                target_position=int(coords["position"]),
                mission_type="collect",
                ships=alloc,
                resources={},
                speed_percent=pct,
                preset_id=preset_id,
                batch_id=batch_id,
                conn=conn,
            )
            if not ok_send or not payload:
                if own:
                    rollback(conn)
                return False, send_reason or "send_failed", None
            started.append(
                {
                    "source_planet_id": int(source_id),
                    "fleet_id": int(payload["fleet"]["id"]),
                }
            )

        batch_status = "completed" if started else "failed"
        conn.execute(
            "UPDATE fleet_batches SET status = ?, total_fleets = ?, updated_at = ? WHERE id = ?;",
            (batch_status, len(started), now, batch_id),
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
            "skipped": [],
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
    resources_mode: str,
    resources: Mapping[str, Any] | None = None,
    ships_selection_mode: str = "manual",
    preset_id: int | None = None,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    ok, reason = validate_logistics_planets(
        player_id, list(target_planet_ids), [origin_planet_id], conn=conn
    )
    if not ok:
        return False, reason, None

    mode = str(ships_selection_mode or "").strip().lower()
    if mode in ("auto_cargo", "preset") and mode == "auto_cargo":
        return False, "logistics_not_implemented", {
            "ok": False,
            "reason": "logistics_not_implemented",
            "message_key": "fleet_logistics_not_implemented",
            "validated": True,
        }

    return False, "logistics_not_implemented", {
        "ok": False,
        "reason": "logistics_not_implemented",
        "message_key": "fleet_logistics_not_implemented",
        "validated": True,
        "note": "Manual distribute transport chains planned for Phase 2.",
    }


def build_logistics_page_context(
    *,
    player_id: int,
    planet_id: int,
    planet: Dict[str, Any],
    conn=None,
) -> Dict[str, Any]:
    """Logistics Collect UI (GC-900C) — colonies + cargo hulls; no parallel state."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not fleet_schema_ready(conn):
            return {"ready": False}

        _finish_due_shipyard_on_planet(conn, int(planet_id), int(player_id))
        process_fleet_tick(player_id=int(player_id), conn=conn)

        colonies: List[Dict[str, Any]] = []
        for p in get_planets_by_player(player_id, conn=conn):
            pid = int(p["id"])
            try:
                pc = get_planet_coordinates(p)
            except GalaxyCoordinateError:
                continue
            ships = get_planet_ships(pid, conn=conn)
            colonies.append(
                {
                    "planet_id": pid,
                    "name": str(p.get("name") or ""),
                    "coordinates": pc["formatted"],
                    "is_active": pid == int(planet_id),
                    "ships": ships,
                }
            )

        cargo_defs = [s for s in ships_for_fleet_ui() if str(s.get("role") or "") == "cargo"]

        return {
            "ready": True,
            "planet_id": int(planet_id),
            "colonies": colonies,
            "cargo_ship_defs": cargo_defs,
            "ships": get_planet_ships(planet_id, conn=conn),
            "fleet_slots": get_fleet_slot_status(player_id, conn=conn),
            "server_time": time.time(),
        }
    finally:
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
        from .ranking import on_player_score_changed

        on_player_score_changed(int(player_id), conn=conn)
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
            "ships": ships,
            "has_ships": sum(int(v) for v in ships.values()) > 0,
            "resources": {
                "metal": int(float(planet.get("metal") or 0)),
                "crystal": int(float(planet.get("crystal") or 0)),
                "fuel_cells": int(float(planet.get("fuel_cells") or 0)),
            },
            "fleet_slots": get_fleet_slot_status(player_id, conn=conn),
            "active_fleets": list_active_movements(player_id, conn=conn),
            "presets": list_presets(player_id, conn=conn),
            "fuel_resource": FLEET_FUEL_RESOURCE,
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
        slots = get_fleet_slot_status(player_id, conn=conn)
        presets = list_presets(player_id, conn=conn)
        process_fleet_tick(player_id=int(player_id), conn=conn)
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
        }
    finally:
        if own and conn is not None:
            conn.close()
