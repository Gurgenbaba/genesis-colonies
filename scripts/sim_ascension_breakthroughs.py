"""Ascension Breakthrough V2 long-horizon balance simulator.

The primary table is intentionally a curve comparison, not a player forecast:
- one Ferronit mine
- all generated value is reinvested into that same mine
- neutral modifiers except the selected Ascension production multiplier
- upgrade cost uses the live power_upgrade_cost owner

A second stress path models the exact Ferdi concern: up to 11 mature feeder worlds
pooling their full value production into one record mine. That path also applies
the canonical mine queue floor, so it provides an aggressive upper bound rather
than a casual-player forecast.

The simulator pins the UNI1 q3 rollout locally and restores process globals afterwards.
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
from game.time_floors import building_progress_floor_seconds


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
    Scenario("baseline_q3", "Baseline q3"),
    Scenario("current_stack", "q3 + current +40%", production_multiplier=Decimal("1.40")),
    Scenario("core_resonance", "Core Resonance q3.15", tail_bonus_hundredths=15),
    Scenario("singularity", "Singularity q3.30", tail_bonus_hundredths=30),
    Scenario(
        "singularity_stack",
        "q3.30 + current +40%",
        tail_bonus_hundredths=30,
        production_multiplier=Decimal("1.40"),
    ),
    Scenario(
        "current_max_rebuild",
        "Current max rebuild from L156",
        start_level=156,
        production_multiplier=Decimal("1.40"),
        rebuild_best_depth=500,
        rebuild_cost_multiplier=Decimal("0.375"),
    ),
    Scenario(
        "breakthrough_full",
        "Full Breakthrough V4 from L156 +100% rebuild surge",
        start_level=156,
        tail_bonus_hundredths=30,
        production_multiplier=Decimal("1.40"),
        rebuild_best_depth=500,
        rebuild_window_levels=50,
        rebuild_cost_multiplier=Decimal("0.375"),
        rebuild_production_multiplier=Decimal("2.00"),
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
    pf.ENDGAME_PRODUCTION_TAIL_POWER = 3
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


def pooled_empire_level_after_days(
    scenario: Scenario,
    days: Decimal | int | float,
    *,
    feeder_worlds: int = 11,
) -> int:
    """Aggressive record-push ceiling with all mature worlds funding one mine.

    Every feeder is assumed to magically keep the record mine's current output,
    and every unit of generated value is spendable on the target upgrade. The
    only non-resource constraint is the canonical server queue floor. Real
    accounts lose value to other buildings, research, fleet, storage and feeder
    progression, so they can only be slower than this stress path.
    """
    worlds = max(1, int(feeder_worlds))
    budget_hours = Decimal(str(days)) * Decimal(24)
    elapsed = Decimal(0)
    level = int(scenario.start_level)
    while True:
        hourly = production_value_per_hour(level, scenario) * Decimal(worlds)
        if hourly <= 0:
            return level
        target = level + 1
        resource_hours = upgrade_value_cost(target, scenario) / hourly
        queue_hours = Decimal(
            building_progress_floor_seconds("metal_mine", target)
        ) / Decimal(3600)
        step = max(resource_hours, queue_hours)
        if elapsed + step > budget_hours:
            return level
        elapsed += step
        level = target


def queue_floor_level_after_days(
    days: Decimal | int | float,
    *,
    start_level: int = 200,
) -> int:
    """Absolute mine ceiling for the period if upgrades cost zero resources."""
    budget_seconds = Decimal(str(days)) * Decimal(86400)
    elapsed = Decimal(0)
    level = max(0, int(start_level))
    while True:
        target = level + 1
        step = Decimal(building_progress_floor_seconds("metal_mine", target))
        if elapsed + step > budget_seconds:
            return level
        elapsed += step
        level = target


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

        stress = next(row for row in SCENARIOS if row.key == "singularity_stack")
        print()
        print("Empire-pooling stress (11 mature feeder worlds → one record mine)")
        print(
            "6 months: "
            f"L{pooled_empire_level_after_days(stress, Decimal('182.5'), feeder_worlds=11)} "
            f"(zero-cost queue ceiling L{queue_floor_level_after_days(Decimal('182.5'))})"
        )
        print(
            "12 months: "
            f"L{pooled_empire_level_after_days(stress, Decimal('365'), feeder_worlds=11)} "
            f"(zero-cost queue ceiling L{queue_floor_level_after_days(Decimal('365'))})"
        )


if __name__ == "__main__":
    main()
