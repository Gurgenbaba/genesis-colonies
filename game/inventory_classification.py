"""
GC-969 — Inventory item classification (trade vs use vs duration booster).

Single owner for item flags used by inventory UI, use API, and collector audit.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

from game.collector_catalog import COLLECTOR_LOCKED_REWARD_KEYS, COLLECTOR_OFFERS, is_prestige_only_item
from game.inventory_catalog import (
    BOOSTER_TIME_SECONDS,
    CONTAINER_KEYS,
    ITEM_CATALOG,
    is_known_item_key,
    resolve_item_use_kind,
    resolve_item_use_role,
)

DURATION_USE_KINDS = frozenset(
    {
        "research_pct_boost",
        "energy_pct_boost",
        "production_pct_boost",
        "fleet_speed_pct_boost",
        "expedition_loot_pct_boost",
        "container_luck_boost",
    }
)

INSTANT_USE_KINDS = frozenset(
    {
        "time_boost",
        "resource",
        "planet_xp",
        "research_datacore",
        "research_instant",
        "blueprint",
    }
)

EFFECT_OWNER_BY_USE_KIND: Dict[str, str] = {
    "time_boost": "queue_engine",
    "resource": "planet_resources",
    "planet_xp": "planet_evolution",
    "research_datacore": "research_queue",
    "research_instant": "research",
    "blueprint": "player_unlocks",
    "research_pct_boost": "effect_resolver.research_time_speed",
    "energy_pct_boost": "effect_resolver.solar_output_factor",
    "production_pct_boost": "effect_resolver.production",
    "fleet_speed_pct_boost": "effect_resolver.fleet_speed",
    "expedition_loot_pct_boost": "expedition_loot",
    "container_luck_boost": "inventory_loot",
}

_COLLECTOR_TRADE_INPUT_KEYS: Optional[Set[str]] = None


def collector_trade_input_keys() -> frozenset[str]:
    global _COLLECTOR_TRADE_INPUT_KEYS
    if _COLLECTOR_TRADE_INPUT_KEYS is None:
        keys: Set[str] = set()
        for offer in COLLECTOR_OFFERS.values():
            ik = str(offer.get("input_key") or "").strip()
            if ik:
                keys.add(ik)
        _COLLECTOR_TRADE_INPUT_KEYS = keys
    return frozenset(_COLLECTOR_TRADE_INPUT_KEYS)


def item_is_locked_planned(item_key: str) -> bool:
    key = str(item_key or "").strip()
    if not key:
        return False
    if key in COLLECTOR_LOCKED_REWARD_KEYS:
        return True
    role = resolve_item_use_role(key)
    if role in ("collectible", "craft_material", "exchange_material"):
        return False
    use_kind = resolve_item_use_kind(key)
    if not use_kind:
        return False
    if use_kind in DURATION_USE_KINDS or use_kind in INSTANT_USE_KINDS:
        from game.inventory_boosters import item_has_implemented_use_effect

        return not item_has_implemented_use_effect(key)
    return True


def item_has_duration_effect(item_key: str) -> bool:
    kind = resolve_item_use_kind(str(item_key or ""))
    return kind in DURATION_USE_KINDS


def item_has_instant_use(item_key: str) -> bool:
    key = str(item_key or "")
    if key in BOOSTER_TIME_SECONDS:
        return True
    return resolve_item_use_kind(key) in INSTANT_USE_KINDS


def classify_inventory_item(item_key: str) -> Dict[str, Any]:
    """Return canonical inventory flags for one catalog item."""
    key = str(item_key or "").strip()
    role = resolve_item_use_role(key)
    use_kind = resolve_item_use_kind(key)
    locked = item_is_locked_planned(key)
    collectible = role == "collectible"
    prestige = is_prestige_only_item(key)
    trade_material = (
        key in collector_trade_input_keys()
        or role in ("exchange_material", "craft_material")
    )
    duration_effect = item_has_duration_effect(key)
    instant_use = item_has_instant_use(key) and not duration_effect

    usable = False
    if role == "usable" and not locked:
        from game.inventory_boosters import item_has_implemented_use_effect

        usable = item_has_implemented_use_effect(key)

    if key in CONTAINER_KEYS:
        trade_material = False
        usable = False
        instant_use = False
        duration_effect = False

    effect_owner = EFFECT_OWNER_BY_USE_KIND.get(str(use_kind or ""))
    if key in BOOSTER_TIME_SECONDS:
        effect_owner = "queue_engine"

    catalog_hint = str((ITEM_CATALOG.get(key) or {}).get("redeem_hint_key") or "").strip()
    use_hint_key: Optional[str] = None
    if locked:
        use_hint_key = "inv_hint_locked_planned"
    elif catalog_hint:
        use_hint_key = catalog_hint
    elif trade_material and not usable:
        use_hint_key = "inv_hint_collector_trade"
    elif prestige:
        use_hint_key = "inv_hint_collector_prestige"
    elif collectible:
        use_hint_key = "inv_collectible_hint"

    return {
        "item_key": key,
        "trade_material": bool(trade_material),
        "usable": bool(usable),
        "instant_use": bool(instant_use),
        "duration_effect": bool(duration_effect),
        "collectible": bool(collectible),
        "prestige_only": bool(prestige),
        "locked_planned": bool(locked),
        "effect_owner": effect_owner,
        "use_hint_key": use_hint_key,
        "use_role": role,
        "use_kind": use_kind,
    }


def audit_all_inventory_items() -> Dict[str, Dict[str, Any]]:
    from game.inventory_catalog import ITEM_CATALOG

    return {key: classify_inventory_item(key) for key in sorted(ITEM_CATALOG.keys())}


def assert_inventory_classification_consistency() -> None:
    """Raise when a non-container item is ambiguous (neither usable/trade/collectible/locked)."""
    from game.inventory_catalog import ITEM_CATALOG

    for key in ITEM_CATALOG:
        if key in CONTAINER_KEYS:
            continue
        row = classify_inventory_item(key)
        if row["locked_planned"] or row["prestige_only"]:
            continue
        if row["usable"] or row["trade_material"] or row["collectible"]:
            continue
        raise AssertionError(f"inventory item {key!r} has no role (usable/trade/collectible/locked)")
