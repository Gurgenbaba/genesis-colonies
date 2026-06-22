"""Deterministic expedition event engine — loot, delays, structured reports."""

from __future__ import annotations

import math
import random
from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple

from .fleet_defs import SHIPS, VALID_RESOURCE_KEYS, ship_score_value

EXPEDITION_REPORT_VERSION = 2

# Expedition loot uses expedition-hull cargo × multiplier (not transport cargo semantics).
EXPEDITION_LOOT_CARGO_MULTIPLIER = 50

# fleet_value^exponent × factor — dampened; economy floor scales endgame finds.
FLEET_LOOT_EXPONENT = 0.72
EXPEDITION_LOOT_FACTOR = 12
_LOOT_VARIANCE_RANGE = (0.75, 1.35)

# Cargo sent on expedition implies economic scale — floor when empire aggregate lags display.
CARGO_ECONOMY_REFERENCE_MULT = 10

# Rare cargo jackpot when raw loot exceeds cap (deterministic per movement_id).
_CARGO_JACKPOT_CHANCE = 0.05
_CARGO_JACKPOT_MULTS: Sequence[int] = (2, 5, 10)

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
}

# Rare additive lootbox drops (resources unchanged). Chance = roll < value.
_EXPEDITION_LOOTBOX_DROPS: Dict[str, Dict[str, Any]] = {
    "void_scan": {"chance": 0.01, "boxes": ("research_capsule",)},
    "mineral_deposit": {"chance": 0.02, "boxes": ("generic_supply_container", "resource_cache")},
    "fuel_cache": {"chance": 0.02, "boxes": ("generic_supply_container", "resource_cache")},
    "debris_salvage": {"chance": 0.05, "boxes": ("wreckage_container", "military_cache")},
    "distress_beacon": {"chance": 0.06, "boxes": ("alien_cache", "military_cache")},
    "ancient_stash": {"chance": 0.20, "boxes": ("alien_cache", "premium_cache", "research_capsule")},
    "sensor_glitch": {"chance": 0.0, "boxes": ()},
    "nav_interference": {"chance": 0.0, "boxes": ()},
    "pirate_encounter": {"chance": 0.0, "boxes": ()},
    "ion_storm": {"chance": 0.0, "boxes": ()},
    "ancient_minefield": {"chance": 0.0, "boxes": ()},
    "lost_container": {"chance": 0.0, "boxes": ()},
    "abandoned_convoy": {"chance": 0.0, "boxes": ()},
    "ancient_derelict": {"chance": 0.0, "boxes": ()},
}

# Hazard events — non-combat risk (GC-620I-A).
_ION_STORM_DELAY_MULT_RANGE = (0.20, 0.60)
_MINEFIELD_LOSS_RANGE = (2, 12)

# Pirate encounter — lightweight ratio combat (no combat.py resolver).
_PIRATE_ENEMY_FACTOR_RANGE = (0.70, 1.25)
_PIRATE_WIN_CHANCE_BASE = 0.18
_PIRATE_WIN_CHANCE_SCALE = 0.70
_PIRATE_WIN_CHANCE_CLAMP = (0.10, 0.90)
_PIRATE_LOSS_WIN_RANGE = (3, 18)
_PIRATE_LOSS_CLOSE_RANGE = (8, 28)
_PIRATE_LOSS_DEFEAT_RANGE = (18, 45)

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
        "weight": 10,
        "label_key": "expedition_event_void_scan",
        "desc_key": "expedition_event_void_scan_desc",
        "severity": "minor",
        "rewards": {},
    },
    {
        "key": "mineral_deposit",
        "weight": 32,
        "label_key": "expedition_event_mineral_deposit",
        "desc_key": "expedition_event_mineral_deposit_desc",
        "severity": "normal",
    },
    {
        "key": "fuel_cache",
        "weight": 16,
        "label_key": "expedition_event_fuel_cache",
        "desc_key": "expedition_event_fuel_cache_desc",
        "severity": "normal",
    },
    {
        "key": "debris_salvage",
        "weight": 12,
        "label_key": "expedition_event_debris_salvage",
        "desc_key": "expedition_event_debris_salvage_desc",
        "severity": "minor",
    },
    {
        "key": "nav_interference",
        "weight": 10,
        "label_key": "expedition_event_nav_interference",
        "desc_key": "expedition_event_nav_interference_desc",
        "severity": "minor",
        "rewards": {},
        "delay_chance": 1.0,
    },
    {
        "key": "distress_beacon",
        "weight": 9,
        "label_key": "expedition_event_distress_beacon",
        "desc_key": "expedition_event_distress_beacon_desc",
        "severity": "normal",
        "delay_chance": 0.25,
    },
    {
        "key": "sensor_glitch",
        "weight": 6,
        "label_key": "expedition_event_sensor_glitch",
        "desc_key": "expedition_event_sensor_glitch_desc",
        "severity": "minor",
        "rewards": {},
    },
    {
        "key": "ancient_stash",
        "weight": 8,
        "label_key": "expedition_event_ancient_stash",
        "desc_key": "expedition_event_ancient_stash_desc",
        "severity": "major",
    },
    {
        "key": "pirate_encounter",
        "weight": 6,
        "label_key": "expedition_event_pirate_encounter",
        "desc_key": "expedition_event_pirate_encounter_desc",
        "severity": "major",
    },
    {
        "key": "ion_storm",
        "weight": 4,
        "label_key": "expedition_event_ion_storm",
        "desc_key": "expedition_event_ion_storm_desc",
        "severity": "minor",
        "rewards": {},
        "delay_chance": 1.0,
        "delay_multiplier_range": _ION_STORM_DELAY_MULT_RANGE,
    },
    {
        "key": "ancient_minefield",
        "weight": 4,
        "label_key": "expedition_event_ancient_minefield",
        "desc_key": "expedition_event_ancient_minefield_desc",
        "severity": "major",
        "rewards": {},
    },
    {
        "key": "lost_container",
        "weight": 4,
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
)

_EVENT_BY_KEY: Dict[str, Dict[str, Any]] = {str(e["key"]): e for e in _EXPEDITION_EVENTS}

_SALVAGE_EVENT_KEYS: frozenset[str] = frozenset(
    {"debris_salvage", "mineral_deposit", "fuel_cache", "distress_beacon"}
)


def expedition_event_keys() -> frozenset[str]:
    return frozenset(_EVENT_BY_KEY.keys())


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


def _fleet_value_for_outcome(
    ships: Mapping[str, int] | None,
    expedition_ship_count: int,
) -> int:
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
        spec = SHIPS.get(str(key)) or {}
        if spec.get("role") == "expedition":
            total += amount
    return total


def calculate_expedition_loot_cap(ships: Mapping[str, int]) -> int:
    """Loot cap from expedition hull cargo × multiplier (combat escorts don't inflate loot)."""
    expedition_cargo = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        spec = SHIPS.get(str(key)) or {}
        if spec.get("role") != "expedition":
            continue
        expedition_cargo += int(spec.get("cargo") or 0) * amount
    if expedition_cargo <= 0:
        for key, qty in ships.items():
            amount = int(qty or 0)
            if amount <= 0:
                continue
            spec = SHIPS.get(str(key)) or {}
            expedition_cargo += int(spec.get("cargo") or 0) * amount
    return max(0, expedition_cargo * EXPEDITION_LOOT_CARGO_MULTIPLIER)


def _pick_event_key(
    rng: random.Random,
    expedition_ship_count: int,
    *,
    salvage: bool = False,
    event_bonus: float = 0.0,
) -> str:
    """Pick event; extra expedition hulls shift weight away from empty outcomes."""
    bonus = min(0.12, max(0, int(expedition_ship_count)) * 0.03) + max(0.0, float(event_bonus))
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
            weight = weight * (1.0 + bonus)
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
    fleet_value: int,
    *,
    empire_daily_total: int = 0,
    cargo_total: int = 0,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    profile = _EVENT_LOOT_PROFILES.get(str(event_key))
    if not profile or fleet_value <= 0 and int(empire_daily_total) <= 0 and int(cargo_total) <= 0:
        return _empty_rewards(), {"economy_base": 0, "raw_loot_total": 0}

    mult_lo, mult_hi = profile["mult_range"]
    event_mult = rng.uniform(float(mult_lo), float(mult_hi))
    variance = rng.uniform(_LOOT_VARIANCE_RANGE[0], _LOOT_VARIANCE_RANGE[1])

    fleet_loot = 0
    if fleet_value > 0:
        fleet_score = math.pow(max(0, int(fleet_value)), FLEET_LOOT_EXPONENT)
        fleet_loot = max(0, int(fleet_score * EXPEDITION_LOOT_FACTOR * event_mult * variance))

    economy_loot = 0
    eco_range = profile.get("economy_day_range")
    daily_total = max(0, int(empire_daily_total))
    cargo_reference = max(0, int(cargo_total)) * CARGO_ECONOMY_REFERENCE_MULT
    economy_base = max(daily_total, cargo_reference)
    if economy_base > 0 and isinstance(eco_range, (list, tuple)) and len(eco_range) == 2:
        eco_mult = rng.uniform(float(eco_range[0]), float(eco_range[1]))
        economy_loot = max(0, int(economy_base * eco_mult * variance))

    total_loot = max(fleet_loot, economy_loot)
    debug = {
        "economy_base": int(economy_base),
        "raw_loot_total": int(total_loot),
        "fleet_loot": int(fleet_loot),
        "economy_loot": int(economy_loot),
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


def _apply_cargo_cap_with_jackpot(
    rewards: MutableMapping[str, int],
    cargo_total: int,
    *,
    movement_id: int,
) -> Dict[str, Any]:
    """Cap loot to cargo; 5% jackpot allows 2×/5×/10× cargo when raw loot overshoots."""
    cargo_cap = max(0, int(cargo_total))
    loaded = sum(int(rewards.get(k) or 0) for k in VALID_RESOURCE_KEYS)
    meta: Dict[str, Any] = {
        "cargo_jackpot": False,
        "cargo_jackpot_mult": 1,
        "raw_loot_total": int(loaded),
    }
    if cargo_cap <= 0 or loaded <= cargo_cap:
        return meta

    jackpot_rng = random.Random(int(movement_id) * 12347 + 99991)
    if jackpot_rng.random() < _CARGO_JACKPOT_CHANCE:
        mult = int(_CARGO_JACKPOT_MULTS[jackpot_rng.randrange(len(_CARGO_JACKPOT_MULTS))])
        jackpot_cap = int(cargo_cap * mult)
        if loaded > jackpot_cap:
            scale = jackpot_cap / max(1, loaded)
            for key in VALID_RESOURCE_KEYS:
                rewards[key] = int(int(rewards.get(key) or 0) * scale)
        meta["cargo_jackpot"] = True
        meta["cargo_jackpot_mult"] = mult
        return meta

    _scale_rewards_to_cargo(rewards, cargo_cap)
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


def apply_expedition_ship_losses(
    ships: Mapping[str, int],
    loss_pct: int,
    *,
    min_remaining: int = 1,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Apply proportional hull losses; never drop below ``min_remaining`` total ships."""
    loss_pct = max(0, min(100, int(loss_pct)))
    cleaned = {str(k): int(v) for k, v in (ships or {}).items() if int(v or 0) > 0}
    if loss_pct <= 0 or not cleaned:
        return cleaned, {}

    total = sum(cleaned.values())
    if total <= max(1, int(min_remaining)):
        return cleaned, {}

    loss_rate = loss_pct / 100.0
    remaining: Dict[str, int] = {}
    losses: Dict[str, int] = {}
    for key, amount in cleaned.items():
        lost_count = min(amount, max(0, int(math.floor(amount * loss_rate))))
        rem = amount - lost_count
        if lost_count > 0:
            losses[key] = lost_count
        if rem > 0:
            remaining[key] = rem

    rem_total = sum(remaining.values())
    floor = max(1, int(min_remaining))
    if rem_total < floor:
        need = floor - rem_total
        for key in sorted(losses.keys(), key=lambda k: losses[k], reverse=True):
            if need <= 0:
                break
            restore = min(need, losses[key])
            losses[key] -= restore
            if losses[key] <= 0:
                losses.pop(key, None)
            remaining[key] = remaining.get(key, 0) + restore
            need -= restore

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
    fleet_value: int,
) -> Dict[str, Any]:
    """Ratio-based pirate skirmish — no combat.py resolver; expedition fleet never wiped."""
    fleet_points = max(1, int(fleet_value))
    enemy_factor = rng.uniform(_PIRATE_ENEMY_FACTOR_RANGE[0], _PIRATE_ENEMY_FACTOR_RANGE[1])
    pirate_points = max(1, int(fleet_points * enemy_factor))
    ratio = fleet_points / max(1, pirate_points)
    win_chance = _pirate_win_chance(ratio)
    won = rng.random() <= win_chance

    if won:
        lo, hi = _PIRATE_LOSS_CLOSE_RANGE if ratio < 1.0 else _PIRATE_LOSS_WIN_RANGE
    else:
        lo, hi = _PIRATE_LOSS_DEFEAT_RANGE
    loss_pct = rng.randint(int(lo), int(hi))

    remaining, losses = apply_expedition_ship_losses(ships, loss_pct)
    return {
        "won": bool(won),
        "pirate_points": int(pirate_points),
        "fleet_points": int(fleet_points),
        "ratio": float(ratio),
        "win_chance": float(win_chance),
        "loss_pct": int(loss_pct),
        "remaining_ships": remaining,
        "losses": losses,
        "losses_total": int(sum(losses.values())),
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
) -> Dict[str, Any]:
    """Idempotent expedition resolution keyed by movement id."""
    flags = dict(directive_flags or {})
    salvage = str(world_type or "") == "wreckage_field"
    event_bonus = float(flags.get("expedition_event_bonus") or 0.0)
    loot_mult = float(flags.get("expedition_loot_mult") or 1.0)
    wreckage_bonus = float(flags.get("expedition_wreckage_bonus") or 0.0)
    fleet_value = _fleet_value_for_outcome(ships, expedition_ship_count)

    rng = random.Random(int(movement_id) * 7919 + 104729)
    event_key = _pick_event_key(
        rng,
        expedition_ship_count,
        salvage=salvage,
        event_bonus=event_bonus,
    )
    event = _EVENT_BY_KEY[event_key]
    pirate_combat: Dict[str, Any] | None = None
    hazard: Dict[str, Any] | None = None
    remaining_ships: Dict[str, int] | None = None
    ship_losses: Dict[str, int] = {}
    story_salvaged: Dict[str, int] = {}
    story_tier: str | None = None

    if event_key == "pirate_encounter" and ships:
        pirate_rng = random.Random(int(movement_id) * 31337 + 271828)
        pirate_combat = resolve_pirate_encounter(pirate_rng, ships, fleet_value)
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

    rewards, loot_debug = _compute_event_loot(
        rng,
        event_key,
        fleet_value,
        empire_daily_total=int(empire_daily_total),
        cargo_total=int(cargo_total),
    )
    lootboxes = _roll_expedition_lootboxes(rng, event_key)
    convoy_mode: str | None = None
    if event_key == "lost_container":
        box_rng = random.Random(int(movement_id) * 11113 + 77777)
        lootboxes = roll_lost_container_lootboxes(box_rng)
    elif event_key == "abandoned_convoy":
        lootboxes = []
        convoy_rng = random.Random(int(movement_id) * 22229 + 88888)
        convoy = resolve_abandoned_convoy_treasure(convoy_rng, fleet_value=fleet_value)
        convoy_mode = str(convoy.get("mode") or "resources")
        story_salvaged = dict(convoy.get("salvaged_ships") or {})
        lootboxes = list(convoy.get("lootboxes") or [])
    elif event_key == "ancient_derelict":
        lootboxes = []
        derelict_rng = random.Random(int(movement_id) * 33347 + 99999)
        derelict = resolve_ancient_derelict_treasure(derelict_rng)
        story_salvaged = dict(derelict.get("salvaged_ships") or {})
        lootboxes = list(derelict.get("lootboxes") or [])
        story_tier = str(derelict.get("story_tier") or "legendary")
    elif event_key in ("pirate_encounter", "ancient_minefield", "ion_storm"):
        lootboxes = []
    if event_key == "pirate_encounter":
        if not (pirate_combat and pirate_combat.get("won")):
            rewards = _empty_rewards()
            loot_debug = {"economy_base": 0, "raw_loot_total": 0}
    elif event_key == "abandoned_convoy" and convoy_mode == "ships":
        rewards = _empty_rewards()
        loot_debug = {"economy_base": 0, "raw_loot_total": 0}
    elif event_key in ("ancient_minefield", "ion_storm"):
        rewards = _empty_rewards()
        loot_debug = {"economy_base": 0, "raw_loot_total": 0}
    _apply_directive_reward_modifiers(
        rewards,
        loot_mult=loot_mult,
        wreckage_bonus=wreckage_bonus,
        salvage=salvage,
    )
    cargo_meta = _apply_cargo_cap_with_jackpot(
        rewards,
        int(cargo_total),
        movement_id=int(movement_id),
    )

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
        "fleet_value": int(fleet_value),
        "empire_daily_total": int(empire_daily_total),
        "economy_base": int(loot_debug.get("economy_base") or 0),
        "raw_loot_total": int(cargo_meta.get("raw_loot_total") or loot_debug.get("raw_loot_total") or 0),
        "cargo_jackpot": bool(cargo_meta.get("cargo_jackpot")),
        "cargo_jackpot_mult": int(cargo_meta.get("cargo_jackpot_mult") or 1),
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
    if remaining_ships is not None:
        result["remaining_ships"] = remaining_ships
    if hazard is not None:
        result["hazard"] = hazard
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
            spec = SHIPS.get(str(ship_key)) or {}
            ship_name = _t(str(spec.get("name_key") or ship_key), str(ship_key))
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
            spec = SHIPS.get(str(ship_key)) or {}
            ship_name = _t(str(spec.get("name_key") or ship_key), str(ship_key))
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
        "economy_base": int(outcome.get("economy_base") or 0),
        "raw_loot_total": int(outcome.get("raw_loot_total") or 0),
        "cargo_jackpot": bool(outcome.get("cargo_jackpot")),
        "cargo_jackpot_mult": int(outcome.get("cargo_jackpot_mult") or 1),
        "losses": {str(k): int(v) for k, v in ship_losses.items() if int(v or 0) > 0},
        "losses_total": losses_total,
        "salvaged_ships": {str(k): int(v) for k, v in salvaged_ships.items() if int(v or 0) > 0},
        "salvaged_total": salvaged_total,
    }
    if outcome.get("story_tier"):
        metadata["story_tier"] = str(outcome.get("story_tier"))
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
            "ratio": float(pirate_combat.get("ratio") or 0),
            "win_chance": float(pirate_combat.get("win_chance") or 0),
            "loss_pct": int(pirate_combat.get("loss_pct") or 0),
            "salvage_tier": str(pirate_combat.get("salvage_tier") or "none"),
        }
        metadata["pirate_won"] = bool(pirate_combat.get("won"))
    if hazard:
        metadata["hazard"] = {
            "key": str(hazard.get("key") or event_key),
            "loss_pct": int(hazard.get("loss_pct") or 0),
        }
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
