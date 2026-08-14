"""Stellar Forge / Orbital Shipyard Ascension (EPIC-30) — owner package.

Planet-scoped 4-pillar Ascension campaign for ``orbital_shipyard``. No second
shipyard engine — reads/writes only its own state and layers onto the existing
``game/shipyard.py`` / ``game/shipyard_queue.py`` build queue.
"""

from __future__ import annotations

from .formulas import (
    FORGE_BUILDING,
    OPERATIONAL_PROTOCOLS,
    OPERATIONAL_PROTOCOLS_REQUIRED,
    forge_cores_required,
    hull_mass_target,
    manufacturing_trial_complete,
    operational_target,
    operational_trial_complete,
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
    record_operational_progress,
    schema_ready,
    start_campaign,
)

__all__ = [
    "FORGE_BUILDING",
    "OPERATIONAL_PROTOCOLS",
    "OPERATIONAL_PROTOCOLS_REQUIRED",
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
    "schema_ready",
    "ship_hull_mass",
    "start_campaign",
    "tribute_cost_for_rank",
    "tribute_hours",
]
