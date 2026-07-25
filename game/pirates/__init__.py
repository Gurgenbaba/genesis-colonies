"""Pirate Ecosystem (EPIC-21) — Living Threat owner package.

Heat, factions, bases, threat, bounty, intel, action log, kill-switch.
Fleet send/combat stay in ``fleet.py`` / ``combat.py``. Galaxy attach in ``galaxy.py``.
"""

from __future__ import annotations

from .bounty import add_player_bounty, get_player_bounty, list_player_bounties
from .heat import (
    HEAT_THRESHOLDS,
    get_galaxy_heat,
    heat_band,
    record_heat_event,
    schema_ready as heat_schema_ready,
)
from .log import log_pirate_action, recent_action_log
from .settings import (
    AI_ENABLED_RUNTIME_KEY,
    is_pirates_ai_enabled,
    set_pirates_ai_enabled,
)

__all__ = [
    "AI_ENABLED_RUNTIME_KEY",
    "HEAT_THRESHOLDS",
    "add_player_bounty",
    "get_galaxy_heat",
    "get_player_bounty",
    "heat_band",
    "is_pirates_ai_enabled",
    "list_player_bounties",
    "log_pirate_action",
    "recent_action_log",
    "record_heat_event",
    "set_pirates_ai_enabled",
    "heat_schema_ready",
]
