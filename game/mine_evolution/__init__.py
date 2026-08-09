"""Mine Evolution / Industrial Ascension (EPIC-29) — owner package.

Planet-scoped Ascension for production mines. Production bonus via
``ProductionContext.building_modifier`` (no second production engine).
"""

from __future__ import annotations

from .formulas import (
    EVOLVABLE_MINES,
    FIRST_EVOLUTION_LEVEL,
    EVOLUTION_LEVEL_STEP,
    MINE_TO_RESOURCE,
    RESOURCE_TO_MINE,
    TRIBUTE_FACTOR,
    TRIBUTE_LOOKBACK_LEVELS,
    UNCAPPED_BUILDING_LEVEL,
    building_modifier_from_rank,
    cumulative_production_bonus,
    is_evolvable_mine,
    required_level_for_evolution,
    roman_numeral,
    tribute_cost_for_next_rank,
)
from .service import (
    building_modifier_for,
    evolve_mine,
    get_evolution_rank,
    get_evolution_ranks_for_planet,
    panel_evolution_fields,
    schema_ready,
)

__all__ = [
    "EVOLVABLE_MINES",
    "FIRST_EVOLUTION_LEVEL",
    "EVOLUTION_LEVEL_STEP",
    "MINE_TO_RESOURCE",
    "RESOURCE_TO_MINE",
    "TRIBUTE_FACTOR",
    "TRIBUTE_LOOKBACK_LEVELS",
    "UNCAPPED_BUILDING_LEVEL",
    "building_modifier_for",
    "building_modifier_from_rank",
    "cumulative_production_bonus",
    "evolve_mine",
    "get_evolution_rank",
    "get_evolution_ranks_for_planet",
    "is_evolvable_mine",
    "panel_evolution_fields",
    "required_level_for_evolution",
    "roman_numeral",
    "schema_ready",
    "tribute_cost_for_next_rank",
]
