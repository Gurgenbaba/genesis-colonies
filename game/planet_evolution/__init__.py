"""Planet Specialization & Evolution System for Genesis Colonies."""

from .bootstrap import ensure_planet_evolution, backfill_all_planets_evolution
from .service import (
    get_planet_state_payload,
    set_active_planet,
    pick_specialization,
    upgrade_specialization_tier,
    make_locked_choice,
    activate_policy,
    resolve_event_choice,
    create_trade_route,
    delete_trade_route,
    start_ascension,
    colonize_planet,
    list_player_planets,
)

__all__ = [
    "ensure_planet_evolution",
    "backfill_all_planets_evolution",
    "get_planet_state_payload",
    "set_active_planet",
    "pick_specialization",
    "upgrade_specialization_tier",
    "make_locked_choice",
    "activate_policy",
    "resolve_event_choice",
    "create_trade_route",
    "delete_trade_route",
    "start_ascension",
    "colonize_planet",
    "list_player_planets",
]
