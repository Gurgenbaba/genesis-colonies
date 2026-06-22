"""
Admin loot pool configuration — validated overrides for container loot tables.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from .inventory_catalog import (
    CONTAINER_DISPLAY_ORDER,
    CONTAINER_KEYS,
    ITEM_CATALOG,
    admin_grant_catalog,
    is_known_item_key,
)
from . import inventory_loot

LootEntry = Dict[str, Any]

VALID_REWARD_TYPES = frozenset({"resource", "item", "booster", "ship", "defense"})
VALID_RESOURCES = frozenset({"metal", "crystal", "fuel_cells"})
MAX_POOL_ENTRIES = 40
MAX_WEIGHT = 100_000
MAX_AMOUNT = 1_000_000_000


def _validate_reward_key(reward_type: str, reward_key: str) -> bool:
    if reward_type == "resource":
        return reward_key in VALID_RESOURCES
    if reward_type == "ship":
        from .fleet_defs import canonical_ship_key, get_ship

        sk = canonical_ship_key(reward_key)
        return bool(get_ship(sk))
    if reward_type == "defense":
        from .defense_defs import DEFENSES

        return reward_key in DEFENSES
    if reward_type in ("item", "booster"):
        return is_known_item_key(reward_key)
    return False


def normalize_loot_entry(raw: Any) -> Optional[LootEntry]:
    if not isinstance(raw, dict):
        return None
    try:
        weight = int(raw.get("weight") or 0)
    except (TypeError, ValueError):
        return None
    reward_type = str(raw.get("reward_type") or "").strip().lower()
    reward_key = str(raw.get("reward_key") or "").strip()
    if reward_type not in VALID_REWARD_TYPES:
        return None
    if not reward_key:
        return None
    if weight < 1 or weight > MAX_WEIGHT:
        return None
    if not _validate_reward_key(reward_type, reward_key):
        return None
    if reward_type == "ship":
        from .fleet_defs import canonical_ship_key

        reward_key = canonical_ship_key(reward_key)

    if reward_type == "resource" and raw.get("stock_fraction") is not None:
        if reward_key != "fuel_cells":
            return None
        try:
            stock_fraction = float(raw.get("stock_fraction"))
        except (TypeError, ValueError):
            return None
        if stock_fraction <= 0 or stock_fraction > 1.0:
            return None
        return {
            "weight": weight,
            "reward_type": reward_type,
            "reward_key": reward_key,
            "stock_fraction": stock_fraction,
        }

    production_hours: Optional[float] = None
    if reward_type == "resource" and raw.get("production_hours") is not None:
        try:
            production_hours = float(raw.get("production_hours"))
        except (TypeError, ValueError):
            return None
        if production_hours <= 0 or production_hours > 168:
            return None
        return {
            "weight": weight,
            "reward_type": reward_type,
            "reward_key": reward_key,
            "production_hours": production_hours,
        }

    if reward_type == "ship" and raw.get("fleet_fraction") is not None:
        try:
            fleet_fraction = float(raw.get("fleet_fraction"))
        except (TypeError, ValueError):
            return None
        if fleet_fraction <= 0 or fleet_fraction > 1.0:
            return None
        return {
            "weight": weight,
            "reward_type": reward_type,
            "reward_key": reward_key,
            "fleet_fraction": fleet_fraction,
        }

    if reward_type == "defense" and raw.get("defense_fraction") is not None:
        try:
            defense_fraction = float(raw.get("defense_fraction"))
        except (TypeError, ValueError):
            return None
        if defense_fraction <= 0 or defense_fraction > 1.0:
            return None
        return {
            "weight": weight,
            "reward_type": reward_type,
            "reward_key": reward_key,
            "defense_fraction": defense_fraction,
        }

    try:
        min_amount = int(raw.get("min_amount") or 1)
        max_amount = int(raw.get("max_amount") or min_amount)
    except (TypeError, ValueError):
        return None
    if min_amount < 1 or max_amount < min_amount or max_amount > MAX_AMOUNT:
        return None
    return {
        "weight": weight,
        "reward_type": reward_type,
        "reward_key": reward_key,
        "min_amount": min_amount,
        "max_amount": max_amount,
    }


def validate_loot_pool(entries: Any) -> Tuple[bool, str, List[LootEntry]]:
    if not isinstance(entries, list):
        return False, "invalid_pool", []
    if not entries:
        return False, "empty_pool", []
    if len(entries) > MAX_POOL_ENTRIES:
        return False, "pool_too_large", []
    normalized: List[LootEntry] = []
    total_weight = 0
    for raw in entries:
        entry = normalize_loot_entry(raw)
        if not entry:
            return False, "invalid_entry", []
        total_weight += int(entry["weight"])
        normalized.append(entry)
    if total_weight <= 0:
        return False, "zero_weight", []
    return True, "", normalized


_RESOURCE_NAME_KEYS = {
    "metal": "resource_metal",
    "crystal": "resource_crystal",
    "fuel_cells": "resource_fuel_cells",
}


def build_reward_key_options() -> Dict[str, List[Dict[str, str]]]:
    resources = [
        {"key": key, "name_key": _RESOURCE_NAME_KEYS.get(key, key)}
        for key in sorted(VALID_RESOURCES)
    ]

    from .fleet_defs import SHIPS

    ships = [
        {"key": key, "name_key": str(spec.get("name_key") or f"fleet_ship_{key}")}
        for key, spec in sorted(SHIPS.items())
    ]

    from .defense_defs import DEFENSES

    defenses = [
        {"key": key, "name_key": str(spec.get("name_key") or f"defense_{key}")}
        for key, spec in sorted(DEFENSES.items())
    ]

    items: List[Dict[str, str]] = []
    boosters: List[Dict[str, str]] = []
    for key, meta in sorted(ITEM_CATALOG.items()):
        entry = {"key": key, "name_key": str(meta.get("name_key") or key)}
        if meta.get("item_type") == "booster" or meta.get("category") == "booster":
            boosters.append(entry)
        else:
            items.append(entry)

    return {
        "resource": resources,
        "ship": ships,
        "defense": defenses,
        "item": items,
        "booster": boosters,
    }


def build_admin_loot_state() -> Dict[str, Any]:
    pools: Dict[str, Any] = {}
    for key in CONTAINER_DISPLAY_ORDER:
        if key not in CONTAINER_KEYS:
            continue
        default_entries = deepcopy(inventory_loot.LOOT_POOLS.get(key) or [])
        effective = inventory_loot.get_loot_pools().get(key) or []
        pools[key] = {
            "entries": deepcopy(effective),
            "default_entries": default_entries,
            "is_custom": inventory_loot.pool_has_override(key),
        }
    return {
        "ok": True,
        "containers": admin_grant_catalog(),
        "pools": pools,
        "reward_types": sorted(VALID_REWARD_TYPES),
        "resource_keys": sorted(VALID_RESOURCES),
        "reward_keys_by_type": build_reward_key_options(),
    }
