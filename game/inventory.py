"""
GC-540 — Container inventory and weighted loot pools (server-authoritative).
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import begin_write_transaction, lock_planet_for_update, table_exists

LootEntry = Dict[str, Any]
Reward = Dict[str, Any]

CONTAINER_KEYS = frozenset(
    {
        "container_basic",
        "container_rare",
        "container_epic",
        "container_relic",
        "container_wreckage",
        "container_research_cache",
        "container_military_cache",
        "container_event_special",
    }
)

CONTAINER_DISPLAY_ORDER: Tuple[str, ...] = (
    "container_basic",
    "container_rare",
    "container_epic",
    "container_relic",
    "container_wreckage",
    "container_research_cache",
    "container_military_cache",
    "container_event_special",
)

CONTAINER_IMAGES: Dict[str, str] = {
    "container_basic": "img/lootboxes/Basic_Container.png",
    "container_rare": "img/lootboxes/Rare_Container.png",
    "container_epic": "img/lootboxes/Epic_Container.png",
    "container_relic": "img/lootboxes/Relic_Container.png",
    "container_wreckage": "img/lootboxes/Wreckage_Container.png",
    "container_research_cache": "img/lootboxes/Research_Cache.png",
    "container_military_cache": "img/lootboxes/Military_Cache.png",
    "container_event_special": "img/lootboxes/Event_Container.png",
}

ITEM_CATALOG: Dict[str, Dict[str, Any]] = {
    "container_basic": {
        "item_type": "container",
        "rarity": "common",
        "name_key": "inv_container_basic",
        "icon": "📦",
        "image": "img/lootboxes/Basic_Container.png",
    },
    "container_rare": {
        "item_type": "container",
        "rarity": "uncommon",
        "name_key": "inv_container_rare",
        "icon": "🎁",
        "image": "img/lootboxes/Rare_Container.png",
    },
    "container_epic": {
        "item_type": "container",
        "rarity": "epic",
        "name_key": "inv_container_epic",
        "icon": "💎",
        "image": "img/lootboxes/Epic_Container.png",
    },
    "container_relic": {
        "item_type": "container",
        "rarity": "legendary",
        "name_key": "inv_container_relic",
        "icon": "🏺",
        "image": "img/lootboxes/Relic_Container.png",
    },
    "container_wreckage": {
        "item_type": "container",
        "rarity": "uncommon",
        "name_key": "inv_container_wreckage",
        "icon": "🛸",
        "image": "img/lootboxes/Wreckage_Container.png",
    },
    "container_research_cache": {
        "item_type": "container",
        "rarity": "rare",
        "name_key": "inv_container_research_cache",
        "icon": "🔬",
        "image": "img/lootboxes/Research_Cache.png",
    },
    "container_military_cache": {
        "item_type": "container",
        "rarity": "rare",
        "name_key": "inv_container_military_cache",
        "icon": "⚔️",
        "image": "img/lootboxes/Military_Cache.png",
    },
    "container_event_special": {
        "item_type": "container",
        "rarity": "epic",
        "name_key": "inv_container_event_special",
        "icon": "✨",
        "image": "img/lootboxes/Event_Container.png",
    },
    "booster_build_15": {
        "item_type": "booster",
        "rarity": "uncommon",
        "name_key": "inv_booster_build_15",
        "icon": "🔧",
    },
    "booster_build_30": {
        "item_type": "booster",
        "rarity": "rare",
        "name_key": "inv_booster_build_30",
        "icon": "🔧",
    },
    "booster_build_60": {
        "item_type": "booster",
        "rarity": "epic",
        "name_key": "inv_booster_build_60",
        "icon": "🔧",
    },
    "booster_research_15": {
        "item_type": "booster",
        "rarity": "uncommon",
        "name_key": "inv_booster_research_15",
        "icon": "📡",
    },
    "booster_research_30": {
        "item_type": "booster",
        "rarity": "rare",
        "name_key": "inv_booster_research_30",
        "icon": "📡",
    },
    "booster_research_60": {
        "item_type": "booster",
        "rarity": "epic",
        "name_key": "inv_booster_research_60",
        "icon": "📡",
    },
    "fragment_artifact_alpha": {
        "item_type": "fragment",
        "rarity": "rare",
        "name_key": "inv_fragment_artifact_alpha",
        "icon": "🧩",
    },
    "artifact_core_fragment": {
        "item_type": "fragment",
        "rarity": "legendary",
        "name_key": "inv_artifact_core_fragment",
        "icon": "🧩",
    },
    "placeholder_special_item": {
        "item_type": "special",
        "rarity": "legendary",
        "name_key": "inv_placeholder_special_item",
        "icon": "⭐",
    },
}

LOOT_POOLS: Dict[str, List[LootEntry]] = {
    "container_basic": [
        {"weight": 35, "reward_type": "resource", "reward_key": "metal", "min_amount": 500, "max_amount": 2000},
        {"weight": 35, "reward_type": "resource", "reward_key": "crystal", "min_amount": 500, "max_amount": 2000},
        {"weight": 25, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 10, "max_amount": 50},
        {"weight": 5, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_rare": [
        {"weight": 30, "reward_type": "resource", "reward_key": "metal", "min_amount": 3000, "max_amount": 8000},
        {"weight": 30, "reward_type": "resource", "reward_key": "crystal", "min_amount": 3000, "max_amount": 8000},
        {"weight": 20, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 50, "max_amount": 150},
        {"weight": 10, "reward_type": "booster", "reward_key": "booster_build_15", "min_amount": 1, "max_amount": 1},
        {"weight": 7, "reward_type": "booster", "reward_key": "booster_research_15", "min_amount": 1, "max_amount": 1},
        {"weight": 3, "reward_type": "item", "reward_key": "container_epic", "min_amount": 1, "max_amount": 1},
    ],
    "container_epic": [
        {"weight": 25, "reward_type": "resource", "reward_key": "metal", "min_amount": 10000, "max_amount": 25000},
        {"weight": 25, "reward_type": "resource", "reward_key": "crystal", "min_amount": 10000, "max_amount": 25000},
        {"weight": 15, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 200, "max_amount": 500},
        {"weight": 12, "reward_type": "booster", "reward_key": "booster_build_30", "min_amount": 1, "max_amount": 1},
        {"weight": 12, "reward_type": "booster", "reward_key": "booster_research_30", "min_amount": 1, "max_amount": 1},
        {"weight": 8, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 1},
        {"weight": 3, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
    ],
    "container_relic": [
        {"weight": 20, "reward_type": "resource", "reward_key": "metal", "min_amount": 50000, "max_amount": 100000},
        {"weight": 20, "reward_type": "resource", "reward_key": "crystal", "min_amount": 50000, "max_amount": 100000},
        {"weight": 15, "reward_type": "booster", "reward_key": "booster_build_60", "min_amount": 1, "max_amount": 1},
        {"weight": 15, "reward_type": "booster", "reward_key": "booster_research_60", "min_amount": 1, "max_amount": 1},
        {"weight": 15, "reward_type": "item", "reward_key": "artifact_core_fragment", "min_amount": 1, "max_amount": 1},
        {"weight": 15, "reward_type": "item", "reward_key": "placeholder_special_item", "min_amount": 1, "max_amount": 1},
    ],
    "container_wreckage": [
        {"weight": 40, "reward_type": "resource", "reward_key": "metal", "min_amount": 2000, "max_amount": 6000},
        {"weight": 30, "reward_type": "resource", "reward_key": "crystal", "min_amount": 1000, "max_amount": 4000},
        {"weight": 20, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 30, "max_amount": 100},
        {"weight": 10, "reward_type": "item", "reward_key": "container_rare", "min_amount": 1, "max_amount": 1},
    ],
    "container_research_cache": [
        {"weight": 35, "reward_type": "resource", "reward_key": "crystal", "min_amount": 4000, "max_amount": 9000},
        {"weight": 30, "reward_type": "booster", "reward_key": "booster_research_15", "min_amount": 1, "max_amount": 1},
        {"weight": 20, "reward_type": "booster", "reward_key": "booster_research_30", "min_amount": 1, "max_amount": 1},
        {"weight": 15, "reward_type": "item", "reward_key": "fragment_artifact_alpha", "min_amount": 1, "max_amount": 1},
    ],
    "container_military_cache": [
        {"weight": 35, "reward_type": "resource", "reward_key": "metal", "min_amount": 5000, "max_amount": 12000},
        {"weight": 30, "reward_type": "booster", "reward_key": "booster_build_15", "min_amount": 1, "max_amount": 1},
        {"weight": 20, "reward_type": "booster", "reward_key": "booster_build_30", "min_amount": 1, "max_amount": 1},
        {"weight": 15, "reward_type": "resource", "reward_key": "fuel_cells", "min_amount": 80, "max_amount": 200},
    ],
    "container_event_special": [
        {"weight": 30, "reward_type": "resource", "reward_key": "metal", "min_amount": 8000, "max_amount": 18000},
        {"weight": 30, "reward_type": "resource", "reward_key": "crystal", "min_amount": 8000, "max_amount": 18000},
        {"weight": 20, "reward_type": "booster", "reward_key": "booster_build_30", "min_amount": 1, "max_amount": 1},
        {"weight": 15, "reward_type": "item", "reward_key": "placeholder_special_item", "min_amount": 1, "max_amount": 1},
        {"weight": 5, "reward_type": "item", "reward_key": "container_relic", "min_amount": 1, "max_amount": 1},
    ],
}


def inventory_schema_ready(conn) -> bool:
    return table_exists(conn, "player_inventory_items") and table_exists(conn, "container_open_log")


def container_image_path(item_key: str) -> str:
    key = str(item_key)
    return str(
        CONTAINER_IMAGES.get(key)
        or (ITEM_CATALOG.get(key) or {}).get("image")
        or "img/lootboxes/Generic_Supply_Container.png"
    )


def item_catalog_entry(item_key: str) -> Dict[str, Any]:
    spec = ITEM_CATALOG.get(str(item_key)) or {}
    key = str(item_key)
    entry = {
        "item_key": key,
        "item_type": str(spec.get("item_type") or "item"),
        "rarity": str(spec.get("rarity") or "common"),
        "name_key": str(spec.get("name_key") or f"inv_item_{item_key}"),
        "icon": str(spec.get("icon") or "📦"),
    }
    if key in CONTAINER_KEYS or spec.get("image"):
        entry["image"] = container_image_path(key)
    return entry


def _serialize_inventory_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    key = str(row["item_key"])
    meta = item_catalog_entry(key)
    out = {
        "id": int(row["id"]),
        "item_key": key,
        "item_type": str(row["item_type"] or meta["item_type"]),
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


def build_container_catalog(owned: Optional[Mapping[str, Mapping[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Full container roster for UI — owned amounts merged, missing entries show 0."""
    owned_map = owned or {}
    catalog: List[Dict[str, Any]] = []
    for key in CONTAINER_DISPLAY_ORDER:
        if key not in CONTAINER_KEYS:
            continue
        meta = item_catalog_entry(key)
        row = owned_map.get(key)
        amount = int((row or {}).get("amount") or 0)
        catalog.append(
            {
                "item_key": key,
                "item_type": "container",
                "rarity": meta["rarity"],
                "amount": amount,
                "name_key": meta["name_key"],
                "icon": meta["icon"],
                "image": meta.get("image") or container_image_path(key),
                "owned": amount > 0,
            }
        )
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
    owned_containers = {
        str(i["item_key"]): i for i in items if i["item_type"] == "container"
    }
    containers = build_container_catalog(owned_containers)
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
        entry: Reward = {
            "reward_type": rtype,
            "reward_key": rkey,
            "amount": amt,
        }
        if rtype in ("item", "booster"):
            meta = item_catalog_entry(rkey)
            entry["name_key"] = meta["name_key"]
            entry["rarity"] = meta["rarity"]
            entry["icon"] = meta["icon"]
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
    metal = crystal = fuel_cells = 0
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
        elif rtype in ("item", "booster"):
            grant_inventory_item(user_id, rkey, amt, conn=conn)
    _credit_planet_resources(
        planet_id,
        metal=metal,
        crystal=crystal,
        fuel_cells=fuel_cells,
        conn=conn,
    )


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
    """
    Open one or more containers. Returns (ok, reason, result).
    Caller must manage transaction boundaries.
    """
    if not inventory_schema_ready(conn):
        return False, "inventory_unavailable", None

    key = str(item_key or "").strip()
    if key not in CONTAINER_KEYS:
        return False, "invalid_container", None

    pool = LOOT_POOLS.get(key)
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
