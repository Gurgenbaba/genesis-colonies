"""
Central gameplay effect calculation for Genesis Colonies.
"""

from .effect_resolver import (
    ACTIVE_MODIFIER_KEYS,
    PREPARED_MODIFIER_KEYS,
    EffectResolver,
    clear_effect_resolver_cache,
    get_effect_resolver,
)
from .endgame_v2_runtime import install_endgame_v2_research_tail

# Endgame Economy V2: make the production-research diminishing tail authoritative
# for every EffectResolver import path (package and direct submodule imports).
# The bridge is a no-op in legacy/shadow mode.
install_endgame_v2_research_tail(EffectResolver)

__all__ = [
    "EffectResolver",
    "get_effect_resolver",
    "clear_effect_resolver_cache",
    "ACTIVE_MODIFIER_KEYS",
    "PREPARED_MODIFIER_KEYS",
]
