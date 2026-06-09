"""
GC-540 — Container inventory and weighted loot pools (server-authoritative).
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import lock_planet_for_update, table_exists
from .inventory_catalog import (
    CONTAINER_BASIC_COOLDOWN_SEC,
    CONTAINER_BASIC_KEY,
    CONTAINER_DISPLAY_ORDER,
    CONTAINER_KEYS,
    GRANTABLE_ITEM_KEYS,
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
    "grant_inventory_item",
    "inventory_schema_ready",
    "is_known_item_key",
    "item_catalog_entry",
    "list_player_inventory",
    "open_containers",
]


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
    if key == CONTAINER_BASIC_KEY:
        max_open = 1
        if user_id is not None and conn is not None:
            cooldown_seconds = basic_container_cooldown_remaining(int(user_id), conn=conn)
            cooldown_active = cooldown_seconds > 0
            # Cooldown limits the free daily open — owned stock can always be opened.
            open_blocked = cooldown_active and amount <= 0
    entry["max_open_amount"] = max_open
    entry["cooldown_seconds"] = cooldown_seconds
    entry["cooldown_active"] = cooldown_active
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


def build_inventory_state(user_id: int, *, conn) -> Dict[str, Any]:
    items = list_player_inventory(user_id, conn=conn)
    owned_containers = {str(i["item_key"]): i for i in items if i["item_type"] == "container"}
    containers = build_container_catalog(owned_containers, user_id=int(user_id), conn=conn)
    other_items = [i for i in items if i["item_type"] != "container"]
    return {
        "ready": inventory_schema_ready(conn),
        "containers": containers,
        "other_items": other_items,
        "all": items,
    }


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


def _roll_single_reward(pool: Sequence[LootEntry], rng: random.Random) -> Reward:
    entries = [e for e in pool if int(e.get("weight") or 0) > 0]
    if not entries:
        return {"reward_type": "resource", "reward_key": "metal", "amount": 0}
    weights = [int(e["weight"]) for e in entries]
    pick = rng.choices(entries, weights=weights, k=1)[0]
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
    from .fleet import add_planet_ships
    from .fleet_defs import canonical_ship_key, is_known_ship_key
    from .models import add_planet_defense
    from .defense_defs import is_known_defense_key

    metal = crystal = fuel_cells = 0
    ships: Dict[str, int] = {}
    defense: Dict[str, int] = {}

    for r in rewards:
        rtype = str(r["reward_type"])
        rkey = str(r["reward_key"])
        amt = int(r.get("amount") or 0)
        if amt <= 0:
            continue
        if rtype == "resource":
            if rkey == "metal":
                metal += amt
            elif rkey == "crystal":
                crystal += amt
            elif rkey == "fuel_cells":
                fuel_cells += amt
        elif rtype == "ship":
            sk = canonical_ship_key(rkey)
            if is_known_ship_key(sk):
                ships[sk] = ships.get(sk, 0) + amt
        elif rtype == "defense":
            if is_known_defense_key(rkey):
                defense[rkey] = defense.get(rkey, 0) + amt
        elif rtype in ("item", "booster") and is_known_item_key(rkey):
            grant_inventory_item(user_id, rkey, amt, conn=conn)

    _credit_planet_resources(
        planet_id,
        metal=metal,
        crystal=crystal,
        fuel_cells=fuel_cells,
        conn=conn,
    )
    if ships:
        add_planet_ships(int(planet_id), int(user_id), ships, conn=conn)
    if defense:
        add_planet_defense(int(planet_id), defense, conn=conn)


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

    pool = inventory_loot.LOOT_POOLS.get(key)
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
            return False, "insufficient_containers", None

    if owned < open_count:
        return False, "insufficient_containers", None

    roll_rng = rng or random.Random()
    rolled: List[Reward] = []
    for _ in range(open_count):
        rolled.append(_roll_single_reward(pool, roll_rng))
    rewards = _merge_rewards(rolled)

    if not _debit_inventory_item(user_id, key, open_count, conn=conn):
        return False, "insufficient_containers", None

    _apply_rewards(user_id, planet_id, rewards, conn=conn)
    _log_container_open(user_id, planet_id, key, rewards, conn=conn)

    inventory = build_inventory_state(user_id, conn=conn)
    return True, "container_open_ok", {
        "opened": open_count,
        "container_key": key,
        "rewards": rewards,
        "inventory": inventory,
    }
