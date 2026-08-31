"""
GC-965A/B — Collector Exchange (read state + redeem).

Offers: game/collector_catalog.py. Redeem grants via inventory.py / shipyard.py.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from game.collector_catalog import (
    COLLECTOR_OFFERS,
    flatten_reward_preview,
    get_collector_offer,
    is_prestige_only_item,
    is_valid_collector_input_key,
    list_collector_offers,
    list_collector_specialists,
    offer_rewards_are_redeemable,
)
from game.db import table_exists
from game.inventory import consume_inventory_item, grant_inventory_item, inventory_amount, inventory_schema_ready
from game.inventory_catalog import is_known_item_key, item_catalog_entry
from game.queue_engine import finish_due_work_once

COLLECTOR_SCHEMA_TABLES = (
    "collector_lifetime_stats",
    "collector_exchange_log",
    "collector_exchange_redemptions",
)

GrantedReward = Dict[str, Any]
MutationResult = Tuple[bool, str, Optional[Dict[str, Any]]]


def collector_schema_ready(conn) -> bool:
    return all(table_exists(conn, name) for name in COLLECTOR_SCHEMA_TABLES)


def compute_progress_pct(owned: int, input_amount: int) -> int:
    """Server-side progress for collector offers (0–100 inclusive)."""
    owned_i = max(0, int(owned))
    required = int(input_amount)
    if required <= 0:
        return 0
    if owned_i >= required:
        return 100
    return int((owned_i * 100) // required)


def compute_can_redeem(
    owned: int,
    *,
    input_amount: int,
    enabled: bool = True,
    input_key: str = "",
) -> bool:
    if not enabled:
        return False
    if not is_valid_collector_input_key(input_key):
        return False
    if is_prestige_only_item(input_key):
        return False
    return int(owned) >= int(input_amount) > 0


def build_offer_state(
    offer_key: str,
    offer: Mapping[str, Any],
    *,
    owned: int,
) -> Dict[str, Any]:
    input_key = str(offer.get("input_key") or "")
    input_amount = int(offer.get("input_amount") or 0)
    enabled = bool(offer.get("enabled", True))
    owned_i = max(0, int(owned))
    rewards = list(offer.get("rewards") or [])
    rewards_ready = offer_rewards_are_redeemable(offer)
    base_can_redeem = compute_can_redeem(
        owned_i,
        input_amount=input_amount,
        enabled=enabled,
        input_key=input_key,
    )
    catalog = item_catalog_entry(input_key) if input_key else {}
    input_image = str(catalog.get("image") or "").strip() or None
    input_icon = str(catalog.get("icon") or "").strip() or None
    return {
        "offer_key": str(offer_key),
        "specialist_key": str(offer.get("specialist_key") or ""),
        "input_key": input_key,
        "input_amount": input_amount,
        "input_image": input_image,
        "input_icon": input_icon,
        "owned": owned_i,
        "progress_pct": compute_progress_pct(owned_i, input_amount),
        "can_redeem": bool(base_can_redeem and rewards_ready),
        "rewards_ready": rewards_ready,
        "lock_reason_key": "" if rewards_ready else "collector_offer_locked_planned",
        "enabled": enabled,
        "reward_preview": flatten_reward_preview(rewards),
        "name_key": str(offer.get("name_key") or f"collector_offer_{offer_key}"),
        "title_key": f"collector_offer_{offer_key}_title",
        "desc_key": f"collector_offer_{offer_key}_desc",
        "reward_line_key": f"collector_offer_{offer_key}_reward",
        "category_key": str(offer.get("category_key") or "collector_cat_misc"),
        "sort": int(offer.get("sort") or 0),
    }


def sort_offers_for_display(offers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Display order: redeemable first, then highest progress, then catalog sort."""
    return sorted(
        offers,
        key=lambda row: (
            0 if row.get("can_redeem") else 1,
            -int(row.get("progress_pct") or 0),
            int(row.get("sort") or 0),
            str(row.get("offer_key") or ""),
        ),
    )


def _collector_input_keys() -> List[str]:
    keys = sorted({str(o.get("input_key") or "") for o in COLLECTOR_OFFERS.values() if o.get("input_key")})
    return keys


def get_inventory_owned_map(user_id: int, *, conn) -> Dict[str, int]:
    """Account inventory amounts for all collector offer inputs."""
    if not table_exists(conn, "player_inventory_items"):
        return {key: 0 for key in _collector_input_keys()}

    keys = _collector_input_keys()
    if not keys:
        return {}

    placeholders = ",".join("?" for _ in keys)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT item_key, amount
        FROM player_inventory_items
        WHERE user_id = ? AND planet_id IS NULL AND item_key IN ({placeholders})
        """,
        [int(user_id), *keys],
    )
    rows = cur.fetchall()
    owned = {key: 0 for key in keys}
    for row in rows:
        owned[str(row["item_key"])] = max(0, int(row["amount"] or 0))
    return owned


def get_owned_for_offer(user_id: int, offer: Mapping[str, Any], *, conn, owned_map: Optional[Mapping[str, int]] = None) -> int:
    input_key = str(offer.get("input_key") or "")
    amounts = owned_map if owned_map is not None else get_inventory_owned_map(user_id, conn=conn)
    return max(0, int(amounts.get(input_key) or 0))


def build_collector_exchange_payload(user_id: int, *, conn) -> Dict[str, Any]:
    if not collector_schema_ready(conn):
        return {"ready": False, "specialists": []}

    owned_map = get_inventory_owned_map(int(user_id), conn=conn)
    specialists_out: List[Dict[str, Any]] = []

    for specialist in list_collector_specialists():
        specialist_key = str(specialist.get("specialist_key") or "")
        offers_out: List[Dict[str, Any]] = []
        for offer_row in list_collector_offers(specialist_key=specialist_key):
            offer_key = str(offer_row.get("offer_key") or "")
            owned = max(0, int(owned_map.get(str(offer_row.get("input_key") or "")) or 0))
            offers_out.append(build_offer_state(offer_key, offer_row, owned=owned))
        offers_out = sort_offers_for_display(offers_out)
        specialists_out.append(
            {
                "specialist_key": specialist_key,
                "name_key": str(specialist.get("name_key") or ""),
                "icon": str(specialist.get("icon") or ""),
                "description_key": str(specialist.get("description_key") or ""),
                "sort": int(specialist.get("sort") or 0),
                "offers": offers_out,
            }
        )

    return {
        "ready": True,
        "specialists": specialists_out,
    }


def get_offer_state(user_id: int, offer_key: str, *, conn) -> Optional[Dict[str, Any]]:
    offer = get_collector_offer(offer_key)
    if not offer:
        return None
    owned = get_owned_for_offer(int(user_id), offer, conn=conn)
    return build_offer_state(str(offer_key), offer, owned=owned)


def list_all_offer_states(user_id: int, *, conn) -> List[Dict[str, Any]]:
    owned_map = get_inventory_owned_map(int(user_id), conn=conn)
    out: List[Dict[str, Any]] = []
    for offer_key, offer in COLLECTOR_OFFERS.items():
        owned = max(0, int(owned_map.get(str(offer.get("input_key") or "")) or 0))
        out.append(build_offer_state(offer_key, offer, owned=owned))
    out.sort(key=lambda row: (str(row.get("specialist_key") or ""), int(row.get("sort") or 0), str(row.get("offer_key") or "")))
    return out


def record_lifetime_acquired(user_id: int, item_key: str, amount: int, *, conn) -> None:
    if not collector_schema_ready(conn):
        return
    key = str(item_key or "").strip()
    amt = int(amount)
    if not key or amt <= 0:
        return
    now = float(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO collector_lifetime_stats (
            user_id, item_key, lifetime_acquired, lifetime_redeemed, updated_at
        ) VALUES (?, ?, ?, 0, ?)
        ON CONFLICT(user_id, item_key) DO UPDATE SET
            lifetime_acquired = collector_lifetime_stats.lifetime_acquired + excluded.lifetime_acquired,
            updated_at = excluded.updated_at;
        """,
        (int(user_id), key, amt, now),
    )


def record_lifetime_redeemed(user_id: int, item_key: str, amount: int, *, conn) -> None:
    if not collector_schema_ready(conn):
        return
    key = str(item_key or "").strip()
    amt = int(amount)
    if not key or amt <= 0:
        return
    now = float(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO collector_lifetime_stats (
            user_id, item_key, lifetime_acquired, lifetime_redeemed, updated_at
        ) VALUES (?, ?, 0, ?, ?)
        ON CONFLICT(user_id, item_key) DO UPDATE SET
            lifetime_redeemed = collector_lifetime_stats.lifetime_redeemed + excluded.lifetime_redeemed,
            updated_at = excluded.updated_at;
        """,
        (int(user_id), key, amt, now),
    )


def get_lifetime_stats(user_id: int, *, conn) -> Dict[str, Dict[str, int]]:
    if not collector_schema_ready(conn):
        return {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT item_key, lifetime_acquired, lifetime_redeemed
        FROM collector_lifetime_stats
        WHERE user_id = ?;
        """,
        (int(user_id),),
    )
    out: Dict[str, Dict[str, int]] = {}
    for row in cur.fetchall():
        key = str(row["item_key"])
        out[key] = {
            "lifetime_acquired": max(0, int(row["lifetime_acquired"] or 0)),
            "lifetime_redeemed": max(0, int(row["lifetime_redeemed"] or 0)),
        }
    return out


def _find_redemption_by_request(user_id: int, request_id: str, *, conn) -> Optional[Dict[str, Any]]:
    rid = str(request_id or "").strip()
    if not rid or not collector_schema_ready(conn):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT offer_key, input_key, input_amount, rewards_json
        FROM collector_exchange_redemptions
        WHERE user_id = ? AND request_id = ?
        LIMIT 1;
        """,
        (int(user_id), rid),
    )
    row = cur.fetchone()
    if not row:
        return None
    try:
        rewards = json.loads(str(row["rewards_json"] or "[]"))
    except json.JSONDecodeError:
        rewards = []
    return {
        "offer_key": str(row["offer_key"]),
        "input_key": str(row["input_key"]),
        "input_amount": int(row["input_amount"] or 0),
        "rewards": rewards if isinstance(rewards, list) else [],
        "idempotent_replay": True,
    }


def _roll_weighted_pool(pool: List[Mapping[str, Any]], rng: random.Random, *, ship: bool) -> Dict[str, Any]:
    entries = [e for e in pool if int(e.get("weight") or 0) > 0]
    if not entries:
        raise ValueError("empty_weighted_pool")
    weights = [int(e.get("weight") or 0) for e in entries]
    pick = rng.choices(entries, weights=weights, k=1)[0]
    if ship:
        return {
            "reward_type": "ship",
            "reward_key": str(pick.get("ship_key") or ""),
            "amount": int(pick.get("amount") or 0),
        }
    return {
        "reward_type": "item",
        "reward_key": str(pick.get("reward_key") or ""),
        "amount": int(pick.get("amount") or 0),
    }


def resolve_offer_grants(offer: Mapping[str, Any], *, rng: Optional[random.Random] = None) -> List[GrantedReward]:
    """Resolve catalog rewards to concrete grant rows (rolls weighted pools once)."""
    roll = rng or random.Random()
    grants: List[GrantedReward] = []
    for reward in offer.get("rewards") or []:
        if not isinstance(reward, dict):
            continue
        rtype = str(reward.get("reward_type") or "")
        if rtype == "item_weighted":
            grants.append(_roll_weighted_pool(list(reward.get("pool") or []), roll, ship=False))
        elif rtype == "ship_weighted":
            grants.append(_roll_weighted_pool(list(reward.get("pool") or []), roll, ship=True))
        elif rtype == "ship":
            grants.append(
                {
                    "reward_type": "ship",
                    "reward_key": str(reward.get("ship_key") or reward.get("reward_key") or ""),
                    "amount": int(reward.get("amount") or 0),
                }
            )
        else:
            grants.append(
                {
                    "reward_type": rtype,
                    "reward_key": str(reward.get("reward_key") or ""),
                    "amount": int(reward.get("amount") or 0),
                }
            )
    return [g for g in grants if int(g.get("amount") or 0) > 0 and str(g.get("reward_key") or "")]


def _apply_granted_rewards(
    user_id: int,
    player_id: int,
    planet_id: int,
    grants: List[GrantedReward],
    *,
    conn,
) -> Tuple[bool, str]:
    from game.shipyard import add_ships_to_planet

    for grant in grants:
        rtype = str(grant.get("reward_type") or "")
        key = str(grant.get("reward_key") or "")
        amount = int(grant.get("amount") or 0)
        if amount <= 0 or not key:
            return False, "invalid_reward"

        if rtype == "ship":
            ok, reason, _ships = add_ships_to_planet(
                int(player_id),
                int(planet_id),
                key,
                amount,
                conn=conn,
            )
            if not ok:
                return False, reason or "ship_grant_failed"
            continue

        if rtype in ("item", "booster", "container"):
            if not is_known_item_key(key):
                return False, "unknown_reward_item"
            if not grant_inventory_item(int(user_id), key, amount, conn=conn):
                return False, "reward_grant_failed"
            continue

        return False, "unsupported_reward_type"
    return True, "ok"


def redeem_collector_offer(
    user_id: int,
    offer_key: str,
    *,
    conn,
    request_id: str = "",
    planet_id: Optional[int] = None,
    player_id: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> MutationResult:
    if not collector_schema_ready(conn):
        return False, "collector_exchange_unavailable", None
    if not inventory_schema_ready(conn):
        return False, "inventory_unavailable", None

    finish_due_work_once(player_id=int(player_id or user_id), planet_id=planet_id, conn=conn, manage_transaction=False)

    rid = str(request_id or "").strip()
    if rid:
        existing = _find_redemption_by_request(int(user_id), rid, conn=conn)
        if existing:
            return True, "collector_redeem_ok", existing

    okey = str(offer_key or "").strip()
    offer = get_collector_offer(okey)
    if not offer:
        return False, "offer_not_found", None
    if not bool(offer.get("enabled", True)):
        return False, "offer_disabled", None
    if not offer_rewards_are_redeemable(offer):
        return False, "offer_rewards_locked", None

    input_key = str(offer.get("input_key") or "")
    input_amount = int(offer.get("input_amount") or 0)
    owned = inventory_amount(int(user_id), input_key, conn=conn)
    if not compute_can_redeem(
        owned,
        input_amount=input_amount,
        enabled=bool(offer.get("enabled", True)),
        input_key=input_key,
    ):
        return False, "insufficient_items", {"offer_key": okey, "owned": owned, "input_amount": input_amount}

    if planet_id is None or player_id is None:
        return False, "planet_required", None

    if not consume_inventory_item(int(user_id), input_key, input_amount, conn=conn):
        return False, "insufficient_items", None

    try:
        grants = resolve_offer_grants(offer, rng=rng)
    except ValueError:
        grants = []

    if not grants:
        return False, "invalid_offer_rewards", None

    ok, reason = _apply_granted_rewards(
        int(user_id),
        int(player_id),
        int(planet_id),
        grants,
        conn=conn,
    )
    if not ok:
        return False, reason or "reward_grant_failed", None

    record_lifetime_redeemed(int(user_id), input_key, input_amount, conn=conn)

    now = float(time.time())
    rewards_json = json.dumps(grants)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO collector_exchange_log (
            user_id, offer_key, input_key, input_amount, rewards_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (int(user_id), okey, input_key, input_amount, rewards_json, now),
    )
    if rid:
        cur.execute(
            """
            INSERT INTO collector_exchange_redemptions (
                user_id, offer_key, request_id, input_key, input_amount, rewards_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (int(user_id), okey, rid, input_key, input_amount, rewards_json, now),
        )

    return True, "collector_redeem_ok", {
        "offer_key": okey,
        "input_key": input_key,
        "input_amount": input_amount,
        "rewards": grants,
    }
