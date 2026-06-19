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

# Per-event multiplier band, economy-day share, and resource split (shares sum to 1.0).
_EVENT_LOOT_PROFILES: Dict[str, Dict[str, Any]] = {
    "mineral_deposit": {
        "mult_range": (1.00, 1.35),
        "economy_day_range": (0.0067, 0.0267),
        "split": {"metal": 0.62, "crystal": 0.38},
    },
    "fuel_cache": {
        "mult_range": (0.85, 1.15),
        "economy_day_range": (0.0050, 0.0200),
        "split": {"fuel_cells": 1.0},
    },
    "debris_salvage": {
        "mult_range": (1.10, 1.60),
        "economy_day_range": (0.0270, 0.1070),
        "split": {"metal": 0.70, "crystal": 0.25, "fuel_cells": 0.05},
    },
    "ancient_stash": {
        "mult_range": (1.80, 3.00),
        "economy_day_range": (0.1330, 0.4000),
        "split": {"metal": 0.50, "crystal": 0.35, "fuel_cells": 0.15},
    },
    "distress_beacon": {
        "mult_range": (0.90, 1.25),
        "economy_day_range": (0.0200, 0.0800),
        "split": {"metal": 0.45, "crystal": 0.30, "fuel_cells": 0.25},
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
}

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
    empty_keys = {"void_scan", "sensor_glitch"}
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
) -> Dict[str, int]:
    profile = _EVENT_LOOT_PROFILES.get(str(event_key))
    if not profile or fleet_value <= 0 and int(empire_daily_total) <= 0:
        return _empty_rewards()

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
    if daily_total > 0 and isinstance(eco_range, (list, tuple)) and len(eco_range) == 2:
        eco_mult = rng.uniform(float(eco_range[0]), float(eco_range[1]))
        economy_loot = max(0, int(daily_total * eco_mult * event_mult * variance))

    total_loot = max(fleet_loot, economy_loot)
    return _split_loot_total(total_loot, profile.get("split") or {})


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
    rewards = _compute_event_loot(
        rng,
        event_key,
        fleet_value,
        empire_daily_total=int(empire_daily_total),
    )
    lootboxes = _roll_expedition_lootboxes(rng, event_key)
    _apply_directive_reward_modifiers(
        rewards,
        loot_mult=loot_mult,
        wreckage_bonus=wreckage_bonus,
        salvage=salvage,
    )
    _scale_rewards_to_cargo(rewards, int(cargo_total))

    delay_extra = 0
    delay_chance = float(event.get("delay_chance") or 0.0)
    if delay_chance > 0:
        delay_rng = random.Random(int(movement_id) * 9176)
        if delay_rng.random() < delay_chance:
            delay_extra = int(flight_seconds or 60)

    reward_total = sum(int(rewards.get(k) or 0) for k in VALID_RESOURCE_KEYS)
    return {
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
        "cargo_total": int(cargo_total),
    }


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

    if world.get("name_key"):
        body_lines.append(
            _t("fleet_world_expedition_report_losses_none", "Losses: none")
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
        "fleet_ships": {str(k): int(v) for k, v in ships.items() if int(v or 0) > 0},
        "rewards": rewards,
        "lootboxes": lootboxes,
        "delay_extra": delay_extra,
        "cargo_total": int(outcome.get("cargo_total") or 0),
        "losses": {},
        "losses_total": 0,
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
