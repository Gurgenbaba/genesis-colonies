"""Fleet system — ships, movements, presets, tick processing, and APIs."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import begin_write_transaction, commit, db, lock_planet_for_update, rollback, table_exists
from .fleet_calc import (
    apply_departure_deduction,
    build_flight_preview_payload,
    calculate_distance,
    calculate_fleet_speed,
    calculate_flight_seconds,
    calculate_fuel_cost,
    calculate_loaded_resources,
    calculate_total_cargo,
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
from .messages import notify_combat, notify_espionage, notify_expedition
from .models import get_planets_by_player, get_research_levels

logger = logging.getLogger(__name__)

FALLBACK_FLEET_SLOTS = 3
BASE_FLEET_SLOTS = 1
COMPUTER_TECH_KEY = "computer_tech"


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


def _planet_owned_by(player_id: int, planet_id: int, *, conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (int(planet_id), int(player_id)),
    )
    return cur.fetchone() is not None


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
    if m in ("transport", "deploy"):
        if loaded_resource_total(resources) > 0 and calculate_total_cargo(ships) <= 0:
            return False, "cargo_required_for_resources"
    if m == "expedition" and not _fleet_has_role(ships, "expedition"):
        if calculate_total_cargo(ships) <= 0 and not _fleet_has_role(ships, "combat"):
            pass
    if m == "colonize":
        ark = int(ships.get("seed_ark") or 0)
        if ark < 1:
            return False, "colonize_requires_ark"
        if loaded_resource_total(resources) > 0:
            return False, "colonize_no_cargo"
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
            out.append(mv)
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
                _json_dumps(resources_json) if resources_json else None,
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
            updates["resources_json"] = (
                _json_dumps(fields["resources_json"]) if fields["resources_json"] else None
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

        origin = _origin_coords(origin_planet)
        target = (int(target_galaxy), int(target_system), int(target_position))
        if mission == "expedition" and target_position != EXPEDITION_POSITION:
            target = (int(target_galaxy), int(target_system), EXPEDITION_POSITION)
            target_position = EXPEDITION_POSITION

        if origin == target and mission not in ("expedition",):
            if own:
                rollback(conn)
            return False, "same_origin_target", None

        ok_mission, m_reason = _mission_allowed(mission, ships_n, resources_n)
        if not ok_mission:
            if own:
                rollback(conn)
            return False, m_reason, None

        cargo = calculate_total_cargo(ships_n)
        loaded_total = resources_n["metal"] + resources_n["crystal"]
        if loaded_total > 0 and loaded_total > cargo:
            if own:
                rollback(conn)
            return False, "not_enough_cargo", None

        metal_have = float(origin_planet.get("metal") or 0)
        crystal_have = float(origin_planet.get("crystal") or 0)
        fuel_cells_have = float(origin_planet.get("fuel_cells") or 0)

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

        ok_bal, bal_reason = validate_departure_balances(
            metal_have, crystal_have, fuel_cells_have, resources_n, fuel_cost
        )
        if not ok_bal:
            if own:
                rollback(conn)
            return False, bal_reason, None

        slots = get_fleet_slot_status(player_id, conn=conn)
        if slots["free"] <= 0:
            if own:
                rollback(conn)
            return False, "fleet_slots_full", None

        target_planet_id = _resolve_planet_at_coords(target[0], target[1], target[2], conn=conn)

        if mission == "colonize":
            if target_planet_id is not None:
                if own:
                    rollback(conn)
                return False, "coordinate_occupied", None
            if int(ships_n.get("seed_ark") or 0) < 1:
                if own:
                    rollback(conn)
                return False, "colonize_requires_ark", None

        if mission in ("transport", "deploy") and target_planet_id is None:
            if own:
                rollback(conn)
            return False, "invalid_target", None

        if mission in ("transport", "deploy") and not _planet_owned_by(
            player_id, int(target_planet_id), conn=conn
        ):
            if own:
                rollback(conn)
            return False, "target_not_owned", None

        ok_deduct, d_reason = deduct_planet_ships(int(origin_planet_id), ships_n, conn=conn)
        if not ok_deduct:
            if own:
                rollback(conn)
            return False, d_reason, None

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
        arrival_at = now + flight_seconds

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
            "fleet": _row_to_movement(
                conn.execute("SELECT * FROM fleet_movements WHERE id = ?;", (fleet_id,)).fetchone()
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


def _start_return(
    movement: Dict[str, Any],
    *,
    conn,
    now: float,
    remaining_resources: Mapping[str, Any] | None = None,
) -> bool:
    resources = remaining_resources if remaining_resources is not None else movement.get("resources") or {}
    flight_seconds = int(movement.get("flight_seconds") or 1)
    return_at = now + flight_seconds
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
    if loaded["metal"] <= 0 and loaded["crystal"] <= 0:
        return
    lock_planet_for_update(conn, int(planet_id))
    cur = conn.cursor()
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    row = cur.fetchone()
    if not row:
        return
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (
            float(row["metal"]) + loaded["metal"],
            float(row["crystal"]) + loaded["crystal"],
            int(planet_id),
        ),
    )


def _handle_arrival(movement: Dict[str, Any], *, conn, now: float) -> None:
    mission = movement["mission_type"]
    player_id = int(movement["player_id"])
    target_id = movement.get("target_planet_id")
    ships = movement.get("ships") or {}
    resources = movement.get("resources") or {}
    movement_id = int(movement["id"])

    if mission == "transport":
        flight_seconds = int(movement.get("flight_seconds") or 1)
        return_at = now + flight_seconds
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
        if not _start_return(movement, conn=conn, now=now):
            return
        coords = movement.get("target_coords") or ""
        notify_espionage(
            player_id,
            f"Spy report {coords}",
            f"Phase 1 placeholder espionage report for target {coords}. Deep scan system pending.",
            metadata={"fleet_id": movement_id, "target_coords": coords},
            conn=conn,
        )
        return

    if mission == "attack":
        if not _start_return(movement, conn=conn, now=now):
            return
        coords = movement.get("target_coords") or ""
        notify_combat(
            player_id,
            f"Combat report {coords}",
            f"Phase 1 placeholder combat report for target {coords}. Full combat engine pending.",
            metadata={"fleet_id": movement_id, "target_coords": coords},
            conn=conn,
        )
        return

    if mission == "hold":
        holding_until = now + DEFAULT_HOLD_SECONDS
        conn.execute(
            """
            UPDATE fleet_movements
            SET status = 'holding', holding_until = ?, updated_at = ?
            WHERE id = ? AND status = 'outbound';
            """,
            (holding_until, now, movement_id),
        )
        return

    if mission == "expedition":
        if not _start_return(movement, conn=conn, now=now):
            return
        notify_expedition(
            player_id,
            "Expedition report",
            "Phase 1 placeholder expedition report. Deep expedition rewards pending.",
            metadata={"fleet_id": movement_id},
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
        return_ships = dict(ships)
        ark_used = min(1, int(return_ships.get("seed_ark") or 0))
        if ark_used:
            return_ships["seed_ark"] = int(return_ships.get("seed_ark") or 0) - ark_used
            if return_ships["seed_ark"] <= 0:
                return_ships.pop("seed_ark", None)

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
                f"Colonization failed {coords}",
                f"Could not establish colony at {coords}: {reason}.",
                metadata={"fleet_id": movement_id, "reason": reason},
                conn=conn,
            )
            return

        flight_seconds = int(movement.get("flight_seconds") or 1)
        return_at = now + flight_seconds
        claimed = _claim_movement_status(
            conn,
            movement_id,
            ("outbound",),
            "returning",
            now,
            extra_sql=", return_at = ?, ships_json = ?, resources_json = ?",
            extra_params=(return_at, _json_dumps(return_ships), _json_dumps({})),
        )
        if claimed:
            notify_combat(
                player_id,
                f"Colony established {coords}",
                f"New colony «{colony_name}» founded at {coords}.",
                metadata={"fleet_id": movement_id, "colony_name": colony_name},
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
    resources_mode: str,
    resources: Mapping[str, Any] | None = None,
    ships_selection_mode: str = "manual",
    preset_id: int | None = None,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    ok, reason = validate_logistics_planets(
        player_id, [target_planet_id], source_planet_ids, conn=conn
    )
    if not ok:
        return False, reason, None

    mode = str(ships_selection_mode or "").strip().lower()
    if mode in ("auto_cargo", "preset") and not preset_id:
        return False, "logistics_not_implemented", {
            "ok": False,
            "reason": "logistics_not_implemented",
            "message_key": "fleet_logistics_not_implemented",
            "validated": True,
            "resources_mode": resources_mode,
            "ships_selection_mode": mode,
        }

    if mode == "auto_cargo":
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
        "note": "Manual multi-collect transport chains planned for Phase 2.",
    }


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
        ships = get_planet_ships(planet_id, conn=conn)
        return {
            "ready": True,
            "planet_id": int(planet_id),
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
