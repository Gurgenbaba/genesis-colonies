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
from .db import begin_write_transaction, commit, rollback, lock_planet_for_update, lock_player_for_update
from .ranking import invalidate_player_score_cache  # ✅ Cache invalidieren nach Finish


# ======================================================================
# TECH CONFIG
# ======================================================================

RESEARCH_TECHS: Dict[str, Dict[str, Any]] = {
    "energy_tech": {
        "label": "Energieeffizienz",
        "label_key": "energy_tech",
        "description": "Optimiert die Energieausbeute aller Anlagen.",
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
        "label": "Metallveredelung",
        "label_key": "mining_tech",
        "description": "Steigert die Reinheit und damit die Produktion von Ferronit.",
        "description_key": "desc_mining_tech",
        "category": "metal",
        "icon": "metallveredelung.png",
        "base_cost_m": 1200,
        "base_cost_c": 600,
        "base_time": 910,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "buildtime_tech": {
        "label": "Bauoptimierung",
        "label_key": "buildtime_tech",
        "description": "Reduziert Bauzeiten aller Gebäude.",
        "description_key": "desc_buildtime_tech",
        "category": "construction",
        "icon": "bauoptimierung.png",
        "base_cost_m": 1500,
        "base_cost_c": 800,
        "base_time": 980,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "storage_tech": {
        "label": "Lagertechnik",
        "label_key": "storage_tech",
        "description": "Erhöht die maximale Kapazität aller Lagergebäude.",
        "description_key": "desc_storage_tech",
        "category": "storage",
        "icon": "lagertechnik.png",
        "base_cost_m": 800,
        "base_cost_c": 800,
        "base_time": 770,
        "cost_factor": 1.6,
        "requirements": {"buildings": {"research_lab": 1}},
    },
    "drone_tech": {
        "label": "Drohnenoptimierung",
        "label_key": "research_drones_tech",
        "description": "Verbesserte Drohnen erhöhen die Ausbeute.",
        "description_key": "desc_research_drones_tech",
        "category": "drones",
        "icon": "drohnenoptimierung.png",
        "base_cost_m": 1500,
        "base_cost_c": 900,
        "base_time": 1050,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "navigation_tech": {
        "label": "Hyperraum-Navigation",
        "label_key": "research_navigation_tech",
        "description": "Verkürzt Flugzeiten.",
        "description_key": "desc_research_navigation_tech",
        "category": "navigation",
        "icon": "hyperraum-navigation.png",
        "base_cost_m": 2000,
        "base_cost_c": 1500,
        "base_time": 1260,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"drone_tech": 2}},
    },
    "engine_tech": {
        "label": "Kryo-Antriebstechnik",
        "label_key": "research_engine_tech",
        "description": "Erhöht Flottengeschwindigkeit.",
        "description_key": "desc_research_engine_tech",
        "category": "engine",
        "icon": "kryo-antriebstechnik.png",
        "base_cost_m": 2200,
        "base_cost_c": 1600,
        "base_time": 1330,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"energy_tech": 2}},
    },
    "weapon_tech": {
        "label": "Waffenentwicklung",
        "label_key": "research_weapon_tech",
        "description": "Erhöht Feuerkraft.",
        "description_key": "desc_research_weapon_tech",
        "category": "weapon",
        "icon": "waffenentwicklung.png",
        "base_cost_m": 1800,
        "base_cost_c": 900,
        "base_time": 1120,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}},
    },
    "armor_tech": {
        "label": "Panzerungstechnik",
        "label_key": "research_armor_tech",
        "description": "Erhöht Hülle.",
        "description_key": "desc_research_armor_tech",
        "category": "armor",
        "icon": "panzerungstechnik.png",
        "base_cost_m": 1900,
        "base_cost_c": 1100,
        "base_time": 1190,
        "cost_factor": 1.7,
        "requirements": {"buildings": {"research_lab": 2}, "research": {"weapon_tech": 1}},
    },
    "shield_tech": {
        "label": "Schildtechnologie",
        "label_key": "research_shield_tech",
        "description": "Erhöht Schildstärke.",
        "description_key": "desc_research_shield_tech",
        "category": "shield",
        "icon": "schildtechnologie.png",
        "base_cost_m": 2200,
        "base_cost_c": 1300,
        "base_time": 1330,
        "cost_factor": 1.8,
        "requirements": {"buildings": {"research_lab": 3}, "research": {"armor_tech": 1}},
    },
    "fuel_efficiency": {
        "label": "Brennzellen-Optimierung",
        "label_key": "research_fuel_efficiency",
        "description": "Reduziert Flotten-Treibstoffverbrauch um 3 % pro Stufe (min. 50 %).",
        "description_key": "desc_fuel_efficiency",
        "category": "propulsion",
        "icon": "kryo-antriebstechnik.png",
        "base_cost_m": 2400,
        "base_cost_c": 1200,
        "base_time": 1400,
        "cost_factor": 1.75,
        "requirements": {"buildings": {"research_lab": 2}, "research": {"energy_tech": 1}},
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
    "production": ["metal", "drones"],
    "construction": ["construction", "storage"],
    "fleet": ["navigation", "engine", "propulsion"],
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
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    factor = max(0.4, 1.0 - 0.05 * lvl)
    return int(round((1.0 - factor) * 100))


def _buildtime_reduction_pct(level: int) -> int:
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    factor = max(0.40, 1.0 - 0.03 * lvl)
    return int(round((1.0 - factor) * 100))


def _metal_prod_bonus_pct(level: int) -> int:
    return int(round(10.0 * max(0, int(level or 0))))


def _crystal_prod_bonus_pct(level: int) -> int:
    return int(round(4.0 * max(0, int(level or 0))))


def _drone_prod_bonus_pct(level: int) -> int:
    return int(round(3.0 * max(0, int(level or 0))))


def _storage_bonus_pct(level: int) -> int:
    return int(round(25.0 * max(0, int(level or 0))))


def _combat_bonus_pct(level: int) -> int:
    return int(round(5.0 * max(0, int(level or 0))))


def _fleet_speed_bonus_pct(level: int, per_level: float) -> int:
    lvl = max(0, int(level or 0))
    return int(round(per_level * lvl * 100))


def _fuel_reduction_pct(level: int) -> int:
    from .fleet_calc import FUEL_EFFICIENCY_MIN_FACTOR, FUEL_EFFICIENCY_PER_LEVEL

    lvl = max(0, int(level or 0))
    factor = max(FUEL_EFFICIENCY_MIN_FACTOR, 1.0 - lvl * FUEL_EFFICIENCY_PER_LEVEL)
    return int(round((1.0 - factor) * 100))


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
    if tech_key == "buildtime_tech":
        return _research_effect_snapshot(
            effect_kind="reduction_percent",
            effect_current=_buildtime_reduction_pct(cur),
            effect_next=_buildtime_reduction_pct(nxt),
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

    base_m = float(cfg.get("base_cost_m", 1000))
    base_c = float(cfg.get("base_cost_c", 500))
    cost_factor = float(cfg.get("cost_factor", 1.6))

    lvl = max(1, int(level))
    factor = cost_factor ** (lvl - 1)

    return int(base_m * factor), int(base_c * factor)


def get_research_time(
    tech_key: str,
    level: int,
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
) -> int:
    if tech_key not in RESEARCH_TECHS:
        return 0

    if buildings is None:
        from .planet_evolution.repository import get_context_planet

        planet = get_context_planet(int(user_id))
        buildings = get_planet_buildings(int(planet["id"]))

    from .effects import EffectResolver

    research_levels = get_research_levels(int(user_id))
    resolver = EffectResolver(buildings, research_levels, player_id=int(user_id))
    return resolver.get_research_time_seconds(tech_key, max(1, int(level)))


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
    cur = conn.cursor()
    schedule_at = ts
    queued_counts: Dict[str, int] = {}

    for idx, row in enumerate(rows):
        tech = str(row["tech_key"])
        current = int(levels.get(tech, 0) or 0)
        queued_same = int(queued_counts.get(tech, 0))
        target = current + queued_same + 1
        duration = float(get_research_time(tech, target, user_id=uid, buildings=buildings))

        if idx == 0:
            start_existing = float(row["start_at"] or 0)
            finish_existing = float(row["finish_at"] or 0)
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
            return max(base, RESEARCH_QUEUE_LIMIT_AT_LAB4)
    return base


# ======================================================================
# QUEUE START
# ======================================================================

def queue_research(player: dict, tech_key: str, user_id: Optional[int] = None):
    if tech_key not in RESEARCH_TECHS:
        return False, "unknown_tech", None

    if user_id is None:
        pid = player.get("id")
        if pid is None:
            raise RuntimeError("queue_research: player hat kein 'id'")
        uid = int(pid)
    else:
        uid = int(user_id)

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

        cur = conn.cursor()
        cur.execute(
            "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
            (planet_id,),
        )
        prow = cur.fetchone()
        if not prow:
            rollback(conn)
            return False, "no_homeworld", None

        planet_metal = float(prow["metal"] or 0)
        planet_crystal = float(prow["crystal"] or 0)

        buildings = resolve_buildings_for_research(
            get_planet_buildings(planet_id, conn=conn),
            uid,
            conn=conn,
        )
        levels = get_research_levels(uid, conn=conn)

        if int(buildings.get("research_lab", 0) or 0) <= 0:
            rollback(conn)
            return False, "no_research_lab", None

        if not has_research_requirements(buildings, levels, tech_key):
            rollback(conn)
            return False, "requirements", None

        rows = get_research_queue_rows(uid, conn=conn)
        research_queue_limit = _resolve_research_queue_limit(player_id=uid, conn=conn)
        if len(rows) >= research_queue_limit:
            rollback(conn)
            return False, "research_queue_full", {
                "queue_count": len(rows),
                "queue_limit": research_queue_limit,
            }

        queued_same = sum(1 for r in rows if str(r["tech_key"]) == tech_key)
        current = int(levels.get(tech_key, 0) or 0)
        target = current + queued_same + 1

        cost_m, cost_c = get_research_cost(tech_key, target)

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

        if planet_metal < float(cost_m) or planet_crystal < float(cost_c):
            rollback(conn)
            return False, "not_enough_resources", _research_not_enough_payload(
                planet_metal=planet_metal,
                planet_crystal=planet_crystal,
                cost_m=int(cost_m),
                cost_c=int(cost_c),
            )

        duration = get_research_time(tech_key, target, user_id=uid, buildings=buildings)
        last_finish = max(float(r["finish_at"]) for r in rows) if rows else now
        start_at = max(now, last_finish)
        finish_at = start_at + float(duration)

        if not try_spend_resources_conn(conn, planet_id, int(cost_m), int(cost_c)):
            rollback(conn)
            cur.execute(
                "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
                (planet_id,),
            )
            after = cur.fetchone()
            avail_m = float(after["metal"] or 0) if after else planet_metal
            avail_c = float(after["crystal"] or 0) if after else planet_crystal
            return False, "not_enough_resources", _research_not_enough_payload(
                planet_metal=avail_m,
                planet_crystal=avail_c,
                cost_m=int(cost_m),
                cost_c=int(cost_c),
            )

        job_id = add_research_job(uid, tech_key, float(start_at), float(finish_at), conn=conn)

        commit(conn)

        if finished_any:
            invalidate_player_score_cache(uid)

        return True, "ok", {
            "job_id": int(job_id),
            "seconds": int(duration),
            "level": int(target),
            "target_level": int(target),
            "queued": len(rows) > 0,
        }

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
            SELECT id, tech_key
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

        delete_research_job(int(row["id"]), conn=conn)
        recalculate_research_queue_finish_times(uid, conn=conn, now=now)
        commit(conn)

        if finished_any:
            invalidate_player_score_cache(uid)

        return True, "ok", {
            "job_id": int(row["id"]),
            "tech_key": str(row["tech_key"]),
            "cancelled": True,
        }
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


# ======================================================================
# STATUS FOR UI
# ======================================================================

def get_research_status(
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
    *,
    skip_finish: bool = False,
    conn=None,
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

    planet_metal = float(resource_planet.get("metal") or 0)
    planet_crystal = float(resource_planet.get("crystal") or 0)

    if buildings is None:
        buildings = get_planet_buildings(int(resource_planet["id"]), conn=conn)

    buildings = resolve_buildings_for_research(buildings, uid, conn=conn)
    lab_level = int(buildings.get("research_lab", 0) or 0)

    levels = get_research_levels(uid, conn=conn)
    queue = get_research_queue_rows(uid, conn=conn)
    now = time.time()

    if not skip_finish:
        for _ in range(3):
            if not queue:
                break
            if float(queue[0]["finish_at"]) > now:
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
            start_at = finish_at - float(get_research_time(tech, targ, user_id=int(user_id), buildings=buildings))

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
            "label": cfg.get("label", tech),
            "label_key": cfg.get("label_key"),
            "description": cfg.get("description", ""),
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

    active = queue_list[0] if queue_list else None

    queue_keys: Dict[str, int] = {}
    for item in queue_list:
        k = str(item["tech_key"])
        queue_keys[k] = queue_keys.get(k, 0) + 1

    techs: List[Dict[str, Any]] = []
    for tech, cfg in RESEARCH_TECHS.items():
        curr = int(levels.get(tech, 0) or 0)
        q_count = int(queue_keys.get(tech, 0) or 0)
        targ = curr + q_count + 1

        cost_m, cost_c = get_research_cost(tech, targ)
        t_sec = get_research_time(tech, targ, user_id=int(user_id), buildings=buildings)

        req = cfg.get("requirements") or {}
        req_met = _check_requirements(req, buildings, levels)
        can_afford = planet_metal >= float(cost_m) and planet_crystal >= float(cost_c)

        is_active = bool(active and str(active.get("tech_key")) == tech)
        in_queue = q_count > 0

        effect_preview = get_research_effect_preview(tech, curr, targ)

        techs.append({
            "key": tech,
            "label": cfg.get("label", tech),
            "label_key": cfg.get("label_key"),
            "description": cfg.get("description", ""),
            "description_key": cfg.get("description_key"),
            "category": cfg.get("category", ""),
            "level": curr,
            "target_level": targ,
            "cost_metal": int(cost_m),
            "cost_crystal": int(cost_c),
            "time_seconds": int(t_sec),
            "requirements_met": bool(req_met),
            "can_afford": bool(can_afford),
            "requirements_items": get_research_requirements_items(tech, buildings, levels),
            "resource_items": [
                {
                    "kind": "resource",
                    "key": "metal",
                    "need": int(cost_m),
                    "have": int(planet_metal),
                    "met": planet_metal >= float(cost_m),
                },
                {
                    "kind": "resource",
                    "key": "crystal",
                    "need": int(cost_c),
                    "have": int(planet_crystal),
                    "met": planet_crystal >= float(cost_c),
                },
            ],
            "icon": cfg.get("icon"),
            "queue_count": q_count,
            "is_active": is_active,
            "in_queue": in_queue,
            **effect_preview,
        })

    research_queue_limit = _resolve_research_queue_limit(player_id=uid, conn=conn)
    summary = {
        "count": len(queue_list),
        "limit": research_queue_limit,
        "has_queue": bool(queue_list),
        "first_finish_in": int(queue_list[0]["remaining"]) if queue_list else 0,
    }

    _attach_queue_jobs_to_research_techs(techs, queue_list)

    return {
        "active": active,
        "queue": queue_list,
        "summary": summary,
        "techs": techs,
        "lab_level": lab_level,
    }


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
