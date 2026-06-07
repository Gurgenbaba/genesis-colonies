"""
Gebäude-Logik für Genesis Colonies.
"""

from __future__ import annotations

import time
from typing import Dict, List, Tuple, Any, Optional

from .models import (
    db,
    get_planet_buildings,
    save_planet_buildings,
    get_build_queue_rows,
    add_build_job,
    delete_build_job,
    get_game_settings,
    get_research_levels,
    try_spend_resources_conn,
    get_planet_owner_id,
)
from .db import begin_write_transaction, commit, rollback, lock_planet_for_update
from .research import RESEARCH_TECHS
from .effects import EffectResolver, get_effect_resolver
from .ranking import invalidate_player_score_cache  # ✅ Cache invalidieren nach Finish

# =============================================================================
#   KONFIG: Gebäude-Keys / Reihenfolge / Tabs / Icons
# =============================================================================

BUILDING_ORDER: List[str] = [
    "metal_mine",
    "crystal_mine",
    "solar_plant",
    "fuel_cell_plant",
    "research_lab",
    "academy",
    "metal_storage",
    "crystal_storage",
    "fuel_storage",
    "command_center",
    "orbital_shipyard",
    "defense_factory",
    "barracks",
    "radar_array",
    "shield_generator",
    "terraformer",
    "nanofactory",
    "geothermal_nexus",
    "planet_core_nexus",
]

ALL_BUILDINGS = set(BUILDING_ORDER)

BUILDING_TAB: Dict[str, str] = {
    "metal_mine": "resources",
    "crystal_mine": "resources",
    "solar_plant": "resources",
    "fuel_cell_plant": "resources",
    "research_lab": "research",
    "academy": "research",
    "metal_storage": "resources",
    "crystal_storage": "resources",
    "fuel_storage": "resources",
    "command_center": "infrastructure",
    "orbital_shipyard": "military",
    "defense_factory": "military",
    "barracks": "military",
    "radar_array": "military",
    "shield_generator": "infrastructure",
    "terraformer": "infrastructure",
    "nanofactory": "infrastructure",
    "geothermal_nexus": "infrastructure",
    "planet_core_nexus": "infrastructure",
}

_BUILDING_ICON_OVERRIDES: Dict[str, str] = {
    "orbital_shipyard": "img/buildings/shipyard.png",
    "fuel_cell_plant": "img/buildings/solar_plant.png",
    "fuel_storage": "img/buildings/crystal_storage.png",
}

BUILDING_ICON: Dict[str, str] = {
    key: _BUILDING_ICON_OVERRIDES.get(key, f"img/buildings/{key}.png")
    for key in BUILDING_ORDER
}

# =============================================================================
#   KONFIG: Kosten, Zeit, Requirements
# =============================================================================

BASE_COST: Dict[str, Tuple[int, int]] = {
    "metal_mine": (75, 25),
    "crystal_mine": (40, 28),
    "solar_plant": (45, 11),
    "fuel_cell_plant": (120, 80),
    "research_lab": (200, 400),
    "academy": (400, 600),
    "metal_storage": (1000, 0),
    "crystal_storage": (0, 1000),
    "fuel_storage": (600, 400),
    "command_center": (500, 200),
    "orbital_shipyard": (400, 300),
    "defense_factory": (600, 400),
    "barracks": (300, 200),
    "radar_array": (200, 600),
    "shield_generator": (1000, 800),
    "terraformer": (2500, 2500),
    "nanofactory": (4000, 2500),
    "geothermal_nexus": (6000, 6000),
    "planet_core_nexus": (8000, 12000),
}

COST_FACTOR: Dict[str, float] = {
    "metal_mine": 1.5,
    "crystal_mine": 1.6,
    "solar_plant": 1.5,
    "fuel_cell_plant": 1.55,
    "research_lab": 1.8,
    "academy": 1.8,
    "metal_storage": 1.7,
    "crystal_storage": 1.7,
    "fuel_storage": 1.7,
    "command_center": 2.0,
    "orbital_shipyard": 1.9,
    "defense_factory": 1.9,
    "barracks": 1.7,
    "radar_array": 1.7,
    "shield_generator": 2.1,
    "terraformer": 1.9,
    "nanofactory": 2.1,
    "geothermal_nexus": 2.0,
    "planet_core_nexus": 2.2,
}

BUILD_TIME_BASE: Dict[str, int] = {
    "metal_mine": 51,
    "crystal_mine": 51,
    "solar_plant": 68,
    "fuel_cell_plant": 90,
    "research_lab": 120,
    "academy": 180,
    "metal_storage": 120,
    "crystal_storage": 120,
    "fuel_storage": 120,
    "command_center": 240,
    "orbital_shipyard": 200,
    "defense_factory": 220,
    "barracks": 160,
    "radar_array": 160,
    "shield_generator": 300,
    "terraformer": 260,
    "nanofactory": 480,
    "geothermal_nexus": 540,
    "planet_core_nexus": 600,
}

BUILD_TIME_FACTOR: Dict[str, float] = {
    "metal_mine": 1.4,
    "crystal_mine": 1.4,
    "solar_plant": 1.5,
    "fuel_cell_plant": 1.45,
    "research_lab": 1.6,
    "academy": 1.6,
    "metal_storage": 1.6,
    "crystal_storage": 1.6,
    "fuel_storage": 1.6,
    "command_center": 1.7,
    "orbital_shipyard": 1.7,
    "defense_factory": 1.7,
    "barracks": 1.6,
    "radar_array": 1.6,
    "shield_generator": 1.8,
    "terraformer": 1.7,
    "nanofactory": 1.8,
    "geothermal_nexus": 1.8,
    "planet_core_nexus": 1.9,
}

DEFAULT_BUILD_TIME_LEVEL_1 = 60
MAX_BUILDING_LEVEL = 50

BUILDING_REQUIREMENTS: Dict[str, Dict[str, Dict[str, int]]] = {
    "metal_mine": {},
    "crystal_mine": {},
    "solar_plant": {},

    "fuel_cell_plant": {"buildings": {"solar_plant": 1, "crystal_mine": 2}},

    "research_lab": {"buildings": {"metal_mine": 3, "crystal_mine": 2}},
    "academy": {"buildings": {"research_lab": 2}},

    "metal_storage": {"buildings": {"metal_mine": 4}},
    "crystal_storage": {"buildings": {"crystal_mine": 4}},
    "fuel_storage": {"buildings": {"fuel_cell_plant": 4}},

    "command_center": {},
    "orbital_shipyard": {"buildings": {"command_center": 2}},
    "defense_factory": {"buildings": {"orbital_shipyard": 2}},
    "barracks": {"buildings": {"command_center": 1}},
    "radar_array": {"buildings": {"command_center": 3}},
    "shield_generator": {"buildings": {"command_center": 4, "defense_factory": 2}},

    "terraformer": {
        "buildings": {"command_center": 4, "metal_storage": 3, "crystal_storage": 3},
        "research": {"storage_tech": 1},
    },
    "nanofactory": {
        "buildings": {"command_center": 4},
        "research": {"drone_tech": 3, "engine_tech": 2},
    },
    "geothermal_nexus": {
        "buildings": {"command_center": 5, "crystal_storage": 4},
        "research": {"storage_tech": 2, "energy_tech": 3},
    },
    "planet_core_nexus": {
        "buildings": {"command_center": 6, "nanofactory": 2, "geothermal_nexus": 1},
        "research": {"storage_tech": 3, "energy_tech": 4},
    },
}

# =============================================================================
# Helpers
# =============================================================================

def get_building_icon(building_type: str) -> str:
    return BUILDING_ICON.get(building_type, "img/buildings/default.png")


def get_building_tab(building_type: str) -> str:
    return BUILDING_TAB.get(building_type, "infrastructure")


def get_building_label_key(building_type: str) -> str:
    return f"building_{building_type}"


# =============================================================================
# Costs & Time
# =============================================================================

def get_upgrade_cost(building_type: str, current_level: int) -> Tuple[int, int]:
    base = BASE_COST.get(building_type, (100, 50))
    factor = COST_FACTOR.get(building_type, 1.5)
    target_level = max(int(current_level) + 1, 1)
    multiplier = factor ** (target_level - 1)
    metal = int(base[0] * multiplier)
    crystal = int(base[1] * multiplier)
    return metal, crystal


def get_build_time(
    building_type: str,
    target_level: int,
    user_id: Optional[int] = None,
    *,
    conn=None,
    buildings: Optional[Dict[str, int]] = None,
    research_levels: Optional[Dict[str, int]] = None,
) -> int:
    if user_id is None:
        base_time = BUILD_TIME_BASE.get(building_type, DEFAULT_BUILD_TIME_LEVEL_1)
        factor = BUILD_TIME_FACTOR.get(building_type, 1.5)
        lvl_factor = factor ** max(int(target_level) - 1, 0)
        return max(int(base_time * lvl_factor), 1)

    if buildings is not None and research_levels is not None:
        resolver = get_effect_resolver(
            int(user_id),
            buildings=buildings,
            research=research_levels,
            conn=conn,
            force_refresh=True,
        )
    else:
        resolver = get_effect_resolver(int(user_id), force_refresh=True)
    return resolver.get_build_time_seconds(building_type, int(target_level))


def recalculate_build_queue_finish_times(
    planet_id: int,
    user_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    """
    Reschedule all build jobs on a planet after cancel or before enqueue.
    In-progress first job (start <= now < finish) keeps its window; followers chain from its finish or now.
    """
    planet_id = int(planet_id)
    uid = int(user_id)
    ts = float(now if now is not None else time.time())
    rows = get_build_queue_rows(planet_id, conn=conn)
    if not rows:
        return

    buildings = get_planet_buildings(planet_id, conn=conn)
    research_levels = get_research_levels(user_id=uid, conn=conn)
    cur = conn.cursor()
    schedule_at = ts
    queued_counts: Dict[str, int] = {}

    for idx, row in enumerate(rows):
        btype = str(row["building_type"])
        current = int(buildings.get(btype, 0) or 0)
        queued_same = int(queued_counts.get(btype, 0))
        target_level = current + queued_same + 1
        duration = int(
            get_build_time(
                btype,
                target_level,
                user_id=uid,
                conn=conn,
                buildings=buildings,
                research_levels=research_levels,
            )
        )

        if idx == 0:
            start_existing = float(row["start_time"] or 0)
            finish_existing = float(row["finish_time"] or 0)
            if start_existing <= ts < finish_existing:
                queued_counts[btype] = queued_same + 1
                schedule_at = finish_existing
                continue

        start_time = schedule_at
        finish_time = schedule_at + duration
        cur.execute(
            """
            UPDATE build_queue
            SET start_time = ?, finish_time = ?
            WHERE id = ?;
            """,
            (float(start_time), float(finish_time), int(row["id"])),
        )
        queued_counts[btype] = queued_same + 1
        schedule_at = finish_time


# =============================================================================
# Dynamic Max Level
# =============================================================================

def get_max_level_for_building(building_type: str, buildings: Dict[str, int]) -> int:
    return EffectResolver(buildings, {}).get_max_building_level(building_type)


# =============================================================================
# Requirements
# =============================================================================

def _check_requirements_for_building(
    building_type: str,
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> bool:
    req_cfg = BUILDING_REQUIREMENTS.get(building_type) or {}
    req_buildings = req_cfg.get("buildings", {})
    req_research = req_cfg.get("research", {})

    for b_key, need_lvl in req_buildings.items():
        if int(buildings.get(b_key, 0) or 0) < int(need_lvl):
            return False

    for r_key, need_lvl in req_research.items():
        if int(research_levels.get(r_key, 0) or 0) < int(need_lvl):
            return False

    return True


def has_building_requirements(buildings: Dict[str, int], research_levels: Dict[str, int], building_type: str) -> bool:
    return _check_requirements_for_building(building_type, buildings, research_levels)


def get_building_requirements_items(
    building_type: str,
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> List[Dict[str, Any]]:
    req_cfg = BUILDING_REQUIREMENTS.get(building_type) or {}
    items: List[Dict[str, Any]] = []

    for b_key, need_lvl in (req_cfg.get("buildings") or {}).items():
        have = int(buildings.get(b_key, 0) or 0)
        need = int(need_lvl)
        items.append({
            "kind": "building",
            "key": b_key,
            "need": need,
            "have": have,
            "met": have >= need,
        })

    for r_key, need_lvl in (req_cfg.get("research") or {}).items():
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


# =============================================================================
# Panel Rows
# =============================================================================

BUILDING_PRODUCTION_RESOURCE: Dict[str, str] = {
    "metal_mine": "metal",
    "crystal_mine": "crystal",
    "fuel_cell_plant": "fuel_cells",
}

BUILDING_ENERGY_CONSUMERS = frozenset({"metal_mine", "crystal_mine", "fuel_cell_plant"})

OVERVIEW_BUILDING_KEYS = ("metal_mine", "crystal_mine", "solar_plant")


def _panel_energy_ratio(buildings: Dict[str, int], research_levels: Dict[str, int]) -> float:
    resolver = EffectResolver(buildings, research_levels or {})
    energy_total, energy_used = resolver.compute_energy()
    return float(EffectResolver.energy_ratio(energy_total, energy_used))


def _panel_effect_snapshot(
    *,
    effect_kind: str,
    effect_current: int,
    effect_next: int,
    effect_resource: str = "",
    effect_unit: str = "",
) -> Dict[str, Any]:
    cur = int(effect_current or 0)
    nxt = int(effect_next or 0)
    delta = max(0, nxt - cur)
    out: Dict[str, Any] = {
        "effect_kind": effect_kind,
        "effect_current": cur,
        "effect_next": nxt,
        "effect_delta": delta,
        "effect_resource": effect_resource,
        "effect_unit": effect_unit,
    }
    if effect_kind == "production":
        out.update(
            {
                "production_per_hour": cur,
                "production_next_per_hour": nxt,
                "production_delta": delta,
                "production_resource": effect_resource,
            }
        )
    return out


def _panel_secondary_energy_effect(
    *,
    r_now: EffectResolver,
    r_next: EffectResolver,
    building_type: str,
    buildings: Dict[str, int],
    target_level: int,
) -> Optional[Dict[str, Any]]:
    if building_type not in BUILDING_ENERGY_CONSUMERS:
        return None
    cur_lvl = int(buildings.get(building_type, 0) or 0)
    nxt_lvl = int(target_level)
    cur_e = r_now.building_energy_draw(building_type, level=cur_lvl)
    nxt_e = r_next.building_energy_draw(building_type, level=nxt_lvl)
    if cur_e <= 0 and nxt_e <= 0:
        return None
    return _panel_effect_snapshot(
        effect_kind="energy_use",
        effect_current=cur_e,
        effect_next=nxt_e,
        effect_resource="energy",
        effect_unit="",
    )


def _panel_upgrade_effect_fields(
    building_type: str,
    buildings: Dict[str, int],
    target_level: int,
    ratio: float,
    research_levels: Dict[str, int],
) -> Dict[str, Any]:
    """Authoritative upgrade preview per building (EffectResolver / production helpers)."""
    from .logic import get_building_production_per_hour

    bumped = dict(buildings)
    bumped[building_type] = int(target_level)
    r_now = EffectResolver(buildings, research_levels or {})
    r_next = EffectResolver(bumped, research_levels or {})

    if building_type in BUILDING_PRODUCTION_RESOURCE:
        prod_now = get_building_production_per_hour(
            buildings, ratio, research=research_levels
        )
        prod_next = get_building_production_per_hour(
            bumped, ratio, research=research_levels
        )
        out = _panel_effect_snapshot(
            effect_kind="production",
            effect_current=int(prod_now.get(building_type, 0) or 0),
            effect_next=int(prod_next.get(building_type, 0) or 0),
            effect_resource=BUILDING_PRODUCTION_RESOURCE[building_type],
            effect_unit="/h",
        )
        sec = _panel_secondary_energy_effect(
            r_now=r_now,
            r_next=r_next,
            building_type=building_type,
            buildings=buildings,
            target_level=target_level,
        )
        if sec:
            out["secondary_effect"] = sec
        return out

    if building_type == "solar_plant":
        cur_et, _ = r_now.compute_energy()
        nxt_et, _ = r_next.compute_energy()
        return _panel_effect_snapshot(
            effect_kind="energy",
            effect_current=cur_et,
            effect_next=nxt_et,
            effect_resource="energy",
            effect_unit="",
        )

    if building_type == "metal_storage":
        caps_now = r_now.get_storage_capacity()
        caps_next = r_next.get_storage_capacity()
        return _panel_effect_snapshot(
            effect_kind="storage",
            effect_current=int(caps_now.get("metal", 0) or 0),
            effect_next=int(caps_next.get("metal", 0) or 0),
            effect_resource="metal",
            effect_unit="",
        )

    if building_type == "crystal_storage":
        caps_now = r_now.get_storage_capacity()
        caps_next = r_next.get_storage_capacity()
        return _panel_effect_snapshot(
            effect_kind="storage",
            effect_current=int(caps_now.get("crystal", 0) or 0),
            effect_next=int(caps_next.get("crystal", 0) or 0),
            effect_resource="crystal",
            effect_unit="",
        )

    if building_type == "fuel_storage":
        caps_now = r_now.get_storage_capacity()
        caps_next = r_next.get_storage_capacity()
        return _panel_effect_snapshot(
            effect_kind="storage",
            effect_current=int(caps_now.get("fuel_cells", 0) or 0),
            effect_next=int(caps_next.get("fuel_cells", 0) or 0),
            effect_resource="fuel_cells",
            effect_unit="",
        )

    if building_type == "research_lab":
        cur_pct = int(round((r_now.research_lab_bonus() - 1.0) * 100))
        nxt_pct = int(round((r_next.research_lab_bonus() - 1.0) * 100))
        return _panel_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=cur_pct,
            effect_next=nxt_pct,
            effect_resource="research",
            effect_unit="%",
        )

    if building_type == "academy":
        lvl = int(buildings.get("academy", 0) or 0)
        cur_pct = int(round(max(0, lvl) * 5))
        nxt_pct = int(round(max(0, int(target_level)) * 5))
        return _panel_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=cur_pct,
            effect_next=nxt_pct,
            effect_resource="research",
            effect_unit="%",
        )

    if building_type == "nanofactory":
        cur_pct = int(round((float(r_now.get_modifiers().get("build_time_speed", 1.0) or 1.0) - 1.0) * 100))
        nxt_pct = int(round((float(r_next.get_modifiers().get("build_time_speed", 1.0) or 1.0) - 1.0) * 100))
        return _panel_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=cur_pct,
            effect_next=nxt_pct,
            effect_resource="build",
            effect_unit="%",
        )

    if building_type == "command_center":
        cc_cur = int(buildings.get("command_center", 0) or 0)
        cc_nxt = int(target_level)
        return _panel_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=int(25 * cc_cur),
            effect_next=int(25 * cc_nxt),
            effect_resource="build",
            effect_unit="%",
        )

    if building_type == "terraformer":
        terra_cur = int(buildings.get("terraformer", 0) or 0)
        terra_nxt = int(target_level)
        return _panel_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=int(5 * terra_cur),
            effect_next=int(5 * terra_nxt),
            effect_resource="storage",
            effect_unit="%",
        )

    if building_type == "geothermal_nexus":
        cur_max = r_now.get_max_building_level("metal_mine")
        nxt_max = r_next.get_max_building_level("metal_mine")
        return _panel_effect_snapshot(
            effect_kind="max_level",
            effect_current=cur_max,
            effect_next=nxt_max,
            effect_resource="",
            effect_unit="",
        )

    if building_type == "planet_core_nexus":
        cur_max = r_now.get_max_building_level("metal_mine")
        nxt_max = r_next.get_max_building_level("metal_mine")
        return _panel_effect_snapshot(
            effect_kind="max_level",
            effect_current=cur_max,
            effect_next=nxt_max,
            effect_resource="",
            effect_unit="",
        )

    if building_type == "radar_array":
        radar_cur = int(buildings.get("radar_array", 0) or 0)
        radar_nxt = int(target_level)
        return _panel_effect_snapshot(
            effect_kind="scan",
            effect_current=2 * radar_cur,
            effect_next=2 * radar_nxt,
            effect_resource="",
            effect_unit="",
        )

    lvl_cur = int(buildings.get(building_type, 0) or 0)
    lvl_nxt = int(target_level)
    return _panel_effect_snapshot(
        effect_kind="level",
        effect_current=lvl_cur,
        effect_next=lvl_nxt,
        effect_resource="",
        effect_unit="",
    )


def _make_panel_row(
    planet: dict,
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
    building_type: str,
    queue_count: int = 0,
    ratio: float = 1.0,
) -> Dict[str, Any]:
    level = int(buildings.get(building_type, 0) or 0)
    max_level = get_max_level_for_building(building_type, buildings)
    queued_same = int(queue_count or 0)
    at_queue_max = (level + queued_same) >= max_level
    target_level = min(level + queued_same + 1, max_level)

    cost_metal, cost_crystal = get_upgrade_cost(building_type, level + queued_same)
    time_seconds = get_build_time(building_type, target_level, user_id=planet.get("player_id"))

    req_met = has_building_requirements(buildings, research_levels, building_type)
    can_afford = (float(planet.get("metal", 0) or 0) >= cost_metal and float(planet.get("crystal", 0) or 0) >= cost_crystal)

    row: Dict[str, Any] = {
        "key": building_type,
        "tab": get_building_tab(building_type),
        "icon": get_building_icon(building_type),
        "level": level,
        "target_level": target_level,
        "max_level": max_level,
        "queue_count": queued_same,
        "at_queue_max": bool(at_queue_max),
        "cost_metal": cost_metal,
        "cost_crystal": cost_crystal,
        "time_seconds": int(time_seconds),
        "requirements_met": bool(req_met),
        "requirements_items": get_building_requirements_items(building_type, buildings, research_levels),
        "can_afford": bool(can_afford),
    }
    row.update(
        _panel_upgrade_effect_fields(
            building_type, buildings, target_level, ratio, research_levels
        )
    )
    return row


def get_buildings_panel_rows(
    planet: dict,
    buildings: Dict[str, int],
    build_queue: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    user_id = planet.get("player_id")
    if user_id is None:
        raise RuntimeError("get_buildings_panel_rows: planet hat kein 'player_id'-Feld")

    research_levels = get_research_levels(user_id=int(user_id))
    ratio = _panel_energy_ratio(buildings, research_levels)

    queue_counts: Dict[str, int] = {}
    if build_queue and isinstance(build_queue.get("queue"), list):
        for job in build_queue["queue"]:
            bt = str(job.get("building_type") or "")
            if bt:
                queue_counts[bt] = queue_counts.get(bt, 0) + 1

    rows_by_tab: Dict[str, List[Dict[str, Any]]] = {
        "resources": [],
        "research": [],
        "military": [],
        "infrastructure": [],
    }

    for key in BUILDING_ORDER:
        row = _make_panel_row(
            planet,
            buildings,
            research_levels,
            key,
            queue_count=queue_counts.get(key, 0),
            ratio=ratio,
        )
        rows_by_tab.setdefault(row["tab"], []).append(row)

    _attach_queue_jobs_to_panel_rows(rows_by_tab, build_queue)

    return rows_by_tab


def _attach_queue_jobs_to_panel_rows(
    rows_by_tab: Dict[str, List[Dict[str, Any]]],
    build_queue: Optional[Dict[str, Any]],
    *,
    now: Optional[float] = None,
) -> None:
    """GC-536B: optional queue_job on each panel row (presentation only)."""
    from .queue_card import (
        card_queue_job_for_item,
        group_card_jobs_by_owner_key,
        map_build_queue_to_card_jobs,
    )

    card_jobs = map_build_queue_to_card_jobs(build_queue, now=now)
    by_key = group_card_jobs_by_owner_key(card_jobs)

    for rows in rows_by_tab.values():
        for row in rows:
            owner_key = str(row.get("key") or "")
            qj = card_queue_job_for_item(by_key, owner_key) if owner_key else None
            if qj:
                enriched = dict(qj)
                target_level = enriched.get("target_level")
                if target_level is not None:
                    enriched["current_level"] = max(0, int(target_level) - 1)
                row["queue_job"] = enriched
            elif "queue_job" in row:
                del row["queue_job"]


def get_overview_building_rows(
    planet: dict,
    buildings: Dict[str, int],
    build_queue: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Compact upgrade-preview rows for overview widgets (key resource buildings)."""
    user_id = planet.get("player_id")
    if user_id is None:
        return []

    research_levels = get_research_levels(user_id=int(user_id))
    ratio = _panel_energy_ratio(buildings, research_levels)

    queue_counts: Dict[str, int] = {}
    if build_queue and isinstance(build_queue.get("queue"), list):
        for job in build_queue["queue"]:
            bt = str(job.get("building_type") or "")
            if bt:
                queue_counts[bt] = queue_counts.get(bt, 0) + 1

    rows: List[Dict[str, Any]] = []
    for key in OVERVIEW_BUILDING_KEYS:
        row = _make_panel_row(
            planet,
            buildings,
            research_levels,
            key,
            queue_count=queue_counts.get(key, 0),
            ratio=ratio,
        )
        rows.append(row)
    return rows


# =============================================================================
# Build Queue
# =============================================================================

def _resolve_build_queue_limit(settings: Optional[Dict[str, Any]] = None) -> int:
    if settings is None:
        settings = get_game_settings()
    raw_limit = settings.get("queue_limit", 3)
    try:
        queue_limit = int(raw_limit)
    except (ValueError, TypeError):
        try:
            queue_limit = int(float(raw_limit))
        except (ValueError, TypeError):
            queue_limit = 3
    return max(queue_limit, 1)


def get_build_queue_status_for_planet(
    planet_id: int,
    conn=None,
    *,
    skip_finish: bool = False,
) -> Dict[str, Any]:
    """
    Liefert Queue + Summary für ein Planet.
    Finish läuft über queue_engine (Caller oder skip_finish=True).
    """
    own = False
    if conn is None:
        conn = db()
        own = True

    try:
        cur = conn.cursor()
        now = time.time()

        from .live_state import coerce_skip_finish

        if not coerce_skip_finish(bool(skip_finish)):
            cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
            prow = cur.fetchone()
            if prow:
                from .queue_engine import finish_active_planet_due_work

                finish_active_planet_due_work(
                    int(prow["player_id"]),
                    int(planet_id),
                    conn,
                    source="build_queue_status",
                )

        buildings = get_planet_buildings(int(planet_id), conn=conn)

        # Queue rows aus derselben conn lesen
        cur.execute(
            """
            SELECT id, building_type, start_time, finish_time
            FROM build_queue
            WHERE planet_id = ?
            ORDER BY finish_time ASC;
            """,
            (int(planet_id),),
        )
        rows_db = cur.fetchall()

        counts: Dict[str, int] = {}
        queue: List[Dict[str, Any]] = []
        first_remaining: Optional[int] = None

        for r in rows_db:
            b_type = str(r["building_type"])
            counts[b_type] = counts.get(b_type, 0) + 1

            finish_time = float(r["finish_time"])
            start_time = float(r["start_time"] or finish_time)

            remaining = max(0, int(finish_time - now))
            total = max(1, int(finish_time - start_time))

            if first_remaining is None or remaining < first_remaining:
                first_remaining = remaining

            current_level = int(buildings.get(b_type, 0) or 0)
            target_level = current_level + counts[b_type]

            queue.append({
                "id": int(r["id"]),
                "building_type": b_type,
                "label_key": get_building_label_key(b_type),
                "target_level": int(target_level),
                "remaining": int(remaining),
                "total": int(total),
                "finish_time": finish_time,
            })

        queue_limit = _resolve_build_queue_limit()

        summary = {
            "count": len(queue),
            "limit": queue_limit,
            "has_queue": bool(queue),
            "first_finish_in": int(first_remaining or 0),
        }

        return {
            "planet_id": int(planet_id),
            "queue": queue,
            "summary": summary,
        }

    finally:
        if own:
            conn.close()


def complete_finished_builds_for_planet(planet_id: int, conn=None) -> Dict[str, int]:
    """
    Conn-safe: delegiert an queue_engine.finish_due_work (Build + Research des Owners).
    """
    planet_id = int(planet_id)
    owner_id = get_planet_owner_id(planet_id)
    if not owner_id:
        return get_planet_buildings(planet_id, conn=conn)

    from .models import db as _db
    from .queue_engine import finish_due_work_once

    own_conn = False
    if conn is None:
        conn = _db()
        own_conn = True

    try:
        if own_conn:
            begin_write_transaction(conn)

        finish_due_work_once(
            player_id=int(owner_id),
            planet_id=planet_id,
            conn=conn,
            source="buildings",
        )

        buildings = get_planet_buildings(planet_id, conn=conn)

        if own_conn:
            commit(conn)
        return buildings
    except Exception:
        if own_conn:
            rollback(conn)
        raise
    finally:
        if own_conn:
            conn.close()


def queue_build_for_planet(
    planet: dict,
    buildings: Dict[str, int],
    building_type: str,
    user_id: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if building_type not in BASE_COST:
        return False, "invalid", {"msg": "Unknown building type"}

    planet_id = int(planet["id"])
    if user_id is None:
        pid = planet.get("player_id")
        if pid is None:
            raise RuntimeError("queue_build_for_planet: planet hat kein 'player_id'")
        user_id = int(pid)
    else:
        user_id = int(user_id)

    conn = db()
    finished_any = False
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)
        now = time.time()

        from .queue_engine import finish_due_work

        engine_result = finish_due_work(
            player_id=user_id,
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

        recalculate_build_queue_finish_times(
            planet_id, user_id, conn=conn, now=now
        )

        cur = conn.cursor()
        cur.execute(
            "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
            (planet_id,),
        )
        prow = cur.fetchone()
        if not prow:
            rollback(conn)
            return False, "invalid", {"msg": "Planet not found"}

        planet_metal = float(prow["metal"] or 0)
        planet_crystal = float(prow["crystal"] or 0)

        buildings = get_planet_buildings(planet_id, conn=conn)
        research_levels = get_research_levels(user_id=user_id, conn=conn)

        current_level = int(buildings.get(building_type, 0) or 0)
        max_level = get_max_level_for_building(building_type, buildings)

        if current_level >= max_level:
            rollback(conn)
            return False, "invalid", {"msg": "Max level reached", "max_level": max_level}

        rows_db = get_build_queue_rows(planet_id, conn=conn)
        queued_same = sum(1 for r in rows_db if str(r["building_type"]) == building_type)
        target_level = current_level + queued_same + 1

        if target_level > max_level:
            rollback(conn)
            return False, "invalid", {
                "msg": "Max level reached",
                "max_level": max_level,
                "target_level": target_level,
            }

        if not has_building_requirements(buildings, research_levels, building_type):
            rollback(conn)
            return False, "requirements", {
                "building_type": building_type,
                "current_level": current_level,
                "target_level": target_level,
            }

        cost_metal, cost_crystal = get_upgrade_cost(building_type, current_level + queued_same)

        if planet_metal < cost_metal or planet_crystal < cost_crystal:
            rollback(conn)
            return False, "resources", {
                "building_type": building_type,
                "current_level": current_level,
                "target_level": target_level,
                "cost_metal": cost_metal,
                "cost_crystal": cost_crystal,
                "planet_metal": planet_metal,
                "planet_crystal": planet_crystal,
            }

        settings = get_game_settings(conn=conn)
        queue_limit = _resolve_build_queue_limit(settings)

        if len(rows_db) >= queue_limit:
            rollback(conn)
            return False, "queue_full", {"queue_count": len(rows_db), "queue_limit": queue_limit}

        duration = get_build_time(
            building_type,
            target_level,
            user_id=user_id,
            conn=conn,
            buildings=buildings,
            research_levels=research_levels,
        )

        last_finish_time = max(float(r["finish_time"]) for r in rows_db) if rows_db else now
        start_time = max(now, last_finish_time)
        finish_time = start_time + duration

        if not try_spend_resources_conn(conn, planet_id, int(cost_metal), int(cost_crystal)):
            rollback(conn)
            return False, "resources", {
                "building_type": building_type,
                "current_level": current_level,
                "target_level": target_level,
                "cost_metal": cost_metal,
                "cost_crystal": cost_crystal,
            }

        job_id = add_build_job(planet_id, building_type, start_time, finish_time, conn=conn)

        commit(conn)

        if finished_any:
            invalidate_player_score_cache(user_id)

        payload = {
            "job_id": int(job_id),
            "building_type": building_type,
            "target_level": int(target_level),
            "duration": int(duration),
            "finish_time": float(finish_time),
            "queue_limit": int(queue_limit),
            "max_level": int(max_level),
        }
        return True, "ok", payload

    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def cancel_build_job_for_planet(
    planet_id: int,
    job_id: int,
    user_id: Optional[int] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    planet_id = int(planet_id)
    job_id = int(job_id)
    user_id_int = int(user_id) if user_id is not None else None

    conn = db()
    finished_any = False
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)
        now = time.time()

        owner_id = get_planet_owner_id(planet_id)
        if not owner_id:
            rollback(conn)
            return False, "not_found", {"msg": "Planet owner not found"}

        if user_id_int is not None and int(owner_id) != user_id_int:
            rollback(conn)
            return False, "forbidden", {"msg": "Not your planet"}

        from .queue_engine import finish_due_work

        engine_result = finish_due_work(
            player_id=int(owner_id),
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

        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, building_type
            FROM build_queue
            WHERE id = ? AND planet_id = ?
            LIMIT 1;
            """,
            (job_id, planet_id),
        )
        row = cur.fetchone()
        if not row:
            rollback(conn)
            return False, "not_found", {"msg": "Build job not found", "job_id": job_id}

        delete_build_job(int(row["id"]), conn=conn)
        recalculate_build_queue_finish_times(
            planet_id, int(owner_id), conn=conn, now=now
        )
        commit(conn)

        if finished_any:
            invalidate_player_score_cache(int(owner_id))

        return True, "ok", {
            "job_id": int(row["id"]),
            "building_type": str(row["building_type"]),
            "cancelled": True,
        }

    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


# =============================================================================
# Config Validation
# =============================================================================

def _validate_building_config() -> None:
    for key in BUILDING_ORDER:
        if key not in BASE_COST:
            raise RuntimeError(f"BUILDING_CONFIG: '{key}' fehlt in BASE_COST")
        if key not in COST_FACTOR:
            raise RuntimeError(f"BUILDING_CONFIG: '{key}' fehlt in COST_FACTOR")
        if key not in BUILD_TIME_BASE:
            raise RuntimeError(f"BUILDING_CONFIG: '{key}' fehlt in BUILD_TIME_BASE")
        if key not in BUILD_TIME_FACTOR:
            raise RuntimeError(f"BUILDING_CONFIG: '{key}' fehlt in BUILD_TIME_FACTOR")
        if key not in BUILDING_TAB:
            raise RuntimeError(f"BUILDING_CONFIG: '{key}' fehlt in BUILDING_TAB")
        if key not in BUILDING_REQUIREMENTS:
            raise RuntimeError(f"BUILDING_CONFIG: '{key}' fehlt in BUILDING_REQUIREMENTS")

    for b_type, req in BUILDING_REQUIREMENTS.items():
        for req_b_key in req.get("buildings", {}).keys():
            if req_b_key not in ALL_BUILDINGS:
                raise RuntimeError(f"BUILDING_CONFIG: '{b_type}' verweist auf unbekanntes Gebäude '{req_b_key}'")
        for req_r_key in req.get("research", {}).keys():
            if req_r_key not in RESEARCH_TECHS:
                raise RuntimeError(f"BUILDING_CONFIG: '{b_type}' verweist auf unbekannte Forschung '{req_r_key}'")


_validate_building_config()
