"""
EPIC-22 / GC-990–992 — Season Battle Pass (Free + Premium tracks).

XP via soft-capped activity drip + Season Ops claims.
Premium unlock via premium_entitlements / player flag.
Grants use grant_inventory_item only (meta rewards).
"""

from __future__ import annotations

import datetime
import json
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import table_exists
from .inventory import grant_inventory_item, inventory_schema_ready
from .inventory_catalog import item_catalog_entry, is_known_item_key
from .premium_entitlements import (
    KIND_BATTLE_PASS_PREMIUM,
    grant_entitlement,
    has_entitlement,
    schema_ready as entitlements_ready,
)

DEFAULT_SEASON_SLUG = "genesis_s1"
DEFAULT_XP_PER_LEVEL = 100
DEFAULT_MAX_LEVEL = 50
DEFAULT_SEASON_DAYS = 60
TRACK_FREE = "free"
TRACK_PREMIUM = "premium"
# Bump when reward tables change — ensure_default_season reseeds levels if stale.
REWARD_CATALOG_VERSION = 5
_CATALOG_MARKER_ITEM = "container_void_artifact"
# L50 premium must credit at least this much direct Timekeeper (catalog v3+).
_CATALOG_MIN_L50_TK_SEC = 48 * 3600
_CATALOG_V4_BADGE_MARKER = "bp_s1_legend"
_CATALOG_V5_FLAIR_MARKER = "imperial"

# Soft-capped passive BP XP from activity_xp (planet XP stays uncapped).
PASSIVE_DRIP_DAILY_CAP = 40
PASSIVE_DRIP_OP_KEY = "_passive_drip"

OP_BUILD = "op_build_1"
OP_RESEARCH = "op_research_1"
OP_FLEET = "op_fleet_1"
OP_WEEK_ACTIVE = "op_week_active"

# Pace (GC-BPUI): 50 levels × 100 XP = 5000.
# Full daily Ops + drip + weekly ≈ finish in ~28–30 calendar days.
# Season length stays 60d so missed days still complete in-season.
# Targets: stronger than trivial 1×, below Story Ops Q1 (build 5–8 / fleet ~5).
OPS_CATALOG: Dict[str, Dict[str, Any]] = {
    OP_BUILD: {
        "cadence": "daily",
        "target": 3,
        "xp_reward": 40,
        "icon": "⚒",
        "image": "img/pass/build_boost.webp",
        "title_key": "bp_op_build_title",
        "hint_key": "bp_op_build_hint",
        "sources": frozenset({"building_finish"}),
    },
    OP_RESEARCH: {
        "cadence": "daily",
        "target": 2,
        "xp_reward": 45,
        "icon": "◈",
        "image": "img/pass/research_booster.webp",
        "title_key": "bp_op_research_title",
        "hint_key": "bp_op_research_hint",
        "sources": frozenset({"account_research_finish"}),
    },
    OP_FLEET: {
        "cadence": "daily",
        "target": 3,
        "xp_reward": 50,
        "icon": "🚀",
        "image": "img/pass/expedition_ticket.webp",
        "title_key": "bp_op_fleet_title",
        "hint_key": "bp_op_fleet_hint",
        "sources": frozenset({"expedition", "spy", "recycle"}),
    },
    OP_WEEK_ACTIVE: {
        "cadence": "weekly",
        "target": 18,
        "xp_reward": 160,
        "icon": "★",
        "image": "img/pass/xp.webp",
        "title_key": "bp_op_week_title",
        "hint_key": "bp_op_week_hint",
        "sources": frozenset({"building_finish", "account_research_finish", "expedition"}),
    },
}

DAILY_OP_KEYS: List[str] = [OP_BUILD, OP_RESEARCH, OP_FLEET]
WEEKLY_OP_KEYS: List[str] = [OP_WEEK_ACTIVE]


def schema_ready(conn) -> bool:
    return bool(
        table_exists(conn, "battle_pass_seasons")
        and table_exists(conn, "battle_pass_levels")
        and table_exists(conn, "player_battle_pass")
        and table_exists(conn, "battle_pass_claims")
        and table_exists(conn, "battle_pass_ops_progress")
    )


def ops_schema_ready(conn) -> bool:
    return bool(table_exists(conn, "battle_pass_ops_progress"))


def _utc_dt(ts: float) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(float(ts), tz=datetime.timezone.utc)


def daily_period_key(ts: Optional[float] = None) -> str:
    dt = _utc_dt(ts if ts is not None else time.time())
    return f"daily:{dt.strftime('%Y-%m-%d')}"


def weekly_period_key(ts: Optional[float] = None) -> str:
    dt = _utc_dt(ts if ts is not None else time.time())
    iso = dt.isocalendar()
    return f"weekly:{iso.year}-W{iso.week:02d}"


def _json_dumps(payload: Mapping[str, Any]) -> str:
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


def _item(item_key: str, amount: int = 1) -> Dict[str, Any]:
    return {"item_key": str(item_key), "amount": int(amount)}


def _bundle(
    *items: Dict[str, Any],
    timekeeper_sec: int = 0,
    themes: Optional[List[str]] = None,
    badges: Optional[List[str]] = None,
    auras: Optional[List[str]] = None,
    title_flairs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "items": list(items),
        "timekeeper_sec": max(0, int(timekeeper_sec or 0)),
    }
    if themes:
        out["themes"] = [str(t).strip().lower() for t in themes if str(t).strip()]
    if badges:
        out["badges"] = [str(b).strip().lower() for b in badges if str(b).strip()]
    if auras:
        out["auras"] = [str(a).strip().lower() for a in auras if str(a).strip()]
    if title_flairs:
        out["title_flairs"] = [
            str(f).strip().lower() for f in title_flairs if str(f).strip()
        ]
    return out


def _with_cosmetics(
    bundle: Dict[str, Any],
    *,
    themes: Optional[List[str]] = None,
    badges: Optional[List[str]] = None,
    auras: Optional[List[str]] = None,
    title_flairs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    out = dict(bundle)
    if themes:
        merged = list(out.get("themes") or [])
        for t in themes:
            key = str(t).strip().lower()
            if key and key not in merged:
                merged.append(key)
        out["themes"] = merged
    if badges:
        merged_b = list(out.get("badges") or [])
        for b in badges:
            key = str(b).strip().lower()
            if key and key not in merged_b:
                merged_b.append(key)
        out["badges"] = merged_b
    if auras:
        merged_a = list(out.get("auras") or [])
        for a in auras:
            key = str(a).strip().lower()
            if key and key not in merged_a:
                merged_a.append(key)
        out["auras"] = merged_a
    if title_flairs:
        merged_f = list(out.get("title_flairs") or [])
        for f in title_flairs:
            key = str(f).strip().lower()
            if key and key not in merged_f:
                merged_f.append(key)
        out["title_flairs"] = merged_f
    return out


def _default_level_rewards(level: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Free stays solid; Premium is the FOMO jackpot (meta + season cosmetics)."""
    lv = int(level)

    # --- Free: steady drip, real milestones, never matches Premium density ---
    if lv == DEFAULT_MAX_LEVEL:
        free = _bundle(
            _item("container_epic", 2),
            _item("booster_build_6h"),
            _item("booster_research_6h"),
            timekeeper_sec=1800,
        )
    elif lv % 10 == 0:
        free = _bundle(
            _item("container_epic" if lv >= 30 else "container_rare", 1 + (1 if lv >= 40 else 0)),
            _item("booster_build_1h"),
            timekeeper_sec=600 if lv >= 30 else 300,
        )
    elif lv % 5 == 0:
        free = _bundle(_item("container_rare"), _item("booster_build_15m"), _item("booster_research_15m"))
    elif lv % 3 == 0:
        free = _bundle(_item("booster_research_15m"), _item("booster_production_25"))
    else:
        free = _bundle(_item("booster_build_15m" if lv >= 20 else "booster_build_5m"))

    # --- Premium: every level pays hard; TK sized for multi-hour builds ---
    if lv == DEFAULT_MAX_LEVEL:
        premium = _bundle(
            _item("container_void_artifact", 2),
            _item("container_mythic", 3),
            _item("container_ancient_relic", 2),
            _item("booster_build_24h", 4),
            _item("booster_research_24h", 4),
            _item("booster_production_100", 3),
            timekeeper_sec=48 * 3600,
        )
    elif lv == 40:
        premium = _bundle(
            _item("container_ancient_relic", 2),
            _item("container_mythic", 2),
            _item("container_relic", 2),
            _item("booster_build_24h", 3),
            _item("booster_research_24h", 3),
            _item("booster_production_100", 2),
            timekeeper_sec=24 * 3600,
        )
    elif lv == 25:
        premium = _bundle(
            _item("container_mythic", 2),
            _item("container_relic", 2),
            _item("booster_build_24h", 2),
            _item("booster_research_24h"),
            _item("booster_research_6h", 2),
            _item("booster_production_100"),
            timekeeper_sec=12 * 3600,
        )
    elif lv % 10 == 0:
        premium = _bundle(
            _item("container_relic" if lv >= 30 else "container_epic", 3),
            _item("container_event_special", 2),
            _item("booster_build_24h" if lv >= 30 else "booster_build_6h", 2 if lv >= 30 else 3),
            _item("booster_research_24h" if lv >= 30 else "booster_research_6h", 2 if lv >= 30 else 3),
            _item("booster_production_100" if lv >= 30 else "booster_production_50", 2),
            timekeeper_sec=(12 * 3600) if lv >= 30 else (6 * 3600),
        )
    elif lv % 5 == 0:
        premium = _bundle(
            _item("container_epic", 2),
            _item("container_rare", 3),
            _item("booster_build_6h", 3),
            _item("booster_research_6h", 3),
            _item("booster_production_50", 2),
            timekeeper_sec=6 * 3600,
        )
    elif lv % 3 == 0:
        premium = _bundle(
            _item("container_rare", 2),
            _item("booster_build_6h"),
            _item("booster_research_6h"),
            _item("booster_build_1h", 2),
            _item("booster_research_1h", 2),
            _item("booster_production_50"),
            timekeeper_sec=3 * 3600,
        )
    else:
        premium = _bundle(
            _item("container_rare" if lv >= 10 else "container_basic", 2),
            _item("booster_build_6h" if lv >= 20 else "booster_build_1h", 2),
            _item("booster_research_1h", 2),
            _item("booster_production_25"),
            timekeeper_sec=(2 * 3600) if lv >= 20 else 3600,
        )

    # Season cosmetics (own layer — never gates base themes cyan/violet/…)
    if lv == 10:
        free = _with_cosmetics(free, themes=["ash"], auras=["rim_ash"])
    elif lv == 20:
        free = _with_cosmetics(free, badges=["bp_s1_attendee"], title_flairs=["etched"])
    elif lv == 40:
        free = _with_cosmetics(free, themes=["steel"], auras=["rim_steel"])

    if lv == 15:
        premium = _with_cosmetics(premium, themes=["gold"], auras=["aura_gold"])
    elif lv == 20:
        premium = _with_cosmetics(premium, themes=["plasma"], auras=["aura_plasma"])
    elif lv == 25:
        premium = _with_cosmetics(
            premium, badges=["bp_s1_operative"], title_flairs=["signal"]
        )
    elif lv == 40:
        premium = _with_cosmetics(
            premium, themes=["void"], badges=["bp_s1_elite"], auras=["aura_void"]
        )
    elif lv == DEFAULT_MAX_LEVEL:
        premium = _with_cosmetics(
            premium, badges=["bp_s1_legend"], title_flairs=["imperial"]
        )

    return free, premium


def _season_levels_stale(conn, season_id: int) -> bool:
    """True if level rows missing or catalog older than REWARD_CATALOG_VERSION marker."""
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM battle_pass_levels WHERE season_id = ?;",
        (int(season_id),),
    ).fetchone()
    if int(count["c"] or 0) < DEFAULT_MAX_LEVEL:
        return True
    row = conn.execute(
        """
        SELECT premium_reward_json FROM battle_pass_levels
        WHERE season_id = ? AND level = ? LIMIT 1;
        """,
        (int(season_id), DEFAULT_MAX_LEVEL),
    ).fetchone()
    if not row:
        return True
    payload = _json_loads(row["premium_reward_json"])
    keys = {str(i.get("item_key") or "") for i in (payload.get("items") or []) if isinstance(i, dict)}
    tk = int(payload.get("timekeeper_sec") or 0)
    void_amt = 0
    for item in payload.get("items") or []:
        if isinstance(item, dict) and str(item.get("item_key") or "") == _CATALOG_MARKER_ITEM:
            void_amt = int(item.get("amount") or 0)
            break
    return (
        _CATALOG_MARKER_ITEM not in keys
        or void_amt < 2
        or tk < _CATALOG_MIN_L50_TK_SEC
        or _CATALOG_V4_BADGE_MARKER not in {
            str(b).strip().lower() for b in (payload.get("badges") or []) if b
        }
        or _CATALOG_V5_FLAIR_MARKER not in {
            str(f).strip().lower() for f in (payload.get("title_flairs") or []) if f
        }
    )


def _seed_season_levels(conn, season_id: int) -> None:
    sid = int(season_id)
    conn.execute("DELETE FROM battle_pass_levels WHERE season_id = ?;", (sid,))
    for level in range(1, DEFAULT_MAX_LEVEL + 1):
        free, premium = _default_level_rewards(level)
        conn.execute(
            """
            INSERT INTO battle_pass_levels (
                season_id, level, free_reward_json, premium_reward_json
            ) VALUES (?, ?, ?, ?);
            """,
            (sid, level, _json_dumps(free), _json_dumps(premium)),
        )


def ensure_default_season(conn, *, now: Optional[float] = None) -> Optional[int]:
    """Ensure an active season + level catalog exists. Returns season id."""
    if not schema_ready(conn):
        return None
    ts = float(now if now is not None else time.time())
    row = conn.execute(
        """
        SELECT id FROM battle_pass_seasons
        WHERE active = 1
        ORDER BY id DESC
        LIMIT 1;
        """
    ).fetchone()
    if row:
        sid = int(row["id"])
        if _season_levels_stale(conn, sid):
            _seed_season_levels(conn, sid)
        return sid

    existing = conn.execute(
        "SELECT id FROM battle_pass_seasons WHERE slug = ? LIMIT 1;",
        (DEFAULT_SEASON_SLUG,),
    ).fetchone()
    if existing:
        sid = int(existing["id"])
        conn.execute("UPDATE battle_pass_seasons SET active = 0;")
        conn.execute(
            "UPDATE battle_pass_seasons SET active = 1, starts_at = ?, ends_at = ? WHERE id = ?;",
            (ts, ts + DEFAULT_SEASON_DAYS * 86400, sid),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO battle_pass_seasons (
                slug, title_key, starts_at, ends_at, xp_per_level, max_level, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?);
            """,
            (
                DEFAULT_SEASON_SLUG,
                "bp_season_default_title",
                ts,
                ts + DEFAULT_SEASON_DAYS * 86400,
                DEFAULT_XP_PER_LEVEL,
                DEFAULT_MAX_LEVEL,
                ts,
            ),
        )
        sid = int(cur.lastrowid)

    if _season_levels_stale(conn, sid):
        _seed_season_levels(conn, sid)
    return sid


def get_active_season(conn, *, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    if not schema_ready(conn):
        return None
    ts = float(now if now is not None else time.time())
    sid = ensure_default_season(conn, now=ts)
    if not sid:
        return None
    row = conn.execute(
        """
        SELECT id, slug, title_key, starts_at, ends_at, xp_per_level, max_level, active
        FROM battle_pass_seasons WHERE id = ? LIMIT 1;
        """,
        (sid,),
    ).fetchone()
    if not row:
        return None
    remaining = max(0, int(float(row["ends_at"] or 0) - ts))
    from .time_format import format_duration_human

    return {
        "id": int(row["id"]),
        "slug": str(row["slug"]),
        "title_key": str(row["title_key"] or "bp_season_default_title"),
        "starts_at": float(row["starts_at"] or 0),
        "ends_at": float(row["ends_at"] or 0),
        "xp_per_level": int(row["xp_per_level"] or DEFAULT_XP_PER_LEVEL),
        "max_level": int(row["max_level"] or DEFAULT_MAX_LEVEL),
        "active": bool(row["active"]),
        "seconds_remaining": remaining,
        "remaining_label": format_duration_human(remaining, max_parts=3),
    }


def _ensure_player_row(player_id: int, season_id: int, *, conn, now: float) -> Dict[str, Any]:
    row = conn.execute(
        """
        SELECT player_id, season_id, xp, level, premium_unlocked, premium_unlocked_at, updated_at
        FROM player_battle_pass
        WHERE player_id = ? AND season_id = ?
        LIMIT 1;
        """,
        (int(player_id), int(season_id)),
    ).fetchone()
    if row:
        return {
            "player_id": int(row["player_id"]),
            "season_id": int(row["season_id"]),
            "xp": int(row["xp"] or 0),
            "level": int(row["level"] or 0),
            "premium_unlocked": bool(row["premium_unlocked"]),
            "premium_unlocked_at": float(row["premium_unlocked_at"]) if row["premium_unlocked_at"] else None,
            "updated_at": float(row["updated_at"] or 0),
        }
    premium = False
    if entitlements_ready(conn):
        premium = has_entitlement(
            int(player_id),
            KIND_BATTLE_PASS_PREMIUM,
            conn=conn,
            season_id=int(season_id),
        ) or has_entitlement(
            int(player_id),
            KIND_BATTLE_PASS_PREMIUM,
            conn=conn,
            season_id=None,
        )
    conn.execute(
        """
        INSERT INTO player_battle_pass (
            player_id, season_id, xp, level, premium_unlocked, premium_unlocked_at, updated_at
        ) VALUES (?, ?, 0, 0, ?, ?, ?);
        """,
        (
            int(player_id),
            int(season_id),
            1 if premium else 0,
            float(now) if premium else None,
            float(now),
        ),
    )
    return {
        "player_id": int(player_id),
        "season_id": int(season_id),
        "xp": 0,
        "level": 0,
        "premium_unlocked": bool(premium),
        "premium_unlocked_at": float(now) if premium else None,
        "updated_at": float(now),
    }


def _level_from_xp(xp: int, xp_per_level: int, max_level: int) -> int:
    if xp_per_level <= 0:
        return 0
    return min(int(max_level), int(xp) // int(xp_per_level))


def _ops_period_key(cadence: str, ts: float) -> str:
    if str(cadence) == "weekly":
        return weekly_period_key(ts)
    return daily_period_key(ts)


def ensure_ops_for_period(
    player_id: int,
    season_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    """Ensure daily + weekly op rows exist for the current periods."""
    if not ops_schema_ready(conn):
        return
    ts = float(now if now is not None else time.time())
    pid = int(player_id)
    sid = int(season_id)
    for op_key, meta in OPS_CATALOG.items():
        period = _ops_period_key(str(meta["cadence"]), ts)
        target = int(meta["target"])
        xp_reward = int(meta["xp_reward"])
        conn.execute(
            """
            INSERT OR IGNORE INTO battle_pass_ops_progress (
                player_id, season_id, period_key, op_key,
                progress, target, xp_reward, claimed_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, NULL, ?);
            """,
            (pid, sid, period, op_key, target, xp_reward, ts),
        )
        # Unclaimed rows pick up catalog XP/target changes (pace retunes without a new period).
        conn.execute(
            """
            UPDATE battle_pass_ops_progress
            SET target = ?, xp_reward = ?, updated_at = ?
            WHERE player_id = ? AND season_id = ? AND period_key = ? AND op_key = ?
              AND claimed_at IS NULL;
            """,
            (target, xp_reward, ts, pid, sid, period, op_key),
        )


def _get_op_row(
    player_id: int,
    season_id: int,
    period_key: str,
    op_key: str,
    *,
    conn,
) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT player_id, season_id, period_key, op_key, progress, target,
               xp_reward, claimed_at, updated_at
        FROM battle_pass_ops_progress
        WHERE player_id = ? AND season_id = ? AND period_key = ? AND op_key = ?
        LIMIT 1;
        """,
        (int(player_id), int(season_id), str(period_key), str(op_key)),
    ).fetchone()
    return dict(row) if row else None


def _drip_granted_today(player_id: int, season_id: int, period_key: str, *, conn) -> int:
    row = _get_op_row(player_id, season_id, period_key, PASSIVE_DRIP_OP_KEY, conn=conn)
    return int(row["progress"]) if row else 0


def credit_activity_drip_xp(
    player_id: int,
    amount: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Credit BP XP from activity with a daily soft-cap (planet XP unaffected)."""
    if not schema_ready(conn):
        return {"granted": False, "reason": "unavailable", "amount": 0}
    want = max(0, int(amount or 0))
    if want <= 0:
        return {"granted": False, "reason": "zero", "amount": 0}

    ts = float(now if now is not None else time.time())
    season = get_active_season(conn, now=ts)
    if not season:
        return {"granted": False, "reason": "no_season", "amount": 0}
    if ts < float(season["starts_at"]) or (season["ends_at"] and ts > float(season["ends_at"])):
        return {"granted": False, "reason": "season_inactive", "amount": 0}

    sid = int(season["id"])
    pid = int(player_id)
    period = daily_period_key(ts)
    _ensure_player_row(pid, sid, conn=conn, now=ts)

    already = _drip_granted_today(pid, sid, period, conn=conn)
    remaining = max(0, PASSIVE_DRIP_DAILY_CAP - already)
    grant = min(want, remaining)
    if grant <= 0:
        return {
            "granted": False,
            "reason": "daily_drip_cap",
            "amount": 0,
            "daily_cap": PASSIVE_DRIP_DAILY_CAP,
            "daily_granted": already,
        }

    result = credit_xp(pid, grant, conn=conn, now=ts)
    if not result.get("granted"):
        return {**result, "amount": 0}

    conn.execute(
        """
        INSERT INTO battle_pass_ops_progress (
            player_id, season_id, period_key, op_key,
            progress, target, xp_reward, claimed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)
        ON CONFLICT(player_id, season_id, period_key, op_key) DO UPDATE SET
            progress = battle_pass_ops_progress.progress + excluded.progress,
            updated_at = excluded.updated_at;
        """,
        (pid, sid, period, PASSIVE_DRIP_OP_KEY, grant, PASSIVE_DRIP_DAILY_CAP, ts),
    )
    return {
        "granted": True,
        "reason": "ok",
        "amount": grant,
        "daily_cap": PASSIVE_DRIP_DAILY_CAP,
        "daily_granted": already + grant,
        "xp": result.get("xp"),
        "level": result.get("level"),
    }


def apply_op_progress(
    player_id: int,
    source_key: str,
    *,
    conn,
    amount: int = 1,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Increment Season Ops counters that match the activity source.

    Returns ``completed`` op_keys that newly reached their target (claimable XP).
    """
    if not schema_ready(conn):
        return {"updated": False, "reason": "unavailable", "ops": [], "completed": []}
    src = str(source_key or "").strip()
    delta = max(0, int(amount or 0))
    if not src or delta <= 0:
        return {"updated": False, "reason": "noop", "ops": [], "completed": []}

    ts = float(now if now is not None else time.time())
    season = get_active_season(conn, now=ts)
    if not season:
        return {"updated": False, "reason": "no_season", "ops": [], "completed": []}
    sid = int(season["id"])
    pid = int(player_id)
    _ensure_player_row(pid, sid, conn=conn, now=ts)
    ensure_ops_for_period(pid, sid, conn=conn, now=ts)

    touched: List[str] = []
    completed: List[str] = []
    for op_key, meta in OPS_CATALOG.items():
        sources = meta.get("sources") or frozenset()
        if src not in sources:
            continue
        period = _ops_period_key(str(meta["cadence"]), ts)
        row = _get_op_row(pid, sid, period, op_key, conn=conn)
        if not row:
            continue
        if row.get("claimed_at"):
            continue
        target = int(row["target"] or meta["target"])
        prev = int(row["progress"] or 0)
        new_prog = min(target, prev + delta)
        if new_prog == prev:
            continue
        conn.execute(
            """
            UPDATE battle_pass_ops_progress
            SET progress = ?, updated_at = ?
            WHERE player_id = ? AND season_id = ? AND period_key = ? AND op_key = ?;
            """,
            (new_prog, ts, pid, sid, period, op_key),
        )
        touched.append(op_key)
        if prev < target <= new_prog:
            completed.append(op_key)

    return {
        "updated": bool(touched),
        "ops": touched,
        "completed": completed,
        "reason": "ok" if touched else "none",
    }


def claim_op(
    player_id: int,
    op_key: str,
    *,
    conn,
    period_key: Optional[str] = None,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Claim XP for a completed Season Op.

    Always claims the current server period for the op cadence.
    Client ``period_key`` is ignored (stale DOM after UTC midnight).
    """
    if not schema_ready(conn):
        return False, "battle_pass_unavailable", None
    key = str(op_key or "").strip()
    meta = OPS_CATALOG.get(key)
    if not meta or key.startswith("_"):
        return False, "unknown_op", None

    ts = float(now if now is not None else time.time())
    season = get_active_season(conn, now=ts)
    if not season:
        return False, "no_season", None
    sid = int(season["id"])
    pid = int(player_id)
    _ensure_player_row(pid, sid, conn=conn, now=ts)
    ensure_ops_for_period(pid, sid, conn=conn, now=ts)

    # Server owns the period; ignore client period_key (UTC rollover safety).
    _ = period_key
    period = _ops_period_key(str(meta["cadence"]), ts)
    row = _get_op_row(pid, sid, period, key, conn=conn)
    if not row:
        return False, "op_missing", None
    if row.get("claimed_at"):
        return False, "already_claimed", None
    if int(row["progress"] or 0) < int(row["target"] or meta["target"]):
        return False, "incomplete", None

    xp_reward = int(row["xp_reward"] or meta["xp_reward"])
    credited = credit_xp(pid, xp_reward, conn=conn, now=ts)
    if not credited.get("granted"):
        return False, str(credited.get("reason") or "credit_failed"), None

    conn.execute(
        """
        UPDATE battle_pass_ops_progress
        SET claimed_at = ?, updated_at = ?
        WHERE player_id = ? AND season_id = ? AND period_key = ? AND op_key = ?;
        """,
        (ts, ts, pid, sid, period, key),
    )
    state = serialize_for_client(pid, conn=conn, now=ts, include_tracks=True)
    return True, "ok", {
        "op_key": key,
        "period_key": period,
        "xp_reward": xp_reward,
        "xp": credited.get("xp"),
        "level": credited.get("level"),
        "battle_pass": state,
    }


def _serialize_op_row(row: Mapping[str, Any], meta: Mapping[str, Any]) -> Dict[str, Any]:
    progress = int(row.get("progress") or 0)
    target = int(row.get("target") or meta.get("target") or 1)
    claimed = row.get("claimed_at") is not None
    complete = progress >= target
    return {
        "op_key": str(row.get("op_key")),
        "period_key": str(row.get("period_key")),
        "cadence": str(meta.get("cadence") or "daily"),
        "title_key": str(meta.get("title_key") or ""),
        "hint_key": str(meta.get("hint_key") or ""),
        "icon": str(meta.get("icon") or "◆"),
        "image": str(meta.get("image") or ""),
        "progress": progress,
        "target": target,
        "xp_reward": int(row.get("xp_reward") or meta.get("xp_reward") or 0),
        "complete": complete,
        "claimed": claimed,
        "claimable": bool(complete and not claimed),
    }


def serialize_ops(
    player_id: int,
    season_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    if not ops_schema_ready(conn):
        return {"daily": [], "weekly": [], "drip_cap": PASSIVE_DRIP_DAILY_CAP, "drip_today": 0}
    ts = float(now if now is not None else time.time())
    pid = int(player_id)
    sid = int(season_id)
    ensure_ops_for_period(pid, sid, conn=conn, now=ts)
    daily_key = daily_period_key(ts)
    weekly_key = weekly_period_key(ts)
    drip_today = _drip_granted_today(pid, sid, daily_key, conn=conn)

    daily: List[Dict[str, Any]] = []
    for op_key in DAILY_OP_KEYS:
        meta = OPS_CATALOG[op_key]
        row = _get_op_row(pid, sid, daily_key, op_key, conn=conn)
        if row:
            daily.append(_serialize_op_row(row, meta))

    weekly: List[Dict[str, Any]] = []
    for op_key in WEEKLY_OP_KEYS:
        meta = OPS_CATALOG[op_key]
        row = _get_op_row(pid, sid, weekly_key, op_key, conn=conn)
        if row:
            weekly.append(_serialize_op_row(row, meta))

    return {
        "daily": daily,
        "weekly": weekly,
        "drip_cap": PASSIVE_DRIP_DAILY_CAP,
        "drip_today": drip_today,
        "daily_period_key": daily_key,
        "weekly_period_key": weekly_key,
    }


def credit_xp(
    player_id: int,
    amount: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Credit battle-pass XP for the active season. Idempotent caller responsibility."""
    if not schema_ready(conn):
        return {"granted": False, "reason": "unavailable"}
    amt = max(0, int(amount or 0))
    if amt <= 0:
        return {"granted": False, "reason": "zero"}
    ts = float(now if now is not None else time.time())
    season = get_active_season(conn, now=ts)
    if not season:
        return {"granted": False, "reason": "no_season"}
    if ts < float(season["starts_at"]) or (season["ends_at"] and ts > float(season["ends_at"])):
        return {"granted": False, "reason": "season_inactive"}

    progress = _ensure_player_row(int(player_id), int(season["id"]), conn=conn, now=ts)
    new_xp = int(progress["xp"]) + amt
    new_level = _level_from_xp(new_xp, int(season["xp_per_level"]), int(season["max_level"]))
    conn.execute(
        """
        UPDATE player_battle_pass
        SET xp = ?, level = ?, updated_at = ?
        WHERE player_id = ? AND season_id = ?;
        """,
        (new_xp, new_level, ts, int(player_id), int(season["id"])),
    )
    return {
        "granted": True,
        "amount": amt,
        "xp": new_xp,
        "level": new_level,
        "season_id": int(season["id"]),
    }


def unlock_premium(
    player_id: int,
    *,
    conn,
    season_id: Optional[int] = None,
    source: str = "admin",
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "battle_pass_unavailable", None
    ts = float(now if now is not None else time.time())
    season = get_active_season(conn, now=ts) if season_id is None else None
    sid = int(season_id) if season_id is not None else (int(season["id"]) if season else 0)
    if sid <= 0:
        return False, "no_season", None

    ok, reason, ent = grant_entitlement(
        int(player_id),
        KIND_BATTLE_PASS_PREMIUM,
        conn=conn,
        season_id=sid,
        source=source,
        now=ts,
    )
    if not ok:
        return False, reason, None

    progress = _ensure_player_row(int(player_id), sid, conn=conn, now=ts)
    conn.execute(
        """
        UPDATE player_battle_pass
        SET premium_unlocked = 1, premium_unlocked_at = ?, updated_at = ?
        WHERE player_id = ? AND season_id = ?;
        """,
        (ts, ts, int(player_id), sid),
    )
    return True, "ok", {
        "player_id": int(player_id),
        "season_id": sid,
        "premium_unlocked": True,
        "entitlement": ent,
        "level": int(progress["level"]),
    }


def _load_level_reward(season_id: int, level: int, track: str, *, conn) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT free_reward_json, premium_reward_json
        FROM battle_pass_levels
        WHERE season_id = ? AND level = ?
        LIMIT 1;
        """,
        (int(season_id), int(level)),
    ).fetchone()
    if not row:
        return None
    raw = row["premium_reward_json"] if track == TRACK_PREMIUM else row["free_reward_json"]
    return _json_loads(raw)


def _reward_preview(payload: Mapping[str, Any]) -> Dict[str, Any]:
    items_out: List[Dict[str, Any]] = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("item_key") or "").strip()
        amount = max(0, int(raw.get("amount") or 0))
        if not key or amount <= 0:
            continue
        spec = item_catalog_entry(key) or {}
        items_out.append(
            {
                "item_key": key,
                "amount": amount,
                "name_key": spec.get("name_key") or key,
                "icon": spec.get("icon") or "",
                "rarity": spec.get("rarity") or "common",
                "image": spec.get("image") or "",
            }
        )
    return {
        "items": items_out,
        "timekeeper_sec": max(0, int(payload.get("timekeeper_sec") or 0)),
        "themes": [
            str(t).strip().lower()
            for t in (payload.get("themes") or [])
            if str(t).strip()
        ],
        "badges": [
            str(b).strip().lower()
            for b in (payload.get("badges") or [])
            if str(b).strip()
        ],
        "auras": [
            str(a).strip().lower()
            for a in (payload.get("auras") or [])
            if str(a).strip()
        ],
        "title_flairs": [
            str(f).strip().lower()
            for f in (payload.get("title_flairs") or [])
            if str(f).strip()
        ],
    }


def _grant_bundle(
    player_id: int,
    reward: Mapping[str, Any],
    *,
    conn,
    source: str,
) -> Tuple[bool, List[str]]:
    if not inventory_schema_ready(conn):
        return False, []
    granted: List[str] = []
    for raw in reward.get("items") or []:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("item_key") or "").strip()
        amount = max(0, int(raw.get("amount") or 0))
        if not key or amount <= 0:
            continue
        if not is_known_item_key(key):
            return False, granted
        ok = grant_inventory_item(
            int(player_id),
            key,
            amount,
            conn=conn,
            metadata={"source": source, "kind": "battle_pass"},
        )
        if not ok:
            return False, granted
        granted.append(key)
    tk_sec = max(0, int(reward.get("timekeeper_sec") or 0))
    if tk_sec > 0:
        from .timekeeper import credit, schema_ready as tk_ready

        if tk_ready(conn):
            credit(int(player_id), tk_sec, source, conn=conn)
            granted.append(f"timekeeper:{tk_sec}")

    from .playercard import unlock_aura, unlock_badge, unlock_theme, unlock_title_flair

    for theme_key in reward.get("themes") or []:
        tok, _treason = unlock_theme(
            int(player_id), str(theme_key), conn=conn, source=source
        )
        if not tok:
            return False, granted
        granted.append(f"theme:{theme_key}")
    for badge_key in reward.get("badges") or []:
        bok, _breason = unlock_badge(int(player_id), str(badge_key), conn=conn)
        if not bok:
            return False, granted
        granted.append(f"badge:{badge_key}")
    for aura_key in reward.get("auras") or []:
        aok, _areason = unlock_aura(
            int(player_id), str(aura_key), conn=conn, source=source
        )
        if not aok:
            return False, granted
        granted.append(f"aura:{aura_key}")
    for flair_key in reward.get("title_flairs") or []:
        fok, _freason = unlock_title_flair(
            int(player_id), str(flair_key), conn=conn, source=source
        )
        if not fok:
            return False, granted
        granted.append(f"title_flair:{flair_key}")
    return True, granted


def _already_claimed(player_id: int, season_id: int, level: int, track: str, *, conn) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM battle_pass_claims
        WHERE player_id = ? AND season_id = ? AND level = ? AND track = ?
        LIMIT 1;
        """,
        (int(player_id), int(season_id), int(level), str(track)),
    ).fetchone()
    return bool(row)


def claim_battle_pass_reward(
    player_id: int,
    level: int,
    track: str,
    *,
    conn,
    now: Optional[float] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    if not schema_ready(conn):
        return False, "battle_pass_unavailable", None
    pid = int(player_id)
    lv = int(level)
    tr = str(track or "").strip().lower()
    if pid <= 0 or lv <= 0 or tr not in (TRACK_FREE, TRACK_PREMIUM):
        return False, "invalid_claim", None

    ts = float(now if now is not None else time.time())
    season = get_active_season(conn, now=ts)
    if not season:
        return False, "no_season", None
    sid = int(season["id"])
    if lv > int(season["max_level"]):
        return False, "invalid_level", None

    progress = _ensure_player_row(pid, sid, conn=conn, now=ts)
    if lv > int(progress["level"]):
        return False, "level_not_reached", None
    if tr == TRACK_PREMIUM and not progress["premium_unlocked"]:
        return False, "premium_required", None
    if _already_claimed(pid, sid, lv, tr, conn=conn):
        return False, "already_claimed", None

    reward = _load_level_reward(sid, lv, tr, conn=conn)
    if not reward:
        return False, "reward_missing", None

    source = f"battle_pass:{sid}:L{lv}:{tr}"
    ok, granted = _grant_bundle(pid, reward, conn=conn, source=source)
    if not ok:
        return False, "grant_failed", None

    conn.execute(
        """
        INSERT INTO battle_pass_claims (
            player_id, season_id, level, track, reward_json, claimed_at
        ) VALUES (?, ?, ?, ?, ?, ?);
        """,
        (pid, sid, lv, tr, _json_dumps({**reward, "granted": granted}), ts),
    )
    state = serialize_for_client(pid, conn=conn, now=ts, include_tracks=True)
    return True, "ok", {
        "level": lv,
        "track": tr,
        "reward": _reward_preview(reward),
        "granted": granted,
        "battle_pass": state,
    }


def serialize_for_client(
    player_id: int,
    *,
    conn,
    now: Optional[float] = None,
    include_tracks: bool = False,
) -> Dict[str, Any]:
    if not schema_ready(conn):
        return {"ready": False}

    ts = float(now if now is not None else time.time())
    season = get_active_season(conn, now=ts)
    if not season:
        return {"ready": False, "reason": "no_season"}

    progress = _ensure_player_row(int(player_id), int(season["id"]), conn=conn, now=ts)
    xp_per = int(season["xp_per_level"])
    xp_into = int(progress["xp"]) % xp_per if xp_per > 0 else 0
    if int(progress["level"]) >= int(season["max_level"]):
        xp_into = xp_per

    claimed = {
        (int(r["level"]), str(r["track"]))
        for r in conn.execute(
            """
            SELECT level, track FROM battle_pass_claims
            WHERE player_id = ? AND season_id = ?;
            """,
            (int(player_id), int(season["id"])),
        ).fetchall()
    }

    claimable = 0
    for level in range(1, int(progress["level"]) + 1):
        if (level, TRACK_FREE) not in claimed:
            claimable += 1
        if progress["premium_unlocked"] and (level, TRACK_PREMIUM) not in claimed:
            claimable += 1

    ops = serialize_ops(int(player_id), int(season["id"]), conn=conn, now=ts)
    ops_claimable = 0
    for op in list(ops.get("daily") or []) + list(ops.get("weekly") or []):
        if op.get("claimable"):
            ops_claimable += 1
            claimable += 1

    out: Dict[str, Any] = {
        "ready": True,
        "season": season,
        "xp": int(progress["xp"]),
        "level": int(progress["level"]),
        "xp_into_level": xp_into,
        "xp_per_level": xp_per,
        "premium_unlocked": bool(progress["premium_unlocked"]),
        "claimable_count": claimable,
        "ops_claimable_count": ops_claimable,
        "ops": ops,
    }

    if include_tracks:
        levels_out: List[Dict[str, Any]] = []
        rows = conn.execute(
            """
            SELECT level, free_reward_json, premium_reward_json
            FROM battle_pass_levels
            WHERE season_id = ?
            ORDER BY level ASC;
            """,
            (int(season["id"]),),
        ).fetchall()
        for row in rows:
            lv = int(row["level"])
            free_r = _json_loads(row["free_reward_json"])
            prem_r = _json_loads(row["premium_reward_json"])
            reached = lv <= int(progress["level"])
            free_claimed = (lv, TRACK_FREE) in claimed
            prem_claimed = (lv, TRACK_PREMIUM) in claimed
            levels_out.append(
                {
                    "level": lv,
                    "reached": reached,
                    "free": {
                        **_reward_preview(free_r),
                        "claimed": free_claimed,
                        "claimable": reached and not free_claimed,
                    },
                    "premium": {
                        **_reward_preview(prem_r),
                        "claimed": prem_claimed,
                        "claimable": bool(
                            progress["premium_unlocked"] and reached and not prem_claimed
                        ),
                        "locked": not progress["premium_unlocked"],
                    },
                }
            )
        out["levels"] = levels_out
    return out
