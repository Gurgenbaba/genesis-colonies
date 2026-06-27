"""Imperial Directives — player High Command objectives (EPIC-17)."""

from __future__ import annotations

from .definitions import (
    DAILY_DIRECTIVE_COUNT,
    WEEKLY_DIRECTIVE_COUNT,
    directives_schema_ready,
    get_definition,
    list_definitions_for_cadence,
)
from .generator import (
    daily_expires_at,
    daily_period_key,
    ensure_player_directives,
    weekly_expires_at,
    weekly_period_key,
)
from .progress import apply_directive_events
from .rewards import claim_all_directive_rewards, claim_directive_reward
from .scaling import compute_scaled_target, scale_profile_config
from .balancing import compute_directive_target, directive_hard_cap, is_directive_target_stale
from .service import get_imperial_directives_state, get_imperial_directives_summary

__all__ = [
    "DAILY_DIRECTIVE_COUNT",
    "WEEKLY_DIRECTIVE_COUNT",
    "apply_directive_events",
    "claim_all_directive_rewards",
    "claim_directive_reward",
    "compute_directive_target",
    "compute_scaled_target",
    "daily_expires_at",
    "daily_period_key",
    "directives_schema_ready",
    "directive_hard_cap",
    "ensure_player_directives",
    "get_definition",
    "get_imperial_directives_state",
    "get_imperial_directives_summary",
    "is_directive_target_stale",
    "list_definitions_for_cadence",
    "scale_profile_config",
    "weekly_expires_at",
    "weekly_period_key",
]
