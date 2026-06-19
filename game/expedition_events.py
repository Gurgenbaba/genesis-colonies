"""Deterministic expedition event engine — loot, delays, structured reports."""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple

from .fleet_defs import SHIPS, VALID_RESOURCE_KEYS, ship_score_value

EXPEDITION_REPORT_VERSION = 2

# Expedition loot uses expedition-hull cargo × multiplier (not transport cargo semantics).
EXPEDITION_LOOT_CARGO_MULTIPLIER = 50

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
        "rewards": {"loot": True},
    },
    {
        "key": "fuel_cache",
        "weight": 16,
        "label_key": "expedition_event_fuel_cache",
        "desc_key": "expedition_event_fuel_cache_desc",
        "severity": "normal",
        "rewards": {"loot": True},
    },
    {
        "key": "debris_salvage",
        "weight": 12,
        "label_key": "expedition_event_debris_salvage",
        "desc_key": "expedition_event_debris_salvage_desc",
        "severity": "minor",
        "rewards": {"loot": True},
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
        "rewards": {"loot": True},
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
        "rewards": {"loot": True},
    },
)

_EVENT_BY_KEY: Dict[str, Dict[str, Any]] = {str(e["key"]): e for e in _EXPEDITION_EVENTS}

_SALVAGE_EVENT_KEYS: frozenset[str] = frozenset(
    {"debris_salvage", "mineral_deposit", "fuel_cache", "distress_beacon"}
)

_NO_LOOT_EVENT_KEYS: frozenset[str] = frozenset(
    {"void_scan", "sensor_glitch", "nav_interference"}
)

_LOOT_EVENT_KEYS: frozenset[str] = frozenset(
    {"mineral_deposit", "fuel_cache", "debris_salvage", "ancient_stash", "distress_beacon"}
)


def expedition_event_keys() -> frozenset[str]:
    return frozenset(_EVENT_BY_KEY.keys())


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


def calculate_fleet_value(
    ships: Mapping[str, int],
    *,
    expedition_ship_count: int = 0,
) -> int:
    """Sum of ship_count × score_value for all hulls in the expedition fleet."""
    total = 0
    for key, qty in ships.items():
        amount = int(qty or 0)
        if amount <= 0:
            continue
        total += amount * ship_score_value(str(key))
    if total <= 0 and int(expedition_ship_count) > 0:
        total = int(expedition_ship_count) * ship_score_value("solar_skiff")
    return max(0, total)


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
        elif event.get("rewards"):
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


def _allocate_integer_shares(total: int, shares: Mapping[str, float]) -> Dict[str, int]:
    """Split *total* across resource keys; remainder goes to the last key."""
    rewards = {key: 0 for key in VALID_RESOURCE_KEYS}
    amount = max(0, int(total))
    if amount <= 0:
        return rewards

    keys = [str(k) for k in shares if str(k) in VALID_RESOURCE_KEYS and float(shares[k]) > 0]
    if not keys:
        return rewards

    allocated = 0
    for key in keys[:-1]:
        part = int(amount * float(shares[key]))
        rewards[key] = part
        allocated += part
    rewards[keys[-1]] = amount - allocated
    return rewards


def _split_loot_total(
    rng: random.Random,
    event_key: str,
    total: int,
) -> Dict[str, int]:
    amount = max(0, int(total))
    if amount <= 0 or event_key not in _LOOT_EVENT_KEYS:
        return {key: 0 for key in VALID_RESOURCE_KEYS}

    if event_key == "mineral_deposit":
        metal_share = rng.uniform(0.45, 0.60)
        return _allocate_integer_shares(
            amount,
            {"metal": metal_share, "crystal": 1.0 - metal_share},
        )

    if event_key == "fuel_cache":
        fuel_share = rng.uniform(0.75, 1.0)
        remainder = max(0.0, 1.0 - fuel_share)
        if remainder <= 0:
            return _allocate_integer_shares(amount, {"fuel_cells": 1.0})
        metal_share = rng.uniform(0.0, 1.0) * remainder
        return _allocate_integer_shares(
            amount,
            {
                "fuel_cells": fuel_share,
                "metal": metal_share,
                "crystal": remainder - metal_share,
            },
        )

    if event_key == "debris_salvage":
        raw = {
            "fuel_cells": rng.uniform(0.0, 0.10),
            "metal": rng.uniform(0.50, 0.70),
            "crystal": rng.uniform(0.25, 0.45),
        }
        norm = sum(raw.values()) or 1.0
        shares = {key: value / norm for key, value in raw.items()}
        return _allocate_integer_shares(amount, shares)

    if event_key in {"ancient_stash", "distress_beacon"}:
        cut_a = rng.random()
        cut_b = rng.random()
        if cut_a + cut_b >= 1.0:
            cut_a *= 0.49
            cut_b *= 0.49
        metal_share = cut_a
        crystal_share = cut_b
        fuel_share = max(0.0, 1.0 - metal_share - crystal_share)
        return _allocate_integer_shares(
            amount,
            {"metal": metal_share, "crystal": crystal_share, "fuel_cells": fuel_share},
        )

    return {key: 0 for key in VALID_RESOURCE_KEYS}


def _effective_loot_total(
    cargo_total: int,
    *,
    loot_mult: float = 1.0,
    wreckage_bonus: float = 0.0,
    salvage: bool = False,
) -> int:
    cap = max(0, int(cargo_total))
    mult = max(0.0, float(loot_mult))
    if salvage and wreckage_bonus:
        mult *= 1.0 + max(0.0, float(wreckage_bonus))
    return min(cap, max(0, int(cap * mult)))


def _compute_event_rewards(
    rng: random.Random,
    event_key: str,
    loot_total: int,
) -> Dict[str, int]:
    if event_key in _NO_LOOT_EVENT_KEYS or loot_total <= 0:
        return {key: 0 for key in VALID_RESOURCE_KEYS}
    return _split_loot_total(rng, event_key, loot_total)


def _scale_rewards_to_cargo(rewards: MutableMapping[str, int], cargo_total: int) -> None:
    loaded = sum(int(rewards.get(k) or 0) for k in VALID_RESOURCE_KEYS)
    if cargo_total <= 0 or loaded <= cargo_total:
        return
    scale = cargo_total / max(1, loaded)
    for key in VALID_RESOURCE_KEYS:
        rewards[key] = int(int(rewards.get(key) or 0) * scale)


def resolve_expedition_outcome(
    movement_id: int,
    *,
    cargo_total: int,
    expedition_ship_count: int,
    flight_seconds: int,
    ships: Mapping[str, int] | None = None,
    world_type: str | None = None,
    directive_flags: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Idempotent expedition resolution keyed by movement id."""
    flags = dict(directive_flags or {})
    salvage = str(world_type or "") == "wreckage_field"
    event_bonus = float(flags.get("expedition_event_bonus") or 0.0)
    loot_mult = float(flags.get("expedition_loot_mult") or 1.0)
    wreckage_bonus = float(flags.get("expedition_wreckage_bonus") or 0.0)

    fleet_value = calculate_fleet_value(ships or {}, expedition_ship_count=expedition_ship_count)
    loot_total = _effective_loot_total(
        int(cargo_total),
        loot_mult=loot_mult,
        wreckage_bonus=wreckage_bonus,
        salvage=salvage,
    )

    rng = random.Random(int(movement_id) * 7919 + 104729)
    event_key = _pick_event_key(
        rng,
        expedition_ship_count,
        salvage=salvage,
        event_bonus=event_bonus,
    )
    event = _EVENT_BY_KEY[event_key]
    rewards = _compute_event_rewards(rng, event_key, loot_total)
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
        "delay_extra": delay_extra,
        "expedition_ship_count": int(expedition_ship_count),
        "cargo_total": int(cargo_total),
        "fleet_value": fleet_value,
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
    else:
        body_lines.append(
            _t(
                "fleet_world_salvage_report_loot_none" if is_salvage else "fleet_world_expedition_report_loot_none",
                "Salvage: none",
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
