"""Nodebuster-style Mine Ascension V1.

One production mine is one independent prestige loop:
push depth -> Ascend -> reset selected mine -> earn permanent points -> buy
reconstruction/rebuild/output upgrades -> push deeper next run.

All mutations are server-authoritative and planet-scoped.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from ..db import (
    begin_write_transaction,
    commit,
    lock_planet_for_update,
    rollback,
    table_exists,
)
from ..models import db, get_build_queue_rows, get_planet_buildings, save_planet_buildings
from .formulas import EVOLVABLE_MINES, is_evolvable_mine

ASCENSION_MIN_LEVEL = 200
QUEUE_SAFETY_SENTINEL = 2_147_483_647

SKILL_CATALOG: Dict[str, Dict[str, Any]] = {
    "reconstruction": {
        "max_rank": 10,
        "base_cost": 1,
        "cost_step_every": 2,
        "kind": "reset_start",
    },
    "frugal_rebuild": {
        "max_rank": 10,
        "base_cost": 1,
        "cost_step_every": 2,
        "kind": "rebuild_cost",
    },
    "rapid_rebuild": {
        "max_rank": 10,
        "base_cost": 1,
        "cost_step_every": 2,
        "kind": "rebuild_time",
    },
    "deep_yield": {
        "max_rank": 10,
        "base_cost": 2,
        "cost_step_every": 2,
        "kind": "production",
    },
    "overdrive": {
        "max_rank": 3,
        "base_cost": 5,
        "cost_step_every": 1,
        "cost_step": 3,
        "kind": "capstone",
        "requires": {
            "reconstruction": 5,
            "frugal_rebuild": 5,
            "rapid_rebuild": 5,
            "deep_yield": 5,
        },
    },
}


def schema_ready(conn) -> bool:
    return bool(
        table_exists(conn, "planet_mine_ascension_state")
        and table_exists(conn, "planet_mine_ascension_skills")
    )


def _empty_state() -> Dict[str, int]:
    return {
        "ascension_count": 0,
        "points_earned": 0,
        "points_unspent": 0,
        "best_depth": 0,
        "last_depth": 0,
    }


def _request_cache() -> Optional[Dict[int, Dict[str, Any]]]:
    try:
        from flask import g, has_request_context
        from ..db import get_db_backend

        if get_db_backend() != "postgres" or not has_request_context():
            return None
        cache = getattr(g, "gc_nodebuster_mine_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            g.gc_nodebuster_mine_cache = cache
        return cache
    except Exception:
        return None


def _invalidate_request_cache(planet_id: int) -> None:
    cache = _request_cache()
    if cache is not None:
        cache.pop(int(planet_id), None)


def get_profiles_for_planet(planet_id: int, *, conn=None) -> Dict[str, Dict[str, Any]]:
    pid = int(planet_id)
    cache = _request_cache()
    if cache is not None and pid in cache:
        return {
            key: {
                "state": dict(value["state"]),
                "skills": dict(value["skills"]),
            }
            for key, value in cache[pid].items()
        }

    out: Dict[str, Dict[str, Any]] = {
        key: {"state": _empty_state(), "skills": {skill: 0 for skill in SKILL_CATALOG}}
        for key in EVOLVABLE_MINES
    }
    own = conn is None
    if own:
        conn = db()
    try:
        if not schema_ready(conn):
            return out

        cur = conn.cursor()
        cur.execute(
            """
            SELECT building_type, ascension_count, points_earned, points_unspent,
                   best_depth, last_depth
            FROM planet_mine_ascension_state
            WHERE planet_id = ?;
            """,
            (pid,),
        )
        for row in cur.fetchall():
            data = dict(row)
            bt = str(data.get("building_type") or "")
            if bt not in out:
                continue
            out[bt]["state"] = {
                "ascension_count": max(0, int(data.get("ascension_count") or 0)),
                "points_earned": max(0, int(data.get("points_earned") or 0)),
                "points_unspent": max(0, int(data.get("points_unspent") or 0)),
                "best_depth": max(0, int(data.get("best_depth") or 0)),
                "last_depth": max(0, int(data.get("last_depth") or 0)),
            }

        cur.execute(
            """
            SELECT building_type, skill_key, skill_rank
            FROM planet_mine_ascension_skills
            WHERE planet_id = ?;
            """,
            (pid,),
        )
        for row in cur.fetchall():
            data = dict(row)
            bt = str(data.get("building_type") or "")
            skill = str(data.get("skill_key") or "")
            if bt in out and skill in SKILL_CATALOG:
                out[bt]["skills"][skill] = max(0, int(data.get("skill_rank") or 0))

        if cache is not None:
            cache[pid] = {
                key: {
                    "state": dict(value["state"]),
                    "skills": dict(value["skills"]),
                }
                for key, value in out.items()
            }
        return out
    finally:
        if own:
            conn.close()


def get_state(
    planet_id: int,
    building_type: str,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, int]:
    bt = str(building_type or "")
    if not is_evolvable_mine(bt):
        return _empty_state()
    data = profiles if profiles is not None else get_profiles_for_planet(int(planet_id), conn=conn)
    return dict((data.get(bt) or {}).get("state") or _empty_state())


def get_skills(
    planet_id: int,
    building_type: str,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, int]:
    bt = str(building_type or "")
    base = {skill: 0 for skill in SKILL_CATALOG}
    if not is_evolvable_mine(bt):
        return base
    data = profiles if profiles is not None else get_profiles_for_planet(int(planet_id), conn=conn)
    stored = (data.get(bt) or {}).get("skills") or {}
    for skill in base:
        base[skill] = max(0, int(stored.get(skill, 0) or 0))
    return base


def ascension_points_for_depth(level: int) -> int:
    """Permanent points awarded for one run.

    L200=1, then +1 per 25 levels and one extra depth point per full 100 levels
    beyond the first Ascension threshold. No hard upper bound.
    """
    depth = int(level or 0)
    if depth < ASCENSION_MIN_LEVEL:
        return 0
    above = depth - ASCENSION_MIN_LEVEL
    return 1 + (above // 25) + (above // 100)


def skill_point_cost(skill_key: str, current_rank: int) -> int:
    cfg = SKILL_CATALOG.get(str(skill_key or ""))
    if not cfg:
        return 0
    rank = max(0, int(current_rank or 0))
    base = int(cfg.get("base_cost") or 1)
    every = max(1, int(cfg.get("cost_step_every") or 1))
    step = max(1, int(cfg.get("cost_step") or 1))
    return base + (rank // every) * step


def skill_prerequisites_met(skill_key: str, skills: Dict[str, int]) -> bool:
    cfg = SKILL_CATALOG.get(str(skill_key or ""))
    if not cfg:
        return False
    req = cfg.get("requires") or {}
    return all(int(skills.get(key, 0) or 0) >= int(rank) for key, rank in req.items())


def reset_start_level(skills: Dict[str, int]) -> int:
    reconstruction = max(0, int(skills.get("reconstruction", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    # At V1 cap: 100 reconstruction + 30 capstone = L130 restart.
    return min(ASCENSION_MIN_LEVEL - 1, reconstruction * 10 + overdrive * 10)


def rebuild_cost_bps(skills: Dict[str, int]) -> int:
    frugal = max(0, int(skills.get("frugal_rebuild", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    return max(5000, 10000 - 400 * frugal - 200 * overdrive)


def rebuild_time_bps(skills: Dict[str, int]) -> int:
    rapid = max(0, int(skills.get("rapid_rebuild", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    return max(4500, 10000 - 500 * rapid - 200 * overdrive)


def production_bonus_bps(skills: Dict[str, int]) -> int:
    yield_rank = max(0, int(skills.get("deep_yield", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    return 250 * yield_rank + 500 * overdrive


def rebuild_cost_multiplier(skills: Dict[str, int]) -> float:
    return rebuild_cost_bps(skills) / 10000.0


def rebuild_time_multiplier(skills: Dict[str, int]) -> float:
    return rebuild_time_bps(skills) / 10000.0


def production_multiplier(skills: Dict[str, int]) -> float:
    return 1.0 + production_bonus_bps(skills) / 10000.0


def production_multiplier_for(
    planet_id: int,
    building_type: str,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> float:
    return production_multiplier(
        get_skills(int(planet_id), building_type, conn=conn, profiles=profiles)
    )


def rebuild_modifiers_for_target(
    planet_id: int,
    building_type: str,
    target_level: int,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[float, float]:
    """Cost/time multipliers while rebuilding through the lifetime best depth."""
    bt = str(building_type or "")
    if not is_evolvable_mine(bt):
        return 1.0, 1.0
    data = profiles if profiles is not None else get_profiles_for_planet(int(planet_id), conn=conn)
    state = get_state(int(planet_id), bt, conn=conn, profiles=data)
    if int(state.get("ascension_count") or 0) <= 0:
        return 1.0, 1.0
    if int(target_level or 0) > int(state.get("best_depth") or 0):
        return 1.0, 1.0
    skills = get_skills(int(planet_id), bt, conn=conn, profiles=data)
    return rebuild_cost_bps(skills) / 10000.0, rebuild_time_bps(skills) / 10000.0


def score_level(
    planet_id: int,
    building_type: str,
    current_level: int,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> int:
    """Lifetime high-water mark used by progression score after a reset."""
    bt = str(building_type or "")
    current = max(0, int(current_level or 0))
    if not is_evolvable_mine(bt):
        return current
    state = get_state(int(planet_id), bt, conn=conn, profiles=profiles)
    return max(current, int(state.get("best_depth") or 0))


def panel_fields(
    planet_id: int,
    building_type: str,
    level: int,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    bt = str(building_type or "")
    if not is_evolvable_mine(bt):
        return {"mine_evolution": False}

    data = profiles if profiles is not None else get_profiles_for_planet(int(planet_id), conn=conn)
    state = get_state(int(planet_id), bt, conn=conn, profiles=data)
    skills = get_skills(int(planet_id), bt, conn=conn, profiles=data)
    lvl = max(0, int(level or 0))
    gain = ascension_points_for_depth(lvl)
    next_depth = max(ASCENSION_MIN_LEVEL, lvl + 25)
    skill_rows = []
    for key, cfg in SKILL_CATALOG.items():
        rank = int(skills.get(key, 0) or 0)
        max_rank = int(cfg["max_rank"])
        cost = 0 if rank >= max_rank else skill_point_cost(key, rank)
        available = rank < max_rank and skill_prerequisites_met(key, skills)
        skill_rows.append(
            {
                "key": key,
                "rank": rank,
                "max_rank": max_rank,
                "cost": cost,
                "available": available,
                "affordable": available and int(state["points_unspent"]) >= int(cost),
                "requires": dict(cfg.get("requires") or {}),
            }
        )

    return {
        "mine_evolution": True,
        "evolution_rank": int(state["ascension_count"]),
        "evolution_roman": str(int(state["ascension_count"])) if state["ascension_count"] else "",
        "evolution_next_roman": str(int(state["ascension_count"]) + 1),
        "evolution_required_level": ASCENSION_MIN_LEVEL,
        "evolution_can_evolve": lvl >= ASCENSION_MIN_LEVEL,
        "evolution_progress_pct": min(100, (lvl * 100) // ASCENSION_MIN_LEVEL),
        "evolution_uncapped": True,
        "evolution_bonus_pct": round((production_multiplier(skills) - 1.0) * 100.0, 2),
        "evolution_next_bonus_pct": round((production_multiplier(skills) - 1.0) * 100.0, 2),
        "evolution_bonus_gain_pct": 0.0,
        "evolution_tribute_metal": 0,
        "evolution_tribute_crystal": 0,
        "nodebuster": True,
        "nodebuster_points_gain": int(gain),
        "nodebuster_points_unspent": int(state["points_unspent"]),
        "nodebuster_points_earned": int(state["points_earned"]),
        "nodebuster_best_depth": int(state["best_depth"]),
        "nodebuster_last_depth": int(state["last_depth"]),
        "nodebuster_reset_level": int(reset_start_level(skills)),
        "nodebuster_next_depth": int(next_depth),
        "nodebuster_rebuild_cost_pct": int(round((1.0 - rebuild_cost_multiplier(skills)) * 100)),
        "nodebuster_rebuild_time_pct": int(round((1.0 - rebuild_time_multiplier(skills)) * 100)),
        "nodebuster_production_bonus_pct": round((production_multiplier(skills) - 1.0) * 100.0, 2),
        "nodebuster_skills": skill_rows,
    }


def ascend_mine(
    user_id: int,
    planet: dict,
    building_type: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    bt = str(building_type or "").strip()
    if not is_evolvable_mine(bt):
        return False, "invalid_building", {"msg": "Not an evolvable mine"}

    planet_id = int(planet["id"])
    if int(planet.get("player_id") or 0) != int(user_id):
        return False, "forbidden", {"msg": "Planet not owned"}

    from ..options import vacation_blocks_outbound

    conn = db()
    try:
        ok_vacation, vac_reason = vacation_blocks_outbound(int(user_id), conn=conn)
        if not ok_vacation:
            return False, vac_reason, {}

        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)

        if not schema_ready(conn):
            rollback(conn)
            return False, "schema_missing", {"msg": "Nodebuster Ascension schema not applied"}

        from ..queue_engine import finish_due_work

        now = time.time()
        finish_due_work(
            player_id=int(user_id),
            planet_id=planet_id,
            now=now,
            conn=conn,
            source="action",
            recalc_ranks=False,
        )

        # Settle production through the exact Ascension cutover while the old
        # run level is still authoritative. Nodebuster has no Tribute spend,
        # so it must not rely on try_spend_resources_conn to perform this tick.
        from ..resources import update_planet_resources

        update_planet_resources(
            dict(planet),
            conn=conn,
            skip_queue_finish=True,
            persist=True,
        )

        buildings = get_planet_buildings(planet_id, conn=conn)
        level = int(buildings.get(bt, 0) or 0)
        if level < ASCENSION_MIN_LEVEL:
            rollback(conn)
            return False, "level_too_low", {
                "level": level,
                "required": ASCENSION_MIN_LEVEL,
            }

        pending = [
            row for row in get_build_queue_rows(planet_id, conn=conn)
            if str(row["building_type"]) == bt
        ]
        if pending:
            rollback(conn)
            return False, "queue_pending", {"pending": len(pending)}

        profiles = get_profiles_for_planet(planet_id, conn=conn)
        state = get_state(planet_id, bt, conn=conn, profiles=profiles)
        skills = get_skills(planet_id, bt, conn=conn, profiles=profiles)
        gain = ascension_points_for_depth(level)
        restart = reset_start_level(skills)

        buildings[bt] = int(restart)
        save_planet_buildings(planet_id, buildings, conn=conn)

        new_count = int(state["ascension_count"]) + 1
        new_earned = int(state["points_earned"]) + int(gain)
        new_unspent = int(state["points_unspent"]) + int(gain)
        best_depth = max(int(state["best_depth"]), level)

        conn.execute(
            """
            INSERT INTO planet_mine_ascension_state (
                planet_id, building_type, ascension_count, points_earned,
                points_unspent, best_depth, last_depth, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(planet_id, building_type) DO UPDATE SET
                ascension_count = excluded.ascension_count,
                points_earned = excluded.points_earned,
                points_unspent = excluded.points_unspent,
                best_depth = excluded.best_depth,
                last_depth = excluded.last_depth,
                updated_at = excluded.updated_at;
            """,
            (
                planet_id,
                bt,
                new_count,
                new_earned,
                new_unspent,
                best_depth,
                level,
                float(now),
            ),
        )
        commit(conn)
        _invalidate_request_cache(planet_id)

        from ..effects.effect_resolver import clear_effect_resolver_cache
        from ..ranking import invalidate_player_score_cache

        clear_effect_resolver_cache(int(user_id))
        invalidate_player_score_cache(int(user_id))

        return True, "ok", {
            "building_type": bt,
            "ascended_from_level": level,
            "level": restart,
            "evolution_rank": new_count,
            "points_gain": gain,
            "points_earned": new_earned,
            "points_unspent": new_unspent,
            "best_depth": best_depth,
            "reset_level": restart,
            "production_bonus_pct": round((production_multiplier(skills) - 1.0) * 100.0, 2),
        }
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        conn.close()


def purchase_skill(
    user_id: int,
    planet: dict,
    building_type: str,
    skill_key: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    bt = str(building_type or "").strip()
    skill = str(skill_key or "").strip()
    cfg = SKILL_CATALOG.get(skill)
    if not is_evolvable_mine(bt) or not cfg:
        return False, "invalid_skill", {}

    planet_id = int(planet["id"])
    if int(planet.get("player_id") or 0) != int(user_id):
        return False, "forbidden", {}

    conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)
        if not schema_ready(conn):
            rollback(conn)
            return False, "schema_missing", {}

        profiles = get_profiles_for_planet(planet_id, conn=conn)
        state = get_state(planet_id, bt, conn=conn, profiles=profiles)
        skills = get_skills(planet_id, bt, conn=conn, profiles=profiles)
        current = int(skills.get(skill, 0) or 0)
        max_rank = int(cfg["max_rank"])
        if current >= max_rank:
            rollback(conn)
            return False, "skill_max", {"skill_key": skill, "rank": current}

        if not skill_prerequisites_met(skill, skills):
            rollback(conn)
            return False, "skill_prerequisite", {
                "skill_key": skill,
                "requires": dict(cfg.get("requires") or {}),
            }

        cost = skill_point_cost(skill, current)
        unspent = int(state.get("points_unspent") or 0)
        if unspent < cost:
            rollback(conn)
            return False, "insufficient_points", {
                "skill_key": skill,
                "cost": cost,
                "points_unspent": unspent,
            }

        new_rank = current + 1
        new_unspent = unspent - cost
        now = time.time()
        conn.execute(
            """
            INSERT INTO planet_mine_ascension_skills (
                planet_id, building_type, skill_key, skill_rank, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(planet_id, building_type, skill_key) DO UPDATE SET
                skill_rank = excluded.skill_rank,
                updated_at = excluded.updated_at;
            """,
            (planet_id, bt, skill, new_rank, float(now)),
        )
        conn.execute(
            """
            UPDATE planet_mine_ascension_state
            SET points_unspent = ?, updated_at = ?
            WHERE planet_id = ? AND building_type = ?;
            """,
            (new_unspent, float(now), planet_id, bt),
        )
        commit(conn)
        _invalidate_request_cache(planet_id)

        from ..effects.effect_resolver import clear_effect_resolver_cache

        clear_effect_resolver_cache(int(user_id))

        updated_skills = dict(skills)
        updated_skills[skill] = new_rank
        return True, "ok", {
            "building_type": bt,
            "skill_key": skill,
            "skill_rank": new_rank,
            "skill_cost": cost,
            "points_unspent": new_unspent,
            "reset_level": reset_start_level(updated_skills),
            "rebuild_cost_pct": int(round((1.0 - rebuild_cost_multiplier(updated_skills)) * 100)),
            "rebuild_time_pct": int(round((1.0 - rebuild_time_multiplier(updated_skills)) * 100)),
            "production_bonus_pct": round((production_multiplier(updated_skills) - 1.0) * 100.0, 2),
        }
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        conn.close()
