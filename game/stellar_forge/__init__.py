"""Stellar Forge / Orbital Shipyard Ascension (EPIC-30) — owner package.

Planet-scoped 4-pillar Ascension campaign for ``orbital_shipyard``. No second
shipyard engine — reads/writes only its own state and layers onto the existing
``game/shipyard.py`` / ``game/shipyard_queue.py`` build queue.
"""

from __future__ import annotations

from .formulas import (
    FORGE_BUILDING,
    MANUFACTURING_ROLE_POOL,
    MANUFACTURING_REQUIRED_ROLE_COUNT,
    OPERATIONAL_PROTOCOLS,
    OPERATIONAL_PROTOCOLS_REQUIRED,
    SALVAGE_FORGE_CORE_CHANCE_MAX,
    SALVAGE_FORGE_CORE_CHANCE_PER_BILLION,
    forge_cores_required,
    hull_mass_target,
    manufacturing_trial_complete,
    operational_target,
    operational_trial_complete,
    roll_manufacturing_roles,
    ship_hull_mass,
    tribute_cost_for_rank,
    tribute_hours,
)
from .service import (
    ascend,
    get_forge_cores,
    get_raw_state,
    grant_forge_cores,
    is_unlocked,
    panel_forge_fields,
    pay_tribute,
    record_hull_mass_delivery,
    schema_ready,
    start_campaign,
)
from .safe_hooks import record_operational_progress

__all__ = [
    "FORGE_BUILDING",
    "MANUFACTURING_ROLE_POOL",
    "MANUFACTURING_REQUIRED_ROLE_COUNT",
    "OPERATIONAL_PROTOCOLS",
    "OPERATIONAL_PROTOCOLS_REQUIRED",
    "SALVAGE_FORGE_CORE_CHANCE_MAX",
    "SALVAGE_FORGE_CORE_CHANCE_PER_BILLION",
    "ascend",
    "forge_cores_required",
    "get_forge_cores",
    "get_raw_state",
    "grant_forge_cores",
    "hull_mass_target",
    "is_unlocked",
    "manufacturing_trial_complete",
    "operational_target",
    "operational_trial_complete",
    "panel_forge_fields",
    "pay_tribute",
    "record_hull_mass_delivery",
    "record_operational_progress",
    "roll_manufacturing_roles",
    "schema_ready",
    "ship_hull_mass",
    "start_campaign",
    "tribute_cost_for_rank",
    "tribute_hours",
]
