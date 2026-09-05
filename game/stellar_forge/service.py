"""Stellar Forge owner — Ascension campaign state, pillar progress, Ascend action."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from ..db import begin_write_transaction, commit, lock_planet_for_update, rollback, table_exists
from ..mine_evolution import roman_numeral
from ..models import db, get_planet_buildings
from .formulas import (
    FORGE_BUILDING,
    HULL_MASS_MIN_ROLES,
    OPERATIONAL_PROTOCOLS,
    OPERATIONAL_PROTOCOLS_REQUIRED,
    forge_capacity_multiplier,
    forge_cores_required,
    hull_mass_target,
    manufacturing_trial_complete,
    nanite_assist_unlocked,
    operational_target,
    operational_trial_complete,
    queue_slot_bonus,
    roll_manufacturing_roles,
    ship_hull_mass,
    specialization_unlocked,
    tribute_cost_for_rank,
    tribute_hours,
)


def schema_ready(conn: sqlite3.Connection) -> bool:
    try:
        return table_exists(conn, "planet_shipyard_ascension")
    except Exception:
        return False


def _row(conn: sqlite3.Connection, planet_id: int) -> Optional[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM planet_shipyard_ascension WHERE planet_id = ? LIMIT 1;",
        (int(planet_id),),
    )
    return cur.fetchone()


def _operational_progress_int(value: Any) -> int:
    """Normalize legacy/new operational progress without an IEEE-754 roundtrip."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _default_state(planet_id: int) -> Dict[str, Any]:
    return {
        "planet_id": int(planet_id),
        "forge_rank": 0,
        "campaign_active": False,
        "campaign_started_at": None,
        "tribute_paid": False,
        "hull_mass_progress": 0,
        "hull_mass_by_role": {},
        "manufacturing_roles": [],
        "operational_progress": {},
        "forge_cores_committed": 0,
        "updated_at": 0.0,
    }


def _parse_row(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        hull_by_role = json.loads(row["hull_mass_by_role"] or "{}")
    except (TypeError, ValueError):
        hull_by_role = {}
    try:
        operational_progress = json.loads(row["operational_protocols_done"] or "{}")
    except (TypeError, ValueError):
        operational_progress = {}
    try:
        # GC-3009 — column added post-launch (migration 151); tolerate rows/DBs
        # from before it existed instead of raising.
        manufacturing_roles = json.loads(row["manufacturing_roles"] or "[]")
    except (TypeError, ValueError, IndexError, KeyError):
        manufacturing_roles = []
    return {
        "planet_id": int(row["planet_id"]),
        "forge_rank": int(row["forge_rank"] or 0),
        "campaign_active": bool(row["campaign_active"]),
        "campaign_started_at": row["campaign_started_at"],
        "tribute_paid": bool(row["tribute_paid"]),
        "hull_mass_progress": int(row["hull_mass_progress"] or 0),
        "hull_mass_by_role": hull_by_role if isinstance(hull_by_role, dict) else {},
        "manufacturing_roles": manufacturing_roles if isinstance(manufacturing_roles, list) else [],
        "operational_progress": operational_progress if isinstance(operational_progress, dict) else {},
        "forge_cores_committed": int(row["forge_cores_committed"] or 0),
        "updated_at": float(row["updated_at"] or 0),
    }


def get_raw_state(planet_id: int, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn):
            return _default_state(planet_id)
        row = _row(conn, planet_id)
        if not row:
            return _default_state(planet_id)
        return _parse_row(row)
    finally:
        if own:
            conn.close()


def is_unlocked(planet_id: int, *, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Shipyard is at its current effective max level (dynamic — not a hardcoded '50')."""
    from ..buildings import get_max_level_for_building

    own = conn is None
    if own:
        conn = db()
    try:
        buildings = get_planet_buildings(int(planet_id), conn=conn)
        level = int(buildings.get(FORGE_BUILDING, 0) or 0)
        if level <= 0:
            return False
        max_level = get_max_level_for_building(FORGE_BUILDING, buildings)
        return level >= max_level
    finally:
        if own:
            conn.close()


def get_forge_cores(player_id: int, conn: Optional[sqlite3.Connection] = None) -> int:
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn):
            return 0
        cur = conn.cursor()
        cur.execute(
            "SELECT forge_cores FROM player_forge_cores WHERE player_id = ? LIMIT 1;",
            (int(player_id),),
        )
        row = cur.fetchone()
        return int(row["forge_cores"]) if row else 0
    finally:
        if own:
            conn.close()


def grant_forge_cores(player_id: int, amount: int, *, conn: sqlite3.Connection, now: Optional[float] = None) -> None:
    """Credit Forge Cores to a player wallet. Called from World Boss / Expedition / Recycler drop hooks."""
    amt = int(amount or 0)
    if amt <= 0 or not schema_ready(conn):
        return
    ts = float(now if now is not None else time.time())
    conn.execute(
        """
        INSERT INTO player_forge_cores (player_id, forge_cores, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            forge_cores = player_forge_cores.forge_cores + excluded.forge_cores,
            updated_at = excluded.updated_at;
        """,
        (int(player_id), amt, ts),
    )


def _upsert_state(conn: sqlite3.Connection, planet_id: int, **fields: Any) -> None:
    existing = _row(conn, planet_id)
    now = float(fields.pop("updated_at", time.time()))
    if existing is None:
        base = _default_state(planet_id)
        base.update(fields)
        conn.execute(
            """
            INSERT INTO planet_shipyard_ascension (
                planet_id, forge_rank, campaign_active, campaign_started_at,
                tribute_paid, hull_mass_progress, hull_mass_by_role, manufacturing_roles,
                operational_protocols_done, forge_cores_committed, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(planet_id),
                int(base["forge_rank"]),
                1 if base["campaign_active"] else 0,
                base["campaign_started_at"],
                1 if base["tribute_paid"] else 0,
                int(base["hull_mass_progress"]),
                json.dumps(base["hull_mass_by_role"]),
                json.dumps(base["manufacturing_roles"]),
                json.dumps(base["operational_progress"]),
                int(base["forge_cores_committed"]),
                now,
            ),
        )
        return

    sets = []
    params: list = []
    col_map = {
        "forge_rank": "forge_rank",
        "campaign_active": "campaign_active",
        "campaign_started_at": "campaign_started_at",
        "tribute_paid": "tribute_paid",
        "hull_mass_progress": "hull_mass_progress",
        "hull_mass_by_role": "hull_mass_by_role",
        "manufacturing_roles": "manufacturing_roles",
        "operational_progress": "operational_protocols_done",
        "forge_cores_committed": "forge_cores_committed",
    }
    for key, col in col_map.items():
        if key not in fields:
            continue
        val = fields[key]
        if key == "campaign_active":
            val = 1 if val else 0
        elif key == "tribute_paid":
            val = 1 if val else 0
        elif key in ("hull_mass_by_role", "manufacturing_roles", "operational_progress"):
            val = json.dumps(val)
        sets.append(f"{col} = ?")
        params.append(val)
    sets.append("updated_at = ?")
    params.append(now)
    params.append(int(planet_id))
    conn.execute(
        f"UPDATE planet_shipyard_ascension SET {', '.join(sets)} WHERE planet_id = ?;",
        params,
    )


def _get_production_per_hour(planet: Dict[str, Any], *, conn: sqlite3.Connection) -> Dict[str, int]:
    """Trailing per-hour production for Tribute — same EffectResolver path as economy_live_audit."""
    from .. import models as _models
    from ..effects.effect_resolver import EffectResolver
    from ..galaxy import get_planet_coordinates

    player_id = int(planet.get("player_id") or 0)
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id, conn=conn)
    research = _models.get_research_levels(player_id, conn=conn)
    coords = get_planet_coordinates(planet)
    position = int(coords.get("position") or 0) or None
    if position is not None and not (1 <= position <= 15):
        position = None

    resolver = EffectResolver(
        buildings, research, player_id=player_id, planet_id=planet_id,
        planet_position=position, conn=conn,
    )
    energy_total, energy_used = resolver.compute_energy()
    ratio = resolver.energy_ratio(energy_total, energy_used)
    prod = resolver.get_building_production_per_hour(ratio)
    return {
        "metal": int(prod.get("metal_mine", 0) or 0),
        "crystal": int(prod.get("crystal_mine", 0) or 0),
        "fuel_cells": int(prod.get("fuel_cell_plant", 0) or 0),
    }


def panel_forge_fields(
    planet: Dict[str, Any],
    *,
    conn: Optional[sqlite3.Connection] = None,
    production_per_hour: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """SSR/UI fields for the orbital shipyard building card.

    ``production_per_hour`` should be the buildings panel's already-built
    ``BuildingsPanelContext.production_per_hour`` (keyed by building type,
    e.g. ``metal_mine``) when called from the panel-row loop — avoids
    building a second, unshared ``EffectResolver`` per row (GC-PERF-PANEL-CONN-001).
    """
    planet_id = int(planet["id"])
    own = conn is None
    if own:
        conn = db()
    try:
        unlocked = is_unlocked(planet_id, conn=conn)
        state = get_raw_state(planet_id, conn=conn)
        rank = int(state["forge_rank"])
        next_rank = rank + 1
        player_id = int(planet.get("player_id") or 0)

        if not unlocked:
            return {
                "stellar_forge_unlocked": False,
                "stellar_forge_rank": rank,
                "stellar_forge_rank_roman": roman_numeral(rank),
            }

        campaign_active = bool(state["campaign_active"])
        tribute = {}
        try:
            if production_per_hour is not None:
                production = {
                    "metal": int(production_per_hour.get("metal_mine", 0) or 0),
                    "crystal": int(production_per_hour.get("crystal_mine", 0) or 0),
                    "fuel_cells": int(production_per_hour.get("fuel_cell_plant", 0) or 0),
                }
            else:
                production = _get_production_per_hour(planet, conn=conn)
            tribute = tribute_cost_for_rank(next_rank, production)
        except Exception:
            tribute = {"metal": 0, "crystal": 0, "fuel_cells": 0}

        hull_target = hull_mass_target(next_rank)
        hull_progress = int(state["hull_mass_progress"])
        op_progress = state["operational_progress"]
        op_done = {
            p for p in OPERATIONAL_PROTOCOLS
            if _operational_progress_int(op_progress.get(p, 0)) >= operational_target(p, next_rank)
        }
        cores_required = forge_cores_required(next_rank)
        cores_have = get_forge_cores(player_id, conn=conn)

        manufacturing_roles = state["manufacturing_roles"]
        pillar1_done = bool(state["tribute_paid"])
        pillar2_done = manufacturing_trial_complete(
            hull_progress, next_rank, state["hull_mass_by_role"], manufacturing_roles
        )
        pillar3_done = operational_trial_complete(op_done)
        pillar4_done = cores_have >= cores_required

        return {
            "stellar_forge_unlocked": True,
            "stellar_forge_rank": rank,
            "stellar_forge_rank_roman": roman_numeral(rank),
            "stellar_forge_next_rank": next_rank,
            "stellar_forge_campaign_active": campaign_active,
            "stellar_forge_tribute_cost": tribute,
            "stellar_forge_tribute_hours": tribute_hours(next_rank),
            "stellar_forge_tribute_paid": pillar1_done,
            "stellar_forge_hull_mass_target": hull_target,
            "stellar_forge_hull_mass_progress": hull_progress,
            "stellar_forge_hull_mass_roles": state["hull_mass_by_role"],
            "stellar_forge_hull_mass_min_roles": HULL_MASS_MIN_ROLES,
            "stellar_forge_manufacturing_roles": manufacturing_roles,
            "stellar_forge_manufacturing_done": pillar2_done,
            "stellar_forge_operational_protocols": {
                p: {
                    "progress": _operational_progress_int(op_progress.get(p, 0)),
                    "target": operational_target(p, next_rank),
                    "done": p in op_done,
                }
                for p in OPERATIONAL_PROTOCOLS
            },
            "stellar_forge_operational_required": OPERATIONAL_PROTOCOLS_REQUIRED,
            "stellar_forge_operational_done": pillar3_done,
            "stellar_forge_forge_cores_required": cores_required,
            "stellar_forge_forge_cores_have": cores_have,
            "stellar_forge_forge_cores_done": pillar4_done,
            "stellar_forge_can_ascend": campaign_active and pillar1_done and pillar2_done and pillar3_done and pillar4_done,
            "stellar_forge_queue_slot_bonus": queue_slot_bonus(rank),
            "stellar_forge_nanite_assist_unlocked": nanite_assist_unlocked(rank),
            "stellar_forge_specialization_unlocked": specialization_unlocked(rank),
            "stellar_forge_capacity_multiplier": forge_capacity_multiplier(rank),
        }
    finally:
        if own:
            conn.close()


def start_campaign(user_id: int, planet: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    planet_id = int(planet["id"])
    owner_id = int(planet.get("player_id") or 0)
    if owner_id != int(user_id):
        return False, "forbidden", {"msg": "Planet not owned"}

    conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)

        if not schema_ready(conn):
            rollback(conn)
            return False, "schema_missing", {"msg": "Stellar Forge schema not applied"}

        if not is_unlocked(planet_id, conn=conn):
            rollback(conn)
            return False, "not_unlocked", {"msg": "Orbital Shipyard not at max level"}

        state = get_raw_state(planet_id, conn=conn)
        if state["campaign_active"]:
            rollback(conn)
            return False, "campaign_active", {"msg": "A Forge campaign is already running"}

        now = time.time()
        manufacturing_roles = roll_manufacturing_roles()
        _upsert_state(
            conn,
            planet_id,
            forge_rank=int(state["forge_rank"]),
            campaign_active=True,
            campaign_started_at=now,
            tribute_paid=False,
            hull_mass_progress=0,
            hull_mass_by_role={},
            manufacturing_roles=manufacturing_roles,
            operational_progress={},
            forge_cores_committed=0,
            updated_at=now,
        )
        commit(conn)
        return True, "ok", {
            "forge_rank": int(state["forge_rank"]),
            "next_rank": int(state["forge_rank"]) + 1,
            "manufacturing_roles": manufacturing_roles,
        }
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def pay_tribute(user_id: int, planet: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    from ..shipyard import _try_spend_build_resources

    planet_id = int(planet["id"])
    owner_id = int(planet.get("player_id") or 0)
    if owner_id != int(user_id):
        return False, "forbidden", {"msg": "Planet not owned"}

    conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)

        if not schema_ready(conn):
            rollback(conn)
            return False, "schema_missing", {}

        state = get_raw_state(planet_id, conn=conn)
        if not state["campaign_active"]:
            rollback(conn)
            return False, "no_campaign", {"msg": "Start a Forge campaign first"}
        if state["tribute_paid"]:
            rollback(conn)
            return False, "already_paid", {}

        next_rank = int(state["forge_rank"]) + 1
        production = _get_production_per_hour(planet, conn=conn)
        cost = tribute_cost_for_rank(next_rank, production)

        ok = _try_spend_build_resources(
            conn,
            planet_id,
            metal=int(cost.get("metal", 0)),
            crystal=int(cost.get("crystal", 0)),
            fuel_cells=int(cost.get("fuel_cells", 0)),
        )
        if not ok:
            rollback(conn)
            return False, "insufficient_resources", {"cost": cost}

        now = time.time()
        _upsert_state(conn, planet_id, tribute_paid=True, updated_at=now)
        commit(conn)
        return True, "ok", {"cost": cost}
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def record_hull_mass_delivery(
    planet_id: int,
    ship_key: str,
    amount: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> None:
    """Add Hull Mass for units delivered by the shipyard queue (only while a campaign is active)."""
    amt = int(amount or 0)
    if amt <= 0 or not schema_ready(conn):
        return
    state = get_raw_state(planet_id, conn=conn)
    if not state["campaign_active"]:
        return

    from ..fleet_defs import get_ship, ship_display_role

    spec = get_ship(ship_key) or {}
    mass = ship_hull_mass(spec.get("build_cost") or {}) * amt
    role = ship_display_role(ship_key) or "utility"

    by_role = dict(state["hull_mass_by_role"])
    by_role[role] = int(by_role.get(role, 0)) + mass

    _upsert_state(
        conn,
        planet_id,
        hull_mass_progress=int(state["hull_mass_progress"]) + mass,
        hull_mass_by_role=by_role,
        updated_at=float(now if now is not None else time.time()),
    )


def record_operational_progress(
    planet_id: int,
    protocol: str,
    amount: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[float] = None,
) -> None:
    """Accumulate progress toward one Operational Trial protocol (only while campaign active)."""
    if protocol not in OPERATIONAL_PROTOCOLS:
        return
    amt = _operational_progress_int(amount)
    if amt <= 0 or not schema_ready(conn):
        return
    state = get_raw_state(planet_id, conn=conn)
    if not state["campaign_active"]:
        return

    progress = dict(state["operational_progress"])
    progress[protocol] = _operational_progress_int(progress.get(protocol, 0)) + amt

    _upsert_state(
        conn,
        planet_id,
        operational_progress=progress,
        updated_at=float(now if now is not None else time.time()),
    )


def ascend(user_id: int, planet: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """Atomic Ascension: verify all 4 pillars, spend Tribute-consumed Forge Cores, rank + 1."""
    planet_id = int(planet["id"])
    owner_id = int(planet.get("player_id") or 0)
    if owner_id != int(user_id):
        return False, "forbidden", {"msg": "Planet not owned"}

    conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)

        if not schema_ready(conn):
            rollback(conn)
            return False, "schema_missing", {}

        from ..queue_engine import finish_due_work

        finish_due_work(
            player_id=int(user_id),
            planet_id=planet_id,
            now=time.time(),
            conn=conn,
            source="action",
            recalc_ranks=False,
        )

        state = get_raw_state(planet_id, conn=conn)
        if not state["campaign_active"]:
            rollback(conn)
            return False, "no_campaign", {"msg": "No active Forge campaign"}
        if not state["tribute_paid"]:
            rollback(conn)
            return False, "tribute_unpaid", {"msg": "Pay the Industrial Tribute first"}

        next_rank = int(state["forge_rank"]) + 1

        if not manufacturing_trial_complete(
            int(state["hull_mass_progress"]), next_rank, state["hull_mass_by_role"], state["manufacturing_roles"]
        ):
            rollback(conn)
            return False, "manufacturing_incomplete", {
                "hull_mass_progress": state["hull_mass_progress"],
                "hull_mass_target": hull_mass_target(next_rank),
                "manufacturing_roles": state["manufacturing_roles"],
            }

        op_done = {
            p for p in OPERATIONAL_PROTOCOLS
            if _operational_progress_int(state["operational_progress"].get(p, 0)) >= operational_target(p, next_rank)
        }
        if not operational_trial_complete(op_done):
            rollback(conn)
            return False, "operational_incomplete", {
                "protocols_done": sorted(op_done),
                "required": OPERATIONAL_PROTOCOLS_REQUIRED,
            }

        cores_required = forge_cores_required(next_rank)
        cores_have = get_forge_cores(int(user_id), conn=conn)
        if cores_have < cores_required:
            rollback(conn)
            return False, "forge_cores_missing", {
                "forge_cores_have": cores_have,
                "forge_cores_required": cores_required,
            }

        now = time.time()
        conn.execute(
            "UPDATE player_forge_cores SET forge_cores = forge_cores - ?, updated_at = ? WHERE player_id = ?;",
            (int(cores_required), now, int(user_id)),
        )
        _upsert_state(
            conn,
            planet_id,
            forge_rank=next_rank,
            campaign_active=False,
            tribute_paid=False,
            hull_mass_progress=0,
            hull_mass_by_role={},
            manufacturing_roles=[],
            operational_progress={},
            forge_cores_committed=0,
            updated_at=now,
        )
        commit(conn)

        return True, "ok", {
            "forge_rank": next_rank,
            "forge_rank_roman": roman_numeral(next_rank),
            "forge_cores_spent": cores_required,
        }
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass
