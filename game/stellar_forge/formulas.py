"""Stellar Forge / Orbital Shipyard Ascension balance formulas (EPIC-30). Server authority only."""

from __future__ import annotations

import random
from decimal import Decimal, ROUND_FLOOR, localcontext
from typing import Any, Dict, List, Mapping, Sequence

FORGE_BUILDING = "orbital_shipyard"

# --- Pillar 1: Industrial Tribute -------------------------------------------------

TRIBUTE_BASE_HOURS = 24
TRIBUTE_HOURS_STEP = 12
TRIBUTE_WEIGHTS: Dict[str, float] = {"metal": 0.55, "crystal": 0.30, "fuel_cells": 0.15}
TRIBUTE_WEIGHT_RATIOS: Dict[str, tuple[int, int]] = {
    "metal": (55, 100),
    "crystal": (30, 100),
    "fuel_cells": (15, 100),
}


def _mul_div_round_half_even_nonnegative(value: Any, numerator: int, denominator: int) -> int:
    """Exact round-half-even(value * numerator / denominator) for non-negative integers."""
    base = max(0, int(value or 0))
    num = max(0, int(numerator))
    den = int(denominator)
    if den <= 0:
        raise ValueError("denominator must be > 0")
    quotient, remainder = divmod(base * num, den)
    doubled = remainder * 2
    if doubled > den or (doubled == den and quotient % 2):
        quotient += 1
    return quotient


def tribute_hours(rank: int) -> int:
    """Trailing-production window (hours) tributed for ascending to ``rank``."""
    n = max(1, int(rank or 1))
    return int(TRIBUTE_BASE_HOURS + (n - 1) * TRIBUTE_HOURS_STEP)


def tribute_cost_for_rank(rank: int, production_per_hour: Mapping[str, Any]) -> Dict[str, int]:
    """Metal/crystal/fuel_cells tribute — exact production × window × resource weight."""
    hours = tribute_hours(rank)
    out: Dict[str, int] = {}
    for resource, (weight_num, weight_den) in TRIBUTE_WEIGHT_RATIOS.items():
        rate = max(0, int(production_per_hour.get(resource, 0) or 0))
        out[resource] = _mul_div_round_half_even_nonnegative(
            rate * hours,
            weight_num,
            weight_den,
        )
    return out


# --- Pillar 2: Manufacturing Trial (Hull Mass) ------------------------------------

# GC-endgame-shipyard-speed: raised ~50,000x from the original 2,000,000 base —
# the Stellar Forge batch-capacity scaling (see shipyard.forge_capacity_multiplier)
# lets endgame yards blow past a million-scale target within a single production
# cycle, which made the Manufacturing Trial complete instantly instead of being a
# real multi-hour challenge.
HULL_MASS_BASE = 100_000_000_000
HULL_MASS_STEP = 50_000_000_000
HULL_MASS_MIN_ROLES = 3
HULL_MASS_FUEL_CELL_WEIGHT = 3

# Ship categories eligible to be rolled as a campaign's 3 required categories.
# Excludes "colony" — colony ships (seed_ark) are meant to stay rare/limited-
# purpose, not mass-produced for a Hull Mass grind.
MANUFACTURING_ROLE_POOL: Sequence[str] = (
    "cargo", "combat", "expedition", "expedition_combat", "recycle", "scout", "siege", "spy",
)
MANUFACTURING_REQUIRED_ROLE_COUNT = 3


def hull_mass_target(rank: int) -> int:
    n = max(1, int(rank or 1))
    return int(HULL_MASS_BASE + (n - 1) * HULL_MASS_STEP)


def ship_hull_mass(build_cost: Mapping[str, int]) -> int:
    """Hull Mass contributed per unit — build_cost value with fuel_cells weighted 3x."""
    metal = int(build_cost.get("metal") or 0)
    crystal = int(build_cost.get("crystal") or 0)
    fuel = int(build_cost.get("fuel_cells") or 0)
    return metal + crystal + fuel * HULL_MASS_FUEL_CELL_WEIGHT


def roll_manufacturing_roles() -> List[str]:
    """Pick this campaign's 3 required ship categories at random (GC-3009)."""
    picked = random.sample(list(MANUFACTURING_ROLE_POOL), MANUFACTURING_REQUIRED_ROLE_COUNT)
    return sorted(picked)


def manufacturing_trial_complete(
    total: int,
    rank: int,
    by_role: Mapping[str, int],
    required_roles: Sequence[str] | None = None,
) -> bool:
    """Total target reached, and each of the campaign's required categories was built.

    No per-role cap — ship unit costs vary too much by tier (e.g. a capital
    combat hull can be 10x+ the Hull Mass of a scout/cargo unit of the same
    quantity) for a flat 60%-of-total ceiling to be a fair "diversify your
    production" signal. Diversity is instead enforced by requiring production
    in 3 specific categories, rolled randomly per campaign (GC-3009) — a
    player can't just pick whichever 3 are cheapest/already stocked.

    Falls back to "any 3 distinct roles" when ``required_roles`` is empty
    (campaigns started before this rolled-categories feature shipped).
    """
    target = hull_mass_target(rank)
    if total < target:
        return False
    roles = list(required_roles or [])
    if roles:
        return all(int(by_role.get(r, 0) or 0) > 0 for r in roles)
    contributing_roles = [v for v in by_role.values() if v > 0]
    return len(contributing_roles) >= HULL_MASS_MIN_ROLES


# --- Pillar 3: Operational Trial ---------------------------------------------------

OPERATIONAL_PROTOCOLS = ("exploration", "salvage", "warfare", "titan", "logistics")
OPERATIONAL_PROTOCOLS_REQUIRED = 3

OPERATIONAL_TARGETS_BASE: Dict[str, int] = {
    "exploration": 10,             # completed expedition missions
    # salvage/warfare/logistics are resource-value protocols, raised x1000
    # alongside Hull Mass (GC-endgame-shipyard-speed) so they stay a real
    # challenge against endgame production/combat output.
    "salvage": 5_000_000_000,      # resource value harvested from debris fields
    "warfare": 5_000_000_000,      # enemy fleet value destroyed in combat
    "titan": 2_000_000,            # damage dealt to a World Boss
    "logistics": 10_000_000_000,   # resources transported between own colonies
}


def operational_target(protocol: str, rank: int) -> int:
    base = int(OPERATIONAL_TARGETS_BASE.get(protocol, 0))
    n = max(1, int(rank or 1))
    # Exact equivalent of round(base * (1 + 0.5 * (n - 1))) without
    # converting an unbounded Forge rank through IEEE-754.
    numerator = base * (n + 1)
    quotient, remainder = divmod(numerator, 2)
    if remainder and quotient % 2:
        quotient += 1
    return quotient


def operational_trial_complete(protocols_done: set) -> bool:
    return len({p for p in protocols_done if p in OPERATIONAL_PROTOCOLS}) >= OPERATIONAL_PROTOCOLS_REQUIRED


# --- Pillar 4: Forge Cores ----------------------------------------------------------

FORGE_CORES_BASE = 8
FORGE_CORES_STEP = 6

# Alt-source (GC-3010): Recycler/wreckage salvage hauls, in addition to
# Expedition legendary events and World Boss kills. Scales with haul SIZE
# (fraction of a billion collected) rather than a fixed absolute threshold,
# so it doesn't need re-tuning every time the economy inflates further.
# Capped so one huge recycle run isn't a guaranteed farm.
SALVAGE_FORGE_CORE_CHANCE_PER_BILLION = 0.03
SALVAGE_FORGE_CORE_CHANCE_MAX = 0.35


def forge_cores_required(rank: int) -> int:
    n = max(1, int(rank or 1))
    return int(FORGE_CORES_BASE + (n - 1) * FORGE_CORES_STEP)


# --- Rank rewards --------------------------------------------------------------------

def queue_slot_bonus(rank: int) -> int:
    """Extra shipyard queue slots granted by completed Forge ranks (Rank I+)."""
    return 1 if int(rank or 0) >= 1 else 0


# Each completed Forge rank adds +150% to the yard's production batch capacity
# (ships built per production cycle), stacking additively on top of the base
# level-50 capacity. Calibrated so Rank X (1 + 10*1.5 = 16x) plus a Level 50
# yard clears the ~130k ships/cycle needed to build 300M ships in ~4-5h —
# see docs/STELLAR_FORGE.md for the full derivation.
FORGE_CAPACITY_BONUS_PER_RANK = 1.5
FORGE_CAPACITY_BONUS_NUMERATOR = 3
FORGE_CAPACITY_BONUS_DENOMINATOR = 2


def forge_capacity_ratio(rank: int) -> tuple[int, int]:
    """Exact multiplier ratio for 1 + rank * 1.5."""
    n = max(0, int(rank or 0))
    return (
        FORGE_CAPACITY_BONUS_DENOMINATOR + n * FORGE_CAPACITY_BONUS_NUMERATOR,
        FORGE_CAPACITY_BONUS_DENOMINATOR,
    )


def forge_capacity_scaled_floor(base_value: Any, rank: int) -> int:
    """floor(base_value * Forge multiplier) with precision for both operands."""
    numerator, denominator = forge_capacity_ratio(rank)
    base = base_value if isinstance(base_value, Decimal) else Decimal(str(base_value))
    if not base.is_finite() or base <= 0:
        return 0

    base_digits = max(
        1,
        len(base.as_tuple().digits),
        base.adjusted() + 1,
    )
    numerator_digits = max(1, (abs(int(numerator)).bit_length() * 30103) // 100000 + 1)
    with localcontext() as ctx:
        ctx.prec = max(128, base_digits + numerator_digits + 64)
        result = base * Decimal(numerator) / Decimal(denominator)
        return int(result.to_integral_value(rounding=ROUND_FLOOR))


def forge_capacity_multiplier(rank: int) -> float | str:
    """UI-compatible multiplier; huge ranks fall back to exact decimal text."""
    numerator, denominator = forge_capacity_ratio(rank)
    if numerator.bit_length() <= 1020:
        return float(numerator) / float(denominator)
    whole, remainder = divmod(numerator, denominator)
    if remainder == 0:
        return str(whole)
    return f"{whole}.5"


def nanite_assist_unlocked(rank: int) -> bool:
    return int(rank or 0) >= 2


NANITE_ASSIST_SPEED_BONUS = 0.25
NANITE_ASSIST_FUEL_CELL_SURCHARGE = 0.35


def specialization_unlocked(rank: int) -> bool:
    """Rank III+ unlocks the Forge Specialization slot (Phase 2 — docs-only until built)."""
    return int(rank or 0) >= 3
