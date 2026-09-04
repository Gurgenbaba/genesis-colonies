"""
GC-550 — Lootbox auction house (server-authoritative, context-planet resources).

Event boxes are never offered: no event_container, no is_event boxes, no event_* keys.
"""

from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import (
    begin_write_transaction,
    commit,
    db,
    lock_planet_for_update,
    rollback,
    tables_exist,
)
from .inventory import grant_inventory_item, inventory_schema_ready
from .inventory_catalog import ITEM_CATALOG, item_catalog_entry
from .models import resource_db_param, table_exists
from .player_display import commander_display_name

AUCTION_CURRENCIES = ("metal", "crystal", "fuel_cells")

ACTIVE_AUCTION_TARGET = 3
MIN_DURATION_SEC = 6 * 3600
MAX_DURATION_SEC = 12 * 3600
ROTATION_INTERVAL_SECONDS = 6 * 3600
MIN_BID_INCREASE_BPS = 500
MIN_BID_INCREASE_PCT = MIN_BID_INCREASE_BPS / 10_000
MAX_BIDS_PER_PLAYER_PER_LISTING = 25

# Ticket box keys → canonical inventory container keys (GC-540).
BOX_INVENTORY_MAP: Dict[str, str] = {
    "generic_supply_container": "container_basic",
    "resource_cache": "container_rare",
    "research_capsule": "container_research_cache",
    "wreckage_container": "container_wreckage",
    "military_cache": "container_military_cache",
    "alien_cache": "container_epic",
    "premium_cache": "container_relic",
    "mythic_container": "container_mythic",
    "ancient_relic": "container_ancient_relic",
    "void_artifact": "container_void_artifact",
    "birthday_gift_container": "container_epic",
}

# Rotation weights (event boxes: 0 %).
ROTATION_WEIGHTS: Dict[str, int] = {
    "generic_supply_container": 45,
    "resource_cache": 25,
    "wreckage_container": 15,
    "research_capsule": 8,
    "military_cache": 5,
    "alien_cache": 1,
    "premium_cache": 1,
}

START_PRICE_BY_RARITY: Dict[str, int] = {
    "common": 50_000,
    "uncommon": 120_000,
    "rare": 300_000,
    "epic": 750_000,
    "legendary": 1_500_000,
}


def auction_schema_ready(conn) -> bool:
    return tables_exist(
        conn,
        ("lootbox_inventory", "auction_house_listings", "auction_house_bids"),
    )


def auction_visits_schema_ready(conn) -> bool:
    return table_exists(conn, "auction_house_player_visits")


def mark_auction_house_visited(
    player_id: int,
    *,
    conn,
    now: float | None = None,
) -> None:
    """Record that the player opened the auction house (clears 'new listing' badge)."""
    if not auction_visits_schema_ready(conn):
        return
    pid = int(player_id)
    if pid <= 0:
        return
    ts = int(now if now is not None else time.time())
    conn.execute(
        """
        INSERT INTO auction_house_player_visits (player_id, last_visited_at)
        VALUES (?, ?)
        ON CONFLICT(player_id) DO UPDATE SET last_visited_at = excluded.last_visited_at;
        """,
        (pid, ts),
    )


def count_auction_nav_attention(player_id: int, *, conn=None) -> int:
    """
    Nav badge count: outbid lots + new active listings since last visit.

    Never-visited players get attention for any active listing (discoverability).
    The Diet/nav path intentionally returns only scalar counts and performs one
    data SELECT after the schema readiness checks.
    """
    own = conn is None
    if own:
        conn = db()
    try:
        if not auction_schema_ready(conn):
            return 0
        pid = int(player_id)
        if pid <= 0:
            return 0
        now_i = int(time.time())
        cur = conn.cursor()

        if auction_visits_schema_ready(conn):
            cur.execute(
                """
                WITH visit AS (
                    SELECT last_visited_at
                    FROM auction_house_player_visits
                    WHERE player_id = ?
                    LIMIT 1
                )
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM auction_house_listings l
                        WHERE l.status = 'active'
                          AND l.ends_at > ?
                          AND l.current_bidder_id IS NOT NULL
                          AND l.current_bidder_id != ?
                          AND EXISTS (
                              SELECT 1
                              FROM auction_house_bids b
                              WHERE b.listing_id = l.id
                                AND b.player_id = ?
                          )
                    ) AS outbid,
                    (
                        SELECT COUNT(*)
                        FROM auction_house_listings n
                        WHERE n.status = 'active'
                          AND n.ends_at > ?
                          AND (
                              NOT EXISTS (SELECT 1 FROM visit)
                              OR n.created_at > COALESCE(
                                  (SELECT last_visited_at FROM visit LIMIT 1),
                                  0
                              )
                          )
                    ) AS new_listings;
                """,
                (pid, now_i, pid, pid, now_i),
            )
        else:
            cur.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM auction_house_listings l
                        WHERE l.status = 'active'
                          AND l.ends_at > ?
                          AND l.current_bidder_id IS NOT NULL
                          AND l.current_bidder_id != ?
                          AND EXISTS (
                              SELECT 1
                              FROM auction_house_bids b
                              WHERE b.listing_id = l.id
                                AND b.player_id = ?
                          )
                    ) AS outbid,
                    (
                        SELECT COUNT(*)
                        FROM auction_house_listings n
                        WHERE n.status = 'active'
                          AND n.ends_at > ?
                    ) AS new_listings;
                """,
                (now_i, pid, pid, now_i),
            )

        row = cur.fetchone()
        return int(row["outbid"] or 0) + int(row["new_listings"] or 0)
    finally:
        if own and conn is not None:
            conn.close()

def resolve_inventory_key(box_key: str) -> Optional[str]:
    key = str(box_key or "").strip()
    if key in BOX_INVENTORY_MAP:
        return BOX_INVENTORY_MAP[key]
    if key in ITEM_CATALOG and str(ITEM_CATALOG[key].get("item_type") or "") == "container":
        return key
    return None


def is_event_box(box_key: str) -> bool:
    key = str(box_key or "").strip()
    if not key:
        return False
    if key in ("event_container", "container_event_special"):
        return True
    if key.startswith("event_"):
        return True
    inv_key = resolve_inventory_key(key) or key
    spec = ITEM_CATALOG.get(inv_key) or {}
    if bool(spec.get("is_event")):
        return True
    if str(spec.get("category") or "") == "event":
        return True
    return False


def is_auction_allowed_box(box_key: str) -> bool:
    key = str(box_key or "").strip()
    if not key or is_event_box(key):
        return False
    if key == "birthday_gift_container":
        return False
    return key in ROTATION_WEIGHTS or key in BOX_INVENTORY_MAP


def _weighted_box_choice(rng: random.Random) -> str:
    pool = [(k, w) for k, w in ROTATION_WEIGHTS.items() if is_auction_allowed_box(k)]
    total = sum(w for _, w in pool)
    if total <= 0:
        return "generic_supply_container"
    roll = rng.randint(1, total)
    acc = 0
    for key, weight in pool:
        acc += weight
        if roll <= acc:
            return key
    return pool[-1][0]


def _start_price_for_box(box_key: str) -> int:
    inv_key = resolve_inventory_key(box_key) or box_key
    meta = item_catalog_entry(inv_key)
    rarity = str(meta.get("rarity") or "common")
    return int(START_PRICE_BY_RARITY.get(rarity, START_PRICE_BY_RARITY["common"]))


def _min_next_bid(listing: Mapping[str, Any]) -> int:
    start = int(listing["start_price"] or 0)
    current = int(listing["current_bid"] or 0)
    if current <= 0:
        return max(1, start)
    # Exact ceil(current * 1.05) without routing huge bids through float.
    scaled = (
        current * (10_000 + MIN_BID_INCREASE_BPS) + 9_999
    ) // 10_000
    return max(start, scaled)


def _hint_key_for_reward(rtype: str, rkey: str) -> Optional[str]:
    rt = str(rtype or "")
    rk = str(rkey or "")
    if rt == "resource":
        return "auction_loot_hint_resources"
    if rt == "ship":
        return "auction_loot_hint_ship_parts"
    if rt == "defense":
        return "auction_loot_hint_defense_modules"
    if rt == "booster":
        if "build" in rk:
            return "auction_loot_hint_build_boosters"
        if "research" in rk:
            return "auction_loot_hint_research_boosters"
        if "shipyard" in rk:
            return "auction_loot_hint_shipyard_boosters"
        if "production" in rk:
            return "auction_loot_hint_production_boosters"
        return "auction_loot_hint_boosters"
    if rt == "item":
        spec = ITEM_CATALOG.get(rk) or {}
        cat = str(spec.get("category") or "")
        if rk.startswith("fragment") or cat in ("expedition", "planet_evolution"):
            return "auction_loot_hint_fragments"
        if "research" in cat or "research" in rk:
            return "auction_loot_hint_research_items"
        if cat in ("mythic", "research") or "artifact" in rk:
            return "auction_loot_hint_artifacts"
        return "auction_loot_hint_special_items"
    return None


def _loot_content_hints(inv_key: str, *, conn) -> List[Dict[str, str]]:
    """Category hints for UI preview — no weights or odds."""
    from . import inventory_loot

    pools = inventory_loot.get_loot_pools(conn)
    pool = pools.get(str(inv_key)) or []
    seen: set[str] = set()
    hints: List[Dict[str, str]] = []
    for entry in pool:
        hint_key = _hint_key_for_reward(
            str(entry.get("reward_type") or ""),
            str(entry.get("reward_key") or ""),
        )
        if not hint_key or hint_key in seen:
            continue
        seen.add(hint_key)
        hints.append({"hint_key": hint_key})
    return hints[:8]


def _listing_recent_bids(listing_id: int, *, conn, limit: int = 3) -> List[Dict[str, Any]]:
    """Highest bid per player (display collapse); history rows stay append-only."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT b.amount, b.player_id, b.created_at, p.name AS player_name
        FROM auction_house_bids b
        JOIN players p ON p.id = b.player_id
        WHERE b.listing_id = ?
        ORDER BY b.amount DESC, b.created_at DESC, b.id DESC;
        """,
        (int(listing_id),),
    )
    rows: List[Dict[str, Any]] = []
    seen_players: set[int] = set()
    for row in cur.fetchall():
        pid = int(row["player_id"])
        if pid in seen_players:
            continue
        seen_players.add(pid)
        rows.append(
            {
                "player_id": pid,
                "player_name": commander_display_name(str(row["player_name"] or "")),
                "amount": int(row["amount"] or 0),
                "created_at": int(row["created_at"] or 0),
            }
        )
        if len(rows) >= max(1, int(limit)):
            break
    try:
        from .playercard import map_equipped_name_styles

        styles = map_equipped_name_styles(
            [int(r["player_id"]) for r in rows], conn=conn
        )
    except Exception:
        styles = {}
    for r in rows:
        r["name_style"] = styles.get(int(r["player_id"]), "none")
    return rows


def _player_auction_stats(player_id: int, auctions: List[Dict[str, Any]], *, conn) -> Dict[str, int]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM lootbox_inventory
        WHERE player_id = ? AND source = 'auction_house';
        """,
        (int(player_id),),
    )
    won = int(cur.fetchone()["c"] or 0)
    my_leading = sum(1 for a in auctions if a.get("is_leading"))
    return {
        "active_auctions": len(auctions),
        "my_bids": my_leading,
        "won_auctions": won,
    }


def _serialize_listing(row: Mapping[str, Any], *, viewer_id: int, conn) -> Dict[str, Any]:
    box_key = str(row["box_key"])
    inv_key = resolve_inventory_key(box_key) or box_key
    meta = item_catalog_entry(inv_key)
    bidder_id = row["current_bidder_id"]
    bidder_name = None
    bidder_name_style = "none"
    if bidder_id is not None:
        cur = conn.cursor()
        cur.execute("SELECT name FROM players WHERE id = ? LIMIT 1;", (int(bidder_id),))
        prow = cur.fetchone()
        if prow:
            bidder_name = commander_display_name(str(prow["name"] or ""))
        try:
            from .playercard import map_equipped_name_styles

            bidder_name_style = map_equipped_name_styles(
                [int(bidder_id)], conn=conn
            ).get(int(bidder_id), "none")
        except Exception:
            bidder_name_style = "none"
    now = int(time.time())
    ends_at = int(row["ends_at"] or 0)
    listing_id = int(row["id"])
    current_bid = int(row["current_bid"] or 0)
    has_bids = current_bid > 0 and bidder_id is not None
    return {
        "id": listing_id,
        "box_key": box_key,
        "inventory_key": inv_key,
        "name_key": meta["name_key"],
        "rarity": meta["rarity"],
        "image": meta.get("image"),
        "currency": str(row["currency"]),
        "start_price": int(row["start_price"] or 0),
        "current_bid": current_bid,
        "display_bid": current_bid if has_bids else int(row["start_price"] or 0),
        "has_bids": has_bids,
        "min_next_bid": _min_next_bid(row),
        "current_bidder_id": int(bidder_id) if bidder_id is not None else None,
        "current_bidder_name": bidder_name,
        "current_bidder_name_style": bidder_name_style,
        "is_leading": bidder_id is not None and int(bidder_id) == int(viewer_id),
        "starts_at": int(row["starts_at"] or 0),
        "ends_at": ends_at,
        "seconds_remaining": max(0, ends_at - now),
        "status": str(row["status"] or "active"),
        "recent_bids": _listing_recent_bids(listing_id, conn=conn),
        "loot_hints": _loot_content_hints(inv_key, conn=conn),
    }


def _credit_planet_resource(
    conn,
    *,
    planet_id: int,
    player_id: int,
    currency: str,
    amount: int,
) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, player_id FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    planet = cur.fetchone()
    if not planet or int(planet["player_id"]) != int(player_id):
        return False
    col = str(currency)
    if col not in AUCTION_CURRENCIES:
        return False
    cur.execute(
        f"UPDATE planets SET {col} = {col} + ? WHERE id = ?;",
        (resource_db_param(amount), int(planet_id)),
    )
    return True


def _debit_planet_resource(
    conn,
    *,
    planet_id: int,
    player_id: int,
    currency: str,
    amount: int,
) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, player_id, metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    planet = cur.fetchone()
    if not planet or int(planet["player_id"]) != int(player_id):
        return False
    col = str(currency)
    if col not in AUCTION_CURRENCIES:
        return False
    balance = int(planet[col] or 0)
    if balance < int(amount):
        return False
    cur.execute(
        f"UPDATE planets SET {col} = {col} - ? WHERE id = ?;",
        (int(amount), int(planet_id)),
    )
    return True


def _grant_won_box(conn, *, player_id: int, box_key: str, now: float) -> None:
    now_i = int(now)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO lootbox_inventory (player_id, box_key, source, created_at)
        VALUES (?, ?, 'auction_house', ?);
        """,
        (int(player_id), str(box_key), now_i),
    )
    inv_key = resolve_inventory_key(box_key)
    if inv_key and inventory_schema_ready(conn):
        grant_inventory_item(int(player_id), inv_key, 1, conn=conn, metadata={"source": "auction_house"})


def finish_due_auctions(*, conn=None, now: Optional[float] = None) -> int:
    """Complete expired listings; winner receives lootbox. Returns count finished."""
    own = conn is None
    if own:
        conn = db()
    if not auction_schema_ready(conn):
        if own:
            conn.close()
        return 0
    ts = float(now if now is not None else time.time())
    now_i = int(ts)
    finished = 0
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, box_key, current_bid, current_bidder_id, currency
            FROM auction_house_listings
            WHERE status = 'active' AND ends_at <= ?
            ORDER BY ends_at ASC, id ASC;
            """,
            (now_i,),
        )
        due = cur.fetchall()
        for row in due:
            listing_id = int(row["id"])
            winner_id = row["current_bidder_id"]
            box_key = str(row["box_key"])
            if winner_id is not None and int(row["current_bid"] or 0) > 0:
                _grant_won_box(conn, player_id=int(winner_id), box_key=box_key, now=ts)
            cur.execute(
                """
                UPDATE auction_house_listings
                SET status = 'completed'
                WHERE id = ? AND status = 'active';
                """,
                (listing_id,),
            )
            if cur.rowcount:
                finished += 1
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()
    return finished


def generate_auction_rotation(*, conn=None, now: Optional[float] = None, seed: Optional[int] = None) -> int:
    """Ensure up to ACTIVE_AUCTION_TARGET live listings. Returns listings created."""
    own = conn is None
    if own:
        conn = db()
    if not auction_schema_ready(conn):
        if own:
            conn.close()
        return 0
    ts = float(now if now is not None else time.time())
    now_i = int(ts)
    created = 0
    rng = random.Random(seed if seed is not None else now_i)
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM auction_house_listings
            WHERE status = 'active' AND ends_at > ?;
            """,
            (now_i,),
        )
        active = int(cur.fetchone()["c"] or 0)
        need = max(0, ACTIVE_AUCTION_TARGET - active)
        for _ in range(need):
            box_key = _weighted_box_choice(rng)
            if not is_auction_allowed_box(box_key) or is_event_box(box_key):
                continue
            currency = rng.choice(AUCTION_CURRENCIES)
            duration = rng.randint(MIN_DURATION_SEC, MAX_DURATION_SEC)
            start_price = _start_price_for_box(box_key)
            cur.execute(
                """
                INSERT INTO auction_house_listings (
                    box_key, currency, start_price, current_bid, starts_at, ends_at, status, created_at
                ) VALUES (?, ?, ?, 0, ?, ?, 'active', ?);
                """,
                (
                    box_key,
                    currency,
                    resource_db_param(start_price),
                    now_i,
                    now_i + duration,
                    now_i,
                ),
            )
            created += 1
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()
    return created


def _compute_next_rotation_at(conn, now_i: int) -> int:
    """Next slot opens when the earliest active auction ends."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT MIN(ends_at) AS m FROM auction_house_listings
        WHERE status = 'active' AND ends_at > ?;
        """,
        (int(now_i),),
    )
    row = cur.fetchone()
    if row and row["m"] is not None:
        return int(row["m"])
    return int(now_i)


def get_rotation_meta(conn, *, now: Optional[float] = None) -> Dict[str, int]:
    now_i = int(now if now is not None else time.time())
    next_at = _compute_next_rotation_at(conn, now_i)
    return {
        "next_rotation_at": next_at,
        "rotation_interval_seconds": ROTATION_INTERVAL_SECONDS,
        "seconds_until_rotation": max(0, next_at - now_i),
    }


def get_active_auctions(player_id: int, *, conn=None) -> List[Dict[str, Any]]:
    own = conn is None
    if own:
        conn = db()
    if not auction_schema_ready(conn):
        if own:
            conn.close()
        return []
    try:
        finish_due_auctions(conn=conn)
        generate_auction_rotation(conn=conn)
        now_i = int(time.time())
        cur = conn.cursor()
        cur.execute(
            """
            SELECT *
            FROM auction_house_listings
            WHERE status = 'active' AND ends_at > ?
            ORDER BY ends_at ASC, id ASC;
            """,
            (now_i,),
        )
        return [_serialize_listing(r, viewer_id=int(player_id), conn=conn) for r in cur.fetchall()]
    finally:
        if own and conn is not None:
            conn.close()


def build_auction_house_state(
    player_id: int,
    planet_id: int,
    *,
    metal: float = 0,
    crystal: float = 0,
    fuel_cells: float = 0,
    conn=None,
    mark_visited: bool = False,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        ready = auction_schema_ready(conn)
        auctions = get_active_auctions(int(player_id), conn=conn) if ready else []
        stats = _player_auction_stats(int(player_id), auctions, conn=conn) if ready else {
            "active_auctions": 0,
            "my_bids": 0,
            "won_auctions": 0,
        }
        now_i = int(time.time())
        if ready and mark_visited:
            mark_auction_house_visited(int(player_id), conn=conn, now=now_i)
        rotation = get_rotation_meta(conn, now=now_i) if ready else {
            "next_rotation_at": now_i,
            "rotation_interval_seconds": ROTATION_INTERVAL_SECONDS,
            "seconds_until_rotation": 0,
        }
        return {
            "ready": ready,
            "auctions": auctions,
            "stats": stats,
            "next_rotation_at": int(rotation["next_rotation_at"]),
            "rotation_interval_seconds": int(rotation["rotation_interval_seconds"]),
            "seconds_until_rotation": int(rotation["seconds_until_rotation"]),
            "balances": {
                "metal": max(0, int(metal)),
                "crystal": max(0, int(crystal)),
                "fuel_cells": max(0, int(fuel_cells)),
            },
            "planet_id": int(planet_id),
        }
    finally:
        if own and conn is not None:
            conn.close()


def place_bid(
    *,
    player_id: int,
    planet_id: int,
    listing_id: int,
    amount: int,
    currency: str,
    conn=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not auction_schema_ready(conn or db()):
        return False, "auction_unavailable", None

    try:
        bid_amount = int(amount)
    except (TypeError, ValueError):
        return False, "invalid_amount", None
    if bid_amount <= 0:
        return False, "invalid_amount", None

    cur_code = str(currency or "").strip().lower()
    if cur_code not in AUCTION_CURRENCIES:
        return False, "invalid_currency", None

    own = conn is None
    if own:
        conn = db()
    try:
        finish_due_auctions(conn=conn)
        now = time.time()
        now_i = int(now)
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM auction_house_listings
            WHERE id = ? AND status = 'active' AND ends_at > ?
            LIMIT 1;
            """,
            (int(listing_id), now_i),
        )
        listing = cur.fetchone()
        if not listing:
            rollback(conn)
            return False, "listing_not_found", None

        listing_cur = str(listing["currency"])
        if cur_code != listing_cur:
            rollback(conn)
            return False, "currency_mismatch", None

        min_bid = _min_next_bid(listing)
        if bid_amount < min_bid:
            rollback(conn)
            return False, "bid_too_low", {"min_bid": min_bid}

        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        if not cur.fetchone():
            rollback(conn)
            return False, "planet_not_found", None

        prev_bidder = listing["current_bidder_id"]
        prev_planet = listing["current_bid_planet_id"]
        prev_amount = int(listing["current_bid"] or 0)
        same_bidder = prev_bidder is not None and int(prev_bidder) == int(player_id)

        if same_bidder and prev_amount > 0 and bid_amount <= prev_amount:
            rollback(conn)
            return False, "bid_must_raise", {"min_bid": min_bid, "current_bid": prev_amount}

        cur.execute(
            """
            SELECT COUNT(*) AS c FROM auction_house_bids
            WHERE listing_id = ? AND player_id = ?;
            """,
            (int(listing_id), int(player_id)),
        )
        bid_count = int(cur.fetchone()["c"] or 0)
        if bid_count >= MAX_BIDS_PER_PLAYER_PER_LISTING:
            rollback(conn)
            return False, "auction_bid_limit_reached", {
                "max_bids": MAX_BIDS_PER_PLAYER_PER_LISTING,
            }

        charge_amount = bid_amount - prev_amount if same_bidder and prev_amount > 0 else bid_amount

        if charge_amount <= 0:
            rollback(conn)
            return False, "bid_too_low", {"min_bid": min_bid}

        if not _debit_planet_resource(
            conn,
            planet_id=int(planet_id),
            player_id=int(player_id),
            currency=listing_cur,
            amount=charge_amount,
        ):
            rollback(conn)
            return False, "insufficient_balance", None

        if prev_bidder is not None and prev_amount > 0 and not same_bidder:
            refund_planet = int(prev_planet) if prev_planet is not None else int(planet_id)
            if not _credit_planet_resource(
                conn,
                planet_id=refund_planet,
                player_id=int(prev_bidder),
                currency=listing_cur,
                amount=prev_amount,
            ):
                rollback(conn)
                return False, "refund_failed", None
            cur.execute(
                """
                SELECT id FROM auction_house_bids
                WHERE listing_id = ? AND player_id = ? AND refunded = 0
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (int(listing_id), int(prev_bidder)),
            )
            refund_row = cur.fetchone()
            if refund_row:
                cur.execute(
                    "UPDATE auction_house_bids SET refunded = 1 WHERE id = ?;",
                    (int(refund_row["id"]),),
                )

        cur.execute(
            """
            UPDATE auction_house_listings
            SET current_bid = ?, current_bidder_id = ?, current_bid_planet_id = ?
            WHERE id = ?;
            """,
            (
                resource_db_param(bid_amount),
                int(player_id),
                int(planet_id),
                int(listing_id),
            ),
        )
        cur.execute(
            """
            INSERT INTO auction_house_bids (
                listing_id, player_id, planet_id, amount, created_at, refunded
            ) VALUES (?, ?, ?, ?, ?, 0);
            """,
            (
                int(listing_id),
                int(player_id),
                int(planet_id),
                resource_db_param(bid_amount),
                now_i,
            ),
        )
        commit(conn)
        return True, "bid_placed", {
            "listing_id": int(listing_id),
            "amount": bid_amount,
            "currency": listing_cur,
        }
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()
