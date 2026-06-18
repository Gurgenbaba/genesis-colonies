"""
GC-551 / GC-552 / GC-551B — Multi-provider vote rewards (server-authoritative).

Providers are configuration rows in vote_providers. Postbacks create pending rewards
with one rolled reward each; players claim them in the Vote Center.
"""

from __future__ import annotations

import json
import logging
import os
import random
import socket
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .auction_house import is_event_box, resolve_inventory_key
from .db import db, lock_planet_for_update, table_exists
from .defense_defs import defense_icon_static_path, get_defense, is_known_defense_key
from .fleet_defs import canonical_ship_key, get_ship, is_known_ship_key, ship_icon_static_path
from .inventory import grant_inventory_item, inventory_schema_ready
from .inventory_catalog import container_image_path, item_catalog_entry

logger = logging.getLogger(__name__)

VOTE_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "topg": {
        "display_name": "TopG",
        "card_image": "img/vote/TopG.png",
        "vote_url_template": "https://topg.org/ogame-private-servers/server-683112-{user_id}#vote",
        "cooldown_seconds": 6 * 60 * 60,
        "postback_enabled": True,
        "sort_order": 10,
        "subtitle_key": "vote_provider_topg_subtitle",
        "reward_status_key": "vote_provider_topg_reward_active",
        "postback_config_json": (
            '{"user_id_params":["p_resp"],"ip_params":["ip"],'
            '"require_numeric_user_id":true,"remote_host":"monitor.topg.org","strict_ip_check":false}'
        ),
    },
    "gtop100": {
        "display_name": "GTop100",
        "card_image": "img/vote/GTop100.png",
        "vote_url_template": "https://gtop100.com/Ogame/server-106142?vote=1&pingUsername={user_id}",
        "cooldown_seconds": 12 * 60 * 60,
        "postback_enabled": True,
        "sort_order": 15,
        "subtitle_key": "vote_provider_gtop100_subtitle",
        "reward_status_key": "vote_provider_gtop100_reward_active",
    },
    "gametoor": {
        "display_name": "GameToor",
        "card_image": "img/vote/GameToor.png",
        "vote_url_template": "http://gametoor.com/in/3277/{user_id}",
        "cooldown_seconds": 12 * 60 * 60,
        "postback_enabled": True,
        "sort_order": 30,
        "subtitle_key": "vote_provider_gametoor_subtitle",
        "reward_status_key": "vote_provider_gametoor_reward_active",
    },
    "arena_top100": {
        "display_name": "Arena-Top100",
        "card_image": "img/vote/Arena-Top100.png",
        "vote_url_template": "https://www.arena-top100.com/index.php?a=in&u=Gurgenbaba&id={user_id}",
        "cooldown_seconds": 12 * 60 * 60,
        "postback_enabled": True,
        "sort_order": 40,
        "subtitle_key": "vote_provider_arena_top100_subtitle",
        "reward_status_key": "vote_provider_arena_top100_reward_active",
        "postback_config_json": (
            '{"user_id_params":["userid"],"ip_params":["userip"],'
            '"require_numeric_user_id":true,"voted_param":"voted","voted_value":"1"}'
        ),
    },
}

TOPG_COOLDOWN_SEC = int(VOTE_PROVIDERS["topg"]["cooldown_seconds"])
VOTE_COOLDOWN_SEC = TOPG_COOLDOWN_SEC
DEFAULT_VOTE_BOX_KEY = "generic_supply_container"
DEFAULT_REWARD_KEY = "vote_container"
VOTE_SKIP_IP_CHECK_ENV = "GC_VOTE_SKIP_IP_CHECK"
TOPG_STRICT_IP_CHECK_ENV = "TOPG_STRICT_IP_CHECK"

TOPG_SERVER_ID = 683112
TOPG_PROVIDER = "topg"
GTOP100_PROVIDER = "gtop100"
GTOP100_SITE_ID = 106142
GTOP100_COOLDOWN_SEC = int(VOTE_PROVIDERS["gtop100"]["cooldown_seconds"])
GTOP100_PINGBACK_KEY_ENV = "GTOP100_PINGBACK_KEY"
ARENA_TOP100_PROVIDER = "arena_top100"
ARENA_TOP100_SECRET_ENV = "ARENA_TOP100_SECRET"
GAMETOOR_PROVIDER = "gametoor"
GAMETOOR_IVN_KEY_ENV = "GAMETOOR_IVN_KEY"
GAMETOOR_COOLDOWN_SEC = int(VOTE_PROVIDERS["gametoor"]["cooldown_seconds"])
TOPG_REWARD_KEY = DEFAULT_REWARD_KEY
TOPG_DEFAULT_BOX_KEY = DEFAULT_VOTE_BOX_KEY
TOPG_REMOTE_HOST = "monitor.topg.org"

ALLOWED_VOTE_BOX_KEYS = frozenset(
    {
        "generic_supply_container",
        "resource_cache",
        "research_capsule",
        "military_cache",
    }
)

VOTE_REWARD_POOL: List[Dict[str, Any]] = [
    {
        "key": "vote_supply_container",
        "type": "lootbox",
        "weight": 45,
        "payload": {"box_key": "generic_supply_container", "amount": 1},
    },
    {
        "key": "vote_resource_pack_small",
        "type": "resources",
        "weight": 25,
        "payload": {"metal": 2_500_000, "crystal": 1_000_000, "fuel_cells": 50_000},
    },
    {
        "key": "vote_resource_pack_large",
        "type": "resources",
        "weight": 10,
        "payload": {"metal": 10_000_000, "crystal": 4_000_000, "fuel_cells": 150_000},
    },
    {
        "key": "vote_ship_pack_scout",
        "type": "ships",
        "weight": 10,
        "payload": {"ships": {"spark_drone": 5}},
    },
    {
        "key": "vote_ship_pack_cargo",
        "type": "ships",
        "weight": 5,
        "payload": {"ships": {"mule_courier": 2}},
    },
    {
        "key": "vote_defense_pack_basic",
        "type": "defense",
        "weight": 5,
        "payload": {"defense": {"sentinel_turret": 5}},
    },
]

REWARD_TYPE_LABEL_KEYS: Dict[str, str] = {
    "lootbox": "vote_reward_type_lootbox",
    "resources": "vote_reward_type_resources",
    "ships": "vote_reward_type_ships",
    "defense": "vote_reward_type_defense",
}

_VOTE_RESOURCE_DISPLAY: Tuple[Tuple[str, str, str], ...] = (
    ("metal", "resource_metal", "/static/img/res/Ferronit.png"),
    ("crystal", "resource_crystal", "/static/img/res/Crytite.png"),
    ("fuel_cells", "resource_fuel_cells", "/static/img/res/Brennzellen.png"),
)


def vote_rewards_schema_ready(conn) -> bool:
    return table_exists(conn, "vote_rewards")


def vote_reward_next_at_column_ready(conn) -> bool:
    if not vote_rewards_schema_ready(conn):
        return False
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(vote_rewards);")
    return any(str(row[1]) == "provider_next_vote_at" for row in cur.fetchall())


def vote_providers_schema_ready(conn) -> bool:
    return table_exists(conn, "vote_providers")


def vote_system_ready(conn) -> bool:
    return vote_rewards_schema_ready(conn) and vote_providers_schema_ready(conn)


def topg_strict_ip_check_enabled() -> bool:
    return os.environ.get(TOPG_STRICT_IP_CHECK_ENV, "0").strip().lower() in ("1", "true", "yes")


def vote_skip_ip_check_enabled() -> bool:
    if os.environ.get(VOTE_SKIP_IP_CHECK_ENV, "").strip().lower() in ("1", "true", "yes"):
        return True
    return os.environ.get("GC_TOPG_SKIP_IP_CHECK", "").strip().lower() in ("1", "true", "yes")


def topg_skip_ip_check_enabled() -> bool:
    return vote_skip_ip_check_enabled() or not topg_strict_ip_check_enabled()


def vote_provider_card_image(provider_key: str) -> str:
    canon = VOTE_PROVIDERS.get(str(provider_key or ""), {})
    rel = str(canon.get("card_image") or "").strip().lstrip("/")
    if rel.startswith("static/"):
        rel = rel[7:]
    return rel


def _apply_canonical_provider_config(provider: Dict[str, Any]) -> Dict[str, Any]:
    key = str(provider.get("provider_key") or "")
    canon = VOTE_PROVIDERS.get(key)
    if not canon:
        return provider
    out = dict(provider)
    out["display_name"] = str(canon.get("display_name") or out.get("display_name") or key)
    out["vote_url_template"] = str(canon.get("vote_url_template") or out.get("vote_url_template") or "")
    out["cooldown_sec"] = int(canon.get("cooldown_seconds") or out.get("cooldown_sec") or VOTE_COOLDOWN_SEC)
    out["postback_enabled"] = bool(canon.get("postback_enabled"))
    out["sort_order"] = int(canon.get("sort_order") or out.get("sort_order") or 0)
    out["subtitle_key"] = str(canon.get("subtitle_key") or "")
    out["reward_status_key"] = str(canon.get("reward_status_key") or "")
    out["no_auto_reward_key"] = str(canon.get("no_auto_reward_key") or "")
    out["card_image"] = vote_provider_card_image(key)
    if canon.get("postback_config_json"):
        out["postback_config_json"] = str(canon["postback_config_json"])
    return out


def resolve_vote_url(template: str, user_id: int) -> str:
    t = str(template or "").strip()
    uid = str(int(user_id))
    if "{user_id}" in t:
        url = t.replace("{user_id}", uid)
    elif "server-683112" in t and f"server-683112-{uid}" not in t:
        url = t.replace("server-683112", f"server-683112-{uid}")
    else:
        url = t
    if url.endswith("/") and not url.endswith("://"):
        url = url.rstrip("/")
    return url


def topg_vote_url(user_id: int) -> str:
    return resolve_vote_url(
        f"https://topg.org/ogame-private-servers/server-{TOPG_SERVER_ID}-{{user_id}}#vote",
        user_id,
    )


def _vote_bucket(now: int, cooldown_sec: int) -> int:
    cd = max(1, int(cooldown_sec))
    return int(now) // cd


def provider_ref(provider_key: str, user_id: int, now: int, cooldown_sec: int) -> str:
    return f"{str(provider_key)}:{int(user_id)}:{_vote_bucket(int(now), cooldown_sec)}"


def topg_provider_ref(user_id: int, now: int) -> str:
    return provider_ref(TOPG_PROVIDER, user_id, now, VOTE_COOLDOWN_SEC)


def roll_vote_reward(*, rng: Optional[random.Random] = None) -> Dict[str, Any]:
    """Pick exactly one weighted vote reward."""
    pool = [e for e in VOTE_REWARD_POOL if int(e.get("weight") or 0) > 0]
    total = sum(int(e["weight"]) for e in pool)
    if total <= 0:
        entry = VOTE_REWARD_POOL[0]
    else:
        r = rng or random.Random()
        roll = r.randint(1, total)
        acc = 0
        entry = pool[-1]
        for candidate in pool:
            acc += int(candidate["weight"])
            if roll <= acc:
                entry = candidate
                break
    payload = dict(entry.get("payload") or {})
    return {
        "reward_type": str(entry["type"]),
        "reward_key": str(entry["key"]),
        **payload,
    }


def _parse_reward_payload(raw: str) -> Dict[str, Any]:
    if not raw:
        return roll_vote_reward()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("reward_type"):
            return data
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    legacy = _parse_legacy_reward_payload(raw)
    if legacy:
        return legacy
    return roll_vote_reward()


def _parse_legacy_reward_payload(raw: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("box_key"):
        return {
            "reward_type": "lootbox",
            "reward_key": DEFAULT_REWARD_KEY,
            "box_key": str(data["box_key"]),
            "amount": int(data.get("amount") or 1),
        }
    return None


def is_allowed_vote_reward_box(box_key: str) -> bool:
    key = str(box_key or "").strip()
    if not key or is_event_box(key):
        return False
    return key in ALLOWED_VOTE_BOX_KEYS


def _remote_host_allowed(
    remote_addr: Optional[str],
    remote_host: str,
    *,
    strict: bool = True,
) -> bool:
    if not strict or vote_skip_ip_check_enabled():
        return True
    host = str(remote_host or "").strip()
    if not host:
        return True
    try:
        expected = socket.gethostbyname(host)
    except OSError:
        logger.warning("vote postback: DNS lookup failed for %s", host)
        return False
    addr = str(remote_addr or "").strip()
    return bool(addr) and addr == expected


def is_topg_postback_allowed(remote_addr: Optional[str]) -> bool:
    return _remote_host_allowed(remote_addr, TOPG_REMOTE_HOST, strict=topg_strict_ip_check_enabled())


def _user_exists(user_id: int, *, conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1;", (int(user_id),))
    return cur.fetchone() is not None


def _row_str(row: Any, key: str, default: str = "") -> str:
    if row is None:
        return default
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return str(val) if val is not None else default


def _get_provider(provider_key: str, *, conn) -> Optional[Dict[str, Any]]:
    if not vote_providers_schema_ready(conn):
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT provider_key, display_name, vote_url_template, enabled, cooldown_sec,
               reward_key, reward_payload_json, postback_enabled, postback_config_json, sort_order
        FROM vote_providers
        WHERE provider_key = ?
        LIMIT 1;
        """,
        (str(provider_key),),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _apply_canonical_provider_config(
        {
            "provider_key": str(row["provider_key"]),
            "display_name": str(row["display_name"]),
            "vote_url_template": str(row["vote_url_template"]),
            "enabled": bool(int(row["enabled"] or 0)),
            "cooldown_sec": int(row["cooldown_sec"] or VOTE_COOLDOWN_SEC),
            "reward_key": str(row["reward_key"] or DEFAULT_REWARD_KEY),
            "reward_payload_json": _row_str(row, "reward_payload_json"),
            "postback_enabled": bool(int(row["postback_enabled"] or 0)),
            "postback_config_json": _row_str(row, "postback_config_json", "{}"),
            "sort_order": int(row["sort_order"] or 0),
        }
    )


def list_enabled_providers(*, conn) -> List[Dict[str, Any]]:
    if not vote_providers_schema_ready(conn):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT provider_key, display_name, vote_url_template, enabled, cooldown_sec,
               reward_key, reward_payload_json, postback_enabled, postback_config_json, sort_order
        FROM vote_providers
        WHERE enabled = 1
        ORDER BY sort_order ASC, provider_key ASC;
        """
    )
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        out.append(
            _apply_canonical_provider_config(
                {
                    "provider_key": str(row["provider_key"]),
                    "display_name": str(row["display_name"]),
                    "vote_url_template": str(row["vote_url_template"]),
                    "enabled": True,
                    "cooldown_sec": int(row["cooldown_sec"] or VOTE_COOLDOWN_SEC),
                    "reward_key": str(row["reward_key"] or DEFAULT_REWARD_KEY),
                    "reward_payload_json": _row_str(row, "reward_payload_json"),
                    "postback_enabled": bool(int(row["postback_enabled"] or 0)),
                    "postback_config_json": _row_str(row, "postback_config_json", "{}"),
                    "sort_order": int(row["sort_order"] or 0),
                }
            )
        )
    return out


def _static_image_url(rel_path: str) -> str:
    rel = str(rel_path or "").strip().lstrip("/")
    if rel.startswith("static/"):
        rel = rel[7:]
    return f"/static/{rel}" if rel else "/static/img/lootboxes/Generic_Supply_Container.png"


def _reward_display_items(payload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rtype = str(payload.get("reward_type") or "lootbox")
    items: List[Dict[str, Any]] = []
    if rtype == "lootbox":
        box_key = str(payload.get("box_key") or DEFAULT_VOTE_BOX_KEY)
        inv_key = resolve_inventory_key(box_key) or box_key
        meta = item_catalog_entry(inv_key)
        items.append(
            {
                "kind": "lootbox",
                "name_key": str(meta.get("name_key") or f"inv_{inv_key}"),
                "name_fallback": inv_key,
                "image": _static_image_url(container_image_path(inv_key)),
                "amount": int(payload.get("amount") or 1),
                "rarity": str(meta.get("rarity") or "common"),
            }
        )
    elif rtype == "resources":
        for res_key, name_key, image in _VOTE_RESOURCE_DISPLAY:
            amount = int(payload.get(res_key) or 0)
            if amount > 0:
                items.append(
                    {
                        "kind": "resource",
                        "resource_key": res_key,
                        "name_key": name_key,
                        "name_fallback": res_key,
                        "image": image,
                        "amount": amount,
                    }
                )
    elif rtype == "ships":
        ships = payload.get("ships") if isinstance(payload.get("ships"), dict) else {}
        for ship_key, amount in ships.items():
            amount_i = int(amount or 0)
            if amount_i <= 0:
                continue
            canon = canonical_ship_key(str(ship_key))
            ship = get_ship(canon) or {}
            items.append(
                {
                    "kind": "ship",
                    "item_key": canon,
                    "name_key": str(ship.get("name_key") or f"fleet_ship_{canon}"),
                    "name_fallback": canon,
                    "image": ship_icon_static_path(canon),
                    "amount": amount_i,
                }
            )
    elif rtype == "defense":
        defense = payload.get("defense") if isinstance(payload.get("defense"), dict) else {}
        for defense_key, amount in defense.items():
            amount_i = int(amount or 0)
            if amount_i <= 0:
                continue
            key = str(defense_key)
            spec = get_defense(key) or {}
            items.append(
                {
                    "kind": "defense",
                    "item_key": key,
                    "name_key": str(spec.get("name_key") or f"defense_{key}"),
                    "name_fallback": key,
                    "image": defense_icon_static_path(key),
                    "amount": amount_i,
                }
            )
    return items


def _reward_summary(payload: Mapping[str, Any]) -> Dict[str, Any]:
    rtype = str(payload.get("reward_type") or "lootbox")
    rkey = str(payload.get("reward_key") or DEFAULT_REWARD_KEY)
    label_key = REWARD_TYPE_LABEL_KEYS.get(rtype, "vote_reward_type_lootbox")
    out: Dict[str, Any] = {
        "reward_type": rtype,
        "reward_key": rkey,
        "reward_type_label_key": label_key,
        "title_key": "vote_reward_title",
    }
    if rtype == "lootbox":
        out["box_key"] = str(payload.get("box_key") or DEFAULT_VOTE_BOX_KEY)
        out["amount"] = int(payload.get("amount") or 1)
    elif rtype == "resources":
        out["metal"] = int(payload.get("metal") or 0)
        out["crystal"] = int(payload.get("crystal") or 0)
        out["fuel_cells"] = int(payload.get("fuel_cells") or 0)
    elif rtype == "ships":
        ships = payload.get("ships") if isinstance(payload.get("ships"), dict) else {}
        out["ships"] = {str(k): int(v) for k, v in ships.items() if int(v or 0) > 0}
    elif rtype == "defense":
        defense = payload.get("defense") if isinstance(payload.get("defense"), dict) else {}
        out["defense"] = {str(k): int(v) for k, v in defense.items() if int(v or 0) > 0}
    out["display_items"] = _reward_display_items(payload)
    return out


def _serialize_pending_reward(row: Any, *, conn, provider_names: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    payload = _parse_reward_payload(_row_str(row, "reward_payload_json"))
    summary = _reward_summary(payload)
    provider_key = str(row["provider"])
    if provider_names and provider_key in provider_names:
        provider_name = provider_names[provider_key]
    elif vote_providers_schema_ready(conn):
        provider = _get_provider(provider_key, conn=conn)
        provider_name = str(provider["display_name"]) if provider else provider_key
    else:
        provider_name = provider_key
    return {
        "id": int(row["id"]),
        "provider": provider_key,
        "provider_name": provider_name,
        "reward_key": _row_str(row, "reward_key") or summary["reward_key"],
        "voted_at": int(row["voted_at"]),
        "status": str(row["status"]),
        **summary,
    }


def _provider_last_vote_at(user_id: int, provider_key: str, *, conn) -> Optional[int]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT MAX(voted_at) AS last_vote_at
        FROM vote_rewards
        WHERE user_id = ? AND provider = ?;
        """,
        (int(user_id), str(provider_key)),
    )
    row = cur.fetchone()
    return int(row["last_vote_at"]) if row and row["last_vote_at"] is not None else None


def get_provider_cooldown_status(
    user_id: int,
    provider: Mapping[str, Any],
    *,
    conn,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    ts = int(now if now is not None else time.time())
    provider_key = str(provider["provider_key"])
    cooldown_sec = int(provider.get("cooldown_sec") or VOTE_COOLDOWN_SEC)
    last_vote_at = _provider_last_vote_at(user_id, provider_key, conn=conn)
    can_vote = True
    next_vote_at: Optional[int] = None
    cooldown_remaining_sec = 0
    if last_vote_at is not None and (ts - last_vote_at) < cooldown_sec:
        can_vote = False
        next_vote_at = last_vote_at + cooldown_sec
        cooldown_remaining_sec = max(0, next_vote_at - ts)
    return {
        "can_vote": can_vote,
        "last_vote_at": last_vote_at,
        "next_vote_at": next_vote_at,
        "cooldown_remaining_sec": cooldown_remaining_sec,
        "cooldown_sec": cooldown_sec,
    }


def _provider_vote_stats(
    user_id: int,
    provider: Mapping[str, Any],
    *,
    conn,
    now: int,
) -> Dict[str, Any]:
    provider_key = str(provider["provider_key"])
    cd = get_provider_cooldown_status(user_id, provider, conn=conn, now=now)
    last_vote_at = cd["last_vote_at"]
    can_vote_hint = bool(cd["can_vote"])
    next_vote_at = cd["next_vote_at"]
    cooldown_remaining_sec = int(cd["cooldown_remaining_sec"])
    cooldown_sec = int(cd["cooldown_sec"])
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM vote_rewards
        WHERE user_id = ? AND provider = ?;
        """,
        (int(user_id), provider_key),
    )
    vote_count = int(cur.fetchone()["c"] or 0)
    vote_url = resolve_vote_url(str(provider["vote_url_template"]), int(user_id))
    postback_enabled = bool(provider.get("postback_enabled"))
    return {
        "provider_key": provider_key,
        "display_name": str(provider["display_name"]),
        "vote_url": vote_url,
        "last_vote_at": last_vote_at,
        "next_vote_at": next_vote_at,
        "cooldown_remaining_sec": cooldown_remaining_sec,
        "can_vote_hint": can_vote_hint,
        "can_vote_now": can_vote_hint,
        "vote_count": vote_count,
        "cooldown_sec": cooldown_sec,
        "postback_enabled": postback_enabled,
        "rewards_active": postback_enabled,
        "subtitle_key": str(provider.get("subtitle_key") or ""),
        "reward_status_key": str(provider.get("reward_status_key") or ""),
        "no_auto_reward_key": str(provider.get("no_auto_reward_key") or ""),
        "card_image": vote_provider_card_image(provider_key),
    }


def count_voteable_providers(user_id: int, *, conn, now: Optional[int] = None) -> int:
    """Nav-badge helper: providers the player can vote on right now (server cooldown truth)."""
    if not vote_system_ready(conn):
        return 0
    ts = int(now if now is not None else time.time())
    total = 0
    for provider in list_enabled_providers(conn=conn):
        cd = get_provider_cooldown_status(int(user_id), provider, conn=conn, now=ts)
        if cd["can_vote"]:
            total += 1
    return total


def get_vote_center_state(user_id: int, *, conn) -> Dict[str, Any]:
    uid = int(user_id)
    now = int(time.time())
    out: Dict[str, Any] = {
        "ready": vote_system_ready(conn),
        "providers": [],
        "pending_rewards": [],
        "pending_count": 0,
        "topg_vote_url": topg_vote_url(uid),
        "last_vote_at": None,
        "next_vote_at": None,
        "can_vote_hint": True,
        "can_vote_now": True,
    }
    if not out["ready"]:
        return out

    providers = list_enabled_providers(conn=conn)
    out["providers"] = [_provider_vote_stats(uid, p, conn=conn, now=now) for p in providers]

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, provider, reward_key, reward_payload_json, voted_at, status
        FROM vote_rewards
        WHERE user_id = ? AND status = 'pending'
        ORDER BY voted_at ASC;
        """,
        (uid,),
    )
    provider_names = {str(p["provider_key"]): str(p["display_name"]) for p in providers}
    pending = [_serialize_pending_reward(r, conn=conn, provider_names=provider_names) for r in cur.fetchall()]
    out["pending_rewards"] = pending
    out["pending_count"] = len(pending)

    topg = next((p for p in out["providers"] if p["provider_key"] == TOPG_PROVIDER), None)
    if topg:
        out["topg_vote_url"] = topg["vote_url"]
        out["last_vote_at"] = topg["last_vote_at"]
        out["next_vote_at"] = topg["next_vote_at"]
        out["can_vote_hint"] = topg["can_vote_hint"]
        out["can_vote_now"] = topg["can_vote_now"]
    return out


def get_gtop100_pingback_key() -> str:
    return os.environ.get(GTOP100_PINGBACK_KEY_ENV, "").strip()


def _gtop100_success_ok(value: Any) -> bool:
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return str(value or "").strip() in ("0", "false", "")


def _flatten_gtop100_common_entry(entry: Any) -> Dict[str, Any]:
    if not isinstance(entry, list):
        return {}
    flat: Dict[str, Any] = {}
    for part in entry:
        if isinstance(part, dict):
            flat.update(part)
    return flat


def _extract_gtop100_vote_entries(
    json_data: Optional[Mapping[str, Any]],
    form_data: Optional[Mapping[str, Any]],
) -> Tuple[Optional[str], Optional[int], List[Dict[str, Any]]]:
    pingback_key: Optional[str] = None
    site_id: Optional[int] = None
    votes: List[Dict[str, Any]] = []

    if json_data:
        pingback_key = str(json_data.get("pingbackkey") or json_data.get("pingbackKey") or "").strip() or None
        raw_site = json_data.get("siteid") or json_data.get("siteId")
        if raw_site is not None and str(raw_site).strip():
            try:
                site_id = int(raw_site)
            except (TypeError, ValueError):
                site_id = -1
        common = json_data.get("Common") or json_data.get("common") or []
        if isinstance(common, list):
            for entry in common:
                flat = _flatten_gtop100_common_entry(entry)
                if flat:
                    votes.append(flat)

    if form_data and not votes:
        pingback_key = pingback_key or str(
            form_data.get("pingbackkey") or form_data.get("pingbackKey") or ""
        ).strip() or None
        votes.append(
            {
                "ip": form_data.get("VoterIP") or form_data.get("ip"),
                "success": form_data.get("Successful") or form_data.get("success"),
                "reason": form_data.get("Reason") or form_data.get("reason"),
                "pb_name": form_data.get("pingUsername") or form_data.get("pb_name"),
            }
        )

    return pingback_key, site_id, votes


def parse_gtop100_pingback(
    json_data: Optional[Mapping[str, Any]],
    form_data: Optional[Mapping[str, Any]],
) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """
    Validate GTop100 pingback envelope.

    Returns (allowed, reason, vote_entries).
    """
    expected_key = get_gtop100_pingback_key()
    if not expected_key:
        logger.warning("gtop100 pingback: %s not configured", GTOP100_PINGBACK_KEY_ENV)
        return False, "pingback_key_missing", []

    pingback_key, site_id, votes = _extract_gtop100_vote_entries(json_data, form_data)
    if not pingback_key or pingback_key != expected_key:
        logger.warning("gtop100 pingback: invalid pingback key")
        return False, "forbidden", []

    if site_id is not None and site_id != GTOP100_SITE_ID:
        logger.warning("gtop100 pingback: invalid site_id=%s", site_id)
        return False, "invalid_site_id", []

    if not votes:
        return True, "no_entries", []

    return True, "ok", votes


def handle_gtop100_pingback(
    json_data: Optional[Mapping[str, Any]],
    form_data: Optional[Mapping[str, Any]],
    *,
    conn,
) -> Tuple[bool, int, str]:
    allowed, reason, entries = parse_gtop100_pingback(json_data, form_data)
    if not allowed:
        return False, 0, reason
    if reason == "no_entries":
        return True, 0, "no_entries"

    created = 0
    for entry in entries:
        if not _gtop100_success_ok(entry.get("success")):
            logger.info("gtop100 pingback skipped non-success entry: %s", entry)
            continue
        user_raw = str(entry.get("pb_name") or entry.get("pingUsername") or "").strip()
        if not user_raw.isdigit():
            logger.warning("gtop100 pingback invalid user_id=%s", user_raw)
            continue
        uid = int(user_raw)
        vote_ip = str(entry.get("ip") or entry.get("VoterIP") or "").strip() or None
        processed, was_created = record_provider_vote(
            GTOP100_PROVIDER,
            uid,
            vote_ip,
            conn=conn,
        )
        if not processed:
            return False, created, "unavailable"
        if was_created:
            created += 1
    return True, created, "ok"


def get_arena_top100_secret() -> str:
    return os.environ.get(ARENA_TOP100_SECRET_ENV, "").strip()


def _merge_postback_params(
    json_data: Optional[Mapping[str, Any]],
    form_data: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(form_data, Mapping):
        merged.update(dict(form_data))
    if isinstance(json_data, Mapping):
        merged.update(dict(json_data))
    return merged


def parse_arena_top100_postback(
    params: Mapping[str, Any],
) -> Tuple[bool, str, Optional[int], Optional[str], Optional[int]]:
    """
    Validate Arena-Top100 callback envelope.

    Returns (allowed, reason, user_id, vote_ip, reset_at).
    """
    expected_secret = get_arena_top100_secret()
    if not expected_secret:
        logger.warning("arena_top100 postback: %s not configured", ARENA_TOP100_SECRET_ENV)
        return False, "secret_missing", None, None, None

    secret = str(params.get("secret") or "").strip()
    if secret != expected_secret:
        logger.warning("arena_top100 postback: invalid secret")
        return False, "forbidden", None, None, None

    voted = str(params.get("voted") or "").strip()
    if voted != "1":
        return True, "vote_not_valid", None, None, None

    user_raw = str(params.get("userid") or params.get("user_id") or "").strip()
    if not user_raw.isdigit():
        logger.warning("arena_top100 postback invalid userid=%s", user_raw)
        return True, "invalid_user_id", None, None, None

    vote_ip = str(params.get("userip") or params.get("ip") or "").strip() or None
    reset_raw = params.get("reset")
    reset_at: Optional[int] = None
    if reset_raw is not None and str(reset_raw).strip():
        try:
            reset_at = int(reset_raw)
        except (TypeError, ValueError):
            logger.warning("arena_top100 postback invalid reset=%s", reset_raw)
            reset_at = None

    return True, "ok", int(user_raw), vote_ip, reset_at


def handle_arena_top100_postback(
    json_data: Optional[Mapping[str, Any]],
    form_data: Optional[Mapping[str, Any]],
    *,
    conn,
) -> Tuple[bool, int, str]:
    params = _merge_postback_params(json_data, form_data)
    allowed, reason, uid, vote_ip, reset_at = parse_arena_top100_postback(params)
    if not allowed:
        return False, 0, reason
    if reason in ("vote_not_valid", "invalid_user_id"):
        return True, 0, reason

    provider_ref_override: Optional[str] = None
    if reset_at is not None and reset_at > 0:
        provider_ref_override = f"{ARENA_TOP100_PROVIDER}:{uid}:{reset_at}"

    processed, was_created = record_provider_vote(
        ARENA_TOP100_PROVIDER,
        uid,
        vote_ip,
        conn=conn,
        provider_ref_override=provider_ref_override,
        provider_next_vote_at=reset_at,
    )
    if not processed:
        return False, 0, "unavailable"
    return True, 1 if was_created else 0, "ok"


def get_gametoor_ivn_key() -> str:
    return os.environ.get(GAMETOOR_IVN_KEY_ENV, "").strip()


def _gametoor_already_voted(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes")


def parse_gametoor_ivn(
    params: Mapping[str, Any],
) -> Tuple[bool, str, Optional[int], Optional[str]]:
    """
    Validate GameToor IVN envelope.

    Returns (allowed, reason, user_id, vote_ip).
    """
    expected_key = get_gametoor_ivn_key()
    if not expected_key:
        logger.warning("gametoor ivn: %s not configured", GAMETOOR_IVN_KEY_ENV)
        return False, "key_missing", None, None

    key = str(params.get("key") or "").strip()
    if key != expected_key:
        logger.warning("gametoor ivn: invalid key")
        return False, "forbidden", None, None

    if _gametoor_already_voted(params.get("already_voted")):
        logger.info("gametoor ivn: already_voted for custom=%s", params.get("custom"))
        return True, "already_voted", None, None

    user_raw = str(params.get("custom") or "").strip()
    if not user_raw.isdigit():
        logger.warning("gametoor ivn invalid custom=%s", user_raw)
        return True, "invalid_user_id", None, None

    vote_ip = str(params.get("ip") or "").strip() or None
    return True, "ok", int(user_raw), vote_ip


def handle_gametoor_ivn(
    json_data: Optional[Mapping[str, Any]],
    form_data: Optional[Mapping[str, Any]],
    *,
    conn,
) -> Tuple[bool, int, str]:
    params = _merge_postback_params(json_data, form_data)
    allowed, reason, uid, vote_ip = parse_gametoor_ivn(params)
    if not allowed:
        return False, 0, reason
    if reason in ("already_voted", "invalid_user_id"):
        return True, 0, reason
    if uid is None or uid <= 0 or not _user_exists(uid, conn=conn):
        logger.warning("gametoor ivn unknown user_id=%s", uid)
        return True, 0, "invalid_user"

    processed, was_created = record_provider_vote(
        GAMETOOR_PROVIDER,
        uid,
        vote_ip,
        conn=conn,
    )
    if not processed:
        return False, 0, "unavailable"
    return True, 1 if was_created else 0, "ok"


def record_provider_vote(
    provider_key: str,
    user_id: int,
    vote_ip: Optional[str],
    *,
    conn,
    now: Optional[float] = None,
    reward_payload: Optional[Mapping[str, Any]] = None,
    provider_ref_override: Optional[str] = None,
    provider_next_vote_at: Optional[int] = None,
) -> Tuple[bool, bool]:
    if not vote_rewards_schema_ready(conn):
        return False, False

    provider = _get_provider(provider_key, conn=conn)
    if not provider or not provider["enabled"]:
        return True, False

    uid = int(user_id)
    if uid <= 0 or not _user_exists(uid, conn=conn):
        return True, False

    ts = int(now if now is not None else time.time())
    pref = str(provider_ref_override or "").strip() or provider_ref(
        str(provider_key), uid, ts, int(provider["cooldown_sec"])
    )
    rolled = dict(reward_payload) if reward_payload else roll_vote_reward()
    reward_key = str(rolled.get("reward_key") or provider["reward_key"])
    payload_json = json.dumps(rolled)
    ip_val = str(vote_ip).strip()[:64] if vote_ip else None

    next_at_val: Optional[int] = None
    if provider_next_vote_at is not None:
        try:
            next_at_val = int(provider_next_vote_at)
        except (TypeError, ValueError):
            next_at_val = None

    cur = conn.cursor()
    if next_at_val is not None and vote_reward_next_at_column_ready(conn):
        cur.execute(
            """
            INSERT INTO vote_rewards (
                provider, user_id, vote_ip, provider_ref, status,
                reward_key, reward_payload_json, voted_at, created_at,
                provider_next_vote_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            ON CONFLICT(provider, user_id, provider_ref) DO NOTHING;
            """,
            (
                str(provider_key),
                uid,
                ip_val,
                pref,
                reward_key,
                payload_json,
                ts,
                ts,
                next_at_val,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO vote_rewards (
                provider, user_id, vote_ip, provider_ref, status,
                reward_key, reward_payload_json, voted_at, created_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
            ON CONFLICT(provider, user_id, provider_ref) DO NOTHING;
            """,
            (
                str(provider_key),
                uid,
                ip_val,
                pref,
                reward_key,
                payload_json,
                ts,
                ts,
            ),
        )
    return True, cur.rowcount > 0


def record_topg_vote(
    user_id: int,
    vote_ip: Optional[str],
    *,
    conn,
    now: Optional[float] = None,
    reward_payload: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, bool]:
    return record_provider_vote(
        TOPG_PROVIDER,
        user_id,
        vote_ip,
        conn=conn,
        now=now,
        reward_payload=reward_payload,
    )


def _first_param_value(params: Mapping[str, Any], keys: Sequence[str]) -> Optional[str]:
    for key in keys:
        val = params.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return None


def parse_provider_postback(
    provider_key: str,
    *,
    query_params: Mapping[str, Any],
    form_params: Optional[Mapping[str, Any]] = None,
    remote_addr: Optional[str] = None,
    conn,
) -> Tuple[bool, str, Optional[int], Optional[str]]:
    provider = _get_provider(provider_key, conn=conn)
    if not provider or not provider["enabled"]:
        return False, "provider_disabled", None, None
    if not provider["postback_enabled"]:
        return False, "postback_disabled", None, None

    try:
        config = json.loads(provider["postback_config_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        config = {}
    if not isinstance(config, dict):
        config = {}

    remote_host = str(config.get("remote_host") or "").strip()
    strict_ip = bool(config.get("strict_ip_check"))
    if str(provider_key) == TOPG_PROVIDER:
        strict_ip = topg_strict_ip_check_enabled()
    if remote_host and not _remote_host_allowed(remote_addr, remote_host, strict=strict_ip):
        logger.warning(
            "vote postback blocked by IP provider=%s remote_addr=%s expected_host=%s strict=%s",
            provider_key,
            remote_addr,
            remote_host,
            strict_ip,
        )
        return False, "forbidden", None, None

    merged: Dict[str, Any] = {}
    merged.update(dict(query_params or {}))
    if form_params:
        merged.update(dict(form_params))

    voted_param = str(config.get("voted_param") or "").strip()
    if voted_param and bool(config.get("require_voted_flag")):
        voted_raw = merged.get(voted_param)
        try:
            voted_ok = int(voted_raw) == 1
        except (TypeError, ValueError):
            voted_ok = str(voted_raw or "").strip().lower() in ("1", "true", "yes")
        if not voted_ok:
            return False, "vote_not_valid", None, None

    user_id_params = config.get("user_id_params") or ["p_resp", "userid", "user_id"]
    if isinstance(user_id_params, str):
        user_id_params = [user_id_params]
    user_raw = _first_param_value(merged, [str(k) for k in user_id_params])
    if not user_raw:
        return False, "missing_user_id", None, None
    if bool(config.get("require_numeric_user_id", True)) and not user_raw.isdigit():
        return False, "invalid_user_id", None, None
    user_id = int(user_raw) if user_raw.isdigit() else 0
    if user_id <= 0:
        return False, "invalid_user_id", None, None

    ip_params = config.get("ip_params") or ["ip", "userip"]
    if isinstance(ip_params, str):
        ip_params = [ip_params]
    vote_ip = _first_param_value(merged, [str(k) for k in ip_params])
    return True, "ok", user_id, vote_ip


def handle_provider_postback(
    provider_key: str,
    *,
    query_params: Mapping[str, Any],
    form_params: Optional[Mapping[str, Any]] = None,
    remote_addr: Optional[str] = None,
    conn,
) -> Tuple[bool, bool, str]:
    allowed, reason, user_id, vote_ip = parse_provider_postback(
        provider_key,
        query_params=query_params,
        form_params=form_params,
        remote_addr=remote_addr,
        conn=conn,
    )
    if not allowed:
        return False, False, reason
    assert user_id is not None
    processed, created = record_provider_vote(provider_key, user_id, vote_ip, conn=conn)
    if not processed:
        return False, False, "unavailable"
    return True, created, "ok"


def handle_vote_visit(
    user_id: int,
    provider_key: str,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, bool, str, int]:
    """
    Record a vote when the player clicks a provider link in Vote Center.

    Hard provider cooldown: no reward is created while cooldown is active.
    """
    provider = _get_provider(str(provider_key), conn=conn)
    if not provider or not provider["enabled"]:
        return False, False, "provider_disabled", 0
    if not provider["postback_enabled"]:
        return True, False, "postback_disabled", 0

    uid = int(user_id)
    if uid <= 0 or not _user_exists(uid, conn=conn):
        return False, False, "invalid_user", 0

    ts = int(now if now is not None else time.time())
    cd = get_provider_cooldown_status(uid, provider, conn=conn, now=ts)
    if not cd["can_vote"]:
        return True, False, "cooldown_active", int(cd["cooldown_remaining_sec"])

    processed, created = record_provider_vote(
        str(provider_key),
        uid,
        None,
        conn=conn,
        now=ts,
    )
    if not processed:
        return False, False, "unavailable", 0
    if created:
        return True, True, "reward_pending", 0
    return True, False, "cooldown_active", int(cd["cooldown_remaining_sec"])


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


def _grant_vote_payload(
    user_id: int,
    planet_id: int,
    payload: Mapping[str, Any],
    *,
    conn,
    now: float,
) -> Tuple[bool, str, Dict[str, Any]]:
    rtype = str(payload.get("reward_type") or "lootbox")
    result: Dict[str, Any] = {
        "reward_type": rtype,
        "reward_key": str(payload.get("reward_key") or ""),
    }

    if rtype == "lootbox":
        box_key = str(payload.get("box_key") or DEFAULT_VOTE_BOX_KEY)
        amount = int(payload.get("amount") or 1)
        if not is_allowed_vote_reward_box(box_key):
            return False, "reward_not_allowed", result
        if not inventory_schema_ready(conn):
            return False, "inventory_unavailable", result
        inv_key = resolve_inventory_key(box_key) or box_key
        if not grant_inventory_item(
            int(user_id),
            inv_key,
            amount,
            conn=conn,
            metadata={"source": "vote_reward", "box_key": box_key},
        ):
            return False, "grant_failed", result
        if table_exists(conn, "lootbox_inventory"):
            cur = conn.cursor()
            for _ in range(amount):
                cur.execute(
                    """
                    INSERT INTO lootbox_inventory (player_id, box_key, source, created_at)
                    VALUES (?, ?, 'vote_reward', ?);
                    """,
                    (int(user_id), str(box_key), int(now)),
                )
        result.update({"box_key": box_key, "amount": amount, "inventory_key": inv_key})
        return True, "ok", result

    if rtype == "resources":
        metal = int(payload.get("metal") or 0)
        crystal = int(payload.get("crystal") or 0)
        fuel_cells = int(payload.get("fuel_cells") or 0)
        if metal <= 0 and crystal <= 0 and fuel_cells <= 0:
            return False, "grant_failed", result
        _credit_planet_resources(
            int(planet_id),
            metal=metal,
            crystal=crystal,
            fuel_cells=fuel_cells,
            conn=conn,
        )
        result.update({"metal": metal, "crystal": crystal, "fuel_cells": fuel_cells, "planet_id": int(planet_id)})
        return True, "ok", result

    if rtype == "ships":
        from .fleet import add_planet_ships

        ships_in = payload.get("ships") if isinstance(payload.get("ships"), dict) else {}
        ships: Dict[str, int] = {}
        for key, amt in ships_in.items():
            sk = canonical_ship_key(str(key))
            n = int(amt or 0)
            if n > 0 and is_known_ship_key(sk):
                ships[sk] = ships.get(sk, 0) + n
        if not ships:
            return False, "grant_failed", result
        add_planet_ships(int(planet_id), int(user_id), ships, conn=conn)
        result.update({"ships": ships, "planet_id": int(planet_id)})
        return True, "ok", result

    if rtype == "defense":
        from .models import add_planet_defense

        defense_in = payload.get("defense") if isinstance(payload.get("defense"), dict) else {}
        defense: Dict[str, int] = {}
        for key, amt in defense_in.items():
            dk = str(key).strip()
            n = int(amt or 0)
            if n > 0 and is_known_defense_key(dk):
                defense[dk] = defense.get(dk, 0) + n
        if not defense:
            return False, "grant_failed", result
        add_planet_defense(int(planet_id), defense, conn=conn)
        result.update({"defense": defense, "planet_id": int(planet_id)})
        return True, "ok", result

    return False, "reward_not_allowed", result


def claim_vote_reward(
    user_id: int,
    reward_id: int,
    *,
    conn,
    planet_id: Optional[int] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not vote_rewards_schema_ready(conn):
        return False, "vote_rewards_unavailable", None

    uid = int(user_id)
    rid = int(reward_id)
    if rid <= 0:
        return False, "invalid_reward_id", None

    if planet_id is None:
        from .planet_evolution.repository import get_context_planet

        planet_id = int(get_context_planet(uid, conn=conn)["id"])

    ts = float(now if now is not None else time.time())
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, status, reward_payload_json, provider, reward_key
        FROM vote_rewards
        WHERE id = ? AND user_id = ?
        LIMIT 1;
        """,
        (rid, uid),
    )
    row = cur.fetchone()
    if not row:
        return False, "reward_not_found", None
    if str(row["status"]) != "pending":
        return False, "reward_already_claimed", None

    payload = _parse_reward_payload(_row_str(row, "reward_payload_json"))
    ok, grant_reason, grant_result = _grant_vote_payload(uid, int(planet_id), payload, conn=conn, now=ts)
    if not ok:
        return False, grant_reason, grant_result

    cur.execute(
        """
        UPDATE vote_rewards
        SET status = 'claimed', claimed_at = ?
        WHERE id = ? AND user_id = ? AND status = 'pending';
        """,
        (int(ts), rid, uid),
    )
    if cur.rowcount <= 0:
        return False, "reward_already_claimed", None

    return True, "vote_reward_claimed", {
        "reward_id": rid,
        "provider": str(row["provider"]),
        **grant_result,
    }


def claim_all_vote_rewards(
    user_id: int,
    *,
    conn,
    planet_id: Optional[int] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not vote_rewards_schema_ready(conn):
        return False, "vote_rewards_unavailable", {}
    uid = int(user_id)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM vote_rewards
        WHERE user_id = ? AND status = 'pending'
        ORDER BY voted_at ASC;
        """,
        (uid,),
    )
    reward_ids = [int(r["id"]) for r in cur.fetchall()]
    if not reward_ids:
        return False, "no_pending_rewards", {"claimed": [], "claimed_count": 0}

    claimed: List[Dict[str, Any]] = []
    for rid in reward_ids:
        ok, reason, result = claim_vote_reward(uid, rid, conn=conn, planet_id=planet_id, now=now)
        if not ok:
            return False, reason, {"claimed": claimed, "claimed_count": len(claimed), "failed_reward_id": rid}
        if result:
            claimed.append(result)
    return True, "vote_rewards_claimed_all", {"claimed": claimed, "claimed_count": len(claimed)}
