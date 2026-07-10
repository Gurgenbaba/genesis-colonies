"""Deterministic expedition event engine — loot, delays, structured reports."""

from __future__ import annotations

import math
import random
from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple

from .fleet_defs import SHIPS, VALID_RESOURCE_KEYS, ship_has_role, ship_roles, ship_score_value

EXPEDITION_REPORT_VERSION = 2

# Canonical expedition loot (GC-EXPEDITION-LOOT-FINAL): expo hull build-cost sum, sublinear exponent.
EXPEDITION_LOOT_EXPONENT = 0.72
FLEET_LOOT_EXPONENT = EXPEDITION_LOOT_EXPONENT  # legacy alias for tests/imports
EXPEDITION_RANDOM_FACTOR_RANGE = (0.66, 1.5)
DEFAULT_EVENT_FACTOR = 1.0

# Daily expedition diminishing returns — cumulative expo_value per UTC day (GC-EXPEDITION-DAILY).
# Knot x = multiples of one solar_skiff expo unit; y = loot efficiency for the next expedition.
EXPEDITION_DAILY_EFFICIENCY_KNOTS: Tuple[Tuple[float, float], ...] = (
    (0.0, 1.00),
    (20.0, 1.00),
    (30.0, 0.95),
    (40.0, 0.90),
    (60.0, 0.75),
    (80.0, 0.60),
)
EXPEDITION_DAILY_EFFICIENCY_FLOOR = 0.60

# Role split (GC-EXPEDITION-LOOT-FINAL): loot / bergung / piratenkampf / escort
_EXPEDITION_CARGO_ROLES = frozenset({"expedition", "cargo"})
_EXPEDITION_HULL_ROLES = frozenset({"expedition"})
_EXPEDITION_ESCORT_ROLES = frozenset({"combat"})
# Legacy alias — pirate combat uses escort-only fight power; hull value scales risk.
_EXPEDITION_COMBAT_ROLES = _EXPEDITION_HULL_ROLES | _EXPEDITION_ESCORT_ROLES

# Escort effectiveness — ratio-based, diminishing returns (GC-SHIP escort balance).
_ESCORT_EFFECTIVENESS_CAP = 0.50
_EXPO_ONLY_FIGHT_FACTOR = 0.08  # desperation fight when no combat escorts aboard

# Voidrunner discovery bonus — once per fleet, server-side (GC-SHIP-1).
_VOIDRUNNER_KEY = "eclipse_runner"
_VOIDRUNNER_DISCOVERY_BONUS = 0.25

# Per-event multiplier band, economy-day share, and resource split (shares sum to 1.0).
_EVENT_LOOT_PROFILES: Dict[str, Dict[str, Any]] = {
    "mineral_deposit": {
        "mult_range": (1.00, 1.35),
        "economy_day_range": (0.0050, 0.0200),
        "split": {"metal": 0.62, "crystal": 0.38},
    },
    "fuel_cache": {
        "mult_range": (0.85, 1.15),
        "economy_day_range": (0.0050, 0.0200),
        "split": {"fuel_cells": 1.0},
    },
    "debris_salvage": {
        "mult_range": (1.10, 1.60),
        "economy_day_range": (0.0200, 0.0800),
        "split": {"metal": 0.70, "crystal": 0.25, "fuel_cells": 0.05},
    },
    "ancient_stash": {
        "mult_range": (1.80, 3.00),
        "economy_day_range": (0.0500, 0.2000),
        "split": {"metal": 0.50, "crystal": 0.35, "fuel_cells": 0.15},
    },
    "distress_beacon": {
        "mult_range": (0.90, 1.25),
        "economy_day_range": (0.0100, 0.0400),
        "split": {"metal": 0.45, "crystal": 0.30, "fuel_cells": 0.25},
    },
    "pirate_encounter": {
        "mult_range": (0.45, 0.80),
        "economy_day_range": (0.0020, 0.0080),
        "split": {"metal": 0.55, "crystal": 0.30, "fuel_cells": 0.15},
    },
    "lost_container": {
        "mult_range": (0.35, 0.65),
        "economy_day_range": (0.0010, 0.0050),
        "split": {"metal": 0.50, "crystal": 0.35, "fuel_cells": 0.15},
    },
    "abandoned_convoy": {
        "mult_range": (0.55, 0.95),
        "economy_day_range": (0.0030, 0.0120),
        "split": {"metal": 0.40, "crystal": 0.45, "fuel_cells": 0.15},
    },
    "ancient_derelict": {
        "mult_range": (0.20, 0.40),
        "economy_day_range": (0.0020, 0.0080),
        "split": {"metal": 0.45, "crystal": 0.35, "fuel_cells": 0.20},
    },
    "spatial_rift": {
        "mult_range": (0.70, 1.00),
        "economy_day_range": (0.0040, 0.0150),
        "split": {"metal": 0.50, "crystal": 0.35, "fuel_cells": 0.15},
    },
    "time_anomaly": {
        "mult_range": (0.35, 0.65),
        "economy_day_range": (0.0010, 0.0050),
        "split": {"metal": 0.50, "crystal": 0.35, "fuel_cells": 0.15},
    },
    "ancient_beacon": {
        "mult_range": (0.15, 0.30),
        "economy_day_range": (0.0010, 0.0040),
        "split": {"metal": 0.45, "crystal": 0.35, "fuel_cells": 0.20},
    },
}

# Rare additive lootbox drops (resources unchanged). Chance = roll < value.
_EXPEDITION_LOOTBOX_DROPS: Dict[str, Dict[str, Any]] = {
    "void_scan": {"chance": 0.005, "boxes": ("research_capsule",)},
    "mineral_deposit": {"chance": 0.01, "boxes": ("generic_supply_container", "resource_cache")},
    "fuel_cache": {"chance": 0.01, "boxes": ("generic_supply_container", "resource_cache")},
    "debris_salvage": {"chance": 0.02, "boxes": ("wreckage_container", "military_cache")},
    "distress_beacon": {"chance": 0.03, "boxes": ("alien_cache", "military_cache")},
    "ancient_stash": {"chance": 0.08, "boxes": ("alien_cache", "premium_cache", "research_capsule")},
    "sensor_glitch": {"chance": 0.0, "boxes": ()},
    "nav_interference": {"chance": 0.0, "boxes": ()},
    "pirate_encounter": {"chance": 0.0, "boxes": ()},
    "ion_storm": {"chance": 0.0, "boxes": ()},
    "ancient_minefield": {"chance": 0.0, "boxes": ()},
    "lost_container": {"chance": 0.0, "boxes": ()},
    "abandoned_convoy": {"chance": 0.0, "boxes": ()},
    "ancient_derelict": {"chance": 0.0, "boxes": ()},
    "spatial_rift": {"chance": 0.0, "boxes": ()},
    "time_anomaly": {"chance": 0.0, "boxes": ()},
    "ancient_beacon": {"chance": 0.0, "boxes": ()},
}

# Hazard events — non-combat risk (GC-620I-A).
_ION_STORM_DELAY_MULT_RANGE = (0.20, 0.60)
_MINEFIELD_LOSS_RANGE = (2, 8)

# Pirate encounter — lightweight ratio combat (no combat.py resolver).
_PIRATE_ENEMY_FACTOR_RANGE = (0.70, 1.25)
_PIRATE_WIN_CHANCE_BASE = 0.18
_PIRATE_WIN_CHANCE_SCALE = 0.70
_PIRATE_WIN_CHANCE_CLAMP = (0.10, 0.90)
_PIRATE_LOSS_WIN_RANGE = (2, 10)
_PIRATE_LOSS_CLOSE_RANGE = (4, 14)
_PIRATE_LOSS_DEFEAT_RANGE = (8, 20)

# Combat escorts absorb expedition losses first (combat → recycle → expedition → cargo → …).
_LOSS_ROLE_PRIORITY: Tuple[str, ...] = (
    "combat",
    "recycle",
    "expedition",
    "cargo",
    "spy",
    "scout",
    "utility",
    "colony",
)

# Pirate salvage on win — light/mid hulls only; never beats shipyard cadence.
_PIRATE_SALVAGE_NONE_CHANCE = 0.70
_PIRATE_SALVAGE_SMALL_CHANCE = 0.25
_PIRATE_SALVAGE_SCORE_CAP_RATIO = 0.12
_PIRATE_SALVAGE_SHIP_LIGHT: Sequence[str] = ("spark_drone", "mule_courier", "veil_probe")
_PIRATE_SALVAGE_SHIP_MID: Sequence[str] = ("mule_courier", "solar_skiff", "falcon_interceptor")

# Story / treasure events (GC-620I-B).
_LOST_CONTAINER_BOX_COMMON: Sequence[str] = (
    "generic_supply_container",
    "resource_cache",
    "research_capsule",
)
_LOST_CONTAINER_BOX_RARE: Sequence[str] = ("military_cache", "alien_cache")
_LOST_CONTAINER_RARE_BOX_CHANCE = 0.15
_CONVoy_RESOURCES_ONLY_CHANCE = 0.40
_CONVoy_SHIPS_ONLY_CHANCE = 0.45
_CONVoy_BOTH_BONUS_BOX_CHANCE = 0.25
_CONVoy_SALVAGE_SCORE_CAP_RATIO = 0.10

# Legendary discoveries (GC-620J-A).
_LEGENDARY_EVENT_KEYS: frozenset[str] = frozenset(
    {"spatial_rift", "time_anomaly", "ancient_beacon"}
)
_SPATIAL_RIFT_AMPLIFIED_CHANCE = 0.60
_SPATIAL_RIFT_AMPL_MULT_RANGE = (1.40, 1.80)
_SPATIAL_RIFT_DELAY_MULT_RANGE = (0.25, 0.55)
_TIME_ANOMALY_BONUS_CHANCE = 0.30
_TIME_ANOMALY_DILATED_DELAY_RANGE = (0.20, 0.40)
_TIME_ANOMALY_BONUS_LOOT_SCALE = 0.50

_EXPEDITION_ALLOWED_BOX_KEYS = frozenset(
    {
        "generic_supply_container",
        "resource_cache",
        "research_capsule",
        "wreckage_container",
        "military_cache",
        "alien_cache",
        "premium_cache",
        "mythic_container",
        "ancient_relic",
        "void_artifact",
    }
)

# Ancient-stash jackpot tiers (rarest first; at most one per expedition).
_EXPEDITION_JACKPOT_DROPS: Sequence[tuple[float, str]] = (
    (0.00005, "void_artifact"),
    (0.00010, "ancient_relic"),
    (0.00050, "mythic_container"),
)

# Weighted event table (sum = 100). Server-authoritative; extend here only.
_EXPEDITION_EVENTS: Sequence[Dict[str, Any]] = (
    {
        "key": "void_scan",
        "weight": 6,
        "label_key": "expedition_event_void_scan",
        "desc_key": "expedition_event_void_scan_desc",
        "severity": "minor",
        "rewards": {},
    },
    {
        "key": "mineral_deposit",
        "weight": 33,
        "label_key": "expedition_event_mineral_deposit",
        "desc_key": "expedition_event_mineral_deposit_desc",
        "severity": "normal",
    },
    {
        "key": "fuel_cache",
        "weight": 18,
        "label_key": "expedition_event_fuel_cache",
        "desc_key": "expedition_event_fuel_cache_desc",
        "severity": "normal",
    },
    {
        "key": "debris_salvage",
        "weight": 14,
        "label_key": "expedition_event_debris_salvage",
        "desc_key": "expedition_event_debris_salvage_desc",
        "severity": "minor",
    },
    {
        "key": "nav_interference",
        "weight": 6,
        "label_key": "expedition_event_nav_interference",
        "desc_key": "expedition_event_nav_interference_desc",
        "severity": "minor",
        "rewards": {},
        "delay_chance": 1.0,
    },
    {
        "key": "distress_beacon",
        "weight": 11,
        "label_key": "expedition_event_distress_beacon",
        "desc_key": "expedition_event_distress_beacon_desc",
        "severity": "normal",
        "delay_chance": 0.25,
    },
    {
        "key": "sensor_glitch",
        "weight": 3,
        "label_key": "expedition_event_sensor_glitch",
        "desc_key": "expedition_event_sensor_glitch_desc",
        "severity": "minor",
        "rewards": {},
    },
    {
        "key": "ancient_stash",
        "weight": 10,
        "label_key": "expedition_event_ancient_stash",
        "desc_key": "expedition_event_ancient_stash_desc",
        "severity": "major",
    },
    {
        "key": "pirate_encounter",
        "weight": 4,
        "label_key": "expedition_event_pirate_encounter",
        "desc_key": "expedition_event_pirate_encounter_desc",
        "severity": "major",
    },
    {
        "key": "ion_storm",
        "weight": 3,
        "label_key": "expedition_event_ion_storm",
        "desc_key": "expedition_event_ion_storm_desc",
        "severity": "minor",
        "rewards": {},
        "delay_chance": 1.0,
        "delay_multiplier_range": _ION_STORM_DELAY_MULT_RANGE,
    },
    {
        "key": "ancient_minefield",
        "weight": 2,
        "label_key": "expedition_event_ancient_minefield",
        "desc_key": "expedition_event_ancient_minefield_desc",
        "severity": "major",
        "rewards": {},
    },
    {
        "key": "lost_container",
        "weight": 3,
        "label_key": "expedition_event_lost_container",
        "desc_key": "expedition_event_lost_container_desc",
        "severity": "normal",
    },
    {
        "key": "abandoned_convoy",
        "weight": 2,
        "label_key": "expedition_event_abandoned_convoy",
        "desc_key": "expedition_event_abandoned_convoy_desc",
        "severity": "major",
    },
    {
        "key": "ancient_derelict",
        "weight": 1,
        "label_key": "expedition_event_ancient_derelict",
        "desc_key": "expedition_event_ancient_derelict_desc",
        "severity": "major",
        "story_tier": "legendary",
    },
    {
        "key": "spatial_rift",
        "weight": 1,
        "label_key": "expedition_event_spatial_rift",
        "desc_key": "expedition_event_spatial_rift_desc",
        "severity": "major",
        "story_tier": "legendary",
    },
    {
        "key": "time_anomaly",
        "weight": 1,
        "label_key": "expedition_event_time_anomaly",
        "desc_key": "expedition_event_time_anomaly_desc",
        "severity": "major",
        "story_tier": "legendary",
    },
    {
        "key": "ancient_beacon",
        "weight": 1,
        "label_key": "expedition_event_ancient_beacon",
        "desc_key": "expedition_event_ancient_beacon_desc",
        "severity": "major",
        "story_tier": "legendary",
    },
)

_EVENT_BY_KEY: Dict[str, Dict[str, Any]] = {str(e["key"]): e for e in _EXPEDITION_EVENTS}

_SALVAGE_EVENT_KEYS: frozenset[str] = frozenset(
    {"debris_salvage", "mineral_deposit", "fuel_cache", "distress_beacon"}
)

# Category shares for weight audit (GC-620J-0) — table weights only, not sub-rolls.
_EXPEDITION_EVENT_CATEGORIES: Dict[str, str] = {
    "void_scan": "neutral",
    "sensor_glitch": "neutral",
    "mineral_deposit": "loot",
    "fuel_cache": "loot",
    "debris_salvage": "loot",
    "distress_beacon": "loot",
    "ancient_stash": "loot",
    "nav_interference": "delay",
    "ion_storm": "delay",
    "pirate_encounter": "combat",
    "ancient_minefield": "hazard",
    "lost_container": "treasure",
    "abandoned_convoy": "treasure",
    "ancient_derelict": "treasure",
    "spatial_rift": "legendary",
    "time_anomaly": "legendary",
    "ancient_beacon": "legendary",
}


def expedition_event_keys() -> frozenset[str]:
    return frozenset(_EVENT_BY_KEY.keys())


def expedition_event_weight_audit() -> Dict[str, Any]:
    """Static weight table summary for balance audit and regression tests."""
    by_key: Dict[str, float] = {}
    for event in _EXPEDITION_EVENTS:
        by_key[str(event["key"])] = float(event.get("weight") or 0.0)
    total = sum(by_key.values())
    by_category: Dict[str, float] = {}
    for key, weight in by_key.items():
        category = _EXPEDITION_EVENT_CATEGORIES.get(key, "other")
        by_category[category] = by_category.get(category, 0.0) + weight
    share_by_category = {
        category: (weight / total if total > 0 else 0.0) for category, weight in by_category.items()
    }
    return {
        "total_weight": int(total),
        "weights_by_key": {key: int(weight) for key, weight in by_key.items()},
        "weight_by_category": {cat: int(weight) for cat, weight in by_category.items()},
        "share_by_category": share_by_category,
    }


def _event_has_loot(event_key: str) -> bool:
    return str(event_key) in _EVENT_LOOT_PROFILES


def calculate_fleet_value(ships: Mapping[str, int]) -> int:
    """Sum of hull count × score_value for all ships on the expedition."""
    total = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        total += amount * ship_score_value(str(key))
    return max(0, total)


def expedition_ship_fleet_value(ship_key: str) -> int:
    """Build-cost sum for one expedition hull — canonical loot scaling input (Odyssey = solar_skiff)."""
    from .fleet_defs import canonical_ship_key

    if not ship_has_role(ship_key, "expedition"):
        return 0
    spec = SHIPS.get(canonical_ship_key(ship_key)) or {}
    costs = spec.get("build_cost") or {}
    return sum(int(costs.get(resource) or 0) for resource in VALID_RESOURCE_KEYS)


def expedition_ship_expo_loot_unit(ship_key: str) -> float:
    """Per expedition hull: build_cost sum ** EXPEDITION_LOOT_EXPONENT (sublinear per hull)."""
    raw = expedition_ship_fleet_value(ship_key)
    if raw <= 0:
        return 0.0
    return math.pow(raw, EXPEDITION_LOOT_EXPONENT)


def expedition_daily_reference_unit() -> float:
    """Reference expo_value unit for daily efficiency knots (one solar_skiff)."""
    return max(1.0, float(expedition_ship_expo_loot_unit("solar_skiff")))


def expedition_daily_day_bucket(ts: float | None = None) -> int:
    import time

    return int(float(ts if ts is not None else time.time()) // 86400)


def _expedition_daily_tables_ready(conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'expedition_daily_value' LIMIT 1;"
    )
    return cur.fetchone() is not None


def get_expedition_daily_expo_value(player_id: int, *, conn, ts: float | None = None) -> int:
    """Accumulated expedition expo_value for the current UTC day (before current resolve)."""
    if not _expedition_daily_tables_ready(conn):
        return 0
    bucket = expedition_daily_day_bucket(ts)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT expo_value_total FROM expedition_daily_value
        WHERE player_id = ? AND day_bucket = ? LIMIT 1;
        """,
        (int(player_id), int(bucket)),
    )
    row = cur.fetchone()
    return int(row["expo_value_total"] if row else 0)


def expedition_daily_efficiency_multiplier(daily_expo_value: int) -> float:
    """
    Loot efficiency for the next expedition based on today's accumulated expo_value.

    Small/mid daily totals stay at 100%; extreme endgame spirals taper toward the floor.
    """
    ref = expedition_daily_reference_unit()
    x = max(0.0, float(daily_expo_value)) / ref
    knots = EXPEDITION_DAILY_EFFICIENCY_KNOTS
    if not knots:
        return 1.0
    if x <= knots[0][0]:
        return float(knots[0][1])
    if x >= knots[-1][0]:
        return max(EXPEDITION_DAILY_EFFICIENCY_FLOOR, float(knots[-1][1]))
    for idx in range(len(knots) - 1):
        x0, y0 = knots[idx]
        x1, y1 = knots[idx + 1]
        if x0 <= x <= x1:
            if x1 <= x0:
                return max(EXPEDITION_DAILY_EFFICIENCY_FLOOR, float(y1))
            t = (x - x0) / (x1 - x0)
            eff = float(y0) + t * (float(y1) - float(y0))
            return max(EXPEDITION_DAILY_EFFICIENCY_FLOOR, eff)
    return max(EXPEDITION_DAILY_EFFICIENCY_FLOOR, float(knots[-1][1]))


def _scale_resource_rewards(rewards: MutableMapping[str, int], mult: float) -> None:
    m = max(0.0, min(1.0, float(mult)))
    if m >= 0.999999:
        return
    for key in VALID_RESOURCE_KEYS:
        if key in rewards:
            rewards[key] = max(0, int(int(rewards.get(key) or 0) * m))


def record_expedition_daily_value(
    player_id: int,
    movement_id: int,
    expo_value: int,
    *,
    conn,
    ts: float | None = None,
) -> bool:
    """Idempotent: add expo_value once per completed expedition movement."""
    if not _expedition_daily_tables_ready(conn):
        return False
    mid = int(movement_id)
    pid = int(player_id)
    value = max(0, int(expo_value))
    if mid <= 0 or value <= 0:
        return False
    bucket = expedition_daily_day_bucket(ts)
    import time

    now = float(ts if ts is not None else time.time())
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM expedition_daily_recorded WHERE movement_id = ? LIMIT 1;",
        (mid,),
    )
    if cur.fetchone():
        return False
    cur.execute(
        """
        INSERT INTO expedition_daily_recorded (movement_id, player_id, day_bucket, expo_value, recorded_at)
        VALUES (?, ?, ?, ?, ?);
        """,
        (mid, pid, int(bucket), value, now),
    )
    cur.execute(
        """
        INSERT INTO expedition_daily_value (player_id, day_bucket, expo_value_total, expedition_count, updated_at)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(player_id, day_bucket) DO UPDATE SET
            expo_value_total = expo_value_total + excluded.expo_value_total,
            expedition_count = expedition_count + 1,
            updated_at = excluded.updated_at;
        """,
        (pid, int(bucket), value, now),
    )
    return True


def expedition_daily_status(player_id: int, *, conn, ts: float | None = None) -> Dict[str, Any]:
    """HUD/report slice — today's accumulated expo_value and current efficiency."""
    import time

    now = float(ts if ts is not None else time.time())
    daily = get_expedition_daily_expo_value(player_id, conn=conn, ts=now)
    eff = expedition_daily_efficiency_multiplier(daily)
    ref = expedition_daily_reference_unit()
    bucket = expedition_daily_day_bucket(now)
    return {
        "day_bucket": bucket,
        "daily_expo_value": int(daily),
        "daily_efficiency_pct": int(round(eff * 100)),
        "daily_efficiency_mult": float(eff),
        "reference_expo_unit": int(ref),
        "reset_at": int((bucket + 1) * 86400),
    }


def calculate_expo_value(ships: Mapping[str, int]) -> int:
    """Σ count × (per_hull_build_cost ** EXPEDITION_LOOT_EXPONENT); escorts/cargo excluded."""
    from .fleet_defs import canonical_ship_key

    total = 0.0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        canon = canonical_ship_key(str(key))
        per_hull_expo = expedition_ship_expo_loot_unit(canon)
        if per_hull_expo <= 0:
            continue
        total += amount * per_hull_expo
    return max(0, int(total))


def calculate_base_expedition_loot(expo_value: int) -> float:
    """Reference base loot before random/event factors (expo_value already per-hull exponent sum)."""
    if expo_value <= 0:
        return 0.0
    return float(max(0, int(expo_value)))


def _expo_value_for_outcome(
    ships: Mapping[str, int] | None,
    expedition_ship_count: int,
) -> int:
    if ships:
        value = calculate_expo_value(ships)
        if value > 0:
            return value
    hulls = max(0, int(expedition_ship_count))
    if hulls <= 0:
        return 0
    return int(hulls * expedition_ship_expo_loot_unit("solar_skiff"))


def calculate_expedition_hull_value(ships: Mapping[str, int]) -> int:
    """Score sum of expedition-role hulls — loot scaling and pirate risk input."""
    from .fleet_defs import canonical_ship_key

    total = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        canon = canonical_ship_key(str(key))
        if not (_EXPEDITION_HULL_ROLES & ship_roles(canon)):
            continue
        total += amount * ship_score_value(str(key))
    return max(0, total)


def calculate_expedition_escort_value(ships: Mapping[str, int]) -> int:
    """Score sum of combat-role escorts only — pure expedition hulls do not fight pirates."""
    from .fleet_defs import canonical_ship_key

    total = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        canon = canonical_ship_key(str(key))
        if not (_EXPEDITION_ESCORT_ROLES & ship_roles(canon)):
            continue
        total += amount * ship_score_value(str(key))
    return max(0, total)


def calculate_expedition_combat_value(ships: Mapping[str, int]) -> int:
    """Escort fight power for pirate encounters (combat role only, not expo hulls)."""
    return calculate_expedition_escort_value(ships)


def _escort_effectiveness(escort_ratio: float) -> float:
    """Diminishing returns on escort_ratio; caps at _ESCORT_EFFECTIVENESS_CAP."""
    ratio = max(0.0, float(escort_ratio))
    if ratio <= 0.0:
        return 0.0
    raw = _ESCORT_EFFECTIVENESS_CAP * (1.0 - math.exp(-2.5 * ratio))
    return min(_ESCORT_EFFECTIVENESS_CAP, raw)


def _voidrunner_count(ships: Mapping[str, int] | None) -> int:
    if not ships:
        return 0
    from .fleet_defs import canonical_ship_key

    key = canonical_ship_key(_VOIDRUNNER_KEY)
    return max(0, int(ships.get(key) or ships.get(_VOIDRUNNER_KEY) or 0))


def _voidrunner_discovery_bonus(ships: Mapping[str, int] | None) -> float:
    """+25 % positive event weight / loot quality — once per fleet when any Voidrunner aboard."""
    if _voidrunner_count(ships) <= 0:
        return 0.0
    return _VOIDRUNNER_DISCOVERY_BONUS


def _voidrunner_loot_mult(ships: Mapping[str, int] | None) -> float:
    bonus = _voidrunner_discovery_bonus(ships)
    return 1.0 + bonus if bonus > 0 else 1.0


def build_expedition_fleet_rating(ships: Mapping[str, int]) -> Dict[str, Any]:
    """Canonical expedition escort / voidrunner rating — preview, outcome, and report."""
    hull_val = calculate_expedition_hull_value(ships)
    escort_val = calculate_expedition_escort_value(ships)
    ratio = escort_val / max(1, hull_val) if hull_val > 0 else 0.0
    eff = _escort_effectiveness(ratio)
    void_bonus = _voidrunner_discovery_bonus(ships)
    return {
        "expedition_hull_value": int(hull_val),
        "escort_combat_value": int(escort_val),
        "escort_ratio": round(ratio, 4),
        "escort_effectiveness": round(eff, 4),
        "voidrunner_bonus_active": void_bonus > 0,
        "voidrunner_bonus_pct": int(round(void_bonus * 100)) if void_bonus > 0 else 0,
    }


def _fleet_value_for_outcome(
    ships: Mapping[str, int] | None,
    expedition_ship_count: int,
) -> int:
    """Total fleet score for story/treasure events (not pirate fight power)."""
    if ships:
        value = calculate_fleet_value(ships)
        if value > 0:
            return value
    hulls = max(0, int(expedition_ship_count))
    if hulls <= 0:
        return 0
    return hulls * ship_score_value("solar_skiff")


def count_expedition_ships(ships: Mapping[str, int]) -> int:
    total = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        if ship_has_role(str(key), "expedition"):
            total += amount
    return total


def calculate_expedition_loot_cap(ships: Mapping[str, int]) -> int:
    """Bergung cap: cargo holds of expedition hulls + Frachter (combat escorts excluded)."""
    from .fleet_defs import canonical_ship_key

    cargo_total = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        canon = canonical_ship_key(str(key))
        if not (_EXPEDITION_CARGO_ROLES & ship_roles(canon)):
            continue
        spec = SHIPS.get(canon) or {}
        cargo_total += int(spec.get("cargo") or 0) * amount
    return max(0, cargo_total)


def _pick_event_key(
    rng: random.Random,
    expedition_ship_count: int,
    *,
    salvage: bool = False,
    event_bonus: float = 0.0,
    voidrunner_bonus: float = 0.0,
) -> str:
    """Pick event; extra expedition hulls shift weight away from empty outcomes."""
    bonus = min(0.12, max(0, int(expedition_ship_count)) * 0.03) + max(0.0, float(event_bonus))
    discovery_bonus = max(0.0, float(voidrunner_bonus))
    empty_keys = {"void_scan", "sensor_glitch", "ion_storm", "ancient_minefield", "nav_interference"}
    adjusted: list[tuple[str, float]] = []
    for event in _EXPEDITION_EVENTS:
        key = str(event["key"])
        if salvage and key not in _SALVAGE_EVENT_KEYS:
            continue
        weight = float(event["weight"])
        if key in empty_keys:
            weight = max(1.0, weight * (1.0 - bonus))
        elif _event_has_loot(key):
            weight = weight * (1.0 + bonus + discovery_bonus)
        adjusted.append((key, weight))
    if not adjusted:
        adjusted = [(str(_EXPEDITION_EVENTS[0]["key"]), 1.0)]
    total = sum(w for _, w in adjusted)
    roll = rng.random() * total
    for key, weight in adjusted:
        roll -= weight
        if roll <= 0:
            return key
    return str(_EXPEDITION_EVENTS[-1]["key"])


def _empty_rewards() -> Dict[str, int]:
    return {key: 0 for key in VALID_RESOURCE_KEYS}


def _split_loot_total(total: int, split: Mapping[str, float]) -> Dict[str, int]:
    rewards = _empty_rewards()
    if total <= 0:
        return rewards
    ordered = [(str(k), float(v)) for k, v in split.items() if k in VALID_RESOURCE_KEYS and float(v) > 0]
    if not ordered:
        return rewards
    allocated = 0
    for idx, (resource, share) in enumerate(ordered):
        if idx == len(ordered) - 1:
            amount = max(0, total - allocated)
        else:
            amount = int(total * share)
            allocated += amount
        rewards[resource] = amount
    return rewards


def _compute_event_loot(
    rng: random.Random,
    event_key: str,
    expo_value: int,
    *,
    cargo_total: int = 0,
    event_factor: float = DEFAULT_EVENT_FACTOR,
    loot_quality_mult: float = 1.0,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    profile = _EVENT_LOOT_PROFILES.get(str(event_key))
    if not profile or int(expo_value) <= 0:
        return _empty_rewards(), {"expo_value": 0, "raw_loot_total": 0}

    mult_lo, mult_hi = profile["mult_range"]
    profile_mult = rng.uniform(float(mult_lo), float(mult_hi))
    random_factor = rng.uniform(
        float(EXPEDITION_RANDOM_FACTOR_RANGE[0]),
        float(EXPEDITION_RANDOM_FACTOR_RANGE[1]),
    )
    global_event_factor = max(0.0, float(event_factor))
    quality_mult = max(1.0, float(loot_quality_mult))

    base_loot = calculate_base_expedition_loot(int(expo_value))
    total_loot = max(
        0,
        int(base_loot * random_factor * profile_mult * global_event_factor * quality_mult),
    )
    cargo_cap = max(0, int(cargo_total))
    if cargo_cap > 0:
        total_loot = min(total_loot, cargo_cap)

    debug = {
        "expo_value": int(expo_value),
        "raw_loot_total": int(total_loot),
        "base_loot": int(base_loot),
        "random_factor": float(random_factor),
        "profile_mult": float(profile_mult),
        "event_factor": float(global_event_factor),
    }
    return _split_loot_total(total_loot, profile.get("split") or {}), debug


def is_allowed_expedition_lootbox(box_key: str) -> bool:
    from .auction_house import is_event_box

    key = str(box_key or "").strip()
    if not key or is_event_box(key):
        return False
    return key in _EXPEDITION_ALLOWED_BOX_KEYS


def _lootbox_display_entry(
    box_key: str,
    amount: int,
    *,
    locale: str | None = None,
    jackpot: bool = False,
) -> Dict[str, Any]:
    from .auction_house import resolve_inventory_key
    from .inventory_catalog import item_catalog_entry
    from .i18n import tr

    inv_key = resolve_inventory_key(box_key) or box_key
    spec = item_catalog_entry(inv_key) or {}
    name_key = str(spec.get("name_key") or box_key)
    return {
        "key": str(box_key),
        "amount": max(1, int(amount)),
        "name": tr(name_key, box_key, locale=locale),
        "name_key": name_key,
        "image": str(spec.get("image") or ""),
        "jackpot": bool(jackpot),
    }


def _roll_expedition_lootboxes(rng: random.Random, event_key: str) -> list[Dict[str, Any]]:
    drops: list[Dict[str, Any]] = []
    if str(event_key) == "ancient_stash":
        for chance, box_key in _EXPEDITION_JACKPOT_DROPS:
            if rng.random() < float(chance) and is_allowed_expedition_lootbox(box_key):
                drops.append({"key": box_key, "amount": 1, "jackpot": True})
                break

    profile = _EXPEDITION_LOOTBOX_DROPS.get(str(event_key))
    if not profile:
        return drops
    chance = float(profile.get("chance") or 0.0)
    if chance <= 0 or rng.random() >= chance:
        return drops
    pool = [str(box) for box in (profile.get("boxes") or ()) if is_allowed_expedition_lootbox(str(box))]
    if not pool:
        return drops
    box_key = pool[rng.randrange(len(pool))]
    drops.append({"key": box_key, "amount": 1})
    return drops


def grant_expedition_lootboxes(
    player_id: int,
    lootboxes: Sequence[Mapping[str, Any]],
    *,
    movement_id: int,
    conn,
) -> None:
    """Persist expedition lootboxes via canonical inventory + lootbox_inventory."""
    if not lootboxes:
        return
    from .auction_house import resolve_inventory_key
    from .inventory import grant_inventory_item, inventory_schema_ready
    from .models import table_exists
    import time

    now = int(time.time())
    cur = conn.cursor()
    for entry in lootboxes:
        box_key = str(entry.get("key") or "").strip()
        amount = max(1, int(entry.get("amount") or 1))
        if not is_allowed_expedition_lootbox(box_key):
            continue
        inv_key = resolve_inventory_key(box_key)
        if inv_key and inventory_schema_ready(conn):
            grant_inventory_item(
                int(player_id),
                inv_key,
                amount,
                conn=conn,
                metadata={"source": "expedition", "movement_id": int(movement_id), "box_key": box_key},
            )
        if table_exists(conn, "lootbox_inventory"):
            for _ in range(amount):
                cur.execute(
                    """
                    INSERT INTO lootbox_inventory (player_id, box_key, source, created_at)
                    VALUES (?, ?, 'expedition', ?);
                    """,
                    (int(player_id), box_key, now),
                )


def _scale_rewards_to_cargo(rewards: MutableMapping[str, int], cargo_total: int) -> None:
    loaded = sum(int(rewards.get(k) or 0) for k in VALID_RESOURCE_KEYS)
    if cargo_total <= 0 or loaded <= cargo_total:
        return
    scale = cargo_total / max(1, loaded)
    for key in VALID_RESOURCE_KEYS:
        rewards[key] = int(int(rewards.get(key) or 0) * scale)


def _apply_cargo_cap(
    rewards: MutableMapping[str, int],
    cargo_total: int,
) -> Dict[str, Any]:
    """Cap loot to expedition cargo; rewards are scaled proportionally when over cap."""
    cargo_cap = max(0, int(cargo_total))
    loaded = sum(int(rewards.get(k) or 0) for k in VALID_RESOURCE_KEYS)
    meta: Dict[str, Any] = {"raw_loot_total": int(loaded)}
    if cargo_cap > 0 and loaded > cargo_cap:
        _scale_rewards_to_cargo(rewards, cargo_cap)
        meta["raw_loot_total"] = cargo_cap
    return meta


def _apply_directive_reward_modifiers(
    rewards: MutableMapping[str, int],
    *,
    loot_mult: float = 1.0,
    wreckage_bonus: float = 0.0,
    salvage: bool = False,
) -> None:
    mult = max(0.0, float(loot_mult))
    if salvage and wreckage_bonus:
        mult *= 1.0 + max(0.0, float(wreckage_bonus))
    if mult == 1.0:
        return
    for key in VALID_RESOURCE_KEYS:
        rewards[key] = int(int(rewards.get(key) or 0) * mult)


def _pirate_win_chance(ratio: float) -> float:
    raw = _PIRATE_WIN_CHANCE_BASE + _PIRATE_WIN_CHANCE_SCALE * float(ratio) / (1.0 + float(ratio))
    return max(_PIRATE_WIN_CHANCE_CLAMP[0], min(_PIRATE_WIN_CHANCE_CLAMP[1], raw))


def _loss_role_priority(ship_key: str) -> int:
    """Lowest priority index across all roles — hybrid Voidrunner is lost like combat first."""
    roles = ship_roles(str(ship_key))
    if not roles:
        return len(_LOSS_ROLE_PRIORITY)
    best = len(_LOSS_ROLE_PRIORITY)
    for role in roles:
        try:
            best = min(best, _LOSS_ROLE_PRIORITY.index(role))
        except ValueError:
            continue
    return best


def apply_expedition_ship_losses(
    ships: Mapping[str, int],
    loss_pct: int,
    *,
    min_remaining: int = 1,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Apply hull losses; combat escorts absorb before expedition hulls. Never wipe fleet."""
    loss_pct = max(0, min(100, int(loss_pct)))
    cleaned = {str(k): int(v) for k, v in (ships or {}).items() if int(v or 0) > 0}
    if loss_pct <= 0 or not cleaned:
        return cleaned, {}

    total = sum(cleaned.values())
    floor = max(1, int(min_remaining))
    if total <= floor:
        return cleaned, {}

    loss_budget = min(total - floor, int(math.floor(total * loss_pct / 100.0)))
    if loss_budget <= 0:
        return cleaned, {}

    remaining = dict(cleaned)
    losses: Dict[str, int] = {}
    ordered_keys = sorted(remaining.keys(), key=lambda k: (_loss_role_priority(k), k))
    for key in ordered_keys:
        if loss_budget <= 0:
            break
        take = min(int(remaining[key]), loss_budget)
        if take <= 0:
            continue
        losses[key] = take
        remaining[key] -= take
        if remaining[key] <= 0:
            remaining.pop(key, None)
        loss_budget -= take

    remaining = {k: v for k, v in remaining.items() if v > 0}
    losses = {k: v for k, v in losses.items() if v > 0}
    return remaining, losses


def _merge_ship_counts(
    base: Mapping[str, int],
    extra: Mapping[str, int],
) -> Dict[str, int]:
    merged = {str(k): int(v) for k, v in (base or {}).items() if int(v or 0) > 0}
    for key, qty in (extra or {}).items():
        amount = int(qty or 0)
        if amount > 0:
            merged[str(key)] = merged.get(str(key), 0) + amount
    return merged


def roll_pirate_salvage_rewards(
    rng: random.Random,
    *,
    pirate_points: int,
    fleet_points: int,
) -> Tuple[Dict[str, int], str]:
    """Salvage/capture roll on pirate victory — 70% none, 25% small, 5% rare."""
    roll = rng.random()
    if roll < _PIRATE_SALVAGE_NONE_CHANCE:
        return {}, "none"
    tier = (
        "small"
        if roll < (_PIRATE_SALVAGE_NONE_CHANCE + _PIRATE_SALVAGE_SMALL_CHANCE)
        else "rare"
    )

    pirate_pts = max(1, int(pirate_points))
    fleet_pts = max(1, int(fleet_points))
    score_cap = max(
        ship_score_value("spark_drone"),
        int(pirate_pts * _PIRATE_SALVAGE_SCORE_CAP_RATIO),
    )
    if tier == "rare":
        score_cap = min(int(score_cap * 1.8), int(pirate_pts * 0.20))

    pool = list(_PIRATE_SALVAGE_SHIP_LIGHT if tier == "small" else _PIRATE_SALVAGE_SHIP_MID)
    max_hulls = 2 if tier == "small" else 3
    if pirate_pts < int(fleet_pts * 0.85):
        max_hulls = min(max_hulls, 1)

    target_hulls = rng.randint(1, max(1, max_hulls))
    salvaged: Dict[str, int] = {}
    total_score = 0
    for _ in range(target_hulls):
        affordable = [k for k in pool if total_score + ship_score_value(k) <= score_cap]
        if not affordable:
            break
        weights = [1.0 / max(1.0, float(ship_score_value(k))) for k in affordable]
        total_w = sum(weights)
        pick = rng.random() * total_w
        chosen = affordable[-1]
        for key, weight in zip(affordable, weights):
            pick -= weight
            if pick <= 0:
                chosen = key
                break
        salvaged[chosen] = salvaged.get(chosen, 0) + 1
        total_score += ship_score_value(chosen)

    return {k: v for k, v in salvaged.items() if v > 0}, tier


def roll_lost_container_lootboxes(rng: random.Random) -> list[Dict[str, Any]]:
    """Drifting supply container — one lootbox, mostly common pool."""
    if rng.random() < _LOST_CONTAINER_RARE_BOX_CHANCE:
        pool = [b for b in _LOST_CONTAINER_BOX_RARE if is_allowed_expedition_lootbox(b)]
    else:
        pool = [b for b in _LOST_CONTAINER_BOX_COMMON if is_allowed_expedition_lootbox(b)]
    if not pool:
        return []
    return [{"key": pool[rng.randrange(len(pool))], "amount": 1}]


def _roll_convoy_ship_salvage(rng: random.Random, fleet_value: int) -> Dict[str, int]:
    """Convoy wreck salvage — light/mid hulls, capped below pirate salvage."""
    fleet_pts = max(1, int(fleet_value))
    score_cap = max(
        ship_score_value("solar_skiff"),
        int(fleet_pts * _CONVoy_SALVAGE_SCORE_CAP_RATIO),
    )
    pool = list(_PIRATE_SALVAGE_SHIP_LIGHT) + list(_PIRATE_SALVAGE_SHIP_MID)
    target_hulls = rng.randint(1, 3)
    salvaged: Dict[str, int] = {}
    total_score = 0
    for _ in range(target_hulls):
        affordable = [k for k in pool if total_score + ship_score_value(k) <= score_cap]
        if not affordable:
            break
        weights = [1.0 / max(1.0, float(ship_score_value(k))) for k in affordable]
        total_w = sum(weights)
        pick = rng.random() * total_w
        chosen = affordable[-1]
        for key, weight in zip(affordable, weights):
            pick -= weight
            if pick <= 0:
                chosen = key
                break
        salvaged[chosen] = salvaged.get(chosen, 0) + 1
        total_score += ship_score_value(chosen)
    return {k: v for k, v in salvaged.items() if v > 0}


def resolve_abandoned_convoy_treasure(
    rng: random.Random,
    *,
    fleet_value: int,
) -> Dict[str, Any]:
    """Abandoned convoy — resources, ships, or both (no combat)."""
    roll = rng.random()
    if roll < _CONVoy_RESOURCES_ONLY_CHANCE:
        mode = "resources"
    elif roll < (_CONVoy_RESOURCES_ONLY_CHANCE + _CONVoy_SHIPS_ONLY_CHANCE):
        mode = "ships"
    else:
        mode = "both"

    salvaged: Dict[str, int] = {}
    lootboxes: list[Dict[str, Any]] = []
    if mode in ("ships", "both"):
        salvaged = _roll_convoy_ship_salvage(rng, fleet_value)
    if mode == "both" and rng.random() < _CONVoy_BOTH_BONUS_BOX_CHANCE:
        box_pool = [b for b in ("resource_cache", "generic_supply_container") if is_allowed_expedition_lootbox(b)]
        if box_pool:
            lootboxes.append({"key": box_pool[rng.randrange(len(box_pool))], "amount": 1})

    return {
        "mode": mode,
        "salvaged_ships": salvaged,
        "lootboxes": lootboxes,
    }


def resolve_ancient_derelict_treasure(rng: random.Random) -> Dict[str, Any]:
    """Ultra-rare derelict — one mid hull plus premium cache lootbox."""
    box_key = "premium_cache" if rng.random() < 0.35 else "alien_cache"
    if not is_allowed_expedition_lootbox(box_key):
        box_key = "alien_cache"
    return {
        "salvaged_ships": {"falcon_interceptor": 1},
        "lootboxes": [{"key": box_key, "amount": 1, "jackpot": True}],
        "story_tier": "legendary",
    }


def _legendary_loot_rng(movement_id: int, salt: int) -> random.Random:
    return random.Random(int(movement_id) * 7919 + int(salt))


def resolve_spatial_rift_legendary(
    rng: random.Random,
    *,
    movement_id: int,
    expo_value: int,
    cargo_total: int,
    flight_seconds: int,
    event_factor: float = DEFAULT_EVENT_FACTOR,
) -> Dict[str, Any]:
    """Spatial rift — amplified cargo-capped find or return delay."""
    base_flight = max(1, int(flight_seconds or 60))
    if rng.random() < _SPATIAL_RIFT_AMPLIFIED_CHANCE:
        loot_rng = _legendary_loot_rng(movement_id, 133773)
        rewards, loot_debug = _compute_event_loot(
            loot_rng,
            "spatial_rift",
            expo_value,
            cargo_total=int(cargo_total),
            event_factor=event_factor,
        )
        ampl = rng.uniform(_SPATIAL_RIFT_AMPL_MULT_RANGE[0], _SPATIAL_RIFT_AMPL_MULT_RANGE[1])
        for key in VALID_RESOURCE_KEYS:
            rewards[key] = int(int(rewards.get(key) or 0) * ampl)
        _apply_cargo_cap(rewards, int(cargo_total))
        return {
            "variant": "amplified",
            "rewards": rewards,
            "loot_debug": loot_debug,
            "delay_extra": 0,
            "lootboxes": [],
        }
    delay_mult = rng.uniform(_SPATIAL_RIFT_DELAY_MULT_RANGE[0], _SPATIAL_RIFT_DELAY_MULT_RANGE[1])
    return {
        "variant": "delayed",
        "rewards": _empty_rewards(),
        "loot_debug": {"expo_value": 0, "raw_loot_total": 0},
        "delay_extra": max(1, int(base_flight * delay_mult)),
        "lootboxes": [],
    }


def resolve_time_anomaly_legendary(
    rng: random.Random,
    *,
    movement_id: int,
    expo_value: int,
    cargo_total: int,
    flight_seconds: int,
    event_factor: float = DEFAULT_EVENT_FACTOR,
) -> Dict[str, Any]:
    """Time anomaly — dilated delay or compressed flavor with optional mini bonus."""
    base_flight = max(1, int(flight_seconds or 60))
    compressed = rng.random() < 0.50
    rewards = _empty_rewards()
    loot_debug: Dict[str, Any] = {"expo_value": 0, "raw_loot_total": 0}
    delay_extra = 0
    if compressed:
        variant = "compressed"
        if rng.random() < _TIME_ANOMALY_BONUS_CHANCE:
            loot_rng = _legendary_loot_rng(movement_id, 144881)
            rewards, loot_debug = _compute_event_loot(
                loot_rng,
                "time_anomaly",
                expo_value,
                cargo_total=int(cargo_total),
                event_factor=event_factor,
            )
            for key in VALID_RESOURCE_KEYS:
                rewards[key] = int(int(rewards.get(key) or 0) * _TIME_ANOMALY_BONUS_LOOT_SCALE)
            _apply_cargo_cap(rewards, int(cargo_total))
    else:
        variant = "dilated"
        delay_mult = rng.uniform(
            _TIME_ANOMALY_DILATED_DELAY_RANGE[0],
            _TIME_ANOMALY_DILATED_DELAY_RANGE[1],
        )
        delay_extra = max(1, int(base_flight * delay_mult))
        if rng.random() < _TIME_ANOMALY_BONUS_CHANCE:
            loot_rng = _legendary_loot_rng(movement_id, 155987)
            rewards, loot_debug = _compute_event_loot(
                loot_rng,
                "time_anomaly",
                expo_value,
                cargo_total=int(cargo_total),
                event_factor=event_factor,
            )
            for key in VALID_RESOURCE_KEYS:
                rewards[key] = int(int(rewards.get(key) or 0) * _TIME_ANOMALY_BONUS_LOOT_SCALE)
            _apply_cargo_cap(rewards, int(cargo_total))
    return {
        "variant": variant,
        "rewards": rewards,
        "loot_debug": loot_debug,
        "delay_extra": int(delay_extra),
        "lootboxes": [],
    }


def resolve_ancient_beacon_legendary(
    rng: random.Random,
    *,
    movement_id: int,
    expo_value: int,
    cargo_total: int,
    event_factor: float = DEFAULT_EVENT_FACTOR,
) -> Dict[str, Any]:
    """Ancient beacon — premium cache lootbox plus modest resources."""
    roll = rng.random()
    if roll < 0.70:
        box_key = "alien_cache"
    elif roll < 0.95:
        box_key = "premium_cache"
    else:
        box_key = "research_capsule"
    if not is_allowed_expedition_lootbox(box_key):
        box_key = "alien_cache"
    loot_rng = _legendary_loot_rng(movement_id, 166699)
    rewards, loot_debug = _compute_event_loot(
        loot_rng,
        "ancient_beacon",
        expo_value,
        cargo_total=int(cargo_total),
        event_factor=event_factor,
    )
    return {
        "variant": "beacon",
        "rewards": rewards,
        "loot_debug": loot_debug,
        "delay_extra": 0,
        "lootboxes": [{"key": box_key, "amount": 1, "jackpot": True}],
    }


def resolve_minefield_hazard(
    rng: random.Random,
    ships: Mapping[str, int],
) -> Dict[str, Any]:
    """Non-combat minefield — small proportional losses, never total fleet wipe."""
    loss_pct = rng.randint(int(_MINEFIELD_LOSS_RANGE[0]), int(_MINEFIELD_LOSS_RANGE[1]))
    remaining, losses = apply_expedition_ship_losses(ships, loss_pct)
    return {
        "key": "ancient_minefield",
        "loss_pct": int(loss_pct),
        "remaining_ships": remaining,
        "losses": losses,
        "losses_total": int(sum(losses.values())),
    }


def _resolve_event_delay_extra(
    movement_id: int,
    event: Mapping[str, Any],
    flight_seconds: int,
) -> int:
    delay_chance = float(event.get("delay_chance") or 0.0)
    if delay_chance <= 0:
        return 0
    delay_rng = random.Random(int(movement_id) * 9176)
    if delay_rng.random() >= delay_chance:
        return 0
    base = max(1, int(flight_seconds or 60))
    mult_range = event.get("delay_multiplier_range")
    if isinstance(mult_range, (list, tuple)) and len(mult_range) == 2:
        mult = delay_rng.uniform(float(mult_range[0]), float(mult_range[1]))
        return max(1, int(base * mult))
    return base


def resolve_pirate_encounter(
    rng: random.Random,
    ships: Mapping[str, int],
    *,
    expedition_hull_value: int | None = None,
    escort_combat_value: int | None = None,
) -> Dict[str, Any]:
    """Ratio-based pirate skirmish — pirates scale with expo hull risk, fight power from escorts only."""
    expo_risk = max(
        1,
        int(
            expedition_hull_value
            if expedition_hull_value is not None
            else calculate_expedition_hull_value(ships)
        ),
    )
    escort_pts = max(
        0,
        int(
            escort_combat_value
            if escort_combat_value is not None
            else calculate_expedition_escort_value(ships)
        ),
    )
    escort_ratio = escort_pts / max(1, expo_risk)
    escort_eff = _escort_effectiveness(escort_ratio)

    enemy_factor = rng.uniform(_PIRATE_ENEMY_FACTOR_RANGE[0], _PIRATE_ENEMY_FACTOR_RANGE[1])
    pirate_points = max(1, int(expo_risk * enemy_factor))

    if escort_pts > 0:
        fight_points = escort_pts
    else:
        fight_points = max(1, int(expo_risk * _EXPO_ONLY_FIGHT_FACTOR))

    ratio = fight_points / max(1, pirate_points)
    base_win = _pirate_win_chance(ratio)
    win_chance = min(
        _PIRATE_WIN_CHANCE_CLAMP[1],
        base_win + escort_eff * (1.0 - base_win),
    )
    win_chance = max(_PIRATE_WIN_CHANCE_CLAMP[0], win_chance)
    won = rng.random() <= win_chance

    if won:
        lo, hi = _PIRATE_LOSS_CLOSE_RANGE if ratio < 1.0 else _PIRATE_LOSS_WIN_RANGE
    else:
        lo, hi = _PIRATE_LOSS_DEFEAT_RANGE
    loss_pct = rng.randint(int(lo), int(hi))
    if escort_eff > 0 and won:
        loss_pct = max(1, int(loss_pct * (1.0 - escort_eff * 0.35)))

    remaining, losses = apply_expedition_ship_losses(ships, loss_pct)
    return {
        "won": bool(won),
        "pirate_points": int(pirate_points),
        "expedition_hull_value": int(expo_risk),
        "escort_combat_value": int(escort_pts),
        "escort_ratio": float(escort_ratio),
        "escort_effectiveness": float(escort_eff),
        "fleet_points": int(fight_points),
        "ratio": float(ratio),
        "win_chance": float(win_chance),
        "loss_pct": int(loss_pct),
        "remaining_ships": remaining,
        "losses": losses,
        "losses_total": int(sum(losses.values())),
    }


def calculate_expedition_recycler_cargo(ships: Mapping[str, int]) -> int:
    """Cargo capacity of recycle-role hulls still on the expedition fleet."""
    from .fleet_defs import SHIPS, canonical_ship_key

    total = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        if not ship_has_role(str(key), "recycle"):
            continue
        spec = SHIPS.get(canonical_ship_key(str(key))) or {}
        total += int(spec.get("cargo") or 0) * amount
    return max(0, total)


def _virtual_pirate_losses(pirate_points: int, *, won: bool) -> Dict[str, int]:
    """Estimate destroyed pirate hulls for debris when the player wins."""
    if not won:
        return {}
    pts = max(0, int(pirate_points))
    if pts <= 0:
        return {}
    wreck_pts = int(pts * 0.60)
    per_hull = max(1, ship_score_value("falcon_interceptor"))
    count = max(1, wreck_pts // per_hull)
    return {"falcon_interceptor": min(count, 500)}


def _load_debris_into_recycler_cargo(
    debris_metal: int,
    debris_crystal: int,
    cargo_cap: int,
) -> Dict[str, int]:
    from .resources import load_resources_up_to_cargo

    pool = {
        "metal": max(0, int(debris_metal)),
        "crystal": max(0, int(debris_crystal)),
        "fuel_cells": 0,
    }
    return load_resources_up_to_cargo(pool, max(0, int(cargo_cap)))


def resolve_expedition_pirate_debris(
    *,
    remaining_ships: Mapping[str, int],
    ship_losses: Mapping[str, int],
    pirate_combat: Mapping[str, Any],
) -> Dict[str, Any] | None:
    """Ephemeral pirate debris field — recyclers aboard salvage during the same expedition."""
    from .combat import build_combat_debris_metadata, calculate_combat_debris

    player_losses = {str(k): int(v) for k, v in (ship_losses or {}).items() if int(v or 0) > 0}
    pirate_losses = _virtual_pirate_losses(
        int(pirate_combat.get("pirate_points") or 0),
        won=bool(pirate_combat.get("won")),
    )
    if not player_losses and not pirate_losses:
        return None

    metal, crystal = calculate_combat_debris(player_losses, pirate_losses)
    if metal <= 0 and crystal <= 0:
        return None

    recycler_cap = calculate_expedition_recycler_cargo(remaining_ships)
    collected = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    if recycler_cap > 0:
        collected = _load_debris_into_recycler_cargo(metal, crystal, recycler_cap)

    debris_meta = dict(build_combat_debris_metadata(player_losses, pirate_losses) or {})
    debris_meta["expedition_field"] = True
    debris_meta["harvested_metal"] = int(collected.get("metal") or 0)
    debris_meta["harvested_crystal"] = int(collected.get("crystal") or 0)
    return {
        "debris": debris_meta,
        "collected": collected,
        "recycler_cap": recycler_cap,
    }


def resolve_expedition_outcome(
    movement_id: int,
    *,
    cargo_total: int,
    expedition_ship_count: int,
    flight_seconds: int,
    ships: Mapping[str, int] | None = None,
    empire_daily_total: int = 0,
    world_type: str | None = None,
    directive_flags: Mapping[str, Any] | None = None,
    daily_efficiency_mult: float = 1.0,
) -> Dict[str, Any]:
    """Idempotent expedition resolution keyed by movement id."""
    flags = dict(directive_flags or {})
    salvage = str(world_type or "") == "wreckage_field"
    event_bonus = float(flags.get("expedition_event_bonus") or 0.0)
    loot_mult = float(flags.get("expedition_loot_mult") or 1.0)
    wreckage_bonus = float(flags.get("expedition_wreckage_bonus") or 0.0)
    global_event_factor = float(flags.get("expedition_event_factor") or DEFAULT_EVENT_FACTOR)
    expo_value = _expo_value_for_outcome(ships, expedition_ship_count)
    fleet_value = _fleet_value_for_outcome(ships, expedition_ship_count)
    fleet_rating = build_expedition_fleet_rating(ships or {})
    voidrunner_bonus = _voidrunner_discovery_bonus(ships)
    voidrunner_loot_mult = _voidrunner_loot_mult(ships)

    rng = random.Random(int(movement_id) * 7919 + 104729)
    event_key = _pick_event_key(
        rng,
        expedition_ship_count,
        salvage=salvage,
        event_bonus=event_bonus,
        voidrunner_bonus=voidrunner_bonus,
    )
    event = _EVENT_BY_KEY[event_key]
    pirate_combat: Dict[str, Any] | None = None
    hazard: Dict[str, Any] | None = None
    remaining_ships: Dict[str, int] | None = None
    ship_losses: Dict[str, int] = {}
    story_salvaged: Dict[str, int] = {}
    story_tier: str | None = None
    legendary_variant: str | None = None
    delay_extra_preset: int | None = None

    if event_key == "pirate_encounter" and ships:
        pirate_rng = random.Random(int(movement_id) * 31337 + 271828)
        pirate_combat = resolve_pirate_encounter(
            pirate_rng,
            ships,
            expedition_hull_value=int(fleet_rating["expedition_hull_value"]),
            escort_combat_value=int(fleet_rating["escort_combat_value"]),
        )
        remaining_ships = dict(pirate_combat.get("remaining_ships") or {})
        ship_losses = dict(pirate_combat.get("losses") or {})
        if pirate_combat.get("won"):
            salvage_rng = random.Random(int(movement_id) * 42424 + 161803)
            salvaged_ships, salvage_tier = roll_pirate_salvage_rewards(
                salvage_rng,
                pirate_points=int(pirate_combat.get("pirate_points") or 0),
                fleet_points=int(pirate_combat.get("fleet_points") or 0),
            )
            if salvaged_ships:
                remaining_ships = _merge_ship_counts(remaining_ships, salvaged_ships)
                pirate_combat = dict(pirate_combat)
                pirate_combat["salvaged_ships"] = salvaged_ships
                pirate_combat["salvage_tier"] = salvage_tier
            else:
                pirate_combat = dict(pirate_combat)
                pirate_combat["salvage_tier"] = salvage_tier

    if event_key == "ancient_minefield" and ships:
        hazard_rng = random.Random(int(movement_id) * 58258 + 314159)
        hazard = resolve_minefield_hazard(hazard_rng, ships)
        remaining_ships = dict(hazard.get("remaining_ships") or {})
        ship_losses = dict(hazard.get("losses") or {})

    legendary_outcome: Dict[str, Any] | None = None
    if event_key in _LEGENDARY_EVENT_KEYS:
        leg_rng = random.Random(int(movement_id) * 44453 + 133773)
        if event_key == "spatial_rift":
            legendary_outcome = resolve_spatial_rift_legendary(
                leg_rng,
                movement_id=movement_id,
                expo_value=expo_value,
                cargo_total=int(cargo_total),
                flight_seconds=int(flight_seconds or 60),
                event_factor=global_event_factor,
            )
        elif event_key == "time_anomaly":
            legendary_outcome = resolve_time_anomaly_legendary(
                leg_rng,
                movement_id=movement_id,
                expo_value=expo_value,
                cargo_total=int(cargo_total),
                flight_seconds=int(flight_seconds or 60),
                event_factor=global_event_factor,
            )
        elif event_key == "ancient_beacon":
            legendary_outcome = resolve_ancient_beacon_legendary(
                leg_rng,
                movement_id=movement_id,
                expo_value=expo_value,
                cargo_total=int(cargo_total),
                event_factor=global_event_factor,
            )
        story_tier = "legendary"
        legendary_variant = str(legendary_outcome.get("variant") or "")
        delay_extra_preset = int(legendary_outcome.get("delay_extra") or 0)

    if legendary_outcome is not None:
        rewards = dict(legendary_outcome.get("rewards") or _empty_rewards())
        loot_debug = dict(legendary_outcome.get("loot_debug") or {})
        lootboxes = list(legendary_outcome.get("lootboxes") or [])
    else:
        rewards, loot_debug = _compute_event_loot(
            rng,
            event_key,
            expo_value,
            cargo_total=int(cargo_total),
            event_factor=global_event_factor,
            loot_quality_mult=voidrunner_loot_mult,
        )
        lootboxes = _roll_expedition_lootboxes(rng, event_key)
    convoy_mode: str | None = None
    if legendary_outcome is None and event_key == "lost_container":
        box_rng = random.Random(int(movement_id) * 11113 + 77777)
        lootboxes = roll_lost_container_lootboxes(box_rng)
    elif legendary_outcome is None and event_key == "abandoned_convoy":
        lootboxes = []
        convoy_rng = random.Random(int(movement_id) * 22229 + 88888)
        convoy = resolve_abandoned_convoy_treasure(convoy_rng, fleet_value=fleet_value)
        convoy_mode = str(convoy.get("mode") or "resources")
        story_salvaged = dict(convoy.get("salvaged_ships") or {})
        lootboxes = list(convoy.get("lootboxes") or [])
    elif legendary_outcome is None and event_key == "ancient_derelict":
        lootboxes = []
        derelict_rng = random.Random(int(movement_id) * 33347 + 99999)
        derelict = resolve_ancient_derelict_treasure(derelict_rng)
        story_salvaged = dict(derelict.get("salvaged_ships") or {})
        lootboxes = list(derelict.get("lootboxes") or [])
        story_tier = str(derelict.get("story_tier") or "legendary")
    elif legendary_outcome is None and event_key in ("pirate_encounter", "ancient_minefield", "ion_storm"):
        lootboxes = []
    if event_key == "pirate_encounter":
        if not (pirate_combat and pirate_combat.get("won")):
            rewards = _empty_rewards()
            loot_debug = {"expo_value": int(expo_value), "raw_loot_total": 0}
    elif event_key == "abandoned_convoy" and convoy_mode == "ships":
        rewards = _empty_rewards()
        loot_debug = {"expo_value": int(expo_value), "raw_loot_total": 0}
    elif event_key in ("ancient_minefield", "ion_storm"):
        rewards = _empty_rewards()
        loot_debug = {"expo_value": int(expo_value), "raw_loot_total": 0}
    daily_eff = max(EXPEDITION_DAILY_EFFICIENCY_FLOOR, min(1.0, float(daily_efficiency_mult)))
    _scale_resource_rewards(rewards, daily_eff)
    _apply_directive_reward_modifiers(
        rewards,
        loot_mult=loot_mult,
        wreckage_bonus=wreckage_bonus,
        salvage=salvage,
    )
    cargo_meta = _apply_cargo_cap(rewards, int(cargo_total))

    debris_meta: Dict[str, Any] | None = None
    if event_key == "pirate_encounter" and pirate_combat:
        fleet_after = dict(remaining_ships) if remaining_ships else dict(ships or {})
        debris_out = resolve_expedition_pirate_debris(
            remaining_ships=fleet_after,
            ship_losses=ship_losses,
            pirate_combat=pirate_combat,
        )
        if debris_out:
            debris_meta = dict(debris_out.get("debris") or {})
            collected = dict(debris_out.get("collected") or {})
            for key in VALID_RESOURCE_KEYS:
                rewards[key] = int(rewards.get(key) or 0) + int(collected.get(key) or 0)

    if delay_extra_preset is not None:
        delay_extra = int(delay_extra_preset)
    else:
        delay_extra = _resolve_event_delay_extra(movement_id, event, int(flight_seconds or 60))

    reward_total = sum(int(rewards.get(k) or 0) for k in VALID_RESOURCE_KEYS)
    result: Dict[str, Any] = {
        "event_key": event_key,
        "event_label_key": str(event.get("label_key") or event_key),
        "event_desc_key": str(event.get("desc_key") or event_key),
        "severity": str(event.get("severity") or "normal"),
        "rewards": rewards,
        "reward_total": reward_total,
        "lootboxes": lootboxes,
        "delay_extra": delay_extra,
        "expedition_ship_count": int(expedition_ship_count),
        "expo_value": int(expo_value),
        "fleet_value": int(fleet_value),
        "expedition_rating": fleet_rating,
        "empire_daily_total": int(empire_daily_total),
        "daily_efficiency_mult": float(daily_eff),
        "daily_efficiency_pct": int(round(daily_eff * 100)),
        "raw_loot_total": int(cargo_meta.get("raw_loot_total") or loot_debug.get("raw_loot_total") or 0),
        "cargo_total": int(cargo_total),
        "losses": ship_losses,
        "losses_total": int(sum(ship_losses.values())),
    }
    if pirate_combat is not None:
        result["pirate_combat"] = pirate_combat
        result["pirate_won"] = bool(pirate_combat.get("won"))
        salvaged = dict(pirate_combat.get("salvaged_ships") or {})
        if salvaged:
            result["salvaged_ships"] = salvaged
            result["salvaged_total"] = int(sum(salvaged.values()))
    if story_salvaged and ships:
        base = dict(remaining_ships) if remaining_ships is not None else dict(ships)
        remaining_ships = _merge_ship_counts(base, story_salvaged)
        if "salvaged_ships" not in result:
            result["salvaged_ships"] = story_salvaged
            result["salvaged_total"] = int(sum(story_salvaged.values()))
    if convoy_mode:
        result["convoy_mode"] = convoy_mode
    if story_tier:
        result["story_tier"] = story_tier
    if legendary_variant:
        result["legendary_variant"] = legendary_variant
    if remaining_ships is not None:
        result["remaining_ships"] = remaining_ships
    if hazard is not None:
        result["hazard"] = hazard
    if debris_meta:
        result["debris"] = debris_meta
    return result


def build_expedition_report(
    coords: str,
    ships: Mapping[str, int],
    outcome: Mapping[str, Any],
    *,
    locale: str | None = None,
    world_context: Mapping[str, Any] | None = None,
) -> Tuple[str, Dict[str, Any]]:
    from .i18n import fmt_int, tr
    from .fleet_defs import ship_display_name

    def _t(key, default=None, **kw):
        return tr(key, default, locale=locale, **kw)

    event_key = str(outcome.get("event_key") or "void_scan")
    event = _EVENT_BY_KEY.get(event_key) or {}
    label = _t(str(event.get("label_key") or event_key), event_key)
    desc = _t(str(event.get("desc_key") or event_key), "")
    rewards = dict(outcome.get("rewards") or {})
    raw_lootboxes = list(outcome.get("lootboxes") or [])
    lootboxes = [
        _lootbox_display_entry(
            str(box.get("key") or ""),
            int(box.get("amount") or 1),
            locale=locale,
            jackpot=bool(box.get("jackpot")),
        )
        for box in raw_lootboxes
        if str(box.get("key") or "").strip()
    ]
    delay_extra = int(outcome.get("delay_extra") or 0)
    expedition_ships = int(outcome.get("expedition_ship_count") or 0)
    ship_losses = dict(outcome.get("losses") or {})
    losses_total = int(outcome.get("losses_total") or sum(ship_losses.values()))
    salvaged_ships = dict(outcome.get("salvaged_ships") or {})
    salvaged_total = int(outcome.get("salvaged_total") or sum(salvaged_ships.values()))
    remaining_ships = dict(outcome.get("remaining_ships") or ships)
    pirate_combat = dict(outcome.get("pirate_combat") or {}) if outcome.get("pirate_combat") else {}
    hazard = dict(outcome.get("hazard") or {}) if outcome.get("hazard") else {}
    report_fleet = remaining_ships if outcome.get("remaining_ships") is not None else ships
    world = dict(world_context or {}) if world_context else {}
    is_salvage = str(world.get("world_type") or "") == "wreckage_field"

    body_lines: list[str] = []
    if world.get("name_key"):
        world_name = _t(str(world["name_key"]), str(world["name_key"]))
        body_lines.append(
            _t(
                "fleet_world_salvage_report_location" if is_salvage else "fleet_world_expedition_report_location",
                "Location: %(world)s",
                world=world_name,
            )
        )
        if world.get("risk_key"):
            body_lines.append(
                _t(
                    "fleet_world_expedition_report_risk",
                    "Risk: %(risk)s",
                    risk=_t(str(world["risk_key"]), ""),
                )
            )
    else:
        body_lines.append(
            _t("fleet_expedition_report_coords", "Coordinates: %(coords)s", coords=coords)
        )

    body_lines.append(
        _t(
            "fleet_world_salvage_report_find" if is_salvage else "fleet_expedition_report_event",
            "Find: %(event)s" if is_salvage else "Event: %(event)s",
            event=label,
        )
    )
    if desc:
        body_lines.append(desc)

    if pirate_combat:
        pirate_pts = int(pirate_combat.get("pirate_points") or 0)
        body_lines.append(
            _t(
                "fleet_expedition_report_pirate_strength",
                "Pirate strength: %(points)s",
                points=fmt_int(pirate_pts),
            )
        )
        outcome_key = (
            "fleet_expedition_report_pirate_outcome_win"
            if pirate_combat.get("won")
            else "fleet_expedition_report_pirate_outcome_loss"
        )
        body_lines.append(
            _t(
                outcome_key,
                "Outcome: victory" if pirate_combat.get("won") else "Outcome: retreat under fire",
            )
        )
        if losses_total > 0:
            body_lines.append(
                _t(
                    "fleet_expedition_report_pirate_loss_rate",
                    "Ship losses: %(pct)s%%",
                    pct=fmt_int(int(pirate_combat.get("loss_pct") or 0)),
                )
            )

    debris = dict(outcome.get("debris") or {}) if outcome.get("debris") else {}
    if debris:
        body_lines.append(_t("fleet_expedition_report_section_debris", "Debris field"))
        h_m = int(debris.get("harvested_metal") or 0)
        h_c = int(debris.get("harvested_crystal") or 0)
        if h_m or h_c:
            if h_m:
                body_lines.append(
                    _t(
                        "fleet_expedition_report_debris_collected_line",
                        "Salvaged: +%(amount)s %(resource)s",
                        amount=fmt_int(h_m),
                        resource=_t("resource_metal", "Ferronit"),
                    )
                )
            if h_c:
                body_lines.append(
                    _t(
                        "fleet_expedition_report_debris_collected_line",
                        "Salvaged: +%(amount)s %(resource)s",
                        amount=fmt_int(h_c),
                        resource=_t("resource_crystal", "Crytite"),
                    )
                )
        else:
            body_lines.append(
                _t(
                    "expedition_report_debris_uncollected",
                    "Debris field created — no reclaimer aboard to salvage.",
                )
            )

    if event_key == "ancient_minefield" and losses_total > 0:
        loss_pct = int(hazard.get("loss_pct") or 0)
        if loss_pct > 0:
            body_lines.append(
                _t(
                    "fleet_expedition_report_minefield_loss_rate",
                    "Minefield damage: %(pct)s%% ship losses",
                    pct=fmt_int(loss_pct),
                )
            )

    if event_key == "ion_storm" and delay_extra > 0:
        body_lines.append(
            _t(
                "fleet_expedition_report_ion_storm_delay",
                "Return delayed by %(seconds)s s due to ion storm.",
                seconds=fmt_int(delay_extra),
            )
        )

    legendary_variant = str(outcome.get("legendary_variant") or "")
    if event_key == "spatial_rift" and legendary_variant:
        if legendary_variant == "amplified":
            body_lines.append(
                _t(
                    "fleet_expedition_report_spatial_rift_amplified",
                    "Spatial distortion amplified the recovered cargo beyond normal limits.",
                )
            )
        elif legendary_variant == "delayed":
            body_lines.append(
                _t(
                    "fleet_expedition_report_spatial_rift_delayed",
                    "The rift collapsed behind the fleet — return delayed by %(seconds)s s.",
                    seconds=fmt_int(delay_extra),
                )
            )
    elif event_key == "time_anomaly" and legendary_variant:
        if legendary_variant == "dilated":
            body_lines.append(
                _t(
                    "fleet_expedition_report_time_anomaly_dilated",
                    "Time dilation stretched the expedition — return delayed by %(seconds)s s.",
                    seconds=fmt_int(delay_extra),
                )
            )
        elif legendary_variant == "compressed":
            body_lines.append(
                _t(
                    "fleet_expedition_report_time_anomaly_compressed",
                    "Chrono compression registered on sensors — no measurable return gain in this phase.",
                )
            )
    elif event_key == "ancient_beacon" and legendary_variant:
        body_lines.append(
            _t(
                "fleet_expedition_report_ancient_beacon",
                "The beacon unlocked a sealed cache from a forgotten age.",
            )
        )

    reward_lines: list[str] = []
    if int(rewards.get("metal") or 0):
        reward_lines.append(
            _t(
                "fleet_world_expedition_report_loot_line",
                "+ %(amount)s %(resource)s",
                amount=fmt_int(rewards["metal"]),
                resource=_t("resource_metal", "Ferronit"),
            )
        )
    if int(rewards.get("crystal") or 0):
        reward_lines.append(
            _t(
                "fleet_world_expedition_report_loot_line",
                "+ %(amount)s %(resource)s",
                amount=fmt_int(rewards["crystal"]),
                resource=_t("resource_crystal", "Crytite"),
            )
        )
    if int(rewards.get("fuel_cells") or 0):
        reward_lines.append(
            _t(
                "fleet_world_expedition_report_loot_line",
                "+ %(amount)s %(resource)s",
                amount=fmt_int(rewards["fuel_cells"]),
                resource=_t("resource_fuel_cells", "Fuel Cells"),
            )
        )
    if reward_lines:
        body_lines.append(
            _t(
                "fleet_world_salvage_report_section_loot" if is_salvage else "fleet_world_expedition_report_section_loot",
                "Salvage",
            )
        )
        body_lines.extend(reward_lines)
    elif delay_extra:
        body_lines.append(
            _t(
                "fleet_expedition_report_delay_only",
                "Return flight extended by %(seconds)s s due to navigation interference.",
                seconds=fmt_int(delay_extra),
            )
        )
    elif not lootboxes:
        body_lines.append(
            _t(
                "fleet_world_salvage_report_loot_none" if is_salvage else "fleet_world_expedition_report_loot_none",
                "Salvage: none",
            )
        )

    if lootboxes:
        body_lines.append(_t("fleet_expedition_report_section_lootboxes", "Lootboxes"))
        for box in lootboxes:
            body_lines.append(
                _t(
                    "fleet_expedition_report_lootbox_line",
                    "+ %(amount)s× %(name)s",
                    amount=fmt_int(box.get("amount") or 1),
                    name=str(box.get("name") or box.get("key") or ""),
                )
            )

    if losses_total > 0:
        body_lines.append(_t("fleet_expedition_report_section_losses", "Ship losses"))
        for ship_key, qty in sorted(ship_losses.items()):
            if int(qty or 0) <= 0:
                continue
            ship_name = ship_display_name(str(ship_key), locale=locale)
            body_lines.append(
                _t(
                    "fleet_expedition_report_loss_line",
                    "− %(amount)s %(ship)s",
                    amount=fmt_int(qty),
                    ship=ship_name,
                )
            )
    elif not pirate_combat and not hazard:
        body_lines.append(
            _t("fleet_world_expedition_report_losses_none", "Losses: none")
        )

    if salvaged_total > 0:
        body_lines.append(_t("fleet_expedition_report_section_salvaged", "Salvaged ships"))
        for ship_key, qty in sorted(salvaged_ships.items()):
            if int(qty or 0) <= 0:
                continue
            ship_name = ship_display_name(str(ship_key), locale=locale)
            body_lines.append(
                _t(
                    "fleet_expedition_report_salvaged_line",
                    "+ %(amount)s %(ship)s",
                    amount=fmt_int(qty),
                    ship=ship_name,
                )
            )

    if delay_extra and reward_lines:
        body_lines.append(
            _t(
                "fleet_expedition_report_delay",
                "Return delay: +%(seconds)s s",
                seconds=fmt_int(delay_extra),
            )
        )

    metadata: Dict[str, Any] = {
        "report_version": EXPEDITION_REPORT_VERSION,
        "target_coords": coords,
        "event_key": event_key,
        "event_label_key": str(event.get("label_key") or event_key),
        "event_desc_key": str(event.get("desc_key") or event_key),
        "event_severity": str(outcome.get("severity") or "normal"),
        "expedition_ships": expedition_ships,
        "fleet_ships": {str(k): int(v) for k, v in report_fleet.items() if int(v or 0) > 0},
        "original_fleet_ships": {str(k): int(v) for k, v in ships.items() if int(v or 0) > 0},
        "rewards": rewards,
        "lootboxes": lootboxes,
        "delay_extra": delay_extra,
        "cargo_total": int(outcome.get("cargo_total") or 0),
        "empire_daily_total": int(outcome.get("empire_daily_total") or 0),
        "expo_value": int(outcome.get("expo_value") or 0),
        "raw_loot_total": int(outcome.get("raw_loot_total") or 0),
        "losses": {str(k): int(v) for k, v in ship_losses.items() if int(v or 0) > 0},
        "losses_total": losses_total,
        "salvaged_ships": {str(k): int(v) for k, v in salvaged_ships.items() if int(v or 0) > 0},
        "salvaged_total": salvaged_total,
    }
    if outcome.get("story_tier"):
        metadata["story_tier"] = str(outcome.get("story_tier"))
    if outcome.get("legendary_variant"):
        metadata["legendary_variant"] = str(outcome.get("legendary_variant"))
    if outcome.get("convoy_mode"):
        metadata["convoy_mode"] = str(outcome.get("convoy_mode"))
    if remaining_ships and (ship_losses or salvaged_ships):
        metadata["remaining_ships"] = {
            str(k): int(v) for k, v in remaining_ships.items() if int(v or 0) > 0
        }
    if pirate_combat:
        metadata["pirate_combat"] = {
            "won": bool(pirate_combat.get("won")),
            "pirate_points": int(pirate_combat.get("pirate_points") or 0),
            "fleet_points": int(pirate_combat.get("fleet_points") or 0),
            "expedition_hull_value": int(pirate_combat.get("expedition_hull_value") or 0),
            "escort_combat_value": int(pirate_combat.get("escort_combat_value") or 0),
            "escort_ratio": float(pirate_combat.get("escort_ratio") or 0),
            "escort_effectiveness": float(pirate_combat.get("escort_effectiveness") or 0),
            "ratio": float(pirate_combat.get("ratio") or 0),
            "win_chance": float(pirate_combat.get("win_chance") or 0),
            "loss_pct": int(pirate_combat.get("loss_pct") or 0),
            "salvage_tier": str(pirate_combat.get("salvage_tier") or "none"),
        }
        metadata["pirate_won"] = bool(pirate_combat.get("won"))
    rating = dict(outcome.get("expedition_rating") or {})
    if rating:
        metadata["expedition_rating"] = rating
        metadata["voidrunner_bonus_active"] = bool(rating.get("voidrunner_bonus_active"))
        if rating.get("voidrunner_bonus_active"):
            metadata["voidrunner_bonus_pct"] = int(rating.get("voidrunner_bonus_pct") or 0)
    if hazard:
        metadata["hazard"] = {
            "key": str(hazard.get("key") or event_key),
            "loss_pct": int(hazard.get("loss_pct") or 0),
        }
    if debris:
        metadata["debris"] = debris
    if world.get("world_key"):
        metadata.update(
            {
                "report_kind": "world_salvage" if is_salvage else "world_expedition",
                "world_key": str(world["world_key"]),
                "world_name_key": str(world.get("name_key") or ""),
                "world_type": str(world.get("world_type") or ""),
                "world_type_key": str(world.get("type_key") or ""),
                "world_risk_key": str(world.get("risk_key") or ""),
                "world_risk_level": str(world.get("risk_level") or "low"),
                "world_role_icon": str(world.get("role_icon") or ""),
            }
        )
    return "\n".join(body_lines), metadata
