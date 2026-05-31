"""Deterministic expedition event engine — loot, delays, structured reports."""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple

from .fleet_defs import SHIPS, VALID_RESOURCE_KEYS

EXPEDITION_REPORT_VERSION = 2

# Weighted event table (sum = 100). Server-authoritative; extend here only.
_EXPEDITION_EVENTS: Sequence[Dict[str, Any]] = (
    {
        "key": "void_scan",
        "weight": 15,
        "label_key": "expedition_event_void_scan",
        "desc_key": "expedition_event_void_scan_desc",
        "severity": "minor",
        "rewards": {},
    },
    {
        "key": "mineral_deposit",
        "weight": 30,
        "label_key": "expedition_event_mineral_deposit",
        "desc_key": "expedition_event_mineral_deposit_desc",
        "severity": "normal",
        "rewards": {"metal": (500, 2500), "crystal": (200, 1200)},
    },
    {
        "key": "fuel_cache",
        "weight": 15,
        "label_key": "expedition_event_fuel_cache",
        "desc_key": "expedition_event_fuel_cache_desc",
        "severity": "normal",
        "rewards": {"fuel_cells": (10, 80)},
    },
    {
        "key": "debris_salvage",
        "weight": 10,
        "label_key": "expedition_event_debris_salvage",
        "desc_key": "expedition_event_debris_salvage_desc",
        "severity": "minor",
        "rewards": {"metal": (150, 900)},
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
        "weight": 8,
        "label_key": "expedition_event_distress_beacon",
        "desc_key": "expedition_event_distress_beacon_desc",
        "severity": "normal",
        "rewards": {"metal": (100, 600), "crystal": (50, 300), "fuel_cells": (5, 25)},
        "delay_chance": 0.25,
    },
    {
        "key": "sensor_glitch",
        "weight": 7,
        "label_key": "expedition_event_sensor_glitch",
        "desc_key": "expedition_event_sensor_glitch_desc",
        "severity": "minor",
        "rewards": {},
    },
    {
        "key": "ancient_stash",
        "weight": 5,
        "label_key": "expedition_event_ancient_stash",
        "desc_key": "expedition_event_ancient_stash_desc",
        "severity": "major",
        "rewards": {"metal": (2000, 5000), "crystal": (1000, 3000), "fuel_cells": (20, 100)},
    },
)

_EVENT_BY_KEY: Dict[str, Dict[str, Any]] = {str(e["key"]): e for e in _EXPEDITION_EVENTS}


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


def _pick_event_key(rng: random.Random, expedition_ship_count: int) -> str:
    """Pick event; extra expedition hulls shift weight away from empty outcomes."""
    bonus = min(0.12, max(0, int(expedition_ship_count)) * 0.03)
    empty_keys = {"void_scan", "sensor_glitch"}
    adjusted: list[tuple[str, float]] = []
    for event in _EXPEDITION_EVENTS:
        key = str(event["key"])
        weight = float(event["weight"])
        if key in empty_keys:
            weight = max(1.0, weight * (1.0 - bonus))
        elif event.get("rewards"):
            weight = weight * (1.0 + bonus)
        adjusted.append((key, weight))
    total = sum(w for _, w in adjusted)
    roll = rng.random() * total
    for key, weight in adjusted:
        roll -= weight
        if roll <= 0:
            return key
    return str(_EXPEDITION_EVENTS[-1]["key"])


def _roll_rewards(
    rng: random.Random,
    reward_ranges: Mapping[str, Any],
) -> Dict[str, int]:
    rewards = {key: 0 for key in VALID_RESOURCE_KEYS}
    for resource, bounds in reward_ranges.items():
        if resource not in VALID_RESOURCE_KEYS:
            continue
        if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
            lo, hi = int(bounds[0]), int(bounds[1])
            rewards[str(resource)] = rng.randint(min(lo, hi), max(lo, hi))
        elif isinstance(bounds, int):
            rewards[str(resource)] = int(bounds)
    return rewards


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
) -> Dict[str, Any]:
    """Idempotent expedition resolution keyed by movement id."""
    rng = random.Random(int(movement_id) * 7919 + 104729)
    event_key = _pick_event_key(rng, expedition_ship_count)
    event = _EVENT_BY_KEY[event_key]
    rewards = _roll_rewards(rng, event.get("rewards") or {})
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
    }


def build_expedition_report(
    coords: str,
    ships: Mapping[str, int],
    outcome: Mapping[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    from .i18n import fmt_int, tr

    event_key = str(outcome.get("event_key") or "void_scan")
    event = _EVENT_BY_KEY.get(event_key) or {}
    label = tr(str(event.get("label_key") or event_key), event_key)
    desc = tr(str(event.get("desc_key") or event_key), "")
    rewards = dict(outcome.get("rewards") or {})
    delay_extra = int(outcome.get("delay_extra") or 0)
    expedition_ships = int(outcome.get("expedition_ship_count") or 0)

    body_lines: list[str] = [
        tr("fleet_expedition_report_coords", "Coordinates: %(coords)s", coords=coords),
        tr("fleet_expedition_report_event", "Event: %(event)s", event=label),
    ]
    if desc:
        body_lines.append(desc)

    reward_lines: list[str] = []
    if int(rewards.get("metal") or 0):
        reward_lines.append(f"{tr('resource_metal', 'Ferronit')}: {fmt_int(rewards['metal'])}")
    if int(rewards.get("crystal") or 0):
        reward_lines.append(f"{tr('resource_crystal', 'Crytite')}: {fmt_int(rewards['crystal'])}")
    if int(rewards.get("fuel_cells") or 0):
        reward_lines.append(
            f"{tr('resource_fuel_cells', 'Fuel Cells')}: {fmt_int(rewards['fuel_cells'])}"
        )
    if reward_lines:
        body_lines.append(tr("fleet_expedition_report_section_loot", "Recovered cargo"))
        body_lines.extend(f"  {line}" for line in reward_lines)
    elif delay_extra:
        body_lines.append(
            tr(
                "fleet_expedition_report_delay_only",
                "Return flight extended by %(seconds)s s due to navigation interference.",
                seconds=fmt_int(delay_extra),
            )
        )
    else:
        body_lines.append(tr("fleet_expedition_report_no_loot", "No recoverable cargo."))

    if delay_extra and reward_lines:
        body_lines.append(
            tr(
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
    }
    return "\n".join(body_lines), metadata
