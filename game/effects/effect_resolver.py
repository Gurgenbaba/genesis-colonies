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
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

from ..economy_balance import STORAGE_BASE_CAPACITY
from ..models import get_game_settings, get_planet_buildings, get_research_levels
from ..planet_evolution.repository import get_context_planet

logger = logging.getLogger(__name__)

EFFECT_DEBUG = os.environ.get("GC_EFFECT_DEBUG", "").strip().lower() in ("1", "true", "yes")

# GC-PERF-EFFECT-CACHE-001: request-scoped resolver reuse (no process TTL).
_RESOLVER_CACHE: ContextVar[Optional[Dict[tuple, "EffectResolver"]]] = ContextVar(
    "gc_effect_resolver_cache",
    default=None,
)
# Isolate optional DB probes so a failure cannot abort an outer write TX (PARITY-001).
_ER_SAVEPOINT_SEQ = 0

# Research / building reduction formulas — single source of truth (GC-622C, Alpha balance).
# Linear per level where noted; display % is unbounded. mine_energy_factor may reach 0; draw is floored.
MINE_ENERGY_PER_LEVEL = 0.01  # Alpha: 1 % mine draw reduction per energy_tech level
MINE_ENERGY_MIN_DRAW_FACTOR = 0.01  # gameplay floor: never 0 draw for active consumers
BUILDTIME_TECH_DURATION = 0.985  # multiplicative: duration × 0.985 ** level (~1.5 % per level)
# Nanofactory: diminishing returns — speed = 1 + coeff × level^exp (not exponential per level).
NANOFACTORY_SPEED_COEFF = 0.55
NANOFACTORY_SPEED_EXPONENT = 0.8
COMMAND_CENTER_NANOFACTORY_DURATION = 0.75  # nanofactory build: × 0.75 ** cc_level
FUEL_EFFICIENCY_PER_LEVEL = 0.03
STORAGE_TECH_PER_LEVEL = 0.15
_DIVISION_EPS = 1e-12  # avoid div-by-zero only; not a balance cap

# Production formulas: game/production_formula.py (GC-820) — do not duplicate here.

# Combat modifiers — consumed by game.combat (GC-504).
COMBAT_MODIFIER_KEYS = frozenset({
    "weapon_bonus",
    "armor_bonus",
    "shield_bonus",
})

# Modifier keys computed but not consumed by any live gameplay engine yet.
PREPARED_MODIFIER_KEYS = frozenset()

ACTIVE_MODIFIER_KEYS = frozenset({
    "mine_energy_factor",
    "metal_prod_factor",
    "crystal_prod_factor",
    "fuel_prod_factor",
    "storage_factor",
    "build_time_speed",
    "research_time_speed",
    "solar_output_factor",
    "fuel_efficiency_factor",
    "fleet_speed_multiplier",
    "cargo_multiplier",
    "shipyard_time_speed",
    "defense_time_speed",
    "scan_range",
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

    BASE_STORAGE = STORAGE_BASE_CAPACITY  # GC-821B — single source in economy_balance
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
        lvl = max(0, int(level or 0))
        if lvl <= 0:
            return 1.0
        return float(BUILDTIME_TECH_DURATION ** lvl)

    @staticmethod
    def buildtime_reduction_pct(level: int) -> int:
        factor = EffectResolver.buildtime_duration_factor_for_level(level)
        return int(round((1.0 - factor) * 100))

    @staticmethod
    def buildtime_speed_bonus_pct(level: int) -> int:
        factor = EffectResolver.buildtime_duration_factor_for_level(level)
        speed = 1.0 / max(factor, _DIVISION_EPS)
        return int(round((speed - 1.0) * 100))

    @staticmethod
    def nanofactory_build_speed(level: int) -> float:
        """Build-speed multiplier from nanofactory level (1.0 = no bonus)."""
        lvl = max(0, int(level or 0))
        if lvl <= 0:
            return 1.0
        return 1.0 + NANOFACTORY_SPEED_COEFF * (float(lvl) ** NANOFACTORY_SPEED_EXPONENT)

    @staticmethod
    def nanofactory_duration_multiplier(level: int) -> float:
        """Duration multiplier from nanofactory (< 1 = faster builds)."""
        speed = EffectResolver.nanofactory_build_speed(level)
        return 1.0 / max(speed, _DIVISION_EPS)

    @staticmethod
    def nanofactory_build_speed_bonus_pct(level: int) -> int:
        speed = EffectResolver.nanofactory_build_speed(level)
        return int(round(max(0.0, speed - 1.0) * 100))

    @staticmethod
    def fuel_efficiency_factor_for_level(level: int) -> float:
        return EffectResolver._reduction_factor(level, FUEL_EFFICIENCY_PER_LEVEL)

    @staticmethod
    def fuel_efficiency_reduction_pct(level: int) -> int:
        return EffectResolver._reduction_pct(level, FUEL_EFFICIENCY_PER_LEVEL)

    @staticmethod
    def metal_prod_bonus_pct(level: int) -> int:
        from ..production_formula import MINING_TECH_PER_LEVEL

        return int(round(MINING_TECH_PER_LEVEL * max(0, int(level or 0)) * 100))

    @staticmethod
    def crystal_prod_bonus_pct(level: int) -> int:
        from ..production_formula import CRYSTAL_TECH_PER_LEVEL

        return int(round(CRYSTAL_TECH_PER_LEVEL * max(0, int(level or 0)) * 100))

    @staticmethod
    def drone_prod_bonus_pct(level: int) -> int:
        from ..production_formula import DRONE_TECH_PER_LEVEL

        return int(round(DRONE_TECH_PER_LEVEL * max(0, int(level or 0)) * 100))

    @staticmethod
    def storage_bonus_pct(level: int) -> int:
        return int(round(STORAGE_TECH_PER_LEVEL * 100 * max(0, int(level or 0))))

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
        planet_position: Optional[int] = None,
        galaxy_id: Optional[int] = None,
        conn=None,
        skip_inventory_boosters: bool = False,
    ) -> None:
        self.buildings = {k: _bld(buildings, k) for k in buildings}
        self.research = dict(research or {})
        self.player_id = int(player_id) if player_id is not None else None
        self.planet_id = int(planet_id) if planet_id is not None else None
        self._skip_inventory_boosters = bool(skip_inventory_boosters)
        if planet_position is not None:
            try:
                pos = int(planet_position)
                self.planet_position = pos if 1 <= pos <= 15 else None
            except (TypeError, ValueError):
                self.planet_position = None
        else:
            self.planet_position = None
        self._conn = conn
        if galaxy_id is not None:
            try:
                self.galaxy_id = int(galaxy_id)
            except (TypeError, ValueError):
                self.galaxy_id = None
        else:
            self.galaxy_id = None
        self._settings = settings
        self._mods: Optional[Dict[str, float]] = None
        self._sources: List[Dict[str, Any]] = []

    @classmethod
    def for_player(
        cls,
        player_id: int,
        conn=None,
        *,
        skip_inventory_boosters: bool = False,
    ) -> EffectResolver:
        planet = get_context_planet(player_id=int(player_id), conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        research = get_research_levels(int(player_id), conn=conn)
        try:
            settings = get_game_settings(conn=conn)
        except TypeError:
            settings = get_game_settings()
        galaxy_raw = planet.get("galaxy")
        galaxy_id = int(galaxy_raw) if galaxy_raw is not None else None
        position_raw = planet.get("position")
        planet_position = int(position_raw) if position_raw not in (None, "") else None
        return cls(
            buildings,
            research,
            settings=settings,
            player_id=int(player_id),
            planet_id=int(planet["id"]),
            planet_position=planet_position,
            galaxy_id=galaxy_id,
            conn=conn,
            skip_inventory_boosters=skip_inventory_boosters,
        )

    def _settings_dict(self) -> Dict[str, Any]:
        if self._settings is not None:
            return self._settings
        # GC-PERF-PANEL-CONN-001: reuse request conn when present (no orphan db()).
        self._settings = get_game_settings(conn=self._conn)
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

    @staticmethod
    def _galactic_directive_source_label(payload: Dict[str, Any]) -> str:
        primary = str(payload.get("primary") or "")
        secondary = payload.get("secondary")
        if not primary:
            return "galactic_directive"
        label = f"gd:{primary}"
        if secondary:
            label += f"+{secondary}"
        return label

    @staticmethod
    def _galactic_diplomacy_source_label(payload: Dict[str, Any]) -> str:
        sources = payload.get("sources") or []
        if not sources:
            return "galactic_diplomacy"
        parts: List[str] = []
        for entry in sources:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            if key:
                parts.append(key)
        if not parts:
            return "galactic_diplomacy"
        return "gdp:" + "+".join(parts)

    def _run_optional_conn_probe(self, label: str, fn):
        """
        Run an optional DB-backed modifier probe.

        On Postgres, wrap in SAVEPOINT so a failure cannot abort an outer write TX
        (queue finish, spend, etc.). Never full-rollback the shared connection here.
        """
        global _ER_SAVEPOINT_SEQ
        conn = self._conn
        if conn is None:
            return fn()
        from ..db import get_db_backend

        use_sp = get_db_backend() == "postgres"
        sp = None
        if use_sp:
            _ER_SAVEPOINT_SEQ = (_ER_SAVEPOINT_SEQ + 1) % 1_000_000
            sp = f"er_{_ER_SAVEPOINT_SEQ}"
            try:
                conn.execute(f"SAVEPOINT {sp}")
            except Exception:
                sp = None
        try:
            out = fn()
        except Exception:
            if use_sp and sp is not None:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                    conn.execute(f"RELEASE SAVEPOINT {sp}")
                except Exception:
                    logger.exception("effect_resolver savepoint rollback failed (%s)", label)
            raise
        if use_sp and sp is not None:
            try:
                conn.execute(f"RELEASE SAVEPOINT {sp}")
            except Exception:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                    conn.execute(f"RELEASE SAVEPOINT {sp}")
                except Exception:
                    logger.exception("effect_resolver savepoint release failed (%s)", label)
                raise
        return out

    def _apply_gd_er_mods(
        self,
        values: Dict[str, float],
        sources: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Apply galaxy-scoped directive effect_resolver modifiers (GC-720E/E2)."""
        if self.galaxy_id is None:
            return values

        try:
            from ..galactic_directives.mechanics import (
                GD_EFFECT_RESOLVER_ADDITIVE_KEYS,
                extract_active_effect_resolver_modifiers,
                get_galaxy_directive_mechanics,
            )

            payload = self._run_optional_conn_probe(
                "gd",
                lambda: get_galaxy_directive_mechanics(self.galaxy_id, conn=self._conn),
            )
        except Exception as exc:
            if EFFECT_DEBUG:
                logger.warning(
                    "galactic_directive_modifiers_failed galaxy=%s err=%s",
                    self.galaxy_id,
                    exc,
                )
            return values

        if not payload:
            return values

        gd_mods = extract_active_effect_resolver_modifiers(payload.get("mechanics"))
        if not gd_mods:
            return values

        label = self._galactic_directive_source_label(payload)
        out = dict(values)
        for gd_key, raw in gd_mods.items():
            if gd_key in GD_EFFECT_RESOLVER_ADDITIVE_KEYS:
                out[gd_key] = float(out.get(gd_key, 0.0)) + float(raw)
            else:
                out[gd_key] = float(out.get(gd_key, 1.0)) * float(raw)
            sources.append(self._source_entry(gd_key, label, float(raw), 0))
        return out

    def _apply_gdp_er_mods(
        self,
        values: Dict[str, float],
        sources: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Apply merged galactic diplomacy effect_resolver modifiers (GC-721H)."""
        if self.galaxy_id is None:
            return values

        try:
            from ..galactic_directives.mechanics import (
                GD_EFFECT_RESOLVER_ADDITIVE_KEYS,
                extract_active_effect_resolver_modifiers,
            )
            from ..galactic_diplomacy.mechanics import get_galaxy_diplomacy_mechanics

            payload = self._run_optional_conn_probe(
                "gdp",
                lambda: get_galaxy_diplomacy_mechanics(self.galaxy_id, conn=self._conn),
            )
        except Exception as exc:
            if EFFECT_DEBUG:
                logger.warning(
                    "galactic_diplomacy_modifiers_failed galaxy=%s err=%s",
                    self.galaxy_id,
                    exc,
                )
            return values

        if not payload:
            return values

        gdp_mods = extract_active_effect_resolver_modifiers(payload.get("mechanics"))
        if not gdp_mods:
            return values

        label = self._galactic_diplomacy_source_label(payload)
        out = dict(values)
        for gdp_key, raw in gdp_mods.items():
            if gdp_key in GD_EFFECT_RESOLVER_ADDITIVE_KEYS:
                out[gdp_key] = float(out.get(gdp_key, 0.0)) + float(raw)
            else:
                out[gdp_key] = float(out.get(gdp_key, 1.0)) * float(raw)
            sources.append(self._source_entry(gdp_key, label, float(raw), 0))
        return out

    def _apply_alliance_mods(
        self,
        values: Dict[str, float],
        sources: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Alliance technology bonuses for members only (EPIC-09)."""
        try:
            from ..alliance import alliance_hub_schema_ready, get_alliance_effect_modifiers

            def _probe():
                if not alliance_hub_schema_ready(self._conn):
                    return None
                return get_alliance_effect_modifiers(int(self.player_id), conn=self._conn)

            amods = self._run_optional_conn_probe("alliance", _probe)
        except Exception as exc:
            if EFFECT_DEBUG:
                logger.warning("alliance_modifiers_failed player=%s err=%s", self.player_id, exc)
            return values

        if not amods:
            return values

        out = dict(values)
        rs = float(amods.get("research_time_speed") or 1.0)
        if rs != 1.0:
            out["research_time_speed"] = float(out.get("research_time_speed", 1.0)) * rs
            sources.append(self._source_entry("research_time_speed", "alliance:research_network", rs, 0))

        for prod_key in ("metal_prod_factor", "crystal_prod_factor", "fuel_prod_factor"):
            pf = float(amods.get(prod_key) or 1.0)
            if pf != 1.0:
                out[prod_key] = float(out.get(prod_key, 1.0)) * pf
        if float(amods.get("metal_prod_factor") or 1.0) != 1.0:
            sources.append(
                self._source_entry(
                    "prod_factor",
                    "alliance:industrial_logistics",
                    float(amods.get("metal_prod_factor") or 1.0),
                    0,
                )
            )

        ab = float(amods.get("armor_bonus") or 0.0)
        sb = float(amods.get("shield_bonus") or 0.0)
        if ab > 0:
            out["armor_bonus"] = float(out.get("armor_bonus", 0.0)) + ab
            sources.append(self._source_entry("armor_bonus", "alliance:defensive_protocols", ab, 0))
        if sb > 0:
            out["shield_bonus"] = float(out.get("shield_bonus", 0.0)) + sb
            sources.append(self._source_entry("shield_bonus", "alliance:defensive_protocols", sb, 0))

        return out

    def _apply_commander_class_mods(
        self,
        values: Dict[str, float],
        sources: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Account commander class skill bonuses (EPIC-27)."""
        try:
            from ..commander_classes import (
                get_commander_effect_modifiers,
                iter_commander_effect_sources,
                schema_ready as commander_schema_ready,
            )

            def _probe():
                if not commander_schema_ready(self._conn):
                    return None
                return (
                    get_commander_effect_modifiers(int(self.player_id), conn=self._conn),
                    iter_commander_effect_sources(int(self.player_id), conn=self._conn),
                )

            probed = self._run_optional_conn_probe("commander_class", _probe)
        except Exception as exc:
            if EFFECT_DEBUG:
                logger.warning("commander_class_modifiers_failed player=%s err=%s", self.player_id, exc)
            return values

        if not probed:
            return values
        cmods, csrc = probed
        if not cmods:
            return values

        from ..commander_class_catalog import ADDITIVE_MOD_KEYS

        out = dict(values)
        for key, raw in cmods.items():
            if key.startswith("_"):
                continue
            if key in ADDITIVE_MOD_KEYS:
                out[key] = float(out.get(key, 0.0)) + float(raw)
            else:
                out[key] = float(out.get(key, 1.0)) * float(raw)
        for mod_key, label, amount in csrc or []:
            sources.append(
                self._source_entry(
                    mod_key,
                    label,
                    float(amount),
                    0,
                    prepared=False,
                )
            )
        return out

    def _apply_galactic_directive_modifiers(
        self,
        *,
        mine_energy_factor: float,
        metal_prod_factor: float,
        crystal_prod_factor: float,
        fuel_prod_factor: float,
        storage_factor: float,
        build_time_speed: float,
        research_time_speed: float,
        solar_output_factor: float,
        sources: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Backward-compatible economy-only wrapper (GC-720E)."""
        applied = self._apply_gd_er_mods(
            {
                "mine_energy_factor": mine_energy_factor,
                "metal_prod_factor": metal_prod_factor,
                "crystal_prod_factor": crystal_prod_factor,
                "fuel_prod_factor": fuel_prod_factor,
                "storage_factor": storage_factor,
                "build_time_speed": build_time_speed,
                "research_time_speed": research_time_speed,
                "solar_output_factor": solar_output_factor,
            },
            sources,
        )
        return {
            "mine_energy_factor": applied["mine_energy_factor"],
            "metal_prod_factor": applied["metal_prod_factor"],
            "crystal_prod_factor": applied["crystal_prod_factor"],
            "fuel_prod_factor": applied["fuel_prod_factor"],
            "storage_factor": applied["storage_factor"],
            "build_time_speed": applied["build_time_speed"],
            "research_time_speed": applied["research_time_speed"],
            "solar_output_factor": applied["solar_output_factor"],
        }

    def _apply_climate_modifiers(
        self,
        values: Dict[str, float],
        sources: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Galaxy slot climate — solar output only; mine production uses production_formula slot/temp (GC-820)."""
        pos = self.planet_position
        if pos is None:
            return values

        from ..planet_visuals import climate_economy_modifiers_for_position

        climate = climate_economy_modifiers_for_position(pos)
        label = f"climate:{climate['label_key']}"
        out = dict(values)
        factor = float(climate["solar_output_factor"])
        if abs(factor - 1.0) >= 1e-9:
            out["solar_output_factor"] = float(out.get("solar_output_factor", 1.0)) * factor
            sources.append(self._source_entry("solar_output_factor", label, factor, pos))
        return out

    def _apply_inventory_booster_mods(
        self,
        values: Dict[str, float],
        sources: List[Dict[str, Any]],
    ) -> Dict[str, float]:
        """GC-968A — timed pct boosters from inventory use."""
        if getattr(self, "_skip_inventory_boosters", False):
            return values
        if self.player_id is None or self._conn is None:
            return values
        try:
            from ..inventory_boosters import (
                EFFECT_RESOLVER_BOOSTER_KEYS,
                boosters_schema_ready,
                get_active_booster_multipliers,
            )
        except Exception:
            return values
        try:
            def _probe():
                if not boosters_schema_ready(self._conn):
                    return {}
                return get_active_booster_multipliers(int(self.player_id), conn=self._conn)

            mults = self._run_optional_conn_probe("boosters", _probe) or {}
        except Exception as exc:
            if EFFECT_DEBUG:
                logger.warning(
                    "inventory_booster_modifiers_failed player=%s err=%s",
                    self.player_id,
                    exc,
                )
            return values
        if not mults:
            return values
        out = dict(values)
        for key, mult in mults.items():
            if key not in EFFECT_RESOLVER_BOOSTER_KEYS:
                continue
            factor = float(mult)
            if factor <= 1.0:
                continue
            out[key] = float(out.get(key, 1.0)) * factor
            sources.append(self._source_entry(key, f"inventory_booster:{key}", factor, 0))
        return out

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
        fuel_prod_factor = 1.0
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
        shipyard_time_speed = 1.0
        defense_time_speed = 1.0

        # --- Research: energy_tech (-5% mine draw per level; mines only, not solar) ---
        le = _lvl(r, "energy_tech")
        if le > 0:
            mine_energy_factor = self.mine_energy_factor_for_level(le)
            sources.append(self._source_entry("mine_energy_factor", "energy_tech", mine_energy_factor, le))

        # --- Research: mining_tech (+3% Ferronit per level — GC-820) ---
        lm = _lvl(r, "mining_tech")
        if lm > 0:
            from ..production_formula import MINING_TECH_PER_LEVEL

            metal_prod_factor *= 1.0 + MINING_TECH_PER_LEVEL * lm
            sources.append(self._source_entry("metal_prod_factor", "mining_tech", metal_prod_factor, lm))

        # --- Research: crystal_tech (+3% Crytite per level) ---
        lc = _lvl(r, "crystal_tech")
        if lc > 0:
            from ..production_formula import CRYSTAL_TECH_PER_LEVEL

            crystal_prod_factor *= 1.0 + CRYSTAL_TECH_PER_LEVEL * lc
            sources.append(self._source_entry("crystal_prod_factor", "crystal_tech", crystal_prod_factor, lc))

        # --- Research: drone_tech (+2% Ferronit + Crytite per level — GC-820) ---
        ld = _lvl(r, "drone_tech")
        if ld > 0:
            from ..production_formula import DRONE_TECH_PER_LEVEL

            drone_bonus = 1.0 + DRONE_TECH_PER_LEVEL * ld
            metal_prod_factor *= drone_bonus
            crystal_prod_factor *= drone_bonus
            sources.append(self._source_entry("prod_factor", "drone_tech", drone_bonus, ld))

        # --- Research: storage_tech (+15% storage per level, additive) ---
        ls = _lvl(r, "storage_tech")
        if ls > 0:
            storage_factor *= 1.0 + STORAGE_TECH_PER_LEVEL * ls
            sources.append(self._source_entry("storage_factor", "storage_tech", storage_factor, ls))

        # --- Research: buildtime_tech (duration × BUILDTIME_TECH_DURATION ** level) ---
        lb = _lvl(r, "buildtime_tech")
        if lb > 0:
            duration_factor = float(BUILDTIME_TECH_DURATION ** lb)
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
            sources.append(self._source_entry("fleet_speed_multiplier", "navigation_tech", fleet_speed_multiplier, lhn))

        leng = _lvl(r, "engine_tech")
        if leng > 0:
            fleet_speed_multiplier *= 1.0 + 0.02 * leng
            cargo_multiplier *= 1.0 + 0.02 * leng
            sources.append(self._source_entry("fleet_speed_multiplier", "engine_tech", fleet_speed_multiplier, leng))
            sources.append(self._source_entry("cargo_multiplier", "engine_tech", cargo_multiplier, leng))

        # --- Buildings: nanofactory (diminishing returns — applied in get_build_time_duration_multiplier) ---
        nano = _bld(b, "nanofactory")
        if nano > 0:
            nano_speed = self.nanofactory_build_speed(nano)
            sources.append(
                self._source_entry(
                    "build_time_speed",
                    "nanofactory",
                    nano_speed,
                    nano,
                )
            )

        # command_center nanofactory-only boost in get_build_time_duration_multiplier()

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

        # --- Buildings: barracks (+2% shipyard speed per level) ---
        barracks = _bld(b, "barracks")
        if barracks > 0:
            shipyard_time_speed *= 1.0 + 0.02 * barracks
            sources.append(
                self._source_entry("shipyard_time_speed", "barracks", shipyard_time_speed, barracks)
            )

        # --- Buildings: shield_generator (+2% combat shield per level) ---
        shield_gen = _bld(b, "shield_generator")
        if shield_gen > 0:
            shield_bonus += 0.02 * shield_gen
            sources.append(
                self._source_entry("shield_bonus", "shield_generator", shield_bonus, shield_gen)
            )

        # --- Radar: scan_range (Deep-Space Threat Net) ---
        radar = _bld(b, "radar_array")
        if radar > 0:
            scan_range += 2 * radar
            sources.append(self._source_entry("scan_range", "radar_array", scan_range, radar))

        climate_state = self._apply_climate_modifiers(
            {
                "mine_energy_factor": mine_energy_factor,
                "metal_prod_factor": metal_prod_factor,
                "crystal_prod_factor": crystal_prod_factor,
                "fuel_prod_factor": fuel_prod_factor,
                "storage_factor": storage_factor,
                "build_time_speed": build_time_speed,
                "research_time_speed": research_time_speed,
                "solar_output_factor": solar_output_factor,
                "weapon_bonus": weapon_bonus,
                "armor_bonus": armor_bonus,
                "shield_bonus": shield_bonus,
                "fleet_speed_multiplier": fleet_speed_multiplier,
                "cargo_multiplier": cargo_multiplier,
                "fuel_efficiency_factor": fuel_efficiency_factor,
                "shipyard_time_speed": shipyard_time_speed,
                "defense_time_speed": defense_time_speed,
            },
            sources,
        )
        mine_energy_factor = climate_state["mine_energy_factor"]
        metal_prod_factor = climate_state["metal_prod_factor"]
        crystal_prod_factor = climate_state["crystal_prod_factor"]
        fuel_prod_factor = climate_state["fuel_prod_factor"]
        storage_factor = climate_state["storage_factor"]
        build_time_speed = climate_state["build_time_speed"]
        research_time_speed = climate_state["research_time_speed"]
        solar_output_factor = climate_state["solar_output_factor"]
        weapon_bonus = climate_state["weapon_bonus"]
        armor_bonus = climate_state["armor_bonus"]
        shield_bonus = climate_state["shield_bonus"]
        fleet_speed_multiplier = climate_state["fleet_speed_multiplier"]
        cargo_multiplier = climate_state["cargo_multiplier"]
        fuel_efficiency_factor = climate_state["fuel_efficiency_factor"]
        shipyard_time_speed = climate_state["shipyard_time_speed"]
        defense_time_speed = climate_state["defense_time_speed"]

        gd_state = self._apply_gd_er_mods(
            {
                "mine_energy_factor": mine_energy_factor,
                "metal_prod_factor": metal_prod_factor,
                "crystal_prod_factor": crystal_prod_factor,
                "fuel_prod_factor": fuel_prod_factor,
                "storage_factor": storage_factor,
                "build_time_speed": build_time_speed,
                "research_time_speed": research_time_speed,
                "solar_output_factor": solar_output_factor,
                "weapon_bonus": weapon_bonus,
                "armor_bonus": armor_bonus,
                "shield_bonus": shield_bonus,
                "fleet_speed_multiplier": fleet_speed_multiplier,
                "cargo_multiplier": cargo_multiplier,
                "fuel_efficiency_factor": fuel_efficiency_factor,
                "shipyard_time_speed": shipyard_time_speed,
                "defense_time_speed": defense_time_speed,
            },
            sources,
        )
        gd_state = self._apply_gdp_er_mods(gd_state, sources)
        mine_energy_factor = gd_state["mine_energy_factor"]
        metal_prod_factor = gd_state["metal_prod_factor"]
        crystal_prod_factor = gd_state["crystal_prod_factor"]
        fuel_prod_factor = gd_state["fuel_prod_factor"]
        storage_factor = gd_state["storage_factor"]
        build_time_speed = gd_state["build_time_speed"]
        research_time_speed = gd_state["research_time_speed"]
        solar_output_factor = gd_state["solar_output_factor"]
        weapon_bonus = gd_state["weapon_bonus"]
        armor_bonus = gd_state["armor_bonus"]
        shield_bonus = gd_state["shield_bonus"]
        fleet_speed_multiplier = gd_state["fleet_speed_multiplier"]
        cargo_multiplier = gd_state["cargo_multiplier"]
        fuel_efficiency_factor = gd_state["fuel_efficiency_factor"]
        shipyard_time_speed = gd_state["shipyard_time_speed"]
        defense_time_speed = gd_state["defense_time_speed"]

        if self.player_id is not None and self._conn is not None:
            ib_state = self._apply_inventory_booster_mods(
                {
                    "mine_energy_factor": mine_energy_factor,
                    "metal_prod_factor": metal_prod_factor,
                    "crystal_prod_factor": crystal_prod_factor,
                    "fuel_prod_factor": fuel_prod_factor,
                    "storage_factor": storage_factor,
                    "build_time_speed": build_time_speed,
                    "research_time_speed": research_time_speed,
                    "solar_output_factor": solar_output_factor,
                    "weapon_bonus": weapon_bonus,
                    "armor_bonus": armor_bonus,
                    "shield_bonus": shield_bonus,
                    "fleet_speed_multiplier": fleet_speed_multiplier,
                    "cargo_multiplier": cargo_multiplier,
                    "fuel_efficiency_factor": fuel_efficiency_factor,
                    "shipyard_time_speed": shipyard_time_speed,
                    "defense_time_speed": defense_time_speed,
                },
                sources,
            )
            mine_energy_factor = ib_state["mine_energy_factor"]
            metal_prod_factor = ib_state["metal_prod_factor"]
            crystal_prod_factor = ib_state["crystal_prod_factor"]
            fuel_prod_factor = ib_state["fuel_prod_factor"]
            storage_factor = ib_state["storage_factor"]
            build_time_speed = ib_state["build_time_speed"]
            research_time_speed = ib_state["research_time_speed"]
            solar_output_factor = ib_state["solar_output_factor"]
            weapon_bonus = ib_state["weapon_bonus"]
            armor_bonus = ib_state["armor_bonus"]
            shield_bonus = ib_state["shield_bonus"]
            fleet_speed_multiplier = ib_state["fleet_speed_multiplier"]
            cargo_multiplier = ib_state["cargo_multiplier"]
            fuel_efficiency_factor = ib_state["fuel_efficiency_factor"]
            shipyard_time_speed = ib_state["shipyard_time_speed"]
            defense_time_speed = ib_state["defense_time_speed"]

        if self.player_id is not None and self._conn is not None:
            alliance_state = self._apply_alliance_mods(
                {
                    "research_time_speed": research_time_speed,
                    "metal_prod_factor": metal_prod_factor,
                    "crystal_prod_factor": crystal_prod_factor,
                    "fuel_prod_factor": fuel_prod_factor,
                    "armor_bonus": armor_bonus,
                    "shield_bonus": shield_bonus,
                },
                sources,
            )
            research_time_speed = alliance_state["research_time_speed"]
            metal_prod_factor = alliance_state["metal_prod_factor"]
            crystal_prod_factor = alliance_state["crystal_prod_factor"]
            fuel_prod_factor = alliance_state["fuel_prod_factor"]
            armor_bonus = alliance_state["armor_bonus"]
            shield_bonus = alliance_state["shield_bonus"]

        if self.player_id is not None and self._conn is not None:
            class_state = self._apply_commander_class_mods(
                {
                    "mine_energy_factor": mine_energy_factor,
                    "metal_prod_factor": metal_prod_factor,
                    "crystal_prod_factor": crystal_prod_factor,
                    "fuel_prod_factor": fuel_prod_factor,
                    "storage_factor": storage_factor,
                    "build_time_speed": build_time_speed,
                    "research_time_speed": research_time_speed,
                    "solar_output_factor": solar_output_factor,
                    "weapon_bonus": weapon_bonus,
                    "armor_bonus": armor_bonus,
                    "shield_bonus": shield_bonus,
                    "scan_range": float(scan_range),
                    "fleet_speed_multiplier": fleet_speed_multiplier,
                    "cargo_multiplier": cargo_multiplier,
                    "fuel_efficiency_factor": fuel_efficiency_factor,
                    "shipyard_time_speed": shipyard_time_speed,
                    "defense_time_speed": defense_time_speed,
                },
                sources,
            )
            mine_energy_factor = class_state.get("mine_energy_factor", mine_energy_factor)
            metal_prod_factor = class_state["metal_prod_factor"]
            crystal_prod_factor = class_state["crystal_prod_factor"]
            fuel_prod_factor = class_state["fuel_prod_factor"]
            storage_factor = class_state.get("storage_factor", storage_factor)
            build_time_speed = class_state.get("build_time_speed", build_time_speed)
            research_time_speed = class_state["research_time_speed"]
            solar_output_factor = class_state.get("solar_output_factor", solar_output_factor)
            weapon_bonus = class_state.get("weapon_bonus", weapon_bonus)
            armor_bonus = class_state["armor_bonus"]
            shield_bonus = class_state["shield_bonus"]
            scan_range = int(class_state.get("scan_range", scan_range) or 0)
            fleet_speed_multiplier = class_state.get("fleet_speed_multiplier", fleet_speed_multiplier)
            cargo_multiplier = class_state.get("cargo_multiplier", cargo_multiplier)
            fuel_efficiency_factor = class_state.get("fuel_efficiency_factor", fuel_efficiency_factor)
            shipyard_time_speed = class_state.get("shipyard_time_speed", shipyard_time_speed)
            defense_time_speed = class_state.get("defense_time_speed", defense_time_speed)

        # LiveOps server events (global timed bonuses) — after personal boosters/classes.
        try:
            from ..server_events import active_build_time_speed, active_research_time_speed

            sev_build = float(active_build_time_speed(conn=self._conn) or 1.0)
            sev_research = float(active_research_time_speed(conn=self._conn) or 1.0)
            if sev_build > 0 and abs(sev_build - 1.0) > 1e-12:
                build_time_speed *= sev_build
                sources.append(
                    self._source_entry("build_time_speed", "server_event:build_time", sev_build, 0)
                )
            if sev_research > 0 and abs(sev_research - 1.0) > 1e-12:
                research_time_speed *= sev_research
                sources.append(
                    self._source_entry(
                        "research_time_speed", "server_event:research_time", sev_research, 0
                    )
                )
        except Exception as exc:
            if EFFECT_DEBUG:
                logger.warning("server_event_time_speed_failed err=%s", exc)

        self._mods = {
            "mine_energy_factor": float(mine_energy_factor),
            "metal_prod_factor": float(metal_prod_factor),
            "crystal_prod_factor": float(crystal_prod_factor),
            "fuel_prod_factor": float(fuel_prod_factor),
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
            "shipyard_time_speed": float(shipyard_time_speed),
            "defense_time_speed": float(defense_time_speed),
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
        ratio = self.energy_ratio(energy_total, energy_used)
        m_rate, c_rate = self.production_rates_per_sec(ratio)
        caps = self.get_storage_capacity()
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
                "metal": int(m_rate * 3600),
                "crystal": int(c_rate * 3600),
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
                    "fuel_cell_plant",
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

    @staticmethod
    def solar_energy_base_at_level(level: int) -> int:
        """GC-863 — solar output matches combined mine draw at the same level + 1."""
        lvl = max(0, int(level or 0))
        if lvl <= 0:
            return 0
        draw = (
            int(10 * (lvl ** 1.25))
            + int(6 * (lvl ** 1.25))
            + int(8 * (lvl ** 1.25))
        )
        return draw + 1

    def compute_energy(self) -> Tuple[int, int]:
        mods = self.get_modifiers()
        b = self.buildings

        solar_lvl = _bld(b, "solar_plant")
        metal_lvl = _bld(b, "metal_mine")
        crystal_lvl = _bld(b, "crystal_mine")

        solar_factor = _mod_float(mods, "solar_output_factor")
        energy_total = (
            int(self.solar_energy_base_at_level(solar_lvl) * solar_factor) if solar_lvl > 0 else 0
        )

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

    def prod_overlay_factor(self, resource_type: str) -> float:
        """GD + diplomacy overlay for production (excludes research; slot/temp in production_formula)."""
        from ..production_formula import normalize_resource_type, research_modifier_for

        key = normalize_resource_type(resource_type)
        mods = self.get_modifiers()
        research_part = research_modifier_for(key, self.research)
        if key == "metal":
            full = _mod_float(mods, "metal_prod_factor")
        elif key == "crystal":
            full = _mod_float(mods, "crystal_prod_factor")
        else:
            full = _mod_float(mods, "fuel_prod_factor")
        return full / max(research_part, 1e-12)

    def production_rates_per_sec(self, energy_ratio: float = 1.0) -> Tuple[float, float]:
        from ..production_formula import calculate_resource_output, production_context_from_resolver

        ratio_f = max(0.0, float(energy_ratio))
        ctx_m = production_context_from_resolver(self, "metal", energy_ratio=ratio_f)
        ctx_c = production_context_from_resolver(self, "crystal", energy_ratio=ratio_f)
        metal_ph = calculate_resource_output("metal", ctx_m)
        crystal_ph = calculate_resource_output("crystal", ctx_c)
        return metal_ph / 3600.0, crystal_ph / 3600.0

    def fuel_cells_rate_per_sec(self, energy_ratio: float = 1.0) -> float:
        per_hour = self.fuel_cells_production_per_hour(energy_ratio)
        return per_hour / 3600.0 if per_hour > 0 else 0.0

    def fuel_cells_production_per_hour(self, energy_ratio: float = 1.0) -> float:
        from ..production_formula import calculate_resource_output, production_context_from_resolver

        ratio_f = max(0.0, float(energy_ratio))
        ctx = production_context_from_resolver(self, "fuel_cells", energy_ratio=ratio_f)
        return calculate_resource_output("fuel_cells", ctx)

    def fuel_storage_capacity(self) -> int:
        """Planet fuel cell depot capacity (base cap + fuel_storage building + tech/terraformer)."""
        mods = self.get_modifiers()
        b = self.buildings

        terra_lvl = _bld(b, "terraformer")
        terra_factor = 1.0 + 0.05 * terra_lvl
        storage_factor = _mod_float(mods, "storage_factor") * terra_factor

        f_lvl = _bld(b, "fuel_storage")
        f_cap = self._storage_base_cap("fuel_cells", f_lvl)
        return int(f_cap * storage_factor)

    def fuel_cells_storage_capacity(self) -> int:
        """Authoritative fuel_cells cap — same base storage as metal/crystal without depot."""
        return self.fuel_storage_capacity()

    def _storage_base_cap(self, resource: str, storage_level: int) -> int:
        """GC-872 Ferdi reference depot cap; resource-independent."""
        from ..economy_balance import storage_capacity_at_depot_level

        _ = resource
        return storage_capacity_at_depot_level(max(0, int(storage_level)))

    def _metal_crystal_storage_base_cap(self, resource: str, storage_level: int) -> int:
        """Backward-compatible alias — use _storage_base_cap."""
        return self._storage_base_cap(resource, storage_level)

    def get_storage_capacity(self) -> Dict[str, int]:
        mods = self.get_modifiers()
        b = self.buildings

        terra_lvl = _bld(b, "terraformer")
        terra_factor = 1.0 + 0.05 * terra_lvl
        storage_factor = _mod_float(mods, "storage_factor") * terra_factor

        m_lvl = _bld(b, "metal_storage")
        c_lvl = _bld(b, "crystal_storage")

        m_cap = self._metal_crystal_storage_base_cap("metal", m_lvl)
        c_cap = self._metal_crystal_storage_base_cap("crystal", c_lvl)

        return {
            "metal": int(m_cap * storage_factor),
            "crystal": int(c_cap * storage_factor),
            "fuel_cells": self.fuel_cells_storage_capacity(),
        }

    def get_building_production_per_hour(self, ratio: float) -> Dict[str, int]:
        from ..production_formula import calculate_resource_output, production_context_from_resolver

        ratio_f = max(0.0, float(ratio))
        metal_ph = int(calculate_resource_output(
            "metal", production_context_from_resolver(self, "metal", energy_ratio=ratio_f)
        ))
        crystal_ph = int(calculate_resource_output(
            "crystal", production_context_from_resolver(self, "crystal", energy_ratio=ratio_f)
        ))
        fuel_cell_ph = int(calculate_resource_output(
            "fuel_cells", production_context_from_resolver(self, "fuel_cells", energy_ratio=ratio_f)
        ))
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

        if building_type in (
            "metal_mine",
            "crystal_mine",
            "solar_plant",
            "fuel_cell_plant",
        ):
            return base_max + core + geo * 2
        if building_type in ("metal_storage", "crystal_storage", "fuel_storage"):
            return base_max + geo * 2
        return base_max

    def get_build_time_duration_multiplier(self, building_type: str) -> float:
        """Building-specific duration multiplier (< 1 = faster). Excludes buildtime_tech + GD."""
        mult = 1.0
        nano = _bld(self.buildings, "nanofactory")
        if nano > 0:
            mult *= self.nanofactory_duration_multiplier(nano)
        if str(building_type) == "nanofactory":
            cc = _bld(self.buildings, "command_center")
            if cc > 0:
                mult *= float(COMMAND_CENTER_NANOFACTORY_DURATION ** cc)
        return mult

    def get_build_time_player_speed(self, building_type: str) -> float:
        """Player-owned build speed multiplier (excludes admin build_speed setting)."""
        mods = self.get_modifiers()
        base_speed = _mod_float(mods, "build_time_speed")
        building_duration = max(self.get_build_time_duration_multiplier(building_type), _DIVISION_EPS)
        return max(0.1, base_speed / building_duration)

    def get_build_time_effective_speed(self, building_type: str) -> float:
        """Authoritative build-time speed multiplier (higher = faster builds)."""
        return max(0.1, self.get_build_time_player_speed(building_type) * self.build_speed_setting())

    def get_build_time_duration_factor(self, building_type: str) -> float:
        """Actual build duration / unmodified duration (player bonuses only)."""
        return 1.0 / self.get_build_time_player_speed(building_type)

    def get_build_time_speed_bonus_pct(self, building_type: str) -> int:
        """Card/technical speed bonus display: (speed − 1) × 100."""
        speed = self.get_build_time_player_speed(building_type)
        return int(round(max(0.0, speed - 1.0) * 100))

    def get_build_time_reduction_pct(self, building_type: str) -> int:
        """Legacy reduction display derived from the same player speed."""
        factor = self.get_build_time_duration_factor(building_type)
        return int(round(max(0.0, (1.0 - factor) * 100)))

    def get_build_time_seconds(self, building_type: str, target_level: int) -> int:
        from ..economy_balance import power_build_seconds

        seconds = float(power_build_seconds(building_type, int(target_level)))
        seconds /= self.get_build_time_effective_speed(building_type)
        return max(int(seconds), 1)

    def get_research_time_seconds(self, tech_key: str, target_level: int) -> int:
        from ..research import RESEARCH_TECHS

        cfg = RESEARCH_TECHS.get(tech_key)
        if not cfg:
            return 0

        base_time = float(cfg.get("base_time", 600))
        lvl = max(1, int(target_level))

        from ..economy_balance import research_base_time_seconds, research_time_tier

        raw = float(research_base_time_seconds(lvl, time_tier=research_time_tier(base_time)))

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
    planet: Optional[Dict[str, Any]] = None,
    skip_inventory_boosters: bool = False,
) -> EffectResolver:
    """
    Build an EffectResolver, reusing a request-scoped instance when inputs match
    (GC-PERF-EFFECT-CACHE-001).

    ``force_refresh=True`` bypasses the cache read, builds fresh, and stores the
    new instance. Pass ``planet`` when resolving a specific colony.
    """
    uid = int(player_id)
    skip_boosters = bool(skip_inventory_boosters)

    if buildings is not None and research is not None:
        planet_id = None
        planet_position = None
        galaxy_id = None
        planet_row = planet
        if planet_row is None:
            try:
                planet_row = get_context_planet(player_id=uid, conn=conn)
            except Exception:
                planet_row = None
        if planet_row is not None:
            try:
                planet_id = int(planet_row["id"])
            except (TypeError, ValueError, KeyError):
                planet_id = None
            try:
                from ..galaxy import get_planet_coordinates

                coords = get_planet_coordinates(planet_row)
                if coords.get("position") is not None:
                    planet_position = int(coords["position"])
                if coords.get("galaxy") is not None:
                    galaxy_id = int(coords["galaxy"])
            except Exception:
                pass

        key = _resolver_cache_key(
            uid,
            planet_id,
            buildings,
            research,
            galaxy_id,
            planet_position,
            skip_boosters,
        )
        if not force_refresh:
            hit = _resolver_cache_get(key)
            if hit is not None:
                return hit

        resolver = EffectResolver(
            buildings,
            research,
            settings=settings,
            player_id=uid,
            planet_id=planet_id,
            planet_position=planet_position,
            galaxy_id=galaxy_id,
            conn=conn,
            skip_inventory_boosters=skip_boosters,
        )
        _resolver_cache_put(key, resolver)
        return resolver

    # for_player path: load inputs, then same identity cache.
    planet_row = get_context_planet(player_id=uid, conn=conn)
    loaded_buildings = get_planet_buildings(int(planet_row["id"]), conn=conn)
    loaded_research = get_research_levels(uid, conn=conn)
    galaxy_raw = planet_row.get("galaxy")
    galaxy_id = int(galaxy_raw) if galaxy_raw is not None else None
    position_raw = planet_row.get("position")
    planet_position = int(position_raw) if position_raw not in (None, "") else None
    planet_id = int(planet_row["id"])

    key = _resolver_cache_key(
        uid,
        planet_id,
        loaded_buildings,
        loaded_research,
        galaxy_id,
        planet_position,
        skip_boosters,
    )
    if not force_refresh:
        hit = _resolver_cache_get(key)
        if hit is not None:
            return hit

    try:
        loaded_settings = get_game_settings(conn=conn) if settings is None else settings
    except TypeError:
        loaded_settings = get_game_settings() if settings is None else settings

    resolver = EffectResolver(
        loaded_buildings,
        loaded_research,
        settings=loaded_settings,
        player_id=uid,
        planet_id=planet_id,
        planet_position=planet_position,
        galaxy_id=galaxy_id,
        conn=conn,
        skip_inventory_boosters=skip_boosters,
    )
    _resolver_cache_put(key, resolver)
    return resolver


def _levels_fp(levels: Optional[Dict[str, int]]) -> Tuple[Tuple[str, int], ...]:
    if not levels:
        return ()
    return tuple(sorted((str(k), int(v or 0)) for k, v in levels.items()))


def _resolver_cache_key(
    player_id: int,
    planet_id: Optional[int],
    buildings: Optional[Dict[str, int]],
    research: Optional[Dict[str, int]],
    galaxy_id: Optional[int],
    planet_position: Optional[int],
    skip_inventory_boosters: bool,
) -> tuple:
    return (
        int(player_id),
        int(planet_id) if planet_id is not None else None,
        _levels_fp(buildings),
        _levels_fp(research),
        int(galaxy_id) if galaxy_id is not None else None,
        int(planet_position) if planet_position is not None else None,
        bool(skip_inventory_boosters),
    )


def _resolver_cache_map() -> Dict[tuple, EffectResolver]:
    cache = _RESOLVER_CACHE.get()
    if cache is None:
        cache = {}
        _RESOLVER_CACHE.set(cache)
    return cache


def _resolver_cache_get(key: tuple) -> Optional[EffectResolver]:
    return _resolver_cache_map().get(key)


def _resolver_cache_put(key: tuple, resolver: EffectResolver) -> None:
    _resolver_cache_map()[key] = resolver


def clear_effect_resolver_cache(player_id: Optional[int] = None) -> None:
    """Drop request-scoped resolver entries (all, or one player)."""
    cache = _RESOLVER_CACHE.get()
    if not cache:
        return
    if player_id is None:
        cache.clear()
        return
    pid = int(player_id)
    for key in list(cache.keys()):
        if key and key[0] == pid:
            del cache[key]
