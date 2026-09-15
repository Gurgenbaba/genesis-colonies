"""Versioned progression valuation for the Endgame Economy V2 cutover.

This module intentionally does *not* call live upgrade-price functions. Ranking must
not be retroactively rewritten when gameplay prices are rebalanced later.

V2 contract:
- levels <= 120 preserve the economy values that were live at the cutover baseline;
- mine levels > 120 use the C1 q=4 production continuation and the V2 reference
  investment horizon;
- research valuation uses a frozen V2 reference-income curve, independent from
  events, boosters, commander effects, directives, energy, or live colony state;
- liquid resources are not part of progression valuation (handled by ranking_core).
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN, localcontext
from functools import lru_cache
from typing import Any, Dict, Mapping, Tuple

VALUATION_VERSION = "v2"
V2_PIVOT_LEVEL = 120
V2_TAIL_POWER = 4
V2_GROWTH_RATE = Decimal("1.075")
V2_HORIZON_AT_PIVOT_HOURS = Decimal("2000")
V2_HORIZON_EXPONENT = Decimal("0.45")

SCORE_METAL_DIVISOR = 1500
SCORE_CRYSTAL_DIVISOR = 1000
SCORE_FUEL_DIVISOR = 500

STANDARD_PRODUCTION = {
    "metal": Decimal("15000"),
    "crystal": Decimal("10000"),
    "fuel_cells": Decimal("5000"),
}
MINE_BASE = {
    "metal": Decimal("150"),
    "crystal": Decimal("100"),
    "fuel_cells": Decimal("50"),
}

# Frozen from the GC-821/GC-863 live baseline at the V2 cutover.
# (k, exponent, metal fraction, crystal fraction, storage multiplier)
_BUILDING_CURVES: Dict[str, Tuple[str, str, str, str, str]] = {
    "metal_mine": ("0.82", "2.05", "0.75", "0.25", "1"),
    "crystal_mine": ("0.55", "2.05", "0.59", "0.41", "1"),
    "fuel_cell_plant": ("0.60", "2.05", "0.60", "0.40", "1"),
    "solar_plant": ("1200", "1.45", "0.82", "0.18", "1"),
    "metal_storage": ("2100", "1.50", "1", "0", "5"),
    "crystal_storage": ("2100", "1.50", "0", "1", "5"),
    "fuel_storage": ("1900", "1.48", "0.60", "0.40", "5"),
    "research_lab": ("3298", "2.20", "0.33", "0.67", "1"),
    "academy": ("4580", "2.20", "0.40", "0.60", "1"),
    "command_center": ("3664", "2.20", "0.71", "0.29", "1"),
    "orbital_shipyard": ("3298", "2.20", "0.57", "0.43", "1"),
    "defense_factory": ("2600", "1.50", "0.60", "0.40", "1"),
    "barracks": ("1400", "1.48", "0.60", "0.40", "1"),
    "radar_array": ("1500", "1.48", "0.25", "0.75", "1"),
    "shield_generator": ("3240", "1.52", "0.56", "0.44", "1"),
    "terraformer": ("4320", "1.54", "0.50", "0.50", "1"),
    "nanofactory": ("3200", "1.55", "0.62", "0.38", "1"),
    "geothermal_nexus": ("6480", "1.55", "0.50", "0.50", "1"),
    "planet_core_nexus": ("8640", "1.56", "0.40", "0.60", "1"),
}
_MINE_BUILDINGS = frozenset({"metal_mine", "crystal_mine", "fuel_cell_plant"})
_MINE_K_RATIO = {
    "metal_mine": Decimal("1"),
    "crystal_mine": Decimal("0.55") / Decimal("0.82"),
    "fuel_cell_plant": Decimal("0.60") / Decimal("0.82"),
}

_MINE_ROI_ANCHORS = {
    20: 50.0,
    40: 100.0,
    60: 200.0,
    80: 500.0,
    100: 1000.0,
    120: 2000.0,
}

# Frozen account-research base costs at the V2 baseline.
_RESEARCH_BASE_COSTS: Dict[str, Tuple[int, int]] = {
    "energy_tech": (1000, 500),
    "mining_tech": (1000, 500),
    "crystal_tech": (1000, 500),
    "buildtime_tech": (1250, 750),
    "storage_tech": (500, 500),
    "drone_tech": (1500, 1000),
    "navigation_tech": (1250, 750),
    "engine_tech": (1500, 1000),
    "weapon_tech": (1000, 500),
    "armor_tech": (1250, 750),
    "shield_tech": (1250, 750),
    "fuel_efficiency": (1500, 500),
    "interstellar_expansion": (2500, 1500),
}
_RESEARCH_AFFORD_HOURS = {
    10: 8.0,
    20: 24.0,
    30: 96.0,
    35: 168.0,
    38: 252.0,
    40: 336.0,
    50: 720.0,
    60: 1080.0,
    80: 2160.0,
    100: 4320.0,
    120: 8640.0,
}
_RESEARCH_L1_AFFORD_HOURS = 3.0
_RESEARCH_COST_RAMP_LEVEL = 10
_RESEARCH_REF_COMBINED_COST = Decimal("1500")


def _dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _legacy_mine_output(resource: str, level: int) -> Decimal:
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return Decimal(0)
    with localcontext() as ctx:
        ctx.prec = max(96, len(str(lvl)) + 96)
        return +(MINE_BASE[resource] * Decimal(lvl) * (V2_GROWTH_RATE ** lvl))


def reference_mine_output_v2(resource: str, level: int) -> Decimal:
    """Frozen reference mine output used only for V2 progression valuation."""
    key = str(resource)
    if key not in MINE_BASE:
        raise ValueError(f"unsupported resource: {resource!r}")
    lvl = max(0, int(level or 0))
    if lvl <= V2_PIVOT_LEVEL:
        return _legacy_mine_output(key, lvl)
    with localcontext() as ctx:
        ctx.prec = max(128, len(str(lvl)) * 6 + 128)
        pivot = _legacy_mine_output(key, V2_PIVOT_LEVEL)
        slope = (Decimal(1) / Decimal(V2_PIVOT_LEVEL)) + Decimal(str(math.log(1.075)))
        x = Decimal(lvl - V2_PIVOT_LEVEL)
        q = Decimal(V2_TAIL_POWER)
        return +(pivot * ((Decimal(1) + slope * x / q) ** V2_TAIL_POWER))


def reference_investment_horizon_hours_v2(level: int) -> Decimal:
    """Reference ROI horizon. Historical anchors stay intact through L120."""
    lvl = max(1, int(level or 1))
    if lvl <= V2_PIVOT_LEVEL:
        return Decimal(str(_log_interpolate(lvl, _MINE_ROI_ANCHORS)))
    # Decimal has no fractional pow on all supported Python versions; this is a
    # tiny bounded balance exponent, so compute the dimensionless ratio in float
    # and immediately convert back. Levels themselves remain integer-exact.
    ratio = float(lvl) / float(V2_PIVOT_LEVEL)
    return Decimal(str(float(V2_HORIZON_AT_PIVOT_HOURS) * (ratio ** float(V2_HORIZON_EXPONENT))))


def _log_interpolate(level: int, anchors: Mapping[int, float]) -> float:
    points = sorted((int(k), float(v)) for k, v in anchors.items())
    lvl = max(1, int(level))
    if lvl <= points[0][0]:
        return points[0][1]
    if lvl >= points[-1][0]:
        return points[-1][1]
    for (l0, v0), (l1, v1) in zip(points, points[1:]):
        if l0 <= lvl <= l1:
            t = (lvl - l0) / float(l1 - l0)
            return math.exp(math.log(v0) * (1.0 - t) + math.log(v1) * t)
    return points[-1][1]


def _split_cost(total: Decimal, metal_frac: Decimal, crystal_frac: Decimal) -> Dict[str, int]:
    total = max(Decimal(1), total)
    with localcontext() as ctx:
        ctx.prec = max(96, len(total.as_tuple().digits) + 64)
        metal = max(1, int((total * metal_frac).to_integral_value(rounding=ROUND_CEILING)))
        crystal = max(0, int((total * crystal_frac).to_integral_value(rounding=ROUND_CEILING)))
    return {"metal": metal, "crystal": crystal, "fuel_cells": 0}


def building_level_reference_cost_v2(building_type: str, target_level: int) -> Dict[str, int]:
    """Frozen reference cost for one target level, independent of live prices."""
    key = str(building_type)
    lvl = max(1, int(target_level))
    if key == "nanofactory":
        growth = 1 << lvl
        return {
            "metal": 10_000 * growth,
            "crystal": 5_000 * growth,
            "fuel_cells": 0,
        }
    cfg = _BUILDING_CURVES.get(key)
    if cfg is None:
        # Preserve the historical unknown-building fallback for completeness.
        mult = Decimal("1.5") ** (lvl - 1)
        return {
            "metal": int(Decimal(100) * mult),
            "crystal": int(Decimal(50) * mult),
            "fuel_cells": 0,
        }
    k, exponent, mf, cf, storage_mult = map(Decimal, cfg)
    if key in _MINE_BUILDINGS:
        current = reference_mine_output_v2("metal", lvl)
        previous = reference_mine_output_v2("metal", lvl - 1)
        delta = max(Decimal(0), current - previous)
        total = delta * reference_investment_horizon_hours_v2(lvl) * _MINE_K_RATIO[key]
    else:
        # Same frozen power curve as the V2 baseline for non-mines.
        raw = float(k) * (float(lvl) ** float(exponent)) * float(storage_mult)
        total = Decimal(str(max(raw, 1.0)))
    return _split_cost(total, mf, cf)


@lru_cache(maxsize=8192)
def building_progression_resources_v2(building_type: str, level: int) -> Tuple[int, int, int]:
    lvl = max(0, int(level or 0))
    metal = crystal = fuel = 0
    for target in range(1, lvl + 1):
        row = building_level_reference_cost_v2(str(building_type), target)
        metal += int(row["metal"])
        crystal += int(row["crystal"])
        fuel += int(row.get("fuel_cells") or 0)
    return metal, crystal, fuel


def _score_resources(metal: int, crystal: int, fuel: int = 0) -> int:
    return (
        max(0, int(metal)) // SCORE_METAL_DIVISOR
        + max(0, int(crystal)) // SCORE_CRYSTAL_DIVISOR
        + max(0, int(fuel)) // SCORE_FUEL_DIVISOR
    )


def building_progression_value_v2(building_type: str, level: int) -> int:
    """Canonical versioned building progression value requested by the V2 cutover."""
    m, c, f = building_progression_resources_v2(str(building_type), int(level))
    return _score_resources(m, c, f)


def _research_afford_hours(level: int) -> float:
    lvl = max(1, int(level))
    if lvl < _RESEARCH_COST_RAMP_LEVEL:
        t = (lvl - 1) / float(_RESEARCH_COST_RAMP_LEVEL - 1)
        return _RESEARCH_L1_AFFORD_HOURS * (1.0 - t) + _RESEARCH_AFFORD_HOURS[10] * t
    return _log_interpolate(lvl, _RESEARCH_AFFORD_HOURS)


def _research_reference_income_v2(level: int) -> Decimal:
    lvl = max(1, int(level))
    return (
        STANDARD_PRODUCTION["metal"]
        + reference_mine_output_v2("metal", lvl)
        + STANDARD_PRODUCTION["crystal"]
        + reference_mine_output_v2("crystal", lvl)
    )


def _round_total(total: Decimal) -> int:
    value = max(Decimal(1), total)
    if value < 1_000:
        step = 50
    elif value < 5_000:
        step = 250
    elif value < 25_000:
        step = 500
    elif value < 100_000:
        step = 2_500
    elif value < 500_000:
        step = 10_000
    elif value < 5_000_000:
        step = 50_000
    elif value < 50_000_000:
        step = 250_000
    elif value < 500_000_000:
        step = 1_000_000
    else:
        step = 5_000_000
    with localcontext() as ctx:
        ctx.prec = max(96, len(value.as_tuple().digits) + 64)
        units = (value / Decimal(step)).to_integral_value(rounding=ROUND_HALF_EVEN)
        return max(step, int(units) * step)


def _split_research_total(total: int, base_m: int, base_c: int) -> Tuple[int, int]:
    combined = int(base_m) + int(base_c)
    if combined <= 0 or total <= 0:
        return max(1, int(total)), 0
    if total >= 100_000_000:
        step = 1_000_000
    elif total >= 10_000_000:
        step = 250_000
    elif total >= 1_000_000:
        step = 50_000
    else:
        step = 250 if total < 5_000 else (500 if total < 25_000 else 2_500)
    # Exact round-half-even ratio, matching the arbitrary-precision live path.
    num = int(total) * int(base_m)
    den = combined * step
    q, r = divmod(num, den)
    twice = r * 2
    if twice > den or (twice == den and q % 2):
        q += 1
    metal = max(step, q * step)
    metal = min(metal, total - step) if total > step else total
    return max(1, metal), max(0, int(total) - metal)


def research_level_reference_cost_v2(tech_key: str, target_level: int) -> Dict[str, int]:
    key = str(tech_key)
    if key not in _RESEARCH_BASE_COSTS:
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    lvl = max(1, int(target_level))
    base_m, base_c = _RESEARCH_BASE_COSTS[key]
    with localcontext() as ctx:
        ctx.prec = 160
        anchor = _research_reference_income_v2(lvl) * Decimal(str(_research_afford_hours(lvl)))
        combined = Decimal(base_m + base_c)
        tier = max(Decimal("0.75"), combined / _RESEARCH_REF_COMBINED_COST)
        total = _round_total(anchor * tier)
    metal, crystal = _split_research_total(total, base_m, base_c)
    return {"metal": metal, "crystal": crystal, "fuel_cells": 0}


@lru_cache(maxsize=4096)
def research_progression_resources_v2(tech_key: str, level: int) -> Tuple[int, int, int]:
    lvl = max(0, int(level or 0))
    metal = crystal = fuel = 0
    for target in range(1, lvl + 1):
        row = research_level_reference_cost_v2(str(tech_key), target)
        metal += int(row["metal"])
        crystal += int(row["crystal"])
        fuel += int(row.get("fuel_cells") or 0)
    return metal, crystal, fuel


def research_progression_value_v2(tech_key: str, level: int) -> int:
    m, c, f = research_progression_resources_v2(str(tech_key), int(level))
    return _score_resources(m, c, f)
