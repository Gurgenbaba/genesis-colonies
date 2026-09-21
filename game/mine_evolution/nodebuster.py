"""Nodebuster-style Mine Ascension V1.

One production mine is one independent prestige loop:
push depth -> Ascend -> reset selected mine -> earn permanent points -> buy
reconstruction/rebuild/output upgrades -> push deeper next run.

All mutations are server-authoritative and planet-scoped.
"""

from __future__ import annotations

import sqlite3
import time
from decimal import Decimal
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

# Breakthrough V2: expensive, one-rank mechanics that change the prestige loop
# instead of only adding another flat percentage.  Tail deltas are stored as
# hundredths so q4.00 -> q4.10 -> q4.20 never depends on binary-float state.
CORE_RESONANCE_TAIL_POWER_HUNDREDTHS = 10
SINGULARITY_TAIL_POWER_HUNDREDTHS = 10
LEGACY_RECONSTRUCTION_BEST_BPS = 3500
BREAKTHROUGH_WINDOW_LEVELS = 25

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
    "deep_storage": {
        "max_rank": 10,
        "base_cost": 1,
        "cost_step_every": 2,
        "kind": "storage",
    },
    "optimized_energy": {
        "max_rank": 10,
        "base_cost": 1,
        "cost_step_every": 2,
        "kind": "energy_efficiency",
        "utility": True,
    },
    "load_balancing": {
        "max_rank": 10,
        "base_cost": 1,
        "cost_step_every": 2,
        "kind": "energy_shortage",
        "utility": True,
        "requires": {"optimized_energy": 3},
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
            "deep_storage": 5,
        },
    },
    "core_resonance": {
        "max_rank": 1,
        "base_cost": 15,
        "cost_step_every": 1,
        "kind": "breakthrough_tail",
        "requires": {"deep_yield": 8},
        "requires_best_depth": 300,
        "breakthrough": True,
    },
    "legacy_reconstruction": {
        "max_rank": 1,
        "base_cost": 20,
        "cost_step_every": 1,
        "kind": "breakthrough_restart",
        "requires": {"reconstruction": 8},
        "requires_best_depth": 400,
        "breakthrough": True,
    },
    "breakthrough_window": {
        "max_rank": 1,
        "base_cost": 24,
        "cost_step_every": 1,
        "kind": "breakthrough_rebuild",
        "requires": {"frugal_rebuild": 8, "rapid_rebuild": 8},
        "requires_best_depth": 400,
        "breakthrough": True,
    },
    "singularity_excavation": {
        "max_rank": 1,
        "base_cost": 36,
        "cost_step_every": 1,
        "kind": "breakthrough_tail",
        "requires": {"core_resonance": 1, "overdrive": 3},
        "requires_best_depth": 500,
        "breakthrough": True,
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


def skill_prerequisites_met(
    skill_key: str,
    skills: Dict[str, int],
    state: Optional[Dict[str, int]] = None,
) -> bool:
    cfg = SKILL_CATALOG.get(str(skill_key or ""))
    if not cfg:
        return False
    req = cfg.get("requires") or {}
    if not all(int(skills.get(key, 0) or 0) >= int(rank) for key, rank in req.items()):
        return False
    required_depth = max(0, int(cfg.get("requires_best_depth") or 0))
    if required_depth > 0:
        if state is None or int(state.get("best_depth") or 0) < required_depth:
            return False
    return True


def tail_power_bonus_hundredths(skills: Dict[str, int]) -> int:
    """Personal q-tail increase for one mine: q4.00 -> q4.10 -> q4.20."""
    core = 1 if int(skills.get("core_resonance", 0) or 0) > 0 else 0
    singularity = 1 if int(skills.get("singularity_excavation", 0) or 0) > 0 else 0
    return (
        core * CORE_RESONANCE_TAIL_POWER_HUNDREDTHS
        + singularity * SINGULARITY_TAIL_POWER_HUNDREDTHS
    )


def rebuild_window_extra_levels(skills: Dict[str, int]) -> int:
    return BREAKTHROUGH_WINDOW_LEVELS if int(skills.get("breakthrough_window", 0) or 0) > 0 else 0


def reset_start_level(skills: Dict[str, int], best_depth: int = 0) -> int:
    reconstruction = max(0, int(skills.get("reconstruction", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    base = reconstruction * 10 + overdrive * 10
    if int(skills.get("legacy_reconstruction", 0) or 0) > 0:
        lifetime_best = max(0, int(best_depth or 0))
        legacy = (lifetime_best * LEGACY_RECONSTRUCTION_BEST_BPS) // 10000
        base = max(base, legacy)
    # Ascension must always restart below the L200 activation threshold.
    return min(ASCENSION_MIN_LEVEL - 1, base)


def rebuild_cost_bps(skills: Dict[str, int]) -> int:
    frugal = max(0, int(skills.get("frugal_rebuild", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    return max(5000, 10000 - 400 * frugal - 200 * overdrive)


def rebuild_time_bps(skills: Dict[str, int]) -> int:
    rapid = max(0, int(skills.get("rapid_rebuild", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    return max(4500, 10000 - 500 * rapid - 200 * overdrive)


def energy_draw_bps(skills: Dict[str, int]) -> int:
    """Per-mine Ascension draw factor. Rank 10 means 80% of normal draw."""
    rank = max(0, min(10, int(skills.get("optimized_energy", 0) or 0)))
    return max(8000, 10000 - 200 * rank)


def shortage_recovery_bps(skills: Dict[str, int]) -> int:
    """Share of missing grid efficiency recovered by this mine (max 25%)."""
    rank = max(0, min(10, int(skills.get("load_balancing", 0) or 0)))
    return min(2500, 250 * rank)


def effective_shortage_ratio_bps(base_ratio_bps: int, skills: Dict[str, int]) -> int:
    base = max(0, min(10000, int(base_ratio_bps or 0)))
    missing = 10000 - base
    recovery = shortage_recovery_bps(skills)
    return min(10000, base + (missing * recovery) // 10000)


def production_bonus_bps(skills: Dict[str, int]) -> int:
    yield_rank = max(0, int(skills.get("deep_yield", 0) or 0))
    overdrive = max(0, int(skills.get("overdrive", 0) or 0))
    return 250 * yield_rank + 500 * overdrive


def storage_bonus_bps(skills: Dict[str, int]) -> int:
    storage_rank = max(0, int(skills.get("deep_storage", 0) or 0))
    return 500 * storage_rank


def storage_multiplier_bps(skills: Dict[str, int]) -> int:
    return 10000 + storage_bonus_bps(skills)


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


def storage_multiplier_bps_for(
    planet_id: int,
    building_type: str,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> int:
    return storage_multiplier_bps(
        get_skills(int(planet_id), building_type, conn=conn, profiles=profiles)
    )


def energy_draw_bps_for(
    planet_id: int,
    building_type: str,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> int:
    return energy_draw_bps(
        get_skills(int(planet_id), building_type, conn=conn, profiles=profiles)
    )


def shortage_recovery_bps_for(
    planet_id: int,
    building_type: str,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> int:
    return shortage_recovery_bps(
        get_skills(int(planet_id), building_type, conn=conn, profiles=profiles)
    )


def _tail_power_display(bonus_hundredths: int) -> float:
    from ..production_formula import ENDGAME_PRODUCTION_TAIL_POWER

    return round(float(ENDGAME_PRODUCTION_TAIL_POWER) + int(bonus_hundredths) / 100.0, 2)


def _tail_step_preview(
    from_bonus_hundredths: int,
    to_bonus_hundredths: int,
    *,
    levels: Tuple[int, ...] = (300, 500, 1000),
) -> list[Dict[str, Any]]:
    from ..production_formula import (
        ENDGAME_PRODUCTION_PIVOT_LEVEL,
        ENDGAME_PRODUCTION_TAIL_POWER,
        endgame_tail_mine_output_decimal,
    )

    base = Decimal(int(ENDGAME_PRODUCTION_TAIL_POWER))
    before_power = base + Decimal(int(from_bonus_hundredths)) / Decimal(100)
    after_power = base + Decimal(int(to_bonus_hundredths)) / Decimal(100)
    out: list[Dict[str, Any]] = []
    for level in levels:
        before = endgame_tail_mine_output_decimal(
            "metal",
            int(level),
            pivot_level=ENDGAME_PRODUCTION_PIVOT_LEVEL,
            tail_power=before_power,
        )
        after = endgame_tail_mine_output_decimal(
            "metal",
            int(level),
            pivot_level=ENDGAME_PRODUCTION_PIVOT_LEVEL,
            tail_power=after_power,
        )
        pct = 0.0 if before <= 0 else (float(after / before) - 1.0) * 100.0
        out.append({"level": int(level), "pct": round(pct, 1)})
    return out


def rebuild_bps_for_target(
    planet_id: int,
    building_type: str,
    target_level: int,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[int, int]:
    """Exact rebuild cost/time basis points for one target level."""
    bt = str(building_type or "")
    if not is_evolvable_mine(bt):
        return 10000, 10000
    data = profiles if profiles is not None else get_profiles_for_planet(int(planet_id), conn=conn)
    state = get_state(int(planet_id), bt, conn=conn, profiles=data)
    if int(state.get("ascension_count") or 0) <= 0:
        return 10000, 10000
    skills = get_skills(int(planet_id), bt, conn=conn, profiles=data)
    rebuild_limit = int(state.get("best_depth") or 0) + rebuild_window_extra_levels(skills)
    if int(target_level or 0) > rebuild_limit:
        return 10000, 10000
    return int(rebuild_cost_bps(skills)), int(rebuild_time_bps(skills))


def rebuild_modifiers_for_target(
    planet_id: int,
    building_type: str,
    target_level: int,
    *,
    conn=None,
    profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[float, float]:
    """Float compatibility wrapper around the exact target-aware basis points."""
    cost_bps, time_bps = rebuild_bps_for_target(
        int(planet_id),
        str(building_type),
        int(target_level),
        conn=conn,
        profiles=profiles,
    )
    return cost_bps / 10000.0, time_bps / 10000.0


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
        available = rank < max_rank and skill_prerequisites_met(key, skills, state)
        row: Dict[str, Any] = {
            "key": key,
            "rank": rank,
            "max_rank": max_rank,
            "cost": cost,
            "available": available,
            "affordable": available and int(state["points_unspent"]) >= int(cost),
            "requires": dict(cfg.get("requires") or {}),
            "requires_best_depth": max(0, int(cfg.get("requires_best_depth") or 0)),
            "breakthrough": bool(cfg.get("breakthrough")),
            "utility": bool(cfg.get("utility")),
            "kind": str(cfg.get("kind") or ""),
        }

        preview_skills = dict(skills)
        preview_skills[key] = min(max_rank, rank + 1)
        if key == "optimized_energy":
            row["preview"] = {
                "draw_reduction_now_pct": round((10000 - energy_draw_bps(skills)) / 100.0, 1),
                "draw_reduction_next_pct": round((10000 - energy_draw_bps(preview_skills)) / 100.0, 1),
            }
        elif key == "load_balancing":
            example_grid_bps = 6000
            row["preview"] = {
                "grid_example_pct": 60,
                "effective_now_pct": round(effective_shortage_ratio_bps(example_grid_bps, skills) / 100.0, 1),
                "effective_next_pct": round(effective_shortage_ratio_bps(example_grid_bps, preview_skills) / 100.0, 1),
            }
        elif key == "core_resonance":
            current_tail = tail_power_bonus_hundredths(skills)
            target_tail = max(current_tail, CORE_RESONANCE_TAIL_POWER_HUNDREDTHS)
            row["preview"] = {
                "tail_from": _tail_power_display(current_tail),
                "tail_to": _tail_power_display(target_tail),
                "levels": _tail_step_preview(current_tail, target_tail),
            }
        elif key == "singularity_excavation":
            current_tail = max(CORE_RESONANCE_TAIL_POWER_HUNDREDTHS, tail_power_bonus_hundredths(skills))
            target_tail = max(
                current_tail,
                CORE_RESONANCE_TAIL_POWER_HUNDREDTHS + SINGULARITY_TAIL_POWER_HUNDREDTHS,
            )
            row["preview"] = {
                "tail_from": _tail_power_display(current_tail),
                "tail_to": _tail_power_display(target_tail),
                "levels": _tail_step_preview(current_tail, target_tail),
            }
        elif key == "legacy_reconstruction":
            best_for_preview = max(int(state["best_depth"]), lvl)
            without = dict(skills)
            without["legacy_reconstruction"] = 0
            with_legacy = dict(skills)
            with_legacy["legacy_reconstruction"] = 1
            row["preview"] = {
                "restart_before": reset_start_level(without, best_for_preview),
                "restart_after": reset_start_level(with_legacy, best_for_preview),
                "best_depth": best_for_preview,
            }
        elif key == "breakthrough_window":
            best_depth = int(state["best_depth"])
            row["preview"] = {
                "window_before": best_depth,
                "window_after": best_depth + BREAKTHROUGH_WINDOW_LEVELS,
                "cost_reduction_pct": int(round((1.0 - rebuild_cost_multiplier(skills)) * 100)),
                "time_reduction_pct": int(round((1.0 - rebuild_time_multiplier(skills)) * 100)),
            }
        skill_rows.append(row)

    from ..production_formula import ENDGAME_PRODUCTION_TAIL_POWER
    effective_tail_power = (
        float(ENDGAME_PRODUCTION_TAIL_POWER)
        + tail_power_bonus_hundredths(skills) / 100.0
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
        "nodebuster_reset_level": int(
            reset_start_level(skills, max(int(state["best_depth"]), lvl))
        ),
        "nodebuster_next_depth": int(next_depth),
        "nodebuster_tail_power_bonus_hundredths": int(tail_power_bonus_hundredths(skills)),
        "nodebuster_tail_power": round(effective_tail_power, 2),
        "nodebuster_rebuild_window_extra_levels": int(rebuild_window_extra_levels(skills)),
        "nodebuster_rebuild_window_level": int(state["best_depth"]) + rebuild_window_extra_levels(skills),
        "nodebuster_rebuild_cost_pct": int(round((1.0 - rebuild_cost_multiplier(skills)) * 100)),
        "nodebuster_rebuild_time_pct": int(round((1.0 - rebuild_time_multiplier(skills)) * 100)),
        "nodebuster_production_bonus_pct": round((production_multiplier(skills) - 1.0) * 100.0, 2),
        "nodebuster_storage_bonus_pct": storage_bonus_bps(skills) / 100.0,
        "nodebuster_energy_draw_reduction_pct": (10000 - energy_draw_bps(skills)) / 100.0,
        "nodebuster_shortage_recovery_pct": shortage_recovery_bps(skills) / 100.0,
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
        best_depth = max(int(state["best_depth"]), level)
        restart = reset_start_level(skills, best_depth)

        buildings[bt] = int(restart)
        save_planet_buildings(planet_id, buildings, conn=conn)

        new_count = int(state["ascension_count"]) + 1
        new_earned = int(state["points_earned"]) + int(gain)
        new_unspent = int(state["points_unspent"]) + int(gain)
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

        if not skill_prerequisites_met(skill, skills, state):
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
            "reset_level": reset_start_level(updated_skills, int(state.get("best_depth") or 0)),
            "tail_power_bonus_hundredths": tail_power_bonus_hundredths(updated_skills),
            "tail_power": 4.0 + tail_power_bonus_hundredths(updated_skills) / 100.0,
            "rebuild_window_extra_levels": rebuild_window_extra_levels(updated_skills),
            "rebuild_window_level": int(state.get("best_depth") or 0) + rebuild_window_extra_levels(updated_skills),
            "rebuild_cost_pct": int(round((1.0 - rebuild_cost_multiplier(updated_skills)) * 100)),
            "rebuild_time_pct": int(round((1.0 - rebuild_time_multiplier(updated_skills)) * 100)),
            "production_bonus_pct": round((production_multiplier(updated_skills) - 1.0) * 100.0, 2),
            "storage_bonus_pct": storage_bonus_bps(updated_skills) / 100.0,
        }
    except Exception:
        try:
            rollback(conn)
        except Exception:
            pass
        raise
    finally:
        conn.close()
