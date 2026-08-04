"""
Gebäude-Logik für Genesis Colonies.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple, Any, Optional

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
#   GC-854 — Shared per-request panel context (SSR / action payloads)
# =============================================================================


@dataclass
class BuildingsPanelContext:
    """One EffectResolver + production snapshot per buildings panel build."""

    user_id: int
    buildings: Dict[str, int]
    research_levels: Dict[str, int]
    ratio: float
    resolver: EffectResolver
    production_per_hour: Dict[str, int]
    _bumped_production: Dict[Tuple[str, int], Dict[str, int]] = field(default_factory=dict)
    _bumped_resolvers: Dict[Tuple[str, int], EffectResolver] = field(default_factory=dict)
    _build_time_cache: Dict[Tuple[str, int], int] = field(default_factory=dict)
    _build_time_at_target_cache: Dict[Tuple[str, int], int] = field(default_factory=dict)

    @classmethod
    def for_planet(
        cls,
        planet: dict,
        buildings: Dict[str, int],
        research_levels: Dict[str, int],
        ratio: float,
        *,
        conn=None,
    ) -> BuildingsPanelContext:
        user_id = int(planet["player_id"])
        resolver = get_effect_resolver(
            user_id,
            buildings=buildings,
            research=research_levels,
            conn=conn,
            planet=planet,
        )
        return cls(
            user_id=user_id,
            buildings=dict(buildings),
            research_levels=dict(research_levels),
            ratio=float(ratio),
            resolver=resolver,
            production_per_hour=resolver.get_building_production_per_hour(float(ratio)),
        )

    @classmethod
    def for_queue_recalc(
        cls,
        user_id: int,
        buildings: Dict[str, int],
        research_levels: Dict[str, int],
        *,
        conn=None,
    ) -> BuildingsPanelContext:
        """GC-862 — one resolver for queue recalc / MAX enqueue loops."""
        resolver = get_effect_resolver(
            int(user_id),
            buildings=buildings,
            research=research_levels,
            conn=conn,
        )
        return cls(
            user_id=int(user_id),
            buildings=dict(buildings),
            research_levels=dict(research_levels),
            ratio=1.0,
            resolver=resolver,
            production_per_hour={},
        )

    def build_time_seconds(self, building_type: str, target_level: int) -> int:
        key = (str(building_type), int(target_level))
        cached = self._build_time_cache.get(key)
        if cached is not None:
            return cached
        val = int(self.resolver.get_build_time_seconds(building_type, int(target_level)))
        self._build_time_cache[key] = val
        return val

    def build_time_seconds_at_target(self, building_type: str, target_level: int) -> int:
        key = (str(building_type), int(target_level))
        cached = self._build_time_at_target_cache.get(key)
        if cached is not None:
            return cached
        val = int(
            self.resolver_at_target(building_type, target_level).get_build_time_seconds(
                building_type, int(target_level)
            )
        )
        self._build_time_at_target_cache[key] = val
        return val

    def max_level(self, building_type: str) -> int:
        return int(self.resolver.get_max_building_level(building_type))

    def resolver_at_target(self, building_type: str, target_level: int) -> EffectResolver:
        key = (str(building_type), int(target_level))
        cached = self._bumped_resolvers.get(key)
        if cached is not None:
            return cached
        bumped = dict(self.buildings)
        bumped[building_type] = int(target_level)
        base = self.resolver
        resolver = EffectResolver(
            bumped,
            self.research_levels,
            settings=base._settings,
            player_id=base.player_id,
            planet_id=base.planet_id,
            planet_position=base.planet_position,
            galaxy_id=base.galaxy_id,
            conn=base._conn,
        )
        self._bumped_resolvers[key] = resolver
        return resolver

    def production_per_hour_at_target(self, building_type: str, target_level: int) -> Dict[str, int]:
        key = (str(building_type), int(target_level))
        cached = self._bumped_production.get(key)
        if cached is not None:
            return cached
        prod = self.resolver_at_target(building_type, target_level).get_building_production_per_hour(
            self.ratio
        )
        self._bumped_production[key] = prod
        return prod


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

# Display-only colony stage slots (percent of stage box).
# Spread per building-tab across the full stage so active-tab views never crowd.
# Not used for economy/queue math. Min ≈18% Euclidean gap between any two slots.
BUILDING_STAGE_LAYOUT: Dict[str, Dict[str, float]] = {
    # Resources — player-tuned 2-3-2 (hex): Crystal Mine top-center,
    # Metal/Solar upper wings, Metal Storage center, Fuel Plant / Crystal Storage
    # lower wings, Fuel Storage bottom-center.
    "crystal_mine": {"left_pct": 49.1, "top_pct": 18.9, "z": 3, "scale": 1.0},
    "metal_mine": {"left_pct": 15.5, "top_pct": 29.0, "z": 3, "scale": 1.0},
    "solar_plant": {"left_pct": 80.3, "top_pct": 28.3, "z": 2, "scale": 1.0},
    "metal_storage": {"left_pct": 49.6, "top_pct": 50.0, "z": 4, "scale": 0.98},
    "fuel_cell_plant": {"left_pct": 15.2, "top_pct": 73.8, "z": 3, "scale": 1.0},
    "crystal_storage": {"left_pct": 79.2, "top_pct": 75.6, "z": 4, "scale": 0.98},
    "fuel_storage": {"left_pct": 49.7, "top_pct": 80.7, "z": 4, "scale": 0.98},
    # Research — wide mid split
    "research_lab": {"left_pct": 26.0, "top_pct": 48.0, "z": 3, "scale": 1.05},
    "academy": {"left_pct": 74.0, "top_pct": 48.0, "z": 3, "scale": 1.02},
    # Military — lower diamond
    "orbital_shipyard": {"left_pct": 18.0, "top_pct": 40.0, "z": 5, "scale": 1.05},
    "radar_array": {"left_pct": 50.0, "top_pct": 34.0, "z": 4, "scale": 0.98},
    "barracks": {"left_pct": 82.0, "top_pct": 40.0, "z": 3, "scale": 1.0},
    "defense_factory": {"left_pct": 50.0, "top_pct": 66.0, "z": 3, "scale": 1.02},
    # Infrastructure — lower hex
    "command_center": {"left_pct": 50.0, "top_pct": 38.0, "z": 6, "scale": 1.08},
    "shield_generator": {"left_pct": 16.0, "top_pct": 52.0, "z": 2, "scale": 0.98},
    "terraformer": {"left_pct": 84.0, "top_pct": 52.0, "z": 2, "scale": 1.0},
    "nanofactory": {"left_pct": 16.0, "top_pct": 74.0, "z": 3, "scale": 1.0},
    "geothermal_nexus": {"left_pct": 84.0, "top_pct": 74.0, "z": 2, "scale": 1.0},
    "planet_core_nexus": {"left_pct": 50.0, "top_pct": 86.0, "z": 1, "scale": 1.05},
}

_BUILDING_ICON_OVERRIDES: Dict[str, str] = {
    "orbital_shipyard": "img/buildings/shipyard.png",
    "fuel_storage": "img/buildings/fuel_cell_storage.png",
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
    "fuel_cell_plant": (108, 72),
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


def get_building_stage_icon(building_type: str) -> str:
    """Prefer stage cutout under img/buildings/stage/; fall back to card icon."""
    key = str(building_type or "").strip()
    if not key:
        return get_building_icon(building_type)
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for ext in (".webp", ".png"):
        candidate = root / "static" / "img" / "buildings" / "stage" / f"{key}{ext}"
        if candidate.is_file() and candidate.stat().st_size > 0:
            return f"img/buildings/stage/{key}{ext}"
    return get_building_icon(building_type)


def get_building_tab(building_type: str) -> str:
    return BUILDING_TAB.get(building_type, "infrastructure")


def _clamp_stage_pct(value: Any, default: float = 50.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float(default)
    if v < 0.0:
        return 0.0
    if v > 100.0:
        return 100.0
    return v


def resolve_stage_layout(planet_id: int, *, conn=None) -> Dict[str, Dict[str, float]]:
    """Merge BUILDING_STAGE_LAYOUT defaults with per-planet DB overrides (display-only)."""
    layout: Dict[str, Dict[str, float]] = {}
    for key, slot in BUILDING_STAGE_LAYOUT.items():
        layout[key] = {
            "left_pct": float(slot.get("left_pct") or 50.0),
            "top_pct": float(slot.get("top_pct") or 50.0),
            "z": float(slot.get("z") or 1),
            "scale": float(slot.get("scale") or 1.0),
        }

    pid = int(planet_id or 0)
    if pid <= 0:
        return layout

    own_conn = conn is None
    if own_conn:
        from .db import db as _db

        conn = _db()
    try:
        try:
            rows = conn.execute(
                "SELECT building_key, left_pct, top_pct FROM planet_building_stage_layout WHERE planet_id = ?",
                (pid,),
            ).fetchall()
        except Exception:
            rows = []
        for row in rows or []:
            key = str(row["building_key"] if hasattr(row, "keys") else row[0] or "").strip()
            if key not in layout:
                continue
            left = row["left_pct"] if hasattr(row, "keys") else row[1]
            top = row["top_pct"] if hasattr(row, "keys") else row[2]
            layout[key]["left_pct"] = _clamp_stage_pct(left, layout[key]["left_pct"])
            layout[key]["top_pct"] = _clamp_stage_pct(top, layout[key]["top_pct"])
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass
    return layout


def save_stage_layout(
    planet_id: int,
    player_id: int,
    positions: Sequence[Dict[str, Any]] | None = None,
    *,
    reset: bool = False,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Persist stage prop positions for a planet. Ownership-checked. Display-only."""
    import time as _time

    from .db import db as _db

    pid = int(planet_id or 0)
    uid = int(player_id or 0)
    if pid <= 0 or uid <= 0:
        return False, "invalid_planet", None

    own_conn = conn is None
    if own_conn:
        conn = _db()
    try:
        planet = conn.execute(
            "SELECT id, player_id FROM planets WHERE id = ?",
            (pid,),
        ).fetchone()
        if not planet:
            return False, "planet_not_found", None
        owner = int(planet["player_id"] if hasattr(planet, "keys") else planet[1] or 0)
        if owner != uid:
            return False, "forbidden", None

        now = float(_time.time())
        if reset:
            conn.execute(
                "DELETE FROM planet_building_stage_layout WHERE planet_id = ?",
                (pid,),
            )
            if own_conn:
                conn.commit()
            return True, "ok", {"reset": True, "layout": resolve_stage_layout(pid, conn=conn)}

        saved = 0
        for item in positions or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("building_key") or item.get("key") or "").strip()
            if key not in BUILDING_STAGE_LAYOUT:
                continue
            left = _clamp_stage_pct(item.get("left_pct"), BUILDING_STAGE_LAYOUT[key]["left_pct"])
            top = _clamp_stage_pct(item.get("top_pct"), BUILDING_STAGE_LAYOUT[key]["top_pct"])
            conn.execute(
                """
                INSERT INTO planet_building_stage_layout (planet_id, building_key, left_pct, top_pct, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(planet_id, building_key) DO UPDATE SET
                    left_pct = excluded.left_pct,
                    top_pct = excluded.top_pct,
                    updated_at = excluded.updated_at
                """,
                (pid, key, left, top, now),
            )
            saved += 1
        if own_conn:
            conn.commit()
        return True, "ok", {"saved": saved, "layout": resolve_stage_layout(pid, conn=conn)}
    finally:
        if own_conn:
            try:
                conn.close()
            except Exception:
                pass


def get_building_label_key(building_type: str) -> str:
    return f"building_{building_type}"


# =============================================================================
# Costs & Time
# =============================================================================

def get_upgrade_cost(building_type: str, current_level: int) -> Tuple[int, int]:
    from .economy_balance import power_upgrade_cost

    target_level = max(int(current_level) + 1, 1)
    return power_upgrade_cost(building_type, target_level)


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
        from .economy_balance import power_build_seconds

        return power_build_seconds(building_type, int(target_level))

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
    hotpath = BuildingsPanelContext.for_queue_recalc(uid, buildings, research_levels, conn=conn)
    cur = conn.cursor()
    schedule_at = ts
    queued_counts: Dict[str, int] = {}
    from .queue_poll import due_cutoff_ts

    finish_cutoff = due_cutoff_ts(ts)

    for idx, row in enumerate(rows):
        btype = str(row["building_type"])
        current = int(buildings.get(btype, 0) or 0)
        queued_same = int(queued_counts.get(btype, 0))
        target_level = current + queued_same + 1
        duration = hotpath.build_time_seconds(btype, target_level)

        if idx == 0:
            start_existing = float(row["start_time"] or 0)
            finish_existing = float(row["finish_time"] or 0)
            # Due / display-zero head: never revive to a full duration; leave for finish.
            if finish_existing <= finish_cutoff:
                queued_counts[btype] = queued_same + 1
                schedule_at = ts
                continue
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


def get_building_resource_items(
    cost_metal: int,
    cost_crystal: int,
    planet_metal: float,
    planet_crystal: float,
) -> List[Dict[str, Any]]:
    return [
        {
            "kind": "resource",
            "key": "metal",
            "need": int(cost_metal),
            "have": int(planet_metal),
            "met": planet_metal >= float(cost_metal),
        },
        {
            "kind": "resource",
            "key": "crystal",
            "need": int(cost_crystal),
            "have": int(planet_crystal),
            "met": planet_crystal >= float(cost_crystal),
        },
    ]


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


# Command Center UI display for nanofactory-only build bonus (gameplay uses EffectResolver).
COMMAND_CENTER_NANOFACTORY_BUILD_BONUS_PER_LEVEL = 15  # GC-863 — UI display only


def command_center_nanofactory_build_bonus_pct(level: int) -> int:
    """Flat UI modifier for Command Center cards/technical data (level × 15 %)."""
    return int(COMMAND_CENTER_NANOFACTORY_BUILD_BONUS_PER_LEVEL * max(0, int(level or 0)))


def nanofactory_build_bonus_pct(level: int) -> int:
    """Nanofactory build-speed bonus % — matches EffectResolver diminishing-returns curve."""
    from .effects import EffectResolver

    return EffectResolver.nanofactory_build_speed_bonus_pct(level)


def _command_center_panel_snapshot(
    buildings: Dict[str, int],
    target_level: int,
) -> Dict[str, Any]:
    cc_cur = int(buildings.get("command_center", 0) or 0)
    cc_nxt = int(target_level)
    return _panel_effect_snapshot(
        effect_kind="bonus_percent",
        effect_current=command_center_nanofactory_build_bonus_pct(cc_cur),
        effect_next=command_center_nanofactory_build_bonus_pct(cc_nxt),
        effect_resource="build",
        effect_unit="%",
    )


def _command_center_effect_payload(level: int) -> Dict[str, Any]:
    pct = command_center_nanofactory_build_bonus_pct(level)
    return {
        "effect_kind": "bonus_percent",
        "effect_value": pct,
        "effect_unit": "%",
        "effect_resource": "build",
    }


def _nanofactory_panel_snapshot(
    buildings: Dict[str, int],
    target_level: int,
    *,
    research_levels: Optional[Dict[str, int]] = None,
    panel_ctx: Optional[BuildingsPanelContext] = None,
) -> Dict[str, Any]:
    from .technical_data import build_nanofactory_time_preview

    cur = int(buildings.get("nanofactory", 0) or 0)
    nxt = int(target_level)
    out = _panel_effect_snapshot(
        effect_kind="bonus_percent",
        effect_current=nanofactory_build_bonus_pct(cur),
        effect_next=nanofactory_build_bonus_pct(nxt),
        effect_resource="build",
        effect_unit="%",
    )
    base = panel_ctx.resolver if panel_ctx is not None else None
    preview = build_nanofactory_time_preview(
        buildings,
        research_levels or (panel_ctx.research_levels if panel_ctx is not None else {}),
        nano_level=cur,
        base_resolver=base,
    )
    out["nano_time_preview"] = preview
    out["build_time_factor"] = preview.get("speed_current")
    return out


def _nanofactory_effect_payload(
    level: int,
    *,
    buildings: Optional[Dict[str, int]] = None,
    research_levels: Optional[Dict[str, int]] = None,
    panel_ctx: Optional[BuildingsPanelContext] = None,
) -> Dict[str, Any]:
    from .technical_data import build_nanofactory_time_preview

    pct = nanofactory_build_bonus_pct(level)
    out: Dict[str, Any] = {
        "effect_kind": "bonus_percent",
        "effect_value": pct,
        "effect_unit": "%",
        "effect_resource": "build",
    }
    bld = dict(buildings or {})
    bld["nanofactory"] = int(level)
    base = panel_ctx.resolver if panel_ctx is not None else None
    preview = build_nanofactory_time_preview(
        bld,
        research_levels or (panel_ctx.research_levels if panel_ctx is not None else {}),
        nano_level=int(level),
        base_resolver=base,
    )
    out["nano_time_preview"] = preview
    out["build_time_factor"] = preview.get("speed_current")
    return out


def _panel_effect_snapshot(
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
    out: Dict[str, Any] = {
        "effect_kind": effect_kind,
        "effect_current": cur,
        "effect_next": nxt,
        "effect_delta": delta,
        "effect_resource": effect_resource,
        "effect_unit": effect_unit,
    }
    if effect_metric_key:
        out["effect_metric_key"] = str(effect_metric_key)
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


def _panel_energy_draw_delta(effects: Dict[str, Any]) -> Optional[int]:
    """Additional energy draw shown on upgrade cards (next level minus current)."""
    sec = effects.get("secondary_effect")
    if isinstance(sec, dict) and sec.get("effect_kind") == "energy_use":
        delta = int(sec.get("effect_delta") or 0)
        return delta if delta > 0 else None
    if effects.get("effect_kind") == "energy_use":
        delta = int(effects.get("effect_delta") or 0)
        return delta if delta > 0 else None
    return None


def _panel_upgrade_effect_fields(
    building_type: str,
    buildings: Dict[str, int],
    target_level: int,
    ratio: float,
    research_levels: Dict[str, int],
    *,
    panel_ctx: Optional[BuildingsPanelContext] = None,
) -> Dict[str, Any]:
    """Authoritative upgrade preview per building (EffectResolver / production helpers)."""
    if panel_ctx is not None:
        r_now = panel_ctx.resolver
        r_next = panel_ctx.resolver_at_target(building_type, target_level)
    else:
        from .logic import get_building_production_per_hour

        r_now = EffectResolver(buildings, research_levels or {})
        bumped = dict(buildings)
        bumped[building_type] = int(target_level)
        r_next = EffectResolver(bumped, research_levels or {})

    if building_type in BUILDING_PRODUCTION_RESOURCE:
        if panel_ctx is not None:
            prod_now = panel_ctx.production_per_hour
            prod_next = panel_ctx.production_per_hour_at_target(building_type, target_level)
        else:
            from .logic import get_building_production_per_hour

            prod_now = get_building_production_per_hour(
                buildings, ratio, research=research_levels
            )
            bumped = dict(buildings)
            bumped[building_type] = int(target_level)
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
        return _nanofactory_panel_snapshot(
            buildings,
            target_level,
            research_levels=research_levels,
            panel_ctx=panel_ctx,
        )

    if building_type == "command_center":
        return _command_center_panel_snapshot(buildings, target_level)

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
        cur_prod = r_now.get_max_building_level("metal_mine")
        nxt_prod = r_next.get_max_building_level("metal_mine")
        cur_store = r_now.get_max_building_level("metal_storage")
        nxt_store = r_next.get_max_building_level("metal_storage")
        out = _panel_effect_snapshot(
            effect_kind="max_level",
            effect_current=cur_prod,
            effect_next=nxt_prod,
            effect_resource="",
            effect_unit="",
            effect_metric_key="buildings_effect_nexus_max_production",
        )
        out["secondary_effect"] = _panel_effect_snapshot(
            effect_kind="max_level",
            effect_current=cur_store,
            effect_next=nxt_store,
            effect_resource="",
            effect_unit="",
            effect_metric_key="buildings_effect_nexus_max_storage",
        )
        return out

    if building_type == "planet_core_nexus":
        cur_max = r_now.get_max_building_level("metal_mine")
        nxt_max = r_next.get_max_building_level("metal_mine")
        return _panel_effect_snapshot(
            effect_kind="max_level",
            effect_current=cur_max,
            effect_next=nxt_max,
            effect_resource="",
            effect_unit="",
            effect_metric_key="buildings_effect_nexus_core_max_production",
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

    if building_type == "barracks":
        bar_cur = int(buildings.get("barracks", 0) or 0)
        bar_nxt = int(target_level)
        return _panel_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=int(2 * bar_cur),
            effect_next=int(2 * bar_nxt),
            effect_resource="shipyard",
            effect_unit="%",
            effect_metric_key="buildings_effect_barracks_shipyard",
        )

    if building_type == "shield_generator":
        sg_cur = int(buildings.get("shield_generator", 0) or 0)
        sg_nxt = int(target_level)
        return _panel_effect_snapshot(
            effect_kind="bonus_percent",
            effect_current=int(2 * sg_cur),
            effect_next=int(2 * sg_nxt),
            effect_resource="shield",
            effect_unit="%",
            effect_metric_key="buildings_effect_shield_generator",
        )

    if building_type == "orbital_shipyard":
        from .shipyard import BUILD_TIME_LEVEL_FACTOR, orbital_production_batch_capacity

        cur_lvl = int(buildings.get("orbital_shipyard", 0) or 0)
        nxt_lvl = int(target_level)
        cur_cap = orbital_production_batch_capacity(max(1, cur_lvl)) if cur_lvl > 0 else 0
        nxt_cap = orbital_production_batch_capacity(max(1, nxt_lvl))
        cur_red = (
            int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (max(1, cur_lvl) - 1)) * 100))
            if cur_lvl > 1
            else 0
        )
        nxt_red = (
            int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (max(1, nxt_lvl) - 1)) * 100))
            if nxt_lvl > 1
            else 0
        )
        return {
            "effect_kind": "yard_capacity",
            "effect_current": cur_cap,
            "effect_next": nxt_cap,
            "effect_delta": max(0, nxt_cap - cur_cap),
            "effect_resource": "",
            "effect_unit": "",
            "build_time_reduction_percent": nxt_red,
            "build_time_reduction_delta": max(0, nxt_red - cur_red),
        }

    lvl_cur = int(buildings.get(building_type, 0) or 0)
    lvl_nxt = int(target_level)
    return _panel_effect_snapshot(
        effect_kind="level",
        effect_current=lvl_cur,
        effect_next=lvl_nxt,
        effect_resource="",
        effect_unit="",
    )


# =============================================================================
# Technical data sheet (GC-557F)
# =============================================================================

def _technical_effects_at_level(
    building_type: str,
    buildings: Dict[str, int],
    level: int,
    ratio: float,
    research_levels: Dict[str, int],
    *,
    panel_ctx: Optional[BuildingsPanelContext] = None,
) -> Dict[str, Any]:
    """Authoritative per-level stats for the technical-data modal."""
    if panel_ctx is not None:
        r = panel_ctx.resolver_at_target(building_type, int(level))
        bumped = dict(panel_ctx.buildings)
        bumped[building_type] = int(level)
    else:
        bumped = dict(buildings)
        bumped[building_type] = int(level)
        r = EffectResolver(bumped, research_levels or {})

    out: Dict[str, Any] = {
        "effect_kind": "level",
        "effect_label_key": "buildings_col_level",
        "effect_value": int(level),
        "effect_unit": "",
        "effect_resource": "",
        "production_metal_per_hour": None,
        "production_crystal_per_hour": None,
        "production_fuel_cells_per_hour": None,
        "energy_total": None,
        "energy_use": None,
        "storage_metal": None,
        "storage_crystal": None,
        "storage_fuel_cells": None,
    }

    if building_type in BUILDING_PRODUCTION_RESOURCE:
        if panel_ctx is not None:
            prod = panel_ctx.production_per_hour_at_target(building_type, int(level))
        else:
            from .logic import get_building_production_per_hour

            prod = get_building_production_per_hour(bumped, ratio, research=research_levels)
        val = int(prod.get(building_type, 0) or 0)
        res = BUILDING_PRODUCTION_RESOURCE[building_type]
        out["effect_kind"] = "production"
        out["effect_value"] = val
        out["effect_unit"] = "/h"
        out["effect_resource"] = res
        if int(level) >= 1:
            prev_lvl = max(0, int(level) - 1)
            if panel_ctx is not None:
                prod_prev = panel_ctx.production_per_hour_at_target(building_type, prev_lvl)
                prod_cur = prod
            else:
                from .logic import get_building_production_per_hour

                bumped_prev = dict(bumped)
                bumped_prev[building_type] = prev_lvl
                prod_prev = get_building_production_per_hour(
                    bumped_prev, ratio, research=research_levels
                )
            delta = max(
                0,
                int(prod.get(building_type, 0) or 0)
                - int(prod_prev.get(building_type, 0) or 0),
            )
            out["production_delta_per_hour"] = int(delta)
            if building_type in ("metal_mine", "crystal_mine", "fuel_cell_plant"):
                from .economy_balance import upgrade_roi_hours

                cost_m, cost_c = get_upgrade_cost(building_type, int(level) - 1)
                roi = upgrade_roi_hours(
                    metal_cost=int(cost_m),
                    crystal_cost=int(cost_c),
                    delta_per_hour=float(delta),
                )
                out["upgrade_roi_hours"] = round(roi, 1) if math.isfinite(roi) else None
        if res == "metal":
            out["production_metal_per_hour"] = val
        elif res == "crystal":
            out["production_crystal_per_hour"] = val
        elif res == "fuel_cells":
            out["production_fuel_cells_per_hour"] = val
        if building_type in BUILDING_ENERGY_CONSUMERS:
            out["energy_use"] = int(r.building_energy_draw(building_type, level=int(level)))
        return out

    if building_type == "solar_plant":
        et, _ = r.compute_energy()
        out["effect_kind"] = "energy"
        out["effect_value"] = int(et)
        out["effect_resource"] = "energy"
        out["energy_total"] = int(et)
        return out

    caps = r.get_storage_capacity()
    if building_type == "metal_storage":
        val = int(caps.get("metal", 0) or 0)
        out.update(
            effect_kind="storage",
            effect_value=val,
            effect_resource="metal",
            storage_metal=val,
        )
        return out
    if building_type == "crystal_storage":
        val = int(caps.get("crystal", 0) or 0)
        out.update(
            effect_kind="storage",
            effect_value=val,
            effect_resource="crystal",
            storage_crystal=val,
        )
        return out
    if building_type == "fuel_storage":
        val = int(caps.get("fuel_cells", 0) or 0)
        out.update(
            effect_kind="storage",
            effect_value=val,
            effect_resource="fuel_cells",
            storage_fuel_cells=val,
        )
        return out

    if building_type == "research_lab":
        pct = int(round((r.research_lab_bonus() - 1.0) * 100))
        out.update(effect_kind="bonus_percent", effect_value=pct, effect_unit="%", effect_resource="research")
        return out

    if building_type == "academy":
        pct = int(round(max(0, int(level)) * 5))
        out.update(effect_kind="bonus_percent", effect_value=pct, effect_unit="%", effect_resource="research")
        return out

    if building_type == "nanofactory":
        out.update(
            _nanofactory_effect_payload(
                int(level),
                buildings=buildings,
                research_levels=research_levels,
                panel_ctx=panel_ctx,
            )
        )
        return out

    if building_type == "command_center":
        out.update(_command_center_effect_payload(int(level)))
        return out

    if building_type == "terraformer":
        pct = int(5 * int(level))
        out.update(effect_kind="bonus_percent", effect_value=pct, effect_unit="%", effect_resource="storage")
        return out

    if building_type == "geothermal_nexus":
        prod_max = int(r.get_max_building_level("metal_mine"))
        store_max = int(r.get_max_building_level("metal_storage"))
        out.update(
            effect_kind="max_level",
            effect_value=prod_max,
            effect_resource="",
            effect_metric_key="buildings_effect_nexus_max_production",
        )
        out["secondary_effect"] = {
            "effect_kind": "max_level",
            "effect_value": store_max,
            "effect_delta": store_max,
            "effect_resource": "",
            "effect_metric_key": "buildings_effect_nexus_max_storage",
        }
        return out

    if building_type == "planet_core_nexus":
        val = int(r.get_max_building_level("metal_mine"))
        out.update(
            effect_kind="max_level",
            effect_value=val,
            effect_resource="",
            effect_metric_key="buildings_effect_nexus_core_max_production",
        )
        return out

    if building_type == "radar_array":
        out.update(effect_kind="scan", effect_value=int(2 * int(level)), effect_resource="")
        return out

    if building_type == "barracks":
        pct = int(2 * int(level))
        out.update(
            effect_kind="bonus_percent",
            effect_value=pct,
            effect_unit="%",
            effect_resource="shipyard",
            effect_metric_key="buildings_effect_barracks_shipyard",
        )
        return out

    if building_type == "shield_generator":
        pct = int(2 * int(level))
        out.update(
            effect_kind="bonus_percent",
            effect_value=pct,
            effect_unit="%",
            effect_resource="shield",
            effect_metric_key="buildings_effect_shield_generator",
        )
        return out

    if building_type in BUILDING_ENERGY_CONSUMERS:
        out["energy_use"] = int(r.building_energy_draw(building_type, level=int(level)))
        out["effect_kind"] = "energy_use"
        out["effect_value"] = out["energy_use"]
        out["effect_resource"] = "energy"
        return out

    if building_type == "orbital_shipyard":
        from .shipyard import (
            PRODUCTION_TECH_EXAMPLE_BASE_SECONDS,
            orbital_production_batch_capacity,
            unit_batch_capacity,
            BUILD_TIME_LEVEL_FACTOR,
        )

        lvl = max(1, int(level))
        yard_cap = orbital_production_batch_capacity(lvl)
        reduction = (
            int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)) * 100)) if lvl > 1 else 0
        )
        examples = {
            tag: unit_batch_capacity(lvl, sec)
            for tag, sec in PRODUCTION_TECH_EXAMPLE_BASE_SECONDS.items()
        }
        out.update(
            effect_kind="yard_production",
            effect_value=yard_cap,
            yard_batch_capacity=yard_cap,
            build_time_reduction_percent=reduction,
            parallel_light=examples.get("light"),
            parallel_medium=examples.get("medium"),
            parallel_heavy=examples.get("heavy"),
        )
        return out

    if building_type == "defense_factory":
        from .shipyard import orbital_production_batch_capacity, shipyard_level_from_buildings

        sy_lvl = shipyard_level_from_buildings(buildings)
        out.update(
            effect_kind="defense_unlock",
            effect_value=int(level),
        )
        if sy_lvl > 0 and int(buildings.get("orbital_shipyard") or buildings.get("shipyard") or 0) > 0:
            yard_cap = orbital_production_batch_capacity(sy_lvl)
            out["secondary_effect"] = {
                "effect_kind": "yard_reference",
                "effect_value": yard_cap,
                "yard_level": sy_lvl,
            }
        return out

    return out


def _technical_level_row(
    building_type: str,
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
    level: int,
    *,
    user_id: int,
    conn,
    ratio: float,
    is_current: bool,
    panel_ctx: Optional[BuildingsPanelContext] = None,
) -> Dict[str, Any]:
    upgrade_from = max(int(level) - 1, 0)
    cost_m, cost_c = get_upgrade_cost(building_type, upgrade_from)
    if panel_ctx is not None:
        time_s = panel_ctx.build_time_seconds_at_target(building_type, int(level))
    else:
        bumped = dict(buildings)
        bumped[building_type] = int(level)
        time_s = int(
            get_build_time(
                building_type,
                int(level),
                user_id=int(user_id),
                conn=conn,
                buildings=bumped,
                research_levels=research_levels,
            )
        )
    row: Dict[str, Any] = {
        "level": int(level),
        "is_current": bool(is_current),
        "cost_metal": int(cost_m),
        "cost_crystal": int(cost_c),
        "time_seconds": time_s,
    }
    row.update(
        _technical_effects_at_level(
            building_type, buildings, level, ratio, research_levels, panel_ctx=panel_ctx
        )
    )
    from .technical_data import enrich_building_technical_row

    enrich_building_technical_row(row, building_type, buildings, research_levels, ratio, level, panel_ctx=panel_ctx)
    return row


def build_building_technical_data(
    building_type: str,
    *,
    user_id: int,
    conn,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    from .planet_evolution.repository import get_context_planet

    btype = str(building_type or "").strip()
    if btype not in BUILDING_ORDER:
        return None, "unknown_building"

    uid = int(user_id)
    planet = get_context_planet(uid, conn=conn)
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id, conn=conn)
    research_levels = get_research_levels(user_id=uid, conn=conn)
    ratio = _panel_energy_ratio(buildings, research_levels)
    current = int(buildings.get(btype, 0) or 0)
    panel_ctx = BuildingsPanelContext.for_planet(planet, buildings, research_levels, ratio, conn=conn)
    max_level = panel_ctx.max_level(btype)
    from .technical_data import (
        build_building_technical_summary,
        build_production_milestones,
        resolve_technical_table_layout,
        technical_preview_levels,
        technical_row_role,
    )

    preview = technical_preview_levels(current, max_level)
    levels: List[Dict[str, Any]] = []
    for lvl in preview:
        row = _technical_level_row(
            btype,
            buildings,
            research_levels,
            lvl,
            user_id=uid,
            conn=conn,
            ratio=ratio,
            is_current=(lvl == current),
            panel_ctx=panel_ctx,
        )
        row["row_role"] = technical_row_role(lvl, current, max_level=max_level)
        levels.append(row)

    next_row = next((r for r in levels if int(r.get("level") or 0) == current + 1), None)
    current_row = next((r for r in levels if r.get("is_current")), None)
    summary = build_building_technical_summary(
        building_type=btype,
        buildings=buildings,
        research_levels=research_levels,
        ratio=ratio,
        current=current,
        max_level=max_level,
        current_row=current_row,
        next_row=next_row,
        panel_ctx=panel_ctx,
    )

    return {
        "building_type": btype,
        "label_key": get_building_label_key(btype),
        "description_key": f"desc_{btype}",
        "kind": "building",
        "current_level": current,
        "max_level": max_level,
        "table_layout": resolve_technical_table_layout(levels),
        "summary": summary,
        "milestones": build_production_milestones(
            building_type=btype,
            buildings=buildings,
            research_levels=research_levels,
            ratio=ratio,
            current=current,
            max_level=max_level,
        ),
        "levels": levels,
        "bulk_upgrade": _mine_bulk_upgrade_meta(
            btype,
            current,
            max_level,
            planet,
        ),
    }, None


def _mine_bulk_upgrade_meta(
    building_type: str,
    current_level: int,
    max_level: int,
    planet: dict,
) -> Optional[Dict[str, Any]]:
    if building_type not in ("metal_mine", "crystal_mine", "fuel_cell_plant"):
        return None
    from .economy_balance import mine_bulk_upgrade_preview

    return mine_bulk_upgrade_preview(
        building_type,
        int(current_level),
        int(max_level),
        metal_available=float(planet.get("metal", 0) or 0),
        crystal_available=float(planet.get("crystal", 0) or 0),
    )


def _make_panel_row(
    planet: dict,
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
    building_type: str,
    queue_count: int = 0,
    ratio: float = 1.0,
    queue_free_slots: int = 0,
    *,
    panel_ctx: Optional[BuildingsPanelContext] = None,
    stage_layout: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, Any]:
    from .live_state import current_ssr_perf

    ssr = current_ssr_perf()
    tech_t0 = time.perf_counter() if ssr is not None else 0.0

    level = int(buildings.get(building_type, 0) or 0)
    if panel_ctx is not None:
        max_level = panel_ctx.max_level(building_type)
    else:
        max_level = get_max_level_for_building(building_type, buildings)
    queued_same = int(queue_count or 0)
    at_queue_max = (level + queued_same) >= max_level
    target_level = min(level + queued_same + 1, max_level)

    cost_metal, cost_crystal = get_upgrade_cost(building_type, level + queued_same)
    if panel_ctx is not None:
        time_seconds = panel_ctx.build_time_seconds(building_type, target_level)
    else:
        time_seconds = get_build_time(
            building_type,
            target_level,
            user_id=planet.get("player_id"),
            buildings=buildings,
            research_levels=research_levels,
        )

    req_met = has_building_requirements(buildings, research_levels, building_type)
    planet_metal = float(planet.get("metal", 0) or 0)
    planet_crystal = float(planet.get("crystal", 0) or 0)
    can_afford = planet_metal >= cost_metal and planet_crystal >= cost_crystal
    max_queue_preview: Dict[str, Any] = {"jobs": 0}
    if req_met and not at_queue_max and can_afford and int(queue_free_slots) > 0:
        max_queue_preview = summarize_max_queueable_build_jobs(
            building_type,
            current_level=level,
            queued_same=queued_same,
            max_level=max_level,
            metal=planet_metal,
            crystal=planet_crystal,
            queue_free_slots=int(queue_free_slots),
            user_id=planet.get("player_id"),
            buildings=buildings,
            research_levels=research_levels,
            panel_ctx=panel_ctx,
        )

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
        "resource_items": get_building_resource_items(
            cost_metal, cost_crystal, planet_metal, planet_crystal
        ),
        "can_afford": bool(can_afford),
        "max_queueable": int(max_queue_preview.get("jobs") or 0),
        "max_queue_preview": max_queue_preview,
    }
    stage = None
    if stage_layout and building_type in stage_layout:
        stage = stage_layout.get(building_type)
    if stage is None:
        stage = BUILDING_STAGE_LAYOUT.get(building_type)
    if stage:
        row["stage_left_pct"] = float(stage.get("left_pct") or 50.0)
        row["stage_top_pct"] = float(stage.get("top_pct") or 50.0)
        row["stage_z"] = int(stage.get("z") or 1)
        row["stage_scale"] = float(stage.get("scale") or 1.0)
        row["stage_icon"] = get_building_stage_icon(building_type)
    row.update(
        _panel_upgrade_effect_fields(
            building_type, buildings, target_level, ratio, research_levels, panel_ctx=panel_ctx
        )
    )
    # GC-TECHCARD-UX-001E — compact cards prefer concrete impact.next.delta
    try:
        from .technical_data import resolve_building_impact

        kind = str(row.get("effect_kind") or "")
        display_for_impact: Dict[str, Any] = {"layout": kind}
        if kind == "production":
            display_for_impact = {
                "layout": "production",
                "current_per_hour": int(row.get("effect_current") or 0),
                "next_per_hour": int(row.get("effect_next") or 0),
            }
        elif kind == "storage":
            display_for_impact = {
                "layout": "storage",
                "current": int(row.get("effect_current") or 0),
                "next": int(row.get("effect_next") or 0),
            }
        elif kind == "energy":
            display_for_impact = {
                "layout": "energy",
                "current": int(row.get("effect_current") or 0),
                "next": int(row.get("effect_next") or 0),
            }
        elif kind == "yard_capacity":
            display_for_impact = {
                "layout": "yard",
                "batch_capacity_current": int(row.get("effect_current") or 0),
                "batch_capacity": int(row.get("effect_next") or 0),
                "capacity_at_level": int(row.get("effect_next") or 0),
            }
        elif building_type == "nanofactory":
            display_for_impact = {
                "layout": "nanofactory_build_time",
                "nano_time_preview": row.get("nano_time_preview") or {},
            }
        impact = resolve_building_impact(
            building_type=building_type,
            buildings=buildings,
            research_levels=research_levels,
            current=level,
            display=display_for_impact,
            panel_ctx=panel_ctx,
        )
        if impact:
            row["impact"] = impact
    except Exception:
        pass
    energy_draw = _panel_energy_draw_delta(row)
    if energy_draw is not None:
        row["energy_draw"] = energy_draw
    if building_type in ("metal_mine", "crystal_mine", "fuel_cell_plant") and target_level >= 1:
        from .economy_balance import upgrade_roi_hours

        delta = float(row.get("effect_delta") or 0)
        roi = upgrade_roi_hours(
            metal_cost=int(row.get("cost_metal") or 0),
            crystal_cost=int(row.get("cost_crystal") or 0),
            fuel_cells_cost=int(row.get("cost_fuel_cells") or 0),
            delta_per_hour=delta,
        )
        row["upgrade_roi_hours"] = round(roi, 1) if math.isfinite(roi) else None
    if ssr is not None:
        ssr.add_tech_data_ms((time.perf_counter() - tech_t0) * 1000.0)
    return row


def get_buildings_panel_rows(
    planet: dict,
    buildings: Dict[str, int],
    build_queue: Optional[Dict[str, Any]] = None,
    *,
    active_tab: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    from .live_state import current_ssr_perf

    ssr = current_ssr_perf()
    panel_t0 = time.perf_counter() if ssr is not None else 0.0
    cards_t0: float | None = None

    user_id = planet.get("player_id")
    if user_id is None:
        raise RuntimeError("get_buildings_panel_rows: planet hat kein 'player_id'-Feld")

    research_levels = get_research_levels(user_id=int(user_id))
    ratio = _panel_energy_ratio(buildings, research_levels)
    panel_ctx = BuildingsPanelContext.for_planet(planet, buildings, research_levels, ratio)

    queue_counts: Dict[str, int] = {}
    if build_queue and isinstance(build_queue.get("queue"), list):
        for job in build_queue["queue"]:
            bt = str(job.get("building_type") or "")
            if bt:
                queue_counts[bt] = queue_counts.get(bt, 0) + 1

    bq_summary = (build_queue or {}).get("summary") or {}
    try:
        bq_count = int(bq_summary.get("count") or 0)
    except (TypeError, ValueError):
        bq_count = len(build_queue.get("queue") or []) if build_queue else 0
    try:
        bq_limit = int(bq_summary.get("limit") or 0)
    except (TypeError, ValueError):
        bq_limit = 0
    if bq_limit <= 0:
        bq_limit = _resolve_build_queue_limit()
    queue_free_slots = max(0, bq_limit - bq_count)

    tab_filter = str(active_tab or "").strip() or None
    if tab_filter:
        rows_by_tab: Dict[str, List[Dict[str, Any]]] = {tab_filter: []}
        building_keys = [k for k in BUILDING_ORDER if BUILDING_TAB.get(k) == tab_filter]
    else:
        rows_by_tab = {
            "resources": [],
            "research": [],
            "military": [],
            "infrastructure": [],
        }
        building_keys = BUILDING_ORDER

    try:
        planet_id = int(planet.get("id") or 0)
    except (TypeError, ValueError):
        planet_id = 0
    stage_layout = resolve_stage_layout(planet_id) if planet_id > 0 else None

    for key in building_keys:
        if ssr is not None and cards_t0 is None:
            cards_t0 = time.perf_counter()
        row = _make_panel_row(
            planet,
            buildings,
            research_levels,
            key,
            queue_count=queue_counts.get(key, 0),
            ratio=ratio,
            queue_free_slots=queue_free_slots,
            panel_ctx=panel_ctx,
            stage_layout=stage_layout,
        )
        rows_by_tab.setdefault(row["tab"], []).append(row)

    _attach_queue_jobs_to_panel_rows(rows_by_tab, build_queue)

    if ssr is not None:
        if cards_t0 is not None:
            ssr.add_cards_ms((time.perf_counter() - cards_t0) * 1000.0)
        ssr.add_buildings_panel_ms((time.perf_counter() - panel_t0) * 1000.0)

    return rows_by_tab


def get_buildings_panel_delta(
    planet: dict,
    buildings: Dict[str, int],
    build_queue: Optional[Dict[str, Any]] = None,
    building_keys: Sequence[str] = (),
) -> Dict[str, List[Dict[str, Any]]]:
    """GC-840: partial panel rows for mutation action responses (affected cards only)."""
    keys = [str(k).strip() for k in building_keys if str(k).strip() in BUILDING_ORDER]
    if not keys:
        return {}

    user_id = planet.get("player_id")
    if user_id is None:
        raise RuntimeError("get_buildings_panel_delta: planet hat kein 'player_id'-Feld")

    research_levels = get_research_levels(user_id=int(user_id))
    ratio = _panel_energy_ratio(buildings, research_levels)
    panel_ctx = BuildingsPanelContext.for_planet(planet, buildings, research_levels, ratio)

    queue_counts: Dict[str, int] = {}
    if build_queue and isinstance(build_queue.get("queue"), list):
        for job in build_queue["queue"]:
            bt = str(job.get("building_type") or "")
            if bt:
                queue_counts[bt] = queue_counts.get(bt, 0) + 1

    bq_summary = (build_queue or {}).get("summary") or {}
    try:
        bq_count = int(bq_summary.get("count") or 0)
    except (TypeError, ValueError):
        bq_count = len(build_queue.get("queue") or []) if build_queue else 0
    try:
        bq_limit = int(bq_summary.get("limit") or 0)
    except (TypeError, ValueError):
        bq_limit = 0
    if bq_limit <= 0:
        bq_limit = _resolve_build_queue_limit()
    queue_free_slots = max(0, bq_limit - bq_count)

    try:
        planet_id = int(planet.get("id") or 0)
    except (TypeError, ValueError):
        planet_id = 0
    stage_layout = resolve_stage_layout(planet_id) if planet_id > 0 else None

    rows_by_tab: Dict[str, List[Dict[str, Any]]] = {}
    for key in keys:
        row = _make_panel_row(
            planet,
            buildings,
            research_levels,
            key,
            queue_count=queue_counts.get(key, 0),
            ratio=ratio,
            queue_free_slots=queue_free_slots,
            panel_ctx=panel_ctx,
            stage_layout=stage_layout,
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
    panel_ctx = BuildingsPanelContext.for_planet(planet, buildings, research_levels, ratio)

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
            panel_ctx=panel_ctx,
        )
        rows.append(row)
    return rows


# =============================================================================
# Build Queue
# =============================================================================

def preview_max_queueable_build_jobs(
    building_type: str,
    *,
    current_level: int,
    queued_same: int,
    max_level: int,
    metal: float,
    crystal: float,
    queue_free_slots: int,
) -> int:
    """How many +1 build jobs can be queued (resources, cap, queue slots)."""
    if building_type not in BASE_COST or int(queue_free_slots) <= 0:
        return 0
    count = 0
    m = float(metal or 0)
    c = float(crystal or 0)
    while count < int(queue_free_slots):
        eff = int(current_level) + int(queued_same) + count
        target = eff + 1
        if target > int(max_level):
            break
        cost_m, cost_c = get_upgrade_cost(building_type, eff)
        if m < float(cost_m) or c < float(cost_c):
            break
        m -= float(cost_m)
        c -= float(cost_c)
        count += 1
    return count


def summarize_max_queueable_build_jobs(
    building_type: str,
    *,
    current_level: int,
    queued_same: int,
    max_level: int,
    metal: float,
    crystal: float,
    queue_free_slots: int,
    user_id: Optional[int] = None,
    buildings: Optional[Dict[str, int]] = None,
    research_levels: Optional[Dict[str, int]] = None,
    panel_ctx: Optional[BuildingsPanelContext] = None,
) -> Dict[str, Any]:
    """Preview payload for MAX queue UX: levels, total cost, cumulative build time."""
    jobs = preview_max_queueable_build_jobs(
        building_type,
        current_level=current_level,
        queued_same=queued_same,
        max_level=max_level,
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
        eff = from_level + i
        cost_m, cost_c = get_upgrade_cost(building_type, eff)
        total_m += float(cost_m)
        total_c += float(cost_c)
        target = eff + 1
        if panel_ctx is not None:
            total_sec += panel_ctx.build_time_seconds(building_type, target)
        else:
            total_sec += int(
                get_build_time(
                    building_type,
                    target,
                    user_id=user_id,
                    buildings=buildings,
                    research_levels=research_levels,
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


def planet_ids_with_build_queue(
    planet_ids: Sequence[int],
    conn=None,
    *,
    now: Optional[float] = None,
) -> set[int]:
    """
    GC-PLANET-UI-001: DISTINCT planet_ids with at least one non-due build_queue row.

    Read-only — no finish/side effects. Callers that need accurate due cleanup
    should run finish_due_work on the normal game-state / action path first.
    """
    ids = [int(pid) for pid in planet_ids if pid is not None]
    if not ids:
        return set()

    own = False
    if conn is None:
        conn = db()
        own = True

    try:
        ts = float(time.time() if now is None else now)
        placeholders = ",".join("?" for _ in ids)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT DISTINCT planet_id
            FROM build_queue
            WHERE planet_id IN ({placeholders})
              AND finish_time > ?;
            """,
            (*ids, ts),
        )
        return {int(r["planet_id"]) for r in cur.fetchall()}
    finally:
        if own and conn is not None:
            conn.close()


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
                "remaining_seconds": int(remaining),
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

        # GC-833: due rows must never appear in client payloads (finish above should remove them)
        queue = [q for q in queue if int(q.get("remaining") or 0) > 0]
        summary["count"] = len(queue)
        summary["has_queue"] = bool(queue)
        if queue:
            summary["first_finish_in"] = min(int(q.get("remaining") or 0) for q in queue)
        else:
            summary["first_finish_in"] = 0

        from .queue_card import (
            group_card_jobs_by_owner_key,
            map_build_queue_to_card_jobs,
            map_card_jobs_to_mini_queue_jobs,
        )

        payload = {
            "planet_id": int(planet_id),
            "queue": queue,
            "summary": summary,
        }
        card_jobs = map_build_queue_to_card_jobs(payload, now=now)
        payload["card_jobs_by_owner"] = group_card_jobs_by_owner_key(card_jobs)
        payload["mini_queue_jobs"] = map_card_jobs_to_mini_queue_jobs(
            card_jobs, domain="building", now=now
        )
        return payload

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
    *,
    queue_mode: str = "single",
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

    from .options import vacation_blocks_outbound

    ok_vacation, vac_reason = vacation_blocks_outbound(user_id, conn=db())
    if not ok_vacation:
        return False, vac_reason, {}

    want_max = str(queue_mode or "single").strip().lower() == "max"

    conn = db()
    finished_any = False
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, planet_id)
        now = time.time()

        from .queue_engine import finish_due_work
        from .live_state import current_action_perf

        perf = current_action_perf()
        finish_t0 = time.perf_counter()
        engine_result = finish_due_work(
            player_id=user_id,
            planet_id=planet_id,
            now=now,
            conn=conn,
            source="action",
            recalc_ranks=False,
        )
        if perf is not None:
            perf.add_finish_ms((time.perf_counter() - finish_t0) * 1000.0)

        mutate_t0 = time.perf_counter()
        finished_any = (
            int(engine_result["finished"]["buildings"])
            + int(engine_result["finished"]["research"])
        ) > 0

        try:
            from game.planet_evolution.repository import evolution_schema_ready
            from game.planet_evolution.bootstrap import ensure_planet_evolution

            if evolution_schema_ready(conn):
                ensure_planet_evolution(planet_id, conn)
        except Exception:
            pass

        recalculate_build_queue_finish_times(
            planet_id, user_id, conn=conn, now=now
        )

        settings = get_game_settings(conn=conn)
        queue_limit = _resolve_build_queue_limit(settings)

        jobs_queued = 0
        job_ids: List[int] = []
        queued_spends: List[tuple[int, int, int]] = []
        last_payload: Dict[str, Any] = {}
        last_reason = "invalid"
        last_fail: Dict[str, Any] = {}
        max_attempts = 64 if want_max else 1

        buildings = get_planet_buildings(planet_id, conn=conn)
        research_levels = get_research_levels(user_id=user_id, conn=conn)
        hotpath = BuildingsPanelContext.for_queue_recalc(
            user_id, buildings, research_levels, conn=conn
        )
        rows_db: List[Dict[str, Any]] = list(get_build_queue_rows(planet_id, conn=conn))

        def _record_mutate_perf() -> None:
            if perf is not None:
                perf.add_mutate_ms((time.perf_counter() - mutate_t0) * 1000.0)

        cur = conn.cursor()
        cur.execute(
            "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
            (planet_id,),
        )
        prow = cur.fetchone()
        if not prow:
            _record_mutate_perf()
            rollback(conn)
            return False, "invalid", {"msg": "Planet not found"}
        planet_metal = float(prow["metal"] or 0)
        planet_crystal = float(prow["crystal"] or 0)

        for _ in range(max_attempts):
            current_level = int(buildings.get(building_type, 0) or 0)
            max_level = hotpath.max_level(building_type)

            if current_level >= max_level:
                last_reason = "invalid"
                last_fail = {"msg": "Max level reached", "max_level": max_level}
                break

            queued_same = sum(1 for r in rows_db if str(r["building_type"]) == building_type)
            target_level = current_level + queued_same + 1

            if target_level > max_level:
                last_reason = "invalid"
                last_fail = {
                    "msg": "Max level reached",
                    "max_level": max_level,
                    "target_level": target_level,
                }
                break

            if not has_building_requirements(buildings, research_levels, building_type):
                last_reason = "requirements"
                last_fail = {
                    "building_type": building_type,
                    "current_level": current_level,
                    "target_level": target_level,
                }
                break

            cost_metal, cost_crystal = get_upgrade_cost(building_type, current_level + queued_same)

            if planet_metal < cost_metal or planet_crystal < cost_crystal:
                last_reason = "resources"
                last_fail = {
                    "building_type": building_type,
                    "current_level": current_level,
                    "target_level": target_level,
                    "cost_metal": cost_metal,
                    "cost_crystal": cost_crystal,
                    "planet_metal": planet_metal,
                    "planet_crystal": planet_crystal,
                }
                break

            if len(rows_db) >= queue_limit:
                last_reason = "queue_full"
                last_fail = {"queue_count": len(rows_db), "queue_limit": queue_limit}
                break

            duration = hotpath.build_time_seconds(building_type, target_level)

            last_finish_time = max(float(r["finish_time"]) for r in rows_db) if rows_db else now
            start_time = max(now, last_finish_time)
            finish_time = start_time + duration

            if not try_spend_resources_conn(conn, planet_id, int(cost_metal), int(cost_crystal)):
                last_reason = "resources"
                last_fail = {
                    "building_type": building_type,
                    "current_level": current_level,
                    "target_level": target_level,
                    "cost_metal": cost_metal,
                    "cost_crystal": cost_crystal,
                }
                break

            job_id = add_build_job(
                planet_id,
                building_type,
                start_time,
                finish_time,
                conn=conn,
                cost_metal=int(cost_metal),
                cost_crystal=int(cost_crystal),
            )
            jobs_queued += 1
            job_ids.append(int(job_id))
            queued_spends.append((int(job_id), int(cost_metal), int(cost_crystal)))
            last_payload = {
                "job_id": int(job_id),
                "building_type": building_type,
                "target_level": int(target_level),
                "duration": int(duration),
                "finish_time": float(finish_time),
                "queue_limit": int(queue_limit),
                "max_level": int(max_level),
            }
            rows_db.append(
                {
                    "id": int(job_id),
                    "building_type": building_type,
                    "start_time": float(start_time),
                    "finish_time": float(finish_time),
                }
            )
            planet_metal -= float(cost_metal)
            planet_crystal -= float(cost_crystal)

            if not want_max:
                break

        if jobs_queued <= 0:
            _record_mutate_perf()
            rollback(conn)
            return False, last_reason, last_fail

        commit(conn)

        if queued_spends:
            try:
                from .directives.progress import emit_resource_spent_event

                for job_id, spend_m, spend_c in queued_spends:
                    emit_resource_spent_event(
                        user_id,
                        metal=spend_m,
                        crystal=spend_c,
                        source_event_id=f"build_spend:{job_id}",
                        context="build",
                        conn=conn,
                        now=now,
                    )
                conn.commit()
            except Exception:
                logger.exception(
                    "imperial_directives build spend progress failed player=%s",
                    user_id,
                )

        if finished_any:
            invalidate_player_score_cache(user_id)

        last_payload["jobs_queued"] = int(jobs_queued)
        if len(job_ids) > 1:
            last_payload["job_ids"] = job_ids
        _record_mutate_perf()
        return True, "ok", last_payload

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
            SELECT id, building_type, start_time, finish_time, cost_metal, cost_crystal
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

        from .queue_refund import refund_build_job

        refund = refund_build_job(
            conn,
            planet_id,
            job_id=int(row["id"]),
            building_type=str(row["building_type"]),
            start_time=float(row["start_time"] or now),
            finish_time=float(row["finish_time"] or now),
            now=now,
            cost_metal=int(row["cost_metal"] or 0),
            cost_crystal=int(row["cost_crystal"] or 0),
            user_id=int(owner_id),
        )

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
            **refund,
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
