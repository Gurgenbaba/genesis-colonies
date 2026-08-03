"""
GC-CB — Case Battles / Relikt-Arena.

Owner for lobby lifecycle, container escrow, seeded rolls, and settlement.
Reuses inventory_loot + inventory grant/consume — no parallel loot engine.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import string
import time
from collections import Counter
from copy import deepcopy
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from game.db import table_exists
from game.inventory import (
    build_roll_preview,
    consume_inventory_item,
    grant_inventory_item,
    inventory_amount,
    roll_single_loot_reward,
)
from game.inventory_catalog import CONTAINER_KEYS, ITEM_CATALOG, item_catalog_entry
from game.inventory_loot import LOOT_POOLS, sanitize_loot_pool

# --- Constants -----------------------------------------------------------------

MODES = frozenset({"standard", "crazy", "terminal", "share", "team"})
VISIBILITIES = frozenset({"public", "private"})
STATUSES = frozenset({"open", "running", "finished", "cancelled"})

PLAYER_LIMITS = frozenset({2, 3, 4})
PLAYER_LIMIT_DEFAULT = 2
PLAYER_LIMIT_TEAM = 4
CASES_MIN = 1
CASES_MAX = 10
AUTO_SETTLE_AFTER_SEC = 180.0
JOIN_CODE_LEN = 6
HISTORY_LIMIT = 20
LOBBY_LIMIT = 40

MODE_META: Dict[str, Dict[str, Any]] = {
    "standard": {"min_players": 2, "max_players": 4, "team": False},
    "crazy": {"min_players": 2, "max_players": 4, "team": False},
    "terminal": {"min_players": 2, "max_players": 4, "team": False},
    "share": {"min_players": 2, "max_players": 4, "team": False},
    "team": {"min_players": 4, "max_players": 4, "team": True},
}

CONTAINER_BATTLE_VALUE: Dict[str, int] = {
    "container_basic": 100,
    "container_rare": 250,
    "container_research_cache": 400,
    "container_military_cache": 500,
    "container_wreckage": 600,
    "container_epic": 900,
    "container_event_special": 1200,
    "container_relic": 2000,
    "container_ancient_relic": 3500,
    "container_mythic": 5000,
    "container_void_artifact": 8000,
}

_RARITY_REWARD_VALUE: Dict[str, int] = {
    "common": 40,
    "uncommon": 90,
    "rare": 180,
    "epic": 450,
    "legendary": 1200,
    "mythic": 2500,
}

# Explicit unit RV overrides (amount multiplies these).
ITEM_REWARD_VALUE: Dict[str, int] = {
    "fragment_dna_common": 35,
    "fragment_dna_rare": 120,
    "fragment_dna_epic": 350,
    "fragment_artifact_alpha": 160,
    "artifact_core_fragment": 900,
    "fragment_alien": 150,
    "fragment_quantum": 400,
    "fragment_genesis": 1500,
    "fragment_wreck_reactor": 80,
    "fragment_wreck_hull": 80,
    "story_scrap_token": 60,
    "dna_core_common": 200,
    "dna_core_rare": 500,
    "dna_core_epic": 1200,
    "evo_planet_xp_250": 70,
    "evo_planet_xp_500": 120,
    "evo_planet_xp_5000": 400,
    "evo_planet_xp_50000": 1400,
    "research_data_energy": 110,
    "research_data_mining": 110,
    "research_data_weapons": 110,
    "research_instant_level": 2000,
    "booster_build_5m": 50,
    "booster_build_15m": 100,
    "booster_build_1h": 220,
    "booster_build_6h": 700,
    "booster_build_24h": 1600,
    "booster_research_5m": 50,
    "booster_research_15m": 100,
    "booster_research_30m": 150,
    "booster_research_1h": 220,
    "booster_research_6h": 700,
    "booster_research_24h": 1600,
    "booster_shipyard_15m": 100,
    "booster_shipyard_1h": 220,
    "booster_production_25": 180,
    "booster_production_50": 320,
    "booster_production_100": 600,
    "booster_energy_50": 280,
    "booster_energy_surge_24h": 500,
    "booster_container_luck_24h": 550,
    "booster_fleet_speed_25_24h": 700,
    "booster_expedition_loot_25_24h": 450,
    "booster_research_pct_2_24h": 280,
    "fleet_nav_chip": 300,
    "fleet_hyperdrive_module": 800,
    "fleet_fuel_optimizer": 350,
    "fleet_computer": 200,
    "utility_repair_drone": 150,
    "mythic_ancient_nexus": 3000,
    "mythic_genesis_core": 4000,
    "expo_alien_relic": 600,
    "expo_star_chart": 250,
}


# --- Schema / helpers ----------------------------------------------------------

def case_battles_schema_ready(conn) -> bool:
    return bool(
        table_exists(conn, "case_battles")
        and table_exists(conn, "case_battle_players")
        and table_exists(conn, "case_battle_rolls")
        and table_exists(conn, "case_battle_settlements")
    )


def battle_value_for_container(container_key: str) -> int:
    key = str(container_key or "").strip()
    if key in CONTAINER_BATTLE_VALUE:
        return int(CONTAINER_BATTLE_VALUE[key])
    return 0


def total_battle_value(cases: Sequence[str]) -> int:
    return sum(battle_value_for_container(k) for k in cases)


def reward_value_for_item(item_key: str, amount: int = 1) -> int:
    """Server-only Reward Value for one grantable meta item (per unit × amount)."""
    key = str(item_key or "").strip()
    amt = max(0, int(amount))
    if amt <= 0 or not key:
        return 0
    if key in CONTAINER_BATTLE_VALUE:
        unit = int(CONTAINER_BATTLE_VALUE[key])
    elif key in ITEM_REWARD_VALUE:
        unit = int(ITEM_REWARD_VALUE[key])
    else:
        spec = ITEM_CATALOG.get(key) or {}
        rarity = str(spec.get("rarity") or "common")
        unit = int(_RARITY_REWARD_VALUE.get(rarity, 40))
    return unit * amt


def _now() -> float:
    return float(time.time())


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _json_loads(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def _normalize_cases(raw: Any) -> Tuple[Optional[List[str]], str]:
    if not isinstance(raw, (list, tuple)):
        return None, "invalid_cases"
    cases = [str(x or "").strip() for x in raw]
    if not (CASES_MIN <= len(cases) <= CASES_MAX):
        return None, "invalid_case_count"
    for key in cases:
        if key not in CONTAINER_KEYS:
            return None, "unknown_container"
        if battle_value_for_container(key) <= 0:
            return None, "container_no_battle_value"
    return cases, ""


def _gen_join_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(JOIN_CODE_LEN))


def _gen_server_seed() -> str:
    return secrets.token_hex(32)


def _hash_seed(server_seed: str) -> str:
    return hashlib.sha256(str(server_seed).encode("utf-8")).hexdigest()


def _roll_rng(server_seed: str, battle_id: int, round_index: int, slot: int, nonce: str) -> Any:
    import random

    msg = f"{int(battle_id)}|{int(round_index)}|{int(slot)}|{nonce}".encode("utf-8")
    digest = hmac.new(str(server_seed).encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return random.Random(int(digest[:16], 16))


def _case_counts(cases: Sequence[str]) -> Dict[str, int]:
    return dict(Counter(str(k) for k in cases))


def _player_name(conn, user_id: int) -> str:
    row = conn.execute(
        "SELECT name FROM players WHERE id = ? LIMIT 1;",
        (int(user_id),),
    ).fetchone()
    if not row:
        return f"Commander #{int(user_id)}"
    return str(row["name"] or f"Commander #{int(user_id)}")


def _snapshot_pools_for_cases(cases: Sequence[str], *, conn) -> Dict[str, List[Dict[str, Any]]]:
    """Freeze loot pools at battle start (defaults only — ignore live admin overrides)."""
    needed = set(cases)
    snap: Dict[str, List[Dict[str, Any]]] = {}
    for key in needed:
        pool = LOOT_POOLS.get(key) or []
        snap[key] = deepcopy(sanitize_loot_pool(pool))
    return snap


def _consume_cases(user_id: int, cases: Sequence[str], *, conn) -> Tuple[bool, str]:
    counts = _case_counts(cases)
    for key, need in counts.items():
        owned = inventory_amount(int(user_id), key, conn=conn)
        if owned < need:
            return False, "insufficient_containers"
    for key, need in counts.items():
        if not consume_inventory_item(int(user_id), key, int(need), conn=conn):
            return False, "insufficient_containers"
    return True, ""


def _refund_cases(user_id: int, cases: Sequence[str], *, conn) -> None:
    for key, need in _case_counts(cases).items():
        grant_inventory_item(int(user_id), key, int(need), conn=conn)


def _reward_display(reward: Mapping[str, Any]) -> Dict[str, Any]:
    rtype = str(reward.get("reward_type") or "item")
    rkey = str(reward.get("reward_key") or "")
    amt = int(reward.get("amount") or 0)
    meta = item_catalog_entry(rkey) if rkey else {}
    return {
        "reward_type": rtype,
        "reward_key": rkey,
        "amount": amt,
        "reward_value": reward_value_for_item(rkey, amt),
        "name_key": str(meta.get("name_key") or rkey),
        "rarity": str(meta.get("rarity") or "common"),
        "icon": str(meta.get("icon") or "📦"),
        "image": str(meta.get("image") or "") or None,
    }


# --- Repository ----------------------------------------------------------------

def _fetch_battle(conn, battle_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM case_battles WHERE id = ? LIMIT 1;",
        (int(battle_id),),
    ).fetchone()
    return dict(row) if row else None


def _fetch_players(conn, battle_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM case_battle_players
        WHERE battle_id = ?
        ORDER BY slot ASC;
        """,
        (int(battle_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_rolls(conn, battle_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM case_battle_rolls
        WHERE battle_id = ?
        ORDER BY round_index ASC, user_id ASC;
        """,
        (int(battle_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_settlement(conn, battle_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM case_battle_settlements WHERE battle_id = ? LIMIT 1;",
        (int(battle_id),),
    ).fetchone()
    return dict(row) if row else None


# --- Serialization -------------------------------------------------------------

def _serialize_battle(
    battle: Mapping[str, Any],
    players: Sequence[Mapping[str, Any]],
    rolls: Sequence[Mapping[str, Any]],
    settlement: Optional[Mapping[str, Any]],
    *,
    conn,
    viewer_id: Optional[int] = None,
) -> Dict[str, Any]:
    cases = _json_loads(battle.get("cases_json"), []) or []
    status = str(battle.get("status") or "open")
    seed = battle.get("server_seed")
    reveal_seed = status == "finished" and bool(seed)
    player_payload = []
    totals: Dict[str, int] = {}
    if settlement:
        raw_totals = _json_loads(settlement.get("totals_json"), {}) or {}
        for k, v in raw_totals.items():
            if str(k).startswith("_"):
                continue
            try:
                totals[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    else:
        for r in rolls:
            uid = str(int(r["user_id"]))
            totals[uid] = totals.get(uid, 0) + int(r.get("reward_value") or 0)

    for p in players:
        uid = int(p["user_id"])
        player_payload.append(
            {
                "user_id": uid,
                "slot": int(p["slot"]),
                "name": _player_name(conn, uid),
                "joined_at": float(p["joined_at"]),
                "total_reward_value": int(totals.get(str(uid), 0)),
                "is_self": viewer_id is not None and int(viewer_id) == uid,
            }
        )

    roll_payload = []
    for r in rolls:
        snap = _json_loads(r.get("reward_snapshot_json"), {}) or {}
        preview = _json_loads(r.get("roll_preview_json"), None)
        roll_payload.append(
            {
                "round_index": int(r["round_index"]),
                "user_id": int(r["user_id"]),
                "container_key": str(r["container_key"]),
                "container_battle_value": battle_value_for_container(str(r["container_key"])),
                "roll_nonce": str(r["roll_nonce"]),
                "reward": snap if snap else _reward_display(
                    {
                        "reward_type": r.get("reward_type"),
                        "reward_key": r.get("reward_key"),
                        "amount": r.get("reward_amount"),
                    }
                ),
                "reward_value": int(r.get("reward_value") or 0),
                "roll_preview": preview,
                "winning_index": int(r["winning_index"]) if r.get("winning_index") is not None else None,
            }
        )

    join_code = battle.get("join_code")
    show_code = (
        str(battle.get("visibility") or "") == "private"
        and viewer_id is not None
        and int(viewer_id) == int(battle["creator_id"])
    )

    out: Dict[str, Any] = {
        "id": int(battle["id"]),
        "creator_id": int(battle["creator_id"]),
        "mode": str(battle["mode"]),
        "status": status,
        "visibility": str(battle.get("visibility") or "public"),
        "player_limit": int(battle.get("player_limit") or PLAYER_LIMIT_DEFAULT),
        "player_count": len(players),
        "total_battle_value": int(battle.get("total_battle_value") or 0),
        "cases": list(cases),
        "case_previews": [
            {
                "item_key": k,
                "battle_value": battle_value_for_container(k),
                "name_key": (ITEM_CATALOG.get(k) or {}).get("name_key") or k,
                "rarity": (ITEM_CATALOG.get(k) or {}).get("rarity") or "common",
                "image": (ITEM_CATALOG.get(k) or {}).get("image"),
                "icon": (ITEM_CATALOG.get(k) or {}).get("icon") or "📦",
            }
            for k in cases
        ],
        "server_seed_hash": battle.get("server_seed_hash"),
        "server_seed": str(seed) if reveal_seed else None,
        "created_at": float(battle.get("created_at") or 0),
        "started_at": float(battle["started_at"]) if battle.get("started_at") is not None else None,
        "finished_at": float(battle["finished_at"]) if battle.get("finished_at") is not None else None,
        "players": player_payload,
        "rolls": roll_payload,
        "winner_id": int(settlement["winner_id"]) if settlement else None,
        "winner_ids": (
            [int(x) for x in (_json_loads(settlement.get("totals_json"), {}) or {}).get("_winner_ids", [])]
            if settlement
            else None
        ),
        "settlement_kind": (
            (_json_loads(settlement.get("totals_json"), {}) or {}).get("_kind")
            if settlement
            else None
        ),
        "settled": settlement is not None,
        "granted": _json_loads(settlement.get("granted_json"), []) if settlement else None,
        "join_code": str(join_code) if show_code and join_code else None,
        "can_join": (
            status == "open"
            and len(players) < int(battle.get("player_limit") or PLAYER_LIMIT_DEFAULT)
            and viewer_id is not None
            and all(int(p["user_id"]) != int(viewer_id) for p in players)
        ),
        "can_cancel": (
            status == "open"
            and viewer_id is not None
            and int(viewer_id) == int(battle["creator_id"])
        ),
        "can_settle": status == "running" and settlement is None,
        "is_participant": viewer_id is not None
        and any(int(p["user_id"]) == int(viewer_id) for p in players),
        "mode_meta": MODE_META.get(str(battle.get("mode") or "standard"), MODE_META["standard"]),
    }
    # Attach team labels for UI
    if str(battle.get("mode") or "") == "team":
        for p in out["players"]:
            p["team"] = "A" if int(p["slot"]) < 2 else "B"
    return out


def get_battle_payload(
    battle_id: int,
    *,
    conn,
    viewer_id: Optional[int] = None,
    auto_settle: bool = False,
) -> Optional[Dict[str, Any]]:
    if not case_battles_schema_ready(conn):
        return None
    if auto_settle:
        maybe_auto_settle(int(battle_id), conn=conn)
    battle = _fetch_battle(conn, int(battle_id))
    if not battle:
        return None
    return _serialize_battle(
        battle,
        _fetch_players(conn, int(battle_id)),
        _fetch_rolls(conn, int(battle_id)),
        _fetch_settlement(conn, int(battle_id)),
        conn=conn,
        viewer_id=viewer_id,
    )


# --- Lifecycle -----------------------------------------------------------------

def create_battle(
    user_id: int,
    *,
    cases: Sequence[Any],
    mode: str = "standard",
    visibility: str = "public",
    player_limit: int = PLAYER_LIMIT_DEFAULT,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not case_battles_schema_ready(conn):
        return False, "case_battles_unavailable", None

    mode_key = str(mode or "standard").strip().lower()
    vis = str(visibility or "public").strip().lower()
    if mode_key not in MODES:
        return False, "invalid_mode", None
    if vis not in VISIBILITIES:
        return False, "invalid_visibility", None

    try:
        limit = int(player_limit)
    except (TypeError, ValueError):
        limit = PLAYER_LIMIT_DEFAULT
    meta = MODE_META[mode_key]
    if mode_key == "team":
        limit = PLAYER_LIMIT_TEAM
    if limit not in PLAYER_LIMITS:
        return False, "invalid_player_limit", None
    if limit < int(meta["min_players"]) or limit > int(meta["max_players"]):
        return False, "invalid_player_limit", None

    case_list, err = _normalize_cases(cases)
    if err or not case_list:
        return False, err or "invalid_cases", None

    ok, reason = _consume_cases(int(user_id), case_list, conn=conn)
    if not ok:
        return False, reason, None

    now = _now()
    join_code = _gen_join_code() if vis == "private" else None
    bv = total_battle_value(case_list)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO case_battles (
            creator_id, mode, status, visibility, join_code, player_limit,
            total_battle_value, cases_json, created_at
        ) VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?);
        """,
        (
            int(user_id),
            mode_key,
            vis,
            join_code,
            int(limit),
            int(bv),
            _json_dumps(case_list),
            now,
        ),
    )
    battle_id = int(cur.lastrowid)
    cur.execute(
        """
        INSERT INTO case_battle_players (battle_id, user_id, slot, joined_at)
        VALUES (?, ?, 0, ?);
        """,
        (battle_id, int(user_id), now),
    )
    payload = get_battle_payload(battle_id, conn=conn, viewer_id=int(user_id))
    return True, "case_battle_created", payload


def join_battle(
    user_id: int,
    battle_id: int,
    *,
    join_code: Optional[str] = None,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not case_battles_schema_ready(conn):
        return False, "case_battles_unavailable", None

    battle = _fetch_battle(conn, int(battle_id))
    if not battle:
        return False, "battle_not_found", None
    if str(battle["status"]) != "open":
        return False, "battle_not_open", None

    players = _fetch_players(conn, int(battle_id))
    if any(int(p["user_id"]) == int(user_id) for p in players):
        return False, "already_joined", None
    limit = int(battle.get("player_limit") or PLAYER_LIMIT_DEFAULT)
    if len(players) >= limit:
        return False, "battle_full", None

    if str(battle.get("visibility") or "") == "private":
        code = str(join_code or "").strip().upper()
        expected = str(battle.get("join_code") or "").strip().upper()
        if not code or code != expected:
            return False, "invalid_join_code", None

    cases = _json_loads(battle.get("cases_json"), []) or []
    ok, reason = _consume_cases(int(user_id), cases, conn=conn)
    if not ok:
        return False, reason, None

    slot = max((int(p["slot"]) for p in players), default=-1) + 1
    now = _now()
    conn.execute(
        """
        INSERT INTO case_battle_players (battle_id, user_id, slot, joined_at)
        VALUES (?, ?, ?, ?);
        """,
        (int(battle_id), int(user_id), int(slot), now),
    )

    players = _fetch_players(conn, int(battle_id))
    if len(players) >= limit:
        start_ok, start_reason = _start_battle(int(battle_id), conn=conn)
        if not start_ok:
            return False, start_reason, None

    payload = get_battle_payload(int(battle_id), conn=conn, viewer_id=int(user_id))
    return True, "case_battle_joined", payload


def join_battle_by_code(
    user_id: int,
    join_code: str,
    *,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    code = str(join_code or "").strip().upper()
    if not code:
        return False, "invalid_join_code", None
    row = conn.execute(
        """
        SELECT id FROM case_battles
        WHERE status = 'open' AND visibility = 'private' AND UPPER(join_code) = ?
        ORDER BY created_at DESC
        LIMIT 1;
        """,
        (code,),
    ).fetchone()
    if not row:
        return False, "battle_not_found", None
    return join_battle(int(user_id), int(row["id"]), join_code=code, conn=conn)


def cancel_battle(user_id: int, battle_id: int, *, conn) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not case_battles_schema_ready(conn):
        return False, "case_battles_unavailable", None

    battle = _fetch_battle(conn, int(battle_id))
    if not battle:
        return False, "battle_not_found", None
    if int(battle["creator_id"]) != int(user_id):
        return False, "not_creator", None
    if str(battle["status"]) != "open":
        return False, "battle_not_open", None

    cases = _json_loads(battle.get("cases_json"), []) or []
    players = _fetch_players(conn, int(battle_id))
    for p in players:
        _refund_cases(int(p["user_id"]), cases, conn=conn)

    now = _now()
    conn.execute(
        """
        UPDATE case_battles
        SET status = 'cancelled', finished_at = ?
        WHERE id = ? AND status = 'open';
        """,
        (now, int(battle_id)),
    )
    payload = get_battle_payload(int(battle_id), conn=conn, viewer_id=int(user_id))
    return True, "case_battle_cancelled", payload


def _start_battle(battle_id: int, *, conn) -> Tuple[bool, str]:
    battle = _fetch_battle(conn, int(battle_id))
    if not battle or str(battle["status"]) != "open":
        return False, "battle_not_open"

    players = _fetch_players(conn, int(battle_id))
    limit = int(battle.get("player_limit") or PLAYER_LIMIT_DEFAULT)
    if len(players) < limit:
        return False, "battle_not_full"

    cases = _json_loads(battle.get("cases_json"), []) or []
    if not cases:
        return False, "invalid_cases"

    server_seed = _gen_server_seed()
    seed_hash = _hash_seed(server_seed)
    pool_snap = _snapshot_pools_for_cases(cases, conn=conn)
    now = _now()

    conn.execute(
        """
        UPDATE case_battles
        SET status = 'running',
            server_seed = ?,
            server_seed_hash = ?,
            pool_snapshot_json = ?,
            started_at = ?
        WHERE id = ? AND status = 'open';
        """,
        (server_seed, seed_hash, _json_dumps(pool_snap), now, int(battle_id)),
    )

    # Hide seed until settle: keep hash, clear seed column temporarily? Plan stores seed
    # encrypted-in-DB until reveal — we keep seed in DB for crash recovery but omit from API
    # until finished (serialize already gates on status==finished).

    for round_index, container_key in enumerate(cases):
        pool = pool_snap.get(container_key) or []
        for p in players:
            slot = int(p["slot"])
            uid = int(p["user_id"])
            nonce = secrets.token_hex(8)
            rng = _roll_rng(server_seed, int(battle_id), round_index, slot, nonce)
            reward = roll_single_loot_reward(pool, rng, loot_context=None)
            # Enrich display fields for snapshot
            display = _reward_display(reward)
            preview_rng = _roll_rng(server_seed, int(battle_id), round_index, slot, nonce + ":preview")
            enriched = {
                "reward_type": display["reward_type"],
                "reward_key": display["reward_key"],
                "amount": display["amount"],
                "name_key": display["name_key"],
                "rarity": display["rarity"],
                "icon": display["icon"],
            }
            roll_preview, winning_index, _winning = build_roll_preview(
                [enriched],
                pool,
                preview_rng,
                loot_context=None,
            )
            rv = int(display["reward_value"])
            conn.execute(
                """
                INSERT INTO case_battle_rolls (
                    battle_id, round_index, user_id, container_key, roll_nonce,
                    reward_type, reward_key, reward_amount, reward_snapshot_json,
                    reward_value, roll_preview_json, winning_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    int(battle_id),
                    int(round_index),
                    uid,
                    str(container_key),
                    nonce,
                    display["reward_type"],
                    display["reward_key"],
                    int(display["amount"]),
                    _json_dumps(display),
                    rv,
                    _json_dumps(roll_preview),
                    int(winning_index),
                ),
            )
    return True, "case_battle_started"


def _resolve_winner(mode: str, totals: Mapping[int, int], players: Sequence[Mapping[str, Any]]) -> int:
    """Winner takes all — standard = highest RV, crazy = lowest RV. Ties: lowest slot."""
    mode_key = str(mode or "standard").strip().lower()
    slot_by_uid = {int(p["user_id"]): int(p["slot"]) for p in players}

    def sort_key(uid: int) -> Tuple[int, int]:
        rv = int(totals.get(uid, 0))
        slot = slot_by_uid.get(uid, 999)
        if mode_key == "crazy":
            return (rv, slot)
        return (-rv, slot)

    uids = [int(p["user_id"]) for p in players]
    return sorted(uids, key=sort_key)[0]


def _slot_team(slot: int) -> str:
    return "A" if int(slot) < 2 else "B"


def _largest_remainder_split(total: int, weights: Mapping[int, float]) -> Dict[int, int]:
    """Split integer `total` across keys by weights (largest remainder)."""
    amt = max(0, int(total))
    if amt <= 0 or not weights:
        return {int(k): 0 for k in weights}
    wsum = sum(max(0.0, float(v)) for v in weights.values())
    if wsum <= 0:
        uids = list(weights.keys())
        out = {int(k): 0 for k in uids}
        out[int(uids[0])] = amt
        return out
    raw = {int(k): (amt * max(0.0, float(v)) / wsum) for k, v in weights.items()}
    floors = {k: int(v) for k, v in raw.items()}
    rem = amt - sum(floors.values())
    order = sorted(raw.keys(), key=lambda k: (raw[k] - floors[k], -k), reverse=True)
    for k in order:
        if rem <= 0:
            break
        floors[k] += 1
        rem -= 1
    return floors


def _compute_settlement_grants(
    mode: str,
    players: Sequence[Mapping[str, Any]],
    rolls: Sequence[Mapping[str, Any]],
) -> Tuple[int, List[int], List[Dict[str, Any]], Dict[str, Any]]:
    """Returns (display_winner_id, winner_ids, granted_rows, totals_meta)."""
    mode_key = str(mode or "standard").strip().lower()
    slot_by_uid = {int(p["user_id"]): int(p["slot"]) for p in players}
    uids = [int(p["user_id"]) for p in players]

    totals: Dict[int, int] = {uid: 0 for uid in uids}
    for r in rolls:
        uid = int(r["user_id"])
        totals[uid] = totals.get(uid, 0) + int(r.get("reward_value") or 0)

    grants: List[Dict[str, Any]] = []
    winner_ids: List[int] = []
    kind = mode_key
    team_totals = {"A": 0, "B": 0}
    win_team = "A"

    if mode_key in ("standard", "crazy"):
        winner = _resolve_winner(mode_key, totals, players)
        winner_ids = [winner]
        merged: Dict[str, int] = {}
        for r in rolls:
            key = str(r["reward_key"])
            merged[key] = merged.get(key, 0) + int(r["reward_amount"])
        for key, amt in merged.items():
            if amt > 0:
                grants.append(
                    {
                        "user_id": winner,
                        "reward_key": key,
                        "amount": int(amt),
                        "reward_value": reward_value_for_item(key, amt),
                    }
                )

    elif mode_key == "terminal":
        by_round: Dict[int, List[Mapping[str, Any]]] = {}
        for r in rolls:
            by_round.setdefault(int(r["round_index"]), []).append(r)
        round_winners: List[int] = []
        for ri, round_rolls in sorted(by_round.items()):
            round_totals = {uid: 0 for uid in uids}
            for r in round_rolls:
                round_totals[int(r["user_id"])] += int(r.get("reward_value") or 0)
            round_winner = sorted(
                uids,
                key=lambda uid: (-int(round_totals.get(uid, 0)), slot_by_uid.get(uid, 999)),
            )[0]
            round_winners.append(round_winner)
            merged_r: Dict[str, int] = {}
            for r in round_rolls:
                key = str(r["reward_key"])
                merged_r[key] = merged_r.get(key, 0) + int(r["reward_amount"])
            for key, amt in merged_r.items():
                if amt > 0:
                    grants.append(
                        {
                            "user_id": round_winner,
                            "reward_key": key,
                            "amount": int(amt),
                            "reward_value": reward_value_for_item(key, amt),
                            "round_index": int(ri),
                        }
                    )
        win_counts = Counter(round_winners)
        display = sorted(
            uids,
            key=lambda uid: (-win_counts.get(uid, 0), -totals.get(uid, 0), slot_by_uid.get(uid, 999)),
        )[0]
        winner_ids = [display] + [w for w in dict.fromkeys(round_winners) if w != display]

    elif mode_key == "share":
        total_rv = sum(totals.values()) or 1
        weights = {uid: float(totals.get(uid, 0)) / float(total_rv) for uid in uids}
        merged_s: Dict[str, int] = {}
        for r in rolls:
            key = str(r["reward_key"])
            merged_s[key] = merged_s.get(key, 0) + int(r["reward_amount"])
        for key, amt in merged_s.items():
            split = _largest_remainder_split(int(amt), weights)
            for uid, n in split.items():
                if n > 0:
                    grants.append(
                        {
                            "user_id": int(uid),
                            "reward_key": key,
                            "amount": int(n),
                            "reward_value": reward_value_for_item(key, n),
                        }
                    )
        winner_ids = [
            sorted(uids, key=lambda uid: (-totals.get(uid, 0), slot_by_uid.get(uid, 999)))[0]
        ]

    elif mode_key == "team":
        team_members = {"A": [], "B": []}
        for p in players:
            team = _slot_team(int(p["slot"]))
            uid = int(p["user_id"])
            team_members[team].append(uid)
            team_totals[team] += int(totals.get(uid, 0))
        win_team = "A" if team_totals["A"] >= team_totals["B"] else "B"
        lose_team = "B" if win_team == "A" else "A"
        winners = team_members[win_team]
        losers = team_members[lose_team]
        winner_ids = list(winners)
        for r in rolls:
            uid = int(r["user_id"])
            if uid in winners:
                amt = int(r["reward_amount"])
                if amt > 0:
                    grants.append(
                        {
                            "user_id": uid,
                            "reward_key": str(r["reward_key"]),
                            "amount": amt,
                            "reward_value": reward_value_for_item(str(r["reward_key"]), amt),
                        }
                    )
        opp_merged: Dict[str, int] = {}
        for r in rolls:
            if int(r["user_id"]) in losers:
                key = str(r["reward_key"])
                opp_merged[key] = opp_merged.get(key, 0) + int(r["reward_amount"])
        w_weights = {uid: 1.0 for uid in winners} or {uids[0]: 1.0}
        for key, amt in opp_merged.items():
            split = _largest_remainder_split(int(amt), w_weights)
            for uid, n in split.items():
                if n > 0:
                    grants.append(
                        {
                            "user_id": int(uid),
                            "reward_key": key,
                            "amount": int(n),
                            "reward_value": reward_value_for_item(key, n),
                        }
                    )
    else:
        winner = _resolve_winner("standard", totals, players)
        winner_ids = [winner]

    merged_grants: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for g in grants:
        mkey = (int(g["user_id"]), str(g["reward_key"]))
        if mkey not in merged_grants:
            merged_grants[mkey] = {
                "user_id": int(g["user_id"]),
                "reward_key": str(g["reward_key"]),
                "amount": 0,
                "reward_value": 0,
            }
        merged_grants[mkey]["amount"] += int(g["amount"])
        merged_grants[mkey]["reward_value"] = reward_value_for_item(
            str(g["reward_key"]), merged_grants[mkey]["amount"]
        )
    grant_rows = list(merged_grants.values())
    display_winner = int(winner_ids[0]) if winner_ids else int(uids[0])
    meta: Dict[str, Any] = {str(k): int(v) for k, v in totals.items()}
    meta["_kind"] = kind
    meta["_winner_ids"] = [int(x) for x in winner_ids]
    if mode_key == "team":
        meta["_team_totals"] = {"A": int(team_totals["A"]), "B": int(team_totals["B"])}
        meta["_win_team"] = win_team
    return display_winner, [int(x) for x in winner_ids], grant_rows, meta


def settle_battle(battle_id: int, *, conn) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Idempotent settle: claim settlement row first, then grant payouts once."""
    if not case_battles_schema_ready(conn):
        return False, "case_battles_unavailable", None

    battle = _fetch_battle(conn, int(battle_id))
    if not battle:
        return False, "battle_not_found", None

    existing = _fetch_settlement(conn, int(battle_id))
    if existing:
        if str(battle["status"]) != "finished":
            conn.execute(
                """
                UPDATE case_battles
                SET status = 'finished', finished_at = COALESCE(finished_at, ?)
                WHERE id = ?;
                """,
                (_now(), int(battle_id)),
            )
        return True, "case_battle_already_settled", get_battle_payload(int(battle_id), conn=conn)

    if str(battle["status"]) != "running":
        return False, "battle_not_running", None

    players = _fetch_players(conn, int(battle_id))
    rolls = _fetch_rolls(conn, int(battle_id))
    if not rolls:
        return False, "rolls_missing", None

    winner_id, _winner_ids, granted_rows, totals_meta = _compute_settlement_grants(
        str(battle["mode"]), players, rolls
    )

    now = _now()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO case_battle_settlements (
                battle_id, winner_id, totals_json, granted_json, settled_at
            ) VALUES (?, ?, ?, ?, ?);
            """,
            (
                int(battle_id),
                int(winner_id),
                _json_dumps(totals_meta),
                _json_dumps(granted_rows),
                now,
            ),
        )
    except Exception:
        return True, "case_battle_already_settled", get_battle_payload(int(battle_id), conn=conn)

    for row in granted_rows:
        grant_inventory_item(
            int(row["user_id"]),
            str(row["reward_key"]),
            int(row["amount"]),
            conn=conn,
        )

    cur.execute(
        """
        UPDATE case_battles
        SET status = 'finished', finished_at = ?
        WHERE id = ? AND status = 'running';
        """,
        (now, int(battle_id)),
    )
    return True, "case_battle_settled", get_battle_payload(int(battle_id), conn=conn)


def maybe_auto_settle(battle_id: int, *, conn) -> None:
    battle = _fetch_battle(conn, int(battle_id))
    if not battle or str(battle["status"]) != "running":
        return
    if _fetch_settlement(conn, int(battle_id)):
        return
    started = float(battle.get("started_at") or 0)
    if started <= 0:
        return
    if (_now() - started) < AUTO_SETTLE_AFTER_SEC:
        return
    settle_battle(int(battle_id), conn=conn)


# --- Fairness verify -----------------------------------------------------------

def verify_battle_roll(
    battle_id: int,
    *,
    round_index: int,
    user_id: int,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Recompute a finished battle roll from revealed server_seed."""
    if not case_battles_schema_ready(conn):
        return False, "case_battles_unavailable", None

    battle = _fetch_battle(conn, int(battle_id))
    if not battle:
        return False, "battle_not_found", None
    if str(battle["status"]) != "finished":
        return False, "battle_not_finished", None
    seed = battle.get("server_seed")
    if not seed:
        return False, "seed_unavailable", None
    if _hash_seed(str(seed)) != str(battle.get("server_seed_hash") or ""):
        return False, "seed_hash_mismatch", None

    players = _fetch_players(conn, int(battle_id))
    player = next((p for p in players if int(p["user_id"]) == int(user_id)), None)
    if not player:
        return False, "player_not_in_battle", None

    row = conn.execute(
        """
        SELECT * FROM case_battle_rolls
        WHERE battle_id = ? AND round_index = ? AND user_id = ?
        LIMIT 1;
        """,
        (int(battle_id), int(round_index), int(user_id)),
    ).fetchone()
    if not row:
        return False, "roll_not_found", None

    pool_snap = _json_loads(battle.get("pool_snapshot_json"), {}) or {}
    container_key = str(row["container_key"])
    pool = pool_snap.get(container_key) or []
    nonce = str(row["roll_nonce"])
    rng = _roll_rng(str(seed), int(battle_id), int(round_index), int(player["slot"]), nonce)
    recomputed = roll_single_loot_reward(pool, rng, loot_context=None)
    matches = (
        str(recomputed.get("reward_key")) == str(row["reward_key"])
        and str(recomputed.get("reward_type")) == str(row["reward_type"])
        and int(recomputed.get("amount") or 0) == int(row["reward_amount"])
    )
    return True, "verified" if matches else "mismatch", {
        "matches": matches,
        "stored": {
            "reward_type": str(row["reward_type"]),
            "reward_key": str(row["reward_key"]),
            "amount": int(row["reward_amount"]),
            "reward_value": int(row["reward_value"]),
        },
        "recomputed": recomputed,
        "server_seed_hash": battle.get("server_seed_hash"),
        "server_seed": str(seed),
    }


# --- Lobby / state -------------------------------------------------------------

def list_lobby_battles(*, conn, viewer_id: Optional[int] = None, limit: int = LOBBY_LIMIT) -> List[Dict[str, Any]]:
    if not case_battles_schema_ready(conn):
        return []
    rows = conn.execute(
        """
        SELECT id FROM case_battles
        WHERE status = 'open' AND visibility = 'public'
        ORDER BY created_at DESC
        LIMIT ?;
        """,
        (int(limit),),
    ).fetchall()
    out = []
    for row in rows:
        payload = get_battle_payload(int(row["id"]), conn=conn, viewer_id=viewer_id)
        if payload:
            out.append(payload)
    return out


def list_my_battles(user_id: int, *, conn, limit: int = HISTORY_LIMIT) -> List[Dict[str, Any]]:
    if not case_battles_schema_ready(conn):
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT b.id
        FROM case_battles b
        JOIN case_battle_players p ON p.battle_id = b.id
        WHERE p.user_id = ?
        ORDER BY COALESCE(b.finished_at, b.started_at, b.created_at) DESC
        LIMIT ?;
        """,
        (int(user_id), int(limit),),
    ).fetchall()
    out = []
    for row in rows:
        payload = get_battle_payload(int(row["id"]), conn=conn, viewer_id=int(user_id))
        if payload:
            out.append(payload)
    return out


def count_case_battles_nav_attention(user_id: int, *, conn) -> int:
    """Open or running Relikt-Arena battles where the player is a participant."""
    if not case_battles_schema_ready(conn):
        return 0
    uid = int(user_id)
    if uid <= 0:
        return 0
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT b.id) AS c
        FROM case_battles b
        JOIN case_battle_players p ON p.battle_id = b.id
        WHERE p.user_id = ?
          AND b.status IN ('open', 'running');
        """,
        (uid,),
    ).fetchone()
    return int((row["c"] if row else 0) or 0)


def build_case_battles_state(user_id: int, *, conn) -> Dict[str, Any]:
    ready = case_battles_schema_ready(conn)
    if not ready:
        return {
            "ready": False,
            "modes": sorted(MODES),
            "mode_meta": MODE_META,
            "player_limits": sorted(PLAYER_LIMITS),
            "container_battle_values": dict(CONTAINER_BATTLE_VALUE),
            "lobby": [],
            "mine": [],
            "active": None,
            "attention_count": 0,
        }

    mine = list_my_battles(int(user_id), conn=conn)
    active = next(
        (b for b in mine if b.get("status") in ("open", "running") and b.get("is_participant")),
        None,
    )
    attention = count_case_battles_nav_attention(int(user_id), conn=conn)
    return {
        "ready": True,
        "modes": sorted(MODES),
        "mode_meta": MODE_META,
        "player_limits": sorted(PLAYER_LIMITS),
        "player_limit_default": PLAYER_LIMIT_DEFAULT,
        "cases_min": CASES_MIN,
        "cases_max": CASES_MAX,
        "container_battle_values": dict(CONTAINER_BATTLE_VALUE),
        "lobby": list_lobby_battles(conn=conn, viewer_id=int(user_id)),
        "mine": mine,
        "active": active,
        "attention_count": int(attention),
    }


def definitions_public() -> Dict[str, Any]:
    return {
        "modes": sorted(MODES),
        "mode_meta": MODE_META,
        "player_limits": sorted(PLAYER_LIMITS),
        "player_limit_default": PLAYER_LIMIT_DEFAULT,
        "cases_min": CASES_MIN,
        "cases_max": CASES_MAX,
        "container_battle_values": dict(CONTAINER_BATTLE_VALUE),
    }
