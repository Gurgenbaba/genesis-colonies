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
    list_active_directives_for_galaxies,
    normalize_galaxy,
)

__all__ = [
    "DIRECTIVE_KEYS",
    "FALLBACK_PRIMARY",
    "GD_EFFECT_RESOLVER_ADDITIVE_KEYS",
    "GD_EFFECT_RESOLVER_ACTIVE_KEYS",
    "SECONDARY_SCALE",
    "build_galactic_directive_banner",
    "extract_active_effect_resolver_modifiers",
    "ensure_galaxy_state",
    "get_active_directives_for_galaxy",
    "get_directive_definition",
    "get_directive_flags_for_galaxy",
    "get_galaxy_directive_mechanics",
    "get_planet_directive_er_modifiers",
    "list_active_directives_for_galaxies",
    "list_directive_definitions",
    "merge_mechanics",
    "normalize_directive_key",
    "normalize_galaxy",
    "reload_definitions",
    "scale_numeric_mechanics",
    "schema_ready",
]
