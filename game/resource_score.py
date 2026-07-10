"""
Canonical resource-to-score conversion (GC-SCORE-A).

Single source of truth for ranking, trader neutrality checks, and asset valuation.
Points = normalized total resource wealth at fixed 3:2:1 divisors (aligned with production).
"""

from __future__ import annotations

from typing import Any, Mapping

from .production_formula import STANDARD_PRODUCTION_PER_HOUR

# 3:2:1 — same ratio as STANDARD_PRODUCTION_PER_HOUR (15000 : 10000 : 5000).
SCORE_METAL_DIVISOR = 1500
SCORE_CRYSTAL_DIVISOR = 1000
SCORE_FUEL_DIVISOR = 500

RESOURCE_SCORE_DIVISORS: dict[str, int] = {
    "metal": SCORE_METAL_DIVISOR,
    "crystal": SCORE_CRYSTAL_DIVISOR,
    "fuel_cells": SCORE_FUEL_DIVISOR,
}


def _safe_amount(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def score_from_resources(
    metal: int = 0,
    crystal: int = 0,
    fuel_cells: int = 0,
) -> int:
    """
    Integer score points from raw resource amounts.

    Each resource is floored independently before summing:
    metal/1500 + crystal/1000 + fuel_cells/500.
    """
    m = _safe_amount(metal)
    c = _safe_amount(crystal)
    f = _safe_amount(fuel_cells)
    return (
        m // SCORE_METAL_DIVISOR
        + c // SCORE_CRYSTAL_DIVISOR
        + f // SCORE_FUEL_DIVISOR
    )


def normalize_cost_dict(raw: Mapping[str, Any] | None) -> dict[str, int]:
    """Normalize build_cost / stock mapping to non-negative integer metal/crystal/fuel_cells."""
    src = raw or {}
    return {
        "metal": _safe_amount(src.get("metal")),
        "crystal": _safe_amount(src.get("crystal")),
        "fuel_cells": _safe_amount(src.get("fuel_cells")),
    }


def score_from_cost_dict(cost: Mapping[str, Any] | None) -> int:
    """Score from a cost or resource dict with metal, crystal, and fuel_cells keys."""
    normalized = normalize_cost_dict(cost)
    return score_from_resources(
        normalized["metal"],
        normalized["crystal"],
        normalized["fuel_cells"],
    )


def add_score_from_cost_dicts(*costs: Mapping[str, Any] | None) -> int:
    """Sum score points from multiple cost dicts (e.g. cumulative upgrade levels)."""
    total_metal = 0
    total_crystal = 0
    total_fuel = 0
    for cost in costs:
        normalized = normalize_cost_dict(cost)
        total_metal += normalized["metal"]
        total_crystal += normalized["crystal"]
        total_fuel += normalized["fuel_cells"]
    return score_from_resources(total_metal, total_crystal, total_fuel)


def score_neutral_exchange_rates() -> dict[str, float]:
    """
    Score-equivalent cross-rates for trader validation (GC-SCORE-F).

    Returns how many units of the target resource one unit of the source is worth
    at the canonical 3:2:1 score basis.
    """
    metal_per_crystal = SCORE_METAL_DIVISOR / SCORE_CRYSTAL_DIVISOR  # 1.5
    metal_per_fuel = SCORE_METAL_DIVISOR / SCORE_FUEL_DIVISOR  # 3.0
    crystal_per_fuel = SCORE_CRYSTAL_DIVISOR / SCORE_FUEL_DIVISOR  # 2.0
    return {
        "metal_per_crystal": metal_per_crystal,
        "crystal_per_metal": SCORE_CRYSTAL_DIVISOR / SCORE_METAL_DIVISOR,
        "metal_per_fuel_cell": metal_per_fuel,
        "fuel_cell_per_metal": SCORE_FUEL_DIVISOR / SCORE_METAL_DIVISOR,
        "crystal_per_fuel_cell": crystal_per_fuel,
        "fuel_cell_per_crystal": SCORE_FUEL_DIVISOR / SCORE_CRYSTAL_DIVISOR,
    }


def production_ratio_matches_score_divisors() -> bool:
    """True when score divisors preserve the production 3:2:1 ratio."""
    metal = float(STANDARD_PRODUCTION_PER_HOUR["metal"])
    crystal = float(STANDARD_PRODUCTION_PER_HOUR["crystal"])
    fuel = float(STANDARD_PRODUCTION_PER_HOUR["fuel_cells"])
    if metal <= 0 or crystal <= 0 or fuel <= 0:
        return False
    return (
        SCORE_METAL_DIVISOR / metal
        == SCORE_CRYSTAL_DIVISOR / crystal
        == SCORE_FUEL_DIVISOR / fuel
    )
