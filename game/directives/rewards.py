"""Directive reward grants and claim flow (GC-913)."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..inventory import grant_inventory_item, inventory_schema_ready
from .definitions import directives_schema_ready, STATUS_CLAIMED, STATUS_COMPLETED

RARITY_CONTAINER: Dict[str, str] = {
    "common": "container_basic",
    "rare": "container_rare",
    "epic": "container_epic",
    "legendary": "container_relic",
}

RARITY_BOOSTERS: Dict[str, List[Dict[str, Any]]] = {
    "common": [{"item_key": "booster_build_5m", "amount": 1}],
    "rare": [{"item_key": "booster_build_15m", "amount": 1}],
    "epic": [
        {"item_key": "booster_build_1h", "amount": 1},
        {"item_key": "booster_research_1h", "amount": 1},
    ],
    "legendary": [
        {"item_key": "booster_build_24h", "amount": 1},
        {"item_key": "booster_research_24h", "amount": 1},
    ],
}


def build_reward_payload(*, rarity: str, cadence: str) -> Dict[str, Any]:
    r = str(rarity or "common").strip().lower()
    container_key = RARITY_CONTAINER.get(r, "container_basic")
    boosters = list(RARITY_BOOSTERS.get(r, RARITY_BOOSTERS["common"]))
    if str(cadence or "daily").strip().lower() == "weekly":
        boosters = [{**entry, "amount": int(entry.get("amount") or 1) + 1} for entry in boosters]
    return {
        "rarity": r,
        "container_key": container_key,
        "container_amount": 1,
        "boosters": boosters,
    }


def reward_json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _grant_reward_bundle(
    player_id: int,
    reward: Mapping[str, Any],
    *,
    conn: sqlite3.Connection,
    source: str,
) -> Tuple[bool, List[str]]:
    if not inventory_schema_ready(conn):
        return False, []
    granted: List[str] = []
    container_key = str(reward.get("container_key") or "").strip()
    container_amount = max(0, int(reward.get("container_amount") or 0))
    if container_key and container_amount > 0:
        ok = grant_inventory_item(
            int(player_id),
            container_key,
            container_amount,
            conn=conn,
            metadata={"source": source, "kind": "imperial_directive_container"},
        )
        if not ok:
            return False, granted
        granted.append(container_key)

    for entry in reward.get("boosters") or []:
        if not isinstance(entry, dict):
            continue
        item_key = str(entry.get("item_key") or "").strip()
        amount = max(0, int(entry.get("amount") or 0))
        if not item_key or amount <= 0:
            continue
        ok = grant_inventory_item(
            int(player_id),
            item_key,
            amount,
            conn=conn,
            metadata={"source": source, "kind": "imperial_directive_booster"},
        )
        if not ok:
            return False, granted
        granted.append(item_key)
    return True, granted


def _fetch_claimable_row(
    player_id: int,
    directive_id: int,
    *,
    conn: sqlite3.Connection,
) -> Optional[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, player_id, definition_key, cadence, rarity, status, reward_json, period_key
        FROM player_directives
        WHERE id = ? AND player_id = ? AND status = ?
        LIMIT 1;
        """,
        (int(directive_id), int(player_id), STATUS_COMPLETED),
    ).fetchone()


def claim_directive_reward(
    player_id: int,
    directive_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not directives_schema_ready(conn):
        return False, "directives_unavailable", None

    pid = int(player_id)
    did = int(directive_id)
    if pid <= 0 or did <= 0:
        return False, "invalid_directive", None

    row = _fetch_claimable_row(pid, did, conn=conn)
    if not row:
        existing = conn.execute(
            "SELECT status FROM player_directives WHERE id = ? AND player_id = ? LIMIT 1;",
            (did, pid),
        ).fetchone()
        if existing and str(existing["status"] or "") == STATUS_CLAIMED:
            return False, "reward_already_claimed", None
        return False, "directive_not_claimable", None

    reward = _json_loads(row["reward_json"])
    if not reward:
        reward = build_reward_payload(
            rarity=str(row["rarity"] or "common"),
            cadence=str(row["cadence"] or "daily"),
        )

    ok, granted = _grant_reward_bundle(
        pid,
        reward,
        conn=conn,
        source=f"imperial_directive:{did}",
    )
    if not ok:
        return False, "grant_failed", None

    ts = int(now if now is not None else time.time())
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE player_directives
        SET status = ?, claimed_at = ?
        WHERE id = ? AND player_id = ? AND status = ?;
        """,
        (STATUS_CLAIMED, ts, did, pid, STATUS_COMPLETED),
    )
    if int(cur.rowcount or 0) != 1:
        return False, "claim_race", None

    return True, "ok", {
        "directive_id": did,
        "definition_key": str(row["definition_key"] or ""),
        "granted_items": granted,
    }


def claim_all_directive_rewards(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float | None = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    if not directives_schema_ready(conn):
        return False, "directives_unavailable", {"claimed": [], "count": 0}

    pid = int(player_id)
    rows = conn.execute(
        """
        SELECT id FROM player_directives
        WHERE player_id = ? AND status = ?
        ORDER BY id ASC;
        """,
        (pid, STATUS_COMPLETED),
    ).fetchall()

    claimed: List[Dict[str, Any]] = []
    for row in rows:
        ok, reason, result = claim_directive_reward(
            pid,
            int(row["id"]),
            conn=conn,
            now=now,
        )
        if ok and result:
            claimed.append(result)
        elif reason not in ("ok", "reward_already_claimed"):
            if claimed:
                break
            return False, reason, {"claimed": claimed, "count": len(claimed)}

    return True, "ok", {"claimed": claimed, "count": len(claimed)}
