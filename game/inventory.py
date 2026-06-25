"""
GC-540 — Container inventory and weighted loot pools (server-authoritative).
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import begin_write_transaction, commit, db, lock_planet_for_update, rollback, table_exists
from .inventory_catalog import (
    CONTAINER_BASIC_COOLDOWN_SEC,
    CONTAINER_BASIC_KEY,
    CONTAINER_DISPLAY_ORDER,
    CONTAINER_KEYS,
    GRANTABLE_ITEM_KEYS,
    ROLL_PREVIEW_MAX,
    ROLL_PREVIEW_MIN,
    ROLL_WINNING_INDEX_MAX,
    ROLL_WINNING_INDEX_MIN,
    admin_grant_catalog,
    container_image_path,
    is_known_item_key,
    item_catalog_entry,
)
from . import inventory_loot

LootEntry = Dict[str, Any]
Reward = Dict[str, Any]

LOOT_POOLS = inventory_loot.LOOT_POOLS

# Re-export for tests and callers
__all__ = [
    "CONTAINER_KEYS",
    "LOOT_POOLS",
    "GRANTABLE_ITEM_KEYS",
    "admin_grant_catalog",
    "build_container_catalog",
    "build_inventory_state",
    "build_loot_drops_reference",
    "grant_inventory_item",
    "inventory_schema_ready",
    "is_known_item_key",
    "item_catalog_entry",
    "list_player_inventory",
    "open_containers",
    "run_inventory_mutation",
]

MutationResult = Tuple[bool, str, Optional[Dict[str, Any]]]


def inventory_schema_ready(conn) -> bool:
    return table_exists(conn, "player_inventory_items") and table_exists(conn, "container_open_log")


def _serialize_inventory_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    key = str(row["item_key"])
    meta = item_catalog_entry(key)
    out = {
        "id": int(row["id"]),
        "item_key": key,
        "item_type": str(row["item_type"] or meta["item_type"]),
        "category": meta.get("category", "misc"),
        "rarity": str(row["rarity"] or meta["rarity"]),
        "amount": int(row["amount"] or 0),
        "name_key": meta["name_key"],
        "icon": meta["icon"],
        "planet_id": int(row["planet_id"]) if row["planet_id"] is not None else None,
        "metadata": json.loads(str(row["metadata_json"] or "{}")),
    }
    if meta.get("image"):
        out["image"] = meta["image"]
    return out


def _last_container_open_at(user_id: int, container_key: str, *, conn) -> Optional[float]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT created_at FROM container_open_log
        WHERE user_id = ? AND container_key = ?
        ORDER BY created_at DESC LIMIT 1;
        """,
        (int(user_id), str(container_key)),
    )
    row = cur.fetchone()
    if not row:
        return None
    return float(row["created_at"])


def basic_container_cooldown_remaining(
    user_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> int:
    """Seconds until the next standard-container open is allowed (0 = ready)."""
    if not inventory_schema_ready(conn):
        return 0
    last = _last_container_open_at(user_id, CONTAINER_BASIC_KEY, conn=conn)
    if last is None:
        return 0
    ts = float(now if now is not None else time.time())
    remaining = float(CONTAINER_BASIC_COOLDOWN_SEC) - (ts - float(last))
    return max(0, int(remaining))


def _attach_container_rules(
    entry: Dict[str, Any],
    *,
    user_id: Optional[int] = None,
    conn=None,
) -> Dict[str, Any]:
    key = str(entry["item_key"])
    amount = int(entry.get("amount") or 0)
    max_open = 10
    cooldown_seconds = 0
    cooldown_active = False
    open_blocked = False
    free_open_available = False
    if key == CONTAINER_BASIC_KEY:
        max_open = 1
        if user_id is not None and conn is not None:
            cooldown_seconds = basic_container_cooldown_remaining(int(user_id), conn=conn)
            cooldown_active = cooldown_seconds > 0
            # Cooldown limits the free daily open — owned stock can always be opened.
            open_blocked = cooldown_active and amount <= 0
            free_open_available = amount <= 0 and not cooldown_active
    entry["max_open_amount"] = max_open
    entry["cooldown_seconds"] = cooldown_seconds
    entry["cooldown_active"] = cooldown_active
    entry["free_open_available"] = free_open_available
    entry["open_blocked"] = open_blocked
    return entry


def build_container_catalog(
    owned: Optional[Mapping[str, Mapping[str, Any]]] = None,
    *,
    user_id: Optional[int] = None,
    conn=None,
) -> List[Dict[str, Any]]:
    owned_map = owned or {}
    catalog: List[Dict[str, Any]] = []
    for key in CONTAINER_DISPLAY_ORDER:
        if key not in CONTAINER_KEYS:
            continue
        meta = item_catalog_entry(key)
        row = owned_map.get(key)
        amount = int((row or {}).get("amount") or 0)
        entry = {
            "item_key": key,
            "item_type": "container",
            "category": "container",
            "rarity": meta["rarity"],
            "amount": amount,
            "name_key": meta["name_key"],
            "icon": meta["icon"],
            "image": meta.get("image") or container_image_path(key),
            "owned": amount > 0,
        }
        catalog.append(_attach_container_rules(entry, user_id=user_id, conn=conn))
    return catalog


def list_player_inventory(user_id: int, *, conn) -> List[Dict[str, Any]]:
    if not inventory_schema_ready(conn):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, item_key, item_type, rarity, amount, planet_id, metadata_json
        FROM player_inventory_items
        WHERE user_id = ? AND amount > 0
        ORDER BY item_type, rarity, item_key;
        """,
        (int(user_id),),
    )
    return [_serialize_inventory_row(r) for r in cur.fetchall()]


from .number_format import fmt_int_compact


def _loot_amount_label(lo: int, hi: int) -> str:
    lo_i, hi_i = int(lo), int(hi)
    if hi_i < lo_i:
        hi_i = lo_i
    if lo_i == hi_i:
        return fmt_int_compact(lo_i)
    return f"{fmt_int_compact(lo_i)}–{fmt_int_compact(hi_i)}"


def build_loot_drops_reference(*, conn=None, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Public loot-pool reference for inventory UI (server data only)."""
    rows: List[Dict[str, Any]] = []
    effective_pools = inventory_loot.get_loot_pools(conn)
    production_per_hour: Optional[Dict[str, int]] = None
    roll_ctx: Optional[Dict[str, Any]] = None
    if user_id is not None and conn is not None:
        roll_ctx = inventory_loot.build_loot_roll_context(int(user_id), "container_basic", conn=conn)
        production_per_hour = roll_ctx.get("production_per_hour")
    for key in CONTAINER_DISPLAY_ORDER:
        pool = effective_pools.get(key) or []
        if not pool:
            continue
        meta = item_catalog_entry(key)
        total_weight = sum(int(e.get("weight") or 0) for e in pool)
        drops: List[Dict[str, Any]] = []
        for entry in pool:
            weight = int(entry.get("weight") or 0)
            if weight <= 0:
                continue
            rtype = str(entry.get("reward_type") or "")
            rkey = str(entry.get("reward_key") or "")
            scaled = inventory_loot.is_dynamic_loot_entry(entry)
            if scaled and roll_ctx is not None:
                preview_rng = random.Random(0)
                amt = inventory_loot.resolve_loot_entry_amount(
                    entry,
                    user_id=int(user_id),
                    container_key=key,
                    conn=conn,
                    rng=preview_rng,
                    loot_context=roll_ctx,
                )
                lo = hi = amt
                amount_label = _loot_amount_label(lo, hi)
            elif scaled:
                lo = hi = 0
                amount_label = inventory_loot.scaled_loot_amount_label(entry, container_key=key)
            else:
                lo = int(entry.get("min_amount") or 1)
                hi = int(entry.get("max_amount") or lo)
                amount_label = _loot_amount_label(lo, hi)
            display = _reward_display_meta(rtype, rkey)
            drop_row: Dict[str, Any] = {
                "reward_type": rtype,
                "reward_key": rkey,
                "name_key": display["name_key"],
                "icon": display.get("icon") or "📦",
                "rarity": display.get("rarity") or "common",
                "min_amount": lo,
                "max_amount": hi,
                "amount_label": amount_label,
                "weight": weight,
                "weight_pct": round(100.0 * weight / total_weight, 1) if total_weight else 0.0,
            }
            if scaled:
                drop_row["scaled_to_mines"] = True
            drops.append(drop_row)
        suffix = key.replace("container_", "", 1)
        rows.append(
            {
                "item_key": key,
                "name_key": meta["name_key"],
                "tagline_key": f"inv_loot_tagline_{suffix}",
                "rarity": meta["rarity"],
                "image": meta.get("image") or container_image_path(key),
                "drops": drops,
            }
        )
    return rows


def build_inventory_state(user_id: int, *, conn) -> Dict[str, Any]:
    from .inventory_use import enrich_inventory_item_row
    from .planet_evolution.repository import get_context_planet

    items = list_player_inventory(user_id, conn=conn)
    planet = get_context_planet(user_id, conn=conn)
    planet_id = int(planet["id"])
    owned_containers = {str(i["item_key"]): i for i in items if i["item_type"] == "container"}
    containers = build_container_catalog(owned_containers, user_id=int(user_id), conn=conn)
    other_items = [
        enrich_inventory_item_row(
            i,
            user_id=int(user_id),
            planet_id=planet_id,
            conn=conn,
        )
        for i in items
        if i["item_type"] != "container"
    ]
    return {
        "ready": inventory_schema_ready(conn),
        "containers": containers,
        "other_items": other_items,
        "loot_drops": build_loot_drops_reference(conn=conn, user_id=int(user_id)),
        "craft_recipes": _craft_recipes_reference(),
        "all": items,
        "planet_name": str(planet.get("name") or ""),
    }


def _craft_recipes_reference() -> List[Dict[str, Any]]:
    from .inventory_catalog import CRAFT_RECIPES, item_catalog_entry

    rows: List[Dict[str, Any]] = []
    for recipe_key, recipe in CRAFT_RECIPES.items():
        requires = []
        for mat_key, amt in (recipe.get("requires") or {}).items():
            meta = item_catalog_entry(str(mat_key))
            requires.append(
                {
                    "item_key": str(mat_key),
                    "amount": int(amt),
                    "name_key": meta["name_key"],
                }
            )
        out_meta = item_catalog_entry(str(recipe.get("output_key") or recipe_key))
        rows.append(
            {
                "recipe_key": recipe_key,
                "name_key": str(recipe.get("name_key") or f"inv_craft_{recipe_key}"),
                "output_key": str(recipe.get("output_key") or recipe_key),
                "output_name_key": out_meta["name_key"],
                "output_amount": int(recipe.get("output_amount") or 1),
                "requires": requires,
            }
        )
    return rows


def _inventory_amount(user_id: int, item_key: str, *, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT amount FROM player_inventory_items
        WHERE user_id = ? AND item_key = ? AND planet_id IS NULL
        LIMIT 1;
        """,
        (int(user_id), str(item_key)),
    )
    row = cur.fetchone()
    return int(row["amount"] or 0) if row else 0


def grant_inventory_item(
    user_id: int,
    item_key: str,
    amount: int,
    *,
    conn,
    planet_id: Optional[int] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> bool:
    if not inventory_schema_ready(conn):
        return False
    if not is_known_item_key(item_key):
        return False
    amt = int(amount)
    if amt <= 0:
        return False
    key = str(item_key)
    spec = item_catalog_entry(key)
    now = float(time.time())
    meta_json = json.dumps(dict(metadata or {}))
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, amount FROM player_inventory_items
        WHERE user_id = ? AND item_key = ? AND planet_id IS NULL
        LIMIT 1;
        """,
        (int(user_id), key),
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            """
            UPDATE player_inventory_items
            SET amount = amount + ?, updated_at = ?
            WHERE id = ?;
            """,
            (amt, now, int(row["id"])),
        )
    else:
        cur.execute(
            """
            INSERT INTO player_inventory_items (
                user_id, planet_id, item_key, item_type, rarity, amount,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(user_id),
                int(planet_id) if planet_id is not None else None,
                key,
                spec["item_type"],
                spec["rarity"],
                amt,
                meta_json,
                now,
                now,
            ),
        )
    return True


def _debit_inventory_item(user_id: int, item_key: str, amount: int, *, conn) -> bool:
    owned = _inventory_amount(user_id, item_key, conn=conn)
    amt = int(amount)
    if amt <= 0 or owned < amt:
        return False
    now = float(time.time())
    new_amt = owned - amt
    cur = conn.cursor()
    if new_amt <= 0:
        cur.execute(
            """
            DELETE FROM player_inventory_items
            WHERE user_id = ? AND item_key = ? AND planet_id IS NULL;
            """,
            (int(user_id), str(item_key)),
        )
    else:
        cur.execute(
            """
            UPDATE player_inventory_items
            SET amount = ?, updated_at = ?
            WHERE user_id = ? AND item_key = ? AND planet_id IS NULL;
            """,
            (new_amt, now, int(user_id), str(item_key)),
        )
    return True


def _roll_single_reward(
    pool: Sequence[LootEntry],
    rng: random.Random,
    *,
    loot_context: Optional[Dict[str, Any]] = None,
) -> Reward:
    entries = inventory_loot.sanitize_loot_pool([e for e in pool if int(e.get("weight") or 0) > 0])
    if not entries:
        return {"reward_type": "item", "reward_key": "fragment_dna_common", "amount": 0}
    weights = [int(e["weight"]) for e in entries]
    pick = rng.choices(entries, weights=weights, k=1)[0]
    if loot_context:
        amount = inventory_loot.resolve_loot_entry_amount(
            pick,
            user_id=int(loot_context["user_id"]),
            container_key=str(loot_context["container_key"]),
            conn=loot_context["conn"],
            rng=rng,
            loot_context=loot_context,
        )
    else:
        lo = int(pick.get("min_amount") or 1)
        hi = int(pick.get("max_amount") or lo)
        if hi < lo:
            hi = lo
        amount = rng.randint(lo, hi)
    return {
        "reward_type": str(pick["reward_type"]),
        "reward_key": str(pick["reward_key"]),
        "amount": int(amount),
    }


def _reward_display_meta(rtype: str, rkey: str) -> Dict[str, Any]:
    if rtype == "ship":
        from .fleet_defs import canonical_ship_key, get_ship

        sk = canonical_ship_key(rkey)
        spec = get_ship(sk) or {}
        return {
            "name_key": str(spec.get("name_key") or f"fleet_ship_{sk}"),
            "rarity": "rare",
            "icon": "🛰️",
        }
    if rtype == "defense":
        from .defense_defs import DEFENSES

        spec = DEFENSES.get(rkey) or {}
        return {
            "name_key": str(spec.get("name_key") or f"defense_{rkey}"),
            "rarity": "uncommon",
            "icon": "🛡️",
        }
    if rtype in ("item", "booster") or rkey in GRANTABLE_ITEM_KEYS:
        meta = item_catalog_entry(rkey)
        return {
            "name_key": meta["name_key"],
            "rarity": meta["rarity"],
            "icon": meta["icon"],
        }
    if rtype == "resource":
        icons = {"metal": "⚙️", "crystal": "💎", "fuel_cells": "🔋"}
        names = {
            "metal": "resource_metal",
            "crystal": "resource_crystal",
            "fuel_cells": "resource_fuel_cells",
        }
        return {
            "name_key": names.get(rkey, rkey),
            "rarity": "common",
            "icon": icons.get(rkey, "📦"),
        }
    return {"name_key": rkey, "rarity": "common", "icon": "📦"}


def _reward_to_roll_preview_entry(reward: Reward) -> Dict[str, Any]:
    rtype = str(reward.get("reward_type") or "")
    rkey = str(reward.get("reward_key") or "")
    meta = _reward_display_meta(rtype, rkey)
    preview_type = rtype
    if rtype == "item":
        preview_type = "item"
    elif rtype == "booster":
        preview_type = "booster"
    return {
        "key": f"{rtype}:{rkey}",
        "name_key": str(reward.get("name_key") or meta["name_key"]),
        "amount": int(reward.get("amount") or 0),
        "rarity": str(reward.get("rarity") or meta.get("rarity") or "common"),
        "type": preview_type,
        "icon": str(reward.get("icon") or meta.get("icon") or "📦"),
    }


def _pool_entry_to_roll_preview(
    entry: LootEntry,
    rng: random.Random,
    *,
    loot_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rtype = str(entry.get("reward_type") or "")
    rkey = str(entry.get("reward_key") or "")
    if loot_context and inventory_loot.is_dynamic_loot_entry(entry):
        amount = inventory_loot.resolve_loot_entry_amount(
            entry,
            user_id=int(loot_context["user_id"]),
            container_key=str(loot_context["container_key"]),
            conn=loot_context["conn"],
            rng=rng,
            loot_context=loot_context,
        )
    else:
        lo = int(entry.get("min_amount") or 1)
        hi = int(entry.get("max_amount") or lo)
        if hi < lo:
            hi = lo
        amount = rng.randint(lo, hi)
    meta = _reward_display_meta(rtype, rkey)
    preview_type = rtype
    if rtype == "item":
        preview_type = "item"
    elif rtype == "booster":
        preview_type = "booster"
    return {
        "key": f"{rtype}:{rkey}",
        "name_key": meta["name_key"],
        "amount": amount,
        "rarity": str(meta.get("rarity") or "common"),
        "type": preview_type,
        "icon": str(meta.get("icon") or "📦"),
    }


_RARITY_RANK: Dict[str, int] = {
    "common": 0,
    "uncommon": 1,
    "rare": 2,
    "epic": 3,
    "legendary": 4,
    "mythic": 5,
}


def _pick_primary_reward(rewards: List[Reward]) -> Reward:
    """Primary tile for the roller — highest rarity, then highest amount."""
    positive = [r for r in rewards if int(r.get("amount") or 0) > 0]
    if not positive:
        return rewards[0] if rewards else {"reward_type": "item", "reward_key": "fragment_dna_common", "amount": 0}

    def _score(r: Reward) -> Tuple[int, int]:
        rarity = str(r.get("rarity") or "common")
        return (_RARITY_RANK.get(rarity, 0), int(r.get("amount") or 0))

    return max(positive, key=_score)


def _winning_reward_payload(reward: Reward) -> Dict[str, Any]:
    entry = _reward_to_roll_preview_entry(reward)
    rkey = str(reward.get("reward_key") or "")
    return {
        "key": rkey,
        "preview_key": str(entry["key"]),
        "name_key": str(entry["name_key"]),
        "amount": int(entry["amount"]),
        "rarity": str(entry["rarity"]),
        "type": str(entry["type"]),
        "icon": str(entry["icon"]),
    }


def build_roll_preview(
    rewards: List[Reward],
    pool: Sequence[LootEntry],
    rng: random.Random,
    *,
    loot_context: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    """UI-only roller strip; winning tile at winning_index matches the real primary reward."""
    primary = _pick_primary_reward(rewards)
    winning_entry = _reward_to_roll_preview_entry(primary)
    winning_reward = _winning_reward_payload(primary)

    real_entries = [
        _reward_to_roll_preview_entry(r)
        for r in rewards
        if int(r.get("amount") or 0) > 0
    ]
    other_reals = [e for e in real_entries if e["key"] != winning_entry["key"] or int(e["amount"]) != int(winning_entry["amount"])]

    pool_entries = [e for e in pool if int(e.get("weight") or 0) > 0]
    if not pool_entries:
        pool_entries = list(pool)
    weights = [int(e.get("weight") or 1) for e in pool_entries] if pool_entries else [1]

    total = rng.randint(ROLL_PREVIEW_MIN, ROLL_PREVIEW_MAX)
    min_win = max(ROLL_WINNING_INDEX_MIN, int(total * 2 / 3))
    max_win = min(ROLL_WINNING_INDEX_MAX, total - 1)
    if min_win > max_win:
        winning_index = total - 1
    else:
        winning_index = rng.randint(min_win, max_win)

    preview: List[Dict[str, Any]] = []
    for _ in range(total):
        if pool_entries:
            pick = rng.choices(pool_entries, weights=weights, k=1)[0]
            preview.append(_pool_entry_to_roll_preview(pick, rng, loot_context=loot_context))
        else:
            preview.append(dict(winning_entry))

    preview[winning_index] = dict(winning_entry)

    open_slots = [i for i in range(total) if i != winning_index]
    rng.shuffle(open_slots)
    for idx, entry in zip(open_slots, other_reals):
        preview[idx] = dict(entry)

    for entry in other_reals:
        if not any(
            p["key"] == entry["key"] and int(p["amount"]) == int(entry["amount"])
            for p in preview
        ):
            replace_idx = rng.choice(open_slots) if open_slots else winning_index
            if replace_idx != winning_index:
                preview[replace_idx] = dict(entry)

    return preview, winning_index, winning_reward


def _merge_rewards(rewards: List[Reward]) -> List[Reward]:
    merged: Dict[Tuple[str, str], int] = {}
    order: List[Tuple[str, str]] = []
    for r in rewards:
        key = (str(r["reward_type"]), str(r["reward_key"]))
        if key not in merged:
            order.append(key)
            merged[key] = 0
        merged[key] += int(r.get("amount") or 0)
    out: List[Reward] = []
    for rtype, rkey in order:
        amt = merged[(rtype, rkey)]
        if amt <= 0:
            continue
        entry: Reward = {"reward_type": rtype, "reward_key": rkey, "amount": amt}
        entry.update(_reward_display_meta(rtype, rkey))
        out.append(entry)
    return out


def _credit_planet_resources(
    planet_id: int,
    *,
    metal: int = 0,
    crystal: int = 0,
    fuel_cells: int = 0,
    conn,
) -> None:
    if metal <= 0 and crystal <= 0 and fuel_cells <= 0:
        return
    lock_planet_for_update(conn, int(planet_id))
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (
            float(row["metal"]) + float(metal),
            float(row["crystal"]) + float(crystal),
            float(row["fuel_cells"] or 0) + float(fuel_cells),
            int(planet_id),
        ),
    )


def _apply_rewards(
    user_id: int,
    planet_id: int,
    rewards: List[Reward],
    *,
    conn,
) -> None:
    _ = planet_id
    for r in rewards:
        rtype = str(r["reward_type"])
        rkey = str(r["reward_key"])
        amt = int(r.get("amount") or 0)
        if amt <= 0:
            continue
        # GC-864 — containers credit inventory meta rewards only.
        if rtype not in ("item", "booster"):
            continue
        if is_known_item_key(rkey):
            grant_inventory_item(user_id, rkey, amt, conn=conn)


def _log_container_open(
    user_id: int,
    planet_id: int,
    container_key: str,
    rewards: List[Reward],
    *,
    conn,
) -> None:
    conn.execute(
        """
        INSERT INTO container_open_log (user_id, planet_id, container_key, reward_json, created_at)
        VALUES (?, ?, ?, ?, ?);
        """,
        (
            int(user_id),
            int(planet_id),
            str(container_key),
            json.dumps(rewards),
            float(time.time()),
        ),
    )


def open_containers(
    user_id: int,
    planet_id: int,
    item_key: str,
    amount: int = 1,
    *,
    conn,
    rng: Optional[random.Random] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not inventory_schema_ready(conn):
        return False, "inventory_unavailable", None

    key = str(item_key or "").strip()
    if key not in CONTAINER_KEYS:
        return False, "invalid_container", None

    pool = inventory_loot.get_loot_pools(conn).get(key)
    if not pool:
        return False, "invalid_container", None

    try:
        open_count = int(amount)
    except (TypeError, ValueError):
        return False, "invalid_amount", None

    if open_count < 1:
        return False, "invalid_amount", None
    if open_count > 10:
        return False, "amount_too_high", None

    owned = _inventory_amount(user_id, key, conn=conn)
    free_basic_open = False

    if key == CONTAINER_BASIC_KEY:
        if open_count > 1:
            return False, "basic_open_once", None
        if owned < open_count:
            cooldown_seconds = basic_container_cooldown_remaining(user_id, conn=conn)
            if cooldown_seconds > 0:
                last = _last_container_open_at(user_id, key, conn=conn)
                next_open_at = float(last or time.time()) + float(CONTAINER_BASIC_COOLDOWN_SEC)
                return False, "container_cooldown", {
                    "container_key": key,
                    "cooldown_seconds": cooldown_seconds,
                    "next_open_at": next_open_at,
                }
            free_basic_open = True

    if not free_basic_open and owned < open_count:
        return False, "insufficient_containers", None

    roll_rng = rng or random.Random()
    loot_context = inventory_loot.build_loot_roll_context(user_id, key, conn=conn)
    rolled: List[Reward] = []
    for _ in range(open_count):
        rolled.append(_roll_single_reward(pool, roll_rng, loot_context=loot_context))
    rewards = _merge_rewards(rolled)

    if not free_basic_open and not _debit_inventory_item(user_id, key, open_count, conn=conn):
        return False, "insufficient_containers", None

    _apply_rewards(user_id, planet_id, rewards, conn=conn)
    _log_container_open(user_id, planet_id, key, rewards, conn=conn)

    container_meta = item_catalog_entry(key)
    preview_rng = random.Random(roll_rng.randint(0, 2**31 - 1))
    roll_preview, winning_index, winning_reward = build_roll_preview(
        rewards, pool, preview_rng, loot_context=loot_context
    )
    return True, "container_open_ok", {
        "opened": open_count,
        "container_key": key,
        "container_name_key": container_meta["name_key"],
        "container_rarity": container_meta["rarity"],
        "container_image": str(container_meta.get("image") or container_image_path(key)),
        "rewards": rewards,
        "roll_preview": roll_preview,
        "winning_index": winning_index,
        "winning_reward": winning_reward,
    }


def run_inventory_mutation(
    mutation_fn: Callable[[Any], MutationResult],
) -> MutationResult:
    """
    Run one inventory write mutation in a single transaction.

    Callers must build ``state`` / ``inventory`` only after this returns (conn closed).
    """
    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, result = mutation_fn(conn)
        if ok:
            commit(conn)
        else:
            rollback(conn)
        return ok, reason, result
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()
