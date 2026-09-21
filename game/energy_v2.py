"""Energy V2 candidate model — shadow/simulation only.

This module deliberately does NOT own live gameplay yet. It exists so the
Solar/Research/secondary-source rebalance can be simulated against current
universes before EffectResolver switches away from the GC-863 legacy anchor.

Design goals:
- equal Solar and mine levels should no longer be an automatic 100% solution;
- Energy Technology stays valuable forever but can never reduce mine draw to 0;
- a secondary generator gives cold/high-output worlds a real alternative;
- orbital collectors can later provide a cheap/fragile temperature-sensitive path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


SOLAR_BASE_SHARE = 0.75
ENERGY_TECH_DRAW_COEFF = 0.025
GEOTHERMAL_BASE = 8.0
GEOTHERMAL_TECH_COEFF = 0.02
ENERGY_TECH_EFFECTIVE_SCALE = 60.0


def mine_raw_draw(level: int, coefficient: int) -> int:
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    return int(int(coefficient) * (lvl ** 1.25))


def combined_raw_mine_draw(
    metal_level: int,
    crystal_level: int,
    fuel_level: int,
) -> int:
    return (
        mine_raw_draw(metal_level, 10)
        + mine_raw_draw(crystal_level, 6)
        + mine_raw_draw(fuel_level, 8)
    )


def energy_tech_draw_factor(level: int) -> float:
    """Diminishing, unbounded research value without ever deleting demand."""
    lvl = max(0, int(level or 0))
    return 1.0 / (1.0 + ENERGY_TECH_DRAW_COEFF * lvl)


def effective_energy_tech_level(level: int) -> float:
    """Logarithmic tail for secondary-generator research scaling."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0.0
    scale = float(ENERGY_TECH_EFFECTIVE_SCALE)
    return scale * math.log1p(lvl / scale)


def solar_supply_base(level: int) -> int:
    """Stable source: 75% of the old equal-level auto-solve anchor."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    legacy_anchor = combined_raw_mine_draw(lvl, lvl, lvl) + 1
    return max(1, int(round(legacy_anchor * SOLAR_BASE_SHARE)))


def geothermal_supply(level: int, energy_tech_level: int) -> int:
    """Secondary generator; research makes it the strong mid/endgame option."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    tech = effective_energy_tech_level(energy_tech_level)
    factor = 1.0 + GEOTHERMAL_TECH_COEFF * tech
    return max(0, int(round(GEOTHERMAL_BASE * (lvl ** 2) * factor)))


def orbital_collector_output_per_unit(max_temperature_c: float) -> int:
    """OGame-like temperature-sensitive orbital source for future integration."""
    return max(1, int((float(max_temperature_c) + 140.0) / 6.0))


def orbital_collector_supply(count: int, max_temperature_c: float) -> int:
    return max(0, int(count or 0)) * orbital_collector_output_per_unit(max_temperature_c)


@dataclass(frozen=True)
class EnergyV2Snapshot:
    solar: int
    geothermal: int
    orbital: int
    total: int
    raw_demand: int
    effective_demand: int
    ratio: float
    tech_draw_factor: float


def candidate_snapshot(
    *,
    metal_level: int,
    crystal_level: int,
    fuel_level: int,
    solar_level: int,
    geothermal_level: int = 0,
    energy_tech_level: int = 0,
    solar_output_factor: float = 1.0,
    orbital_collectors: int = 0,
    max_temperature_c: Optional[float] = None,
) -> EnergyV2Snapshot:
    raw = combined_raw_mine_draw(metal_level, crystal_level, fuel_level)
    tech_factor = energy_tech_draw_factor(energy_tech_level)
    demand = 0 if raw <= 0 else max(1, int(round(raw * tech_factor)))

    solar = max(
        0,
        int(round(solar_supply_base(solar_level) * max(0.0, float(solar_output_factor)))),
    )
    geo = geothermal_supply(geothermal_level, energy_tech_level)
    orbital = 0
    if orbital_collectors > 0 and max_temperature_c is not None:
        orbital = orbital_collector_supply(orbital_collectors, max_temperature_c)

    total = solar + geo + orbital
    ratio = 1.0 if demand <= 0 else min(1.0, total / demand)
    return EnergyV2Snapshot(
        solar=solar,
        geothermal=geo,
        orbital=orbital,
        total=total,
        raw_demand=raw,
        effective_demand=demand,
        ratio=ratio,
        tech_draw_factor=tech_factor,
    )
