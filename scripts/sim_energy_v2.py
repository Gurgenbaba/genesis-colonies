"""Energy V2 research simulator.

Candidate only — zero live gameplay changes.

The goal is to preserve Genesis' long-level power-law energy scale while
copying the *decision structure* that makes OGame-style energy interesting:
a stable ground source, a research-scaling secondary source, and a
temperature-sensitive orbital source.

Legacy values are read from EffectResolver so this tool stays honest about the
currently shipped game.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Dict, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.effects import EffectResolver
from game.planet_visuals import temperature_range_for_position

from game.energy_v2 import (
    candidate_snapshot,
    geothermal_output as candidate_geothermal_output,
    orbital_output_per_unit,
    solar_output as candidate_solar_output,
)

BENCHMARK_LEVELS = (50, 100, 200, 300, 500, 650, 1000)
BENCHMARK_SLOTS = (1, 8, 15)
BENCHMARK_TECHS = (0, 20, 50)

def candidate_orbital_output_per_unit(slot: int) -> int:
    """Slot wrapper around the canonical temperature-based candidate helper."""
    temp = temperature_range_for_position(int(slot))
    return orbital_output_per_unit(int(temp["max_c"]))




def candidate_ratio(
    mine_level: int,
    *,
    solar_level: int,
    geothermal_level: int = 0,
    energy_tech: int = 0,
    orbital_units: int = 0,
    slot: int = 8,
    ascension_draw_bps: int = 10000,
) -> float:
    temp = temperature_range_for_position(int(slot))
    snap = candidate_snapshot(
        metal_level=mine_level,
        crystal_level=mine_level,
        fuel_level=mine_level,
        solar_level=solar_level,
        geothermal_level=geothermal_level,
        energy_tech=energy_tech,
        orbital_units=orbital_units,
        max_temperature_c=int(temp["max_c"]),
        metal_draw_bps=ascension_draw_bps,
        crystal_draw_bps=ascension_draw_bps,
        fuel_draw_bps=ascension_draw_bps,
    )
    return snap.ratio


def required_solar_level(
    mine_level: int,
    *,
    geothermal_level: int = 0,
    energy_tech: int = 0,
    orbital_units: int = 0,
    slot: int = 8,
    ascension_draw_bps: int = 10000,
) -> int:
    """Small deterministic search; candidate Solar is monotonic and unbounded."""
    mine = max(0, int(mine_level or 0))
    if mine <= 0:
        return 0
    limit = max(mine + 100, int(math.ceil(mine * 1.6)) + 10)
    for solar in range(0, limit + 1):
        if candidate_ratio(
            mine,
            solar_level=solar,
            geothermal_level=geothermal_level,
            energy_tech=energy_tech,
            orbital_units=orbital_units,
            slot=slot,
            ascension_draw_bps=ascension_draw_bps,
        ) >= 1.0:
            return solar
    raise RuntimeError(f"solar search exceeded candidate guardrail for L{mine}")


def legacy_ratio(level: int, *, energy_tech: int, slot: int) -> float:
    buildings = {
        "metal_mine": int(level),
        "crystal_mine": int(level),
        "fuel_cell_plant": int(level),
        "solar_plant": int(level),
    }
    er = EffectResolver(
        buildings,
        {"energy_tech": int(energy_tech)},
        planet_position=int(slot),
    )
    total, used = er.compute_energy()
    return er.energy_ratio(total, used)


def run_matrix(
    levels: Iterable[int] = BENCHMARK_LEVELS,
    slots: Iterable[int] = BENCHMARK_SLOTS,
    techs: Iterable[int] = BENCHMARK_TECHS,
) -> list[Dict[str, float | int]]:
    rows: list[Dict[str, float | int]] = []
    for level in levels:
        for tech in techs:
            for slot in slots:
                rows.append(
                    {
                        "level": int(level),
                        "energy_tech": int(tech),
                        "slot": int(slot),
                        "legacy_same_level_ratio": round(
                            legacy_ratio(level, energy_tech=tech, slot=slot), 4
                        ),
                        "v2_same_level_ratio": round(
                            candidate_ratio(level, solar_level=level, energy_tech=tech, slot=slot),
                            4,
                        ),
                        "v2_required_solar": required_solar_level(
                            level,
                            energy_tech=tech,
                            slot=slot,
                        ),
                        "orbital_energy_each": candidate_orbital_output_per_unit(slot),
                    }
                )
    return rows


def main() -> None:
    rows = run_matrix()
    print(
        "Level | E-Tech | Slot | Legacy same-level | V2 same-level | "
        "V2 Solar for 100% | Orbital/unit"
    )
    print("---: | ---: | ---: | ---: | ---: | ---: | ---:")
    for row in rows:
        print(
            f"L{row['level']} | {row['energy_tech']} | {row['slot']} | "
            f"{row['legacy_same_level_ratio']:.3f} | "
            f"{row['v2_same_level_ratio']:.3f} | "
            f"L{row['v2_required_solar']} | {row['orbital_energy_each']}"
        )

    print("\nEnergy-Tech / Geothermal role example (mine L300, solar L300, geo L50):")
    for tech in BENCHMARK_TECHS:
        ratio = candidate_ratio(
            300,
            solar_level=300,
            geothermal_level=50,
            energy_tech=tech,
            slot=8,
        )
        print(
            f"E-Tech {tech}: geo={candidate_geothermal_output(50, tech):,} "
            f"grid={ratio*100:.1f}%"
        )


if __name__ == "__main__":
    main()
