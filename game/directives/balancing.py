"""Imperial Directives target balancing — hard caps + production-aware scaling (GC-915)."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .definitions import (
    CADENCE_DAILY,
    CADENCE_WEEKLY,
    OBJECTIVE_ACCUMULATE,
    OBJECTIVE_COUNT,
    RARITY_TARGET_MULTIPLIER,
    effective_base_target,
)
from .scaling import SCORE_ANCHOR, SCORE_FLOOR, scale_profile_config

# (daily_max, weekly_max) — 0 means profile-only cap
DIRECTIVE_TARGET_CAPS: Dict[str, Tuple[int, int]] = {
    "upgrade_buildings": (10, 25),
    "upgrade_storages": (10, 20),
    "upgrade_solar_plants": (10, 20),
    "upgrade_fuel_plants": (10, 20),
    "launch_expeditions": (10, 30),
    "complete_expeditions": (10, 35),
    "send_fleet_missions": (50, 120),
    "recycle_debris": (5, 15),
    "start_research": (2, 5),
    "complete_research": (3, 8),
    "upgrade_mining_tech": (2, 4),
    "upgrade_energy_tech": (2, 4),
    "upgrade_navigation_tech": (2, 4),
    "win_battles": (3, 8),
    "defeat_pirates": (3, 8),
    "destroy_enemy_defense": (30, 80),
    "build_defense": (40, 100),
    "build_combat_ships": (30, 80),
    "build_ships": (50, 150),
    "destroy_enemy_ships": (50, 150),
    "trigger_expedition_events": (5, 15),
    "find_rare_loot": (3, 8),
    "recover_ancient_technology": (2, 5),
    "salvage_ancient_ships": (2, 5),
}

COUNT_TIER_SNAP: Dict[str, Sequence[int]] = {
    "launch_expeditions": (3, 5, 10),
    "complete_expeditions": (3, 5, 10),
    "send_fleet_missions": (10, 20, 30, 40, 50),
    "upgrade_buildings": (3, 5, 8, 10),
    "upgrade_storages": (3, 5, 8, 10),
    "upgrade_solar_plants": (3, 5, 8, 10),
    "upgrade_fuel_plants": (3, 5, 8, 10),
    "start_research": (1, 2),
    "complete_research": (1, 2, 3),
    "win_battles": (1, 2, 3),
    "defeat_pirates": (1, 2, 3),
    "recycle_debris": (2, 3, 5),
    "find_rare_loot": (1, 2, 3),
    "trigger_expedition_events": (2, 3, 5),
}

# Daily production share by rarity (produce / spend accumulate objectives)
PRODUCE_DAILY_PCT: Dict[str, float] = {
    "common": 0.02,
    "rare": 0.035,
    "epic": 0.055,
    "legendary": 0.08,
}

WEEKLY_PRODUCE_MULTIPLIER = 5.0
STARTER_DAILY_PRODUCTION = 12_000
PRODUCE_ABSOLUTE_DAILY_CAP = 25_000_000
PRODUCE_ABSOLUTE_WEEKLY_CAP = 120_000_000


def directive_hard_cap(definition_key: str, *, cadence: str) -> Optional[int]:
    caps = DIRECTIVE_TARGET_CAPS.get(str(definition_key or "").strip())
    if not caps:
        return None
    daily_max, weekly_max = caps
    if str(cadence or CADENCE_DAILY).strip().lower() == CADENCE_WEEKLY:
        return weekly_max if weekly_max > 0 else None
    return daily_max if daily_max > 0 else None


def _resolve_score(context: Mapping[str, Any] | None) -> int:
    if not context:
        return SCORE_FLOOR
    raw = context.get("total_score")
    if raw is None:
        raw = context.get("total")
    return max(SCORE_FLOOR, int(raw or 0))


def _daily_resource_production(context: Mapping[str, Any] | None, resource_key: str) -> int:
    if not context:
        return STARTER_DAILY_PRODUCTION
    daily = context.get("daily_production")
    if isinstance(daily, Mapping):
        val = int(daily.get(resource_key) or daily.get(str(resource_key)) or 0)
        if val > 0:
            return val
        total = int(daily.get("total") or 0)
        if total > 0 and resource_key == "combined":
            return total
    return STARTER_DAILY_PRODUCTION


def _snap_to_tier(raw: int, tiers: Sequence[int]) -> int:
    if not tiers:
        return max(1, raw)
    best = tiers[0]
    for tier in tiers:
        if raw >= tier:
            best = tier
        else:
            break
    return max(1, int(best))


def _score_tier_index(score: int, tier_count: int) -> int:
    if tier_count <= 1:
        return 0
    ratio = max(1.0, float(score)) / float(SCORE_ANCHOR)
    idx = int(math.floor(math.log(max(1.0, ratio), 2.5)))
    return max(0, min(tier_count - 1, idx))


def _count_target_from_tiers(
    definition_key: str,
    *,
    score: int,
    cadence: str,
    rarity: str,
) -> int:
    tiers = list(COUNT_TIER_SNAP.get(definition_key) or (1, 2, 3))
    idx = _score_tier_index(score, len(tiers))
    rarity_boost = {"common": 0, "rare": 0, "epic": 1, "legendary": 1}.get(
        str(rarity or "common").strip().lower(),
        0,
    )
    idx = min(len(tiers) - 1, idx + rarity_boost)
    target = tiers[idx]
    if str(cadence or CADENCE_DAILY).strip().lower() == CADENCE_WEEKLY:
        target = min(tiers[-1] * 2, max(tiers) + 2 + idx)
    return max(1, int(target))


def _scaled_count_target(
    base: int,
    score: int,
    *,
    scale_profile: str,
    cadence: str,
) -> int:
    cfg = scale_profile_config(scale_profile)
    exponent = float(cfg.get("exponent") or 0.25)
    ratio = max(float(SCORE_FLOOR), float(score)) / float(SCORE_ANCHOR)
    scaled = float(max(1, base)) * math.pow(ratio, exponent)
    if str(cadence or CADENCE_DAILY).strip().lower() == CADENCE_WEEKLY:
        scaled *= float(cfg.get("weekly_multiplier") or 3.5)
    result = max(1, int(math.floor(scaled)))
    max_target = int(cfg.get("max_target") or 0)
    if max_target > 0:
        result = min(max_target, result)
    return result


def _produce_target(
    *,
    resource_key: str,
    rarity: str,
    cadence: str,
    context: Mapping[str, Any] | None,
) -> int:
    daily = _daily_resource_production(context, resource_key)
    pct = float(PRODUCE_DAILY_PCT.get(str(rarity or "common").strip().lower(), 0.02))
    target = int(math.floor(float(daily) * pct))
    if str(cadence or CADENCE_DAILY).strip().lower() == CADENCE_WEEKLY:
        target = int(math.floor(float(target) * WEEKLY_PRODUCE_MULTIPLIER))
        cap = PRODUCE_ABSOLUTE_WEEKLY_CAP
    else:
        cap = PRODUCE_ABSOLUTE_DAILY_CAP
    score = _resolve_score(context)
    if score < SCORE_ANCHOR:
        target = max(target, int(STARTER_DAILY_PRODUCTION * pct))
    return max(500, min(cap, target))


def _ships_target(
    base: int,
    score: int,
    *,
    cadence: str,
    rarity: str,
) -> int:
    mult = float(RARITY_TARGET_MULTIPLIER.get(str(rarity or "common").strip().lower(), 1.0))
    ratio = max(1.0, float(score) / float(SCORE_ANCHOR))
    scaled = float(max(1, base)) * mult * math.pow(ratio, 0.28)
    if str(cadence or CADENCE_DAILY).strip().lower() == CADENCE_WEEKLY:
        scaled *= 3.5
    result = max(2, int(math.floor(scaled)))
    return min(80 if cadence == CADENCE_DAILY else 150, result)


def compute_directive_target(
    definition: Mapping[str, Any],
    *,
    rarity: str,
    cadence: str,
    context: Mapping[str, Any] | None = None,
) -> int:
    """Compute a player-facing directive target with hard limits."""
    key = str(definition.get("key") or "").strip()
    kind = str(definition.get("objective_kind") or OBJECTIVE_COUNT).strip().lower()
    profile = str(definition.get("scale_profile") or "count_light").strip()
    score = _resolve_score(context)
    cadence_norm = str(cadence or CADENCE_DAILY).strip().lower()

    if kind == OBJECTIVE_ACCUMULATE or profile == "produce":
        filters = definition.get("filters") if isinstance(definition.get("filters"), dict) else {}
        resource = str(filters.get("resource") or "combined").strip().lower()
        if resource in ("", "any", "all"):
            resource = "combined"
        target = _produce_target(resource_key=resource, rarity=rarity, cadence=cadence_norm, context=context)
    elif key in COUNT_TIER_SNAP:
        target = _count_target_from_tiers(key, score=score, cadence=cadence_norm, rarity=rarity)
    elif key in ("build_ships", "build_combat_ships", "build_defense", "destroy_enemy_ships", "destroy_enemy_defense"):
        base = effective_base_target(definition, rarity)
        target = _ships_target(base, score, cadence=cadence_norm, rarity=rarity)
    else:
        base = effective_base_target(definition, rarity)
        target = _scaled_count_target(
            base,
            score,
            scale_profile=profile,
            cadence=cadence_norm,
        )
        if key in COUNT_TIER_SNAP:
            target = _snap_to_tier(target, COUNT_TIER_SNAP[key])

    hard = directive_hard_cap(key, cadence=cadence_norm)
    if hard is not None and hard > 0:
        target = min(target, hard)

    cfg = scale_profile_config(profile)
    profile_max = int(cfg.get("max_target") or 0)
    if profile_max > 0:
        target = min(target, profile_max)

    return max(1, int(target))


def is_directive_target_stale(
    definition_key: str,
    target_value: int,
    *,
    cadence: str,
) -> bool:
    """True when an existing row exceeds post-balancing hard caps."""
    hard = directive_hard_cap(definition_key, cadence=cadence)
    if hard is not None and hard > 0 and int(target_value) > hard:
        return True
    if int(target_value) > PRODUCE_ABSOLUTE_WEEKLY_CAP:
        return True
    return False
