"""VOIDFALL Release 3: community convergence and capped rare discoveries.

The community score counts ONLY canonical, already-granted daily VOIDFALL
mission receipts (not raw fleet spam, premium actions, or free welcome claims).
All rewards use the Release 2 account-scoped ledger and transaction owner.
"""

from __future__ import annotations

import json
import secrets
import time

from .inventory import grant_inventory_item

# Every daily claim can add one signal to its own universe's shared count.
# 3 daily rewards/account max, independently of how many planets they own.
COMMUNITY_MILESTONES = (
    ("community_breach", 20, (("container_rare", 1),)),
    ("community_stabilize", 40, (("container_event_special", 1),)),
    ("community_contain", 70, (("container_relic", 1),)),
)

# Release 4: an irreversible, one-time account-wide choice.
ALIGNMENT_CLAIM_KEY = "voidfall2026:alignment"
ALIGNMENT_UNLOCK_SIGNALS = 40
ALIGNMENT_PERSONAL_SIGNALS = 3
ALIGNMENT_OPTIONS = (
    ("alignment_industry", (("booster_build_15m", 2),), "⚒"),
    ("alignment_science", (("booster_research_15m", 2),), "⌬"),
    ("alignment_exploration", (("booster_expedition_loot_25_24h", 1),), "🚀"),
)

# Limited to two discoveries per account throughout the event.
# 5% roll per legitimately claimed daily mission, with no paid rerolls.
DISCOVERY_CHANCE_PER_10000 = 500
DISCOVERY_MAX_PER_ACCOUNT = 2
DISCOVERY_POOL = (
    ("echo", 75, "container_event_special"),
    ("relic", 20, "container_relic"),
    ("artifact", 5, "container_void_artifact"),
)

# Lexicographic range of ISO-8601 days: includes only 2026-10-31..11-07
# mission claims, excluding welcome, community and discovery receipts.
DAILY_CLAIM_LOWER = "voidfall2026:2026-10-31:"
DAILY_CLAIM_UPPER = "voidfall2026:2026-11-08:"
COMMUNITY_PREFIX = "voidfall2026:community:"
DISCOVERY_PREFIX = "voidfall2026:discovery:"


def community_claim_key(key: str) -> str:
    return f"{COMMUNITY_PREFIX}{key}"


def get_community_state(player_id: int, *, conn, active: bool) -> dict:
    """Read a shared aggregate using a claim-key index and one account row scan."""
    from .voidfall import _reward_preview

    pid = int(player_id)
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN user_id = ? THEN 1 ELSE 0 END), 0) AS own
        FROM voidfall_reward_claims
        WHERE claim_key >= ? AND claim_key < ?;
        """,
        (pid, DAILY_CLAIM_LOWER, DAILY_CLAIM_UPPER),
    ).fetchone()
    total = int(row["total"] or 0)
    own = int(row["own"] or 0)

    own_rows = conn.execute(
        """
        SELECT claim_key, reward_json, claimed_at
        FROM voidfall_reward_claims
        WHERE user_id = ?
          AND (claim_key LIKE ?
               OR claim_key LIKE ?
               OR claim_key = ?)
        ORDER BY claimed_at, claim_key;
        """,
        (pid, f"{COMMUNITY_PREFIX}%", f"{DISCOVERY_PREFIX}%", ALIGNMENT_CLAIM_KEY),
    ).fetchall()
    receipts = {str(r["claim_key"]): r for r in own_rows}
    milestones = []
    for key, threshold, rewards in COMMUNITY_MILESTONES:
        receipt_key = community_claim_key(key)
        has_claimed = receipt_key in receipts
        reached = total >= threshold
        milestones.append({
            "key": key,
            "threshold": threshold,
            "progress": min(total, threshold),
            "unlocked": reached,
            "claimed": has_claimed,
            "claimable": active and reached and own >= 1 and not has_claimed,
            "rewards": _reward_preview(rewards),
        })

    alignment_receipt = receipts.get(ALIGNMENT_CLAIM_KEY)
    selected_path = None
    if alignment_receipt is not None:
        try:
            saved = json.loads(str(alignment_receipt["reward_json"] or "[]"))
        except (TypeError, ValueError):
            saved = []
        if isinstance(saved, list) and saved and isinstance(saved[0], dict):
            candidate = saved[0].get("path")
            if candidate in {option[0] for option in ALIGNMENT_OPTIONS}:
                selected_path = candidate
    alignment_available = (
        active and total >= ALIGNMENT_UNLOCK_SIGNALS
        and own >= ALIGNMENT_PERSONAL_SIGNALS and alignment_receipt is None
    )
    alignment = {
        "unlocked": total >= ALIGNMENT_UNLOCK_SIGNALS,
        "available": alignment_available,
        "chosen": alignment_receipt is not None,
        "selected_path": selected_path,
        "required_global": ALIGNMENT_UNLOCK_SIGNALS,
        "required_personal": ALIGNMENT_PERSONAL_SIGNALS,
        "options": [
            {
                "key": key, "icon": icon, "rewards": _reward_preview(rewards),
                "claimable": alignment_available,
                "claimed": alignment_receipt is not None,
                "selected": selected_path == key,
            }
            for key, rewards, icon in ALIGNMENT_OPTIONS
        ],
    }

    discoveries = []
    for seq in range(1, DISCOVERY_MAX_PER_ACCOUNT + 1):
        receipt = receipts.get(f"{DISCOVERY_PREFIX}{seq}")
        if not receipt:
            continue
        payload = json.loads(str(receipt["reward_json"] or "[]"))
        if not isinstance(payload, list) or not payload:
            continue
        reward = payload[0]
        kind = str(reward.get("kind") or "echo")
        if kind not in {row[0] for row in DISCOVERY_POOL}:
            continue
        item_key = str(reward.get("item_key") or "")
        discoveries.append({
            "kind": kind, "sequence": seq,
            "rewards": _reward_preview(((item_key, 1),)),
        })

    return {
        "signals": total,
        "my_signals": own,
        "milestones": milestones,
        "alignment": alignment,
        "discoveries": discoveries,
        "discovery_count": len(discoveries),
        "discovery_max": DISCOVERY_MAX_PER_ACCOUNT,
    }


def maybe_award_discovery(player_id: int, *, conn, now: float | None = None) -> dict | None:
    """Roll once on a successfully claimed daily mission; transaction owned by caller."""
    pid = int(player_id)
    existing = conn.execute(
        """
        SELECT claim_key FROM voidfall_reward_claims
        WHERE user_id = ? AND claim_key LIKE ?;
        """,
        (pid, f"{DISCOVERY_PREFIX}%"),
    ).fetchall()
    claimed = {str(row["claim_key"]) for row in existing}
    sequence = next(
        (i for i in range(1, DISCOVERY_MAX_PER_ACCOUNT + 1)
         if f"{DISCOVERY_PREFIX}{i}" not in claimed),
        None,
    )
    if sequence is None or secrets.randbelow(10000) >= DISCOVERY_CHANCE_PER_10000:
        return None

    # Unbiased tier selection: 75% echo, 20% relic, 5% artifact.
    roll = secrets.randbelow(sum(int(row[1]) for row in DISCOVERY_POOL))
    kind = "echo"
    item_key = "container_event_special"
    for candidate_kind, weight, candidate_item in DISCOVERY_POOL:
        if roll < int(weight):
            kind, item_key = candidate_kind, candidate_item
            break
        roll -= int(weight)

    receipt_key = f"{DISCOVERY_PREFIX}{sequence}"
    if not grant_inventory_item(
        pid, item_key, 1, conn=conn,
        metadata={"source": "voidfall_discovery", "claim_key": receipt_key},
    ):
        # Let the outer transaction roll back the mission reward as well.
        raise RuntimeError("voidfall_discovery_grant_failed")
    reward = {"kind": kind, "item_key": item_key, "amount": 1}
    conn.execute(
        """
        INSERT INTO voidfall_reward_claims (user_id, claim_key, reward_json, claimed_at)
        VALUES (?, ?, ?, ?);
        """,
        (pid, receipt_key, json.dumps([reward], separators=(",", ":")),
         float(time.time() if now is None else now)),
    )
    return {"kind": kind, "reward": reward, "sequence": sequence}
