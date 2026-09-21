"""Ascension Breakthrough V2 long-horizon balance simulator.

This is intentionally a curve comparison, not a player forecast:
- one Ferronit mine
- all generated value is reinvested into that same mine
- neutral modifiers except the selected Ascension production multiplier
- upgrade cost uses the live power_upgrade_cost owner
- build queue duration, other planets, research, loot and storage are excluded

The simulator pins the UNI1 q4 rollout locally and restores process globals afterwards.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import sys
from typing import Dict, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game import production_formula as pf
from game.economy_balance import power_upgrade_cost


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    start_level: int = 200
    tail_bonus_hundredths: int = 0
    production_multiplier: Decimal = Decimal("1")
    rebuild_best_depth: int = 0
    rebuild_window_levels: int = 0
    rebuild_cost_multiplier: Decimal = Decimal("1")
    rebuild_production_multiplier: Decimal = Decimal("1")


SCENARIOS = (
    Scenario("baseline_q4", "Baseline q4"),
    Scenario("current_stack", "q4 + current +40%", production_multiplier=Decimal("1.40")),
    Scenario("core_resonance", "Core Resonance q4.10", tail_bonus_hundredths=10),
    Scenario("singularity", "Singularity q4.20", tail_bonus_hundredths=20),
    Scenario(
        "singularity_stack",
        "q4.20 + current +40%",
        tail_bonus_hundredths=20,
        production_multiplier=Decimal("1.40"),
    ),
    Scenario(
        "current_max_rebuild",
        "Current max rebuild from L130",
        start_level=130,
        production_multiplier=Decimal("1.40"),
        rebuild_best_depth=500,
        rebuild_cost_multiplier=Decimal("0.54"),
    ),
    Scenario(
        "breakthrough_full",
        "Full Breakthrough V3 from L130 +30% rebuild surge",
        start_level=130,
        tail_bonus_hundredths=20,
        production_multiplier=Decimal("1.40"),
        rebuild_best_depth=500,
        rebuild_window_levels=25,
        rebuild_cost_multiplier=Decimal("0.54"),
        rebuild_production_multiplier=Decimal("1.30"),
    ),
)


@contextmanager
def uni1_q4_curve():
    previous = (
        pf.ENDGAME_ECONOMY_MODE,
        pf.ENDGAME_PRODUCTION_PIVOT_LEVEL,
        pf.ENDGAME_PRODUCTION_TAIL_POWER,
    )
    pf.ENDGAME_ECONOMY_MODE = "active"
    pf.ENDGAME_PRODUCTION_PIVOT_LEVEL = 120
    pf.ENDGAME_PRODUCTION_TAIL_POWER = 4
    try:
        yield
    finally:
        (
            pf.ENDGAME_ECONOMY_MODE,
            pf.ENDGAME_PRODUCTION_PIVOT_LEVEL,
            pf.ENDGAME_PRODUCTION_TAIL_POWER,
        ) = previous


def production_value_per_hour(level: int, scenario: Scenario) -> Decimal:
    mine = pf.mine_output_decimal(
        "metal",
        int(level),
        tail_power_bonus_hundredths=int(scenario.tail_bonus_hundredths),
    )
    standard = pf.standard_output_decimal("metal")
    rebuild_limit = int(scenario.rebuild_best_depth) + int(scenario.rebuild_window_levels)
    rebuild_prod = Decimal("1")
    if rebuild_limit > 0 and int(level) <= rebuild_limit:
        rebuild_prod = Decimal(scenario.rebuild_production_multiplier)
    return (standard + mine * rebuild_prod) * Decimal(scenario.production_multiplier)


def upgrade_value_cost(target_level: int, scenario: Scenario) -> Decimal:
    metal, crystal = power_upgrade_cost("metal_mine", int(target_level))
    total = Decimal(int(metal) + int(crystal))
    rebuild_limit = int(scenario.rebuild_best_depth) + int(scenario.rebuild_window_levels)
    if rebuild_limit > 0 and int(target_level) <= rebuild_limit:
        total *= Decimal(scenario.rebuild_cost_multiplier)
    return total


def hours_to_target(scenario: Scenario, target_level: int) -> Decimal:
    if int(target_level) <= int(scenario.start_level):
        return Decimal(0)
    elapsed = Decimal(0)
    level = int(scenario.start_level)
    while level < int(target_level):
        hourly = production_value_per_hour(level, scenario)
        if hourly <= 0:
            raise RuntimeError("non-positive production")
        elapsed += upgrade_value_cost(level + 1, scenario) / hourly
        level += 1
    return elapsed


def level_after_days(scenario: Scenario, days: Decimal | int | float) -> int:
    budget_hours = Decimal(str(days)) * Decimal(24)
    elapsed = Decimal(0)
    level = int(scenario.start_level)
    while True:
        hourly = production_value_per_hour(level, scenario)
        if hourly <= 0:
            return level
        step = upgrade_value_cost(level + 1, scenario) / hourly
        if elapsed + step > budget_hours:
            return level
        elapsed += step
        level += 1


def run_horizons(
    scenarios: Iterable[Scenario] = SCENARIOS,
    *,
    horizons_days: Iterable[Decimal | int | float] = (Decimal("182.5"), Decimal("365")),
) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    with uni1_q4_curve():
        for scenario in scenarios:
            out[scenario.key] = {
                f"{Decimal(str(days)):g}d": level_after_days(scenario, days)
                for days in horizons_days
            }
    return out


def main() -> None:
    with uni1_q4_curve():
        results = run_horizons()
        print("Scenario | Start | 6 months | 12 months | Days to L300 | Days to L500")
        print("--- | ---: | ---: | ---: | ---: | ---:")
        for scenario in SCENARIOS:
            row = results[scenario.key]
            to300 = hours_to_target(scenario, 300) / Decimal(24)
            to500 = hours_to_target(scenario, 500) / Decimal(24)
            print(
                f"{scenario.label} | L{scenario.start_level} | "
                f"L{row['182.5d']} | L{row['365d']} | "
                f"{to300:.1f} | {to500:.1f}"
            )


if __name__ == "__main__":
    main()
