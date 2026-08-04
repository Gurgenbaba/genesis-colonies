"""
Unified production formula — single source of truth for resource output (GC-820 / GC-860).

All production values must flow through ``calculate_resource_output``.
EffectResolver and resources.py delegate here; no duplicate formulas elsewhere.

Authoritative documentation: docs/PRODUCTION_FORMULA_SYSTEM.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .effects.effect_resolver import EffectResolver

# ---------------------------------------------------------------------------
# Ferdi rebase (GC-PRODUCTION-FERDI-REBASE) — standard income + mine exponential
# ---------------------------------------------------------------------------

RESOURCE_KEYS = frozenset({"metal", "crystal", "fuel_cells"})

LEVEL_GROWTH_RATE = 1.075
FERDI_GROWTH_RATE = LEVEL_GROWTH_RATE  # legacy alias

FERRONIT_MINE_BASE = 150.0
CRYTITE_MINE_BASE = 100.0
FUEL_CELLS_MINE_BASE = 50.0

STANDARD_PRODUCTION_PER_HOUR: Dict[str, float] = {
    "metal": 15000.0,
    "crystal": 10000.0,
    "fuel_cells": 5000.0,
}

LEVEL_GROWTH: Dict[str, Dict[str, float]] = {
    "metal": {"multiplier": FERRONIT_MINE_BASE, "building": "metal_mine"},
    "crystal": {"multiplier": CRYTITE_MINE_BASE, "building": "crystal_mine"},
    "fuel_cells": {"multiplier": FUEL_CELLS_MINE_BASE, "building": "fuel_cell_plant"},
}

MINING_TECH_PER_LEVEL = 0.03
CRYSTAL_TECH_PER_LEVEL = 0.03
DRONE_TECH_PER_LEVEL = 0.02

SLOT_METAL_RANGE = (4, 9)
SLOT_METAL_MAX_BONUS = 0.20
SLOT_CRYSTAL_RANGE = (1, 3)
SLOT_CRYSTAL_MAX_BONUS = 0.25
SLOT_FUEL_RANGE = (10, 15)
SLOT_FUEL_MAX_BONUS = 0.20

FUEL_TEMP_MODIFIER_MIN = 0.75
FUEL_TEMP_MODIFIER_MAX = 1.35
# Mid-slot reference temperatures (°C) for linear fuel temperature map.
_HOTTEST_TEMP_MID_C = 435.0
_COLDEST_TEMP_MID_C = -207.5


def _lvl(levels: Optional[Mapping[str, Any]], key: str) -> int:
    if not levels:
        return 0
    try:
        return max(0, int(levels.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_resource_type(resource_type: str) -> str:
    key = str(resource_type or "").strip().lower()
    aliases = {
        "ferronit": "metal",
        "metal": "metal",
        "crytite": "crystal",
        "crystal": "crystal",
        "brennzellen": "fuel_cells",
        "fuel": "fuel_cells",
        "fuel_cells": "fuel_cells",
        "fuel_cell": "fuel_cells",
    }
    normalized = aliases.get(key, key)
    if normalized not in RESOURCE_KEYS:
        raise ValueError(f"unsupported resource_type: {resource_type!r}")
    return normalized


def normalize_resource_type(resource_type: str) -> str:
    return _normalize_resource_type(resource_type)


def standard_output(resource_type: str) -> float:
    """Planet baseline income per hour (no mine required)."""
    key = _normalize_resource_type(resource_type)
    return float(STANDARD_PRODUCTION_PER_HOUR[key])


def mine_output(resource_type: str, level: int) -> float:
    """Mine-only base curve per hour (before production_speed and gameplay modifiers)."""
    key = _normalize_resource_type(resource_type)
    lvl = max(0, int(level or 0))
    if lvl <= 0:
        return 0.0
    base = float(LEVEL_GROWTH[key]["multiplier"])
    return base * lvl * (LEVEL_GROWTH_RATE ** lvl)


def ferdi_base_output(resource_type: str, level: int) -> float:
    """Alias for mine-only output (legacy name)."""
    return mine_output(resource_type, level)


def level_growth(resource_type: str, level: int, production_speed: float = 1.0) -> float:
    """Mine output × production_speed (per hour, before slot/research/energy modifiers)."""
    base = mine_output(resource_type, level)
    if base <= 0:
        return 0.0
    speed = max(0.0, float(production_speed or 1.0))
    return base * speed


def _slot_linear_bonus(
    slot: Optional[int],
    slot_min: int,
    slot_max: int,
    max_bonus: float,
    *,
    peak_at_min: bool,
) -> float:
    if slot is None:
        return 1.0
    try:
        pos = int(slot)
    except (TypeError, ValueError):
        return 1.0
    if pos < slot_min or pos > slot_max:
        return 1.0
    span = slot_max - slot_min
    if span <= 0:
        return 1.0 + max_bonus
    if peak_at_min:
        t = (pos - slot_min) / span
        return 1.0 + max_bonus * (1.0 - t)
    t = (pos - slot_min) / span
    return 1.0 + max_bonus * t


def slot_modifier_for(resource_type: str, slot: Optional[int]) -> float:
    key = _normalize_resource_type(resource_type)
    if key == "metal":
        lo, hi = SLOT_METAL_RANGE
        return _slot_linear_bonus(slot, lo, hi, SLOT_METAL_MAX_BONUS, peak_at_min=True)
    if key == "crystal":
        lo, hi = SLOT_CRYSTAL_RANGE
        return _slot_linear_bonus(slot, lo, hi, SLOT_CRYSTAL_MAX_BONUS, peak_at_min=True)
    lo, hi = SLOT_FUEL_RANGE
    return _slot_linear_bonus(slot, lo, hi, SLOT_FUEL_MAX_BONUS, peak_at_min=False)


def temperature_mid_c_for_slot(slot: Optional[int]) -> Optional[float]:
    if slot is None:
        return None
    from .planet_visuals import temperature_range_for_position

    band = temperature_range_for_position(slot)
    lo = float(band["min_c"])
    hi = float(band["max_c"])
    return (lo + hi) / 2.0


def temperature_modifier_for(resource_type: str, temperature_mid_c: Optional[float]) -> float:
    """Fuel cells only — clamped to [0.75, 1.35]. Hot worlds reduce, cold worlds boost."""
    key = _normalize_resource_type(resource_type)
    if key != "fuel_cells":
        return 1.0
    if temperature_mid_c is None:
        return 1.0
    span = _COLDEST_TEMP_MID_C - _HOTTEST_TEMP_MID_C
    if abs(span) < 1e-9:
        return 1.0
    t = (float(temperature_mid_c) - _HOTTEST_TEMP_MID_C) / span
    t = max(0.0, min(1.0, t))
    raw = FUEL_TEMP_MODIFIER_MIN + t * (FUEL_TEMP_MODIFIER_MAX - FUEL_TEMP_MODIFIER_MIN)
    return max(FUEL_TEMP_MODIFIER_MIN, min(FUEL_TEMP_MODIFIER_MAX, raw))


def research_modifier_for(resource_type: str, research: Optional[Mapping[str, Any]]) -> float:
    key = _normalize_resource_type(resource_type)
    mining = _lvl(research, "mining_tech")
    crystal = _lvl(research, "crystal_tech")
    drone = _lvl(research, "drone_tech")
    if key == "metal":
        return (1.0 + MINING_TECH_PER_LEVEL * mining) * (1.0 + DRONE_TECH_PER_LEVEL * drone)
    if key == "crystal":
        return (1.0 + CRYSTAL_TECH_PER_LEVEL * crystal) * (1.0 + DRONE_TECH_PER_LEVEL * drone)
    return 1.0


@dataclass
class ProductionContext:
    """Inputs for the canonical production formula."""

    resource_type: str
    level: int
    slot: Optional[int] = None
    temperature: Optional[float] = None
    energy_ratio: float = 1.0
    production_speed: float = 1.0
    research: Optional[Dict[str, int]] = None
    player: Any = None
    planet: Any = None
    empire: Any = None
    building_modifier: float = 1.0
    planet_modifier: float = 1.0
    empire_modifier: float = 1.0
    alliance_modifier: float = 1.0
    directive_modifier: float = 1.0
    event_modifier: float = 1.0
    season_modifier: float = 1.0
    active_effects: List[Any] = field(default_factory=list)
    active_events: List[Any] = field(default_factory=list)
    active_directives: List[Any] = field(default_factory=list)


class ProductionModifiers:
    """Modifier accessors — each returns a multiplicative factor (default 1.0)."""

    def __init__(self, context: ProductionContext) -> None:
        self.context = context
        self._resource = _normalize_resource_type(context.resource_type)

    def slot_modifier(self) -> float:
        return slot_modifier_for(self._resource, self.context.slot)

    def temperature_modifier(self) -> float:
        temp = self.context.temperature
        if temp is None and self.context.slot is not None:
            temp = temperature_mid_c_for_slot(self.context.slot)
        return temperature_modifier_for(self._resource, temp)

    def research_modifier(self) -> float:
        return research_modifier_for(self._resource, self.context.research)

    def energy_modifier(self) -> float:
        return max(0.0, min(1.0, float(self.context.energy_ratio or 1.0)))

    def building_modifier(self) -> float:
        return max(0.0, float(self.context.building_modifier or 1.0))

    def planet_modifier(self) -> float:
        return max(0.0, float(self.context.planet_modifier or 1.0))

    def empire_modifier(self) -> float:
        return max(0.0, float(self.context.empire_modifier or 1.0))

    def alliance_modifier(self) -> float:
        return max(0.0, float(self.context.alliance_modifier or 1.0))

    def directive_modifier(self) -> float:
        return max(0.0, float(self.context.directive_modifier or 1.0))

    def event_modifier(self) -> float:
        return max(0.0, float(self.context.event_modifier or 1.0))

    def seasonal_modifier(self) -> float:
        return max(0.0, float(self.context.season_modifier or 1.0))

    def combined_without_energy(self) -> float:
        """Gameplay modifiers shared by standard and mine production."""
        return (
            self.slot_modifier()
            * self.temperature_modifier()
            * self.research_modifier()
            * self.building_modifier()
            * self.planet_modifier()
            * self.empire_modifier()
            * self.alliance_modifier()
            * self.directive_modifier()
            * self.event_modifier()
            * self.seasonal_modifier()
        )

    def combined(self) -> float:
        return self.combined_without_energy() * self.energy_modifier()


def calculate_resource_output(resource_type: str, context: ProductionContext) -> float:
    """
    Canonical production output per hour.

    Output = StandardBase × speed × modifiers (excl. energy)
           + MineBase(level) × speed × modifiers (incl. energy on mine part only)
    """
    key = _normalize_resource_type(resource_type)
    lvl = max(0, int(context.level or 0))
    speed = max(0.0, float(context.production_speed or 1.0))
    mods = ProductionModifiers(context)
    mod_shared = mods.combined_without_energy()

    standard_part = standard_output(key) * speed * mod_shared
    mine_base = mine_output(key, lvl) * speed
    mine_part = mine_base * mods.combined() if mine_base > 0 else 0.0

    return max(0.0, standard_part + mine_part)


def production_context_from_resolver(
    resolver: EffectResolver,
    resource_type: str,
    *,
    level: Optional[int] = None,
    energy_ratio: float = 1.0,
) -> ProductionContext:
    """Build a ProductionContext from an EffectResolver instance."""
    key = _normalize_resource_type(resource_type)
    cfg = LEVEL_GROWTH[key]
    building_key = cfg["building"]
    if level is None:
        try:
            level = max(0, int(resolver.buildings.get(building_key, 0) or 0))
        except (TypeError, ValueError):
            level = 0

    temp = temperature_mid_c_for_slot(resolver.planet_position)
    overlay = resolver.prod_overlay_factor(key)

    event_mod = 1.0
    try:
        from .server_events import active_production_mult

        event_mod = float(active_production_mult() or 1.0)
    except Exception:
        event_mod = 1.0

    return ProductionContext(
        resource_type=key,
        level=int(level),
        slot=resolver.planet_position,
        temperature=temp,
        energy_ratio=float(energy_ratio),
        production_speed=resolver.production_speed_setting(),
        research=dict(resolver.research or {}),
        player=resolver.player_id,
        planet=resolver.planet_id,
        directive_modifier=float(overlay),
        event_modifier=max(0.0, event_mod),
    )


def snapshot_outputs(
    *,
    production_speed: float = 1.0,
    energy_ratio: float = 1.0,
    slot: Optional[int] = 9,
) -> Dict[str, Dict[int, float]]:
    """Reference table for docs/tests — per-hour output at benchmark levels."""
    levels = (0, 1, 10, 30, 60, 90, 120)
    out: Dict[str, Dict[int, float]] = {k: {} for k in RESOURCE_KEYS}
    for res in RESOURCE_KEYS:
        for lvl in levels:
            ctx = ProductionContext(
                resource_type=res,
                level=lvl,
                slot=slot,
                temperature=temperature_mid_c_for_slot(slot),
                energy_ratio=energy_ratio,
                production_speed=production_speed,
            )
            out[res][lvl] = calculate_resource_output(res, ctx)
    return out
