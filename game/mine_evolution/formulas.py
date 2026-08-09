"""Mine Evolution / Ascension balance formulas (EPIC-29 / GC-2905). Server authority only."""

from __future__ import annotations

import math
from typing import Dict, FrozenSet, Tuple

# Production mines only — solar_plant stays on nexus caps.
EVOLVABLE_MINES: FrozenSet[str] = frozenset(
    {"metal_mine", "crystal_mine", "fuel_cell_plant"}
)

MINE_TO_RESOURCE: Dict[str, str] = {
    "metal_mine": "metal",
    "crystal_mine": "crystal",
    "fuel_cell_plant": "fuel_cells",
}

RESOURCE_TO_MINE: Dict[str, str] = {v: k for k, v in MINE_TO_RESOURCE.items()}

# Soft sentinel for EffectResolver / enqueue (not a gameplay wall).
UNCAPPED_BUILDING_LEVEL = 10_000

FIRST_EVOLUTION_LEVEL = 200
EVOLUTION_LEVEL_STEP = 25

TRIBUTE_LOOKBACK_LEVELS = 40
TRIBUTE_FACTOR = 0.25  # 25 % of lookback upgrade costs at the rank milestone

# bonus(rank) = MAX_BONUS_ASYMPTOTE * (1 - exp(-BONUS_K * rank^BONUS_P))
MAX_BONUS_ASYMPTOTE = 0.55
BONUS_K = 0.246
BONUS_P = 0.69


def is_evolvable_mine(building_type: str) -> bool:
    return str(building_type or "") in EVOLVABLE_MINES


def required_level_for_evolution(next_rank: int) -> int:
    """Level required to complete evolution ``next_rank`` (1-based)."""
    n = max(1, int(next_rank or 1))
    return int(FIRST_EVOLUTION_LEVEL + (n - 1) * EVOLUTION_LEVEL_STEP)


def cumulative_production_bonus(rank: int) -> float:
    """Additive production bonus fraction for completed evolutions (0.12 ≈ +12%)."""
    r = max(0, int(rank or 0))
    if r <= 0:
        return 0.0
    return float(MAX_BONUS_ASYMPTOTE * (1.0 - math.exp(-BONUS_K * (float(r) ** BONUS_P))))


def building_modifier_from_rank(rank: int) -> float:
    """Multiplicative factor for ProductionContext.building_modifier."""
    return 1.0 + cumulative_production_bonus(rank)


def tribute_cost_for_next_rank(building_type: str, next_rank: int) -> Tuple[int, int]:
    """
    Metal/crystal tribute for ascending to ``next_rank`` (1-based).

    Milestone-based: sum upgrade costs to reach target levels
    ``(M - LOOKBACK + 1) … M`` where ``M = required_level(next_rank)``, then × 25 %.
    Catch-up at higher current levels pays the same as a milestone purchase.
    """
    from ..buildings import get_upgrade_cost

    if not is_evolvable_mine(building_type):
        return 0, 0
    m_level = required_level_for_evolution(next_rank)
    lookback = int(TRIBUTE_LOOKBACK_LEVELS)
    metal_sum = 0
    crystal_sum = 0
    # Cost to reach target_level = get_upgrade_cost(current = target_level - 1).
    for target_level in range(m_level - lookback + 1, m_level + 1):
        m, c = get_upgrade_cost(str(building_type), int(target_level) - 1)
        metal_sum += int(m)
        crystal_sum += int(c)
    # Exact 0.25 without float precision loss on large ints.
    return metal_sum // 4, crystal_sum // 4


def roman_numeral(rank: int) -> str:
    """Display helper for evolution rank (0 → empty)."""
    n = int(rank or 0)
    if n <= 0:
        return ""
    if n >= 4000:
        return str(n)
    vals = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    out: list[str] = []
    for value, numeral in vals:
        while n >= value:
            out.append(numeral)
            n -= value
    return "".join(out)
