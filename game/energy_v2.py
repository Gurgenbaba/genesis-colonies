"""Energy V2 candidate formulas — simulation/shadow only.

This module is the single source for the proposed power-economy curve. It does
not replace EffectResolver's live GC-863 energy contract yet.

The candidate copies the useful OGame-style *decision structure* without
copying its scale:
- Solar is the stable baseline but equal mine/Solar levels are only ~75% grid.
- Energy Technology no longer erases universal mine demand.
- Geothermal Nexus takes the fusion-reactor role and scales strongly with
  Energy Technology.
- Orbital collectors are a future temperature-sensitive, combat-exposed source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


ENERGY_EXPONENT = 1.25
SOLAR_COEFF = 18.0
METAL_DRAW_COEFF = 10.0
CRYSTAL_DRAW_COEFF = 6.0
FUEL_DRAW_COEFF = 8.0
GEOTHERMAL_COEFF = 4.0
GEOTHERMAL_EXPONENT = 2.0
GEOTHERMAL_ENERGY_TECH_PER_EFFECTIVE_LEVEL = 0.04
ENERGY_TECH_EFFECTIVE_SCALE = 60.0


def energy_curve(level: int) -> float:
    lvl = max(0, int(level or 0))
    return float(lvl ** ENERGY_EXPONENT) if lvl > 0 else 0.0


def solar_output(level: int) -> int:
    """Stable ground source. Equal producer/Solar levels cover ~75% raw demand."""
    return int(SOLAR_COEFF * energy_curve(level))


def effective_energy_tech_level(level: int) -> float:
    """Unbounded but diminishing research tail for power-generation scaling."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0.0
    scale = float(ENERGY_TECH_EFFECTIVE_SCALE)
    return scale * math.log1p(lvl / scale)


def geothermal_output(level: int, energy_tech: int) -> int:
    """Fusion-role source: strong mid/endgame power amplified by Energy Technology."""
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0
    effective_tech = effective_energy_tech_level(energy_tech)
    tech_factor = 1.0 + GEOTHERMAL_ENERGY_TECH_PER_EFFECTIVE_LEVEL * effective_tech
    return int(GEOTHERMAL_COEFF * (lvl ** GEOTHERMAL_EXPONENT) * tech_factor)


def mine_demand(
    metal_level: int,
    crystal_level: int,
    fuel_level: int,
    *,
    metal_draw_bps: int = 10000,
    crystal_draw_bps: int = 10000,
    fuel_draw_bps: int = 10000,
) -> int:
    """Candidate mine demand. Energy Tech does not globally reduce this value."""
    draws = (
        (METAL_DRAW_COEFF, metal_level, metal_draw_bps),
        (CRYSTAL_DRAW_COEFF, crystal_level, crystal_draw_bps),
        (FUEL_DRAW_COEFF, fuel_level, fuel_draw_bps),
    )
    total = 0
    for coeff, level, bps in draws:
        raw = int(coeff * energy_curve(level))
        factor_bps = max(100, min(10000, int(bps or 10000)))
        total += (raw * factor_bps) // 10000
    return max(0, total)


def orbital_output_per_unit(max_temperature_c: float) -> int:
    """Future OGame-inspired orbital source; temperature-sensitive by design."""
    return max(1, int(math.floor((float(max_temperature_c) + 160.0) / 6.0)))


def orbital_output(count: int, max_temperature_c: float) -> int:
    return max(0, int(count or 0)) * orbital_output_per_unit(max_temperature_c)


@dataclass(frozen=True)
class EnergyV2Snapshot:
    solar: int
    geothermal: int
    orbital: int
    total_supply: int
    demand: int
    ratio: float


def candidate_snapshot(
    *,
    metal_level: int,
    crystal_level: int,
    fuel_level: int,
    solar_level: int,
    geothermal_level: int = 0,
    energy_tech: int = 0,
    solar_output_factor: float = 1.0,
    orbital_units: int = 0,
    max_temperature_c: Optional[float] = None,
    metal_draw_bps: int = 10000,
    crystal_draw_bps: int = 10000,
    fuel_draw_bps: int = 10000,
) -> EnergyV2Snapshot:
    solar = max(
        0,
        int(round(solar_output(solar_level) * max(0.0, float(solar_output_factor)))),
    )
    geo = geothermal_output(geothermal_level, energy_tech)
    orbital = 0
    if orbital_units > 0 and max_temperature_c is not None:
        orbital = orbital_output(orbital_units, max_temperature_c)

    demand = mine_demand(
        metal_level,
        crystal_level,
        fuel_level,
        metal_draw_bps=metal_draw_bps,
        crystal_draw_bps=crystal_draw_bps,
        fuel_draw_bps=fuel_draw_bps,
    )
    supply = solar + geo + orbital
    ratio = 1.0 if demand <= 0 else max(0.0, min(1.0, supply / demand))
    return EnergyV2Snapshot(
        solar=solar,
        geothermal=geo,
        orbital=orbital,
        total_supply=supply,
        demand=demand,
        ratio=ratio,
    )
