"""Runtime bridge for Endgame Economy V2 production-research diminishing returns.

The canonical production formula already applies the V2 research tail in active mode,
but EffectResolver historically materialized the raw linear research factors before
production_formula removes that research part from the overlay.  This bridge corrects
the cached production modifier bundle in active mode so every downstream consumer sees
the same diminished research factor and production_formula no longer cancels it out.

Shadow/legacy modes remain byte-for-byte gameplay compatible.
"""

from __future__ import annotations

from typing import Any


def install_endgame_v2_research_tail(effect_resolver_cls: Any) -> None:
    """Patch EffectResolver.get_modifiers once, preserving legacy/shadow behavior."""
    if bool(getattr(effect_resolver_cls, "_gc_endgame_v2_research_tail_installed", False)):
        return

    original = effect_resolver_cls.get_modifiers

    def _get_modifiers_with_v2_research_tail(self):
        mods = original(self)

        if bool(getattr(self, "_gc_endgame_v2_research_tail_applied", False)):
            return mods

        from ..production_formula import (
            CRYSTAL_TECH_PER_LEVEL,
            DRONE_TECH_PER_LEVEL,
            MINING_TECH_PER_LEVEL,
            endgame_economy_mode,
            research_modifier_for,
        )

        if endgame_economy_mode() != "active":
            return mods

        research = dict(getattr(self, "research", None) or {})
        try:
            mining = max(0, int(research.get("mining_tech", 0) or 0))
        except (TypeError, ValueError):
            mining = 0
        try:
            crystal = max(0, int(research.get("crystal_tech", 0) or 0))
        except (TypeError, ValueError):
            crystal = 0
        try:
            drone = max(0, int(research.get("drone_tech", 0) or 0))
        except (TypeError, ValueError):
            drone = 0

        legacy_metal_research = (
            (1.0 + MINING_TECH_PER_LEVEL * mining)
            * (1.0 + DRONE_TECH_PER_LEVEL * drone)
        )
        legacy_crystal_research = (
            (1.0 + CRYSTAL_TECH_PER_LEVEL * crystal)
            * (1.0 + DRONE_TECH_PER_LEVEL * drone)
        )
        active_metal_research = float(research_modifier_for("metal", research))
        active_crystal_research = float(research_modifier_for("crystal", research))

        if legacy_metal_research > 0.0:
            mods["metal_prod_factor"] = float(mods.get("metal_prod_factor", 1.0)) * (
                active_metal_research / legacy_metal_research
            )
        if legacy_crystal_research > 0.0:
            mods["crystal_prod_factor"] = float(mods.get("crystal_prod_factor", 1.0)) * (
                active_crystal_research / legacy_crystal_research
            )

        # Keep the deprecated alias coherent with the authoritative metal factor.
        mods["prod_multiplier"] = float(mods.get("metal_prod_factor", 1.0))
        self._gc_endgame_v2_research_tail_applied = True
        return mods

    effect_resolver_cls.get_modifiers = _get_modifiers_with_v2_research_tail
    effect_resolver_cls._gc_endgame_v2_research_tail_installed = True
