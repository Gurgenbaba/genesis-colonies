"""
Forschungs-Logik für Genesis Colonies.

- Research-Konfiguration (RESEARCH_TECHS)
- Kosten- und Zeit-Berechnung
- Requirement-Checks
- Research-Queue (Starten)
- Finish-Handling läuft über queue_engine.finish_due_work (zentral)
- Cache invalidieren nach Finish (ranking.invalidate_player_score_cache)

WICHTIG:
- Dieses Modul enthält keine Flask- oder Template-Logik.
- Multi-User-safe: Finish/Start sind defensiv und robust.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Tuple, List, Any, Optional

logger = logging.getLogger(__name__)

from .models import (
    db,
    get_game_settings,
    get_research_levels,
    get_research_queue_rows,
    add_research_job,
    delete_research_job,
    get_homeworld,
    get_planet_buildings,
    try_spend_resources_conn,
)
from .i18n import tr
from .db import begin_write_transaction, commit, rollback, lock_planet_for_update, lock_player_for_update
from .ranking import invalidate_player_score_cache  # ✅ Cache invalidieren nach Finish


# ======================================================================
# TECH CONFIG
# ======================================================================

RESEARCH_TECHS: Dict[str, Dict[str, Any]] = {
    "energy_tech": {
        "label_key": "energy_tech",
        "description_key": "desc_energy_tech",
        "category": "energy",
        "icon": "energieeffizienz.png",
        "base_cost_m": 1000,
        "base_cost_c": 500,
        "base_time": 840,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "mining_tech": {
        "label_key": "mining_tech",
        "description_key": "desc_mining_tech",
        "category": "metal",
        "icon": "metallveredelung.png",
        "base_cost_m": 1000,
        "base_cost_c": 500,
        "base_time": 910,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "crystal_tech": {
        "label_key": "crystal_tech",
        "description_key": "desc_crystal_tech",
        "category": "crystal",
        "icon": "crytite-synthese.png",
        "base_cost_m": 1000,
        "base_cost_c": 500,
        "base_time": 910,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "buildtime_tech": {
        "label_key": "buildtime_tech",
        "description_key": "desc_buildtime_tech",
        "category": "construction",
        "icon": "bauoptimierung.png",
        "base_cost_m": 1250,
        "base_cost_c": 750,
        "base_time": 980,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "storage_tech": {
        "label_key": "storage_tech",
        "description_key": "desc_storage_tech",
        "category": "storage",
        "icon": "lagertechnik.png",
        "base_cost_m": 500,
        "base_cost_c": 500,
        "base_time": 770,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "drone_tech": {
        "label_key": "research_drones_tech",
        "description_key": "desc_research_drones_tech",
        "category": "drones",
        "icon": "drohnenoptimierung.png",
        "base_cost_m": 1500,
        "base_cost_c": 1000,
        "base_time": 1050,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "navigation_tech": {
        "label_key": "research_navigation_tech",
        "description_key": "desc_research_navigation_tech",
        "category": "navigation",
        "icon": "hyperraum-navigation.png",
        "base_cost_m": 1250,
        "base_cost_c": 750,
        "base_time": 1260,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"drone_tech": 2}},
    },
    "engine_tech": {
        "label_key": "research_engine_tech",
        "description_key": "desc_research_engine_tech",
        "category": "engine",
        "icon": "kryo-antriebstechnik.png",
        "base_cost_m": 1500,
        "base_cost_c": 1000,
        "base_time": 1330,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"energy_tech": 2}},
    },
    "weapon_tech": {
        "label_key": "research_weapon_tech",
        "description_key": "desc_research_weapon_tech",
        "category": "weapon",
        "icon": "waffenentwicklung.png",
        "base_cost_m": 1000,
        "base_cost_c": 500,
        "base_time": 1120,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "armor_tech": {
        "label_key": "research_armor_tech",
        "description_key": "desc_research_armor_tech",
        "category": "armor",
        "icon": "panzerungstechnik.png",
        "base_cost_m": 1250,
        "base_cost_c": 750,
        "base_time": 1190,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}, "research": {"weapon_tech": 1}},
    },
    "shield_tech": {
        "label_key": "research_shield_tech",
        "description_key": "desc_research_shield_tech",
        "category": "shield",
        "icon": "schildtechnologie.png",
        "base_cost_m": 1250,
        "base_cost_c": 750,
        "base_time": 1330,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"armor_tech": 1}},
    },
    "fuel_efficiency": {
        "label_key": "research_fuel_efficiency",
        "description_key": "desc_fuel_efficiency",
        "category": "propulsion",
        "icon": "brennzellenoptimierung.png",
        "base_cost_m": 1500,
        "base_cost_c": 500,
        "base_time": 1400,
        "cost_factor": 1.75,
        "requirements": {"buildings": {"research_lab": 2}, "research": {"energy_tech": 1}},
    },
    "interstellar_expansion": {
        "label_key": "research_interstellar_expansion",
        "description_key": "desc_research_interstellar_expansion",
        "category": "expansion",
        "icon": "hyperraum-navigation.png",
        "base_cost_m": 2500,
        "base_cost_c": 1500,
        "base_time": 1680,
        "cost_factor": 1.85,
        "requirements": {"buildings": {"research_lab": 4}, "research": {"navigation_tech": 3}},
    },
}

# Account-wide parallel fleet movements (GC-537) — tiers by navigation_tech level.
NAVIGATION_TECH_KEY = "navigation_tech"
BASE_FLEET_SLOTS = 3
NAVIGATION_FLEET_SLOT_TIERS: Tuple[int, int, ...] = (
    (0, 3),
    (3, 4),
    (5, 5),
    (8, 6),
    (10, 7),
)
# After the last fixed tier: +1 slot every N navigation levels (13→8, 16→9, …).
NAVIGATION_FLEET_SLOT_POST_TIER_LEVEL = 10
NAVIGATION_FLEET_SLOT_POST_TIER_INTERVAL = 3


def fleet_slots_for_navigation_level(level: int) -> int:
    """Return max parallel fleet slots for a navigation_tech level (no hard cap)."""
    lvl = max(0, int(level or 0))
    slots = BASE_FLEET_SLOTS
    for min_level, tier_slots in NAVIGATION_FLEET_SLOT_TIERS:
        if lvl >= min_level:
            slots = tier_slots
    post = NAVIGATION_FLEET_SLOT_POST_TIER_LEVEL
    if lvl > post:
        slots += (lvl - post) // NAVIGATION_FLEET_SLOT_POST_TIER_INTERVAL
    return slots


def next_navigation_fleet_slot_unlock(level: int) -> Optional[Dict[str, Any]]:
    """Next navigation level that raises the fleet slot cap."""
    lvl = max(0, int(level or 0))
    current = fleet_slots_for_navigation_level(lvl)

    for min_level, tier_slots in NAVIGATION_FLEET_SLOT_TIERS:
        if min_level > lvl and tier_slots > current:
            return {
                "research_key": NAVIGATION_TECH_KEY,
                "level": min_level,
                "slots": tier_slots,
            }

    post = NAVIGATION_FLEET_SLOT_POST_TIER_LEVEL
    interval = NAVIGATION_FLEET_SLOT_POST_TIER_INTERVAL
    if lvl >= post - 1:
        if lvl < post:
            next_level = post
        else:
            steps = max(0, (lvl - post) // interval)
            next_level = post + (steps + 1) * interval
        next_slots = fleet_slots_for_navigation_level(next_level)
        if next_slots > current:
            return {
                "research_key": NAVIGATION_TECH_KEY,
                "level": next_level,
                "slots": next_slots,
            }
    return None


# Tab groups for research UI (category keys from RESEARCH_TECHS)
RESEARCH_TAB_GROUPS: Dict[str, List[str]] = {
    "energy": ["energy"],
    "production": ["metal", "crystal", "drones"],
    "construction": ["construction", "storage"],
    "fleet": ["navigation", "engine", "propulsion", "expansion"],
    "military": ["weapon", "armor", "shield"],
}


def _research_effect_snapshot(
    *,
    effect_kind: str,
    effect_current: int,
    effect_next: int,
    effect_resource: str = "",
    effect_unit: str = "",
    effect_metric_key: str = "",
) -> Dict[str, Any]:
    cur = int(effect_current or 0)
    nxt = int(effect_next or 0)
    delta = max(0, nxt - cur)
    return {
        "effect_kind": effect_kind,
        "effect_current": cur,
        "effect_next": nxt,
        "effect_delta": delta,
        "effect_resource": effect_resource,
        "effect_unit": effect_unit,
        "effect_metric_key": effect_metric_key,
    }


def _mine_energy_reduction_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.mine_energy_reduction_pct(level)


def _buildtime_speed_bonus_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.buildtime_speed_bonus_pct(level)


def _metal_prod_bonus_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.metal_prod_bonus_pct(level)


def _crystal_prod_bonus_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.crystal_prod_bonus_pct(level)


def _drone_prod_bonus_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.drone_prod_bonus_pct(level)


def _storage_bonus_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.storage_bonus_pct(level)


def _combat_bonus_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.combat_bonus_pct(level)


def _fleet_speed_bonus_pct(level: int, per_level: float) -> int:
    from .effects import EffectResolver

    return EffectResolver.fleet_speed_bonus_pct(level, per_level)


def _fuel_reduction_pct(level: int) -> int:
    from .effects import EffectResolver

    return EffectResolver.fuel_efficiency_reduction_pct(level)


def get_research_effect_preview(tech_key: str, current_level: int, next_level: int) -> Dict[str, Any]:
    """
    UI-only effect snapshot — formulas mirror EffectResolver / fleet_calc (server authority).
    """
    cur = max(0, int(current_level or 0))
    nxt = max(cur + 1, int(next_level or 0))

    if tech_key == "energy_tech":
        return _research_effect_snapshot(
            effect_kind="reduction_percent",
            effect_current=_mine_energy_reduction_pct(cur),
            effect_next=_mine_energy_reduction_pct(nxt),
            effect_metric_key="research_effect_mine_energy",
        )
    if tech_key == "mining_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_metal_prod_bonus_pct(cur),
            effect_next=_metal_prod_bonus_pct(nxt),
            effect_resource="metal",
            effect_metric_key="research_effect_metal_prod",
        )
    if tech_key == "crystal_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_crystal_prod_bonus_pct(cur),
            effect_next=_crystal_prod_bonus_pct(nxt),
            effect_resource="crystal",
            effect_metric_key="research_effect_crystal_prod",
        )
    if tech_key == "buildtime_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_buildtime_speed_bonus_pct(cur),
            effect_next=_buildtime_speed_bonus_pct(nxt),
            effect_resource="build",
            effect_metric_key="research_effect_build_time",
        )
    if tech_key == "storage_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_storage_bonus_pct(cur),
            effect_next=_storage_bonus_pct(nxt),
            effect_resource="storage",
            effect_metric_key="research_effect_storage",
        )
    if tech_key == "drone_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_drone_prod_bonus_pct(cur),
            effect_next=_drone_prod_bonus_pct(nxt),
            effect_metric_key="research_effect_prod",
        )
    if tech_key == "weapon_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_combat_bonus_pct(cur),
            effect_next=_combat_bonus_pct(nxt),
            effect_metric_key="research_effect_weapon",
        )
    if tech_key == "armor_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_combat_bonus_pct(cur),
            effect_next=_combat_bonus_pct(nxt),
            effect_metric_key="research_effect_armor",
        )
    if tech_key == "shield_tech":
        return _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_combat_bonus_pct(cur),
            effect_next=_combat_bonus_pct(nxt),
            effect_metric_key="research_effect_shield",
        )
    if tech_key == "navigation_tech":
        primary = _research_effect_snapshot(
            effect_kind="level",
            effect_current=fleet_slots_for_navigation_level(cur),
            effect_next=fleet_slots_for_navigation_level(nxt),
            effect_metric_key="research_effect_fleet_slots",
        )
        secondary = _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_fleet_speed_bonus_pct(cur, 0.03),
            effect_next=_fleet_speed_bonus_pct(nxt, 0.03),
            effect_metric_key="research_effect_fleet_speed",
        )
        primary["secondary_effect"] = secondary
        return primary
    if tech_key == "engine_tech":
        primary = _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_fleet_speed_bonus_pct(cur, 0.02),
            effect_next=_fleet_speed_bonus_pct(nxt, 0.02),
            effect_metric_key="research_effect_fleet_speed",
        )
        secondary = _research_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=_fleet_speed_bonus_pct(cur, 0.02),
            effect_next=_fleet_speed_bonus_pct(nxt, 0.02),
            effect_resource="cargo",
            effect_metric_key="research_effect_cargo",
        )
        primary["secondary_effect"] = secondary
        return primary
    if tech_key == "fuel_efficiency":
        return _research_effect_snapshot(
            effect_kind="reduction_percent",
            effect_current=_fuel_reduction_pct(cur),
            effect_next=_fuel_reduction_pct(nxt),
            effect_metric_key="research_effect_fuel_use",
        )
    if tech_key == "interstellar_expansion":
        from .planet_evolution.expansion_protocol import (
            INTERSTELLAR_EXPANSION_MAX_LEVEL,
            interstellar_expansion_reach_label,
        )

        return _research_effect_snapshot(
            effect_kind="level",
            effect_current=cur,
            effect_next=min(nxt, INTERSTELLAR_EXPANSION_MAX_LEVEL),
            effect_metric_key=interstellar_expansion_reach_label(cur),
        )

    return _research_effect_snapshot(
        effect_kind="level",
        effect_current=cur,
        effect_next=nxt,
        effect_metric_key="buildings_effect_level",
    )


# ======================================================================
# COSTS & TIME
# ======================================================================
def get_research_cost(tech_key: str, level: int) -> Tuple[int, int]:
    cfg = RESEARCH_TECHS.get(tech_key)
    if not cfg:
        return 0, 0

    from .economy_balance import research_upgrade_cost

    return research_upgrade_cost(
        int(cfg.get("base_cost_m", 1000)),
        int(cfg.get("base_cost_c", 500)),
        max(1, int(level)),
    )


def cumulative_research_resource_totals(tech_key: str, level: int) -> Dict[str, int]:
    """GC-SCORE-D — cumulative metal/crystal/fuel invested for research levels 1..level."""
    lvl = max(0, int(level or 0))
    if lvl <= 0 or tech_key not in RESEARCH_TECHS:
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    metal = 0
    crystal = 0
    for target in range(1, lvl + 1):
        m, c = get_research_cost(tech_key, target)
        metal += int(m)
        crystal += int(c)
    return {"metal": metal, "crystal": crystal, "fuel_cells": 0}


def get_research_time(
    tech_key: str,
    level: int,
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
    *,
    levels: Optional[Dict[str, int]] = None,
    conn=None,
    resolver=None,
) -> int:
    """Research duration in seconds. Prefer shared ``levels`` / ``conn`` / ``resolver`` (GC-PERF-RESEARCH-TIME-001)."""
    if tech_key not in RESEARCH_TECHS:
        return 0

    if resolver is not None:
        return int(resolver.get_research_time_seconds(tech_key, max(1, int(level))))

    if buildings is None:
        from .planet_evolution.repository import get_context_planet

        planet = get_context_planet(int(user_id), conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)

    if levels is None:
        levels = get_research_levels(int(user_id), conn=conn)

    from .effects import EffectResolver, get_effect_resolver

    if conn is not None:
        er = get_effect_resolver(
            int(user_id),
            buildings=buildings,
            research=levels,
            conn=conn,
        )
    else:
        er = EffectResolver(buildings, levels, player_id=int(user_id), conn=conn)
    return int(er.get_research_time_seconds(tech_key, max(1, int(level))))


def recalculate_research_queue_finish_times(
    user_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    """
    Reschedule account research queue after cancel or before enqueue.
    In-progress first job keeps its window; followers chain from its finish or now.
    """
    uid = int(user_id)
    ts = float(now if now is not None else time.time())
    rows = get_research_queue_rows(uid, conn=conn)
    if not rows:
        return

    resource_planet = _research_resource_planet(uid, conn)
    planet_id = int(resource_planet["id"])
    buildings = resolve_buildings_for_research(
        get_planet_buildings(planet_id, conn=conn),
        uid,
        conn=conn,
    )
    levels = get_research_levels(uid, conn=conn)
    from .effects import get_effect_resolver

    time_resolver = get_effect_resolver(
        uid,
        buildings=buildings,
        research=levels,
        conn=conn,
    )
    cur = conn.cursor()
    schedule_at = ts
    queued_counts: Dict[str, int] = {}
    from .queue_poll import due_cutoff_ts

    finish_cutoff = due_cutoff_ts(ts)

    for idx, row in enumerate(rows):
        tech = str(row["tech_key"])
        current = int(levels.get(tech, 0) or 0)
        queued_same = int(queued_counts.get(tech, 0))
        target = current + queued_same + 1
        duration = float(
            get_research_time(
                tech,
                target,
                user_id=uid,
                buildings=buildings,
                levels=levels,
                conn=conn,
                resolver=time_resolver,
            )
        )

        if idx == 0:
            start_existing = float(row["start_at"] or 0)
            finish_existing = float(row["finish_at"] or 0)
            # Due / display-zero head: never revive to a full duration; leave for finish.
            if finish_existing <= finish_cutoff:
                queued_counts[tech] = queued_same + 1
                schedule_at = ts
                continue
            if start_existing <= ts < finish_existing:
                queued_counts[tech] = queued_same + 1
                schedule_at = finish_existing
                continue

        start_at = schedule_at
        finish_at = schedule_at + duration
        cur.execute(
            """
            UPDATE research_queue
            SET start_at = ?, finish_at = ?
            WHERE id = ?;
            """,
            (float(start_at), float(finish_at), int(row["id"])),
        )
        queued_counts[tech] = queued_same + 1
        schedule_at = finish_at


# ======================================================================
# REQUIREMENTS
# ======================================================================
def get_player_research_lab_level(player_id: int, conn=None) -> int:
    """
    Research is account-scoped; unlock checks use the highest research_lab
    level on any planet owned by the player (finished levels only).
    """
    from .models import db as _db

    uid = int(player_id)
    own_conn = False
    if conn is None:
        conn = _db()
        own_conn = True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(MAX(pb.research_lab), 0) AS lab_level
            FROM planet_buildings pb
            INNER JOIN planets p ON p.id = pb.planet_id
            WHERE p.player_id = ?;
            """,
            (uid,),
        )
        row = cur.fetchone()
        return int(row["lab_level"] if row else 0)
    finally:
        if own_conn:
            conn.close()


def resolve_buildings_for_research(
    buildings: Optional[Dict[str, int]],
    player_id: int,
    *,
    conn=None,
) -> Dict[str, int]:
    """
    Overlay empire-wide research_lab level onto a planet buildings snapshot.
    Other building keys stay planet-local; only research_lab drives tech unlocks.
    """
    resolved = dict(buildings or {})
    resolved["research_lab"] = get_player_research_lab_level(player_id, conn=conn)
    return resolved


def _check_requirements(
    base_requirements: Dict[str, Any],
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> bool:
    if not base_requirements:
        return True

    for b_key, need_lvl in (base_requirements.get("buildings") or {}).items():
        if int(buildings.get(b_key, 0) or 0) < int(need_lvl):
            return False

    for r_key, need_lvl in (base_requirements.get("research") or {}).items():
        if int(research_levels.get(r_key, 0) or 0) < int(need_lvl):
            return False

    return True


def get_research_requirements_items(
    tech_key: str,
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> List[Dict[str, Any]]:
    cfg = RESEARCH_TECHS.get(tech_key) or {}
    req = cfg.get("requirements") or {}
    items: List[Dict[str, Any]] = []

    for b_key, need_lvl in (req.get("buildings") or {}).items():
        have = int(buildings.get(b_key, 0) or 0)
        need = int(need_lvl)
        items.append({
            "kind": "building",
            "key": b_key,
            "need": need,
            "have": have,
            "met": have >= need,
        })

    for r_key, need_lvl in (req.get("research") or {}).items():
        have = int(research_levels.get(r_key, 0) or 0)
        need = int(need_lvl)
        items.append({
            "kind": "research",
            "key": r_key,
            "need": need,
            "have": have,
            "met": have >= need,
        })

    return items


def has_research_requirements(
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
    tech_key: str,
) -> bool:
    cfg = RESEARCH_TECHS.get(tech_key)
    if not cfg:
        return False
    req = cfg.get("requirements") or {}
    return _check_requirements(req, buildings, research_levels)


# ======================================================================
# FINISH (ATOMAR, CONN-SAFE)
# ======================================================================
def complete_finished_research(user_id: int, conn=None) -> bool:
    """
    Conn-safe: delegiert an queue_engine.finish_due_work (nur dieser Spieler).
    """
    uid = int(user_id)

    from .models import db as _db
    from .planet_evolution.repository import get_context_planet
    from .queue_engine import finish_due_work_once

    own_conn = False
    if conn is None:
        conn = _db()
        own_conn = True

    try:
        if own_conn:
            begin_write_transaction(conn)

        engine_result = finish_due_work_once(
            player_id=uid,
            planet_id=int(get_context_planet(uid, conn=conn)["id"]),
            conn=conn,
            source="research",
        )
        finished_any = (
            int(engine_result["finished"]["buildings"])
            + int(engine_result["finished"]["research"])
        ) > 0

        if own_conn:
            commit(conn)
        return bool(finished_any)

    except Exception:
        if own_conn:
            rollback(conn)
        raise
    finally:
        if own_conn:
            conn.close()


RESEARCH_QUEUE_LIMIT = 2
RESEARCH_QUEUE_LIMIT_AT_LAB4 = 3
RESEARCH_QUEUE_LAB_LEVEL_FOR_BONUS = 4


def _research_resource_planet(player_id: int, conn) -> Dict[str, Any]:
    """
    Planet whose metal/crystal pay for imperial research — matches UI + building upgrades.
    """
    from .planet_evolution.repository import get_context_planet

    return get_context_planet(int(player_id), conn=conn)


def _research_not_enough_payload(
    *,
    planet_metal: float,
    planet_crystal: float,
    cost_m: int,
    cost_c: int,
) -> Dict[str, int]:
    """Missing amounts for error messages (never locale-formatted strings)."""
    return {
        "metal": int(max(0, cost_m - int(planet_metal))),
        "crystal": int(max(0, cost_c - int(planet_crystal))),
        "available_metal": int(planet_metal),
        "available_crystal": int(planet_crystal),
        "cost_metal": int(cost_m),
        "cost_crystal": int(cost_c),
    }


def _resolve_research_queue_limit(
    settings: Optional[Dict[str, Any]] = None,
    *,
    player_id: Optional[int] = None,
    conn=None,
) -> int:
    if settings is None:
        try:
            settings = get_game_settings(conn=conn)
        except TypeError:
            settings = get_game_settings()
    raw_limit = settings.get("research_queue_limit", RESEARCH_QUEUE_LIMIT)
    try:
        queue_limit = int(raw_limit)
    except (ValueError, TypeError):
        try:
            queue_limit = int(float(raw_limit))
        except (ValueError, TypeError):
            queue_limit = RESEARCH_QUEUE_LIMIT
    base = max(queue_limit, 1)
    if player_id is not None:
        lab = get_player_research_lab_level(int(player_id), conn=conn)
        if lab >= RESEARCH_QUEUE_LAB_LEVEL_FOR_BONUS:
            base = max(base, RESEARCH_QUEUE_LIMIT_AT_LAB4)
        # GC-720J: scientific directive may grant extra research queue slots.
        try:
            from .galactic_directives.mechanics import get_directive_queue_limit_bonus
            from .models import get_homeworld

            hw = get_homeworld(int(player_id), conn=conn) or {}
            galaxy = int(hw.get("galaxy") or 0)
            if galaxy > 0:
                base += get_directive_queue_limit_bonus(galaxy, "research", conn=conn)
        except Exception:
            pass
    return base


# ======================================================================
# QUEUE START
# ======================================================================
def preview_max_queueable_research_jobs(
    tech_key: str,
    *,
    current_level: int,
    queued_same: int,
    metal: int,
    crystal: int,
    queue_free_slots: int,
) -> int:
    """How many +1 research jobs can be queued for one tech."""
    if tech_key not in RESEARCH_TECHS or int(queue_free_slots) <= 0:
        return 0
    count = 0
    m = int(metal or 0)
    c = int(crystal or 0)
    while count < int(queue_free_slots):
        target = int(current_level) + int(queued_same) + count + 1
        cost_m, cost_c = get_research_cost(tech_key, target)
        if m < int(cost_m) or c < int(cost_c):
            break
        m -= int(cost_m)
        c -= int(cost_c)
        count += 1
    return count


def summarize_max_queueable_research_jobs(
    tech_key: str,
    *,
    current_level: int,
    queued_same: int,
    metal: int,
    crystal: int,
    queue_free_slots: int,
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
    levels: Optional[Dict[str, int]] = None,
    conn=None,
    resolver=None,
) -> Dict[str, Any]:
    """Preview payload for MAX research queue UX: levels, total cost, cumulative time."""
    jobs = preview_max_queueable_research_jobs(
        tech_key,
        current_level=current_level,
        queued_same=queued_same,
        metal=metal,
        crystal=crystal,
        queue_free_slots=queue_free_slots,
    )
    if jobs <= 0:
        return {"jobs": 0}
    from_level = int(current_level) + int(queued_same)
    total_m = 0.0
    total_c = 0.0
    total_sec = 0
    for i in range(jobs):
        target = from_level + i + 1
        cost_m, cost_c = get_research_cost(tech_key, target)
        total_m += float(cost_m)
        total_c += float(cost_c)
        total_sec += int(
            get_research_time(
                tech_key,
                target,
                int(user_id),
                buildings=buildings,
                levels=levels,
                conn=conn,
                resolver=resolver,
            )
        )
    return {
        "jobs": int(jobs),
        "from_level": from_level,
        "to_level": from_level + int(jobs),
        "cost_metal": int(round(total_m)),
        "cost_crystal": int(round(total_c)),
        "time_seconds": int(total_sec),
    }


def queue_research(player: dict, tech_key: str, user_id: Optional[int] = None, *, queue_mode: str = "single"):
    if tech_key not in RESEARCH_TECHS:
        return False, "unknown_tech", None

    if user_id is None:
        pid = player.get("id")
        if pid is None:
            raise RuntimeError("queue_research: player hat kein 'id'")
        uid = int(pid)
    else:
        uid = int(user_id)

    from .options import vacation_blocks_outbound

    ok_vacation, vac_reason = vacation_blocks_outbound(uid, conn=db())
    if not ok_vacation:
        return False, vac_reason, None

    want_max = str(queue_mode or "single").strip().lower() == "max"

    conn = db()
    finished_any = False
    try:
        begin_write_transaction(conn)
        lock_player_for_update(conn, uid)
        now = time.time()

        planet = _research_resource_planet(uid, conn)
        if not planet or not planet.get("id"):
            rollback(conn)
            return False, "no_homeworld", None

        planet_id = int(planet["id"])

        from .queue_engine import finish_due_work

        engine_result = finish_due_work(
            player_id=uid,
            planet_id=planet_id,
            now=now,
            conn=conn,
            source="action",
            recalc_ranks=False,
        )
        finished_any = (
            int(engine_result["finished"]["buildings"])
            + int(engine_result["finished"]["research"])
        ) > 0

        recalculate_research_queue_finish_times(uid, conn=conn, now=now)

        research_queue_limit = _resolve_research_queue_limit(player_id=uid, conn=conn)
        jobs_queued = 0
        job_ids: List[int] = []
        queued_research: List[tuple[int, str, int, int]] = []
        last_payload: Dict[str, Any] = {}
        last_reason = "unknown"
        last_fail: Any = None
        max_attempts = 64 if want_max else 1

        for _ in range(max_attempts):
            cur = conn.cursor()
            cur.execute(
                "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
                (planet_id,),
            )
            prow = cur.fetchone()
            if not prow:
                if jobs_queued > 0:
                    break
                rollback(conn)
                return False, "no_homeworld", None

            planet_metal = int(prow["metal"] or 0)
            planet_crystal = int(prow["crystal"] or 0)

            buildings = resolve_buildings_for_research(
                get_planet_buildings(planet_id, conn=conn),
                uid,
                conn=conn,
            )
            levels = get_research_levels(uid, conn=conn)

            if int(buildings.get("research_lab", 0) or 0) <= 0:
                last_reason = "no_research_lab"
                last_fail = None
                break

            if not has_research_requirements(buildings, levels, tech_key):
                last_reason = "requirements"
                last_fail = None
                break

            rows = get_research_queue_rows(uid, conn=conn)
            if len(rows) >= research_queue_limit:
                last_reason = "research_queue_full"
                last_fail = {
                    "queue_count": len(rows),
                    "queue_limit": research_queue_limit,
                }
                break

            queued_same = sum(1 for r in rows if str(r["tech_key"]) == tech_key)
            current = int(levels.get(tech_key, 0) or 0)
            target = current + queued_same + 1

            cost_m, cost_c = get_research_cost(tech_key, target)

            if planet_metal < int(cost_m) or planet_crystal < int(cost_c):
                last_reason = "not_enough_resources"
                last_fail = _research_not_enough_payload(
                    planet_metal=planet_metal,
                    planet_crystal=planet_crystal,
                    cost_m=int(cost_m),
                    cost_c=int(cost_c),
                )
                break

            duration = get_research_time(
                tech_key,
                target,
                user_id=uid,
                buildings=buildings,
                levels=levels,
                conn=conn,
            )
            last_finish = max(float(r["finish_at"]) for r in rows) if rows else now
            start_at = max(now, last_finish)
            finish_at = start_at + float(duration)

            if not try_spend_resources_conn(conn, planet_id, int(cost_m), int(cost_c)):
                last_reason = "not_enough_resources"
                cur.execute(
                    "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
                    (planet_id,),
                )
                after = cur.fetchone()
                avail_m = int(after["metal"] or 0) if after else planet_metal
                avail_c = int(after["crystal"] or 0) if after else planet_crystal
                last_fail = _research_not_enough_payload(
                    planet_metal=avail_m,
                    planet_crystal=avail_c,
                    cost_m=int(cost_m),
                    cost_c=int(cost_c),
                )
                break

            job_id = add_research_job(
                uid,
                tech_key,
                float(start_at),
                float(finish_at),
                conn=conn,
                cost_metal=int(cost_m),
                cost_crystal=int(cost_c),
            )
            jobs_queued += 1
            job_ids.append(int(job_id))
            queued_research.append((int(job_id), tech_key, int(cost_m), int(cost_c)))
            last_payload = {
                "job_id": int(job_id),
                "seconds": int(duration),
                "level": int(target),
                "target_level": int(target),
                "queued": len(rows) > 0,
            }

            if jobs_queued == 1:
                logger.info(
                    "Research Start: player_id=%s planet_id=%s available_feronit=%s available_crytite=%s "
                    "required_feronit=%s required_crytite=%s tech=%s",
                    uid,
                    planet_id,
                    int(planet_metal),
                    int(planet_crystal),
                    int(cost_m),
                    int(cost_c),
                    tech_key,
                )

            if not want_max:
                break

        if jobs_queued <= 0:
            rollback(conn)
            return False, last_reason, last_fail

        commit(conn)

        if queued_research:
            try:
                from .directives.progress import emit_research_started_event

                for job_id, queued_tech, spend_m, spend_c in queued_research:
                    emit_research_started_event(
                        uid,
                        tech_key=queued_tech,
                        metal=spend_m,
                        crystal=spend_c,
                        job_id=job_id,
                        conn=conn,
                        now=now,
                    )
                conn.commit()
            except Exception:
                logger.exception(
                    "imperial_directives research start progress failed player=%s",
                    uid,
                )

        if finished_any:
            invalidate_player_score_cache(uid)

        last_payload["jobs_queued"] = int(jobs_queued)
        if len(job_ids) > 1:
            last_payload["job_ids"] = job_ids
        return True, "ok", last_payload

    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def cancel_research_job(user_id: int, job_id: int):
    uid = int(user_id)
    jid = int(job_id)

    conn = db()
    finished_any = False
    try:
        begin_write_transaction(conn)
        lock_player_for_update(conn, uid)
        now = time.time()

        from .queue_engine import finish_due_work

        resource_planet = _research_resource_planet(uid, conn)
        engine_result = finish_due_work(
            player_id=uid,
            planet_id=int(resource_planet["id"]),
            now=now,
            conn=conn,
            source="action",
            recalc_ranks=False,
        )
        finished_any = (
            int(engine_result["finished"]["buildings"])
            + int(engine_result["finished"]["research"])
        ) > 0

        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, tech_key, start_at, finish_at, cost_metal, cost_crystal
            FROM research_queue
            WHERE id = ? AND user_id = ?
            LIMIT 1;
            """,
            (jid, uid),
        )
        row = cur.fetchone()
        if not row:
            rollback(conn)
            return False, "not_found", {"msg": "Research job not found", "job_id": jid}

        from .queue_refund import refund_research_job

        refund = refund_research_job(
            conn,
            int(resource_planet["id"]),
            uid,
            job_id=int(row["id"]),
            tech_key=str(row["tech_key"]),
            start_time=float(row["start_at"] or row["finish_at"] or now),
            finish_time=float(row["finish_at"] or now),
            now=now,
            cost_metal=int(row["cost_metal"] or 0),
            cost_crystal=int(row["cost_crystal"] or 0),
        )

        delete_research_job(int(row["id"]), conn=conn)
        recalculate_research_queue_finish_times(uid, conn=conn, now=now)
        commit(conn)

        if finished_any:
            invalidate_player_score_cache(uid)

        return True, "ok", {
            "job_id": int(row["id"]),
            "tech_key": str(row["tech_key"]),
            "cancelled": True,
            **refund,
        }
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


# ======================================================================
# STATUS FOR UI
# ======================================================================
def player_has_active_research_queue(
    user_id: int,
    conn=None,
    *,
    now: Optional[float] = None,
) -> bool:
    """
    GC-PLANET-UI-001: True when account research_queue has a non-due job.

    Research is account-scoped; callers attach the indicator to the context
    planet (same as Command Center research_applies).
    """
    own = False
    if conn is None:
        conn = db()
        own = True
    try:
        ts = float(time.time() if now is None else now)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 AS ok
            FROM research_queue
            WHERE user_id = ? AND finish_at > ?
            LIMIT 1;
            """,
            (int(user_id), ts),
        )
        return cur.fetchone() is not None
    finally:
        if own and conn is not None:
            conn.close()


def get_research_status(
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
    *,
    skip_finish: bool = False,
    include_techs: bool = True,
    conn=None,
    levels: Optional[Dict[str, int]] = None,
) -> dict:
    uid = int(user_id)

    from .live_state import coerce_skip_finish

    skip_finish = coerce_skip_finish(bool(skip_finish))

    resource_planet = _research_resource_planet(uid, conn)
    planet_id = int(resource_planet["id"])

    if not skip_finish:
        if conn is not None:
            from .queue_engine import finish_active_planet_due_work

            finish_active_planet_due_work(
                uid,
                planet_id,
                conn,
                source="research_status",
            )
        else:
            complete_finished_research(uid)

    planet_metal = int(resource_planet.get("metal") or 0)
    planet_crystal = int(resource_planet.get("crystal") or 0)

    if buildings is None:
        buildings = get_planet_buildings(int(resource_planet["id"]), conn=conn)

    buildings = resolve_buildings_for_research(buildings, uid, conn=conn)
    lab_level = int(buildings.get("research_lab", 0) or 0)

    if levels is None:
        levels = get_research_levels(uid, conn=conn)
    queue = get_research_queue_rows(uid, conn=conn)
    now = time.time()
    from .queue_poll import due_cutoff_ts

    finish_cutoff = due_cutoff_ts(now)

    if not skip_finish:
        for _ in range(3):
            if not queue:
                break
            if float(queue[0]["finish_at"]) > finish_cutoff:
                break
            if conn is not None:
                from .queue_engine import finish_active_planet_due_work

                engine = finish_active_planet_due_work(
                    uid,
                    planet_id,
                    conn,
                    source="research_status_retry",
                    recalc_ranks=False,
                )
                if int(engine.get("finished", {}).get("research", 0)) <= 0:
                    break
            elif not complete_finished_research(uid):
                break
            queue = get_research_queue_rows(uid, conn=conn)
            levels = get_research_levels(uid, conn=conn)

    queue_list: List[Dict[str, Any]] = []
    pending: Dict[str, int] = {}

    # GC-PERF-RESEARCH-TIME-001: one resolver for queue fallback + full tech catalog.
    from .effects import EffectResolver, get_effect_resolver

    if conn is not None:
        time_resolver = get_effect_resolver(
            uid,
            buildings=buildings,
            research=levels,
            conn=conn,
        )
    else:
        time_resolver = EffectResolver(
            buildings, levels, player_id=uid, conn=conn
        )

    for i, job in enumerate(queue):
        tech = str(job["tech_key"])
        cfg = RESEARCH_TECHS.get(tech, {})
        pending[tech] = pending.get(tech, 0) + 1

        curr = int(levels.get(tech, 0) or 0)
        targ = curr + pending[tech]

        finish_at = float(job["finish_at"])
        start_raw = job["start_at"] if "start_at" in job.keys() else None
        if start_raw is not None and float(start_raw or 0) > 0:
            start_at = float(start_raw)
        elif i > 0:
            start_at = float(queue[i - 1]["finish_at"])
        else:
            start_at = finish_at - float(
                get_research_time(
                    tech,
                    targ,
                    user_id=uid,
                    buildings=buildings,
                    levels=levels,
                    conn=conn,
                    resolver=time_resolver,
                )
            )

        total = max(1, int(finish_at - start_at))
        remain = max(0, int(finish_at - now))

        from .logic import normalize_queue_job_timer_fields

        timer_fields = normalize_queue_job_timer_fields(
            finish_at=finish_at,
            remaining=remain,
            is_active=(i == 0),
        )

        queue_list.append({
            "id": int(job["id"]),
            "tech_key": tech,
            "key": tech,
            "label": tr(str(cfg.get("label_key") or tech)),
            "label_key": cfg.get("label_key"),
            "description": tr(str(cfg.get("description_key") or f"desc_{tech}")),
            "description_key": cfg.get("description_key"),
            "current_level": curr,
            "target_level": int(targ),
            "total_seconds": int(total),
            "total": int(total),
            "start_at": start_at,
            "icon": cfg.get("icon"),
            "position": i + 1,
            **timer_fields,
        })

    # GC-833: due rows must never appear in client payloads (finish above should remove them)
    queue_list = [q for q in queue_list if int(q.get("remaining") or 0) > 0]

    active = queue_list[0] if queue_list else None

    queue_keys: Dict[str, int] = {}
    for item in queue_list:
        k = str(item["tech_key"])
        queue_keys[k] = queue_keys.get(k, 0) + 1

    research_queue_limit = _resolve_research_queue_limit(player_id=uid, conn=conn)
    queue_free_slots = max(0, research_queue_limit - len(queue_list))

    techs: List[Dict[str, Any]] = []
    # Diet/HUD/probe: queue timers only — full catalog is SSR / include_panel (GC-PERF live).
    if include_techs:
        for tech, cfg in RESEARCH_TECHS.items():
            curr = int(levels.get(tech, 0) or 0)
            q_count = int(queue_keys.get(tech, 0) or 0)
            targ = curr + q_count + 1

            cost_m, cost_c = get_research_cost(tech, targ)
            t_sec = get_research_time(
                tech,
                targ,
                user_id=uid,
                buildings=buildings,
                levels=levels,
                conn=conn,
                resolver=time_resolver,
            )

            req = cfg.get("requirements") or {}
            req_met = _check_requirements(req, buildings, levels)
            can_afford = planet_metal >= int(cost_m) and planet_crystal >= int(cost_c)
            max_queue_preview: Dict[str, Any] = {"jobs": 0}
            if req_met:
                max_queue_preview = summarize_max_queueable_research_jobs(
                    tech,
                    current_level=curr,
                    queued_same=q_count,
                    metal=planet_metal,
                    crystal=planet_crystal,
                    queue_free_slots=queue_free_slots,
                    user_id=uid,
                    buildings=buildings,
                    levels=levels,
                    conn=conn,
                    resolver=time_resolver,
                )

            is_active = bool(active and str(active.get("tech_key")) == tech)
            in_queue = q_count > 0

            effect_preview = get_research_effect_preview(tech, curr, targ)

            techs.append({
                "key": tech,
                "label": tr(str(cfg.get("label_key") or tech)),
                "label_key": cfg.get("label_key"),
                "description": tr(str(cfg.get("description_key") or f"desc_{tech}")),
                "description_key": cfg.get("description_key"),
                "category": cfg.get("category", ""),
                "level": curr,
                "target_level": targ,
                "cost_metal": int(cost_m),
                "cost_crystal": int(cost_c),
                "time_seconds": int(t_sec),
                "requirements_met": bool(req_met),
                "can_afford": bool(can_afford),
                "max_queueable": int(max_queue_preview.get("jobs") or 0),
                "max_queue_preview": max_queue_preview,
                "requirements_items": get_research_requirements_items(tech, buildings, levels),
                "resource_items": [
                    {
                        "kind": "resource",
                        "key": "metal",
                        "need": int(cost_m),
                        "have": int(planet_metal),
                        "met": planet_metal >= int(cost_m),
                    },
                    {
                        "kind": "resource",
                        "key": "crystal",
                        "need": int(cost_c),
                        "have": int(planet_crystal),
                        "met": planet_crystal >= int(cost_c),
                    },
                ],
                "icon": cfg.get("icon"),
                "queue_count": q_count,
                "is_active": is_active,
                "in_queue": in_queue,
                **effect_preview,
            })

        _attach_queue_jobs_to_research_techs(techs, queue_list)

    summary = {
        "count": len(queue_list),
        "limit": research_queue_limit,
        "has_queue": bool(queue_list),
        "first_finish_in": int(queue_list[0]["remaining"]) if queue_list else 0,
    }

    from .queue_card import (
        group_card_jobs_by_owner_key,
        map_card_jobs_to_mini_queue_jobs,
        map_research_queue_to_card_jobs,
    )

    card_jobs = map_research_queue_to_card_jobs({"queue": queue_list}, now=now)
    card_jobs_by_owner = group_card_jobs_by_owner_key(card_jobs)

    out: Dict[str, Any] = {
        "active": active,
        "queue": queue_list,
        "summary": summary,
        "lab_level": lab_level,
        "card_jobs_by_owner": card_jobs_by_owner,
        "mini_queue_jobs": map_card_jobs_to_mini_queue_jobs(
            card_jobs, domain="research", now=now
        ),
    }
    if include_techs:
        out["techs"] = techs
    return out


def _research_technical_level_row(
    tech_key: str,
    level: int,
    *,
    user_id: int,
    buildings: Dict[str, int],
    is_current: bool,
    levels: Optional[Dict[str, int]] = None,
    conn=None,
    resolver=None,
) -> Dict[str, Any]:
    lvl = max(0, int(level))
    cost_level = max(1, lvl) if lvl > 0 else 1
    cost_m, cost_c = get_research_cost(tech_key, cost_level)
    time_s = int(
        get_research_time(
            tech_key,
            cost_level,
            int(user_id),
            buildings=buildings,
            levels=levels,
            conn=conn,
            resolver=resolver,
        )
    )
    if lvl > 0:
        effect = get_research_effect_preview(tech_key, lvl - 1, lvl)
    else:
        effect = get_research_effect_preview(tech_key, 0, 1)
    row: Dict[str, Any] = {
        "level": lvl,
        "is_current": bool(is_current),
        "cost_metal": int(cost_m),
        "cost_crystal": int(cost_c),
        "time_seconds": time_s,
        "effect_kind": effect.get("effect_kind") or "level",
        "effect_current": effect.get("effect_current"),
        "effect_next": effect.get("effect_next"),
        "effect_delta": effect.get("effect_delta"),
        "effect_value": effect.get("effect_current"),
        "effect_unit": effect.get("effect_unit") or "",
        "effect_resource": effect.get("effect_resource") or "",
        "effect_metric_key": effect.get("effect_metric_key") or "",
    }
    sec = effect.get("secondary_effect")
    if isinstance(sec, dict):
        row["secondary_effect"] = {
            "effect_kind": sec.get("effect_kind") or "level",
            "effect_current": sec.get("effect_current"),
            "effect_next": sec.get("effect_next"),
            "effect_delta": sec.get("effect_delta"),
            "effect_value": sec.get("effect_current"),
            "effect_unit": sec.get("effect_unit") or "",
            "effect_resource": sec.get("effect_resource") or "",
            "effect_metric_key": sec.get("effect_metric_key") or "",
        }
    from .technical_data import enrich_research_technical_row

    enrich_research_technical_row(row, tech_key, lvl)
    return row


def build_research_technical_data(
    tech_key: str,
    *,
    user_id: int,
    conn,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    key = str(tech_key or "").strip()
    if key not in RESEARCH_TECHS:
        return None, "unknown_research"

    uid = int(user_id)
    resource_planet = _research_resource_planet(uid, conn)
    buildings = resolve_buildings_for_research(
        get_planet_buildings(int(resource_planet["id"]), conn=conn),
        uid,
        conn=conn,
    )
    levels = get_research_levels(uid, conn=conn)
    current = int(levels.get(key, 0) or 0)
    cfg = RESEARCH_TECHS[key]
    from .technical_data import (
        build_research_technical_summary,
        resolve_technical_table_layout,
        technical_preview_levels,
        technical_row_role,
    )

    from .effects import EffectResolver, get_effect_resolver

    time_resolver = get_effect_resolver(
        uid,
        buildings=buildings,
        research=levels,
        conn=conn,
    ) if conn is not None else EffectResolver(
        buildings, levels, player_id=uid, conn=conn
    )

    preview = technical_preview_levels(current)
    level_rows: List[Dict[str, Any]] = []
    for lvl in preview:
        row = _research_technical_level_row(
            key,
            lvl,
            user_id=uid,
            buildings=buildings,
            is_current=(lvl == current),
            levels=levels,
            conn=conn,
            resolver=time_resolver,
        )
        row["row_role"] = technical_row_role(lvl, current)
        level_rows.append(row)

    next_row = next((r for r in level_rows if int(r.get("level") or 0) == current + 1), None)
    summary = build_research_technical_summary(
        tech_key=key,
        current=current,
        next_row=next_row,
        buildings=buildings,
        research_levels=levels,
    )

    return {
        "tech_key": key,
        "label_key": cfg.get("label_key") or key,
        "description_key": cfg.get("description_key") or f"desc_{key}",
        "kind": "research",
        "current_level": current,
        "max_level": None,
        "table_layout": resolve_technical_table_layout(level_rows),
        "summary": summary,
        "milestones": [],
        "levels": level_rows,
    }, None


def _attach_queue_jobs_to_research_techs(
    techs: List[Dict[str, Any]],
    queue_list: List[Dict[str, Any]],
    *,
    now: Optional[float] = None,
) -> None:
    """GC-536C: optional queue_job on each research tech row (presentation only)."""
    from .queue_card import (
        card_queue_job_for_item,
        group_card_jobs_by_owner_key,
        map_research_queue_to_card_jobs,
    )

    card_jobs = map_research_queue_to_card_jobs({"queue": queue_list}, now=now)
    by_key = group_card_jobs_by_owner_key(card_jobs)

    for tech in techs:
        owner_key = str(tech.get("key") or "")
        qj = card_queue_job_for_item(by_key, owner_key) if owner_key else None
        if qj:
            tech["queue_job"] = dict(qj)
        elif "queue_job" in tech:
            del tech["queue_job"]


# ======================================================================
# VALIDATION
# ======================================================================
def _validate_research_config() -> None:
    for tech_key, cfg in RESEARCH_TECHS.items():
        req = cfg.get("requirements") or {}
        for r_key in (req.get("research") or {}).keys():
            if r_key not in RESEARCH_TECHS:
                raise RuntimeError(
                    f"RESEARCH_CONFIG: Requirements von '{tech_key}' verweisen auf unbekannte Forschung '{r_key}'"
                )

_validate_research_config()

# ============================================================================
# Modifiers (delegates to EffectResolver – single source of truth)
# ============================================================================

def get_research_modifiers(player_id: int, conn=None) -> dict:
    """
    Canonical modifier bundle for resources, buildings, and API consumers.
    All formulas live in game.effects.effect_resolver.EffectResolver.
    """
    from .effects import get_effect_resolver

    resolver = get_effect_resolver(int(player_id), conn=conn, force_refresh=True)
    return resolver.get_modifiers()
