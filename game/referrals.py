"""
GC-703 — Referral system (server-authoritative rewards via inventory lootboxes).

Each player has a unique referral code. Referred players may link a code once
(at registration or ingame). Referrer tier rewards unlock after referred players
meet activity milestones; same-IP referrals are recorded but do not count.
"""

from __future__ import annotations

import secrets
import string
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .auction_house import is_event_box, resolve_inventory_key
from .db import column_exists, table_exists
from .inventory import grant_inventory_item, inventory_schema_ready
from .inventory_catalog import container_image_path, item_catalog_entry

REFERRAL_MIN_ACCOUNT_AGE_SEC = 24 * 60 * 60
REFERRAL_MIN_PLANET_LEVEL = 3
REFERRAL_CODE_LENGTH = 8
REFERRAL_CODE_ALPHABET = string.ascii_uppercase + string.digits

# Ticket box keys → inventory (non-event only).
ALLOWED_REFERRAL_BOX_KEYS = frozenset(
    {
        "generic_supply_container",
        "resource_cache",
        "research_capsule",
        "military_cache",
        "premium_cache",
        "alien_cache",
    }
)

REFERRER_TIER_REWARDS: Tuple[Dict[str, Any], ...] = (
    {
        "reward_key": "tier_1",
        "required_count": 1,
        "box_key": "generic_supply_container",
        "amount": 1,
        "label_key": "referral_tier_1_label",
        "desc_key": "referral_tier_1_desc",
    },
    {
        "reward_key": "tier_3",
        "required_count": 3,
        "box_key": "resource_cache",
        "amount": 1,
        "label_key": "referral_tier_3_label",
        "desc_key": "referral_tier_3_desc",
    },
    {
        "reward_key": "tier_5",
        "required_count": 5,
        "box_key": "research_capsule",
        "amount": 1,
        "label_key": "referral_tier_5_label",
        "desc_key": "referral_tier_5_desc",
    },
    {
        "reward_key": "tier_10",
        "required_count": 10,
        "box_key": "military_cache",
        "amount": 1,
        "label_key": "referral_tier_10_label",
        "desc_key": "referral_tier_10_desc",
    },
    {
        "reward_key": "tier_25",
        "required_count": 25,
        "box_key": "premium_cache",
        "amount": 1,
        "label_key": "referral_tier_25_label",
        "desc_key": "referral_tier_25_desc",
    },
    {
        "reward_key": "tier_50",
        "required_count": 50,
        "box_key": "alien_cache",
        "amount": 1,
        "label_key": "referral_tier_50_label",
        "desc_key": "referral_tier_50_desc",
    },
)

REFERRED_LINK_REWARD = {
    "reward_scope": "referred",
    "reward_key": "referred_starter",
    "box_key": "generic_supply_container",
    "amount": 1,
    "label_key": "referral_referred_starter_label",
    "desc_key": "referral_referred_starter_desc",
}


def referrals_schema_ready(conn) -> bool:
    return (
        table_exists(conn, "player_referral_codes")
        and table_exists(conn, "player_referrals")
        and table_exists(conn, "referral_reward_claims")
    )


def is_allowed_referral_box(box_key: str) -> bool:
    key = str(box_key or "").strip()
    if not key or is_event_box(key):
        return False
    return key in ALLOWED_REFERRAL_BOX_KEYS


def _static_image_url(rel_path: str) -> str:
    rel = str(rel_path or "").strip().lstrip("/")
    if rel.startswith("static/"):
        rel = rel[7:]
    return f"/static/{rel}" if rel else "/static/img/lootboxes/Generic_Supply_Container.png"


def _box_display(box_key: str, amount: int = 1) -> Dict[str, Any]:
    inv_key = resolve_inventory_key(box_key) or box_key
    meta = item_catalog_entry(inv_key)
    return {
        "kind": "lootbox",
        "box_key": str(box_key),
        "inventory_key": inv_key,
        "name_key": str(meta.get("name_key") or f"inv_{inv_key}"),
        "name_fallback": inv_key,
        "image": _static_image_url(container_image_path(inv_key)),
        "amount": int(amount),
        "rarity": str(meta.get("rarity") or "common"),
    }


def _row_int(row: Any, key: str, default: int = 0) -> int:
    if row is None:
        return default
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _row_str(row: Any, key: str, default: str = "") -> str:
    if row is None:
        return default
    try:
        val = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return str(val) if val is not None else default


def _user_exists(user_id: int, *, conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE id = ? LIMIT 1;", (int(user_id),))
    return cur.fetchone() is not None


def _is_player_banned(player_id: int, *, conn) -> bool:
    from game.auth import _get_active_ban

    return _get_active_ban(int(player_id)) is not None


def _player_registered_at(player_id: int, *, conn) -> Optional[int]:
    cur = conn.cursor()
    cur.execute("SELECT registered_at FROM users WHERE id = ? LIMIT 1;", (int(player_id),))
    row = cur.fetchone()
    if not row:
        return None
    raw = row["registered_at"] if isinstance(row, dict) else row[0]
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _player_registration_ip(player_id: int, *, conn) -> Optional[str]:
    cur = conn.cursor()
    cur.execute("SELECT registration_ip FROM users WHERE id = ? LIMIT 1;", (int(player_id),))
    row = cur.fetchone()
    if not row:
        return None
    raw = row["registration_ip"] if isinstance(row, dict) else row[0]
    ip = str(raw or "").strip()
    return ip or None


def _player_max_planet_level(player_id: int, *, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT MAX(COALESCE(planet_level, 1)) AS max_level
        FROM planets
        WHERE player_id = ?;
        """,
        (int(player_id),),
    )
    row = cur.fetchone()
    return max(1, _row_int(row, "max_level", 1))


def _account_age_sec(player_id: int, *, conn, now: int, fallback_created_at: Optional[int] = None) -> int:
    registered_at = _player_registered_at(player_id, conn=conn)
    if registered_at is None:
        registered_at = fallback_created_at
    if registered_at is None:
        return 0
    return max(0, int(now) - int(registered_at))


def _meets_success_criteria(
    referred_player_id: int,
    *,
    conn,
    now: int,
    referral_created_at: Optional[int] = None,
) -> bool:
    pid = int(referred_player_id)
    if _is_player_banned(pid, conn=conn):
        return False
    age = _account_age_sec(pid, conn=conn, now=now, fallback_created_at=referral_created_at)
    if age < REFERRAL_MIN_ACCOUNT_AGE_SEC:
        return False
    if _player_max_planet_level(pid, conn=conn) < REFERRAL_MIN_PLANET_LEVEL:
        return False
    return True


def _generate_unique_code(*, conn) -> str:
    cur = conn.cursor()
    for _ in range(64):
        code = "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH))
        cur.execute(
            "SELECT 1 FROM player_referral_codes WHERE code = ? LIMIT 1;",
            (code,),
        )
        if not cur.fetchone():
            return code
    raise RuntimeError("referral_code_generation_failed")


def ensure_referral_code(player_id: int, *, conn, now: Optional[int] = None) -> str:
    if not referrals_schema_ready(conn):
        raise RuntimeError("referrals_unavailable")
    pid = int(player_id)
    cur = conn.cursor()
    cur.execute(
        "SELECT code FROM player_referral_codes WHERE player_id = ? LIMIT 1;",
        (pid,),
    )
    row = cur.fetchone()
    if row:
        return str(row["code"])
    ts = int(now if now is not None else time.time())
    code = _generate_unique_code(conn=conn)
    cur.execute(
        """
        INSERT INTO player_referral_codes (player_id, code, created_at)
        VALUES (?, ?, ?);
        """,
        (pid, code, ts),
    )
    return code


def _resolve_referrer_by_code(code: str, *, conn) -> Optional[int]:
    normalized = str(code or "").strip().upper()
    if not normalized:
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT player_id FROM player_referral_codes
        WHERE UPPER(code) = ?
        LIMIT 1;
        """,
        (normalized,),
    )
    row = cur.fetchone()
    if row:
        return int(row["player_id"])
    try:
        from .shop_promos import resolve_referrer_player_id, schema_ready as promo_schema_ready

        if promo_schema_ready(conn):
            return resolve_referrer_player_id(normalized, conn=conn)
    except Exception:
        pass
    return None


def _get_referral_link_row(referred_player_id: int, *, conn) -> Optional[Any]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, referred_player_id, referrer_player_id, referral_code,
               apply_ip, same_ip_flag, status, qualified_at, created_at
        FROM player_referrals
        WHERE referred_player_id = ?
        LIMIT 1;
        """,
        (int(referred_player_id),),
    )
    return cur.fetchone()


def _claimed_reward_keys(player_id: int, reward_scope: str, *, conn) -> frozenset[str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT reward_key FROM referral_reward_claims
        WHERE player_id = ? AND reward_scope = ?;
        """,
        (int(player_id), str(reward_scope)),
    )
    return frozenset(str(r["reward_key"]) for r in cur.fetchall())


def count_successful_referrals(referrer_player_id: int, *, conn) -> int:
    if not referrals_schema_ready(conn):
        return 0
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM player_referrals
        WHERE referrer_player_id = ?
          AND status = 'qualified'
          AND same_ip_flag = 0;
        """,
        (int(referrer_player_id),),
    )
    return int(cur.fetchone()["c"] or 0)


def refresh_referral_qualifications(
    *,
    conn,
    player_id: Optional[int] = None,
    now: Optional[int] = None,
) -> None:
    """Promote pending referrals to qualified when milestone criteria are met."""
    if not referrals_schema_ready(conn):
        return
    ts = int(now if now is not None else time.time())
    cur = conn.cursor()
    if player_id is not None:
        cur.execute(
            """
            SELECT id, referred_player_id, created_at
            FROM player_referrals
            WHERE status = 'pending'
              AND (referrer_player_id = ? OR referred_player_id = ?);
            """,
            (int(player_id), int(player_id)),
        )
    else:
        cur.execute(
            """
            SELECT id, referred_player_id, created_at
            FROM player_referrals
            WHERE status = 'pending';
            """
        )
    rows = cur.fetchall()
    for row in rows:
        referred_id = int(row["referred_player_id"])
        if not _meets_success_criteria(
            referred_id,
            conn=conn,
            now=ts,
            referral_created_at=int(row["created_at"]),
        ):
            continue
        cur.execute(
            """
            UPDATE player_referrals
            SET status = 'qualified', qualified_at = ?
            WHERE id = ? AND status = 'pending';
            """,
            (ts, int(row["id"])),
        )


def apply_referral_code(
    referred_player_id: int,
    code: str,
    apply_ip: Optional[str],
    *,
    conn,
    now: Optional[int] = None,
) -> Tuple[bool, str]:
    if not referrals_schema_ready(conn):
        return False, "referrals_unavailable"
    pid = int(referred_player_id)
    if pid <= 0 or not _user_exists(pid, conn=conn):
        return False, "invalid_user"

    normalized_code = str(code or "").strip().upper()
    if not normalized_code:
        return False, "missing_referral_code"

    if _get_referral_link_row(pid, conn=conn):
        return False, "referral_already_linked"

    referrer_id = _resolve_referrer_by_code(normalized_code, conn=conn)
    if referrer_id is None:
        return False, "referral_code_not_found"
    if int(referrer_id) == pid:
        return False, "referral_self_not_allowed"

    referrer_ip = _player_registration_ip(int(referrer_id), conn=conn)
    apply_ip_val = str(apply_ip or "").strip()[:64] or None
    same_ip_flag = int(
        bool(referrer_ip and apply_ip_val and referrer_ip == apply_ip_val)
    )

    ts = int(now if now is not None else time.time())
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO player_referrals (
            referred_player_id, referrer_player_id, referral_code,
            apply_ip, same_ip_flag, status, created_at
        ) VALUES (?, ?, ?, ?, ?, 'pending', ?);
        """,
        (pid, int(referrer_id), normalized_code, apply_ip_val, same_ip_flag, ts),
    )
    try:
        from .shop_promos import record_register_attribution, schema_ready as promo_schema_ready

        if promo_schema_ready(conn):
            record_register_attribution(
                normalized_code, pid, conn=conn, now=float(ts)
            )
    except Exception:
        pass
    return True, "referral_linked"


def _tier_entry_state(
    tier: Mapping[str, Any],
    *,
    successful_count: int,
    claimed_keys: frozenset[str],
) -> Dict[str, Any]:
    required = int(tier["required_count"])
    reward_key = str(tier["reward_key"])
    box_key = str(tier["box_key"])
    amount = int(tier.get("amount") or 1)
    unlocked = successful_count >= required
    claimed = reward_key in claimed_keys
    claimable = unlocked and not claimed
    return {
        "reward_key": reward_key,
        "required_count": required,
        "successful_count": successful_count,
        "progress_label": f"{min(successful_count, required)} / {required}",
        "unlocked": unlocked,
        "claimed": claimed,
        "claimable": claimable,
        "label_key": str(tier.get("label_key") or ""),
        "desc_key": str(tier.get("desc_key") or ""),
        "box_key": box_key,
        "amount": amount,
        "display": _box_display(box_key, amount),
    }


def _referred_reward_state(
    *,
    has_referrer: bool,
    claimed_keys: frozenset[str],
) -> Optional[Dict[str, Any]]:
    if not has_referrer:
        return None
    reward_key = str(REFERRED_LINK_REWARD["reward_key"])
    box_key = str(REFERRED_LINK_REWARD["box_key"])
    amount = int(REFERRED_LINK_REWARD["amount"])
    claimed = reward_key in claimed_keys
    return {
        "reward_key": reward_key,
        "reward_scope": str(REFERRED_LINK_REWARD["reward_scope"]),
        "unlocked": True,
        "claimed": claimed,
        "claimable": not claimed,
        "label_key": str(REFERRED_LINK_REWARD["label_key"]),
        "desc_key": str(REFERRED_LINK_REWARD["desc_key"]),
        "box_key": box_key,
        "amount": amount,
        "display": _box_display(box_key, amount),
    }


def get_referral_state(
    player_id: int,
    *,
    conn,
    referral_link_base: Optional[str] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    uid = int(player_id)
    ts = int(now if now is not None else time.time())
    out: Dict[str, Any] = {
        "ready": referrals_schema_ready(conn),
        "code": "",
        "referral_url": "",
        "successful_count": 0,
        "pending_count": 0,
        "referrer_tiers": [],
        "referred_reward": None,
        "has_referrer": False,
        "referrer_code": None,
        "same_ip_flag": False,
        "can_apply_code": False,
        "claimable_count": 0,
        "criteria": {
            "min_account_age_hours": REFERRAL_MIN_ACCOUNT_AGE_SEC // 3600,
            "min_planet_level": REFERRAL_MIN_PLANET_LEVEL,
        },
    }
    if not out["ready"]:
        return out

    refresh_referral_qualifications(conn=conn, player_id=uid, now=ts)

    code = ensure_referral_code(uid, conn=conn, now=ts)
    out["code"] = code
    if referral_link_base:
        sep = "&" if "?" in referral_link_base else "?"
        out["referral_url"] = f"{referral_link_base}{sep}ref={code}"

    successful = count_successful_referrals(uid, conn=conn)
    out["successful_count"] = successful

    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM player_referrals
        WHERE referrer_player_id = ? AND status = 'pending';
        """,
        (uid,),
    )
    out["pending_count"] = int(cur.fetchone()["c"] or 0)

    claimed_referrer = _claimed_reward_keys(uid, "referrer", conn=conn)
    tiers = [
        _tier_entry_state(t, successful_count=successful, claimed_keys=claimed_referrer)
        for t in REFERRER_TIER_REWARDS
    ]
    out["referrer_tiers"] = tiers

    link_row = _get_referral_link_row(uid, conn=conn)
    has_referrer = link_row is not None
    out["has_referrer"] = has_referrer
    out["can_apply_code"] = not has_referrer
    if link_row:
        out["referrer_code"] = _row_str(link_row, "referral_code")
        out["same_ip_flag"] = bool(_row_int(link_row, "same_ip_flag"))

    claimed_referred = _claimed_reward_keys(uid, "referred", conn=conn)
    out["referred_reward"] = _referred_reward_state(
        has_referrer=has_referrer,
        claimed_keys=claimed_referred,
    )

    claimable = sum(1 for t in tiers if t["claimable"])
    if out["referred_reward"] and out["referred_reward"]["claimable"]:
        claimable += 1
    out["claimable_count"] = claimable
    return out


def count_claimable_referral_rewards(
    player_id: int,
    *,
    conn,
    now: Optional[int] = None,
    read_only: bool = False,
) -> int:
    """Nav-badge helper: set read_only=True to avoid writes during game-state polls."""
    if read_only:
        return _count_claimable_referral_rewards_readonly(int(player_id), conn=conn)
    state = get_referral_state(int(player_id), conn=conn, now=now)
    return int(state.get("claimable_count") or 0)


def _count_claimable_referral_rewards_readonly(player_id: int, *, conn) -> int:
    if not referrals_schema_ready(conn):
        return 0
    uid = int(player_id)
    successful = count_successful_referrals(uid, conn=conn)
    claimed_referrer = _claimed_reward_keys(uid, "referrer", conn=conn)
    claimable = sum(
        1
        for tier in REFERRER_TIER_REWARDS
        if successful >= int(tier["required_count"])
        and str(tier["reward_key"]) not in claimed_referrer
    )
    if _get_referral_link_row(uid, conn=conn):
        claimed_referred = _claimed_reward_keys(uid, "referred", conn=conn)
        if str(REFERRED_LINK_REWARD["reward_key"]) not in claimed_referred:
            claimable += 1
    return claimable


def _grant_referral_box(
    user_id: int,
    box_key: str,
    amount: int,
    *,
    conn,
    now: float,
    source: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    key = str(box_key or "").strip()
    qty = max(1, int(amount or 1))
    if not is_allowed_referral_box(key):
        return False, "reward_not_allowed", {"box_key": key}
    if not inventory_schema_ready(conn):
        return False, "inventory_unavailable", {"box_key": key}
    inv_key = resolve_inventory_key(key) or key
    if not grant_inventory_item(
        int(user_id),
        inv_key,
        qty,
        conn=conn,
        metadata={"source": source, "box_key": key},
    ):
        return False, "grant_failed", {"box_key": key}
    if table_exists(conn, "lootbox_inventory"):
        cur = conn.cursor()
        for _ in range(qty):
            cur.execute(
                """
                INSERT INTO lootbox_inventory (player_id, box_key, source, created_at)
                VALUES (?, ?, ?, ?);
                """,
                (int(user_id), key, source, int(now)),
            )
    return True, "ok", {"box_key": key, "amount": qty, "inventory_key": inv_key}


def claim_referral_reward(
    player_id: int,
    reward_scope: str,
    reward_key: str,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not referrals_schema_ready(conn):
        return False, "referrals_unavailable", None

    uid = int(player_id)
    scope = str(reward_scope or "").strip().lower()
    rkey = str(reward_key or "").strip()
    if scope not in ("referrer", "referred") or not rkey:
        return False, "invalid_reward", None

    ts = float(now if now is not None else time.time())
    refresh_referral_qualifications(conn=conn, player_id=uid, now=int(ts))

    if _claimed_reward_keys(uid, scope, conn=conn).__contains__(rkey):
        return False, "reward_already_claimed", None

    box_key: Optional[str] = None
    amount = 1

    if scope == "referred":
        if rkey != REFERRED_LINK_REWARD["reward_key"]:
            return False, "invalid_reward", None
        if not _get_referral_link_row(uid, conn=conn):
            return False, "referral_not_linked", None
        box_key = str(REFERRED_LINK_REWARD["box_key"])
        amount = int(REFERRED_LINK_REWARD["amount"])
    else:
        tier = next((t for t in REFERRER_TIER_REWARDS if str(t["reward_key"]) == rkey), None)
        if not tier:
            return False, "invalid_reward", None
        successful = count_successful_referrals(uid, conn=conn)
        if successful < int(tier["required_count"]):
            return False, "reward_not_unlocked", None
        box_key = str(tier["box_key"])
        amount = int(tier.get("amount") or 1)

    assert box_key is not None
    ok, grant_reason, grant_result = _grant_referral_box(
        uid,
        box_key,
        amount,
        conn=conn,
        now=ts,
        source="referral_reward",
    )
    if not ok:
        return False, grant_reason, grant_result

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO referral_reward_claims (
            player_id, reward_scope, reward_key, box_key, amount, claimed_at
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (uid, scope, rkey, box_key, amount, int(ts)),
    )
    return True, "referral_reward_claimed", {
        "reward_scope": scope,
        "reward_key": rkey,
        **grant_result,
    }


def set_user_registration_meta(
    user_id: int,
    *,
    registration_ip: Optional[str],
    conn,
    now: Optional[int] = None,
) -> None:
    """Persist registration timestamp/IP when schema columns exist."""
    cols = set()
    if column_exists(conn, "users", "registered_at"):
        cols.add("registered_at")
    if column_exists(conn, "users", "registration_ip"):
        cols.add("registration_ip")
    if not cols:
        return
    cur = conn.cursor()
    ts = int(now if now is not None else time.time())
    ip_val = str(registration_ip or "").strip()[:64] or None
    sets: List[str] = []
    params: List[Any] = []
    if "registered_at" in cols:
        sets.append("registered_at = COALESCE(registered_at, ?)")
        params.append(ts)
    if "registration_ip" in cols and ip_val:
        sets.append("registration_ip = COALESCE(registration_ip, ?)")
        params.append(ip_val)
    if not sets:
        return
    params.append(int(user_id))
    cur.execute(
        f"UPDATE users SET {', '.join(sets)} WHERE id = ?;",
        tuple(params),
    )
