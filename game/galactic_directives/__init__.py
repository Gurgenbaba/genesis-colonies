"""Galactic Directives — galaxy-scoped community politics (GC-720B+)."""

from .banner import build_galactic_directive_banner
from .definitions import (
    DIRECTIVE_KEYS,
    get_directive_definition,
    list_directive_definitions,
    normalize_directive_key,
    reload_definitions,
    schema_ready,
)
from .mechanics import (
    GD_EFFECT_RESOLVER_ADDITIVE_KEYS,
    GD_EFFECT_RESOLVER_ACTIVE_KEYS,
    SECONDARY_SCALE,
    extract_active_effect_resolver_modifiers,
    get_galaxy_directive_mechanics,
    get_directive_flags_for_galaxy,
    get_planet_directive_er_modifiers,
    merge_mechanics,
    scale_numeric_mechanics,
)
from .state import (
    FALLBACK_PRIMARY,
    ensure_galaxy_state,
    get_active_directives_for_galaxy,
    get_player_vote_galaxies,
    list_active_directives_for_galaxies,
    normalize_galaxy,
)
from .voting import (
    build_galaxy_politics_entry,
    get_galactic_politics_state,
    get_or_create_current_cycle,
    get_vote_phase,
    resolve_directive_cycle,
    submit_directive_vote,
)

__all__ = [
    "DIRECTIVE_KEYS",
    "FALLBACK_PRIMARY",
    "GD_EFFECT_RESOLVER_ADDITIVE_KEYS",
    "GD_EFFECT_RESOLVER_ACTIVE_KEYS",
    "SECONDARY_SCALE",
    "build_galactic_directive_banner",
    "extract_active_effect_resolver_modifiers",
    "build_galaxy_politics_entry",
    "ensure_galaxy_state",
    "get_active_directives_for_galaxy",
    "get_directive_definition",
    "get_directive_flags_for_galaxy",
    "get_galactic_politics_state",
    "get_galaxy_directive_mechanics",
    "get_or_create_current_cycle",
    "get_planet_directive_er_modifiers",
    "get_player_vote_galaxies",
    "get_vote_phase",
    "list_active_directives_for_galaxies",
    "resolve_directive_cycle",
    "submit_directive_vote",
    "list_directive_definitions",
    "merge_mechanics",
    "normalize_directive_key",
    "normalize_galaxy",
    "reload_definitions",
    "scale_numeric_mechanics",
    "schema_ready",
]
