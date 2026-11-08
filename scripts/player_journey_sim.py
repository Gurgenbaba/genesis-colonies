#!/usr/bin/env python3
"""GC Trait-R3 player-journey simulator (measurement only).

Implements the measurement contract of ``docs/GC_TRAIT_R3_PLAYER_JOURNEY_GATE.md``:
fresh-account trajectories (S1 = one homeworld, S11 = legal expansion towards
eleven worlds) over 182.5 / 365 days for three play styles, next to the
optimistic record-mine upper bounds of ``scripts/audit_long_horizon_economy.py``.

Design rules
------------
* No gameplay change, no new DB tables, no deployment.  Everything runs against
  a throw-away SQLite sandbox created from the repository migrations, never a
  live database.
* No duplicated formulas.  Economy, costs, timers, storage and energy come from
  ``EffectResolver`` / ``economy_balance`` / ``buildings`` / ``research``.  Planet
  XP, reveal tiers, DNA scans, colonisation gates and colony founding are executed
  by the canonical owners (``activity_xp``, ``planet_level``, ``dna_analysis``,
  ``expansion_protocol``, ``colonize_planet``) inside the sandbox.
* Deterministic.  There is no RNG; the decision policy is versioned
  (``POLICY_VERSION``) and every blocker / skipped interval is reconstructible.

Run:
  python scripts/player_journey_sim.py --quick --stdout
  python scripts/player_journey_sim.py --out-json artifacts/player_journey/latest.json \
      --out-md docs/GC_TRAIT_R3_PLAYER_JOURNEY_REPORT.md
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.buildings import (  # noqa: E402
    ALL_BUILDINGS,
    BUILDING_REQUIREMENTS,
    _effective_building_queue_cap,
    _nodebuster_rebuild_bps,
    _resolve_build_queue_limit,
    _scale_bps,
    get_upgrade_cost,
    has_building_requirements,
)
from game.economy_balance import research_empire_maturity_index  # noqa: E402
from game.effects import EffectResolver  # noqa: E402
from game.exchange import (  # noqa: E402
    _min_give_amount,
    _preview_receive,
    _route_enabled,
    get_exchange_config,
    trade_would_increase_score,
)
from game.fleet_defs import get_ship  # noqa: E402
from game.mine_evolution import nodebuster as nodebuster_mod  # noqa: E402
from game.mine_evolution.formulas import EVOLVABLE_MINES  # noqa: E402
from game.mine_evolution.nodebuster import ascension_points_for_depth  # noqa: E402
from game.models import DEFAULT_GAME_SETTINGS  # noqa: E402
from game.planet_evolution import dna_analysis  # noqa: E402
from game.planet_evolution.constants import (  # noqa: E402
    ASCENSION_UNLOCK_LEVEL,
    MAX_PLANET_LEVEL,
    SPECIALIZATION_UNLOCK_LEVEL,
)
from game.planet_evolution.definitions import get_ascension as get_ascension_def  # noqa: E402
from game.planet_evolution.expansion_phase import ESTABLISHMENT_MILESTONE_DEFS  # noqa: E402
from game.planet_evolution.expansion_protocol import (  # noqa: E402
    COLONY_MATURITY_REQUIRED_LEVEL,
    EXPANSION_SLOT_GATES,
    INTERSTELLAR_EXPANSION_TECH,
    OUTPOST_ALLOWED_BUILDINGS,
    WORLD_TYPE_GATES,
)
from game.planet_evolution.planet_level import xp_threshold_for_level  # noqa: E402
from game.research import (  # noqa: E402
    RESEARCH_TECHS,
    _resolve_research_queue_limit,
    get_research_payment_cost,
    has_research_requirements,
)
from game.shipyard import production_level_cycle_seconds  # noqa: E402
from game.time_floors import building_progress_floor_seconds  # noqa: E402

# One simulated universe at a time per process.  The simulator patches process-global state (endgame curve, colony gate,
# database path, environment) for the duration of a run; this re-entrant lock makes concurrent callers (threads) queue instead
# of silently reading each other's parameters.  Separate processes (the analysis runners) are isolated by the OS.
SIM_LOCK = threading.RLock()


def universe_key() -> Tuple[Any, ...]:
    """Every process-global parameter that can change a price, a production figure or a gate - the cache key of the simulator."""
    from game import production_formula as pf
    from game.planet_evolution import expansion_protocol as ep

    return (
        str(pf.ENDGAME_ECONOMY_MODE),
        int(pf.ENDGAME_PRODUCTION_PIVOT_LEVEL),
        int(pf.ENDGAME_PRODUCTION_TAIL_POWER),
        int(ep.COLONY_MATURITY_REQUIRED_LEVEL),
    )


@functools.lru_cache(maxsize=None)
def _upgrade_cost_in(universe: Tuple[Any, ...], key: str, level: int) -> Tuple[int, int]:
    return get_upgrade_cost(key, level)


def _upgrade_cost(key: str, level: int) -> Tuple[int, int]:
    """Canonical upgrade price, cached per universe: a lookup under another endgame curve can never serve a stale price."""
    return _upgrade_cost_in(universe_key(), key, int(level))


_upgrade_cost.cache_clear = _upgrade_cost_in.cache_clear  # type: ignore[attr-defined]


@functools.lru_cache(maxsize=200_000)
def _research_payment_in(universe: Tuple[Any, ...], tech: str, level: int, income: Any, maturity: Any, worlds: Any) -> Tuple[int, int]:
    return get_research_payment_cost(tech, level, cost_context={"empire_combined_per_hour": income, "maturity_index": maturity, "world_count": worlds})


def _research_payment(tech: str, level: int, income: Any, maturity: Any, worlds: Any) -> Tuple[int, int]:
    return _research_payment_in(universe_key(), tech, level, income, maturity, worlds)


_research_payment.cache_clear = _research_payment_in.cache_clear  # type: ignore[attr-defined]

SANDBOX_RNG_SEED = 20_261_106
ELIGIBLE_HOME_SEED = 2  # homeworld DNA with 3 eligible specialisations (guarded by a test); the default seed has none
MANDATE_START_WORLDS = 3  # the player starts the late-realm work once two colonies exist
SURVEY_SHIPS = 2
SURVEY_SHIP_KEY = "eclipse_runner"
EXPEDITION_ROUND_SEC = 3 * 3600  # assumption: 1 h stay (canonical default) + 2 h round-trip flight
EXPEDITION_RECORD_VALUE = 1000
BOSS_SHIP_KEY = "falcon_interceptor"  # cheapest combat hull; World Boss claim route needs only one damaging hit
BOSS_SHIPS = 3
APEX_ASCENSION_KEY = "machine_ascension"  # requires specialisation tier 3 + metal/crystal, no trait gate of its own
SIM_VERSION = "player-journey/1"
POLICY_VERSION = "pj-policy/1"

DAY = 86400
SIM_EPOCH = 20_000 * DAY  # day-aligned wall clock so canonical day buckets/cooldowns are exact
CHECKPOINT_DAYS: Tuple[float, ...] = (7, 30, 90, 182.5, 365)
TARGET_WORLDS = 11
LONG_DAYS = 730.0  # extended horizon only used to find WHEN a legal 11/11 empire would be reachable
COLONY_TRANSIT_SEC = 2 * 3600  # approximation, see NOT_MODELLED / assumptions
CLIMATE_SLOT = {"hot": 1, "mid": 8, "cold": 15}
COLONY_CLIMATE_CYCLE = ("mid", "hot", "cold")
ENERGY_LOW_RATIO = 0.95
EPS = 1e-6
PATIENCE_SEC = 6 * 3600  # a player saves for a goal only if it is affordable within this horizon
PATIENCE_V2_SEC = 24 * 3600  # pj-policy/2: a planning player saves up to a day for the best purchase / a needed enabler
SLACK_PRICE = 0.15  # pj-policy/2: relative value of the non-binding resource when ranking purchases by payback
STRATEGY_VERSIONS = {"v1": "pj-policy/1", "v2": "pj-policy/2"}

# Counterfactual levers (SIMULATION ONLY - they remove or scale one brake to measure how much progression it costs;
# none of them is a game change or a proposal by itself, and none is a player route).
LEVERS: Dict[str, str] = {
    "none": "baseline (canonical rules)",
    "instant_build": "construction time x0.01 (is build duration a brake?)",
    "instant_research": "research time x0.01 (is research duration a brake?)",
    "free_research_cost": "research costs 0 metal / 0 crystal (is the research resource sink a brake?)",
    "free_energy": "energy ratio forced to 1.0 (is energy supply a brake?)",
    "free_storage": "storage capacity unlimited (are depot caps a brake?)",
    "no_colony_chain": "colony-maturity gate lowered from planet level 15 to 1 (is the serial PL15 chain a brake?)",
    "income_x1.25": "metal/crystal/fuel production x1.25 (elasticity of progression to income)",
    # candidate mechanics (design options measured as levers; none is enabled anywhere)
    "build_time_x0.88": "construction time x0.88 (what a -12 % build-time resonance could at most deliver)",
    "build_time_x0.5": "construction time x0.5 (how much of the queue time is construction duration?)",
    "research_time_x0.88": "research time x0.88 (the same -12 % applied to the research queue)",
    "colony_gate_pl10": "colony-maturity gate at planet level 10 instead of 15 (dose-response of the colony chain)",
    "colony_gate_pl12": "colony-maturity gate at planet level 12 instead of 15 (the middle option between PL10 and PL15)",
    "colony_gate_pl5": "colony-maturity gate at planet level 5 instead of 15 (dose-response of the colony chain)",
    "auto_start": "a purchase the player cannot afford yet is reserved and starts by itself when the funds arrive (removes action-window latency)",
    # equal-strength (about 10 %) candidates for a trait resonance: which brake does it act on?
    "res_cost_x0.9": "research costs x0.9 (-10 %)",
    "mine_cost_x0.9": "metal/crystal mine, fuel plant and solar upgrade costs x0.9 (-10 %)",
    "storage_cap_x1.1": "depot capacity x1.1 (+10 %)",
    "colony_xp_x1.1": "planet XP of colonies x1.1 (+10 %, DNA scans, building finishes, ...)",
    "colony_xp_x1.25": "planet XP of colonies x1.25 (+25 %)",
}
COLONY_XP_BOOST = {"colony_xp_x1.1": 1.10, "colony_xp_x1.25": 1.25}
ASCENSION_ONLY_LEVERS = frozenset({"build_time_x0.5", "colony_gate_pl12"})  # side-study levers (the Ascension check, the PL12 gate comparison); not part of the bottleneck-report matrix
MINE_COST_KEYS = frozenset({"metal_mine", "crystal_mine", "fuel_cell_plant", "solar_plant"})
LEVER_GATE_LEVEL = {"no_colony_chain": 1, "colony_gate_pl10": 10, "colony_gate_pl12": 12, "colony_gate_pl5": 5}
AGGRESSIVE_COOLDOWN_DAYS = 7  # policy A<n>: a player who presses Ascend whenever the button is enabled, at most once a week per mine
LEVER_INCOME_FACTOR = 1.25
LEVER_TIME_FACTOR = 0.01

# Mine Ascension model (asc-model/1).  The canonical owners ``game.mine_evolution.nodebuster.ascend_mine`` and
# ``purchase_skill`` perform every reset / AP grant / skill purchase against the sandbox DB; the simulator only
# decides WHEN to call them.  Scenario.asc selects the mine rule set and the ascension policy:
ASC_MODEL_VERSION = "asc-model/1"
PRE_NODEBUSTER_MINE_CEILING = 200  # 50 base + 50 planet-core nexus + 2 x 50 geothermal nexus: the resolver cap the pj/1 policy was built around
ASC_EXTRA_CHECKPOINT_DAYS: Tuple[float, ...] = (730, 1095, 1460, 2190)  # full snapshots of Ascension scenarios (24 months and the extended exploration)
ASC_MINES = ("metal_mine", "crystal_mine")  # the fuel plant never reaches the L200 activation level in these journeys
ASC_MODES: Dict[str, str] = {
    "legacy": "pj/1 behaviour: the resolver's nexus cap (L200) stops the mines; no Ascension (reference, kept for comparability with the bottleneck report)",
    "never": "canonical Nodebuster queue rules (no mine cap) and the player never ascends: keep building",
    "T<n>": "canonical rules; each production mine ascends the first time it is at level >= n (n >= 200) with an empty mine queue; one mine per planet rebuilds at a time",
    "O<n>[x<k>]": "like T<n> but each mine ascends exactly k times (default 1), then keeps building (price of a first reset / of farming k resets, no treadmill)",
    "L<n>+<d>": "ladder: the first reset at depth >= n, every further reset only at depth >= previous best depth + d (a prestige loop that must beat its own record)",
}
ASC_SKILL_ORDERS: Dict[str, Tuple[str, ...]] = {
    # strict priority: buy the first available skill of the list as soon as the AP are there (save otherwise)
    "rebuild_first": (
        "frugal_rebuild", "rapid_rebuild", "reconstruction", "deep_yield", "deep_storage", "overdrive",
        "core_resonance", "legacy_reconstruction", "breakthrough_window", "singularity_excavation",
        "optimized_energy", "load_balancing",
    ),
    "yield_first": (
        "deep_yield", "deep_storage", "frugal_rebuild", "rapid_rebuild", "reconstruction", "overdrive",
        "core_resonance", "legacy_reconstruction", "breakthrough_window", "singularity_excavation",
        "optimized_energy", "load_balancing",
    ),
}


def parse_asc_policy(mode: str) -> Tuple[bool, Optional[int], str, int]:
    """(mines_uncapped, first ascension depth or None, kind 'T' | 'O' | 'L' | 'M' | 'G' | '', ladder step for 'L' / resets per mine for 'O').

    Empire scope (S11): ``O<n>`` resets every mine once, one rebuild at a time *per planet* (planets in parallel); ``G<n>`` the same but
    one rebuild at a time in the whole empire (serial); ``M<n>`` exactly one reset of one single mine in the whole empire.  Selective:
    ``P<n>`` only the metal mine of every planet, ``C<n>`` only the crystal mine, ``H<n>`` only the homeworld.  ``A<n>`` is the button-masher:
    it resets whenever a mine is at or above n, at most once a week per mine, and never stops building in between (stress test)."""
    if mode == "legacy":
        return False, None, "", 0
    if mode == "never":
        return True, None, "", 0
    kind, rest = mode[:1], mode[1:]
    if kind == "L" and "x" in rest:  # ladder with a cap of resets per mine: L200+50x3 (see parse_asc_cap)
        rest, cap = rest.rsplit("x", 1)
        if not cap.isdigit() or int(cap) < 1:
            raise ValueError(f"unknown ascension mode {mode!r}")
    if kind == "T" and rest.isdigit():
        depth, step = int(rest), 0
    elif kind in ("O", "G", "M", "P", "H", "C", "A") and rest.isdigit():
        depth, step = int(rest), 1
    elif kind in ("O", "P", "H") and "x" in rest and rest.split("x", 1)[0].isdigit() and rest.split("x", 1)[1].isdigit() and int(rest.split("x", 1)[1]) >= 1:
        depth, step = int(rest.split("x", 1)[0]), int(rest.split("x", 1)[1])
    elif kind == "L" and "+" in rest and rest.split("+", 1)[0].isdigit() and rest.split("+", 1)[1].isdigit():
        depth, step = int(rest.split("+", 1)[0]), int(rest.split("+", 1)[1])
        if step < 1:
            raise ValueError(f"ladder step must be positive: {mode!r}")
    else:
        raise ValueError(f"unknown ascension mode {mode!r}")
    if depth < nodebuster_mod.ASCENSION_MIN_LEVEL:
        raise ValueError(f"ascension threshold below the canonical activation level: {mode!r}")
    return True, depth, kind, step


def expected_ascension_points(level: int, previous_best: int) -> int:
    """AP the owner's CURRENT rule awards for a reset at ``level`` when the mine's record was ``previous_best`` (canonical: independent of it)."""
    fn = nodebuster_mod.ascension_points_for_depth
    try:
        return int(fn(level, previous_best=previous_best))
    except TypeError:
        return int(fn(level))


def parse_asc_cap(mode: str) -> Optional[int]:
    """Resets per mine of a capped ladder (``L200+50x3`` -> 3), None for every other policy."""
    if mode[:1] == "L" and "x" in mode[1:]:
        parse_asc_policy(mode)  # validates
        return int(mode.rsplit("x", 1)[1])
    return None


def parse_asc_mode(mode: str) -> Tuple[bool, Optional[int]]:
    """(mines_uncapped, ascension depth threshold or None)."""
    uncapped, depth, _kind, _step = parse_asc_policy(mode)
    return uncapped, depth


ECON_TECHS = ("energy_tech", "mining_tech", "crystal_tech", "buildtime_tech", "storage_tech")
PROD_BUILDINGS = frozenset({"metal_mine", "crystal_mine", "solar_plant"})  # pj-policy/2 ranks these by payback

NOT_MODELLED = [
    "Expeditions and their loot: only the XP sensitivity scenario S11-active-mid-exp6 grants expedition XP (6/day); ship/fuel upkeep and loot are never charged or granted.",
    "Imperial Mandates use real prerequisites: survey = 2 canonical expedition ships + 12 missions (3 h round trip is an assumption, no loot), presence = owned systems, directive = canonical vote, apex = homeworld specialisation tier 3 + machine_ascension (5M/3M, 7 d). If the homeworld DNA has no eligible specialisation the player takes the World Boss claim route instead (3 combat hulls, one real hit on a scheduled boss, claim after the event); no combat realism beyond the canonical damage call.",
    "Timekeeper / login / Battle Pass skips are reported as available potential only; none is applied to a queue (no free skips).",
    "Real fleet transport: colony supply is a flat package delivered after a fixed transit (assumption), transport ships are not charged.",
    "Per-planet mechanics flags (world-type start multipliers, trait effects, specialisations, policies) other than the candidate R3 resonance toggle.",
    "Trader/exchange, military sinks, defence, galactic directives, discoveries/events XP and planet research XP.",
    "Mine Ascension: the reset, AP grant, skill purchases and rebuild discounts run through the canonical nodebuster owners only in scenarios with asc != legacy (asc-model/1); legacy scenarios report AP as potential only. Research-Lab Ascension, Stellar Forge and Ascension-skill resets are not modelled.",
    "Research queue beyond the canonical default limit; research is paid from the best-stocked established world (assumption: the player switches planet context), labs/academy bonuses come from the homeworld.",
]

EXPANSION_BLOCKERS = frozenset(
    {
        "planet_evolution_colony_slot_required",
        "expansion_gate_homeworld_level",
        "expansion_gate_interstellar_tech",
        "expansion_gate_world_type",
        "colony_maturity_required",
        "imperial_mandate_required",
        "colony_limit_reached",
        "seed_ark_prerequisites",
        "seed_ark_unaffordable",
    }
)

BLOCKER_RECOVERY = {
    "planet_evolution_colony_slot_required": "Raise the Genesis Ark planet level to the next EXPANSION_SLOT_GATES step (XP: DNA scans, building/research finishes).",
    "expansion_gate_homeworld_level": "Raise the Genesis Ark planet level.",
    "expansion_gate_interstellar_tech": "Research Interstellar Expansion to the required level (needs lab 4 + navigation 3).",
    "expansion_gate_world_type": "Pick a world type matching current Ark level and expansion tech.",
    "colony_maturity_required": "Level every existing colony to planet level 15 (XP: DNA scans, building finishes).",
    "imperial_mandate_required": "Earn Imperial Mandates (survey/presence/directive/apex) - loops not modelled here.",
    "colony_limit_reached": "Admin ceiling (max_colonies_per_player) reached.",
    "seed_ark_prerequisites": "Build orbital shipyard/command center and research navigation/storage tech for the Seed Ark.",
    "seed_ark_unaffordable": "Accumulate Seed Ark metal/crystal/fuel on the homeworld (fuel needs a fuel cell plant).",
    "storage_cap_below_cost": "Raise the matching storage building (or storage tech) above the next cost.",
    "colony_supply_waiting": "Homeworld must afford the colony supply package.",
}


# ---------------------------------------------------------------------------
# Policies (scheduling assumptions - not guarantees of real user behaviour)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    key: str
    windows_hours: Tuple[int, ...]  # action windows per day (hour offsets); empty => continuous
    queue_fill: int  # max queue entries the player keeps filled
    scan_frac: float  # max share of a world's stock one DNA scan may consume
    scan_in_s1: bool  # scan even when no colony depends on the level
    description: str

    @property
    def continuous(self) -> bool:
        return not self.windows_hours


POLICIES: Dict[str, Policy] = {
    "casual": Policy("casual", (9, 21), 2, 0.25, False, "two action windows/day, shallow queue, scans only when a colony needs the level"),
    "active": Policy("active", (7, 12, 17, 22), 3, 0.15, True, "four action windows/day, full queue, cheap daily scans"),
    "optimizer": Policy("optimizer", (), 99, 0.25, True, "acts at every event, near-zero avoidable idle, no paid boosts"),
}

TRAIT_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "none": {"reduction": 0.0, "worlds": "none", "label": "zero-trait (core progress, no rare DNA)"},
    "r5_one": {"reduction": 0.05, "worlds": "one", "label": "candidate resonance -5% build time on ONE qualified world"},
    "r10_one": {"reduction": 0.10, "worlds": "one", "label": "candidate resonance -10% build time on ONE qualified world"},
    "r12_one": {"reduction": 0.12, "worlds": "one", "label": "candidate resonance -12% build time on ONE qualified world"},
    "r12_all": {"reduction": 0.12, "worlds": "all", "label": "STRESS: -12% on every qualified world (no combined cap)"},
}


def resonance_qualified(*, enabled: bool, planet_level: int, reveal_tier: int, specialization_active: bool) -> bool:
    """R3 gate: revealed trait + genuinely active specialisation, else zero resonance."""
    if not enabled:
        return False
    if reveal_tier < 1:
        return False
    if planet_level < SPECIALIZATION_UNLOCK_LEVEL:
        return False
    return bool(specialization_active)


# ---------------------------------------------------------------------------
# Sandbox: throw-away SQLite DB running the canonical progression owners
# ---------------------------------------------------------------------------


class Sandbox:
    """Disposable game database. Never touches a configured/live database."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.seed = SANDBOX_RNG_SEED if seed is None else int(seed)
        self._dir: Optional[str] = None
        self._saved_env: Dict[str, Optional[str]] = {}
        self._saved_paths: Tuple[Any, Any] = (None, None)
        self.conn = None
        self.user_id = 0
        self.home_planet_id = 0
        self.colony_xp_boost = 1.0  # lever colony_xp_*: extra planet XP on colonies, granted through add_planet_xp
        self._coord_x = 700
        self._system_seq = 300

    def __enter__(self) -> "Sandbox":
        SIM_LOCK.acquire()
        try:
            return self._enter()
        except BaseException:
            SIM_LOCK.release()
            raise

    def _enter(self) -> "Sandbox":
        import game.db as gdb
        import game.models as models

        self._saved_env = {k: os.environ.get(k) for k in ("GC_DB_PATH", "GC_SKIP_MIGRATION_CHECK")}
        self._saved_paths = (getattr(gdb, "_DB_PATH", None), getattr(models, "DB_PATH", None))
        self._dir = tempfile.mkdtemp(prefix="gc_player_journey_")
        path = os.path.join(self._dir, "sandbox.db")
        os.environ["GC_DB_PATH"] = path
        os.environ["GC_SKIP_MIGRATION_CHECK"] = "1"
        gdb._DB_PATH = None
        models.DB_PATH = path
        with contextlib.redirect_stdout(io.StringIO()):
            models.init_db()
            import migrate

            migrate.main()
        from game.db import db
        from game.models import create_user, ensure_player_and_homeworld, get_homeworld

        self.conn = db()
        # Homeworld coordinates are drawn from the global RNG; pin it (and restore it) so the
        # DNA and every trait count in the report are reproducible without touching game code.
        import random

        rng_state = random.getstate()
        random.seed(self.seed)
        try:
            ok, err, user = create_user("pj_sim_commander", "sandbox-only-secret-1")
            if not ok:
                raise RuntimeError(f"sandbox user creation failed: {err}")
            self.user_id = int(user["id"])
            ensure_player_and_homeworld(self.user_id, player_name="JourneySim", conn=self.conn)
        finally:
            random.setstate(rng_state)
        self.conn.commit()
        hw = get_homeworld(self.user_id, conn=self.conn) or {}
        self.home_planet_id = int(hw["id"])
        return self

    def __exit__(self, *_exc: Any) -> None:
        import game.db as gdb
        import game.models as models

        try:
            if self.conn is not None:
                self.conn.close()
        finally:
            gdb._DB_PATH, models.DB_PATH = self._saved_paths
            for key, value in self._saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if self._dir:
                shutil.rmtree(self._dir, ignore_errors=True)
            SIM_LOCK.release()

    # -- canonical reads/writes -------------------------------------------------
    def planet(self, planet_id: int) -> Dict[str, Any]:
        from game.planet_evolution.repository import get_planet_row

        row = get_planet_row(int(planet_id), conn=self.conn) or {}
        return {
            "level": int(row.get("planet_level") or 0),
            "xp": int(row.get("planet_xp") or 0),
            "tier": int(row.get("dna_reveal_tier") or 0),
        }

    def trait_counts(self, planet_id: int, tier: int) -> Tuple[int, int]:
        """(known, hidden) trait COUNTS only - names never leave the sandbox."""
        from game.planet_evolution.dna import all_trait_keys
        from game.planet_evolution.repository import get_planet_dna

        dna = get_planet_dna(int(planet_id), conn=self.conn) or {}
        total = len(all_trait_keys(dna, 3))
        known = len(all_trait_keys(dna, int(tier))) if int(tier) >= 1 else 0
        return known, max(0, total - known)

    def set_research(self, tech_key: str, level: int) -> None:
        self.conn.execute(
            "INSERT INTO research_levels (user_id, tech_key, level) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;",
            (self.user_id, tech_key, int(level)),
        )
        self.conn.commit()

    def set_buildings(self, planet_id: int, levels: Dict[str, int]) -> None:
        cols = {str(r[1]) for r in self.conn.execute("PRAGMA table_info(planet_buildings);").fetchall()}
        sets = [(k, int(v)) for k, v in levels.items() if k in cols]
        if not sets:
            return
        clause = ", ".join(f"{k} = ?" for k, _ in sets)
        self.conn.execute(
            f"UPDATE planet_buildings SET {clause} WHERE planet_id = ?;",
            [v for _, v in sets] + [int(planet_id)],
        )
        self.conn.commit()

    # -- Mine Ascension (canonical owners; the sandbox DB is the single source of truth for AP / ranks) --------------
    def planet_row(self, planet_id: int) -> Dict[str, Any]:
        row = self.conn.execute("SELECT * FROM planets WHERE id = ?;", (int(planet_id),)).fetchone()
        return dict(row)

    def ascend_mine(self, planet_id: int, building_type: str) -> Tuple[bool, str, Dict[str, Any]]:
        """`nodebuster.ascend_mine` exactly as the endpoint calls it (reset, AP grant, best depth)."""
        self.conn.commit()
        ok, reason, data = nodebuster_mod.ascend_mine(self.user_id, self.planet_row(planet_id), str(building_type))
        self.conn.commit()
        return bool(ok), str(reason), dict(data or {})

    def buy_skill(self, planet_id: int, building_type: str, skill_key: str) -> Tuple[bool, str, Dict[str, Any]]:
        self.conn.commit()
        ok, reason, data = nodebuster_mod.purchase_skill(self.user_id, self.planet_row(planet_id), str(building_type), str(skill_key))
        self.conn.commit()
        return bool(ok), str(reason), dict(data or {})

    def asc_profiles(self, planet_id: int) -> Dict[str, Dict[str, Any]]:
        return nodebuster_mod.get_profiles_for_planet(int(planet_id), conn=self.conn)

    def grant_xp(self, source_key: str, planet_id: int, t: float, idem: str) -> int:
        from game.activity_xp import grant_activity_xp

        result = grant_activity_xp(
            self.user_id,
            int(planet_id),
            source_key,
            conn=self.conn,
            idempotency_key=idem,
            now=SIM_EPOCH + float(t),
        )
        self.conn.commit()
        got = int(result.get("amount") or 0) if result.get("granted") else 0
        self._boost_colony_xp(int(planet_id), got)
        return got

    def _boost_colony_xp(self, planet_id: int, gained: int) -> None:
        if self.colony_xp_boost <= 1.0 or gained <= 0 or int(planet_id) == self.home_planet_id:
            return
        extra = int(gained * (self.colony_xp_boost - 1.0))
        if extra > 0:
            from game.planet_evolution.planet_level import add_planet_xp

            add_planet_xp(int(planet_id), extra, self.conn, reason="lever_colony_xp", skip_diversity=True)
            self.conn.commit()

    def scan_status(self, planet_id: int, t: float) -> Dict[str, Any]:
        return dna_analysis.scan_status(int(planet_id), conn=self.conn, now=SIM_EPOCH + float(t))

    def scan(self, planet_id: int, t: float, metal: float, crystal: float) -> Tuple[bool, str, float, float, int]:
        self.conn.execute("UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;", (float(metal), float(crystal), int(planet_id)))
        self.conn.commit()
        ok, reason, data = dna_analysis.perform_scan(
            int(planet_id), player_id=self.user_id, now=SIM_EPOCH + float(t), conn=self.conn
        )
        row = self.conn.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (int(planet_id),)).fetchone()
        xp = int((data or {}).get("xp_gained") or 0) if ok else 0
        self._boost_colony_xp(int(planet_id), xp)
        return bool(ok), str(reason), float(row["metal"]), float(row["crystal"]), int((data or {}).get("xp_gained") or 0)

    def cap_check(self) -> Tuple[bool, str]:
        from game.logic import check_planet_cap_available

        ok, reason = check_planet_cap_available(self.user_id, conn=self.conn)
        return bool(ok), str(reason or "")

    def expansion_gate(self, world_type: Optional[str]) -> Tuple[bool, str, Dict[str, Any]]:
        from game.planet_evolution.expansion_protocol import evaluate_expansion_gates

        ok, reason, meta = evaluate_expansion_gates(self.user_id, conn=self.conn, world_type=world_type)
        return bool(ok), str(reason or ""), dict(meta or {})

    def cap_info(self) -> Dict[str, Any]:
        from game.planet_evolution.expansion_protocol import expansion_gameplay_cap

        return dict(expansion_gameplay_cap(self.user_id, conn=self.conn))

    def next_binding(self) -> Dict[str, Any]:
        """Easiest-gate colonisable site (same site search as the colonisation tests)."""
        from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
        from game.planet_evolution.world_colonization import (
            build_world_key,
            is_colonizable_world_type,
            parse_world_key,
            sector_coords,
        )

        best: Optional[Tuple[Tuple[int, int], Dict[str, Any], int]] = None
        for wx in range(self._coord_x, 6000, 40):
            for wy in range(700, 6000, 40):
                wt = strategic_world_type_for_coords(float(wx), float(wy))
                if not is_colonizable_world_type(wt):
                    continue
                gate = WORLD_TYPE_GATES.get(str(wt), {"homeworld_level": 1, "expansion_tech": 1})
                rank = (int(gate["homeworld_level"]), int(gate["expansion_tech"]))
                if best is None or rank < best[0]:
                    world_key = build_world_key(float(wx), float(wy), world_type=wt)
                    parsed = parse_world_key(world_key)
                    sx, sy = sector_coords(float(wx), float(wy))
                    binding = {
                        "world_key": world_key,
                        "world_x": float(wx),
                        "world_y": float(wy),
                        "sector_x": int(sx),
                        "sector_y": int(sy),
                        "planet_role": parsed["planet_role"],
                        "origin_world_key": world_key,
                        "world_type": str(wt),
                    }
                    best = (rank, binding, wx)
                if rank == (5, 1):
                    break
            if best is not None and best[0] == (5, 1):
                break
        if best is None:
            raise RuntimeError("no colonisable site found in sandbox")
        self._coord_x = best[2] + 40
        return best[1]

    def found_colony(self, name: str, binding: Dict[str, Any]) -> Tuple[bool, str, int]:
        from game.planet_evolution.service import colonize_planet

        self._system_seq += 1
        clean = {k: v for k, v in binding.items() if k != "world_type"}
        ok, reason, extra = colonize_planet(
            self.user_id,
            name=name,
            galaxy=1,
            system=self._system_seq,
            position=1,
            world_binding=clean,
            conn=self.conn,
        )
        return bool(ok), str(reason or ""), int((extra or {}).get("planet_id") or 0)

    def touch_planet(self, planet_id: int) -> None:
        """Planet load path (`ensure_planet_evolution`), incl. legacy-colony bootstrap."""
        from game.planet_evolution.bootstrap import ensure_planet_evolution

        ensure_planet_evolution(int(planet_id), self.conn)
        self.conn.commit()

    def sync_establishment(self, planet_id: int) -> None:
        """What queue_engine runs after every finished building."""
        from game.planet_evolution.expansion_protocol import sync_establishment_state

        sync_establishment_state(int(planet_id), conn=self.conn)
        self.conn.commit()

    def establishment_state(self, planet_id: int) -> Dict[str, bool]:
        from game.planet_evolution.expansion_phase import is_establishment_complete
        from game.planet_evolution.expansion_protocol import is_legacy_full_colony, is_outpost_planet

        pid = int(planet_id)
        return {
            "restricted_outpost": bool(is_outpost_planet(pid, conn=self.conn)),
            "milestones_complete": bool(is_establishment_complete(pid, conn=self.conn)),
            "legacy_full_colony": bool(is_legacy_full_colony(pid, conn=self.conn)),
        }

    def planet_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM planets WHERE player_id = ?;", (self.user_id,)).fetchone()[0])


# ---------------------------------------------------------------------------
# Simulation state
# ---------------------------------------------------------------------------


@dataclass
class Job:
    jid: int
    kind: str  # build | research
    key: str
    target: int
    cost_m: int
    cost_c: int
    category: str
    world: int
    start: Optional[float] = None
    finish: Optional[float] = None


@dataclass
class World:
    idx: int
    planet_id: int
    climate: str
    slot: int
    home: bool
    founded_at: float
    outpost: bool
    buildings: Dict[str, int] = field(default_factory=dict)
    metal: float = 0.0
    crystal: float = 0.0
    fuel: float = 0.0
    queue: List[Job] = field(default_factory=list)
    established_at: Optional[float] = None
    unrestricted_at: Optional[float] = None
    dna_early_at: Optional[float] = None
    touched: bool = False
    package_sent: bool = False
    package_wait_since: Optional[float] = None
    supply_wait_sec: float = 0.0
    specialization_active: bool = False
    next_scan_t: float = 0.0
    scans: int = 0
    scan_spend_m: float = 0.0
    scan_spend_c: float = 0.0
    # accumulators (seconds / amounts)
    build_busy_sec: float = 0.0
    idle_cost_sec: float = 0.0
    idle_window_sec: float = 0.0
    idle_nothing_sec: float = 0.0
    energy_low_sec: float = 0.0
    storage_full_sec: float = 0.0
    wasted_m: float = 0.0
    wasted_c: float = 0.0
    wasted_f: float = 0.0
    produced_m: float = 0.0
    produced_c: float = 0.0
    produced_f: float = 0.0
    energy_low_by_climate_sec: float = 0.0
    # exclusive time ledger (seconds since the world exists): busy + one cause per queue-empty interval
    causes: Dict[str, float] = field(default_factory=dict)
    lost_energy_m: float = 0.0
    lost_energy_c: float = 0.0
    lost_energy_f: float = 0.0
    reserved: Optional[Tuple[str, int, int, int]] = None  # auto_start lever: next purchase waiting for funds
    asc_any: bool = False  # a mine of this world has ascended: the resolver then reads the Nodebuster state of the sandbox DB


@dataclass
class Scenario:
    sid: str
    topology: str  # S1 | S11
    policy: str
    climate: str  # homeworld climate
    trait: str = "none"
    days: float = 365.0
    expeditions_per_day: int = 0
    transit_sec: int = COLONY_TRANSIT_SEC
    rng_seed: Optional[int] = None  # sandbox homeworld placement/DNA; None = default seed
    lever: str = "none"  # counterfactual lever (see LEVERS) - never a player route
    strategy: str = "v1"  # v1 = pj-policy/1 (goal list + patience); v2 = pj-policy/2 (payback-ranked, saves for the best purchase)
    asc: str = "legacy"  # mine rule set / Ascension policy, see ASC_MODES
    asc_skills: str = "rebuild_first"  # AP spending order, see ASC_SKILL_ORDERS
    trader: bool = False  # sell surplus crystal for the metal a purchase lacks (canonical game.exchange route, rate and daily limit)


def _settings() -> Dict[str, float]:
    return {
        "production_speed": float(DEFAULT_GAME_SETTINGS.get("production_speed", 1)),
        "build_speed": float(DEFAULT_GAME_SETTINGS.get("build_speed", 1)),
        "research_speed": float(DEFAULT_GAME_SETTINGS.get("research_speed", 1)),
    }


class Journey:
    """One deterministic player journey."""

    def __init__(self, scenario: Scenario, sandbox: Sandbox) -> None:
        self.sc = scenario
        self.sb = sandbox
        self.policy = POLICIES[scenario.policy]
        self.settings = _settings()
        self.build_limit = min(int(_resolve_build_queue_limit(DEFAULT_GAME_SETTINGS)), self.policy.queue_fill)
        self.research_limit = int(_resolve_research_queue_limit(DEFAULT_GAME_SETTINGS))
        self.horizon = float(scenario.days) * DAY
        self.t = 0.0
        self._jid = 0
        self.completed_ids: set[int] = set()
        self.research: Dict[str, int] = {}
        self.research_ver = 0
        self.rqueue: List[Job] = []
        self.r_busy_sec = 0.0
        self.r_idle_cost_sec = 0.0
        self.r_idle_window_sec = 0.0
        self.r_idle_nothing_sec = 0.0
        self.r_causes: Dict[str, float] = {}
        self.r_reserved: Optional[Tuple[str, int, int, int, int]] = None
        if scenario.lever not in LEVERS:
            raise ValueError(f"unknown lever {scenario.lever!r}")
        if scenario.strategy not in STRATEGY_VERSIONS:
            raise ValueError(f"unknown strategy {scenario.strategy!r}")
        self.lever = scenario.lever
        self.mines_uncapped, self.asc_depth, self.asc_kind, self.asc_step = parse_asc_policy(scenario.asc)
        self.asc_max = parse_asc_cap(scenario.asc)
        self.asc_last: Dict[Tuple[int, str], float] = {}  # day of the last reset per (world, mine): the cooldown of policy A
        if scenario.asc_skills not in ASC_SKILL_ORDERS:
            raise ValueError(f"unknown skill order {scenario.asc_skills!r}")
        self.trader = bool(scenario.trader)
        self._exch_cfg: Optional[Dict[str, Any]] = None
        self._trade_day = -1
        self._trade_used = 0
        self._trade_retry: Optional[float] = None
        self.trades: Dict[str, float] = {"trades": 0, "crystal_sold": 0.0, "metal_bought": 0.0, "metal_sold": 0.0, "crystal_bought": 0.0, "capped_days": 0}
        self._trade_capped_day = -1
        self._last_trade: Dict[int, Tuple[int, str]] = {}
        self.asc_ver = 0  # bumps with every canonical Ascension mutation (cache key of everything state-dependent)
        self._probe_caches: Dict[int, Dict[tuple, Any]] = {}
        self._profile_cache: Dict[Tuple[int, int], Dict[str, Dict[str, Any]]] = {}
        self.asc_runs: List[Dict[str, Any]] = []
        self.asc_skill_log: List[Dict[str, Any]] = []
        self.asc_rejections: Dict[str, int] = {}
        self.asc_open: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self.asc_peak: Dict[Tuple[int, str], int] = {}
        self.sb.colony_xp_boost = COLONY_XP_BOOST.get(scenario.lever, 1.0)
        self.colony_state = "init"
        self.colony_state_sec: Dict[str, float] = {}
        self._hyp_cache: Dict[Tuple[Any, ...], Tuple[float, float, float]] = {}
        self.research_needs: Dict[str, int] = {}
        self.worlds: List[World] = []
        self._stat_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        self._ctx: Optional[Tuple[int, float, int]] = None
        self.spend: Dict[str, float] = {k: 0.0 for k in ("mines", "solar", "storage", "research", "colony_expansion", "dna_scans", "infrastructure", "transport", "mandates")}
        self.spend_c: Dict[str, float] = {k: 0.0 for k in self.spend}
        self.spend_f: float = 0.0
        self.blockers: Dict[str, Dict[str, Any]] = {}
        self.scan_rejections: Dict[str, int] = {}
        self.colony_log: List[Dict[str, Any]] = []
        self.gate_audit: List[Dict[str, Any]] = []
        self.findings: Dict[str, Dict[str, Any]] = {}
        self.daily: List[Dict[str, Any]] = []
        self.checkpoints: Dict[str, Dict[str, Any]] = {}
        self.invariant_violations: List[str] = []
        self.xp_by_source: Dict[str, int] = {}
        self.ark: Optional[Dict[str, Any]] = None
        self.convoys: List[Dict[str, Any]] = []
        self.arks_built = 0
        self.expedition_count = 0
        self.wake: Optional[float] = None
        self.resonance_world_idx: Optional[int] = None
        self.resonance_enabled = TRAIT_SCENARIOS[scenario.trait]["worlds"] != "none"
        self.reduction = float(TRAIT_SCENARIOS[scenario.trait]["reduction"])
        self.target_worlds = TARGET_WORLDS if scenario.topology == "S11" else 1
        self.cap_info: Dict[str, Any] = self.sb.cap_info()
        self.storage_need: Optional[str] = None
        self.ships_home = 0
        self.ship_build: Optional[Dict[str, Any]] = None
        self.missions: List[Dict[str, Any]] = []
        self.missions_done = 0
        self._movement_seq = 0
        self.vote_done = False
        self.asc: Optional[Dict[str, Any]] = None
        self.mandate_rejections: Dict[str, int] = {}
        self.mandate_log: List[Dict[str, Any]] = []
        self._mandates_seen: List[str] = []
        self.spec_picked: Optional[str] = None
        self.boss_route = False
        self.boss: Optional[Dict[str, Any]] = None
        self._gate_next = 0.0
        self.lab_need = 0
        self._next_colony_binding: Optional[Dict[str, Any]] = None
        self._add_home()

    # -- setup ----------------------------------------------------------------
    def _add_home(self) -> None:
        start = {
            "metal": float(DEFAULT_GAME_SETTINGS.get("start_metal", 150000)),
            "crystal": float(DEFAULT_GAME_SETTINGS.get("start_crystal", 100000)),
            "fuel": float(DEFAULT_GAME_SETTINGS.get("start_fuel_cells", 25000)),
        }
        self.initial_state = {"home_climate": self.sc.climate, "home_slot": CLIMATE_SLOT[self.sc.climate], **start}
        w = World(
            idx=0,
            planet_id=self.sb.home_planet_id,
            climate=self.sc.climate,
            slot=CLIMATE_SLOT[self.sc.climate],
            home=True,
            founded_at=0.0,
            outpost=False,
            metal=start["metal"],
            crystal=start["crystal"],
            fuel=start["fuel"],
            established_at=0.0,
        )
        self.worlds.append(w)

    # -- economy helpers ------------------------------------------------------
    def _new_resolver(self, w: World, buildings: Dict[str, int], research: Dict[str, int]) -> EffectResolver:
        """EffectResolver of a world.  After the first Ascension of a world the resolver is bound to the sandbox planet,
        so the canonical Nodebuster hooks (production / rebuild surge / tail, storage, energy) read the real state."""
        if not w.asc_any:
            return EffectResolver(dict(buildings), dict(research), settings=self.settings, planet_position=w.slot)
        cache = self._probe_caches.setdefault(w.planet_id, {})
        return EffectResolver(
            dict(buildings),
            dict(research),
            settings=self.settings,
            planet_position=w.slot,
            planet_id=w.planet_id,
            conn=self.sb.conn,
            external_probe_cache=cache,
        )

    def _resolver(self, w: World, buildings: Dict[str, int]) -> EffectResolver:
        return self._new_resolver(w, buildings, self.research)

    def asc_key(self, w: World) -> int:
        return self.asc_ver if w.asc_any else 0

    def profiles(self, w: World) -> Dict[str, Dict[str, Any]]:
        """Canonical Nodebuster state of a world (ascension counts, AP, best depth, skill ranks)."""
        key = (w.planet_id, self.asc_ver)
        hit = self._profile_cache.get(key)
        if hit is None:
            hit = self.sb.asc_profiles(w.planet_id)
            if len(self._profile_cache) > 512:
                self._profile_cache.clear()
            self._profile_cache[key] = hit
        return hit

    def max_level(self, w: World, r: EffectResolver, key: str) -> int:
        """Authoritative enqueue cap: the canonical queue owner under Nodebuster (no mine / solar cap), else the resolver cap."""
        base = int(r.get_max_building_level(key))
        if self.mines_uncapped and (key in EVOLVABLE_MINES or key == "solar_plant"):
            return int(_effective_building_queue_cap(key, base, planet_id=w.planet_id, conn=self.sb.conn))
        return base

    def stats(self, w: World) -> Dict[str, Any]:
        key = (w.idx, tuple(sorted(w.buildings.items())), self.research_ver, self.asc_key(w))
        hit = self._stat_cache.get(key)
        if hit is not None:
            return hit
        r = self._resolver(w, w.buildings)
        total, used = r.compute_energy()
        ratio = EffectResolver.energy_ratio(total, used)
        m_rate, c_rate = r.production_rates_per_sec()
        f_rate = r.fuel_cells_rate_per_sec()
        caps = r.get_storage_capacity()
        ratio_eff, income = self._lever_scale(float(ratio))
        free_storage = self.lever == "free_storage"
        cap_mult = 1.1 if self.lever == "storage_cap_x1.1" else 1.0
        out = {
            "ratio": float(ratio_eff),
            "ratio_real": float(ratio),
            "supply": int(total),
            "demand": int(used),
            "m_ps": float(m_rate) * ratio_eff * income,
            "c_ps": float(c_rate) * ratio_eff * income,
            "f_ps": float(f_rate) * ratio_eff * income,
            "cap_m": 1e18 if free_storage else float(caps.get("metal", 10**12)) * cap_mult,
            "cap_c": 1e18 if free_storage else float(caps.get("crystal", 10**12)) * cap_mult,
            "cap_f": 1e18 if free_storage else float(caps.get("fuel_cells", 10**12)) * cap_mult,
        }
        if len(self._stat_cache) > 4000:
            self._stat_cache.clear()
        self._stat_cache[key] = out
        return out

    def ucost(self, key: str, level: int, w: Optional[World] = None) -> Tuple[int, int]:
        cm, cc = _upgrade_cost(key, level)
        if self.lever == "mine_cost_x0.9" and key in MINE_COST_KEYS:
            return int(cm * 0.9), int(cc * 0.9)
        if w is not None and w.asc_any and key in EVOLVABLE_MINES:
            # canonical rebuild discount (Frugal Rebuild / Overdrive / Breakthrough Window), exact integer basis points
            cost_bps, _time_bps = _nodebuster_rebuild_bps(w.planet_id, key, int(level) + 1, conn=self.sb.conn, profiles=self.profiles(w))
            if cost_bps != 10000:
                return _scale_bps(cm, cost_bps), _scale_bps(cc, cost_bps)
        return cm, cc

    def _lever_scale(self, ratio: float) -> Tuple[float, float]:
        """(energy ratio used, income factor) after the counterfactual lever; identity for the baseline."""
        ratio_eff = 1.0 if self.lever == "free_energy" else ratio
        income = LEVER_INCOME_FACTOR if self.lever == "income_x1.25" else 1.0
        return ratio_eff, income

    def hyp_income(self, w: World, buildings: Dict[str, int], research: Optional[Dict[str, int]] = None) -> Tuple[float, float, float]:
        """Hypothetical (metal, crystal, fuel) per second of `w` with other buildings/research (same EffectResolver path as stats())."""
        rs = self.research if research is None else research
        key = (w.slot, tuple(sorted(buildings.items())), tuple(sorted(rs.items())))
        if w.asc_any:
            key += (w.planet_id, self.asc_ver)
        hit = self._hyp_cache.get(key)
        if hit is None:
            r = self._new_resolver(w, buildings, rs)
            total, used = r.compute_energy()
            ratio_eff, income = self._lever_scale(float(EffectResolver.energy_ratio(total, used)))
            m_rate, c_rate = r.production_rates_per_sec()
            f_rate = r.fuel_cells_rate_per_sec()
            hit = (float(m_rate) * ratio_eff * income, float(c_rate) * ratio_eff * income, float(f_rate) * ratio_eff * income)
            if len(self._hyp_cache) > 20000:
                self._hyp_cache.clear()
            self._hyp_cache[key] = hit
        return hit

    def eff_buildings(self, w: World) -> Dict[str, int]:
        eff = dict(w.buildings)
        for job in w.queue:
            eff[job.key] = max(int(eff.get(job.key, 0)), int(job.target))
        return eff

    # -- Trader (canonical game.exchange): crystal -> metal --------------------------------------------------
    def exchange_cfg(self) -> Dict[str, Any]:
        if self._exch_cfg is None:
            self._exch_cfg = get_exchange_config(conn=self.sb.conn)
        return self._exch_cfg

    def exchange_rates(self) -> Tuple[float, float]:
        """(metal paid per 1 crystal bought, metal received per 1 crystal sold); 0.0 for a disabled route."""
        cfg = self.exchange_cfg()
        if not cfg.get("enabled"):
            return 0.0, 0.0
        buy = max(0.0, float(cfg["rate_metal_to_crystal"])) if _route_enabled("metal", "crystal", cfg) else 0.0
        sell = max(0.0, float(cfg["rate_crystal_to_metal"])) if _route_enabled("crystal", "metal", cfg) else 0.0
        return buy, sell

    def trade_daily_limit(self) -> int:
        cfg = self.exchange_cfg()
        m, c, f = self.empire_hourly()
        scaled = int((m + c + f) * 24.0 * float(cfg["daily_limit_pct"]) / 100.0)
        return max(int(cfg["daily_limit_min"]), scaled)

    def _afford_wait_trader(self, w: World, s: Dict[str, Any], cost_m: float, cost_c: float) -> float:
        """Time until a purchase is affordable when the surplus of one resource can be traded for the other at the canonical rates."""
        buy, sell = self.exchange_rates()
        need_m = max(0.0, cost_m - w.metal)
        need_c = max(0.0, cost_c - w.crystal)
        if need_m <= 0 and need_c <= 0:
            return 0.0
        if cost_m > s["cap_m"] or cost_c > s["cap_c"]:
            return math.inf
        t_m_own = 0.0 if need_m <= 0 else (need_m / s["m_ps"] if s["m_ps"] > 0 else math.inf)
        t_c_own = 0.0 if need_c <= 0 else (need_c / s["c_ps"] if s["c_ps"] > 0 else math.inf)
        best = max(t_m_own, t_c_own)
        if sell > 0 and need_m > 0:  # metal is short: sell crystal beyond the purchase's own crystal cost
            denom = s["m_ps"] + sell * s["c_ps"]
            if denom > 0:
                best = min(best, max(t_c_own, (cost_m - w.metal - sell * (w.crystal - cost_c)) / denom, 0.0))
        if buy > 0 and need_c > 0:  # crystal is short: buy it with metal beyond the purchase's own metal cost
            denom = s["c_ps"] + s["m_ps"] / buy
            if denom > 0:
                best = min(best, max(t_m_own, (cost_c - w.crystal - (w.metal - cost_m) / buy) / denom, 0.0))
        return best

    def _trade_execute(self, w: World, give_res: str, receive_res: str, give: float) -> bool:
        """One canonical Trader transaction: minimum, preview, score guard and the daily limit of game.exchange."""
        day = int(self.t // DAY)
        if day != self._trade_day:
            self._trade_day, self._trade_used = day, 0
        remaining = self.trade_daily_limit() - self._trade_used
        give_i = int(give)
        if give_i > remaining:  # the canonical daily limit refuses the trade (daily_limit_exceeded): try again after the reset
            if self._trade_capped_day != day:
                self._trade_capped_day = day
                self.trades["capped_days"] += 1
            self._trade_retry = (day + 1) * DAY
            return False
        cfg = self.exchange_cfg()
        if give_i < _min_give_amount(give_res, receive_res, cfg):
            return False
        got = int(_preview_receive(give_res, receive_res, give_i, cfg))
        if got <= 0:
            return False
        if trade_would_increase_score(
            metal=int(w.metal), crystal=int(w.crystal), fuel_cells=int(w.fuel),
            give_resource=give_res, give_amount=give_i, receive_resource=receive_res, receive_amount=got,
        ):
            return False
        setattr(w, give_res, getattr(w, give_res) - give_i)
        setattr(w, receive_res, getattr(w, receive_res) + got)
        self._trade_used += give_i
        self.trades["trades"] += 1
        self.trades[f"{give_res}_sold"] = self.trades.get(f"{give_res}_sold", 0.0) + give_i
        self.trades[f"{receive_res}_bought"] = self.trades.get(f"{receive_res}_bought", 0.0) + got
        return True

    def trade_for(self, w: World, cost_m: float, cost_c: float) -> None:
        """Trade the surplus resource for the one a purchase lacks - only when the trade makes the purchase affordable right now.

        The policy never trades half-way (no ping-pong, no spread burned on speculative conversions) and never reverses a
        trade of the same planet on the same day.
        """
        if not self.trader:
            return
        buy, sell = self.exchange_rates()
        s = self.stats(w)
        cfg = self.exchange_cfg()
        day = int(self.t // DAY)
        last = self._last_trade.get(w.idx)
        if w.metal + EPS < cost_m and w.crystal + EPS >= cost_c:
            if sell <= 0 or (last and last[0] == day and last[1] == "metal_to_crystal"):
                return
            give = math.ceil((cost_m - w.metal) / sell)
            give = max(give, _min_give_amount("crystal", "metal", cfg))
            if w.crystal - cost_c < give or w.metal + give * sell > s["cap_m"]:
                return  # the surplus cannot complete the purchase
            if self._trade_execute(w, "crystal", "metal", float(give)):
                self._last_trade[w.idx] = (day, "crystal_to_metal")
        elif w.crystal + EPS < cost_c and w.metal + EPS >= cost_m:
            if buy <= 0 or (last and last[0] == day and last[1] == "crystal_to_metal"):
                return
            need_c = cost_c - w.crystal
            give = math.ceil(need_c * buy)
            give = max(give, _min_give_amount("metal", "crystal", cfg))
            if w.metal - cost_m < give or w.crystal + give / buy > s["cap_c"]:
                return
            if self._trade_execute(w, "metal", "crystal", float(give)):
                self._last_trade[w.idx] = (day, "metal_to_crystal")

    def afford_wait(self, w: World, cost_m: float, cost_c: float) -> float:
        s = self.stats(w)
        if self.trader:
            return self._afford_wait_trader(w, s, cost_m, cost_c)
        need_m = max(0.0, cost_m - w.metal)
        need_c = max(0.0, cost_c - w.crystal)
        wait = 0.0
        if need_m > 0:
            if s["m_ps"] <= 0 or cost_m > s["cap_m"]:
                return math.inf
            wait = max(wait, need_m / s["m_ps"])
        if need_c > 0:
            if s["c_ps"] <= 0 or cost_c > s["cap_c"]:
                return math.inf
            wait = max(wait, need_c / s["c_ps"])
        return wait

    def hw(self) -> World:
        return self.worlds[0]

    def best_payer(self, cost_m: float, cost_c: float) -> Tuple[World, float]:
        """Research is paid from the planet in context; assume the best-stocked established world."""
        best: Optional[Tuple[World, float]] = None
        for w in self.worlds:
            if w.outpost:
                continue
            wait = self.afford_wait(w, cost_m, cost_c)
            if best is None or wait < best[1]:
                best = (w, wait)
        return best if best else (self.hw(), math.inf)

    def empire_hourly(self) -> Tuple[float, float, float]:
        m = c = f = 0.0
        for w in self.worlds:
            s = self.stats(w)
            m += s["m_ps"] * 3600.0
            c += s["c_ps"] * 3600.0
            f += s["f_ps"] * 3600.0
        return m, c, f

    def research_cost(self, tech: str, level: int) -> Tuple[int, int]:
        if self.lever == "free_research_cost":
            return 0, 0
        scale = 0.9 if self.lever == "res_cost_x0.9" else 1.0
        ctx = self._ctx
        if ctx is None:
            m, c, _f = self.empire_hourly()
            ctx = (int(m + c), float(research_empire_maturity_index(self._world_levels())), len(self.worlds))
            self._ctx = ctx
        mm, cc = _research_payment(tech, int(level), ctx[0], ctx[1], ctx[2])
        return int(mm * scale), int(cc * scale)

    def _world_levels(self) -> List[int]:
        return [self.sb.planet(w.planet_id)["level"] for w in self.worlds]

    # -- blockers -------------------------------------------------------------
    def block(self, reason: str, detail: str = "") -> None:
        if not reason:
            return
        day = int(self.t // DAY)
        row = self.blockers.setdefault(
            reason,
            {"first_day": day, "last_day": day, "days": set(), "recovery": BLOCKER_RECOVERY.get(reason, ""), "detail": detail},
        )
        row["last_day"] = day
        row["days"].add(day)

    # -- goal resolution ------------------------------------------------------
    def step_toward(self, key: str, level: int, eff: Dict[str, int], depth: int = 0) -> Optional[str]:
        """Next building to construct to reach `key` at `level`; records research needs."""
        if int(eff.get(key, 0)) >= level or depth > 8:
            return None
        req = BUILDING_REQUIREMENTS.get(key, {}) or {}
        for pre, plvl in (req.get("buildings") or {}).items():
            if int(eff.get(pre, 0)) < int(plvl):
                return self.step_toward(pre, int(plvl), eff, depth + 1)
        for tech, tlvl in (req.get("research") or {}).items():
            if int(self.research.get(tech, 0)) < int(tlvl):
                self.research_needs[tech] = max(int(self.research_needs.get(tech, 0)), int(tlvl))
                return None
        return key

    def build_goals(self, w: World, eff: Dict[str, int]) -> List[Tuple[str, int]]:
        L = lambda k: int(eff.get(k, 0))  # noqa: E731
        r = self._resolver(w, eff)
        s = self.stats(w)
        goals: List[Tuple[str, int]] = []
        if w.outpost:
            for spec in ESTABLISHMENT_MILESTONE_DEFS:
                if spec.get("placeholder") or not spec.get("required", True):
                    continue
                goals.append((str(spec["building"]), max(1, int(spec.get("min_level") or 1))))
            return goals
        goals += [("solar_plant", 1), ("metal_mine", 1), ("crystal_mine", 1)]
        mine_avg = (L("metal_mine") + L("crystal_mine")) // 2
        if w.home:
            goals.append(("research_lab", 1))
            goals.append(("fuel_cell_plant", 1))
        if s["ratio"] < 0.98:
            goals.append(("solar_plant", L("solar_plant") + 1))
        if w.home and self.storage_need:
            goals.append((self.storage_need, L(self.storage_need) + 1))
        if w.home:
            lab_target = max(1, min(10, 1 + mine_avg // 5), int(self.lab_need))
            if self.sc.topology == "S11":
                lab_target = max(lab_target, 4)
            goals.append(("research_lab", lab_target))
            goals.append(("command_center", 3))
            if self.mandate_phase() and self.boss_route and (self.boss is None or self.boss.get("stage") == "building"):
                for b, lvl in ((get_ship(BOSS_SHIP_KEY).get("requirements") or {}).get("buildings") or {}).items():
                    goals.append((str(b), int(lvl)))
            if self.mandate_phase() and self.survey_remaining() > 0:
                goals.append(("orbital_shipyard", int(get_ship(SURVEY_SHIP_KEY)["requirements"]["buildings"]["orbital_shipyard"])))
            if self.sc.topology == "S11":
                goals.append(("orbital_shipyard", int(get_ship("seed_ark")["requirements"]["buildings"]["orbital_shipyard"])))
                goals.append(("fuel_cell_plant", max(1, min(mine_avg // 2, 12))))
            else:
                goals.append(("fuel_cell_plant", max(1, min(mine_avg // 3, 8))))
        # storage guard: never let the next mine/building cost exceed what the depot can hold
        lowest = "metal_mine" if L("metal_mine") <= L("crystal_mine") else "crystal_mine"
        nm, nc = self.ucost(lowest, L(lowest), w)
        if nm > 0.9 * s["cap_m"]:
            goals.append(("metal_storage", L("metal_storage") + 1))
        if nc > 0.9 * s["cap_c"]:
            goals.append(("crystal_storage", L("crystal_storage") + 1))
        if mine_avg >= 12:
            goals.append(("nanofactory", min(20, mine_avg // 3)))
        mine_cap = r.get_max_building_level("metal_mine")

        def blocked(k: str) -> bool:
            # pj/1 policy: below the old nexus ceiling a mine waits for the nexus buildings.  Under the canonical Nodebuster
            # queue (asc != legacy) there is no cap beyond that ceiling, so mines at/above L200 are never blocked.
            lvl = L(k)
            return lvl >= mine_cap and (not self.mines_uncapped or lvl < PRE_NODEBUSTER_MINE_CEILING)

        other = "crystal_mine" if lowest == "metal_mine" else "metal_mine"
        if blocked(lowest):
            goals.append(("geothermal_nexus", L("geothermal_nexus") + 1))
            goals.append(("planet_core_nexus", L("planet_core_nexus") + 1))
        elif not self.asc_hold(w, lowest, eff):
            goals.append((lowest, L(lowest) + 1))
        if not blocked(other) and not self.asc_hold(w, other, eff):
            goals.append((other, L(other) + 1))
        return goals

    def choose_build(self, w: World) -> Optional[Tuple[str, int, int, int]]:
        """Highest-priority goal that is affordable now or within PATIENCE_SEC.

        Goals that would take longer to afford are skipped (a player does not idle
        behind a hopeless purchase); if every goal is hopeless the nearest one is
        returned so the queue still waits for something.
        """
        if self.sc.strategy == "v2":
            return self.choose_build_v2(w)
        eff = self.eff_buildings(w)
        r = self._resolver(w, eff)
        s = self.stats(w)
        fallback: Optional[Tuple[float, Tuple[str, int, int, int]]] = None
        for key, level in self.build_goals(w, eff):
            if w.outpost and key not in OUTPOST_ALLOWED_BUILDINGS:
                continue
            nxt = self.step_toward(key, level, eff)
            if nxt is None:
                continue
            if w.outpost and nxt not in OUTPOST_ALLOWED_BUILDINGS:
                continue
            cur = int(eff.get(nxt, 0))
            if cur >= self.max_level(w, r, nxt):
                continue
            if not has_building_requirements(eff, self.research, nxt):
                continue
            cm, cc = self.ucost(nxt, cur, w)
            if cm > s["cap_m"] or cc > s["cap_c"]:
                storage = "metal_storage" if cm > s["cap_m"] else "crystal_storage"
                if int(eff.get(storage, 0)) < r.get_max_building_level(storage) and has_building_requirements(eff, self.research, storage):
                    cm2, cc2 = self.ucost(storage, int(eff.get(storage, 0)))
                    cand = (storage, int(eff.get(storage, 0)) + 1, int(cm2), int(cc2))
                else:
                    self.block("storage_cap_below_cost", f"{nxt} L{cur + 1} on world {w.idx}")
                    continue
            else:
                cand = (nxt, cur + 1, int(cm), int(cc))
            wait = self.afford_wait(w, cand[2], cand[3])
            if wait <= PATIENCE_SEC:
                return cand
            if math.isfinite(wait) and (fallback is None or wait < fallback[0]):
                fallback = (wait, cand)
        return fallback[1] if fallback else None

    # -- pj-policy/2: payback-ranked purchases, saving for the best one -------------
    # Same goals, prerequisites, costs, queue depth and action windows as pj-policy/1 (so it is a legal
    # play pattern); only the choice differs: among income purchases take the lowest
    # (time-to-afford + payback), save for it instead of buying cheaper filler, and let the canonical
    # energy model (solar vs mine) and the depot rule decide the priority dynamically.
    def _build_candidates_v2(self, w: World, eff: Dict[str, int]) -> List[Tuple[Tuple[str, int, int, int], str]]:
        r = self._resolver(w, eff)
        s = self.stats(w)
        goals = list(self.build_goals(w, eff))
        if not w.outpost:
            goals.append(("solar_plant", int(eff.get("solar_plant", 0)) + 1))
        out: List[Tuple[Tuple[str, int, int, int], str]] = []
        seen: set = set()
        for key, level in goals:
            if w.outpost and key not in OUTPOST_ALLOWED_BUILDINGS:
                continue
            nxt = self.step_toward(key, level, eff)
            if nxt is None:
                continue
            if w.outpost and nxt not in OUTPOST_ALLOWED_BUILDINGS:
                continue
            cur = int(eff.get(nxt, 0))
            if cur >= self.max_level(w, r, nxt):
                continue
            if not has_building_requirements(eff, self.research, nxt):
                continue
            cm, cc = self.ucost(nxt, cur, w)
            if cm > s["cap_m"] or cc > s["cap_c"]:
                storage = "metal_storage" if cm > s["cap_m"] else "crystal_storage"
                if int(eff.get(storage, 0)) < r.get_max_building_level(storage) and has_building_requirements(eff, self.research, storage):
                    cm2, cc2 = self.ucost(storage, int(eff.get(storage, 0)))
                    cand = (storage, int(eff.get(storage, 0)) + 1, int(cm2), int(cc2))
                else:
                    self.block("storage_cap_below_cost", f"{nxt} L{cur + 1} on world {w.idx}")
                    continue
            else:
                cand = (nxt, cur + 1, int(cm), int(cc))
            if cand[0] in seen:
                continue
            seen.add(cand[0])
            if w.outpost:
                kind = "enabler"
            elif cand[0].endswith("_storage"):
                kind = "storage"
            elif cand[0] in PROD_BUILDINGS:
                kind = "prod"
            elif cand[0] == "nanofactory":
                kind = "neutral"
            else:
                kind = "enabler"
            out.append((cand, kind))
        return out

    def shadow_prices(self, w: World, cm: float, cc: float) -> Tuple[float, float]:
        """Dynamic priority by bottleneck: the resource that takes longer to produce for this purchase is priced 1,
        the slack one low (a surplus crystal that overflows the depot is worth little)."""
        s = self.stats(w)
        tm = cm / s["m_ps"] if s["m_ps"] > 0 else math.inf
        tc = cc / s["c_ps"] if s["c_ps"] > 0 else math.inf
        return (1.0, SLACK_PRICE) if tm >= tc else (SLACK_PRICE, 1.0)

    def choose_build_v2(self, w: World) -> Optional[Tuple[str, int, int, int]]:
        eff = self.eff_buildings(w)
        best: Optional[Tuple[float, Tuple[str, int, int, int]]] = None
        fallback: Optional[Tuple[float, Tuple[str, int, int, int]]] = None
        base = None
        for cand, kind in self._build_candidates_v2(w, eff):
            wait = self.afford_wait(w, cand[2], cand[3])
            if not math.isfinite(wait):
                continue
            if kind in ("enabler", "storage"):
                if wait <= PATIENCE_V2_SEC:
                    return cand
            elif kind == "prod":
                if base is None:
                    base = self.hyp_income(w, eff)
                after = self.hyp_income(w, {**eff, cand[0]: cand[1]})
                pm, pc = self.shadow_prices(w, cand[2], cand[3])
                gain = pm * (after[0] - base[0]) + pc * (after[1] - base[1])
                if gain > 0:
                    score = wait + (pm * cand[2] + pc * cand[3]) / gain
                    if best is None or score < best[0]:
                        best = (score, cand)
                    continue
            if fallback is None or wait < fallback[0]:
                fallback = (wait, cand)
        if best is not None:
            return best[1]
        return fallback[1] if fallback else None

    def choose_research_v2(self) -> Optional[Tuple[str, int, int, int, int]]:
        hw = self.hw()
        eff = self.eff_buildings(hw)
        queued = {j.key: j.target for j in self.rqueue}
        best: Optional[Tuple[float, Tuple[str, int, int, int, int]]] = None
        fallback: Optional[Tuple[float, Tuple[str, int, int, int, int]]] = None
        established = [x for x in self.worlds if not x.outpost]
        goals = self.research_goals()
        must_n = int(getattr(self, "_must_goals", 0))
        for gi, (tech0, level) in enumerate(goals):
            cur0 = max(int(self.research.get(tech0, 0)), int(queued.get(tech0, 0)))
            cur = cur0
            if cur >= level or tech0 not in RESEARCH_TECHS:
                continue
            tech, level, cur = self.resolve_research_prereq(tech0, level, cur, queued)
            if tech is None:
                continue
            if not has_research_requirements(eff, {**self.research, **queued}, tech):
                req = RESEARCH_TECHS[tech].get("requirements") or {}
                for b, bl in (req.get("buildings") or {}).items():
                    if b == "research_lab" and int(eff.get(b, 0)) < int(bl):
                        self.lab_need = max(int(self.lab_need), int(bl))
                continue
            cm, cc = self.research_cost(tech, cur + 1)
            payer, wait = self.best_payer(cm, cc)
            s = self.stats(payer)
            cand = (tech, cur + 1, cm, cc, payer.idx)
            if cm > s["cap_m"] or cc > s["cap_c"]:
                return (tech, cur + 1, cm, cc, hw.idx)
            if not math.isfinite(wait):
                continue
            if gi >= must_n:
                trial = {**self.research, tech0: cur0 + 1}  # value of the economy tech this purchase leads to
                pm, pc = self.shadow_prices(payer, cm, cc)
                gain = 0.0
                for x in established:
                    b = self.eff_buildings(x)
                    now = self.hyp_income(x, b)
                    nxt_ = self.hyp_income(x, b, trial)
                    gain += pm * (nxt_[0] - now[0]) + pc * (nxt_[1] - now[1])
                if gain > 0:
                    score = wait + (pm * cm + pc * cc) / gain
                    if best is None or score < best[0]:
                        best = (score, cand)
                    continue
            elif wait <= 3 * PATIENCE_V2_SEC:  # required for a gate / ship / mandate: a planner saves up to three days for it
                return cand
            if fallback is None or wait < fallback[0]:
                fallback = (wait, cand)
        if best is not None:
            return best[1]
        return fallback[1] if fallback else None

    @staticmethod
    def category_of(key: str) -> str:
        if key in ("metal_mine", "crystal_mine", "fuel_cell_plant"):
            return "mines"
        if key == "solar_plant":
            return "solar"
        if key.endswith("_storage"):
            return "storage"
        return "infrastructure"

    def next_id(self) -> int:
        self._jid += 1
        return self._jid

    # -- queue mechanics ------------------------------------------------------
    def duration_for(self, w: World, job: Job) -> float:
        r = self._resolver(w, w.buildings)
        dur = float(r.get_build_time_seconds(job.key, job.target))
        if w.asc_any and job.key in EVOLVABLE_MINES:
            _cost_bps, time_bps = _nodebuster_rebuild_bps(w.planet_id, job.key, int(job.target), conn=self.sb.conn, profiles=self.profiles(w))
            if time_bps != 10000:
                dur = float(_scale_bps(int(dur), time_bps, minimum=building_progress_floor_seconds(job.key, int(job.target))))
        if self.is_resonating(w):
            dur *= 1.0 - self.reduction
        if self.lever == "instant_build":
            dur *= LEVER_TIME_FACTOR
        elif self.lever == "build_time_x0.88":
            dur *= 0.88
        elif self.lever == "build_time_x0.5":
            dur *= 0.5
        return max(1.0, dur)

    def is_resonating(self, w: World) -> bool:
        if not self.resonance_enabled:
            return False
        mode = TRAIT_SCENARIOS[self.sc.trait]["worlds"]
        if mode == "one" and self.resonance_world_idx is not None and w.idx != self.resonance_world_idx:
            return False
        p = self.sb.planet(w.planet_id)
        ok = resonance_qualified(
            enabled=True,
            planet_level=p["level"],
            reveal_tier=p["tier"],
            specialization_active=w.specialization_active,
        )
        if ok and mode == "one" and self.resonance_world_idx is None:
            self.resonance_world_idx = w.idx
        return ok

    def start_next(self, w: World) -> None:
        if w.queue and w.queue[0].start is None:
            job = w.queue[0]
            job.start = self.t
            job.finish = self.t + self.duration_for(w, job)

    def enqueue_build(self, w: World, key: str, target: int, cm: int, cc: int) -> None:
        assert w.metal >= cm - EPS and w.crystal >= cc - EPS
        before = max([int(w.buildings.get(key, 0))] + [j.target for j in w.queue if j.key == key])
        if target != before + 1:
            self.invariant_violations.append(f"day {int(self.t // DAY)}: level skip {key} {before}->{target}")
        w.metal -= cm
        w.crystal -= cc
        cat = self.category_of(key)
        self.spend[cat] += cm
        self.spend_c[cat] += cc
        if w.outpost:
            self.spend["colony_expansion"] += 0.0  # establishment costs are tracked in the package
        job = Job(self.next_id(), "build", key, target, cm, cc, cat, w.idx)
        w.queue.append(job)
        self.start_next(w)

    def fill_build_queue(self, w: World) -> None:
        guard = 0
        while len(w.queue) < self.build_limit and guard < 8:
            guard += 1
            pick = self.choose_build(w)
            if pick is None:
                return
            key, target, cm, cc = pick
            if self.trader:
                self.trade_for(w, cm, cc)
            if w.metal + EPS < cm or w.crystal + EPS < cc:
                return
            self.enqueue_build(w, key, target, cm, cc)

    def finish_build(self, w: World, job: Job) -> None:
        if job.jid in self.completed_ids:
            self.invariant_violations.append(f"duplicate completion job {job.jid}")
            return
        self.completed_ids.add(job.jid)
        self._ctx = None
        w.buildings[job.key] = int(job.target)
        w.queue.pop(0)
        if job.key in ASC_MINES:
            self.asc_track_finish(w, job.key)
        got = self.sb.grant_xp("building_finish", w.planet_id, self.t, f"building_finish:job:{job.jid}")
        self.xp_by_source["building_finish"] = self.xp_by_source.get("building_finish", 0) + got
        if not w.home:
            self.sb.set_buildings(w.planet_id, w.buildings)
            self.sb.sync_establishment(w.planet_id)
            self.refresh_establishment(w)
        self.start_next(w)

    def refresh_establishment(self, w: World) -> None:
        """Mirror the canonical outpost/establishment state of a colony (never decided by the sim)."""
        if w.home:
            return
        st = self.sb.establishment_state(w.planet_id)
        p = self.sb.planet(w.planet_id)
        day = round(self.t / DAY, 2)
        if w.outpost and not st["restricted_outpost"]:
            w.outpost = False
            w.unrestricted_at = self.t
            self.colony_log.append({"event": "unrestricted", "world": w.idx, "day": day, "via": "legacy_full_colony" if (st["legacy_full_colony"] and not st["milestones_complete"]) else "milestones"})
        if w.established_at is None and st["milestones_complete"]:
            w.established_at = self.t
            self.colony_log.append({"event": "established", "world": w.idx, "day": day})
        if w.dna_early_at is None and p["tier"] >= 1 and not st["milestones_complete"]:
            w.dna_early_at = self.t
            self.findings.setdefault(
                "dna_revealed_before_establishment",
                {"first_day": day, "worlds": [], "mechanism": "colonize XP lifts planet level 0->2, is_legacy_full_colony() turns true, ensure_planet_evolution() -> bootstrap_legacy_establishment() sets dna_reveal_tier=1"},
            )["worlds"].append(w.idx)

    # -- Mine Ascension (asc-model/1) -------------------------------------------------
    def asc_rebuilding(self, w: World, key: str) -> bool:
        """True while the mine climbs back through its lifetime best depth (canonical rebuild window of the owner)."""
        st = self.profiles(w)[key]["state"] if w.asc_any else None
        return bool(st and int(st["ascension_count"]) > 0 and int(w.buildings.get(key, 0)) < int(st["best_depth"]))

    def asc_stagger_blocked(self, w: World, key: str) -> bool:
        """Income-continuity rule of the policy: only one production mine of a planet rebuilds at a time (policy ``G``: in the whole empire)."""
        if self.asc_kind == "G":
            return any(self.asc_rebuilding(ow, other) for ow in self.worlds for other in ASC_MINES if ow is not w or other != key)
        return any(self.asc_rebuilding(w, other) for other in ASC_MINES if other != key)

    def asc_target(self, w: World, key: str) -> Optional[int]:
        """Depth at which the policy ascends this mine next (None: it will not ascend again)."""
        if self.asc_depth is None:
            return None
        if self.asc_kind == "M":  # one single reset in the whole empire: the first mine that gets there
            return None if self.asc_runs else self.asc_depth
        if self.asc_kind == "P" and key != "metal_mine":  # selective: only the metal mine of every planet
            return None
        if self.asc_kind == "C" and key != "crystal_mine":  # selective: only the crystal mine of every planet
            return None
        if self.asc_kind == "A":  # button-masher: always eligible (the weekly cooldown is applied in maybe_ascend)
            return self.asc_depth
        if self.asc_kind == "H" and w.idx != 0:  # selective: only the homeworld
            return None
        if self.asc_kind == "T" or not w.asc_any:
            return self.asc_depth
        st = self.profiles(w)[key]["state"]
        count = int(st["ascension_count"])
        if self.asc_kind in ("O", "G", "P", "H", "C"):
            return self.asc_depth if count < max(1, self.asc_step) else None
        if self.asc_max is not None and count >= self.asc_max:  # capped ladder: the mine has had its resets
            return None
        best = int(st["best_depth"])
        return max(self.asc_depth, best + self.asc_step) if count > 0 else self.asc_depth

    def asc_hold(self, w: World, key: str, eff: Dict[str, int]) -> bool:
        """The mine is at its ascension depth and waits for the reset: do not deepen it further."""
        if self.asc_depth is None or w.outpost or key not in ASC_MINES or self.asc_kind == "A":  # the button-masher never waits at a depth
            return False
        target = self.asc_target(w, key)
        return target is not None and int(eff.get(key, 0)) >= target and not self.asc_stagger_blocked(w, key)

    def maybe_ascend(self, w: World) -> None:
        if self.asc_depth is None or w.outpost:
            return
        for key in sorted(ASC_MINES, key=lambda k: -int(w.buildings.get(k, 0))):
            lvl = int(w.buildings.get(key, 0))
            target = self.asc_target(w, key)
            if target is None or lvl < target:
                continue
            if any(j.key == key for j in w.queue):  # canonical owner: queue_pending
                continue
            if self.asc_kind == "A" and self.t / DAY - self.asc_last.get((w.idx, key), -1e9) < AGGRESSIVE_COOLDOWN_DAYS:
                continue
            if self.asc_kind != "A" and self.asc_stagger_blocked(w, key):  # the button-masher ignores the income-continuity rule
                continue
            self.ascend(w, key)
            return

    def ascend(self, w: World, key: str) -> None:
        level = int(w.buildings.get(key, 0))
        before = self.stats(w)
        income_before = (before["m_ps"] + before["c_ps"]) * 3600.0
        self.sb.set_buildings(w.planet_id, w.buildings)
        ok, reason, data = self.sb.ascend_mine(w.planet_id, key)
        if not ok:
            self.asc_rejections[reason] = self.asc_rejections.get(reason, 0) + 1
            return
        restart = int(data["level"])
        w.buildings[key] = restart
        w.asc_any = True
        self._bump_asc()
        after = self.stats(w)
        run = {
            "world": w.idx,
            "mine": key,
            "run": int(data["evolution_rank"]),
            "day": round(self.t / DAY, 3),
            "from_level": level,
            "ap_gain": int(data["points_gain"]),
            "reset_level": restart,
            "best_depth": int(data["best_depth"]),
            "income_before_h": int(income_before),
            "income_after_h": int((after["m_ps"] + after["c_ps"]) * 3600.0),
            "rebuild_to_best_days": None,
            "income_recovered_days": None,
        }
        self.asc_runs.append(run)
        self.asc_last[(w.idx, key)] = self.t / DAY
        self.asc_open[(w.idx, key)] = run
        self.asc_spend_ap(w, key)

    def _bump_asc(self) -> None:
        self.asc_ver += 1
        self._probe_caches.clear()
        self._ctx = None

    def asc_next_skill(self, w: World, key: str) -> Optional[Tuple[str, int]]:
        prof = self.profiles(w)[key]
        state, skills = prof["state"], prof["skills"]
        for skill in ASC_SKILL_ORDERS[self.sc.asc_skills]:
            cfg = nodebuster_mod.SKILL_CATALOG[skill]
            rank = int(skills.get(skill, 0))
            if rank >= int(cfg["max_rank"]) or not nodebuster_mod.skill_prerequisites_met(skill, skills, state):
                continue
            return skill, int(nodebuster_mod.skill_point_cost(skill, rank))
        return None

    def asc_spend_ap(self, w: World, key: str) -> None:
        """Strict-priority AP spending through the canonical purchase (the server validates prerequisites, cost and balance)."""
        for _ in range(64):
            pick = self.asc_next_skill(w, key)
            if pick is None:
                return
            skill, cost = pick
            if cost > int(self.profiles(w)[key]["state"]["points_unspent"]):
                return  # save for it
            ok, reason, data = self.sb.buy_skill(w.planet_id, key, skill)
            if not ok:
                self.asc_rejections[f"skill:{reason}"] = self.asc_rejections.get(f"skill:{reason}", 0) + 1
                return
            self._bump_asc()
            self.asc_skill_log.append({"world": w.idx, "mine": key, "day": round(self.t / DAY, 3), "skill": skill, "rank": int(data["skill_rank"]), "cost": int(data["skill_cost"])})

    def asc_track_finish(self, w: World, key: str) -> None:
        run = self.asc_open.get((w.idx, key))
        level = int(w.buildings.get(key, 0))
        self.asc_peak[(w.idx, key)] = max(self.asc_peak.get((w.idx, key), 0), level)
        if run is None:
            return
        days = (self.t / DAY) - float(run["day"])
        if run["rebuild_to_best_days"] is None and level >= int(run["best_depth"]):
            run["rebuild_to_best_days"] = round(days, 3)
        if run["income_recovered_days"] is None:
            s = self.stats(w)
            if (s["m_ps"] + s["c_ps"]) * 3600.0 >= float(run["income_before_h"]):
                run["income_recovered_days"] = round(days, 3)
        if run["rebuild_to_best_days"] is not None and run["income_recovered_days"] is not None:
            self.asc_open.pop((w.idx, key), None)

    def asc_summary(self) -> Dict[str, Any]:
        """Per planet and mine: canonical state (AP, ranks, best depth) read back from the sandbox DB."""
        rows: List[Dict[str, Any]] = []
        for w in self.worlds:
            prof = self.profiles(w) if w.asc_any else None
            for key in ASC_MINES:
                level = int(w.buildings.get(key, 0))
                st = prof[key]["state"] if prof else {"ascension_count": 0, "points_earned": 0, "points_unspent": 0, "best_depth": 0, "last_depth": 0}
                sk = prof[key]["skills"] if prof else {}
                peak = max(level, int(st["best_depth"]), self.asc_peak.get((w.idx, key), 0))
                rows.append(
                    {
                        "world": w.idx,
                        "mine": key,
                        "level": level,
                        "peak_depth": peak,
                        "ascensions": int(st["ascension_count"]),
                        "ap_earned": int(st["points_earned"]),
                        "ap_unspent": int(st["points_unspent"]),
                        "ap_spent": int(st["points_earned"]) - int(st["points_unspent"]),
                        "best_depth": int(st["best_depth"]),
                        "skills": {k: int(v) for k, v in sorted(sk.items()) if v},
                        "rebuilding": self.asc_rebuilding(w, key),
                    }
                )
        return {
            "mode": self.sc.asc,
            "skill_order": self.sc.asc_skills,
            "mines": rows,
            "ascensions_total": sum(r["ascensions"] for r in rows),
            "ascensions_max_single_mine": max([r["ascensions"] for r in rows] or [0]),
            "ap_earned_total": sum(r["ap_earned"] for r in rows),
            "ap_spent_total": sum(r["ap_spent"] for r in rows),
            "peak_depth_max": max([r["peak_depth"] for r in rows] or [0]),
            "mines_rebuilding": sum(1 for r in rows if r["rebuilding"]),
        }

    def check_asc_invariants(self) -> None:
        """No free AP, no skipped prerequisites: AP earned must equal the canonical award per run, AP spent the canonical skill costs."""
        if not any(w.asc_any for w in self.worlds):
            return
        for w in self.worlds:
            if not w.asc_any:
                continue
            for key in ASC_MINES:
                st = self.profiles(w)[key]["state"]
                sk = self.profiles(w)[key]["skills"]
                runs = [r for r in self.asc_runs if r["world"] == w.idx and r["mine"] == key]
                awarded, record = 0, 0
                for r in sorted(runs, key=lambda x: float(x["day"])):  # the owner's rule may depend on the mine's record (ap_by_record sandbox rule)
                    awarded += expected_ascension_points(int(r["from_level"]), record)
                    record = max(record, int(r["from_level"]))
                if int(st["points_earned"]) != awarded:
                    self.invariant_violations.append(f"AP mismatch world {w.idx} {key}: earned {st['points_earned']} vs awarded {awarded}")
                spent = sum(sum(nodebuster_mod.skill_point_cost(name, r) for r in range(int(rank))) for name, rank in sk.items())
                if int(st["points_earned"]) - int(st["points_unspent"]) != spent:
                    self.invariant_violations.append(f"AP spent mismatch world {w.idx} {key}: {st['points_earned'] - st['points_unspent']} vs skills {spent}")
                if int(st["points_unspent"]) < 0:
                    self.invariant_violations.append(f"negative AP world {w.idx} {key}")
                for r in runs:
                    if int(r["from_level"]) < nodebuster_mod.ASCENSION_MIN_LEVEL:
                        self.invariant_violations.append(f"ascension below L200 world {w.idx} {key}")

    # -- research -------------------------------------------------------------
    def research_goals(self) -> List[Tuple[str, int]]:
        goals: List[Tuple[str, int]] = []
        for tech, lvl in sorted(self.research_needs.items()):
            goals.append((tech, lvl))
        if self.mandate_phase() and self.boss_route and (self.boss is None or self.boss.get("stage") == "building"):
            for tech, lvl in ((get_ship(BOSS_SHIP_KEY).get("requirements") or {}).get("research") or {}).items():
                goals.append((str(tech), int(lvl)))
        if self.mandate_phase() and self.survey_remaining() > 0:
            for tech, lvl in ((get_ship(SURVEY_SHIP_KEY).get("requirements") or {}).get("research") or {}).items():
                goals.append((str(tech), int(lvl)))
        if self.sc.topology == "S11":
            ark_req = (get_ship("seed_ark").get("requirements") or {}).get("research") or {}
            goals.append(("drone_tech", 2))
            for tech, lvl in ark_req.items():
                goals.append((str(tech), int(lvl)))
            slots = len(self.worlds)  # next expansion index == worlds already owned (HW counts as 0)
            gate = EXPANSION_SLOT_GATES[min(slots, len(EXPANSION_SLOT_GATES)) - 1] if slots >= 1 else EXPANSION_SLOT_GATES[0]
            goals.append((INTERSTELLAR_EXPANSION_TECH, int(gate["expansion_tech"])))
        self._must_goals = len(goals)  # everything before the economy pool is required by a gate / ship / mandate
        hw = self.hw()
        mine_avg = (hw.buildings.get("metal_mine", 0) + hw.buildings.get("crystal_mine", 0)) // 2
        cap = max(2, mine_avg + 4)
        pool = sorted(ECON_TECHS, key=lambda k: (int(self.research.get(k, 0)), ECON_TECHS.index(k)))
        for tech in pool:
            goals.append((tech, min(cap, int(self.research.get(tech, 0)) + 1)))
        return goals

    def resolve_research_prereq(self, tech: str, level: int, cur: int, queued: Dict[str, int]) -> Tuple[Optional[str], int, int]:
        """Follow unmet research prerequisites down the chain; None when the chain is already queued."""
        have = {**self.research, **{k: max(v, int(self.research.get(k, 0))) for k, v in queued.items()}}
        for _ in range(8):
            req = (RESEARCH_TECHS.get(tech, {}).get("requirements") or {}).get("research") or {}
            nxt = next(((t, int(l)) for t, l in req.items() if int(have.get(t, 0)) < int(l)), None)
            if nxt is None:
                return tech, level, cur
            tech, level = nxt
            cur = int(have.get(tech, 0))
            if cur >= level:
                return None, level, cur
        return None, level, cur

    def choose_research(self) -> Optional[Tuple[str, int, int, int, int]]:
        if self.sc.strategy == "v2":
            return self.choose_research_v2()
        hw = self.hw()
        eff = self.eff_buildings(hw)
        queued = {j.key: j.target for j in self.rqueue}
        fallback: Optional[Tuple[float, Tuple[str, int, int, int, int]]] = None
        for tech, level in self.research_goals():
            cur = max(int(self.research.get(tech, 0)), int(queued.get(tech, 0)))
            if cur >= level or tech not in RESEARCH_TECHS:
                continue
            tech, level, cur = self.resolve_research_prereq(tech, level, cur, queued)
            if tech is None:
                continue
            if not has_research_requirements(eff, {**self.research, **queued}, tech):
                req = RESEARCH_TECHS[tech].get("requirements") or {}
                for b, bl in (req.get("buildings") or {}).items():
                    if b == "research_lab" and int(eff.get(b, 0)) < int(bl):
                        self.lab_need = max(int(self.lab_need), int(bl))
                continue
            cm, cc = self.research_cost(tech, cur + 1)
            payer, wait = self.best_payer(cm, cc)
            s = self.stats(payer)
            cand = (tech, cur + 1, cm, cc, payer.idx)
            if cm > s["cap_m"] or cc > s["cap_c"]:
                return (tech, cur + 1, cm, cc, hw.idx)  # storage response is handled by the caller
            if wait <= PATIENCE_SEC:
                return cand
            if math.isfinite(wait) and (fallback is None or wait < fallback[0]):
                fallback = (wait, cand)
        return fallback[1] if fallback else None

    def fill_research_queue(self) -> None:
        guard = 0
        while len(self.rqueue) < min(self.research_limit, self.policy.queue_fill) and guard < 4:
            guard += 1
            pick = self.choose_research()
            if pick is None:
                return
            tech, target, cm, cc, pidx = pick
            payer = self.worlds[pidx]
            s = self.stats(payer)
            if cm > s["cap_m"] or cc > s["cap_c"]:
                self.storage_need = "metal_storage" if cm > s["cap_m"] else "crystal_storage"
                self.block("storage_cap_below_cost", f"research {tech} L{target}")
                return
            self.storage_need = None
            if self.trader:
                self.trade_for(payer, cm, cc)
            if payer.metal + EPS < cm or payer.crystal + EPS < cc:
                return
            payer.metal -= cm
            payer.crystal -= cc
            self.spend["research"] += cm
            self.spend_c["research"] += cc
            self.rqueue.append(Job(self.next_id(), "research", tech, target, cm, cc, "research", payer.idx))
            self.start_research()

    # -- auto_start lever (simulation only): reserve the next unaffordable purchase -------------
    def enqueue_research(self, tech: str, target: int, cm: int, cc: int, pidx: int) -> None:
        payer = self.worlds[pidx]
        payer.metal -= cm
        payer.crystal -= cc
        self.spend["research"] += cm
        self.spend_c["research"] += cc
        self.rqueue.append(Job(self.next_id(), "research", tech, target, cm, cc, "research", payer.idx))
        self.start_research()

    def reserve_next(self) -> None:
        """The player queues what they want next even if it is not affordable yet; the game starts it when funds arrive."""
        if self.lever != "auto_start":
            return
        for w in self.worlds:
            w.reserved = None
            if len(w.queue) < self.build_limit:
                pick = self.choose_build(w)
                if pick is not None and (w.metal + EPS < pick[2] or w.crystal + EPS < pick[3]):
                    w.reserved = pick
        self.r_reserved = None
        if len(self.rqueue) < min(self.research_limit, self.policy.queue_fill):
            rp = self.choose_research()
            if rp is not None:
                payer = self.worlds[rp[4]]
                s = self.stats(payer)
                if rp[2] <= s["cap_m"] and rp[3] <= s["cap_c"] and (payer.metal + EPS < rp[2] or payer.crystal + EPS < rp[3]):
                    self.r_reserved = rp

    def start_reserved(self) -> None:
        if self.lever != "auto_start":
            return
        for w in self.worlds:
            r = w.reserved
            if r is None or len(w.queue) >= self.build_limit:
                continue
            key, target, cm, cc = r
            cur = max([int(w.buildings.get(key, 0))] + [j.target for j in w.queue if j.key == key])
            if target != cur + 1:
                w.reserved = None
            elif w.metal + EPS >= cm and w.crystal + EPS >= cc:
                w.reserved = None
                self.enqueue_build(w, key, target, cm, cc)
        rr = self.r_reserved
        if rr is not None and len(self.rqueue) < min(self.research_limit, self.policy.queue_fill):
            tech, target, cm, cc, pidx = rr
            queued = max([int(self.research.get(tech, 0))] + [j.target for j in self.rqueue if j.key == tech])
            payer = self.worlds[pidx]
            if target != queued + 1:
                self.r_reserved = None
            elif payer.metal + EPS >= cm and payer.crystal + EPS >= cc:
                self.r_reserved = None
                self.enqueue_research(tech, target, cm, cc, pidx)

    def start_research(self) -> None:
        if self.rqueue and self.rqueue[0].start is None:
            job = self.rqueue[0]
            r = self._resolver(self.hw(), self.hw().buildings)
            job.start = self.t
            dur = float(r.get_research_time_seconds(job.key, job.target))
            if self.lever == "instant_research":
                dur *= LEVER_TIME_FACTOR
            elif self.lever == "research_time_x0.88":
                dur *= 0.88
            job.finish = self.t + max(1.0, dur)

    def finish_research(self, job: Job) -> None:
        if job.jid in self.completed_ids:
            self.invariant_violations.append(f"duplicate completion job {job.jid}")
            return
        self.completed_ids.add(job.jid)
        self._ctx = None
        self.rqueue.pop(0)
        self.research[job.key] = int(job.target)
        self.research_ver += 1
        for tech in list(self.research_needs):
            if int(self.research.get(tech, 0)) >= self.research_needs[tech]:
                del self.research_needs[tech]
        if job.key == INTERSTELLAR_EXPANSION_TECH:
            self.sb.set_research(INTERSTELLAR_EXPANSION_TECH, job.target)
        got = self.sb.grant_xp("account_research_finish", self.hw().planet_id, self.t, f"account_research_finish:job:{job.jid}")
        self.xp_by_source["account_research_finish"] = self.xp_by_source.get("account_research_finish", 0) + got
        self.start_research()

    # -- DNA scans / XP -------------------------------------------------------
    def colony_gating_level(self) -> bool:
        """True while some planet level is what blocks the next colony."""
        if self.sc.topology != "S11" or len(self.worlds) >= self.target_worlds:
            return False
        return True

    def maybe_scan(self, w: World) -> None:
        if self.t + EPS < w.next_scan_t:
            return
        p = self.sb.planet(w.planet_id)
        if p["tier"] < 1:
            self.scan_rejections["dna_not_revealed"] = self.scan_rejections.get("dna_not_revealed", 0) + 1
            return
        if p["level"] < dna_analysis.SCAN_MIN_LEVEL:
            self.scan_rejections["level_below_3"] = self.scan_rejections.get("level_below_3", 0) + 1
            return
        if p["level"] >= dna_analysis.SCAN_MAX_LEVEL:
            self.scan_rejections["max_level"] = self.scan_rejections.get("max_level", 0) + 1
            return
        if not (self.policy.scan_in_s1 or self.colony_gating_level()):
            return
        if self.sc.topology == "S11" and w.idx != 0 and p["level"] >= COLONY_MATURITY_REQUIRED_LEVEL and not self.policy.scan_in_s1:
            return
        st = self.sb.scan_status(w.planet_id, self.t)
        if not st.get("visible"):
            self.scan_rejections[str(st.get("reason") or "not_visible")] = self.scan_rejections.get(str(st.get("reason")), 0) + 1
            return
        if not st.get("ready"):
            w.next_scan_t = float(st.get("ready_at") or 0) - SIM_EPOCH
            return
        cost = dna_analysis.scan_cost(p["level"])
        if cost["metal"] > self.policy.scan_frac * w.metal or cost["crystal"] > self.policy.scan_frac * w.crystal:
            self.scan_rejections["deferred_budget"] = self.scan_rejections.get("deferred_budget", 0) + 1
            return
        ok, reason, new_m, new_c, xp = self.sb.scan(w.planet_id, self.t, w.metal, w.crystal)
        if not ok:
            self.scan_rejections[reason] = self.scan_rejections.get(reason, 0) + 1
            return
        spent_m, spent_c = w.metal - new_m, w.crystal - new_c
        w.metal, w.crystal = new_m, new_c
        w.scans += 1
        self._ctx = None
        w.scan_spend_m += spent_m
        w.scan_spend_c += spent_c
        w.next_scan_t = self.t + dna_analysis.SCAN_COOLDOWN_SECONDS
        self.spend["dna_scans"] += spent_m
        self.spend_c["dna_scans"] += spent_c
        self.xp_by_source["dna_scan"] = self.xp_by_source.get("dna_scan", 0) + xp

    def maybe_specialize(self, w: World) -> None:
        if w.specialization_active or not self.resonance_enabled:
            return
        p = self.sb.planet(w.planet_id)
        if p["level"] >= SPECIALIZATION_UNLOCK_LEVEL and p["tier"] >= 1:
            w.specialization_active = True

    def apply_expeditions(self) -> None:
        n = int(self.sc.expeditions_per_day)
        if n <= 0:
            return
        day = int(self.t // DAY)
        if getattr(self, "_exp_day", -1) == day:
            return
        self._exp_day = day
        self._ctx = None
        target = self.xp_focus_world()
        for i in range(n):
            got = self.sb.grant_xp("expedition", target.planet_id, self.t, f"exp:{day}:{i}")
            self.xp_by_source["expedition"] = self.xp_by_source.get("expedition", 0) + got
            self.expedition_count += 1

    def xp_focus_world(self) -> World:
        behind = [w for w in self.worlds[1:] if not w.outpost and self.sb.planet(w.planet_id)["level"] < COLONY_MATURITY_REQUIRED_LEVEL]
        return behind[0] if behind else self.hw()

    # -- Imperial Mandates (real prerequisites, nothing is granted) ---------------
    def mandate_phase(self) -> bool:
        return self.sc.topology == "S11" and len(self.worlds) >= MANDATE_START_WORLDS

    def survey_remaining(self) -> int:
        from game.planet_evolution.imperial_mandates import SURVEY_EXPEDITIONS_REQUIRED

        return max(0, SURVEY_EXPEDITIONS_REQUIRED - self.missions_done - len(self.missions))

    def mandate_reject(self, reason: str) -> None:
        self.mandate_rejections[reason] = self.mandate_rejections.get(reason, 0) + 1
        self.block(reason)

    def mandate_step(self) -> None:
        if not self.mandate_phase():
            return
        self._survey_step()
        self._directive_step()
        self._apex_step()
        self._track_mandates()

    def _track_mandates(self) -> None:
        from game.planet_evolution.imperial_mandates import list_earned_mandates, sync_earned_mandates

        sync_earned_mandates(self.sb.user_id, conn=self.sb.conn, now=SIM_EPOCH + self.t)
        self.sb.conn.commit()
        earned = list_earned_mandates(self.sb.user_id, conn=self.sb.conn)
        for key in earned:
            if key not in self._mandates_seen:
                self._mandates_seen.append(key)
                self.mandate_log.append({"mandate": key, "day": round(self.t / DAY, 2), "worlds": len(self.worlds)})

    def _survey_step(self) -> None:
        if self.survey_remaining() <= 0 and not self.missions and self.ships_home <= 0 and not self.ship_build:
            return
        hw = self.hw()
        ship = get_ship(SURVEY_SHIP_KEY) or {}
        req = ship.get("requirements") or {}
        ready = all(int(hw.buildings.get(b, 0)) >= int(l) for b, l in (req.get("buildings") or {}).items()) and all(
            int(self.research.get(t, 0)) >= int(l) for t, l in (req.get("research") or {}).items()
        )
        if self.survey_remaining() > 0 and self.ships_home + (self.ship_build or {}).get("count", 0) + len(self.missions) < SURVEY_SHIPS:
            if not ready:
                self.mandate_reject("survey_ship_prerequisites")
                return
            cost = ship.get("build_cost") or {}
            n = SURVEY_SHIPS
            cm, cc, cf = int(cost.get("metal", 0)) * n, int(cost.get("crystal", 0)) * n, int(cost.get("fuel_cells", 0)) * n
            if hw.metal + EPS < cm or hw.crystal + EPS < cc or hw.fuel + EPS < cf:
                self.mandate_reject("survey_ships_unaffordable")
                return
            hw.metal -= cm
            hw.crystal -= cc
            hw.fuel -= cf
            self.spend["mandates"] += cm
            self.spend_c["mandates"] += cc
            self.spend_f += cf
            cycle = float(production_level_cycle_seconds(int(ship.get("build_seconds", 260)), max(1, int(hw.buildings.get("orbital_shipyard", 0)))))
            self.ship_build = {"ready": self.t + cycle, "count": n}
        fuel_each = int(ship.get("fuel", 0))
        while self.ships_home > 0 and self.survey_remaining() > 0 and hw.fuel + EPS >= fuel_each:
            hw.fuel -= fuel_each
            self.spend_f += fuel_each
            self.ships_home -= 1
            self._movement_seq += 1
            self.missions.append({"arrive": self.t + EXPEDITION_ROUND_SEC, "movement": self._movement_seq})

    def finish_mission(self, m: Dict[str, Any]) -> None:
        from game.expedition_events import record_expedition_daily_value

        record_expedition_daily_value(self.sb.user_id, int(m["movement"]), EXPEDITION_RECORD_VALUE, conn=self.sb.conn, ts=SIM_EPOCH + self.t)
        self.sb.conn.commit()
        got = self.sb.grant_xp("expedition", self.hw().planet_id, self.t, f"expedition:movement:{m['movement']}")
        self.xp_by_source["expedition"] = self.xp_by_source.get("expedition", 0) + got
        self.missions_done += 1
        self.ships_home += 1
        self._ctx = None

    def _directive_step(self) -> None:
        if self.vote_done:
            return
        from game.galactic_directives.voting import submit_directive_vote

        galaxy = int(self.sb.conn.execute("SELECT galaxy FROM planets WHERE id = ?;", (self.hw().planet_id,)).fetchone()[0])
        res = submit_directive_vote(self.sb.user_id, galaxy, "expansion", conn=self.sb.conn, now=int(SIM_EPOCH + self.t))
        if res.get("ok"):
            self.vote_done = True
            self.mandate_log.append({"action": "directive_vote", "day": round(self.t / DAY, 2)})
        else:
            self.mandate_reject(f"directive_vote_{res.get('reason')}")

    def _apex_step(self) -> None:
        from game.planet_evolution.service import pick_specialization, start_ascension, upgrade_specialization_tier
        from game.planet_evolution.specialization import eligible_specialization_keys, tier_upgrade_requirements

        hw = self.hw()
        pid = hw.planet_id
        if self.asc:
            return
        row = self.sb.conn.execute("SELECT ascension_key, specialization_key, specialization_tier, planet_level FROM planets WHERE id = ?;", (pid,)).fetchone()
        if str(row["ascension_key"] or ""):
            return
        if not row["specialization_key"]:
            if int(row["planet_level"]) < SPECIALIZATION_UNLOCK_LEVEL:
                self.mandate_reject("apex_waiting_planet_level")
                return
            options = eligible_specialization_keys(pid, self.sb.conn)
            if not options:
                self.mandate_reject("apex_no_eligible_specialization")
                self.boss_route = True
                self._boss_step()
                return
            ok, reason, _extra = pick_specialization(pid, options[0], self.sb.user_id, conn=self.sb.conn)
            self.sb.conn.commit()
            if not ok:
                self.mandate_reject(f"apex_pick_{reason}")
                return
            self.spec_picked = options[0]
            self.mandate_log.append({"action": "specialization_picked", "day": round(self.t / DAY, 2), "tier": 0})
            row = self.sb.conn.execute("SELECT ascension_key, specialization_key, specialization_tier, planet_level FROM planets WHERE id = ?;", (pid,)).fetchone()
        while int(row["specialization_tier"] or 0) < 3:
            ok_t, _missing = tier_upgrade_requirements(pid, self.sb.conn)
            if not ok_t:
                self.mandate_reject("apex_waiting_planet_level")
                return
            ok, reason, _extra = upgrade_specialization_tier(pid, self.sb.user_id, conn=self.sb.conn)
            self.sb.conn.commit()
            if not ok:
                self.mandate_reject(f"apex_tier_{reason}")
                return
            row = self.sb.conn.execute("SELECT ascension_key, specialization_key, specialization_tier, planet_level FROM planets WHERE id = ?;", (pid,)).fetchone()
            self.mandate_log.append({"action": "specialization_tier", "day": round(self.t / DAY, 2), "tier": int(row["specialization_tier"])})
        from game.planet_evolution.ascension import ascension_cost_resources, check_ascension_requirements

        cost = ascension_cost_resources(APEX_ASCENSION_KEY)
        s = self.stats(hw)
        if cost["metal"] > s["cap_m"] or cost["crystal"] > s["cap_c"]:
            self.storage_need = "metal_storage" if cost["metal"] > s["cap_m"] else "crystal_storage"
            self.mandate_reject("storage_cap_below_cost")
            return
        self.sb.conn.execute("UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;", (hw.metal, hw.crystal, pid))
        self.sb.conn.commit()
        ok_req, missing = check_ascension_requirements(pid, APEX_ASCENSION_KEY, self.sb.conn)
        if not ok_req:
            self.mandate_reject("apex_ascension_" + ("unaffordable" if all(str(x).startswith("cost:") for x in missing) else "requirements"))
            return
        ok, reason, extra = start_ascension(pid, APEX_ASCENSION_KEY, self.sb.user_id, conn=self.sb.conn)
        self.sb.conn.commit()
        if not ok:
            self.mandate_reject(f"apex_ascension_{reason}")
            return
        after = self.sb.conn.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,)).fetchone()
        self.spend["mandates"] += hw.metal - float(after["metal"])
        self.spend_c["mandates"] += hw.crystal - float(after["crystal"])
        hw.metal, hw.crystal = float(after["metal"]), float(after["crystal"])
        duration = float(get_ascension_def(APEX_ASCENSION_KEY).get("duration_days") or 7) * DAY
        self.asc = {"finish_sim": self.t + duration, "db_finish": float((extra or {}).get("finish_at") or 0)}
        self.mandate_log.append({"action": "ascension_started", "day": round(self.t / DAY, 2)})

    def _boss_step(self) -> None:
        """World Boss claim route: DNA-independent apex mandate (one damaging hit + claim)."""
        from game import world_boss as wb
        from game.fleet import set_planet_ships

        hw = self.hw()
        now_abs = SIM_EPOCH + self.t
        if self.boss is None:
            ship = get_ship(BOSS_SHIP_KEY) or {}
            req = ship.get("requirements") or {}
            if not (
                all(int(hw.buildings.get(b, 0)) >= int(l) for b, l in (req.get("buildings") or {}).items())
                and all(int(self.research.get(t, 0)) >= int(l) for t, l in (req.get("research") or {}).items())
            ):
                self.mandate_reject("apex_boss_prerequisites")
                return
            cost = ship.get("build_cost") or {}
            cm, cc, cf = (int(cost.get(k, 0)) * BOSS_SHIPS for k in ("metal", "crystal", "fuel_cells"))
            if hw.metal + EPS < cm or hw.crystal + EPS < cc or hw.fuel + EPS < cf:
                self.mandate_reject("apex_boss_ships_unaffordable")
                return
            hw.metal -= cm
            hw.crystal -= cc
            hw.fuel -= cf
            self.spend["mandates"] += cm
            self.spend_c["mandates"] += cc
            self.spend_f += cf
            cycle = float(production_level_cycle_seconds(int(ship.get("build_seconds", 60)), max(1, int(hw.buildings.get("orbital_shipyard", 0)))))
            self.boss = {"stage": "building", "ready": self.t + cycle}
            return
        stage = self.boss["stage"]
        if stage == "ready":
            wb.tick_world_boss_schedule(conn=self.sb.conn, now=now_abs, include_auto_attack=False)
            self.sb.conn.commit()
            events = wb.list_active_events(conn=self.sb.conn, now=now_abs)
            if not events:
                self.mandate_reject("apex_boss_no_active_event")
                return
            ev = events[0]
            out = wb.execute_instant_attack(self.sb.user_id, int(ev["id"]), {BOSS_SHIP_KEY: BOSS_SHIPS}, planet_id=hw.planet_id, conn=self.sb.conn, now=now_abs)
            self.sb.conn.commit()
            if not out.get("ok"):
                self.mandate_reject(f"apex_boss_attack_{out.get('error')}")
                return
            self.boss.update(stage="waiting_end", event_id=int(ev["id"]), ends=float(ev["ends_at"]) - SIM_EPOCH)
            self.mandate_log.append({"action": "world_boss_hit", "day": round(self.t / DAY, 2)})
        elif stage == "waiting_end" and self.t + EPS >= float(self.boss["ends"]):
            wb.tick_world_boss_schedule(conn=self.sb.conn, now=now_abs, include_auto_attack=False)
            res = wb.claim_world_boss_rewards(self.sb.user_id, int(self.boss["event_id"]), conn=self.sb.conn, now=now_abs)
            self.sb.conn.commit()
            if res.get("ok"):
                self.boss["stage"] = "claimed"
                self.mandate_log.append({"action": "world_boss_claim", "day": round(self.t / DAY, 2), "tiers": list(res.get("tiers") or [])})
            else:
                self.mandate_reject(f"apex_boss_claim_{res.get('error')}")

    def finish_apex_ascension(self) -> None:
        from game.planet_evolution.ascension import finish_ascension_jobs

        pid = self.hw().planet_id
        done = finish_ascension_jobs(self.sb.conn, pid, float(self.asc["db_finish"]) + 1.0)
        self.sb.conn.commit()
        self.asc = None
        self._ctx = None
        self.xp_by_source["ascension"] = self.xp_by_source.get("ascension", 0) + (500 if done else 0)
        self.mandate_log.append({"action": "ascension_finished", "day": round(self.t / DAY, 2), "completed": bool(done)})

    # -- colonisation pipeline ------------------------------------------------
    def colony_package_cost(self) -> Tuple[int, int]:
        eff: Dict[str, int] = {}
        total_m = total_c = 0
        for spec in ESTABLISHMENT_MILESTONE_DEFS:
            if spec.get("placeholder") or not spec.get("required", True):
                continue
            target = max(1, int(spec.get("min_level") or 1))
            key = str(spec["building"])
            needs = [(key, target)]
            req = BUILDING_REQUIREMENTS.get(key, {}).get("buildings") or {}
            needs = [(b, int(l)) for b, l in req.items()] + needs
            for b, lvl in needs:
                for level in range(int(eff.get(b, 0)), lvl):
                    m, c = _upgrade_cost(b, level)
                    total_m += int(m)
                    total_c += int(c)
                eff[b] = max(int(eff.get(b, 0)), lvl)
        return int(total_m * 1.25), int(total_c * 1.25)

    def colonization_step(self) -> None:
        if self.sc.topology != "S11":
            return
        # 1) launch a finished ark at the next online moment
        if self.ark and self.ark["stage"] == "built":
            self.ark.update(stage="flying", arrive=self.t + self.sc.transit_sec)
        # 2) retry stuck supply packages
        for w in self.worlds[1:]:
            if w.outpost and not w.package_sent:
                self.send_package(w)
        if self.ark or len(self.worlds) >= self.target_worlds:
            self.colony_state = "ark_building_or_flying" if self.ark else "target_reached"
            return
        if self.policy.continuous and self.t + EPS < self._gate_next:
            return  # an always-online player re-checks the expansion gates hourly
        self._gate_next = self.t + 3600.0
        hw = self.hw()
        ok_cap, cap_reason = self.sb.cap_check()
        if not ok_cap:
            self.block(cap_reason)
            self.colony_state = f"gate:{cap_reason or 'cap'}"
            return
        if self._next_colony_binding is None:
            self._next_colony_binding = self.sb.next_binding()
        ok_gate, gate_reason, _meta = self.sb.expansion_gate(self._next_colony_binding.get("world_type"))
        if not ok_gate:
            self.block(gate_reason)
            self.colony_state = f"gate:{gate_reason}"
            return
        ship = get_ship("seed_ark") or {}
        req = ship.get("requirements") or {}
        missing = any(int(hw.buildings.get(b, 0)) < int(l) for b, l in (req.get("buildings") or {}).items()) or any(
            int(self.research.get(t, 0)) < int(l) for t, l in (req.get("research") or {}).items()
        )
        if missing:
            self.block("seed_ark_prerequisites")
            self.colony_state = "seed_ark_prerequisites"
            return
        cost = ship.get("build_cost") or {}
        cm, cc, cf = int(cost.get("metal", 0)), int(cost.get("crystal", 0)), int(cost.get("fuel_cells", 0))
        s = self.stats(hw)
        if cf > s["cap_f"] or cm > s["cap_m"] or cc > s["cap_c"]:
            self.block("storage_cap_below_cost", "seed ark vs depot capacity")
            self.colony_state = "seed_ark_storage_cap_below_cost"
            return
        if hw.metal + EPS < cm or hw.crystal + EPS < cc or hw.fuel + EPS < cf:
            self.block("seed_ark_unaffordable")
            waits = {
                "metal": max(0.0, cm - hw.metal) / s["m_ps"] if s["m_ps"] > 0 else math.inf,
                "crystal": max(0.0, cc - hw.crystal) / s["c_ps"] if s["c_ps"] > 0 else math.inf,
                "fuel": max(0.0, cf - hw.fuel) / s["f_ps"] if s["f_ps"] > 0 else (math.inf if cf > hw.fuel else 0.0),
            }
            self.colony_state = "seed_ark_unaffordable:" + max(waits, key=lambda k: waits[k])
            return
        self.colony_state = "ark_building_or_flying"
        hw.metal -= cm
        hw.crystal -= cc
        hw.fuel -= cf
        self.spend["colony_expansion"] += cm
        self.spend_c["colony_expansion"] += cc
        self.spend_f += cf
        levels = self._world_levels()
        self.gate_audit.append(
            {
                "day": round(self.t / DAY, 3),
                "expansion_index": len(self.worlds),
                "hw_planet_level": levels[0],
                "colony_levels": levels[1:],
                "worlds_before": len(self.worlds),
            }
        )
        yard = int(hw.buildings.get("orbital_shipyard", 0))
        cycle = float(production_level_cycle_seconds(int(ship.get("build_seconds", 260)), max(1, yard)))
        self.ark = {"stage": "building", "ready": self.t + cycle}
        self.arks_built += 1

    def send_package(self, w: World) -> None:
        hw = self.hw()
        cm, cc = self.colony_package_cost()
        if hw.metal + EPS < cm or hw.crystal + EPS < cc:
            if w.package_wait_since is None:
                w.package_wait_since = self.t
            self.block("colony_supply_waiting")
            return
        hw.metal -= cm
        hw.crystal -= cc
        self.spend["colony_expansion"] += cm
        self.spend_c["colony_expansion"] += cc
        w.package_sent = True
        if w.package_wait_since is not None:
            w.supply_wait_sec = self.t - w.package_wait_since
        self.convoys.append({"arrive": self.t + self.sc.transit_sec, "world": w.idx, "m": cm, "c": cc})

    def found_colony_now(self) -> None:
        idx = len(self.worlds)
        binding = self._next_colony_binding or self.sb.next_binding()
        ok, reason, pid = self.sb.found_colony(f"Colony {idx}", binding)
        if not ok:
            self.block(reason or "colony_limit_reached")
            self.ark = {"stage": "built"}  # ship returns, retry at next window
            return
        self._next_colony_binding = None
        self.ark = None
        climate = COLONY_CLIMATE_CYCLE[(idx - 1) % len(COLONY_CLIMATE_CYCLE)]
        w = World(
            idx=idx,
            planet_id=pid,
            climate=climate,
            slot=CLIMATE_SLOT[climate],
            home=False,
            founded_at=self.t,
            outpost=True,
            metal=500.0,
            crystal=250.0,
            fuel=0.0,
        )
        self.worlds.append(w)
        self._ctx = None
        got = self.sb.grant_xp("colonize", pid, self.t, f"colonize:fleet:{idx}")
        self.xp_by_source["colonize"] = self.xp_by_source.get("colonize", 0) + got
        self.colony_log.append({"event": "founded", "world": idx, "day": round(self.t / DAY, 2), "climate": climate, "world_type": binding.get("world_type")})
        self.send_package(w)

    # -- time stepping --------------------------------------------------------
    def next_window_after(self, t: float) -> float:
        if self.policy.continuous:
            return math.inf
        day = math.floor(t / DAY)
        for d in (day, day + 1):
            for h in self.policy.windows_hours:
                cand = d * DAY + h * 3600.0
                if cand > t + EPS:
                    return cand
        return math.inf

    def next_event_time(self, snaps: List[float], snap_i: int, next_window: float) -> float:
        cands = [self.horizon]
        if snap_i < len(snaps):
            cands.append(snaps[snap_i])
        for w in self.worlds:
            if w.queue and w.queue[0].finish is not None:
                cands.append(w.queue[0].finish)
        if self.rqueue and self.rqueue[0].finish is not None:
            cands.append(self.rqueue[0].finish)
        if self.ark:
            if self.ark.get("stage") == "building":
                cands.append(float(self.ark["ready"]))
            elif self.ark.get("stage") == "flying":
                cands.append(float(self.ark["arrive"]))
        for cv in self.convoys:
            cands.append(float(cv["arrive"]))
        if self.ship_build:
            cands.append(float(self.ship_build["ready"]))
        for m in self.missions:
            cands.append(float(m["arrive"]))
        if self.lever == "auto_start":
            for w in self.worlds:
                if w.reserved is not None:
                    wait = self.afford_wait(w, w.reserved[2], w.reserved[3])
                    if math.isfinite(wait):
                        cands.append(self.t + wait + 1.0)
            if self.r_reserved is not None:
                wait = self.afford_wait(self.worlds[self.r_reserved[4]], self.r_reserved[2], self.r_reserved[3])
                if math.isfinite(wait):
                    cands.append(self.t + wait + 1.0)
        if self.asc:
            cands.append(float(self.asc["finish_sim"]))
        if self.boss:
            if self.boss.get("stage") == "building":
                cands.append(float(self.boss["ready"]))
            elif self.boss.get("stage") == "waiting_end":
                cands.append(float(self.boss["ends"]))
        cands.append(next_window)
        if self.wake is not None:
            cands.append(self.wake)
        return max(self.t, min(cands))

    @staticmethod
    def _add(ledger: Dict[str, float], key: str, sec: float) -> None:
        if sec > 0:
            ledger[key] = ledger.get(key, 0.0) + sec

    def _wait_split(self, ledger: Dict[str, float], w: World, cm: float, cc: float, cost_part: float, storage_target: bool) -> None:
        """Split a resource-wait interval into energy drag and the binding resource (pure observation, no state change)."""
        s = self.stats(w)
        ratio = s["ratio"]
        energy_part = cost_part * (1.0 - ratio) if 0.0 < ratio < 1.0 else 0.0
        pure = cost_part - energy_part
        self._add(ledger, "wait_energy_drag", energy_part)
        if storage_target:
            self._add(ledger, "wait_storage_build", pure)
            return
        need_m = max(0.0, cm - w.metal)
        need_c = max(0.0, cc - w.crystal)
        wm = need_m / s["m_ps"] if s["m_ps"] > 0 else (math.inf if need_m > 0 else 0.0)
        wc = need_c / s["c_ps"] if s["c_ps"] > 0 else (math.inf if need_c > 0 else 0.0)
        self._add(ledger, "wait_metal" if wm >= wc else "wait_crystal", pure)

    def classify_idle(self, w: World, dt: float) -> None:
        if w.queue:
            w.build_busy_sec += dt
            self._add(w.causes, "busy", dt)
            return
        pick = self.choose_build(w)
        if pick is None:
            w.idle_nothing_sec += dt
            if self.research_needs:
                self._add(w.causes, "research_prerequisite", dt)
            elif self.blockers.get("storage_cap_below_cost", {}).get("last_day") == int(self.t // DAY):
                self._add(w.causes, "storage_cap_below_cost", dt)
            else:
                self._add(w.causes, "no_goal", dt)
            return
        wait = self.afford_wait(w, pick[2], pick[3])
        cost_part = min(dt, wait if math.isfinite(wait) else dt)
        w.idle_cost_sec += cost_part
        w.idle_window_sec += dt - cost_part
        self._wait_split(w.causes, w, pick[2], pick[3], cost_part, pick[0].endswith("_storage"))
        self._add(w.causes, "player_not_acting", dt - cost_part)

    def advance(self, dt: float) -> None:
        if dt <= 0:
            return
        hw = self.hw()
        for w in self.worlds:
            s = self.stats(w)
            self.classify_idle(w, dt)
            if s["ratio"] < ENERGY_LOW_RATIO:
                w.energy_low_sec += dt
            if 0.0 < s["ratio"] < 1.0:
                w.lost_energy_m += s["m_ps"] * (1.0 / s["ratio"] - 1.0) * dt
                w.lost_energy_c += s["c_ps"] * (1.0 / s["ratio"] - 1.0) * dt
                w.lost_energy_f += s["f_ps"] * (1.0 / s["ratio"] - 1.0) * dt
            full = 0.0
            for attr, ps, cap, prod, waste in (
                ("metal", s["m_ps"], s["cap_m"], "produced_m", "wasted_m"),
                ("crystal", s["c_ps"], s["cap_c"], "produced_c", "wasted_c"),
                ("fuel", s["f_ps"], s["cap_f"], "produced_f", "wasted_f"),
            ):
                cur = getattr(w, attr)
                gain = ps * dt
                if gain <= 0:
                    continue
                room = max(0.0, cap - cur)
                added = min(gain, room)
                setattr(w, attr, cur + added)
                setattr(w, prod, getattr(w, prod) + added)
                setattr(w, waste, getattr(w, waste) + (gain - added))
                if gain > room and attr != "fuel":
                    full = max(full, dt - (room / ps if ps > 0 else dt))
            w.storage_full_sec += min(dt, full)
        # research queue occupancy
        if self.rqueue:
            self.r_busy_sec += dt
            self._add(self.r_causes, "busy", dt)
        else:
            pick = self.choose_research()
            if pick is None:
                self.r_idle_nothing_sec += dt
                self._add(self.r_causes, "no_goal", dt)
            else:
                payer = self.worlds[pick[4]]
                wait = self.afford_wait(payer, pick[2], pick[3])
                part = min(dt, wait if math.isfinite(wait) else dt)
                self.r_idle_cost_sec += part
                self.r_idle_window_sec += dt - part
                self._wait_split(self.r_causes, payer, pick[2], pick[3], part, False)
                self._add(self.r_causes, "player_not_acting", dt - part)
        if self.sc.topology == "S11":
            self._add(self.colony_state_sec, self.colony_state, dt)
        self.t += dt

    def process_events(self) -> None:
        progressed = True
        self.start_reserved()
        while progressed:
            progressed = False
            for w in self.worlds:
                if w.queue and w.queue[0].finish is not None and w.queue[0].finish <= self.t + EPS:
                    self.finish_build(w, w.queue[0])
                    progressed = True
            if self.rqueue and self.rqueue[0].finish is not None and self.rqueue[0].finish <= self.t + EPS:
                self.finish_research(self.rqueue[0])
                progressed = True
        if self.ark and self.ark.get("stage") == "building" and float(self.ark["ready"]) <= self.t + EPS:
            self.ark = {"stage": "built"}
        if self.ark and self.ark.get("stage") == "flying" and float(self.ark["arrive"]) <= self.t + EPS:
            self.found_colony_now()
        if self.ship_build and float(self.ship_build["ready"]) <= self.t + EPS:
            self.ships_home += int(self.ship_build["count"])
            self.ship_build = None
        for m in [m for m in self.missions if m["arrive"] <= self.t + EPS]:
            self.missions.remove(m)
            self.finish_mission(m)
        if self.asc and float(self.asc["finish_sim"]) <= self.t + EPS:
            self.finish_apex_ascension()
        if self.boss and self.boss.get("stage") == "building" and float(self.boss["ready"]) <= self.t + EPS:
            from game.fleet import set_planet_ships

            set_planet_ships(self.hw().planet_id, self.sb.user_id, {BOSS_SHIP_KEY: BOSS_SHIPS}, conn=self.sb.conn)
            self.sb.conn.commit()
            self.boss["stage"] = "ready"
        due = [cv for cv in self.convoys if cv["arrive"] <= self.t + EPS]
        for cv in due:
            self.convoys.remove(cv)
            w = self.worlds[cv["world"]]
            w.metal += cv["m"]
            w.crystal += cv["c"]
        self.start_reserved()

    def act(self) -> None:
        for w in self.worlds[1:]:
            if not w.touched:
                w.touched = True
                self.sb.touch_planet(w.planet_id)  # the player opens the new colony
                self.refresh_establishment(w)
        self.apply_expeditions()
        for w in self.worlds:
            self.maybe_specialize(w)
        for w in self.worlds:
            self.maybe_scan(w)
        self.fill_research_queue()
        hw = self.hw()
        for w in self.worlds:
            self.maybe_ascend(w)
        for w in self.worlds:
            self.fill_build_queue(w)
        self.fill_research_queue()
        self.reserve_next()
        self.mandate_step()
        self.colonization_step()
        self.update_wake()
        _ = hw

    def update_wake(self) -> None:
        self.wake = None
        if not self.policy.continuous:
            return
        best = math.inf
        for w in self.worlds:
            if len(w.queue) < self.build_limit:
                pick = self.choose_build(w)
                if pick is not None:
                    wait = self.afford_wait(w, pick[2], pick[3])
                    if math.isfinite(wait) and wait > 0:
                        best = min(best, self.t + wait + 1.0)
                    elif self.trader and math.isfinite(wait) and (w.metal + EPS < pick[2] or w.crystal + EPS < pick[3]):
                        best = min(best, self.t + 3600.0)  # fungible funds exist but no legal trade completed it: look again within the hour
            if w.next_scan_t > self.t:
                best = min(best, w.next_scan_t + 1.0)
        if self._trade_retry is not None and self._trade_retry > self.t:
            best = min(best, self._trade_retry + 1.0)  # the Trader's daily limit was hit: try again after the reset
        if self.mandate_phase():
            best = min(best, self.t + 3600.0)  # always-online player re-checks the mandate checklist hourly
        if len(self.rqueue) < min(self.research_limit, self.policy.queue_fill):
            pick = self.choose_research()
            if pick is not None:
                wait = self.afford_wait(self.worlds[pick[4]], pick[2], pick[3])
                if math.isfinite(wait) and wait > 0:
                    best = min(best, self.t + wait + 1.0)
        if self.sc.topology == "S11" and not self.ark and len(self.worlds) < self.target_worlds:
            hw = self.hw()
            ship = get_ship("seed_ark") or {}
            cost = ship.get("build_cost") or {}
            wait_m = max(0.0, (cost.get("metal", 0) - hw.metal)) / max(1e-9, self.stats(hw)["m_ps"])
            wait_c = max(0.0, (cost.get("crystal", 0) - hw.crystal)) / max(1e-9, self.stats(hw)["c_ps"])
            wait_f = max(0.0, (cost.get("fuel_cells", 0) - hw.fuel)) / max(1e-9, self.stats(hw)["f_ps"]) if self.stats(hw)["f_ps"] > 0 else math.inf
            wait = max(wait_m, wait_c, wait_f)
            if math.isfinite(wait) and wait > 0:
                best = min(best, self.t + wait + 1.0)
            best = min(best, self.t + 3600.0)  # re-evaluate gates hourly while expanding
        if math.isfinite(best):
            self.wake = max(best, self.t + 1.0)

    # -- metrics --------------------------------------------------------------
    def check_invariants(self) -> None:
        for w in self.worlds:
            if min(w.metal, w.crystal, w.fuel) < -EPS:
                self.invariant_violations.append(f"day {int(self.t // DAY)}: negative stock world {w.idx}")
            if len(w.queue) > self.build_limit:
                self.invariant_violations.append(f"day {int(self.t // DAY)}: queue overflow world {w.idx}")
            p = self.sb.planet(w.planet_id)
            if p["level"] > MAX_PLANET_LEVEL:
                self.invariant_violations.append(f"world {w.idx}: planet level above cap")
        if len(self.worlds) > int(self.cap_info.get("admin_ceiling") or TARGET_WORLDS):
            self.invariant_violations.append("worlds exceed admin ceiling")
        if self.sb.planet_count() != len(self.worlds):
            self.invariant_violations.append("sandbox planet count differs from simulated worlds")
        self.check_asc_invariants()

    def snapshot(self, label: str, full: bool) -> Dict[str, Any]:
        m_h, c_h, f_h = self.empire_hourly()
        metal_lv = [int(w.buildings.get("metal_mine", 0)) for w in self.worlds]
        crystal_lv = [int(w.buildings.get("crystal_mine", 0)) for w in self.worlds]
        planets = [self.sb.planet(w.planet_id) for w in self.worlds]
        established = [w for w in self.worlds if not w.outpost]
        row: Dict[str, Any] = {
            "label": label,
            "day": round(self.t / DAY, 3),
            "worlds": len(self.worlds),
            "established": len(established),
            "mine_depth_max": max(metal_lv),
            "mine_depth_median": float(median(metal_lv)),
            "mine_depth_min": min(metal_lv),
            "empire_metal_h": int(m_h),
            "empire_crystal_h": int(c_h),
            "empire_fuel_h": int(f_h),
            "hw_planet_level": planets[0]["level"],
            "planet_levels": [p["level"] for p in planets],
            "reveal_tiers": [p["tier"] for p in planets],
            "research_sum": sum(self.research.values()),
            "scans": sum(w.scans for w in self.worlds),
        }
        if self.sc.asc != "legacy":
            peak = max([self.asc_peak.get((w.idx, k), 0) for w in self.worlds for k in ASC_MINES] + metal_lv + crystal_lv)
            row["peak_depth_max"] = max(peak, max((int(r["best_depth"]) for r in self.asc_runs), default=0))
            row["ascensions_total"] = len(self.asc_runs)
        if full:
            span = max(self.t, 1.0)
            if self.sc.asc != "legacy":
                row["ascension"] = self.asc_summary()
            row.update(
                {
                    "crystal_depth_max": max(crystal_lv),
                    "mine_depth_by_world": metal_lv,
                    "per_world": [
                        {
                            "idx": w.idx,
                            "climate": w.climate,
                            "slot": w.slot,
                            "outpost": w.outpost,
                            "founded_day": round(w.founded_at / DAY, 2),
                            "established_day": None if w.established_at is None else round(w.established_at / DAY, 2),
                            "unrestricted_day": None if w.unrestricted_at is None else round(w.unrestricted_at / DAY, 2),
                            "dna_before_establishment_day": None if w.dna_early_at is None else round(w.dna_early_at / DAY, 2),
                            "metal_h": int(self.stats(w)["m_ps"] * 3600),
                            "crystal_h": int(self.stats(w)["c_ps"] * 3600),
                            "fuel_h": int(self.stats(w)["f_ps"] * 3600),
                            "energy_supply": self.stats(w)["supply"],
                            "energy_demand": self.stats(w)["demand"],
                            "energy_ratio": round(self.stats(w)["ratio"], 4),
                            "energy_low_days": round(w.energy_low_sec / DAY, 2),
                            "storage_full_days": round(w.storage_full_sec / DAY, 2),
                            "wasted_metal": int(w.wasted_m),
                            "wasted_crystal": int(w.wasted_c),
                            "wasted_fuel": int(w.wasted_f),
                            "produced_metal": int(w.produced_m),
                            "produced_crystal": int(w.produced_c),
                            "produced_fuel": int(w.produced_f),
                            "lost_to_energy_metal": int(w.lost_energy_m),
                            "lost_to_energy_crystal": int(w.lost_energy_c),
                            "lost_to_energy_fuel": int(w.lost_energy_f),
                            "age_sec": round(self.t - w.founded_at, 3),
                            "time_ledger_sec": {k: round(v, 3) for k, v in sorted(w.causes.items())},
                            "queue_busy_pct": round(100 * w.build_busy_sec / span, 1),
                            "idle_waiting_cost_pct": round(100 * w.idle_cost_sec / span, 1),
                            "idle_waiting_player_pct": round(100 * w.idle_window_sec / span, 1),
                            "idle_nothing_to_build_pct": round(100 * w.idle_nothing_sec / span, 1),
                            "planet_level": planets[i]["level"],
                            "planet_xp": planets[i]["xp"],
                            "reveal_tier": planets[i]["tier"],
                            "scans": w.scans,
                            "scan_spend_metal": int(w.scan_spend_m),
                            "scan_spend_crystal": int(w.scan_spend_c),
                            "traits_known": self.sb.trait_counts(w.planet_id, planets[i]["tier"])[0],
                            "traits_hidden": self.sb.trait_counts(w.planet_id, planets[i]["tier"])[1],
                            "supply_wait_days": round(w.supply_wait_sec / DAY, 3),
                            "buildings": {k: int(v) for k, v in sorted(w.buildings.items()) if v},
                        }
                        for i, w in enumerate(self.worlds)
                    ],
                    "research": dict(sorted(self.research.items())),
                    "research_time_ledger_sec": {k: round(v, 3) for k, v in sorted(self.r_causes.items())},
                    "colony_pipeline_sec": {k: round(v, 3) for k, v in sorted(self.colony_state_sec.items())},
                    "elapsed_sec": round(self.t, 3),
                    "research_queue_busy_pct": round(100 * self.r_busy_sec / span, 1),
                    "research_idle_waiting_cost_pct": round(100 * self.r_idle_cost_sec / span, 1),
                    "research_idle_waiting_player_pct": round(100 * self.r_idle_window_sec / span, 1),
                    "spend_metal": {k: int(v) for k, v in self.spend.items()},
                    "spend_crystal": {k: int(v) for k, v in self.spend_c.items()},
                    "spend_fuel_cells": int(self.spend_f),
                    "ascension_ap_if_reset_top_mine": int(nodebuster_mod.ascension_points_for_depth(max(metal_lv))),
                    "ascension_note": "potential only - no reset simulated",
                    "xp_by_source": dict(sorted(self.xp_by_source.items())),
                    "paid_accelerators": 0,
                    "free_accelerators_applied_sec": 0,
                }
            )
        return row

    # -- main loop ------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        cp_days = tuple(CHECKPOINT_DAYS) + (ASC_EXTRA_CHECKPOINT_DAYS if self.sc.asc != "legacy" else ())
        snaps = sorted({float(d) * DAY for d in range(0, int(math.ceil(self.sc.days)) + 1) if d * DAY <= self.horizon} | {d * DAY for d in cp_days if d * DAY <= self.horizon} | {self.horizon})
        cp_times = {d * DAY: ("day%g" % d) for d in cp_days if d * DAY <= self.horizon}
        snap_i = 0
        self.process_events()
        self.act()
        while True:
            while snap_i < len(snaps) and snaps[snap_i] <= self.t + EPS:
                ts = snaps[snap_i]
                snap_i += 1
                self.check_invariants()
                if abs(ts / DAY - round(ts / DAY)) < 1e-9:
                    self.daily.append(self.snapshot(f"d{int(round(ts / DAY))}", full=False))
                if ts in cp_times:
                    self.checkpoints[cp_times[ts]] = self.snapshot(cp_times[ts], full=True)
            if self.t >= self.horizon - EPS:
                break
            nw = self.next_window_after(self.t)
            t_next = self.next_event_time(snaps, snap_i, nw)
            if t_next <= self.t + EPS:
                t_next = self.t + 1.0
            t_next = min(t_next, self.horizon)
            self.advance(t_next - self.t)
            self.process_events()
            acted = self.policy.continuous or nw <= self.t + EPS
            if acted:
                self.act()
            elif self.wake is not None and self.t + EPS >= self.wake:
                self.act()
        final = self.snapshot("final", full=True)
        return self.package(final)

    def package(self, final: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": self.sc.sid,
            "topology": self.sc.topology,
            "policy": self.sc.policy,
            "home_climate": self.sc.climate,
            "trait_scenario": self.sc.trait,
            "trait_label": TRAIT_SCENARIOS[self.sc.trait]["label"],
            "lever": self.sc.lever,
            "lever_label": LEVERS[self.sc.lever],
            "strategy": self.sc.strategy,
            "policy_version": STRATEGY_VERSIONS[self.sc.strategy],
            "asc": self.sc.asc,
            "asc_skills": self.sc.asc_skills,
            "asc_model_version": ASC_MODEL_VERSION,
            "ascension_runs": [dict(r) for r in self.asc_runs],
            "ascension_skill_log": [dict(r) for r in self.asc_skill_log],
            "ascension_rejections": dict(sorted(self.asc_rejections.items())),
            "trader": {"enabled": self.trader, **{k: int(v) for k, v in self.trades.items()}},
            "days": self.sc.days,
            "expeditions_per_day": self.sc.expeditions_per_day,
            "transit_sec": self.sc.transit_sec,
            "status": self.status(),
            "checkpoints": self.checkpoints,
            "final": final,
            "daily": self.daily,
            "colony_log": self.colony_log,
            "gate_audit": self.gate_audit,
            "mandates": {
                "earned": [dict(e) for e in self.mandate_log if "mandate" in e],
                "actions": [dict(e) for e in self.mandate_log if "action" in e],
                "survey_missions_done": self.missions_done,
                "rejections": dict(sorted(self.mandate_rejections.items())),
                "specialization": self.spec_picked,
                "apex_route": "world_boss_claim" if self.boss_route else ("machine_ascension" if self.spec_picked else None),
            },
            "findings": self.findings,
            "blockers": {
                k: {"first_day": v["first_day"], "last_day": v["last_day"], "days_observed": len(v["days"]), "recovery": v["recovery"], "detail": v["detail"]}
                for k, v in sorted(self.blockers.items(), key=lambda kv: kv[1]["first_day"])
            },
            "scan_rejections": dict(sorted(self.scan_rejections.items())),
            "invariants": {"ok": not self.invariant_violations, "violations": self.invariant_violations[:20]},
            "resonance_world": self.resonance_world_idx,
            "arks_built": self.arks_built,
        }

    def status(self) -> str:
        if self.sc.topology == "S1":
            return "complete"
        if len(self.worlds) >= TARGET_WORLDS:
            return "complete"
        cap = self.cap_info.get("admin_ceiling")
        if cap is not None and int(cap) < TARGET_WORLDS:
            return "scenario_unavailable"
        expansion = {k: v for k, v in self.blockers.items() if k in EXPANSION_BLOCKERS}
        pool = expansion or self.blockers
        last = max(pool.items(), key=lambda kv: kv[1]["last_day"])[0] if pool else "unknown"
        return f"partial_blocked:{last}"


# ---------------------------------------------------------------------------
# Upper-bound control, meta, scenarios
# ---------------------------------------------------------------------------


def upper_bound_control() -> Dict[str, Any]:
    """Re-use the existing record-mine audit as the optimistic control (not a player route)."""
    try:
        from scripts.audit_long_horizon_economy import build_audit

        audit = build_audit()
        rows = {a["key"]: a for a in audit["anchors"]}
        return {
            "available": True,
            "source": "scripts/audit_long_horizon_economy.py",
            "note": "optimistic record-mine upper bounds; NOT a player route",
            "free_skip_economy": {
                k: audit["free_skip_economy"].get(k)
                for k in (
                    "login_perfect_365_tk_equivalent_sec",
                    "battle_pass_free_tk_equivalent_sec",
                    "deterministic_free_year_tk_equivalent_sec",
                )
            },
            "levels": {k: {"worlds": rows[k]["worlds"], "mine_level": rows[k]["level"], "metal_per_hour": rows[k]["metal_per_hour"]} for k in ("1w_6m", "1w_12m", "11w_6m", "11w_12m") if k in rows},
        }
    except Exception as exc:  # pragma: no cover - audit stack is optional here
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def apex_dna_fairness(samples: int = 600) -> Dict[str, Any]:
    """Share of homeworld DNAs that can reach the ascension route of the apex mandate.

    Uses the canonical DNA generator and specialisation eligibility rule at planet level 22 with all
    traits revealed (tier 2).  `without_rare` ignores rare/epic traits to show whether common DNA suffices.
    """
    import random

    from game.planet_evolution import definitions as defs
    from game.planet_evolution.dna import all_trait_keys, generate_planet_dna
    from game.planet_evolution.specialization import _ineligible_reason

    rng = random.Random(SANDBOX_RNG_SEED)
    eligible = eligible_common = 0
    with Sandbox() as sb:
        defs.reload_definitions(sb.conn)
        specs = defs.get_specializations()
        traits = defs.get_traits()
        rare = {k for k, t in traits.items() if str(t.get("rarity")) in ("rare", "epic")}
        for _ in range(samples):
            dna = generate_planet_dna(galaxy=rng.randint(1, 5), system=rng.randint(1, 499), position=rng.randint(1, 15), is_homeworld=True)
            known = set(all_trait_keys(dna, 2))
            aff = dna.get("affinity_scores") or {}

            def ok(trait_set: set) -> bool:
                return any(_ineligible_reason(k, v, planet_level=22, traits=trait_set, affinities=aff, current_spec=None) is None for k, v in specs.items())

            eligible += 1 if ok(known) else 0
            eligible_common += 1 if ok(known - rare) else 0
    return {
        "samples": samples,
        "share_with_eligible_specialization": round(eligible / samples, 4),
        "share_without_rare_or_epic_traits": round(eligible_common / samples, 4),
        "route": "homeworld specialisation tier 3 -> machine_ascension (no trait gate of its own)",
        "alternative": "World Boss claim (no DNA dependence): 3 falcon_interceptor hulls + one hit + claim",
    }


def code_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def meta(args_days: float) -> Dict[str, Any]:
    settings = {
        "speeds": _settings(),
        "build_queue_limit": int(_resolve_build_queue_limit(DEFAULT_GAME_SETTINGS)),
        "research_queue_limit": int(_resolve_research_queue_limit(DEFAULT_GAME_SETTINGS)),
        "scan_cooldown_sec": dna_analysis.SCAN_COOLDOWN_SECONDS,
        "scan_reward_xp": dna_analysis.SCAN_REWARD_XP,
        "scan_levels": [dna_analysis.SCAN_MIN_LEVEL, dna_analysis.SCAN_MAX_LEVEL],
        "colony_maturity_level": COLONY_MATURITY_REQUIRED_LEVEL,
        "expansion_slot_gates": list(EXPANSION_SLOT_GATES),
        "specialization_unlock_level": SPECIALIZATION_UNLOCK_LEVEL,
        "ascension_unlock_level": ASCENSION_UNLOCK_LEVEL,
        "xp_thresholds": {str(l): xp_threshold_for_level(l) for l in (3, 5, 8, 10, 15, 20, 25, 30)},
        "sim_assumptions": {"colony_transit_sec": COLONY_TRANSIT_SEC, "target_worlds": TARGET_WORLDS},
    }
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {
        "sim_version": SIM_VERSION,
        "policy_version": POLICY_VERSION,
        "code_sha": code_sha(),
        "settings_digest": digest,
        "settings": settings,
        "rounding": "Day 182.5 is sampled at exactly t=15 768 000 s; integer-day rows sit on either side (day 182 and 183). Mine depth = metal mine level.",
        "determinism": "no RNG; fixed policy; sandbox DB seeded from migrations; homeworld placement pinned per scenario (rng_seed)",
        "buildings_known": sorted(ALL_BUILDINGS),
    }


def build_scenarios(days: float, quick: bool) -> List[Scenario]:
    out: List[Scenario] = []
    policies = ("casual", "active", "optimizer")
    for pol in policies:
        for climate in (("mid",) if quick else ("hot", "mid", "cold")):
            out.append(Scenario(f"S1-{pol}-{climate}", "S1", pol, climate, "none", days))
    for pol in policies:
        out.append(Scenario(f"S11-{pol}-mid", "S11", pol, "mid", "none", days))
    if not quick:
        out.append(Scenario("S11-active-mid-exp6", "S11", "active", "mid", "none", days, expeditions_per_day=6))
        for pol in policies:
            out.append(Scenario(f"S11L-{pol}-mid-dnaE", "S11", pol, "mid", "none", LONG_DAYS, rng_seed=ELIGIBLE_HOME_SEED))
        out.append(Scenario("S11L-active-mid-dnaE-exp6", "S11", "active", "mid", "none", LONG_DAYS, expeditions_per_day=6, rng_seed=ELIGIBLE_HOME_SEED))
        out.append(Scenario("S11L-active-mid-dnaN", "S11", "active", "mid", "none", LONG_DAYS))
        for trait in ("r5_one", "r10_one", "r12_one", "r12_all"):
            out.append(Scenario(f"S1-active-mid-{trait}", "S1", "active", "mid", trait, days))
            out.append(Scenario(f"S11-active-mid-{trait}", "S11", "active", "mid", trait, days))
    return out


@contextlib.contextmanager
def economy_curve(curve: str):
    """Match the endgame production curve of the record-mine control (UNI1) or use the process default."""
    with SIM_LOCK:
        if curve == "uni1":
            from scripts.sim_ascension_breakthroughs import uni1_endgame_curve

            with uni1_endgame_curve():
                yield
        else:
            yield


@contextlib.contextmanager
def lever_context(lever: str):
    """Sandbox-only patches for levers that act on canonical rules (restored on exit; never a game change)."""
    with SIM_LOCK:
        if lever in LEVER_GATE_LEVEL:
            import game.planet_evolution.expansion_protocol as ep

            old = ep.COLONY_MATURITY_REQUIRED_LEVEL
            ep.COLONY_MATURITY_REQUIRED_LEVEL = LEVER_GATE_LEVEL[lever]
            try:
                yield
            finally:
                ep.COLONY_MATURITY_REQUIRED_LEVEL = old
        else:
            yield


def universe_probe(curve: str, lever: str = "none", dwell: float = 0.0) -> Dict[str, Any]:
    """Self-check of the isolation (used by the stress tests): what a scenario of this universe sees inside its contexts and what the
    process looks like before and after.  ``dwell`` keeps the universe open for that many seconds so that concurrent callers would
    interleave if the lock did not serialise them."""
    from game.planet_evolution import expansion_protocol as ep

    before = universe_key()
    with economy_curve(curve), lever_context(lever):
        if dwell > 0:
            time.sleep(dwell)
        inside = {"key": universe_key(), "gate": int(ep.COLONY_MATURITY_REQUIRED_LEVEL), "price": tuple(_upgrade_cost("metal_mine", 250))}
        if dwell > 0:
            time.sleep(dwell)
        inside["key_after_dwell"] = universe_key()
    return {"before": before, "inside": inside, "after": universe_key()}


def run_scenario(sc: Scenario, curve: str = "uni1") -> Dict[str, Any]:
    started = time.time()
    with economy_curve(curve), lever_context(sc.lever), Sandbox(sc.rng_seed) as sb:
        result = Journey(sc, sb).run()
    result["wall_seconds"] = round(time.time() - started, 1)
    result["economy_curve"] = curve
    return result


def run_all(days: float, quick: bool, only: Optional[str], with_upper_bound: bool, curve: str = "uni1") -> Dict[str, Any]:
    scenarios = build_scenarios(days, quick)
    if only:
        scenarios = [s for s in scenarios if only in s.sid]
    results = [run_scenario(s, curve) for s in scenarios]
    info = meta(days)
    info["economy_curve"] = curve
    return {
        "meta": info,
        "apex_dna_fairness": apex_dna_fairness() if (with_upper_bound and not quick) else {"skipped": True},
        "upper_bound_control": upper_bound_control() if with_upper_bound else {"available": False, "error": "skipped"},
        "not_modelled": NOT_MODELLED,
        "scenarios": results,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _human(value: Any) -> str:
    n = float(value or 0)
    for threshold, suffix in ((1e18, "Qi"), (1e15, "Qa"), (1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(n) >= threshold:
            return f"{n / threshold:.2f}{suffix}"
    return f"{int(n):,}"


def _fmt_int(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except Exception:
        return str(n)


def _hours(sec: Any) -> str:
    try:
        return f"{int(sec) / 3600:.0f} h"
    except Exception:
        return "n/a"


def render_markdown(data: Dict[str, Any]) -> str:
    meta_ = data["meta"]
    ub = data.get("upper_bound_control", {})
    base_rows = [s for s in data["scenarios"] if s["trait_scenario"] == "none" and not s["expeditions_per_day"] and float(s["days"]) <= 365]
    long_rows = [s for s in data["scenarios"] if float(s["days"]) > 365]
    lines: List[str] = [
        "# GC - Trait R3 Player Journey Report",
        "",
        "> Generated by `python scripts/player_journey_sim.py` (measurement only - no gameplay change, no deployment).",
        f"> Economy curve: `{meta_.get('economy_curve', 'uni1')}` (uni1 = same endgame production curve as the upper-bound control).",
        f"> Code `{meta_['code_sha'][:12]}` · settings digest `{meta_['settings_digest']}` · policy `{meta_['policy_version']}` · sim `{meta_['sim_version']}`.",
        "",
        "## How to read this",
        "",
        "* **Simulated trajectories** start from a fresh account and run the canonical economy and progression owners (EffectResolver, costs, planet XP, DNA analysis, expansion gates, `colonize_planet`) in a throw-away sandbox DB.",
        "* **Upper bounds** are the existing record-mine control (`audit_long_horizon_economy.py`). They are not a player route.",
        "* Results depend on the decision policy (`" + meta_["policy_version"] + "`). A policy stall is not automatically a game softlock; blockers below name the canonical reason.",
        f"* {meta_['rounding']}",
        "",
        "### Play styles (scheduling assumptions, not behaviour guarantees)",
        "",
        "| Style | Action windows | Queue depth kept | DNA scan budget | Scans without colony need |",
        "|---|---|---:|---:|---|",
    ]
    for pol in POLICIES.values():
        windows = "every event" if pol.continuous else ", ".join(f"{h:02d}:00" for h in pol.windows_hours)
        lines.append(f"| {pol.key} | {windows} | {min(pol.queue_fill, 3)} | {int(pol.scan_frac * 100)}% of stock | {'yes' if pol.scan_in_s1 else 'no'} |")
    lines += ["", "## Upper bound vs simulated trajectories (metal-mine depth)", ""]
    ubl = ub.get("levels", {}) if ub.get("available") else {}
    lines += ["| Case | 182.5 d | 365 d |", "|---|---:|---:|"]
    if ubl:
        lines.append(f"| **Upper bound** 1 world (record mine) | L{ubl.get('1w_6m', {}).get('mine_level', '-')} | L{ubl.get('1w_12m', {}).get('mine_level', '-')} |")
        lines.append(f"| **Upper bound** 11 worlds pooled (control) | L{ubl.get('11w_6m', {}).get('mine_level', '-')} | L{ubl.get('11w_12m', {}).get('mine_level', '-')} |")
    else:
        lines.append(f"| Upper bound control | n/a ({ub.get('error', 'skipped')}) | n/a |")
    for s in base_rows:
        a, b = s["checkpoints"].get("day182.5"), s["checkpoints"].get("day365")
        if not a or not b:
            continue
        lines.append(f"| {s['id']} (best / median world) | L{a['mine_depth_max']} / L{int(a['mine_depth_median'])} | L{b['mine_depth_max']} / L{int(b['mine_depth_median'])} |")
    skip = ub.get("free_skip_economy") if ub.get("available") else None
    if skip:
        lines += ["", f"Deterministic free Timekeeper potential over 365 d (login + free pass): {_hours(skip.get('deterministic_free_year_tk_equivalent_sec'))}. It is reported only; **no skip is applied** in any simulated run (paid accelerators = 0)."]

    lines += ["", "## Checkpoints per scenario", ""]
    for s in base_rows:
        lines += [f"### {s['id']}  - status `{s['status']}`", "", "| Day | Worlds | HW PL | Best / median / worst mine | Empire M/C per h | Research Σ | Scans |", "|---:|---:|---:|---:|---:|---:|---:|"]
        for label in ("day7", "day30", "day90", "day182.5", "day365"):
            c = s["checkpoints"].get(label)
            if c:
                lines.append(
                    f"| {c['day']:g} | {c['worlds']} | {c['hw_planet_level']} | L{c['mine_depth_max']} / L{int(c['mine_depth_median'])} / L{c['mine_depth_min']} | "
                    f"{_fmt_int(c['empire_metal_h'])} / {_fmt_int(c['empire_crystal_h'])} | {c['research_sum']} | {c['scans']} |"
                )
        lines.append("")

    lines += ["## S11: legal expansion towards eleven worlds", ""]
    for s in base_rows:
        if s["topology"] != "S11":
            continue
        ev = s["colony_log"]
        founded = [e for e in ev if e["event"] == "founded"]
        lines.append(f"**{s['id']}** - {len(founded) + 1} of {TARGET_WORLDS} worlds after {s['days']:g} d, status `{s['status']}`.")
        lines.append("")
        lines += ["| Colony | Founded (day) | Unrestricted (day, via) | Establishment milestones (day) |", "|---:|---:|---|---|"]
        for f in founded:
            unres = next((e for e in ev if e["event"] == "unrestricted" and e["world"] == f["world"]), None)
            est = next((e for e in ev if e["event"] == "established" and e["world"] == f["world"]), None)
            unres_txt = ("%g (%s)" % (unres["day"], unres["via"])) if unres else "-"
            est_txt = ("%g" % est["day"]) if est else "not reached (not required by the canonical state)"
            lines.append(f"| #{f['world']} | {f['day']:g} | {unres_txt} | {est_txt} |")
        lines.append("")
    lines += ["", "## Imperial Mandates (real prerequisites, nothing granted)", "", "Survey = 2 canonical expedition ships + 12 missions, presence = three owned systems, directive = canonical vote, apex = homeworld specialisation tier 3 + `machine_ascension` (5M metal / 3M crystal, 7 d). Late slots 7-10 open one per mandate, in order.", "", "| Scenario | Survey | Presence | Directive | Apex | Mandate spend M | Rejections (count) |", "|---|---:|---:|---:|---:|---:|---|"]
    for s_ in base_rows + long_rows:
        if s_["topology"] != "S11":
            continue
        got = {e["mandate"]: e["day"] for e in s_.get("mandates", {}).get("earned", [])}
        rej = ", ".join(f"{k}={v}" for k, v in s_.get("mandates", {}).get("rejections", {}).items()) or "-"
        spent = (s_["final"].get("spend_metal") or {}).get("mandates", 0)
        lines.append(f"| {s_['id']} | {got.get('survey', '-')} | {got.get('presence', '-')} | {got.get('directive', '-')} | {got.get('apex', '-')} | {_human(spent)} | {rej} |")
    fair = data.get("apex_dna_fairness") or {}
    if fair and not fair.get("skipped"):
        lines += ["", f"**Apex route fairness:** in {fair['samples']} sampled homeworld DNAs only **{fair['share_with_eligible_specialization']:.0%}** have any specialisation they are eligible for (tier 2 reveal, planet level 22); ignoring rare/epic traits changes this to {fair['share_without_rare_or_epic_traits']:.0%}, i.e. the gate is the common-trait/affinity roll, not rarity. The remaining accounts use the World Boss claim route, which is DNA-independent and modelled as the fallback."]

    if long_rows:
        lines += ["", "## 11/11 attempt (730-day horizon, legal route only)", "", "Same policy and rules as above, run longer only to find out *when* a legal eleven-world empire becomes reachable. Colony n+1 can only be launched after every existing colony reached planet level 15.", "", "| Scenario | Worlds @365 | Worlds @730 | Day of 11th world | Last colony PL15 chain (days/colony) | Status |", "|---|---:|---:|---:|---:|---|"]
        for s_ in long_rows:
            founded = [e for e in s_["colony_log"] if e["event"] == "founded"]
            at365 = next((r for r in s_["daily"] if r["label"] == "d365"), None)
            eleventh = next((e["day"] for e in founded if e["world"] == TARGET_WORLDS - 1), None)
            cadence = (founded[-1]["day"] - founded[0]["day"]) / max(1, len(founded) - 1) if len(founded) > 1 else 0
            lines.append(f"| {s_['id']} | {at365['worlds'] if at365 else '-'} | {s_['final']['worlds']} | {('%g' % eleventh) if eleventh else 'not reached'} | {cadence:.0f} | `{s_['status']}` |")
        lines.append("")

    lines += ["### Dispersion across worlds (median and worst world vs best world)", "", "| Scenario | Day | Best | Median | Worst | Median/Best | Worst/Best |", "|---|---:|---:|---:|---:|---:|---:|"]
    for s in base_rows:
        if s["topology"] != "S11":
            continue
        for label in ("day182.5", "day365"):
            c = s["checkpoints"].get(label)
            if c and c["mine_depth_max"]:
                lines.append(f"| {s['id']} | {c['day']:g} | L{c['mine_depth_max']} | L{int(c['mine_depth_median'])} | L{c['mine_depth_min']} | {c['mine_depth_median'] / c['mine_depth_max']:.0%} | {c['mine_depth_min'] / c['mine_depth_max']:.0%} |")

    lines += ["", "## DNA / XP / spend at 365 d", "", "| Scenario | HW PL | Scans | Scan spend M | XP: scans | XP: buildings | XP: research | XP: colonize | Spend M: mines | research | storage | scans | expansion |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in base_rows:
        c = s["checkpoints"].get("day365")
        if not c:
            continue
        x, sp = c["xp_by_source"], c["spend_metal"]
        scan_m = sum(w["scan_spend_metal"] for w in c["per_world"])
        lines.append(
            f"| {s['id']} | {c['hw_planet_level']} | {c['scans']} | {_human(scan_m)} | {_fmt_int(x.get('dna_scan', 0))} | {_fmt_int(x.get('building_finish', 0))} | "
            f"{_fmt_int(x.get('account_research_finish', 0))} | {_fmt_int(x.get('colonize', 0))} | {_human(sp.get('mines', 0))} | {_human(sp.get('research', 0))} | "
            f"{_human(sp.get('storage', 0))} | {_human(sp.get('dna_scans', 0))} | {_human(sp.get('colony_expansion', 0))} |"
        )

    lines += ["", "## Findings from composing the canonical owners", ""]
    seen: Dict[str, Dict[str, Any]] = {}
    for s in data["scenarios"]:
        for key, val in s.get("findings", {}).items():
            seen.setdefault(key, {"mechanism": val.get("mechanism", ""), "first_day": val.get("first_day"), "scenarios": []})["scenarios"].append(s["id"])
    if seen:
        for key, val in seen.items():
            lines.append(f"* **`{key}`** (first seen day {val['first_day']}, {len(val['scenarios'])} scenarios): {val['mechanism']}. Observed through canonical functions in the sandbox; confirm against a live planet before acting on it.")
    else:
        lines.append("* none")

    lines += ["", "## Blockers (first occurrence, recovery path)", "", "| Scenario | Blocker | First day | Last day | Days seen | Recovery |", "|---|---|---:|---:|---:|---|"]
    for s in base_rows:
        for reason, row in s["blockers"].items():
            lines.append(f"| {s['id']} | `{reason}` | {row['first_day']} | {row['last_day']} | {row['days_observed']} | {row['recovery']} |")

    lines += ["", "## Bottlenecks at horizon end (measured, not failures by themselves)", "", "| Scenario | World | Energy<0.95 days | Storage-full days | Wasted metal | Queue busy % | Idle: waiting cost % | Idle: waiting player % | Idle: nothing to build % |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in base_rows:
        end = s["checkpoints"].get("day365") or s["final"]
        for w in end["per_world"][:3]:
            lines.append(f"| {s['id']} | {w['idx']} ({w['climate']}) | {w['energy_low_days']} | {w['storage_full_days']} | {_human(w['wasted_metal'])} | {w['queue_busy_pct']} | {w['idle_waiting_cost_pct']} | {w['idle_waiting_player_pct']} | {w['idle_nothing_to_build_pct']} |")

    exp = next((x for x in data["scenarios"] if x["expeditions_per_day"]), None)
    ref11 = next((x for x in base_rows if x["id"] == "S11-active-mid"), None)
    if exp and ref11:
        lines += ["", "### Sensitivity: expedition XP (S11, active)", "", f"{exp['expeditions_per_day']} expeditions/day grant only the canonical activity XP (15 each, +75 per 10); no ships, fuel or loot are modelled.", "", "| Run | Colony founding days | Worlds @365 | XP: expeditions |", "|---|---|---:|---:|"]
        for x in (ref11, exp):
            days = ", ".join("%g" % e["day"] for e in x["colony_log"] if e["event"] == "founded")
            lines.append(f"| {x['id']} | {days} | {x['final']['worlds']} | {_fmt_int(x['final']['xp_by_source'].get('expedition', 0))} |")

    lines += ["", "## Candidate resonance (simulation-only, R3 not enabled live)", "", "Compared with the active/mid zero-trait baseline (core progress without any rare DNA). The candidate only shortens **construction duration** on qualified worlds (revealed trait + active specialisation, planet level >= 8).", "", "A duration cut can only act on the share of time a build is actually running (*queue busy %* below, small in every run); the rest is waiting for resources or for the player. Deltas of about +-2% (including negative ones for a pure speed-up) are path-dependence noise of the fixed policy, not an effect or a penalty.", ""]
    base = {(s["topology"], s["home_climate"]): s for s in base_rows if s["policy"] == "active"}
    lines += ["| Scenario | Δ best mine @182.5 | Δ best mine @365 | Δ empire M/h @365 | Δ median mine @365 | HW queue busy % @365 |", "|---|---:|---:|---:|---:|---:|"]

    def pct(a: float, b: float) -> str:
        return f"{(a - b) / b * 100:+.2f}%" if b else "n/a"

    for s in data["scenarios"]:
        if s["trait_scenario"] == "none":
            continue
        ref = base.get((s["topology"], s["home_climate"]))
        if not ref:
            continue
        a, c = s["checkpoints"].get("day182.5"), s["checkpoints"].get("day365")
        ra, r = ref["checkpoints"].get("day182.5"), ref["checkpoints"].get("day365")
        if not (a and c and ra and r):
            continue
        lines.append(f"| {s['id']} | {pct(a['mine_depth_max'], ra['mine_depth_max'])} | {pct(c['mine_depth_max'], r['mine_depth_max'])} | {pct(c['empire_metal_h'], r['empire_metal_h'])} | {pct(c['mine_depth_median'], r['mine_depth_median'])} | {c['per_world'][0]['queue_busy_pct']} |")

    lines += ["", "## Not modelled", ""] + [f"* {item}" for item in data["not_modelled"]]
    lines += ["", "## Invariants", "", "| Scenario | OK | Violations |", "|---|---|---|"]
    for s in data["scenarios"]:
        lines.append(f"| {s['id']} | {'yes' if s['invariants']['ok'] else 'NO'} | {'; '.join(s['invariants']['violations'][:3]) or '-'} |")
    lines += ["", "## Reproduce", "", "```bash", "python scripts/player_journey_sim.py --out-json artifacts/player_journey/latest.json --out-md docs/GC_TRAIT_R3_PLAYER_JOURNEY_REPORT.md", "```", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GC Trait-R3 player journey simulator")
    parser.add_argument("--days", type=float, default=365.0)
    parser.add_argument("--quick", action="store_true", help="reduced scenario matrix (mid climate, no trait/expedition variants)")
    parser.add_argument("--only", default=None, help="substring filter on scenario id")
    parser.add_argument("--skip-upper-bound", action="store_true")
    parser.add_argument(
        "--economy-curve",
        choices=("uni1", "default"),
        default="uni1",
        help="uni1 = same endgame production curve as the record-mine control (default); default = process defaults",
    )
    parser.add_argument("--render-from", type=Path, default=None, help="re-render Markdown from an existing JSON result without simulating")
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args(argv)

    if args.render_from:
        data = json.loads(args.render_from.read_text(encoding="utf-8"))
    else:
        data = run_all(args.days, args.quick, args.only, not args.skip_upper_bound, args.economy_curve)
    md = render_markdown(data)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")
    if args.stdout or not (args.out_json or args.out_md):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
