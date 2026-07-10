"""
GC-821 — Economy rebalance helpers (consumer pass after GC-820).

Aligns building costs/times with power-scaled production from production_formula.
Does NOT implement production — only upgrade pacing, storage targets, and snapshots.

Authoritative production: game/production_formula.py · docs/PRODUCTION_FORMULA_SYSTEM.md
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .production_formula import (
    LEVEL_GROWTH,
    ProductionContext,
    calculate_resource_output,
    mine_output,
    normalize_resource_type,
)

# Benchmark levels for tests and balance docs.
BENCHMARK_LEVELS: Tuple[int, ...] = (10, 30, 60, 90, 120)
# GC-821E — ROI snapshot levels (mine payback hours).
ROI_BENCHMARK_LEVELS: Tuple[int, ...] = (20, 40, 60, 80, 100, 120)
NEUTRAL_BALANCE_SLOT = 9
MINE_PACE_REF_LEVEL = 20
MINE_ENDGAME_PACE_THRESHOLD = 80

# GC-821F — target payback hours (neutral slot, metal mine reference).
MINE_UPGRADE_ROI_TARGET_HOURS: Dict[int, float] = {
    20: 50.0,
    40: 100.0,
    60: 200.0,
    80: 500.0,
    100: 1000.0,
    120: 2000.0,
}

# GC-821F — bulk upgrade UX prep (UI follow-up ticket).
MINE_BULK_UPGRADE_INCREMENTS: Tuple[int, ...] = (1, 5, 10)

MINE_BUILDING_TYPES = frozenset({"metal_mine", "crystal_mine", "fuel_cell_plant"})
STORAGE_BUILDING_TYPES = frozenset({"metal_storage", "crystal_storage", "fuel_storage"})
STORAGE_BUILDING_COST_MULTIPLIER = 5.0
MINE_RESOURCE_BY_BUILDING: Dict[str, str] = {
    "metal_mine": "metal",
    "crystal_mine": "crystal",
    "fuel_cell_plant": "fuel_cells",
}

# Power-cost: total resource value ≈ K × level^exponent (split per building).
class _CostCurve:
    __slots__ = ("k", "exponent", "metal_frac", "crystal_frac", "pace_gamma", "endgame_delta")

    def __init__(
        self,
        k: float,
        exponent: float,
        metal_frac: float,
        crystal_frac: float,
        *,
        pace_gamma: float = 0.0,
        endgame_delta: float = 0.0,
    ) -> None:
        self.k = k
        self.exponent = exponent
        self.metal_frac = metal_frac
        self.crystal_frac = crystal_frac
        self.pace_gamma = pace_gamma
        self.endgame_delta = endgame_delta


# GC-821E — mine costs: power exponent + level pacing (L120 ≈ 1–3 months ROI).
_MINE_COST_EXPONENT = 2.05
_MINE_PACE_GAMMA = 1.25
_MINE_ENDGAME_DELTA = 3.40

# GC-863A — percent-power buildings use steeper endgame cost exponent.
_PERCENT_POWER_COST_EXPONENT = 2.20

BUILDING_UPGRADE_CURVES: Dict[str, _CostCurve] = {
    "metal_mine": _CostCurve(
        0.82, _MINE_COST_EXPONENT, 0.75, 0.25, pace_gamma=_MINE_PACE_GAMMA, endgame_delta=_MINE_ENDGAME_DELTA
    ),
    "crystal_mine": _CostCurve(
        0.55, _MINE_COST_EXPONENT, 0.59, 0.41, pace_gamma=_MINE_PACE_GAMMA, endgame_delta=_MINE_ENDGAME_DELTA
    ),
    "solar_plant": _CostCurve(1200.0, 1.45, 0.82, 0.18),  # GC-863
    "fuel_cell_plant": _CostCurve(
        0.60, _MINE_COST_EXPONENT, 0.60, 0.40, pace_gamma=_MINE_PACE_GAMMA, endgame_delta=_MINE_ENDGAME_DELTA
    ),
    "metal_storage": _CostCurve(2100.0, 1.50, 1.0, 0.0),  # GC-863
    "crystal_storage": _CostCurve(2100.0, 1.50, 0.0, 1.0),  # GC-863
    "fuel_storage": _CostCurve(1900.0, 1.48, 0.60, 0.40),  # GC-863
    "research_lab": _CostCurve(3298.0, _PERCENT_POWER_COST_EXPONENT, 0.33, 0.67),  # GC-863A
    "academy": _CostCurve(4580.0, _PERCENT_POWER_COST_EXPONENT, 0.40, 0.60),  # GC-863A
    "command_center": _CostCurve(3664.0, _PERCENT_POWER_COST_EXPONENT, 0.71, 0.29),  # GC-863A
    "orbital_shipyard": _CostCurve(3298.0, _PERCENT_POWER_COST_EXPONENT, 0.57, 0.43),  # GC-863A
    "defense_factory": _CostCurve(2600.0, 1.50, 0.60, 0.40),  # GC-863
    "barracks": _CostCurve(1400.0, 1.48, 0.60, 0.40),  # GC-863
    "radar_array": _CostCurve(1500.0, 1.48, 0.25, 0.75),  # GC-863
    "shield_generator": _CostCurve(3240.0, 1.52, 0.56, 0.44),  # GC-863
    "terraformer": _CostCurve(4320.0, 1.54, 0.50, 0.50),  # GC-863
    "nanofactory": _CostCurve(3200.0, 1.55, 0.62, 0.38),  # overridden in power_upgrade_cost (GC-863)
    "geothermal_nexus": _CostCurve(6480.0, 1.55, 0.50, 0.50),  # GC-863
    "planet_core_nexus": _CostCurve(8640.0, 1.56, 0.40, 0.60),  # GC-863
}

# Build seconds ≈ TIME_K × level^1.35 (player speed applied separately).
BUILD_TIME_CURVES: Dict[str, Tuple[float, float]] = {
    "metal_mine": (114.0, 1.35),
    "crystal_mine": (114.0, 1.35),
    "solar_plant": (130.0, 1.35),
    "fuel_cell_plant": (145.0, 1.36),
    "metal_storage": (120.0, 1.36),
    "crystal_storage": (120.0, 1.36),
    "fuel_storage": (120.0, 1.36),
    "research_lab": (180.0, 1.38),
    "academy": (220.0, 1.38),
    "command_center": (280.0, 1.40),
    "orbital_shipyard": (260.0, 1.40),
    "defense_factory": (280.0, 1.40),
    "barracks": (200.0, 1.38),
    "radar_array": (200.0, 1.38),
    "shield_generator": (360.0, 1.42),
    "terraformer": (320.0, 1.42),
    "nanofactory": (480.0, 1.44),
    "geothermal_nexus": (520.0, 1.44),
    "planet_core_nexus": (580.0, 1.45),
}

# GC-821B — default depot when no storage building (metal/crystal/fuel starter cap).
STORAGE_BASE_CAPACITY = 150_000
# GC-872 — depot cap = base + 24h of a metal mine at 3× depot level.
STORAGE_REFERENCE_RESOURCE = "metal"
STORAGE_REFERENCE_MINE_LEVEL_FACTOR = 3
STORAGE_REFERENCE_HOURS = 24

# GC-863 — nanofactory upgrade costs (target level X); GC-863A steeper growth.
NANOFACTORY_METAL_BASE = 10_000.0
NANOFACTORY_CRYSTAL_BASE = 5_000.0
NANOFACTORY_COST_GROWTH = 2.0  # Alpha: doubles per target level (OGame-style steep investment)

# GC-821B — exchange (scales with empire day production via exchange.py).
EXCHANGE_DAILY_LIMIT_MIN = 500_000
EXCHANGE_DAILY_LIMIT_PCT_DEFAULT = 80

# GC-821C — loot / reward floors scale with empire output, not fixed pre-820 absolutes.
LOOT_RESOURCE_FLOOR_MIN = 12_000
LOOT_RESOURCE_FLOOR_MAX = 30_000
LOOT_BASE_PRODUCTION_HOURS = 0.5

# GC-821D — military cost multiplier vs legacy defs (uniform pass).
MILITARY_COST_MULTIPLIER = 1.25
MILITARY_SCORE_MULTIPLIER = 1.0
MILITARY_BUILD_SECONDS_MULTIPLIER = 1.0

# GC-825 — account research upgrade pacing (time anchors unchanged).
RESEARCH_REF_COMBINED_COST = 1500.0  # energy_tech base_m + base_c
RESEARCH_REF_BASE_TIME = 840.0  # energy_tech base_time seconds
RESEARCH_BENCHMARK_LEVELS: Tuple[int, ...] = (10, 20, 30, 35, 40, 50, 60, 80, 100, 120)

RESEARCH_TIME_ANCHOR_HOURS: Dict[int, float] = {
    10: 1.5,  # ~90 min
    20: 5.0,
    30: 24.0,
    40: 72.0,  # 3 days
    60: 336.0,  # 2 weeks
    80: 1080.0,  # ~45 days
    100: 2160.0,  # ~90 days
    120: 4320.0,  # ~180 days
}

# GC-RESEARCH-COST-REBALANCE — target afford hours × reference empire income (metal+crystal @ level).
# energy_tech tier 1.0; other techs scale via research_cost_tier(base_cost_m/c).
RESEARCH_COST_AFFORD_HOURS: Dict[int, float] = {
    10: 8.0,
    20: 24.0,
    30: 96.0,  # ~4 days production
    35: 168.0,  # ~1 week
    38: 252.0,  # ~10 days
    40: 336.0,  # ~2 weeks
    50: 720.0,  # ~30 days
    60: 1080.0,  # ~45 days
    80: 2160.0,  # ~90 days
    100: 4320.0,  # ~180 days
    120: 8640.0,  # ~360 days
}
_RESEARCH_L1_AFFORD_HOURS = 3.0
_RESEARCH_COST_RAMP_LEVEL = 10


def _log_interpolate_anchor_map(level: int, anchors: Dict[int, float]) -> float:
    """Log-linear interpolation between sorted anchor levels."""
    sorted_anchors = sorted(anchors.items())
    lvl = max(1, int(level))
    if lvl <= sorted_anchors[0][0]:
        return float(sorted_anchors[0][1])
    if lvl >= sorted_anchors[-1][0]:
        return float(sorted_anchors[-1][1])
    for i in range(len(sorted_anchors) - 1):
        l0, v0 = sorted_anchors[i]
        l1, v1 = sorted_anchors[i + 1]
        if l0 <= lvl <= l1:
            span = float(l1 - l0)
            if span <= 0:
                return float(v1)
            t = (lvl - l0) / span
            return math.exp(math.log(float(v0)) * (1.0 - t) + math.log(float(v1)) * t)
    return float(sorted_anchors[-1][1])


def research_time_anchor_hours(level: int) -> float:
    """GC-825 target research duration before lab/settings modifiers."""
    return _log_interpolate_anchor_map(level, RESEARCH_TIME_ANCHOR_HOURS)


def _research_income_reference(level: int) -> float:
    """Neutral-slot metal+crystal production/h at mine level (cost calibration reference)."""
    lvl = max(1, int(level))
    return reference_production_per_hour("metal", lvl) + reference_production_per_hour(
        "crystal", lvl
    )


def research_cost_afford_hours(level: int) -> float:
    """Target hours of reference income to afford one research upgrade (energy_tech tier)."""
    lvl = max(1, int(level))
    if lvl < _RESEARCH_COST_RAMP_LEVEL:
        h1 = float(_RESEARCH_L1_AFFORD_HOURS)
        h10 = float(RESEARCH_COST_AFFORD_HOURS[_RESEARCH_COST_RAMP_LEVEL])
        t = (lvl - 1) / float(_RESEARCH_COST_RAMP_LEVEL - 1)
        return h1 * (1.0 - t) + h10 * t
    return _log_interpolate_anchor_map(lvl, RESEARCH_COST_AFFORD_HOURS)


def research_cost_anchor_total(level: int) -> float:
    """GC-825 combined resource value (energy_tech tier) before tech tier split."""
    lvl = max(1, int(level))
    return max(1.0, _research_income_reference(lvl) * research_cost_afford_hours(lvl))


def research_time_tier(base_time: float) -> float:
    """Per-tech multiplier from legacy ``base_time`` (energy_tech = 1.0)."""
    return max(0.75, float(base_time) / RESEARCH_REF_BASE_TIME)


def research_base_time_seconds(target_level: int, *, time_tier: float = 1.0) -> int:
    """GC-825 base research seconds before EffectResolver speed bonuses."""
    hours = research_time_anchor_hours(target_level)
    seconds = hours * 3600.0 * max(0.75, float(time_tier))
    return max(60, int(seconds))


def research_cost_tier(base_cost_m: int, base_cost_c: int) -> float:
    """Per-tech cost multiplier from legacy base costs (energy_tech = 1.0)."""
    combined = float(base_cost_m) + float(base_cost_c)
    if combined <= 0:
        return 1.0
    return max(0.75, combined / RESEARCH_REF_COMBINED_COST)


def _research_cost_round_total(total: float) -> int:
    """GC-863B — snap combined research cost to Genesis round numbers."""
    t = max(1.0, float(total))
    if t < 1_000:
        step = 50
    elif t < 5_000:
        step = 250
    elif t < 25_000:
        step = 500
    elif t < 100_000:
        step = 2_500
    elif t < 500_000:
        step = 10_000
    elif t < 5_000_000:
        step = 50_000
    elif t < 50_000_000:
        step = 250_000
    elif t < 500_000_000:
        step = 1_000_000
    else:
        step = 5_000_000
    return max(step, int(round(t / step) * step))


def _split_research_cost_round(total: int, base_cost_m: int, base_cost_c: int) -> Tuple[int, int]:
    """Split a round total into round metal/crystal using tech base ratio."""
    total = int(total)
    bm, bc = int(base_cost_m), int(base_cost_c)
    combined = bm + bc
    if combined <= 0 or total <= 0:
        return max(1, total), 0
    if total >= 100_000_000:
        comp_step = 1_000_000
    elif total >= 10_000_000:
        comp_step = 250_000
    elif total >= 1_000_000:
        comp_step = 50_000
    else:
        comp_step = 250 if total < 5_000 else (500 if total < 25_000 else 2_500)
    metal = max(
        comp_step,
        int(round((total * bm / combined) / comp_step) * comp_step),
    )
    metal = min(metal, total - comp_step) if total > comp_step else total
    crystal = total - metal
    return max(1, metal), max(0, crystal)


def research_upgrade_cost(base_cost_m: int, base_cost_c: int, target_level: int) -> Tuple[int, int]:
    """GC-825 research upgrade cost (metal, crystal) before payment."""
    lvl = max(1, int(target_level))
    tier = research_cost_tier(base_cost_m, base_cost_c)
    raw_total = max(research_cost_anchor_total(lvl) * tier, 1.0)
    total = _research_cost_round_total(raw_total)
    return _split_research_cost_round(total, int(base_cost_m), int(base_cost_c))


def legacy_research_base_time_seconds(
    base_time: float,
    cost_factor: float,
    target_level: int,
) -> int:
    """Pre-GC-825 exponential research time (audit only)."""
    lvl = max(1, int(target_level))
    factor = float(cost_factor) ** (lvl - 1)
    return max(1, int(float(base_time) * factor))


def legacy_research_upgrade_cost(
    base_cost_m: int,
    base_cost_c: int,
    cost_factor: float,
    target_level: int,
) -> Tuple[int, int]:
    """Pre-GC-825 exponential research cost (audit only)."""
    lvl = max(1, int(target_level))
    factor = float(cost_factor) ** (lvl - 1)
    return max(1, int(base_cost_m * factor)), max(0, int(base_cost_c * factor))


def mine_upgrade_pace_factor(level: int, *, pace_gamma: float, endgame_delta: float) -> float:
    """Level pacing multiplier for mine upgrade costs (GC-821E)."""
    lvl = max(1, int(level))
    ref = float(MINE_PACE_REF_LEVEL)
    factor = (lvl / ref) ** float(pace_gamma)
    if endgame_delta > 0 and lvl > MINE_ENDGAME_PACE_THRESHOLD:
        factor *= ((lvl - MINE_ENDGAME_PACE_THRESHOLD) / 40.0 + 1.0) ** float(endgame_delta)
    return factor


def _mine_upgrade_cost_total_raw(building_type: str, target_level: int) -> float:
    """821E power cost before GC-821F ROI anchor scaling."""
    btype = str(building_type)
    lvl = max(1, int(target_level))
    curve = BUILDING_UPGRADE_CURVES.get(btype)
    if curve is None or btype not in MINE_BUILDING_TYPES:
        return 0.0
    total = curve.k * (float(lvl) ** curve.exponent)
    if curve.pace_gamma > 0:
        total *= mine_upgrade_pace_factor(
            lvl, pace_gamma=curve.pace_gamma, endgame_delta=curve.endgame_delta
        )
    return max(total, 1.0)


def mine_roi_anchor_hours(level: int) -> float:
    """Log-interpolated ROI target between GC-821F anchor levels."""
    return _log_interpolate_anchor_map(level, MINE_UPGRADE_ROI_TARGET_HOURS)


def mine_roi_cost_multiplier(target_level: int) -> float:
    """
    GC-821F — scale mine upgrade cost so neutral-slot metal-mine ROI follows anchor curve.
    Applied uniformly to all mine building types.

    Calibration uses full upgrade value (metal + crystal share of raw total) so
    ``mine_upgrade_roi_hours`` matches anchors after the full cost-basis ROI rule.
    """
    lvl = max(1, int(target_level))
    delta = production_delta_per_hour("metal", lvl)
    if delta <= 0:
        return 1.0
    raw_total = _mine_upgrade_cost_total_raw("metal_mine", lvl)
    baseline_roi = raw_total / delta
    if baseline_roi <= 0:
        return 1.0
    target = mine_roi_anchor_hours(lvl)
    return max(0.05, target / baseline_roi)


def storage_capacity_at_depot_level(storage_level: int) -> int:
    """GC-872 — depot cap before storage_tech/terraformer (Ferdi 3× mine × 24h anchor)."""
    lvl = max(0, int(storage_level))
    if lvl <= 0:
        return STORAGE_BASE_CAPACITY
    reference_mine_level = lvl * int(STORAGE_REFERENCE_MINE_LEVEL_FACTOR)
    reference_day_cap = mine_output(STORAGE_REFERENCE_RESOURCE, reference_mine_level) * float(
        STORAGE_REFERENCE_HOURS
    )
    return max(STORAGE_BASE_CAPACITY, int(STORAGE_BASE_CAPACITY + reference_day_cap))


def storage_capacity_anchor(
    resource_type: str,
    storage_level: int,
    *,
    slot: int = NEUTRAL_BALANCE_SLOT,
    production_speed: float = 1.0,
) -> int:
    """Legacy additive name: total depot cap minus base (resource-independent)."""
    _ = resource_type, slot, production_speed
    lvl = max(0, int(storage_level))
    if lvl <= 0:
        return 0
    return max(0, storage_capacity_at_depot_level(lvl) - STORAGE_BASE_CAPACITY)


def nanofactory_upgrade_cost(target_level: int) -> Tuple[int, int]:
    """GC-863 — Ferronit/Crytite = base × 1.33^target_level."""
    lvl = max(1, int(target_level))
    metal = max(1, int(math.ceil(NANOFACTORY_METAL_BASE * (NANOFACTORY_COST_GROWTH ** lvl))))
    crystal = max(0, int(math.ceil(NANOFACTORY_CRYSTAL_BASE * (NANOFACTORY_COST_GROWTH ** lvl))))
    return metal, crystal


def power_upgrade_cost(building_type: str, target_level: int) -> Tuple[int, int]:
    """GC-821 upgrade cost — mines use 821E pacing × GC-821F ROI anchors."""
    btype = str(building_type)
    lvl = max(1, int(target_level))
    if btype == "nanofactory":
        return nanofactory_upgrade_cost(lvl)
    curve = BUILDING_UPGRADE_CURVES.get(btype)
    if curve is None:
        mult = 1.5 ** (lvl - 1)
        return int(100 * mult), int(50 * mult)

    if btype in MINE_BUILDING_TYPES:
        total = _mine_upgrade_cost_total_raw(btype, lvl)
        total *= mine_roi_cost_multiplier(lvl)
    else:
        total = curve.k * (float(lvl) ** curve.exponent)
    if btype in STORAGE_BUILDING_TYPES:
        total *= STORAGE_BUILDING_COST_MULTIPLIER
    total = max(total, 1.0)
    metal = max(1, int(math.ceil(total * curve.metal_frac)))
    crystal = max(0, int(math.ceil(total * curve.crystal_frac)))
    return metal, crystal


def power_build_seconds(building_type: str, target_level: int) -> int:
    """GC-821 base build duration before player/admin speed modifiers."""
    btype = str(building_type)
    lvl = max(1, int(target_level))
    k, exp = BUILD_TIME_CURVES.get(btype, (120.0, 1.35))
    return max(30, int(k * (float(lvl) ** exp)))


def reference_production_per_hour(
    resource_type: str,
    mine_level: int,
    *,
    slot: int = NEUTRAL_BALANCE_SLOT,
    production_speed: float = 1.0,
) -> float:
    """Authoritative production reference for balance tables (delegates to GC-820)."""
    ctx = ProductionContext(
        resource_type=normalize_resource_type(resource_type),
        level=max(0, int(mine_level)),
        slot=slot,
        production_speed=production_speed,
    )
    return calculate_resource_output(normalize_resource_type(resource_type), ctx)


def production_delta_per_hour(
    resource_type: str,
    level: int,
    *,
    slot: int = NEUTRAL_BALANCE_SLOT,
    production_speed: float = 1.0,
) -> float:
    """Hourly output gain from upgrading to level (vs level - 1)."""
    lvl = max(0, int(level))
    if lvl < 1:
        return 0.0
    cur = reference_production_per_hour(
        resource_type, lvl, slot=slot, production_speed=production_speed
    )
    prev = reference_production_per_hour(
        resource_type, lvl - 1, slot=slot, production_speed=production_speed
    )
    return max(0.0, cur - prev)


def upgrade_roi_cost_basis(
    *,
    metal_cost: int = 0,
    crystal_cost: int = 0,
    fuel_cells_cost: int = 0,
) -> float:
    """Total upgrade cost for ROI (all resource types; missing fuel_cells → 0)."""
    return float(metal_cost or 0) + float(crystal_cost or 0) + float(fuel_cells_cost or 0)


def upgrade_roi_hours(
    *,
    metal_cost: int = 0,
    crystal_cost: int = 0,
    fuel_cells_cost: int = 0,
    delta_per_hour: float = 0,
) -> float:
    """Payback hours: sum(upgrade costs) / hourly production delta."""
    delta = float(delta_per_hour or 0)
    if delta <= 0:
        return float("inf")
    basis = upgrade_roi_cost_basis(
        metal_cost=metal_cost,
        crystal_cost=crystal_cost,
        fuel_cells_cost=fuel_cells_cost,
    )
    if basis <= 0:
        return float("inf")
    return basis / delta


def mine_upgrade_roi_hours(
    building_type: str,
    target_level: int,
    *,
    slot: int = NEUTRAL_BALANCE_SLOT,
    production_speed: float = 1.0,
    fuel_cells_cost: int = 0,
    delta_per_hour: Optional[float] = None,
) -> float:
    """Payback hours: full upgrade cost / hourly production delta (GC-821E)."""
    btype = str(building_type)
    if btype not in MINE_BUILDING_TYPES:
        return float("inf")
    resource = MINE_RESOURCE_BY_BUILDING[btype]
    metal_cost, crystal_cost = power_upgrade_cost(btype, target_level)
    if delta_per_hour is None:
        delta = production_delta_per_hour(
            resource, target_level, slot=slot, production_speed=production_speed
        )
    else:
        delta = float(delta_per_hour)
    return upgrade_roi_hours(
        metal_cost=int(metal_cost),
        crystal_cost=int(crystal_cost),
        fuel_cells_cost=int(fuel_cells_cost or 0),
        delta_per_hour=delta,
    )


def mine_upgrade_metal_hours(
    target_level: int,
    *,
    slot: int = NEUTRAL_BALANCE_SLOT,
    production_speed: float = 1.0,
) -> float:
    """Ferronit-mine payback hours (alias for mine_upgrade_roi_hours)."""
    return mine_upgrade_roi_hours(
        "metal_mine", target_level, slot=slot, production_speed=production_speed
    )


def balance_snapshot_table(
    *,
    production_speed: float = 1.0,
    slot: int = NEUTRAL_BALANCE_SLOT,
) -> Dict[str, Dict[int, Dict[str, float]]]:
    """Manual balance table: production + upgrade pacing at benchmark levels."""
    out: Dict[str, Dict[int, Dict[str, float]]] = {
        "production_per_hour": {},
        "production_delta_per_hour": {},
        "metal_upgrade_hours": {},
        "metal_upgrade_roi_hours": {},
        "metal_upgrade_cost": {},
    }
    snapshot_levels = tuple(sorted(set(BENCHMARK_LEVELS) | set(ROI_BENCHMARK_LEVELS)))
    for lvl in snapshot_levels:
        out["production_per_hour"][lvl] = {
            "metal": reference_production_per_hour("metal", lvl, slot=slot, production_speed=production_speed),
            "crystal": reference_production_per_hour("crystal", lvl, slot=slot, production_speed=production_speed),
            "fuel_cells": reference_production_per_hour(
                "fuel_cells", lvl, slot=slot, production_speed=production_speed
            ),
        }
        out["production_delta_per_hour"][lvl] = {
            "metal": production_delta_per_hour("metal", lvl, slot=slot, production_speed=production_speed),
            "crystal": production_delta_per_hour("crystal", lvl, slot=slot, production_speed=production_speed),
            "fuel_cells": production_delta_per_hour(
                "fuel_cells", lvl, slot=slot, production_speed=production_speed
            ),
        }
        mc, _ = power_upgrade_cost("metal_mine", lvl)
        out["metal_upgrade_cost"][lvl] = float(mc)
        roi = mine_upgrade_roi_hours("metal_mine", lvl, slot=slot, production_speed=production_speed)
        out["metal_upgrade_hours"][lvl] = roi
        out["metal_upgrade_roi_hours"][lvl] = roi
    return out


def scaled_military_cost(raw: int) -> int:
    return max(1, int(math.ceil(int(raw) * MILITARY_COST_MULTIPLIER)))


def scaled_military_score(raw: int) -> int:
    return max(1, int(math.ceil(int(raw) * MILITARY_SCORE_MULTIPLIER)))


def cumulative_upgrade_resource_totals(building_type: str, level: int) -> Dict[str, int]:
    """GC-SCORE-D — cumulative metal/crystal/fuel invested for levels 1..level."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    metal = 0
    crystal = 0
    for target in range(1, lvl + 1):
        m, c = power_upgrade_cost(building_type, target)
        metal += int(m)
        crystal += int(c)
    return {"metal": metal, "crystal": crystal, "fuel_cells": 0}


def cumulative_upgrade_cost_sum(building_type: str, level: int) -> int:
    """Sum of metal+crystal spent for levels 1..level (GC-821 power costs)."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    total = 0
    for target in range(1, lvl + 1):
        metal, crystal = power_upgrade_cost(building_type, target)
        total += int(metal) + int(crystal)
    return total


def cumulative_upgrade_cost_range(
    building_type: str,
    from_level: int,
    to_level: int,
) -> Tuple[int, int]:
    """GC-821F prep — total metal+crystal for upgrades (from_level+1)..to_level inclusive."""
    start = max(0, int(from_level))
    end = max(start, int(to_level))
    metal = 0
    crystal = 0
    for target in range(start + 1, end + 1):
        m, c = power_upgrade_cost(building_type, target)
        metal += int(m)
        crystal += int(c)
    return metal, crystal


def max_affordable_mine_upgrade_level(
    building_type: str,
    from_level: int,
    max_level: int,
    *,
    metal_available: float,
    crystal_available: float,
) -> int:
    """GC-821F prep — highest target level affordable in one bulk action."""
    btype = str(building_type)
    if btype not in MINE_BUILDING_TYPES:
        return max(0, int(from_level))
    cur = max(0, int(from_level))
    cap = max(cur, int(max_level))
    best = cur
    metal = float(metal_available or 0)
    crystal = float(crystal_available or 0)
    for target in range(cur + 1, cap + 1):
        m, c = power_upgrade_cost(btype, target)
        metal -= m
        crystal -= c
        if metal < 0 or crystal < 0:
            break
        best = target
    return best


def mine_bulk_upgrade_preview(
    building_type: str,
    from_level: int,
    max_level: int,
    *,
    metal_available: float,
    crystal_available: float,
) -> Dict[str, Any]:
    """GC-821F prep — metadata for +1/+5/+10/max bulk upgrade UI (no actions yet)."""
    btype = str(building_type)
    cur = max(0, int(from_level))
    cap = max(cur, int(max_level))
    affordable_max = max_affordable_mine_upgrade_level(
        btype,
        cur,
        cap,
        metal_available=metal_available,
        crystal_available=crystal_available,
    )
    options: List[Dict[str, Any]] = []
    for step in MINE_BULK_UPGRADE_INCREMENTS:
        target = min(cap, cur + int(step))
        if target <= cur:
            continue
        m, c = cumulative_upgrade_cost_range(btype, cur, target)
        options.append(
            {
                "step": int(step),
                "target_level": int(target),
                "cost_metal": int(m),
                "cost_crystal": int(c),
                "can_afford": metal_available >= m and crystal_available >= c,
            }
        )
    if affordable_max > cur:
        m, c = cumulative_upgrade_cost_range(btype, cur, affordable_max)
        options.append(
            {
                "step": "max",
                "target_level": int(affordable_max),
                "cost_metal": int(m),
                "cost_crystal": int(c),
                "can_afford": True,
            }
        )
    return {
        "increments": list(MINE_BULK_UPGRADE_INCREMENTS),
        "from_level": cur,
        "max_level": cap,
        "affordable_max_level": int(affordable_max),
        "options": options,
    }


def legacy_exponential_cost_sum(
    building_type: str,
    level: int,
    *,
    base_m: int,
    base_c: int,
    factor: float,
) -> int:
    """Pre-GC-821 cumulative cost reference for migration audits only."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    total = 0
    for lv in range(1, lvl + 1):
        mult = float(factor) ** (lv - 1)
        total += int(base_m * mult) + int(base_c * mult)
    return total


# ---------------------------------------------------------------------------
# GC-864 — loot meta pool helpers (no economy rewards in containers)
# ---------------------------------------------------------------------------

LOOT_JACKPOT_MAX_WEIGHT_PCT = 2.0


def loot_pool_total_weight(pool: List[Dict[str, Any]]) -> int:
    return sum(max(0, int(e.get("weight") or 0)) for e in pool)


def loot_jackpot_entries(
    pool: List[Dict[str, Any]],
    *,
    max_weight_pct: float = LOOT_JACKPOT_MAX_WEIGHT_PCT,
) -> List[Dict[str, Any]]:
    """Entries at or below jackpot weight threshold (container upgrades, mythics)."""
    total_w = loot_pool_total_weight(pool)
    if total_w <= 0:
        return []
    out: List[Dict[str, Any]] = []
    threshold = float(max_weight_pct)
    for entry in pool:
        w = int(entry.get("weight") or 0)
        if w <= 0:
            continue
        pct = 100.0 * float(w) / float(total_w)
        rtype = str(entry.get("reward_type") or "")
        rkey = str(entry.get("reward_key") or "")
        is_upgrade = rtype == "item" and rkey.startswith("container_")
        is_mythic = "mythic" in rkey or rkey in {
            "research_instant_level",
            "artifact_core_fragment",
            "mythic_genesis_core",
            "mythic_ancient_nexus",
        }
        if pct <= threshold and (is_upgrade or is_mythic):
            out.append({**entry, "weight_pct": round(pct, 2)})
    return out


def loot_duplicate_reward_audit(
    pools: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """reward_key → containers; flags keys appearing in 3+ pools."""
    index: Dict[str, List[str]] = {}
    for container_key, pool in pools.items():
        seen_in_pool: set[str] = set()
        for entry in pool:
            rtype = str(entry.get("reward_type") or "")
            rkey = str(entry.get("reward_key") or "")
            token = f"{rtype}:{rkey}"
            if token in seen_in_pool:
                continue
            seen_in_pool.add(token)
            index.setdefault(token, []).append(str(container_key))
    rows: List[Dict[str, Any]] = []
    for token, containers in sorted(index.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(containers) < 3:
            continue
        rtype, rkey = token.split(":", 1)
        rows.append(
            {
                "reward_type": rtype,
                "reward_key": rkey,
                "pool_count": len(containers),
                "containers": containers,
            }
        )
    return rows


def generate_loot_balance_table_markdown() -> str:
    """GC-864 — markdown meta-loot table from live LOOT_POOLS."""
    from .inventory_catalog import CONTAINER_DISPLAY_ORDER, ITEM_CATALOG

    il = _loot_import_inventory_loot()
    pools = il.LOOT_POOLS
    lines: List[str] = [
        "# GC-864 — Loot Balance Table",
        "",
        "> Auto-generated from `game/inventory_loot.py`.",
        "> **Meta-only:** boosters, fragments, items, containers — no resources/ships/defense.",
        "",
        "## Container overview",
        "",
        "| Container | Entries | Total weight | Jackpots ≤2% | Economy drops |",
        "|-----------|---------|--------------|--------------|---------------|",
    ]
    for key in CONTAINER_DISPLAY_ORDER:
        if key not in pools:
            continue
        pool = pools[key]
        total_w = loot_pool_total_weight(pool)
        jackpots = loot_jackpot_entries(pool)
        jp_note = f"{len(jackpots)} ok" if jackpots else "—"
        economy = "yes" if il.pool_has_forbidden_rewards(pool) else "no"
        lines.append(f"| `{key}` | {len(pool)} | {total_w} | {jp_note} | {economy} |")

    lines.extend(["", "## Duplicate reward audit (3+ pools)", ""])
    dupes = loot_duplicate_reward_audit(pools)
    if not dupes:
        lines.append("_No cross-pool duplicates at 3+ threshold._")
    else:
        lines.append("| Reward | Pools | Containers |")
        lines.append("|--------|-------|------------|")
        for row in dupes:
            lines.append(
                f"| `{row['reward_key']}` ({row['reward_type']}) | {row['pool_count']} | {', '.join(f'`{c}`' for c in row['containers'])} |"
            )

    lines.extend(["", "## Drops by rarity (ITEM_CATALOG)", ""])
    for key in CONTAINER_DISPLAY_ORDER:
        if key not in pools:
            continue
        pool = pools[key]
        total_w = loot_pool_total_weight(pool)
        by_rarity: Dict[str, List[str]] = {}
        for entry in pool:
            w = int(entry.get("weight") or 0)
            if w <= 0 or total_w <= 0:
                continue
            rtype = str(entry.get("reward_type") or "")
            rkey = str(entry.get("reward_key") or "")
            if rtype in ("item", "booster"):
                rarity = str((ITEM_CATALOG.get(rkey) or {}).get("rarity") or "common")
            else:
                rarity = "forbidden"
            pct = 100.0 * w / total_w
            lo = int(entry.get("min_amount") or 1)
            hi = int(entry.get("max_amount") or lo)
            amt = str(lo) if lo == hi else f"{lo}–{hi}"
            label = f"{rtype}:{rkey} ×{amt} ({pct:.1f}%)"
            by_rarity.setdefault(rarity, []).append(label)
        lines.append(f"### `{key}`")
        lines.append("")
        for rarity in ("common", "uncommon", "rare", "epic", "legendary", "mythic", "forbidden"):
            items = by_rarity.get(rarity)
            if not items:
                continue
            lines.append(f"- **{rarity}**: " + "; ".join(items))
        lines.append("")

    lines.append("---\n\n_Regenerate: `python scripts/gen_loot_balance_table.py`_")
    return "\n".join(lines)


def _loot_import_inventory_loot():
    from . import inventory_loot

    return inventory_loot
