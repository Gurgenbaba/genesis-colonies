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
from .db import column_exists, db, table_columns, table_exists, tables_exist
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
DEFAULT_REWARD_KEY = "standard_box"
STANDARD_VOTE_REWARD_TYPE = "standard_box"

STANDARD_VOTE_REWARD_PAYLOAD: Dict[str, Any] = {
    "reward_type": STANDARD_VOTE_REWARD_TYPE,
    "reward_key": DEFAULT_REWARD_KEY,
    "box_key": DEFAULT_VOTE_BOX_KEY,
    "amount": 1,
}
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

VOTE_CHANNEL_PLAYER = "player"
# Historical only — synthetic grants are retired; never write this channel again.
VOTE_CHANNEL_REENGAGEMENT = "reengagement"
ALLOWED_VOTE_CHANNELS = frozenset({VOTE_CHANNEL_PLAYER})

ALLOWED_VOTE_BOX_KEYS = frozenset({DEFAULT_VOTE_BOX_KEY})

REWARD_TYPE_LABEL_KEYS: Dict[str, str] = {
    "standard_box": "vote_reward_type_standard_box",
    "lootbox": "vote_reward_type_standard_box",
}


def vote_rewards_schema_ready(conn) -> bool:
    return table_exists(conn, "vote_rewards")


def vote_reward_next_at_column_ready(conn) -> bool:
    if not vote_rewards_schema_ready(conn):
        return False
    return column_exists(conn, "vote_rewards", "provider_next_vote_at")


def vote_channel_column_ready(conn) -> bool:
    if not vote_rewards_schema_ready(conn):
        return False
    return column_exists(conn, "vote_rewards", "vote_channel")


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


def _normalize_vote_reward_payload(
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Votes always grant exactly one standard supply container."""
    return dict(STANDARD_VOTE_REWARD_PAYLOAD)


def roll_vote_reward(*, rng: Optional[random.Random] = None) -> Dict[str, Any]:
    """Every vote grants exactly one standard supply container."""
    return _normalize_vote_reward_payload()


def _parse_reward_payload(raw: str) -> Dict[str, Any]:
    if not raw:
        return _normalize_vote_reward_payload()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return _normalize_vote_reward_payload(data)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return _normalize_vote_reward_payload()


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
    normalized = _normalize_vote_reward_payload(payload)
    box_key = str(normalized.get("box_key") or DEFAULT_VOTE_BOX_KEY)
    inv_key = resolve_inventory_key(box_key) or box_key
    meta = item_catalog_entry(inv_key)
    return [
        {
            "kind": "lootbox",
            "name_key": str(meta.get("name_key") or f"inv_{inv_key}"),
            "name_fallback": inv_key,
            "image": _static_image_url(container_image_path(inv_key)),
            "amount": int(normalized.get("amount") or 1),
            "rarity": str(meta.get("rarity") or "common"),
        }
    ]


def _reward_summary(payload: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_vote_reward_payload(payload)
    rtype = str(normalized["reward_type"])
    rkey = str(normalized["reward_key"])
    label_key = REWARD_TYPE_LABEL_KEYS.get(rtype, "vote_reward_type_standard_box")
    return {
        "reward_type": rtype,
        "reward_key": rkey,
        "reward_type_label_key": label_key,
        "title_key": "vote_reward_title",
        "box_key": str(normalized["box_key"]),
        "amount": int(normalized["amount"]),
        "display_items": _reward_display_items(normalized),
    }


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


def _provider_latest_vote_row(
    user_id: int,
    provider_key: str,
    *,
    conn,
) -> Optional[Any]:
    """
    Latest *external* vote row for provider (player channel only).

    Historical ``vote_channel=reengagement`` rows must not drive cooldowns —
    they were synthetic grants and would block real Vote Center votes.
    """
    cur = conn.cursor()
    channel_filter = ""
    if vote_channel_column_ready(conn):
        channel_filter = " AND COALESCE(vote_channel, 'player') = 'player'"
    if vote_reward_next_at_column_ready(conn):
        cur.execute(
            f"""
            SELECT voted_at, provider_next_vote_at
            FROM vote_rewards
            WHERE user_id = ? AND provider = ?{channel_filter}
            ORDER BY voted_at DESC
            LIMIT 1;
            """,
            (int(user_id), str(provider_key)),
        )
    else:
        cur.execute(
            f"""
            SELECT voted_at, NULL AS provider_next_vote_at
            FROM vote_rewards
            WHERE user_id = ? AND provider = ?{channel_filter}
            ORDER BY voted_at DESC
            LIMIT 1;
            """,
            (int(user_id), str(provider_key)),
        )
    return cur.fetchone()


def _provider_last_vote_at(user_id: int, provider_key: str, *, conn) -> Optional[int]:
    row = _provider_latest_vote_row(user_id, provider_key, conn=conn)
    if not row or row["voted_at"] is None:
        return None
    return int(row["voted_at"])


def get_provider_vote_end(
    user_id: int,
    provider: Mapping[str, Any],
    *,
    conn,
) -> int:
    """
    Absolute unix time when the next vote is allowed on this provider.
    Returns 0 when the player has never voted on this provider.
    """
    provider_key = str(provider["provider_key"])
    cooldown_sec = int(provider.get("cooldown_sec") or VOTE_COOLDOWN_SEC)
    row = _provider_latest_vote_row(user_id, provider_key, conn=conn)
    if not row or row["voted_at"] is None:
        return 0
    next_at_raw = row["provider_next_vote_at"]
    if next_at_raw is not None:
        try:
            next_at = int(next_at_raw)
        except (TypeError, ValueError):
            next_at = 0
        if next_at > 0:
            return next_at
    return int(row["voted_at"]) + cooldown_sec


def can_process_provider_vote(
    user_id: int,
    provider: Mapping[str, Any],
    *,
    conn,
    now: Optional[int] = None,
) -> bool:
    """True when provider cooldown has expired and a new vote may be recorded."""
    ts = int(now if now is not None else time.time())
    vote_end = get_provider_vote_end(user_id, provider, conn=conn)
    return vote_end <= ts


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
    vote_end = get_provider_vote_end(user_id, provider, conn=conn)
    can_vote = vote_end <= ts
    next_vote_at: Optional[int] = None
    cooldown_remaining_sec = 0
    if not can_vote and vote_end > 0:
        next_vote_at = vote_end
        cooldown_remaining_sec = max(0, vote_end - ts)
    return {
        "can_vote": can_vote,
        "last_vote_at": last_vote_at,
        "next_vote_at": next_vote_at,
        "vote_end": vote_end if vote_end > 0 else None,
        "cooldown_remaining_sec": cooldown_remaining_sec,
        "cooldown_sec": cooldown_sec,
    }


def _empty_process_vote_result(
    *,
    error: str = "",
    cooldown_remaining_sec: int = 0,
) -> Dict[str, Any]:
    return {
        "success": False,
        "created": False,
        "already_voted": False,
        "error": error,
        "cooldown_remaining_sec": int(cooldown_remaining_sec),
        "reward_id": None,
    }


def process_provider_vote(
    provider_key: str,
    user_id: int,
    vote_ip: Optional[str],
    *,
    conn,
    now: Optional[float] = None,
    reward_payload: Optional[Mapping[str, Any]] = None,
    provider_ref_override: Optional[str] = None,
    provider_next_vote_at: Optional[int] = None,
    vote_channel: str = VOTE_CHANNEL_PLAYER,
) -> Dict[str, Any]:
    """
    Canonical vote write path for real player accounts (postback, visit, IVN).

    Cooldown and idempotency are enforced before INSERT; rewards stay pending until claim.
    """
    if not vote_rewards_schema_ready(conn):
        return _empty_process_vote_result(error="unavailable")

    provider = _get_provider(provider_key, conn=conn)
    if not provider or not provider["enabled"]:
        return _empty_process_vote_result(error="provider_disabled")

    uid = int(user_id)
    if uid <= 0 or not _user_exists(uid, conn=conn):
        return _empty_process_vote_result(error="invalid_user")

    ts = int(now if now is not None else time.time())
    cd = get_provider_cooldown_status(uid, provider, conn=conn, now=ts)
    if not cd["can_vote"]:
        return {
            "success": True,
            "created": False,
            "already_voted": True,
            "error": "cooldown",
            "cooldown_remaining_sec": int(cd["cooldown_remaining_sec"]),
            "reward_id": None,
        }

    cooldown_sec = int(provider.get("cooldown_sec") or VOTE_COOLDOWN_SEC)
    next_at_val: Optional[int] = None
    if provider_next_vote_at is not None:
        try:
            next_at_val = int(provider_next_vote_at)
        except (TypeError, ValueError):
            next_at_val = None
    if next_at_val is None or next_at_val <= ts:
        next_at_val = ts + cooldown_sec

    processed, created = record_provider_vote(
        str(provider_key),
        uid,
        vote_ip,
        conn=conn,
        now=ts,
        reward_payload=reward_payload,
        provider_ref_override=provider_ref_override,
        provider_next_vote_at=next_at_val,
        skip_cooldown_check=True,
        vote_channel=str(vote_channel or VOTE_CHANNEL_PLAYER),
    )
    if not processed:
        return _empty_process_vote_result(error="unavailable")

    reward_id: Optional[int] = None
    if created:
        pref = str(provider_ref_override or "").strip() or provider_ref(
            str(provider_key), uid, ts, cooldown_sec
        )
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id FROM vote_rewards
            WHERE provider = ? AND user_id = ? AND provider_ref = ?
            LIMIT 1;
            """,
            (str(provider_key), uid, pref),
        )
        row = cur.fetchone()
        if row:
            reward_id = int(row["id"])

    if created:
        return {
            "success": True,
            "created": True,
            "already_voted": False,
            "error": "",
            "cooldown_remaining_sec": 0,
            "reward_id": reward_id,
        }

    return {
        "success": True,
        "created": False,
        "already_voted": True,
        "error": "cooldown",
        "cooldown_remaining_sec": int(cd["cooldown_remaining_sec"]),
        "reward_id": None,
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
    """Providers the player can vote on right now (server-authoritative cooldown)."""
    if not vote_system_ready(conn):
        return 0
    ts = int(now if now is not None else time.time())
    total = 0
    for provider in list_enabled_providers(conn=conn):
        cd = get_provider_cooldown_status(int(user_id), provider, conn=conn, now=ts)
        if cd["can_vote"]:
            total += 1
    return total


def count_pending_vote_rewards(user_id: int, *, conn) -> int:
    """Unclaimed vote rewards waiting in the Vote Center (e.g. after postback while away)."""
    if not vote_rewards_schema_ready(conn):
        return 0
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM vote_rewards
        WHERE user_id = ? AND status = 'pending';
        """,
        (int(user_id),),
    )
    return int(cur.fetchone()["c"] or 0)


def count_vote_center_attention(user_id: int, *, conn, now: Optional[int] = None) -> int:
    """Diet-safe Vote Center badge: voteable providers + pending rewards.

    The full Vote Center keeps the detailed per-provider serializers. The high-frequency
    nav path reads schema compatibility once, then resolves all enabled provider cooldowns
    from one bulk query instead of repeating latest-vote/schema probes per provider.
    """
    uid = int(user_id)
    if uid <= 0:
        return 0
    if not tables_exist(conn, ("vote_rewards", "vote_providers")):
        return 0

    reward_columns = table_columns(conn, "vote_rewards")
    has_channel = "vote_channel" in reward_columns
    has_next_at = "provider_next_vote_at" in reward_columns
    channel_filter = (
        " AND COALESCE(vote_channel, 'player') = 'player'" if has_channel else ""
    )
    next_at_select = (
        "provider_next_vote_at" if has_next_at else "NULL AS provider_next_vote_at"
    )
    ts = int(now if now is not None else time.time())

    rows = conn.execute(
        f"""
        WITH latest_ranked AS (
            SELECT provider, voted_at, {next_at_select},
                   ROW_NUMBER() OVER (
                       PARTITION BY provider
                       ORDER BY voted_at DESC
                   ) AS rn
            FROM vote_rewards
            WHERE user_id = ?{channel_filter}
        ),
        pending AS (
            SELECT COUNT(*) AS c
            FROM vote_rewards
            WHERE user_id = ? AND status = 'pending'
        ),
        providers AS (
            SELECT provider_key, cooldown_sec, sort_order
            FROM vote_providers
            WHERE enabled = 1
        )
        SELECT p.provider_key, p.cooldown_sec,
               l.voted_at, l.provider_next_vote_at,
               pending.c AS pending_count
        FROM pending
        LEFT JOIN providers p ON 1 = 1
        LEFT JOIN latest_ranked l
          ON l.provider = p.provider_key AND l.rn = 1
        ORDER BY p.sort_order ASC, p.provider_key ASC;
        """,
        (uid, uid),
    ).fetchall()

    pending_count = int(rows[0]["pending_count"] or 0) if rows else 0
    voteable = 0
    for row in rows:
        provider_key = str(row["provider_key"] or "")
        if not provider_key:
            continue
        canonical = VOTE_PROVIDERS.get(provider_key) or {}
        cooldown_sec = int(
            canonical.get("cooldown_seconds")
            or row["cooldown_sec"]
            or VOTE_COOLDOWN_SEC
        )
        voted_at = row["voted_at"]
        if voted_at is None:
            voteable += 1
            continue

        next_at = 0
        next_at_raw = row["provider_next_vote_at"]
        if next_at_raw is not None:
            try:
                next_at = int(next_at_raw)
            except (TypeError, ValueError):
                next_at = 0
        vote_end = next_at if next_at > 0 else int(voted_at) + cooldown_sec
        if vote_end <= ts:
            voteable += 1

    return int(voteable + pending_count)


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
        result = process_provider_vote(
            GTOP100_PROVIDER,
            uid,
            vote_ip,
            conn=conn,
        )
        if not result["success"] and result["error"] == "unavailable":
            return False, created, "unavailable"
        if result["created"]:
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

    result = process_provider_vote(
        ARENA_TOP100_PROVIDER,
        uid,
        vote_ip,
        conn=conn,
        provider_ref_override=provider_ref_override,
        provider_next_vote_at=reset_at,
    )
    if not result["success"] and result["error"] == "unavailable":
        return False, 0, "unavailable"
    return True, 1 if result["created"] else 0, "ok"


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

    result = process_provider_vote(
        GAMETOOR_PROVIDER,
        uid,
        vote_ip,
        conn=conn,
    )
    if not result["success"] and result["error"] == "unavailable":
        return False, 0, "unavailable"
    return True, 1 if result["created"] else 0, "ok"


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
    skip_cooldown_check: bool = False,
    vote_channel: str = VOTE_CHANNEL_PLAYER,
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
    cooldown_sec = int(provider["cooldown_sec"])

    if not skip_cooldown_check:
        cd = get_provider_cooldown_status(uid, provider, conn=conn, now=ts)
        if not cd["can_vote"]:
            return True, False

    pref = str(provider_ref_override or "").strip() or provider_ref(
        str(provider_key), uid, ts, cooldown_sec
    )
    rolled = _normalize_vote_reward_payload(reward_payload)
    reward_key = str(rolled["reward_key"])
    payload_json = json.dumps(rolled)
    ip_val = str(vote_ip).strip()[:64] if vote_ip else None

    next_at_val: Optional[int] = None
    if provider_next_vote_at is not None:
        try:
            next_at_val = int(provider_next_vote_at)
        except (TypeError, ValueError):
            next_at_val = None
    if next_at_val is None or next_at_val <= ts:
        next_at_val = ts + cooldown_sec

    channel = str(vote_channel or VOTE_CHANNEL_PLAYER).strip().lower()
    if channel not in ALLOWED_VOTE_CHANNELS:
        channel = VOTE_CHANNEL_PLAYER

    cur = conn.cursor()
    if vote_channel_column_ready(conn) and vote_reward_next_at_column_ready(conn):
        cur.execute(
            """
            INSERT INTO vote_rewards (
                provider, user_id, vote_ip, provider_ref, status,
                reward_key, reward_payload_json, voted_at, created_at,
                provider_next_vote_at, vote_channel
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
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
                channel,
            ),
        )
    elif vote_reward_next_at_column_ready(conn):
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
    result = process_provider_vote(provider_key, user_id, vote_ip, conn=conn)
    if not result["success"] and result["error"] == "unavailable":
        return False, False, "unavailable"
    return True, bool(result["created"]), "ok"


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
    result = process_provider_vote(str(provider_key), uid, None, conn=conn, now=ts)
    if not result["success"]:
        if result["error"] == "unavailable":
            return False, False, "unavailable", 0
        return False, False, str(result["error"]), int(result["cooldown_remaining_sec"])

    if result["created"]:
        return True, True, "reward_pending", 0
    if result["already_voted"]:
        return True, False, "cooldown_active", int(result["cooldown_remaining_sec"])
    return True, False, "cooldown_active", 0


def _grant_vote_payload(
    user_id: int,
    planet_id: int,
    payload: Mapping[str, Any],
    *,
    conn,
    now: float,
) -> Tuple[bool, str, Dict[str, Any]]:
    normalized = _normalize_vote_reward_payload(payload)
    rtype = str(normalized["reward_type"])
    result: Dict[str, Any] = {
        "reward_type": rtype,
        "reward_key": str(normalized["reward_key"]),
    }

    box_key = str(normalized["box_key"])
    amount = int(normalized["amount"])
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


def _admin_vote_channel_expr(conn) -> str:
    if vote_channel_column_ready(conn):
        return "COALESCE(vr.vote_channel, 'player')"
    return "'player'"


def build_admin_vote_stats(*, conn, now: Optional[int] = None) -> Dict[str, Any]:
    """
    Admin Vote Center reporting.

    Distinguishes external player votes from historical synthetic reengagement grants.
    Does not mint rewards.
    """
    from .ranking import RANKING_INACTIVE_AFTER_SEC, is_player_inactive

    ts = int(now if now is not None else time.time())
    week_ago = ts - 7 * 86400
    day_ago = ts - 86400
    channel_expr = _admin_vote_channel_expr(conn)
    out: Dict[str, Any] = {
        "ready": vote_system_ready(conn),
        "inactive_threshold_sec": int(RANKING_INACTIVE_AFTER_SEC),
        "summary": {
            # Total reward rows granted (external + historical synthetic)
            "votes_7d": 0,
            "rewards_granted_7d": 0,
            "external_votes_7d": 0,
            "player_votes_7d": 0,  # alias: external
            "historical_synthetic_7d": 0,
            "reengagement_votes_7d": 0,  # alias: historical synthetic
            "votes_24h": 0,
            "rewards_granted_24h": 0,
            "external_votes_24h": 0,
            "player_votes_24h": 0,
            "historical_synthetic_24h": 0,
            "reengagement_votes_24h": 0,
            "pending_rewards": 0,
            "players_voted_7d": 0,
            "inactive_players_voted_7d": 0,
            "active_players_voted_7d": 0,
            "inactive_voteable_now": 0,
            "active_voteable_now": 0,
        },
        "providers": [],
    }
    if not out["ready"]:
        return out

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS external_votes,
            SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS synthetic_votes
        FROM vote_rewards vr
        WHERE vr.voted_at >= ?;
        """,
        (week_ago,),
    )
    row = cur.fetchone()
    total_7d = int(row["total"] or 0)
    external_7d = int(row["external_votes"] or 0)
    synthetic_7d = int(row["synthetic_votes"] or 0)
    out["summary"]["votes_7d"] = total_7d
    out["summary"]["rewards_granted_7d"] = total_7d
    out["summary"]["external_votes_7d"] = external_7d
    out["summary"]["player_votes_7d"] = external_7d
    out["summary"]["historical_synthetic_7d"] = synthetic_7d
    out["summary"]["reengagement_votes_7d"] = synthetic_7d

    cur.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS external_votes,
            SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS synthetic_votes
        FROM vote_rewards vr
        WHERE vr.voted_at >= ?;
        """,
        (day_ago,),
    )
    row24 = cur.fetchone()
    total_24h = int(row24["total"] or 0)
    external_24h = int(row24["external_votes"] or 0)
    synthetic_24h = int(row24["synthetic_votes"] or 0)
    out["summary"]["votes_24h"] = total_24h
    out["summary"]["rewards_granted_24h"] = total_24h
    out["summary"]["external_votes_24h"] = external_24h
    out["summary"]["player_votes_24h"] = external_24h
    out["summary"]["historical_synthetic_24h"] = synthetic_24h
    out["summary"]["reengagement_votes_24h"] = synthetic_24h

    cur.execute("SELECT COUNT(*) AS c FROM vote_rewards WHERE status = 'pending';")
    out["summary"]["pending_rewards"] = int(cur.fetchone()["c"] or 0)

    cur.execute(
        """
        SELECT COUNT(DISTINCT vr.user_id) AS c
        FROM vote_rewards vr
        WHERE vr.voted_at >= ?
          AND COALESCE(vr.vote_channel, 'player') = 'player';
        """
        if vote_channel_column_ready(conn)
        else """
        SELECT COUNT(DISTINCT vr.user_id) AS c
        FROM vote_rewards vr
        WHERE vr.voted_at >= ?;
        """,
        (week_ago,),
    )
    out["summary"]["players_voted_7d"] = int(cur.fetchone()["c"] or 0)

    inactive_cutoff = ts - int(RANKING_INACTIVE_AFTER_SEC)
    if vote_channel_column_ready(conn):
        cur.execute(
            """
            SELECT COUNT(DISTINCT vr.user_id) AS c
            FROM vote_rewards vr
            JOIN players p ON p.id = vr.user_id
            WHERE vr.voted_at >= ?
              AND COALESCE(vr.vote_channel, 'player') = 'player'
              AND COALESCE(p.last_seen, 0) <= ?;
            """,
            (week_ago, inactive_cutoff),
        )
    else:
        cur.execute(
            """
            SELECT COUNT(DISTINCT vr.user_id) AS c
            FROM vote_rewards vr
            JOIN players p ON p.id = vr.user_id
            WHERE vr.voted_at >= ?
              AND COALESCE(p.last_seen, 0) <= ?;
            """,
            (week_ago, inactive_cutoff),
        )
    out["summary"]["inactive_players_voted_7d"] = int(cur.fetchone()["c"] or 0)
    out["summary"]["active_players_voted_7d"] = max(
        0,
        out["summary"]["players_voted_7d"] - out["summary"]["inactive_players_voted_7d"],
    )

    providers = list_enabled_providers(conn=conn)
    provider_stats: List[Dict[str, Any]] = []
    for provider in providers:
        key = str(provider["provider_key"])
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS external_votes,
                SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS synthetic_votes
            FROM vote_rewards vr
            WHERE vr.provider = ? AND vr.voted_at >= ?;
            """,
            (key, week_ago),
        )
        prow = cur.fetchone()
        ext = int(prow["external_votes"] or 0)
        syn = int(prow["synthetic_votes"] or 0)
        provider_stats.append(
            {
                "provider_key": key,
                "display_name": str(provider["display_name"]),
                "votes_7d": int(prow["total"] or 0),
                "rewards_granted_7d": int(prow["total"] or 0),
                "external_votes_7d": ext,
                "player_votes_7d": ext,
                "historical_synthetic_7d": syn,
                "reengagement_votes_7d": syn,
                "cooldown_sec": int(provider.get("cooldown_sec") or 0),
            }
        )
    out["providers"] = provider_stats

    cur.execute(
        """
        SELECT p.id AS user_id, COALESCE(p.last_seen, 0) AS last_seen
        FROM players p
        JOIN users u ON u.id = p.id
        WHERE COALESCE(p.banned_until, 0) <= ?;
        """,
        (ts,),
    )
    inactive_voteable = 0
    active_voteable = 0
    for prow in cur.fetchall():
        uid = int(prow["user_id"])
        inactive = is_player_inactive({"last_seen": int(prow["last_seen"] or 0)}, now=ts)
        voteable = any(
            can_process_provider_vote(uid, p, conn=conn, now=ts) for p in providers
        )
        if not voteable:
            continue
        if inactive:
            inactive_voteable += 1
        else:
            active_voteable += 1
    out["summary"]["inactive_voteable_now"] = inactive_voteable
    out["summary"]["active_voteable_now"] = active_voteable
    return out


def search_admin_vote_players(
    *,
    conn,
    q: str = "",
    activity: str = "all",
    limit: int = 50,
    offset: int = 0,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    from .ranking import RANKING_INACTIVE_AFTER_SEC, is_player_inactive

    ts = int(now if now is not None else time.time())
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    inactive_cutoff = ts - int(RANKING_INACTIVE_AFTER_SEC)
    channel_expr = _admin_vote_channel_expr(conn)

    where: List[str] = ["COALESCE(p.banned_until, 0) <= ?"]
    params: List[Any] = [ts]
    q_norm = str(q or "").strip()
    if q_norm:
        where.append("(u.username LIKE ? OR p.name LIKE ? OR CAST(p.id AS TEXT) = ?)")
        like = f"%{q_norm}%"
        params.extend([like, like, q_norm])

    activity_norm = str(activity or "all").strip().lower()
    if activity_norm == "active":
        where.append("COALESCE(p.last_seen, 0) > ?")
        params.append(inactive_cutoff)
    elif activity_norm == "inactive":
        where.append("(COALESCE(p.last_seen, 0) <= ? OR COALESCE(p.last_seen, 0) = 0)")
        params.append(inactive_cutoff)

    where_sql = " AND ".join(where)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM players p
        JOIN users u ON u.id = p.id
        WHERE {where_sql};
        """,
        tuple(params),
    )
    total = int(cur.fetchone()["c"] or 0)

    cur.execute(
        f"""
        SELECT p.id AS user_id, u.username, p.name AS player_name,
               COALESCE(p.last_seen, 0) AS last_seen
        FROM players p
        JOIN users u ON u.id = p.id
        WHERE {where_sql}
        ORDER BY p.last_seen DESC, p.id ASC
        LIMIT ? OFFSET ?;
        """,
        tuple(params) + (lim, off),
    )
    providers = list_enabled_providers(conn=conn)
    players: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        uid = int(row["user_id"])
        last_seen = int(row["last_seen"] or 0)
        inactive = is_player_inactive({"last_seen": last_seen}, now=ts)
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN {channel_expr} = 'player' THEN 1 ELSE 0 END) AS external_votes,
                SUM(CASE WHEN {channel_expr} = 'reengagement' THEN 1 ELSE 0 END) AS synthetic_votes,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_rewards
            FROM vote_rewards vr
            WHERE vr.user_id = ?;
            """,
            (uid,),
        )
        vrow = cur.fetchone()
        provider_rows: List[Dict[str, Any]] = []
        for provider in providers:
            pkey = str(provider["provider_key"])
            cd = get_provider_cooldown_status(uid, provider, conn=conn, now=ts)
            cur.execute(
                f"""
                SELECT voted_at, {channel_expr} AS vote_channel
                FROM vote_rewards vr
                WHERE vr.user_id = ? AND vr.provider = ?
                ORDER BY vr.voted_at DESC
                LIMIT 1;
                """,
                (uid, pkey),
            )
            last = cur.fetchone()
            provider_rows.append(
                {
                    "provider_key": pkey,
                    "display_name": str(provider["display_name"]),
                    "last_vote_at": int(last["voted_at"]) if last and last["voted_at"] else None,
                    "last_channel": str(last["vote_channel"]) if last else None,
                    "next_vote_at": cd["next_vote_at"],
                    "can_vote": bool(cd["can_vote"]),
                    "cooldown_remaining_sec": int(cd["cooldown_remaining_sec"]),
                    "vote_end": cd.get("vote_end"),
                }
            )
        external = int(vrow["external_votes"] or 0)
        synthetic = int(vrow["synthetic_votes"] or 0)
        players.append(
            {
                "user_id": uid,
                "username": str(row["username"]),
                "player_name": str(row["player_name"] or row["username"]),
                "last_seen": last_seen,
                "activity": "inactive" if inactive else "active",
                "total_votes": int(vrow["total"] or 0),
                "rewards_granted": int(vrow["total"] or 0),
                "external_votes": external,
                "player_votes": external,
                "historical_synthetic_votes": synthetic,
                "reengagement_votes": synthetic,
                "pending_rewards": int(vrow["pending_rewards"] or 0),
                "providers": provider_rows,
            }
        )

    return {
        "ok": True,
        "total": total,
        "limit": lim,
        "offset": off,
        "players": players,
    }
