"""VOIDFALL 2026 daily operations and account welcome claim.

Reads canonical activity_xp_log; grants canonical inventory items only.
All writes must run inside the caller's transaction after locking the user row.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from .db import table_exists
from .inventory import grant_inventory_item, inventory_schema_ready
from .inventory_catalog import item_catalog_entry

START_AT = 1793404800
END_AT = 1794095999
SLUG = "voidfall-rift-opening-2026"
CLAIM_PREFIX = "voidfall2026"
WELCOME_KEY = "welcome"

# Complete all three objectives with just two expeditions and one completed build.
# No planet count, premium requirement, timekeeper, or raw-resource injection.
MISSION_CATALOG = (
    ("expeditions", 2, ("expedition",), (("booster_expedition_loot_25_24h", 1),), "🚀"),
    ("construction", 1, ("building_finish",), (("booster_build_15m", 1),), "⚒"),
    ("operations", 3, ("expedition", "building_finish", "account_research_finish", "spy", "recycle"),
     (("container_event_special", 1),), "✦"),
)
WELCOME_ITEMS = (("container_rare", 1), ("booster_research_15m", 1))

# Only VOIDFALL reward items receive a player-facing, verified effect description.
# Time booster values are actual queue/Timekeeper seconds, not a percentage.
REWARD_DETAIL_ITEMS = frozenset({
    "container_rare", "container_event_special", "container_relic",
    "container_void_artifact", "booster_build_15m", "booster_research_15m",
    "booster_expedition_loot_25_24h",
})

LABEL_NAMES = (
    "subtitle",
    "welcome",
    "welcome_hint",
    "expeditions",
    "construction",
    "operations",
    "claim",
    "claimed",
    "locked",
    "ended",
    "success",
    "failed",
    "remaining",
    "reward",
    "until",
    "community_title",
    "community_hint",
    "community_signals",
    "community_eligibility",
    "community_breach",
    "community_stabilize",
    "community_contain",
    "alignment_title",
    "alignment_hint",
    "alignment_global",
    "alignment_personal",
    "alignment_industry",
    "alignment_science",
    "alignment_exploration",
    "alignment_chosen",
    "discovery_title",
    "discovery_hint",
    "discovery_echo",
    "discovery_relic",
    "discovery_artifact",
    "discovery_none",
    "discovery_found",
    "how_expeditions",
    "how_construction",
    "how_operations",
    "source_expedition",
    "source_building_finish",
    "source_account_research_finish",
    "source_spy",
    "source_recycle",
    "go_fleet",
    "go_buildings",
    "go_research",
    "objective_title",
    "reward_benefit",
    "activity_breakdown",
    "inventory_hint",
)


def schema_ready(conn) -> bool:
    return (
        table_exists(conn, "voidfall_reward_claims")
        and table_exists(conn, "server_events")
        and table_exists(conn, "activity_xp_log")
        and inventory_schema_ready(conn)
    )


def _reward_preview(items: tuple[tuple[str, int], ...]) -> list[dict[str, Any]]:
    out = []
    for key, amount in items:
        spec = item_catalog_entry(key) or {}
        out.append({
            "item_key": key, "amount": amount,
            "name_key": spec.get("name_key") or key,
            "icon": spec.get("icon") or "✦",
            "image": spec.get("image") or "",
            "detail_key": f"voidfall_reward_detail_{key}" if key in REWARD_DETAIL_ITEMS else None,
        })
    return out


def _utc_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _claim_key(key: str, ts: float) -> str:
    if key == WELCOME_KEY:
        return f"{CLAIM_PREFIX}:{WELCOME_KEY}"
    return f"{CLAIM_PREFIX}:{_utc_day(ts)}:{key}"


def _event_status(conn, ts: float) -> tuple[bool, bool]:
    row = conn.execute(
        "SELECT enabled, starts_at, ends_at FROM server_events WHERE slug = ? LIMIT 1;",
        (SLUG,),
    ).fetchone()
    if not row:
        return False, False
    active = (
        bool(int(row["enabled"] or 0))
        and START_AT <= ts <= END_AT
        and float(row["starts_at"]) <= ts <= float(row["ends_at"])
    )
    return True, active


def get_state(player_id: int, *, conn, now: float | None = None, locale: str | None = None) -> dict[str, Any]:
    ts = float(time.time() if now is None else now)
    if not schema_ready(conn) or int(player_id) <= 0:
        return {"ready": False, "visible": False, "active": False}
    from .i18n import current_locale, tr
    loc = (locale or current_locale()).lower()
    labels = {name: tr(f"voidfall_{name}", locale=loc) for name in LABEL_NAMES}
    visible, active = _event_status(conn, ts)
    if not visible:
        return {"ready": True, "visible": False, "active": False}
    # GC-VOIDFALL-009: an expired event is a tiny, read-only recap, not
    # the full daily-ops screen. Avoid the activity/day-claim queries forever
    # after expiry; use the existing receipt ledger for stable final totals.
    if ts > END_AT:
        from .voidfall_community import get_community_state
        community = get_community_state(int(player_id), conn=conn, active=False)
        return {
            "ready": True, "visible": True, "active": False, "ended": True,
            "slug": SLUG, "ends_at": END_AT, "labels": labels,
            "community": community,
            "archive": {
                "my_signals": community["my_signals"],
                "signals": community["signals"],
                "milestones_claimed": sum(
                    1 for milestone in community["milestones"] if milestone["claimed"]
                ),
                "discovery_count": community["discovery_count"],
                "selected_path": community["alignment"]["selected_path"],
            },
        }
    bucket = int(ts // 86400)
    rows = conn.execute(
        """
        SELECT source_key, COUNT(*) AS n FROM activity_xp_log
        WHERE player_id = ? AND day_bucket = ?
          AND source_key IN ('expedition','building_finish','account_research_finish','spy','recycle')
        GROUP BY source_key;
        """,
        (int(player_id), bucket),
    ).fetchall()
    counts = {str(r["source_key"]): int(r["n"]) for r in rows}
    date = _utc_day(ts)
    claim_rows = conn.execute(
        "SELECT claim_key FROM voidfall_reward_claims WHERE user_id = ? AND (claim_key = ? OR claim_key LIKE ?);",
        (int(player_id), f"{CLAIM_PREFIX}:welcome", f"{CLAIM_PREFIX}:{date}:%"),
    ).fetchall()
    claimed = {str(r["claim_key"]) for r in claim_rows}
    missions = []
    for key, target, sources, rewards, icon in MISSION_CATALOG:
        progress = min(target, sum(counts.get(src, 0) for src in sources))
        has_claimed = _claim_key(key, ts) in claimed
        missions.append({
            "key": key, "title": labels[key], "icon": icon,
            "progress": progress, "target": target,
            "sources": sources,
            "source_counts": {src: int(counts.get(src, 0)) for src in sources},
            "claimed": has_claimed, "claimable": active and progress >= target and not has_claimed,
            "rewards": _reward_preview(rewards),
        })
    from .voidfall_community import get_community_state
    community = get_community_state(int(player_id), conn=conn, active=active)
    welcomed = _claim_key(WELCOME_KEY, ts) in claimed
    return {
        "ready": True, "visible": True, "active": active, "ended": False,
        "slug": SLUG, "day": date, "ends_at": END_AT,
        "server_now": ts, "next_reset_at": (bucket + 1) * 86400,
        "labels": labels,
        "welcome": {
            "key": WELCOME_KEY, "claimed": welcomed, "claimable": active and not welcomed,
            "rewards": _reward_preview(WELCOME_ITEMS),
        },
        "missions": missions,
        "community": community,
    }


def claim(player_id: int, key: str, *, conn, now: float | None = None) -> tuple[bool, str, dict[str, Any] | None]:
    """Caller owns a write transaction and must lock the account row first."""
    ts = float(time.time() if now is None else now)
    if not schema_ready(conn):
        return False, "unavailable", None
    if not (START_AT <= ts <= END_AT):
        return False, "event_ended", None
    from .voidfall_community import (
        ALIGNMENT_CLAIM_KEY, ALIGNMENT_OPTIONS, COMMUNITY_MILESTONES,
        community_claim_key, maybe_award_discovery,
    )
    mission_keys = tuple(m[0] for m in MISSION_CATALOG)
    community_keys = tuple(m[0] for m in COMMUNITY_MILESTONES)
    alignment_keys = tuple(option[0] for option in ALIGNMENT_OPTIONS)
    allowed = (WELCOME_KEY,) + mission_keys + community_keys + alignment_keys
    if key not in allowed:
        return False, "unknown_claim", None
    state = get_state(int(player_id), conn=conn, now=ts)
    if not state.get("active"):
        return False, "event_inactive", None
    if key == WELCOME_KEY:
        target = state["welcome"]
        rewards = WELCOME_ITEMS
    elif key in community_keys:
        target = next(m for m in state["community"]["milestones"] if m["key"] == key)
        rewards = next(m[2] for m in COMMUNITY_MILESTONES if m[0] == key)
    elif key in alignment_keys:
        target = next(o for o in state["community"]["alignment"]["options"] if o["key"] == key)
        rewards = next(o[1] for o in ALIGNMENT_OPTIONS if o[0] == key)
    else:
        target = next(m for m in state["missions"] if m["key"] == key)
        rewards = next(m[3] for m in MISSION_CATALOG if m[0] == key)
    if target["claimed"]:
        return False, "already_claimed", None
    if not target["claimable"]:
        return False, "objective_incomplete", None

    claim_key = (
        ALIGNMENT_CLAIM_KEY if key in alignment_keys else
        community_claim_key(key) if key in community_keys else _claim_key(key, ts)
    )
    for item_key, amount in rewards:
        if not grant_inventory_item(
            int(player_id), item_key, amount, conn=conn,
            metadata={"source": "voidfall", "claim_key": claim_key},
        ):
            return False, "grant_failed", None

    payload = [
        {"item_key": k, "amount": n, **({"path": key} if key in alignment_keys else {})}
        for k, n in rewards
    ]
    conn.execute(
        "INSERT INTO voidfall_reward_claims (user_id, claim_key, reward_json, claimed_at) VALUES (?, ?, ?, ?);",
        (int(player_id), claim_key, json.dumps(payload, separators=(",", ":")), ts),
    )
    result = {"claim_key": claim_key, "rewards": _reward_preview(rewards)}
    if key in mission_keys:
        discovery = maybe_award_discovery(int(player_id), conn=conn, now=ts)
        if discovery is not None:
            result["discovery"] = discovery
    return True, "ok", result
