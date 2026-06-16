"""
Central authoritative effect resolver for Genesis Colonies.

All gameplay modifiers (buildings + research + admin settings) are computed here.
Consumers must not duplicate formulas in resources.py, buildings.py, or the frontend.

Status (see docs/EFFECTS.md):
  - Economy / time effects: active (fixed).
  - Combat (weapon_tech / armor_tech / shield_tech): active — consumed by ``game.combat``.
  - Fleet / radar scan: PREPARED ONLY until those engines consume modifiers.
  - Multi-universe: not supported (no universe_id in DB schema).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from ..models import get_game_settings, get_planet_buildings, get_research_levels
from ..planet_evolution.repository import get_context_planet

logger = logging.getLogger(__name__)

EFFECT_DEBUG = os.environ.get("GC_EFFECT_DEBUG", "").strip().lower() in ("1", "true", "yes")

# Research reduction formulas — single source of truth (GC-622C).
# Linear per level; display % is unbounded. mine_energy_factor may reach 0; actual draw is floored.
MINE_ENERGY_PER_LEVEL = 0.05
MINE_ENERGY_MIN_DRAW_FACTOR = 0.01  # gameplay floor: never 0 draw for active consumers
BUILDTIME_PER_LEVEL = 0.03
FUEL_EFFICIENCY_PER_LEVEL = 0.03
_DIVISION_EPS = 1e-12  # avoid div-by-zero only; not a balance cap

# Production balance (GC-622C / GC-622D — Ferronit:Crytite:Brennzellen ≈ 100:65:35)
METAL_PROD_BASE = 0.04
METAL_PROD_EXP = 1.4
CRYSTAL_PROD_BASE = 0.046  # GC-622D buff (+24% vs 622C, +53% vs original 0.03)
CRYSTAL_PROD_EXP = 1.39  # was 1.35 — stronger late scaling
FUEL_CELL_GROWTH = 1.255  # was 1.35 — late-game Brennzellen nerf (GC-622D)

# Combat modifiers — consumed by game.combat (GC-504).
COMBAT_MODIFIER_KEYS = frozenset({
    "weapon_bonus",
    "armor_bonus",
    "shield_bonus",
})

# Modifier keys computed but not consumed by any live gameplay engine yet.
PREPARED_MODIFIER_KEYS = frozenset({
    "scan_range",
    "fleet_speed_multiplier",
    "cargo_multiplier",
})

ACTIVE_MODIFIER_KEYS = frozenset({
    "mine_energy_factor",
    "metal_prod_factor",
    "crystal_prod_factor",
    "storage_factor",
    "build_time_speed",
    "research_time_speed",
    "solar_output_factor",
    "fuel_efficiency_factor",
}) | COMBAT_MODIFIER_KEYS


def _lvl(levels: Dict[str, Any], key: str) -> int:
    try:
        return max(0, int(levels.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _bld(buildings: Dict[str, int], key: str) -> int:
    try:
        return max(0, int(buildings.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def _mod_float(mods: Dict[str, Any], key: str, default: float = 1.0) -> float:
    """Read modifier float; preserves legitimate 0.0 (unlike ``val or default``)."""
    if key not in mods:
        return default
    val = mods[key]
    if val is None:
        return default
    return float(val)


class EffectResolver:
    """
    Deterministic, server-side effect calculator for one planet + player research.
    """

    BASE_STORAGE = 100_000
    STORAGE_GROW = 1.8
    MAX_BUILDING_LEVEL = 50

    # ------------------------------------------------------------------
    # Per-research formulas (display + gameplay — no duplicate min() elsewhere)
    # ------------------------------------------------------------------

    @staticmethod
    def _reduction_factor(level: int, per_level: float) -> float:
        """Gameplay multiplier in [0, 1]; clamps at 0 when linear reduction exceeds 100%."""
        lvl = max(0, int(level or 0))
        if lvl <= 0:
            return 1.0
        return max(0.0, 1.0 - per_level * lvl)

    @staticmethod
    def _reduction_pct(level: int, per_level: float) -> int:
        """Display reduction % — unbounded (can exceed 100%)."""
        lvl = max(0, int(level or 0))
        if lvl <= 0:
            return 0
        return int(round(per_level * lvl * 100))

    @staticmethod
    def mine_energy_factor_for_level(level: int) -> float:
        return EffectResolver._reduction_factor(level, MINE_ENERGY_PER_LEVEL)

    @staticmethod
    def mine_energy_reduction_pct(level: int) -> int:
        return EffectResolver._reduction_pct(level, MINE_ENERGY_PER_LEVEL)

    @staticmethod
    def apply_mine_energy_draw(raw: int, factor: float) -> int:
        """Apply energy_tech to one consumer; draw never 0 when raw > 0."""
        raw_i = int(raw or 0)
        if raw_i <= 0:
            return 0
        effective = max(MINE_ENERGY_MIN_DRAW_FACTOR, float(factor))
        return max(1, int(raw_i * effective))

    @staticmethod
    def buildtime_duration_factor_for_level(level: int) -> float:
        return EffectResolver._reduction_factor(level, BUILDTIME_PER_LEVEL)

    @staticmethod
    def buildtime_reduction_pct(level: int) -> int:
        return EffectResolver._reduction_pct(level, BUILDTIME_PER_LEVEL)

    @staticmethod
    def fuel_efficiency_factor_for_level(level: int) -> float:
        return EffectResolver._reduction_factor(level, FUEL_EFFICIENCY_PER_LEVEL)

    @staticmethod
    def fuel_efficiency_reduction_pct(level: int) -> int:
        return EffectResolver._reduction_pct(level, FUEL_EFFICIENCY_PER_LEVEL)

    @staticmethod
    def metal_prod_bonus_pct(level: int) -> int:
        return int(round(10.0 * max(0, int(level or 0))))

    @staticmethod
    def crystal_prod_bonus_pct(level: int) -> int:
        return int(round(4.0 * max(0, int(level or 0))))

    @staticmethod
    def drone_prod_bonus_pct(level: int) -> int:
        return int(round(3.0 * max(0, int(level or 0))))

    @staticmethod
    def storage_bonus_pct(level: int) -> int:
        return int(round(25.0 * max(0, int(level or 0))))

    @staticmethod
    def combat_bonus_pct(level: int) -> int:
        return int(round(5.0 * max(0, int(level or 0))))

    @staticmethod
    def fleet_speed_bonus_pct(level: int, per_level: float) -> int:
        lvl = max(0, int(level or 0))
        return int(round(per_level * lvl * 100))

    def __init__(
        self,
        buildings: Dict[str, int],
        research: Dict[str, int],
        *,
        settings: Optional[Dict[str, Any]] = None,
        player_id: Optional[int] = None,
        planet_id: Optional[int] = None,
    ) -> None:
        self.buildings = {k: _bld(buildings, k) for k in buildings}
        self.research = dict(research or {})
        self.player_id = int(player_id) if player_id is not None else None
        self.planet_id = int(planet_id) if planet_id is not None else None
        self._settings = settings
        self._mods: Optional[Dict[str, float]] = None
        self._sources: List[Dict[str, Any]] = []

    @classmethod
    def for_player(cls, player_id: int, conn=None) -> EffectResolver:
        planet = get_context_planet(player_id=int(player_id), conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        research = get_research_levels(int(player_id), conn=conn)
        try:
            settings = get_game_settings(conn=conn)
        except TypeError:
            settings = get_game_settings()
        return cls(
            buildings,
            research,
            settings=settings,
            player_id=int(player_id),
            planet_id=int(planet["id"]),
        )

    def _settings_dict(self) -> Dict[str, Any]:
        if self._settings is not None:
            return self._settings
        self._settings = get_game_settings()
        return self._settings

    @staticmethod
    def _source_entry(
        key: str,
        source: str,
        value: Any,
        level: int,
        *,
        prepared: bool = False,
    ) -> Dict[str, Any]:
        return {
            "key": key,
            "source": source,
            "value": value,
            "level": level,
            "status": "prepared" if prepared else "active",
        }

    # ------------------------------------------------------------------
    # Modifier bundle (canonical consumer keys)
    # ------------------------------------------------------------------

    def get_modifiers(self) -> Dict[str, float]:
        if self._mods is not None:
            return self._mods

        b = self.buildings
        r = self.research
        sources: List[Dict[str, Any]] = []
        self._sources = sources

        mine_energy_factor = 1.0
        metal_prod_factor = 1.0
        crystal_prod_factor = 1.0
        storage_factor = 1.0
        build_time_speed = 1.0
        research_time_speed = 1.0
        solar_output_factor = 1.0

        weapon_bonus = 0.0
        armor_bonus = 0.0
        shield_bonus = 0.0
        scan_range = 0
        fleet_speed_multiplier = 1.0
        cargo_multiplier = 1.0
        fuel_efficiency_factor = 1.0

        # --- Research: energy_tech (-5% mine draw per level; mines only, not solar) ---
        le = _lvl(r, "energy_tech")
        if le > 0:
            mine_energy_factor = self.mine_energy_factor_for_level(le)
            sources.append(self._source_entry("mine_energy_factor", "energy_tech", mine_energy_factor, le))

        # --- Research: mining_tech (+10% metal, +4% crystal per level) ---
        lm = _lvl(r, "mining_tech")
        if lm > 0:
            metal_prod_factor *= 1.0 + 0.10 * lm
            crystal_prod_factor *= 1.0 + 0.04 * lm
            sources.append(self._source_entry("metal_prod_factor", "mining_tech", metal_prod_factor, lm))

        # --- Research: drone_tech (+3% both per level) ---
        ld = _lvl(r, "drone_tech")
        if ld > 0:
            drone_bonus = 1.0 + 0.03 * ld
            metal_prod_factor *= drone_bonus
            crystal_prod_factor *= drone_bonus
            sources.append(self._source_entry("prod_factor", "drone_tech", drone_bonus, ld))

        # --- Research: storage_tech (+25% storage per level) ---
        ls = _lvl(r, "storage_tech")
        if ls > 0:
            storage_factor *= 1.0 + 0.25 * ls
            sources.append(self._source_entry("storage_factor", "storage_tech", storage_factor, ls))

        # --- Research: buildtime_tech (-3% build+research time per level) ---
        lb = _lvl(r, "buildtime_tech")
        if lb > 0:
            duration_factor = self.buildtime_duration_factor_for_level(lb)
            speed_boost = 1.0 / max(duration_factor, _DIVISION_EPS)
            build_time_speed *= speed_boost
            research_time_speed *= speed_boost
            sources.append(self._source_entry("build_time_speed", "buildtime_tech", speed_boost, lb))

        # --- Research: fuel_efficiency (-3% fleet fuel per level) ---
        lf = _lvl(r, "fuel_efficiency")
        if lf > 0:
            fuel_efficiency_factor = self.fuel_efficiency_factor_for_level(lf)
            sources.append(
                self._source_entry("fuel_efficiency_factor", "fuel_efficiency", fuel_efficiency_factor, lf)
            )

        # --- Research: combat (weapon_tech / armor_tech / shield_tech → game.combat) ---
        lw = _lvl(r, "weapon_tech")
        if lw > 0:
            weapon_bonus += 0.05 * lw
            sources.append(self._source_entry("weapon_bonus", "weapon_tech", weapon_bonus, lw))

        la = _lvl(r, "armor_tech")
        if la > 0:
            armor_bonus += 0.05 * la
            sources.append(self._source_entry("armor_bonus", "armor_tech", armor_bonus, la))

        lsh = _lvl(r, "shield_tech")
        if lsh > 0:
            shield_bonus += 0.05 * lsh
            sources.append(self._source_entry("shield_bonus", "shield_tech", shield_bonus, lsh))

        lhn = _lvl(r, "navigation_tech")
        if lhn > 0:
            fleet_speed_multiplier *= 1.0 + 0.03 * lhn
            sources.append(self._source_entry("fleet_speed_multiplier", "navigation_tech", fleet_speed_multiplier, lhn, prepared=True))

        leng = _lvl(r, "engine_tech")
        if leng > 0:
            fleet_speed_multiplier *= 1.0 + 0.02 * leng
            cargo_multiplier *= 1.0 + 0.02 * leng
            sources.append(self._source_entry("fleet_speed_multiplier", "engine_tech", fleet_speed_multiplier, leng, prepared=True))

        # --- Buildings: nanofactory (+30% build speed per level, all buildings) ---
        nano = _bld(b, "nanofactory")
        if nano > 0:
            build_time_speed *= 1.0 + 0.30 * nano
            sources.append(self._source_entry("build_time_speed", "nanofactory", build_time_speed, nano))

        # command_center nanofactory-only build boost applied in get_build_time_seconds()

        # --- Buildings: academy (+5% research speed per level) ---
        academy = _bld(b, "academy")
        if academy > 0:
            research_time_speed *= 1.0 + 0.05 * academy
            sources.append(self._source_entry("research_time_speed", "academy", research_time_speed, academy))

        # --- Buildings: geothermal (+3% solar output per level) ---
        geo = _bld(b, "geothermal_nexus")
        if geo > 0:
            solar_output_factor *= 1.0 + 0.03 * geo
            sources.append(self._source_entry("solar_output_factor", "geothermal_nexus", solar_output_factor, geo))

        # --- Prepared: radar scan (no galaxy/scan engine yet) ---
        radar = _bld(b, "radar_array")
        if radar > 0:
            scan_range += 2 * radar
            sources.append(self._source_entry("scan_range", "radar_array", scan_range, radar, prepared=True))

        self._mods = {
            "mine_energy_factor": float(mine_energy_factor),
            "metal_prod_factor": float(metal_prod_factor),
            "crystal_prod_factor": float(crystal_prod_factor),
            "storage_factor": float(storage_factor),
            "build_time_speed": float(build_time_speed),
            "research_time_speed": float(research_time_speed),
            "solar_output_factor": float(solar_output_factor),
            "weapon_bonus": float(weapon_bonus),
            "armor_bonus": float(armor_bonus),
            "shield_bonus": float(shield_bonus),
            "scan_range": int(scan_range),
            "fleet_speed_multiplier": float(fleet_speed_multiplier),
            "cargo_multiplier": float(cargo_multiplier),
            "fuel_efficiency_factor": float(fuel_efficiency_factor),
            # Legacy aliases (deprecated; kept one release for external callers)
            "prod_multiplier": float(metal_prod_factor),
            "storage_multiplier": float(storage_factor),
            "build_time_multiplier": float(1.0 / max(build_time_speed, _DIVISION_EPS)),
            "research_time_multiplier": float(1.0 / max(research_time_speed, _DIVISION_EPS)),
            "energy_efficiency": float(mine_energy_factor),
        }

        if EFFECT_DEBUG:
            logger.info(
                "effect_resolver player=%s planet=%s mods=%s sources=%s",
                self.player_id,
                self.planet_id,
                self._mods,
                sources,
            )

        return self._mods

    def get_active_modifiers(self) -> Dict[str, float]:
        mods = self.get_modifiers()
        return {k: v for k, v in mods.items() if k in ACTIVE_MODIFIER_KEYS}

    def get_prepared_modifiers(self) -> Dict[str, float]:
        mods = self.get_modifiers()
        return {k: v for k, v in mods.items() if k in PREPARED_MODIFIER_KEYS}

    def get_combat_modifiers(self) -> Dict[str, float]:
        """
        Account research combat bonuses for ``game.combat.CombatModifiers``.

        weapon_tech → weapon_bonus (+5% attack per level)
        armor_tech → armor_bonus (+5% hull per level)
        shield_tech → shield_bonus (+5% shield per level)
        """
        mods = self.get_modifiers()
        return {
            "weapon_bonus": float(mods.get("weapon_bonus", 0.0) or 0.0),
            "armor_bonus": float(mods.get("armor_bonus", 0.0) or 0.0),
            "shield_bonus": float(mods.get("shield_bonus", 0.0) or 0.0),
        }

    def debug_snapshot(self) -> Dict[str, Any]:
        mods = self.get_modifiers()
        energy_total, energy_used = self.compute_energy()
        m_rate, c_rate = self.production_rates_per_sec()
        caps = self.get_storage_capacity()
        ratio = self.energy_ratio(energy_total, energy_used)
        active_sources = [s for s in self._sources if s.get("status") == "active"]
        prepared_sources = [s for s in self._sources if s.get("status") == "prepared"]
        return {
            "player_id": self.player_id,
            "planet_id": self.planet_id,
            "buildings": dict(self.buildings),
            "research": dict(self.research),
            "modifiers": mods,
            "modifiers_active": self.get_active_modifiers(),
            "modifiers_prepared": self.get_prepared_modifiers(),
            "sources": list(self._sources),
            "sources_active": active_sources,
            "sources_prepared": prepared_sources,
            "energy": {"total": energy_total, "used": energy_used, "ratio": ratio},
            "production_per_sec": {"metal": m_rate, "crystal": c_rate},
            "production_per_hour": {
                "metal": int(m_rate * ratio * 3600 * self.production_speed_setting()),
                "crystal": int(c_rate * ratio * 3600 * self.production_speed_setting()),
            },
            "storage": caps,
            "build_time_speed": mods.get("build_time_speed", 1.0),
            "research_time_speed": mods.get("research_time_speed", 1.0),
            "lab_bonus": self.research_lab_bonus(),
            "max_levels": {
                bt: self.get_max_building_level(bt)
                for bt in (
                    "metal_mine",
                    "crystal_mine",
                    "solar_plant",
                    "metal_storage",
                    "crystal_storage",
                    "fuel_storage",
                )
            },
        }

    # ------------------------------------------------------------------
    # Gameplay calculations
    # ------------------------------------------------------------------

    def production_speed_setting(self) -> float:
        return float(self._settings_dict().get("production_speed", 1.0) or 1.0)

    def build_speed_setting(self) -> float:
        return float(self._settings_dict().get("build_speed", 1.0) or 1.0)

    def research_speed_setting(self) -> float:
        return float(self._settings_dict().get("research_speed", 1.0) or 1.0)

    def fleet_speed_setting(self) -> float:
        return float(self._settings_dict().get("fleet_speed", 1.0) or 1.0)

    def research_lab_bonus(self) -> float:
        lab = _bld(self.buildings, "research_lab")
        return 1.0 + max(0, lab - 1) * 0.10

    def compute_energy(self) -> Tuple[int, int]:
        mods = self.get_modifiers()
        b = self.buildings

        solar_lvl = _bld(b, "solar_plant")
        metal_lvl = _bld(b, "metal_mine")
        crystal_lvl = _bld(b, "crystal_mine")

        solar_factor = _mod_float(mods, "solar_output_factor")
        energy_total = int(20 * (solar_lvl ** 1.4) * solar_factor) if solar_lvl > 0 else 0

        energy_metal = int(10 * (metal_lvl ** 1.25)) if metal_lvl > 0 else 0
        energy_crystal = int(6 * (crystal_lvl ** 1.25)) if crystal_lvl > 0 else 0
        fuel_cell_lvl = _bld(b, "fuel_cell_plant")
        energy_fuel_cell = int(8 * (fuel_cell_lvl ** 1.25)) if fuel_cell_lvl > 0 else 0

        mine_energy_factor = _mod_float(mods, "mine_energy_factor")
        energy_used = (
            self.apply_mine_energy_draw(energy_metal, mine_energy_factor)
            + self.apply_mine_energy_draw(energy_crystal, mine_energy_factor)
            + self.apply_mine_energy_draw(energy_fuel_cell, mine_energy_factor)
        )

        return energy_total, energy_used

    def building_energy_draw(self, building_type: str, *, level: Optional[int] = None) -> int:
        """Per-building energy draw (mines + fuel cell plant), incl. mine_energy_factor."""
        lvl = int(level if level is not None else _bld(self.buildings, building_type))
        if lvl <= 0:
            return 0
        if building_type == "metal_mine":
            raw = int(10 * (lvl ** 1.25))
        elif building_type == "crystal_mine":
            raw = int(6 * (lvl ** 1.25))
        elif building_type == "fuel_cell_plant":
            raw = int(8 * (lvl ** 1.25))
        else:
            return 0
        factor = _mod_float(self.get_modifiers(), "mine_energy_factor")
        return self.apply_mine_energy_draw(raw, factor)

    @staticmethod
    def energy_ratio(energy_total: int, energy_used: int) -> float:
        if energy_total >= energy_used:
            return 1.0
        return max(0.0, float(energy_total) / max(1.0, float(energy_used)))

    def production_rates_per_sec(self) -> Tuple[float, float]:
        mods = self.get_modifiers()
        b = self.buildings

        metal_lvl = _bld(b, "metal_mine")
        crystal_lvl = _bld(b, "crystal_mine")

        metal_rate = METAL_PROD_BASE * (metal_lvl ** METAL_PROD_EXP) if metal_lvl > 0 else 0.0
        crystal_rate = CRYSTAL_PROD_BASE * (crystal_lvl ** CRYSTAL_PROD_EXP) if crystal_lvl > 0 else 0.0

        metal_rate *= _mod_float(mods, "metal_prod_factor")
        crystal_rate *= _mod_float(mods, "crystal_prod_factor")

        return metal_rate, crystal_rate

    def fuel_cells_rate_per_sec(self) -> float:
        """Brennzellen-Produktion: fuel_production_per_hour * level * FUEL_CELL_GROWTH^(level-1)."""
        per_hour = self.fuel_cells_production_per_hour()
        return per_hour / 3600.0 if per_hour > 0 else 0.0

    def fuel_cells_production_per_hour(self) -> float:
        lvl = _bld(self.buildings, "fuel_cell_plant")
        if lvl <= 0:
            return 0.0
        base_ph = float(self._settings_dict().get("fuel_production_per_hour", 2.0) or 2.0)
        return base_ph * lvl * (FUEL_CELL_GROWTH ** max(0, lvl - 1))

    def fuel_storage_capacity(self) -> int:
        """Planet fuel cell depot capacity (fuel_storage building + tech/terraformer)."""
        mods = self.get_modifiers()
        b = self.buildings

        terra_lvl = _bld(b, "terraformer")
        terra_factor = 1.0 + 0.05 * terra_lvl
        storage_factor = _mod_float(mods, "storage_factor") * terra_factor

        f_lvl = _bld(b, "fuel_storage")
        if f_lvl <= 0:
            return 0
        f_cap = self.BASE_STORAGE * (self.STORAGE_GROW ** max(0, f_lvl - 1))
        return int(f_cap * storage_factor)

    def fuel_cells_storage_capacity(self) -> int:
        """Authoritative fuel_cells cap — depot only (plant no longer stores)."""
        return self.fuel_storage_capacity()

    def get_storage_capacity(self) -> Dict[str, int]:
        mods = self.get_modifiers()
        b = self.buildings

        terra_lvl = _bld(b, "terraformer")
        terra_factor = 1.0 + 0.05 * terra_lvl
        storage_factor = _mod_float(mods, "storage_factor") * terra_factor

        m_lvl = _bld(b, "metal_storage")
        c_lvl = _bld(b, "crystal_storage")

        m_cap = self.BASE_STORAGE * (self.STORAGE_GROW ** max(0, m_lvl - 1)) if m_lvl > 0 else self.BASE_STORAGE
        c_cap = self.BASE_STORAGE * (self.STORAGE_GROW ** max(0, c_lvl - 1)) if c_lvl > 0 else self.BASE_STORAGE

        return {
            "metal": int(m_cap * storage_factor),
            "crystal": int(c_cap * storage_factor),
            "fuel_cells": self.fuel_cells_storage_capacity(),
        }

    def get_building_production_per_hour(self, ratio: float) -> Dict[str, int]:
        prod_speed = self.production_speed_setting()
        m_rate, c_rate = self.production_rates_per_sec()
        fc_rate = self.fuel_cells_rate_per_sec()
        metal_ph = int(m_rate * float(ratio) * 3600 * prod_speed)
        crystal_ph = int(c_rate * float(ratio) * 3600 * prod_speed)
        fuel_cell_ph = int(fc_rate * float(ratio) * 3600 * prod_speed)
        return {
            "metal_mine": metal_ph,
            "crystal_mine": crystal_ph,
            "fuel_cell_plant": fuel_cell_ph,
            "solar_plant": 0,
            "research_lab": 0,
            "academy": 0,
            "metal_storage": 0,
            "crystal_storage": 0,
            "fuel_storage": 0,
            "command_center": 0,
            "shipyard": 0,
            "defense_factory": 0,
            "barracks": 0,
            "radar_array": 0,
            "shield_generator": 0,
            "terraformer": 0,
            "nanofactory": 0,
            "geothermal_nexus": 0,
            "planet_core_nexus": 0,
        }

    def get_max_building_level(self, building_type: str) -> int:
        base_max = self.MAX_BUILDING_LEVEL
        b = self.buildings
        core = _bld(b, "planet_core_nexus")
        geo = _bld(b, "geothermal_nexus")

        if building_type in ("metal_mine", "crystal_mine", "solar_plant"):
            return base_max + core + geo * 2
        if building_type in ("metal_storage", "crystal_storage", "fuel_storage"):
            return base_max + geo * 2
        return base_max

    def get_build_time_seconds(self, building_type: str, target_level: int) -> int:
        from ..buildings import BUILD_TIME_BASE, BUILD_TIME_FACTOR, DEFAULT_BUILD_TIME_LEVEL_1

        base_time = BUILD_TIME_BASE.get(building_type, DEFAULT_BUILD_TIME_LEVEL_1)
        factor = BUILD_TIME_FACTOR.get(building_type, 1.5)
        lvl_factor = factor ** max(int(target_level) - 1, 0)
        seconds = float(base_time * lvl_factor)

        mods = self.get_modifiers()
        build_time_speed = _mod_float(mods, "build_time_speed")
        if str(building_type) == "nanofactory":
            command_center = _bld(self.buildings, "command_center")
            if command_center > 0:
                build_time_speed *= 1.0 + 0.25 * command_center
        effective_speed = max(0.1, build_time_speed * self.build_speed_setting())
        seconds /= effective_speed
        return max(int(seconds), 1)

    def get_research_time_seconds(self, tech_key: str, target_level: int) -> int:
        from ..research import RESEARCH_TECHS

        cfg = RESEARCH_TECHS.get(tech_key)
        if not cfg:
            return 0

        base_time = float(cfg.get("base_time", 600))
        cost_factor = float(cfg.get("cost_factor", 1.6))
        lvl = max(1, int(target_level))
        factor = cost_factor ** (lvl - 1)
        raw = float(base_time * factor)

        mods = self.get_modifiers()
        research_time_speed = _mod_float(mods, "research_time_speed")
        effective_speed = max(
            0.1,
            self.build_speed_setting()
            * self.research_speed_setting()
            * self.research_lab_bonus()
            * research_time_speed,
        )
        raw /= effective_speed
        # Technical safety floor only (no balance cap). Keep >0 to avoid stuck/0-duration queues.
        return max(1, int(raw))


def get_effect_resolver(
    player_id: int,
    *,
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    conn=None,
    settings: Optional[Dict[str, Any]] = None,
    force_refresh: bool = False,
) -> EffectResolver:
    """
    Build a fresh EffectResolver (no cross-request cache).
    force_refresh kept for API compatibility; always loads current DB state.
    """
    del force_refresh  # no cache layer — always authoritative from DB inputs

    if buildings is not None and research is not None:
        planet_id = None
        if conn is not None:
            try:
                planet = get_context_planet(player_id=int(player_id), conn=conn)
                planet_id = int(planet["id"])
            except Exception:
                pass
        return EffectResolver(
            buildings,
            research,
            settings=settings,
            player_id=int(player_id),
            planet_id=planet_id,
        )

    return EffectResolver.for_player(int(player_id), conn=conn)


def clear_effect_resolver_cache(player_id: Optional[int] = None) -> None:
    """No-op: resolver cache removed; kept for call-site compatibility."""
    del player_id
