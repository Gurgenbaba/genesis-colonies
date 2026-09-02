"""
Server Events — timed global LiveOps bonuses + recurring schedule materializer.

Owner for admin CRUD, preset catalog, schedule rules, and active factor reads.
Gameplay hooks:
- production_formula.production_context_from_resolver → event_modifier
- fleet.expedition_stay_seconds → hold duration mult
- shop.serialize_cart / create_pending_order → shop_discount_bps
- EffectResolver.get_modifiers → build/research_time_speed
- asteroids.build_schedule_info → asteroid_spawn_mult
- world_boss.build_schedule_info → world_boss_spawn_mult
- inactive_autoplay._ensure_resource_floor → inactive_farm_mult
- world_boss.spawn_world_boss via apply_preset / schedule actions (no parallel spawn path)
- fleet_worker post-maint → maybe_tick_schedules (INSERT-only materialize)
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import db, table_exists
from .i18n import get_locale_dict, tr

KIND_PRODUCTION_MULT = "production_mult"
KIND_EXPEDITION_HOLD_MULT = "expedition_hold_mult"
KIND_SHOP_DISCOUNT_BPS = "shop_discount_bps"
KIND_BUILD_TIME_SPEED = "build_time_speed"
KIND_RESEARCH_TIME_SPEED = "research_time_speed"
KIND_ASTEROID_SPAWN_MULT = "asteroid_spawn_mult"
KIND_WORLD_BOSS_SPAWN_MULT = "world_boss_spawn_mult"
KIND_INACTIVE_FARM_MULT = "inactive_farm_mult"

EFFECT_KINDS = frozenset(
    {
        KIND_PRODUCTION_MULT,
        KIND_EXPEDITION_HOLD_MULT,
        KIND_SHOP_DISCOUNT_BPS,
        KIND_BUILD_TIME_SPEED,
        KIND_RESEARCH_TIME_SPEED,
        KIND_ASTEROID_SPAWN_MULT,
        KIND_WORLD_BOSS_SPAWN_MULT,
        KIND_INACTIVE_FARM_MULT,
    }
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")

SHOP_DISCOUNT_BPS_MAX = 9000
SCHEDULE_LOOKAHEAD_SEC = 6 * 3600
SCHEDULE_TICK_THROTTLE_SEC = 60.0
SCHEDULE_RUNTIME_KEY = "liveops_schedule_last_tick"
WB_SPAWN_COOLDOWN_FLOOR_SEC = 30 * 60
RRULE_WEEKLY = "weekly"
RRULE_DAILY = "daily"
RRULE_ONCE = "once"

# Short process cache so resource ticks / fleet previews do not re-query every call.
_FACTOR_CACHE: Tuple[float, Dict[str, float]] = (0.0, {})
_FACTOR_CACHE_TTL = 3.0

# ---------------------------------------------------------------------------
# Preset catalog (server truth — Admin UI applies via API)
# ---------------------------------------------------------------------------

DURATION_UNTIL_SUNDAY_2000 = "until_sunday_2000"
DURATION_24H = "24h"
DURATION_48H = "48h"

EVENT_PRESETS: Dict[str, Dict[str, Any]] = {
    "weekend_prod_expo": {
        "id": "weekend_prod_expo",
        "title_key": "server_event_preset_weekend_prod_expo",
        "slug_prefix": "weekend-prod-expo",
        "duration": DURATION_UNTIL_SUNDAY_2000,
        "effects": [
            {"kind": KIND_PRODUCTION_MULT, "mult": 2.0},
            {"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75},
        ],
        "actions": [],
    },
    "double_production_24h": {
        "id": "double_production_24h",
        "title_key": "server_event_preset_double_production_24h",
        "slug_prefix": "double-production",
        "duration": DURATION_24H,
        "effects": [{"kind": KIND_PRODUCTION_MULT, "mult": 2.0}],
        "actions": [],
    },
    "expedition_rush_48h": {
        "id": "expedition_rush_48h",
        "title_key": "server_event_preset_expedition_rush_48h",
        "slug_prefix": "expedition-rush",
        "duration": DURATION_48H,
        "effects": [{"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.5}],
        "actions": [],
    },
    "shop_sale_20_48h": {
        "id": "shop_sale_20_48h",
        "title_key": "server_event_preset_shop_sale_20_48h",
        "slug_prefix": "shop-sale-20",
        "duration": DURATION_48H,
        "effects": [{"kind": KIND_SHOP_DISCOUNT_BPS, "bps": 2000}],
        "actions": [],
    },
    "build_research_rush_24h": {
        "id": "build_research_rush_24h",
        "title_key": "server_event_preset_build_research_rush_24h",
        "slug_prefix": "build-research-rush",
        "duration": DURATION_24H,
        "effects": [
            {"kind": KIND_BUILD_TIME_SPEED, "mult": 1.25},
            {"kind": KIND_RESEARCH_TIME_SPEED, "mult": 1.25},
        ],
        "actions": [],
    },
    "world_boss_leviathan": {
        "id": "world_boss_leviathan",
        "title_key": "server_event_preset_world_boss_leviathan",
        "slug_prefix": "",
        "duration": None,
        "effects": [],
        "actions": [
            {
                "type": "spawn_world_boss",
                "boss_key": "ancient_leviathan",
                "announce": True,
                "force": False,
            }
        ],
    },
    "mega_weekend": {
        "id": "mega_weekend",
        "title_key": "server_event_preset_mega_weekend",
        "slug_prefix": "mega-weekend",
        "duration": DURATION_UNTIL_SUNDAY_2000,
        "effects": [
            {"kind": KIND_PRODUCTION_MULT, "mult": 2.0},
            {"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75},
            {"kind": KIND_SHOP_DISCOUNT_BPS, "bps": 1500},
        ],
        "actions": [
            {
                "type": "spawn_world_boss",
                "boss_key": "ancient_leviathan",
                "announce": True,
                "force": False,
            }
        ],
    },
    "asteroid_storm_48h": {
        "id": "asteroid_storm_48h",
        "title_key": "server_event_preset_asteroid_storm_48h",
        "slug_prefix": "asteroid-storm",
        "duration": DURATION_48H,
        "effects": [{"kind": KIND_ASTEROID_SPAWN_MULT, "mult": 2.0}],
        "actions": [],
    },
    "boss_hunt_24h": {
        "id": "boss_hunt_24h",
        "title_key": "server_event_preset_boss_hunt_24h",
        "slug_prefix": "boss-hunt",
        "duration": DURATION_24H,
        "effects": [{"kind": KIND_WORLD_BOSS_SPAWN_MULT, "mult": 2.0}],
        "actions": [],
    },
    "inactive_farm_weekend": {
        "id": "inactive_farm_weekend",
        "title_key": "server_event_preset_inactive_farm_weekend",
        "slug_prefix": "inactive-farm",
        "duration": DURATION_UNTIL_SUNDAY_2000,
        "effects": [{"kind": KIND_INACTIVE_FARM_MULT, "mult": 3.0}],
        "actions": [],
    },
    "chaos_weekend": {
        "id": "chaos_weekend",
        "title_key": "server_event_preset_chaos_weekend",
        "slug_prefix": "chaos-weekend",
        "duration": DURATION_UNTIL_SUNDAY_2000,
        "effects": [
            {"kind": KIND_PRODUCTION_MULT, "mult": 2.0},
            {"kind": KIND_EXPEDITION_HOLD_MULT, "mult": 0.75},
            {"kind": KIND_SHOP_DISCOUNT_BPS, "bps": 1500},
            {"kind": KIND_ASTEROID_SPAWN_MULT, "mult": 2.0},
            {"kind": KIND_WORLD_BOSS_SPAWN_MULT, "mult": 2.0},
            {"kind": KIND_INACTIVE_FARM_MULT, "mult": 3.0},
        ],
        "actions": [],
    },
}


def schema_ready(conn) -> bool:
    return bool(table_exists(conn, "server_events"))


def schedule_schema_ready(conn) -> bool:
    return bool(table_exists(conn, "server_event_schedules"))


def clear_factor_cache() -> None:
    global _FACTOR_CACHE
    _FACTOR_CACHE = (0.0, {})


def _row_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    try:
        return {k: row[k] for k in row.keys()}
    except Exception:
        return {}


def _parse_effect_item(item: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    kind = str(item.get("kind") or "").strip()
    if kind not in EFFECT_KINDS:
        return None
    if kind == KIND_SHOP_DISCOUNT_BPS:
        try:
            bps = int(item.get("bps"))
        except (TypeError, ValueError):
            return None
        if bps < 1 or bps > SHOP_DISCOUNT_BPS_MAX:
            return None
        return {"kind": kind, "bps": bps}
    try:
        mult = float(item.get("mult"))
    except (TypeError, ValueError):
        return None
    if mult <= 0:
        return None
    return {"kind": kind, "mult": mult}


def _parse_effects(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, str):
        try:
            data = json.loads(raw or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    else:
        return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, Mapping):
            continue
        parsed = _parse_effect_item(item)
        if parsed:
            out.append(parsed)
    return out


def validate_effects(raw: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Validate admin payload; reject unknown kinds or bad values."""
    if raw is None:
        return [], None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return [], "invalid_effects_json"
    if not isinstance(raw, list):
        return [], "effects_must_be_list"
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            return [], "invalid_effect_entry"
        kind = str(item.get("kind") or "").strip()
        if kind not in EFFECT_KINDS:
            return [], f"unknown_effect_kind:{kind or 'empty'}"
        if kind == KIND_SHOP_DISCOUNT_BPS:
            try:
                bps = int(item.get("bps"))
            except (TypeError, ValueError):
                return [], "invalid_effect_bps"
            if bps < 1:
                return [], "effect_bps_must_be_positive"
            if bps > SHOP_DISCOUNT_BPS_MAX:
                return [], "effect_bps_too_large"
            out.append({"kind": kind, "bps": bps})
            continue
        try:
            mult = float(item.get("mult"))
        except (TypeError, ValueError):
            return [], "invalid_effect_mult"
        if mult <= 0:
            return [], "effect_mult_must_be_positive"
        if mult > 100:
            return [], "effect_mult_too_large"
        out.append({"kind": kind, "mult": mult})
    return out, None


def _normalize_slug(raw: str) -> str:
    return str(raw or "").strip().lower().replace(" ", "-")


def _preset_fallback_title(preset: Mapping[str, Any]) -> str:
    """Stable English DB/admin fallback; player rendering uses title_key."""
    title_key = str(preset.get("title_key") or "").strip()
    if title_key:
        text = get_locale_dict("en").get(title_key)
        if text:
            return str(text)
    return str(preset.get("id") or "server_event")


def _preset_title_key_for_slug(slug: str) -> str:
    slug_n = _normalize_slug(slug)
    if not slug_n:
        return ""
    for preset in EVENT_PRESETS.values():
        prefix = _normalize_slug(str(preset.get("slug_prefix") or ""))
        title_key = str(preset.get("title_key") or "").strip()
        if not prefix or not title_key:
            continue
        if slug_n == prefix or slug_n.startswith(f"{prefix}-"):
            return title_key
    return ""


def _localized_event_title(event: Mapping[str, Any], *, locale: Optional[str] = None) -> str:
    title = str(event.get("title") or event.get("slug") or "")
    title_key = str(event.get("title_key") or _preset_title_key_for_slug(str(event.get("slug") or "")))
    if not title_key:
        return title
    return tr(title_key, title, locale=locale)


def _serialize_row(row: Mapping[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
    ts = float(now if now is not None else time.time())
    effects = _parse_effects(row.get("effects_json"))
    starts = int(row.get("starts_at") or 0)
    ends = int(row.get("ends_at") or 0)
    enabled = bool(int(row.get("enabled") or 0))
    if not enabled:
        status = "disabled"
    elif ts < starts:
        status = "scheduled"
    elif ts > ends:
        status = "ended"
    else:
        status = "active"
    return {
        "id": int(row["id"]),
        "slug": str(row.get("slug") or ""),
        "title": str(row.get("title") or ""),
        "title_key": _preset_title_key_for_slug(str(row.get("slug") or "")),
        "starts_at": starts,
        "ends_at": ends,
        "enabled": enabled,
        "effects": effects,
        "status": status,
        "created_at": int(row.get("created_at") or 0),
        "updated_at": int(row.get("updated_at") or 0),
        "created_by": int(row["created_by"]) if row.get("created_by") is not None else None,
    }


def list_events(*, conn=None, limit: int = 100) -> List[Dict[str, Any]]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schema_ready(conn):
            return []
        rows = conn.execute(
            """
            SELECT id, slug, title, starts_at, ends_at, enabled, effects_json,
                   created_at, updated_at, created_by
            FROM server_events
            ORDER BY starts_at DESC, id DESC
            LIMIT ?;
            """,
            (max(1, min(500, int(limit))),),
        ).fetchall()
        now = time.time()
        return [_serialize_row(_row_dict(r), now=now) for r in rows]
    finally:
        if owns:
            conn.close()


def get_event(event_id: int, *, conn=None) -> Optional[Dict[str, Any]]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schema_ready(conn):
            return None
        row = conn.execute(
            """
            SELECT id, slug, title, starts_at, ends_at, enabled, effects_json,
                   created_at, updated_at, created_by
            FROM server_events WHERE id = ?;
            """,
            (int(event_id),),
        ).fetchone()
        if not row:
            return None
        return _serialize_row(_row_dict(row))
    finally:
        if owns:
            conn.close()


def create_event(
    *,
    slug: str,
    title: str,
    starts_at: int,
    ends_at: int,
    effects: Any,
    enabled: bool = True,
    created_by: Optional[int] = None,
    conn=None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    slug_n = _normalize_slug(slug)
    title_n = str(title or "").strip()
    if not _SLUG_RE.match(slug_n):
        return None, "invalid_slug"
    if not title_n:
        return None, "title_required"
    starts = int(starts_at)
    ends = int(ends_at)
    if ends <= starts:
        return None, "ends_before_starts"
    effects_clean, err = validate_effects(effects)
    if err:
        return None, err

    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schema_ready(conn):
            return None, "schema_unavailable"
        now = int(time.time())
        try:
            cur = conn.execute(
                """
                INSERT INTO server_events (
                    slug, title, starts_at, ends_at, enabled, effects_json,
                    created_at, updated_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    slug_n,
                    title_n,
                    starts,
                    ends,
                    1 if enabled else 0,
                    json.dumps(effects_clean),
                    now,
                    now,
                    int(created_by) if created_by is not None else None,
                ),
            )
        except Exception:
            return None, "slug_taken"
        conn.commit()
        clear_factor_cache()
        return get_event(int(cur.lastrowid), conn=conn), None
    finally:
        if owns:
            conn.close()


def update_event(
    event_id: int,
    *,
    slug: Optional[str] = None,
    title: Optional[str] = None,
    starts_at: Optional[int] = None,
    ends_at: Optional[int] = None,
    effects: Any = None,
    enabled: Optional[bool] = None,
    conn=None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schema_ready(conn):
            return None, "schema_unavailable"
        existing = get_event(int(event_id), conn=conn)
        if not existing:
            return None, "not_found"

        slug_n = existing["slug"]
        if slug is not None:
            slug_n = _normalize_slug(slug)
            if not _SLUG_RE.match(slug_n):
                return None, "invalid_slug"

        title_n = existing["title"]
        if title is not None:
            title_n = str(title or "").strip()
            if not title_n:
                return None, "title_required"

        starts = int(existing["starts_at"] if starts_at is None else starts_at)
        ends = int(existing["ends_at"] if ends_at is None else ends_at)
        if ends <= starts:
            return None, "ends_before_starts"

        effects_clean = list(existing.get("effects") or [])
        if effects is not None:
            effects_clean, err = validate_effects(effects)
            if err:
                return None, err

        en = bool(existing["enabled"]) if enabled is None else bool(enabled)
        now = int(time.time())
        try:
            conn.execute(
                """
                UPDATE server_events
                SET slug = ?, title = ?, starts_at = ?, ends_at = ?, enabled = ?,
                    effects_json = ?, updated_at = ?
                WHERE id = ?;
                """,
                (
                    slug_n,
                    title_n,
                    starts,
                    ends,
                    1 if en else 0,
                    json.dumps(effects_clean),
                    now,
                    int(event_id),
                ),
            )
        except Exception:
            return None, "slug_taken"
        conn.commit()
        clear_factor_cache()
        return get_event(int(event_id), conn=conn), None
    finally:
        if owns:
            conn.close()


def delete_event(event_id: int, *, conn=None) -> Tuple[bool, Optional[str]]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schema_ready(conn):
            return False, "schema_unavailable"
        cur = conn.execute("DELETE FROM server_events WHERE id = ?;", (int(event_id),))
        conn.commit()
        clear_factor_cache()
        if int(cur.rowcount or 0) <= 0:
            return False, "not_found"
        return True, None
    finally:
        if owns:
            conn.close()


def list_active_events(*, now: Optional[float] = None, conn=None) -> List[Dict[str, Any]]:
    ts = float(now if now is not None else time.time())
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schema_ready(conn):
            return []
        rows = conn.execute(
            """
            SELECT id, slug, title, starts_at, ends_at, enabled, effects_json,
                   created_at, updated_at, created_by
            FROM server_events
            WHERE enabled = 1 AND starts_at <= ? AND ends_at >= ?
            ORDER BY starts_at ASC, id ASC;
            """,
            (int(ts), int(ts)),
        ).fetchall()
        return [_serialize_row(_row_dict(r), now=ts) for r in rows]
    finally:
        if owns:
            conn.close()


def serialize_active_events(*, now: Optional[float] = None, conn=None) -> Dict[str, Any]:
    """Player-facing active events + combined factors."""
    active = list_active_events(now=now, conn=conn)
    factors = _combine_factors(active)
    return {
        "events": [
            {
                "id": e["id"],
                "slug": e["slug"],
                "title": _localized_event_title(e),
                "title_key": str(e.get("title_key") or ""),
                "starts_at": e["starts_at"],
                "ends_at": e["ends_at"],
                "effects": e["effects"],
            }
            for e in active
        ],
        "production_mult": float(factors.get(KIND_PRODUCTION_MULT, 1.0)),
        "expedition_hold_mult": float(factors.get(KIND_EXPEDITION_HOLD_MULT, 1.0)),
        "shop_discount_bps": int(factors.get(KIND_SHOP_DISCOUNT_BPS, 0.0) or 0),
        "build_time_speed": float(factors.get(KIND_BUILD_TIME_SPEED, 1.0)),
        "research_time_speed": float(factors.get(KIND_RESEARCH_TIME_SPEED, 1.0)),
        "asteroid_spawn_mult": float(factors.get(KIND_ASTEROID_SPAWN_MULT, 1.0)),
        "world_boss_spawn_mult": float(factors.get(KIND_WORLD_BOSS_SPAWN_MULT, 1.0)),
        "inactive_farm_mult": float(factors.get(KIND_INACTIVE_FARM_MULT, 1.0)),
    }


def effect_summary_short(effects: Any, *, locale: Optional[str] = None) -> List[str]:
    """Compact player-facing labels resolved through locale SSOT."""
    out: List[str] = []
    if not isinstance(effects, list):
        return out
    for eff in effects:
        if not isinstance(eff, Mapping):
            continue
        kind = str(eff.get("kind") or "").strip()
        if kind == KIND_SHOP_DISCOUNT_BPS:
            try:
                bps = int(eff.get("bps") or 0)
            except (TypeError, ValueError):
                continue
            if bps > 0:
                pct = int(round(bps / 100.0))
                out.append(tr("server_event_effect_shop_discount", locale=locale, pct=pct))
            continue
        try:
            mult = float(eff.get("mult") or 1.0)
        except (TypeError, ValueError):
            continue
        if kind == KIND_PRODUCTION_MULT and mult > 0:
            pct = int(round((mult - 1.0) * 100))
            if pct != 0:
                value = f"+{pct}" if pct > 0 else str(pct)
                out.append(tr("server_event_effect_production", locale=locale, value=value))
        elif kind == KIND_EXPEDITION_HOLD_MULT and mult > 0:
            pct = int(round((1.0 - mult) * 100))
            if pct != 0:
                value = f"−{pct}" if pct > 0 else f"+{abs(pct)}"
                out.append(tr("server_event_effect_expedition_hold", locale=locale, value=value))
        elif kind == KIND_BUILD_TIME_SPEED and mult > 0:
            pct = int(round((mult - 1.0) * 100))
            if pct != 0:
                value = f"+{pct}" if pct > 0 else str(pct)
                out.append(tr("server_event_effect_build_speed", locale=locale, value=value))
        elif kind == KIND_RESEARCH_TIME_SPEED and mult > 0:
            pct = int(round((mult - 1.0) * 100))
            if pct != 0:
                value = f"+{pct}" if pct > 0 else str(pct)
                out.append(tr("server_event_effect_research_speed", locale=locale, value=value))
        elif kind == KIND_ASTEROID_SPAWN_MULT and mult > 0 and abs(mult - 1.0) > 1e-9:
            out.append(tr("server_event_effect_asteroid_spawn", locale=locale, mult=f"{mult:g}"))
        elif kind == KIND_WORLD_BOSS_SPAWN_MULT and mult > 0 and abs(mult - 1.0) > 1e-9:
            out.append(tr("server_event_effect_world_boss_spawn", locale=locale, mult=f"{mult:g}"))
        elif kind == KIND_INACTIVE_FARM_MULT and mult > 0 and abs(mult - 1.0) > 1e-9:
            out.append(tr("server_event_effect_inactive_farm", locale=locale, mult=f"{mult:g}"))
    return out


def active_events_banner(*, now: Optional[float] = None, conn=None, locale: Optional[str] = None) -> List[Dict[str, Any]]:
    """UI teaser rows for Overview / Login Rewards (active server events only)."""
    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for ev in list_active_events(now=ts, conn=conn):
        ends = int(ev.get("ends_at") or 0)
        effects = ev.get("effects") or []
        has_prod = any(
            str(eff.get("kind") or "") == KIND_PRODUCTION_MULT
            and float(eff.get("mult") or 1.0) > 1.0
            for eff in effects
            if isinstance(eff, Mapping)
        )
        out.append(
            {
                "kind": "server_event",
                "id": int(ev.get("id") or 0),
                "slug": str(ev.get("slug") or ""),
                "title": _localized_event_title(ev, locale=locale),
                "title_key": str(ev.get("title_key") or ""),
                "effects_summary": effect_summary_short(effects, locale=locale),
                "ends_at": ends,
                "remaining_sec": max(0, ends - int(ts)) if ends else 0,
                "href": "login_rewards_view",
                # Production events stay under Ressourcen with res-bar chips.
                "group": "resources" if has_prod else "events",
            }
        )
    return out


def _combine_factors(events: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    prod = 1.0
    hold = 1.0
    shop_bps = 0.0
    build = 1.0
    research = 1.0
    asteroid = 1.0
    world_boss = 1.0
    inactive_farm = 1.0
    for ev in events:
        for eff in ev.get("effects") or []:
            kind = str(eff.get("kind") or "")
            if kind == KIND_SHOP_DISCOUNT_BPS:
                try:
                    bps = float(eff.get("bps") or 0)
                except (TypeError, ValueError):
                    continue
                if bps > 0:
                    shop_bps = max(shop_bps, bps)
                continue
            try:
                mult = float(eff.get("mult") or 1.0)
            except (TypeError, ValueError):
                continue
            if mult <= 0:
                continue
            if kind == KIND_PRODUCTION_MULT:
                prod *= mult
            elif kind == KIND_EXPEDITION_HOLD_MULT:
                hold *= mult
            elif kind == KIND_BUILD_TIME_SPEED:
                build *= mult
            elif kind == KIND_RESEARCH_TIME_SPEED:
                research *= mult
            elif kind == KIND_ASTEROID_SPAWN_MULT:
                asteroid *= mult
            elif kind == KIND_WORLD_BOSS_SPAWN_MULT:
                world_boss *= mult
            elif kind == KIND_INACTIVE_FARM_MULT:
                inactive_farm *= mult
    return {
        KIND_PRODUCTION_MULT: prod,
        KIND_EXPEDITION_HOLD_MULT: hold,
        KIND_SHOP_DISCOUNT_BPS: shop_bps,
        KIND_BUILD_TIME_SPEED: build,
        KIND_RESEARCH_TIME_SPEED: research,
        KIND_ASTEROID_SPAWN_MULT: asteroid,
        KIND_WORLD_BOSS_SPAWN_MULT: world_boss,
        KIND_INACTIVE_FARM_MULT: inactive_farm,
    }


def _cached_active_factors(*, now: Optional[float] = None, conn=None) -> Dict[str, float]:
    global _FACTOR_CACHE
    ts = float(now if now is not None else time.time())
    cached_at, cached = _FACTOR_CACHE
    if cached and abs(ts - cached_at) <= _FACTOR_CACHE_TTL:
        return dict(cached)
    factors = _combine_factors(list_active_events(now=ts, conn=conn))
    _FACTOR_CACHE = (ts, dict(factors))
    return factors


def active_production_mult(*, now: Optional[float] = None, conn=None) -> float:
    return float(_cached_active_factors(now=now, conn=conn).get(KIND_PRODUCTION_MULT, 1.0) or 1.0)


def active_expedition_hold_mult(*, now: Optional[float] = None, conn=None) -> float:
    return float(
        _cached_active_factors(now=now, conn=conn).get(KIND_EXPEDITION_HOLD_MULT, 1.0) or 1.0
    )


def active_shop_discount_bps(*, now: Optional[float] = None, conn=None) -> int:
    raw = _cached_active_factors(now=now, conn=conn).get(KIND_SHOP_DISCOUNT_BPS, 0.0) or 0.0
    return max(0, min(SHOP_DISCOUNT_BPS_MAX, int(raw)))


def active_build_time_speed(*, now: Optional[float] = None, conn=None) -> float:
    return float(_cached_active_factors(now=now, conn=conn).get(KIND_BUILD_TIME_SPEED, 1.0) or 1.0)


def active_research_time_speed(*, now: Optional[float] = None, conn=None) -> float:
    return float(
        _cached_active_factors(now=now, conn=conn).get(KIND_RESEARCH_TIME_SPEED, 1.0) or 1.0
    )


def active_asteroid_spawn_mult(*, now: Optional[float] = None, conn=None) -> float:
    return float(
        _cached_active_factors(now=now, conn=conn).get(KIND_ASTEROID_SPAWN_MULT, 1.0) or 1.0
    )


def active_world_boss_spawn_mult(*, now: Optional[float] = None, conn=None) -> float:
    return float(
        _cached_active_factors(now=now, conn=conn).get(KIND_WORLD_BOSS_SPAWN_MULT, 1.0) or 1.0
    )


def active_inactive_farm_mult(*, now: Optional[float] = None, conn=None) -> float:
    return float(
        _cached_active_factors(now=now, conn=conn).get(KIND_INACTIVE_FARM_MULT, 1.0) or 1.0
    )


def production_hud_contribution(
    *,
    now: Optional[float] = None,
    conn=None,
) -> Optional[Dict[str, Any]]:
    """
    Resource-bar chip contribution for active production_mult events.

    Returns pct (+100 for mult 2.0), remaining_seconds, ends_at — or None.
    """
    ts = float(now if now is not None else time.time())
    active = list_active_events(now=ts, conn=conn)
    prod_events = [
        ev
        for ev in active
        if any(
            str(eff.get("kind") or "") == KIND_PRODUCTION_MULT
            and float(eff.get("mult") or 1.0) > 1.0
            for eff in (ev.get("effects") or [])
        )
    ]
    if not prod_events:
        return None
    mult = 1.0
    ends_at = None
    titles: List[str] = []
    for ev in prod_events:
        titles.append(_localized_event_title(ev))
        end = int(ev.get("ends_at") or 0)
        if ends_at is None or (end > 0 and end < ends_at):
            ends_at = end
        for eff in ev.get("effects") or []:
            if str(eff.get("kind") or "") != KIND_PRODUCTION_MULT:
                continue
            try:
                m = float(eff.get("mult") or 1.0)
            except (TypeError, ValueError):
                continue
            if m > 0:
                mult *= m
    if mult <= 1.0 + 1e-9 or not ends_at or ends_at <= ts:
        return None
    pct = max(0, int(round((mult - 1.0) * 100)))
    if pct <= 0:
        return None
    return {
        "pct": pct,
        "mult": mult,
        "ends_at": float(ends_at),
        "remaining_seconds": max(0, int(ends_at - ts)),
        "titles": [t for t in titles if t],
    }


def effect_kind_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "kind": KIND_PRODUCTION_MULT,
            "label_key": "admin_events_kind_production",
            "default_mult": 2.0,
            "hint": "1.0 = none, 2.0 = +100%",
        },
        {
            "kind": KIND_EXPEDITION_HOLD_MULT,
            "label_key": "admin_events_kind_expo_hold",
            "default_mult": 0.75,
            "hint": "0.75 = -25% hold time",
        },
        {
            "kind": KIND_SHOP_DISCOUNT_BPS,
            "label_key": "admin_events_kind_shop_discount",
            "default_bps": 2000,
            "hint": "2000 = -20% (auto, no promo code)",
        },
        {
            "kind": KIND_BUILD_TIME_SPEED,
            "label_key": "admin_events_kind_build_speed",
            "default_mult": 1.25,
            "hint": "1.25 = +25% build speed",
        },
        {
            "kind": KIND_RESEARCH_TIME_SPEED,
            "label_key": "admin_events_kind_research_speed",
            "default_mult": 1.25,
            "hint": "1.25 = +25% research speed",
        },
        {
            "kind": KIND_ASTEROID_SPAWN_MULT,
            "label_key": "admin_events_kind_asteroid_spawn",
            "default_mult": 2.0,
            "hint": "2.0 = half cooldown / higher cap",
        },
        {
            "kind": KIND_WORLD_BOSS_SPAWN_MULT,
            "label_key": "admin_events_kind_world_boss_spawn",
            "default_mult": 2.0,
            "hint": "2.0 = half inter-spawn cooldown",
        },
        {
            "kind": KIND_INACTIVE_FARM_MULT,
            "label_key": "admin_events_kind_inactive_farm",
            "default_mult": 3.0,
            "hint": "3.0 = 3× inactive soft resource floor",
        },
    ]


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def next_sunday_2000_unix(now: Optional[float] = None, *, tz_offset_minutes: int = 0) -> int:
    """Next local Sunday 20:00 as UTC unix. Offset = minutes east of UTC (JS getTimezoneOffset inverted)."""
    ts = float(now if now is not None else time.time())
    offset = int(tz_offset_minutes)
    # Local wall clock = UTC + offset
    local = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(minutes=offset)
    # weekday: Mon=0 … Sun=6
    days_ahead = (6 - local.weekday()) % 7
    candidate = local.replace(hour=20, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    if candidate <= local:
        candidate = candidate + timedelta(days=7)
    utc = candidate - timedelta(minutes=offset)
    return int(utc.timestamp())


def resolve_preset_window(
    duration: Optional[str],
    *,
    now: Optional[float] = None,
    starts_at: Optional[int] = None,
    ends_at: Optional[int] = None,
    tz_offset_minutes: int = 0,
) -> Tuple[int, int]:
    """Compute starts/ends for a preset duration key."""
    ts = float(now if now is not None else time.time())
    start = int(starts_at) if starts_at is not None else int(ts)
    if ends_at is not None:
        return start, int(ends_at)
    key = str(duration or DURATION_24H)
    if key == DURATION_UNTIL_SUNDAY_2000:
        return start, next_sunday_2000_unix(ts, tz_offset_minutes=tz_offset_minutes)
    if key == DURATION_48H:
        return start, start + 48 * 3600
    # default 24h
    return start, start + 24 * 3600


def list_presets() -> List[Dict[str, Any]]:
    """Admin-facing preset catalog (stable order)."""
    order = [
        "weekend_prod_expo",
        "double_production_24h",
        "expedition_rush_48h",
        "shop_sale_20_48h",
        "build_research_rush_24h",
        "asteroid_storm_48h",
        "boss_hunt_24h",
        "inactive_farm_weekend",
        "chaos_weekend",
        "world_boss_leviathan",
        "mega_weekend",
    ]
    out: List[Dict[str, Any]] = []
    for pid in order:
        preset = EVENT_PRESETS.get(pid)
        if not preset:
            continue
        out.append(
            {
                "id": preset["id"],
                "title": _preset_fallback_title(preset),
                "title_key": str(preset.get("title_key") or ""),
                "slug_prefix": preset.get("slug_prefix") or "",
                "duration": preset.get("duration"),
                "effects": list(preset.get("effects") or []),
                "actions": list(preset.get("actions") or []),
                "has_effects": bool(preset.get("effects")),
                "has_world_boss": any(
                    str(a.get("type") or "") == "spawn_world_boss"
                    for a in (preset.get("actions") or [])
                    if isinstance(a, Mapping)
                ),
            }
        )
    return out


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    key = str(preset_id or "").strip()
    preset = EVENT_PRESETS.get(key)
    if not preset:
        return None
    return dict(preset)


def _unique_slug(prefix: str, *, conn) -> str:
    base = _normalize_slug(prefix) or "liveops-event"
    if not _SLUG_RE.match(base):
        base = "liveops-event"
    candidate = base
    n = 2
    while True:
        row = conn.execute(
            "SELECT 1 FROM server_events WHERE slug = ? LIMIT 1;",
            (candidate,),
        ).fetchone()
        if not row:
            return candidate[:63]
        suffix = f"-{n}"
        candidate = (base[: max(1, 63 - len(suffix))] + suffix)[:63]
        n += 1
        if n > 50:
            candidate = f"{base[:40]}-{int(time.time())}"[:63]
            return candidate


def _dispatch_preset_actions(
    actions: Sequence[Mapping[str, Any]],
    *,
    conn,
    force_world_boss: bool = False,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        atype = str(action.get("type") or "").strip()
        if atype != "spawn_world_boss":
            results.append({"type": atype or "unknown", "ok": False, "error": "unknown_action"})
            continue
        from . import world_boss as wb

        boss_key = str(action.get("boss_key") or "").strip()
        announce = bool(action.get("announce", True))
        force = bool(force_world_boss) or bool(action.get("force", False))
        spawn_res = wb.spawn_world_boss(
            boss_key,
            conn=conn,
            announce=announce,
            force=force,
        )
        ok = bool(spawn_res.get("ok"))
        results.append(
            {
                "type": "spawn_world_boss",
                "ok": ok,
                "boss_key": boss_key,
                "error": None if ok else str(spawn_res.get("error") or "spawn_failed"),
                "event": spawn_res.get("event") if ok else None,
            }
        )
    return results


def apply_preset(
    preset_id: str,
    *,
    created_by: Optional[int] = None,
    starts_at: Optional[int] = None,
    ends_at: Optional[int] = None,
    tz_offset_minutes: int = 0,
    force_world_boss: bool = False,
    enabled: bool = True,
    conn=None,
    now: Optional[float] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Apply a LiveOps preset: create server_event row when effects exist,
    dispatch world_boss.spawn_world_boss for spawn actions.
    """
    preset = get_preset(preset_id)
    if not preset:
        return None, "unknown_preset"

    effects = list(preset.get("effects") or [])
    actions = list(preset.get("actions") or [])
    ts = float(now if now is not None else time.time())

    owns = conn is None
    if owns:
        conn = db()
    try:
        entry = None
        if effects:
            if not schema_ready(conn):
                return None, "schema_unavailable"
            start, end = resolve_preset_window(
                preset.get("duration"),
                now=ts,
                starts_at=starts_at,
                ends_at=ends_at,
                tz_offset_minutes=int(tz_offset_minutes or 0),
            )
            slug = _unique_slug(str(preset.get("slug_prefix") or preset["id"]), conn=conn)
            entry, err = create_event(
                slug=slug,
                title=_preset_fallback_title(preset),
                starts_at=start,
                ends_at=end,
                effects=effects,
                enabled=bool(enabled),
                created_by=created_by,
                conn=conn,
            )
            if err or not entry:
                return None, err or "create_failed"

        action_results = _dispatch_preset_actions(
            actions, conn=conn, force_world_boss=force_world_boss
        )
        # Commit spawn side-effects when we own the connection and create_event
        # already committed; spawn_world_boss typically commits via same conn.
        if owns:
            try:
                conn.commit()
            except Exception:
                pass

        return (
            {
                "preset_id": preset["id"],
                "event": entry,
                "actions": action_results,
            },
            None,
        )
    finally:
        if owns:
            conn.close()


# ---------------------------------------------------------------------------
# Schedule rules (auto-materialize — INSERT only, never mutates active events)
# ---------------------------------------------------------------------------


def _parse_hhmm(raw: str) -> Tuple[int, int]:
    parts = str(raw or "18:00").strip().split(":")
    try:
        hour = max(0, min(23, int(parts[0])))
    except (TypeError, ValueError, IndexError):
        hour = 18
    try:
        minute = max(0, min(59, int(parts[1]))) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        minute = 0
    return hour, minute


def _parse_weekdays(raw: Any) -> List[int]:
    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, str):
        try:
            data = json.loads(raw or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    else:
        return []
    out: List[int] = []
    for item in data:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            out.append(day)
    return sorted(set(out))


def _serialize_schedule_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": str(row.get("name") or ""),
        "preset_id": str(row.get("preset_id") or ""),
        "effects": _parse_effects(row.get("effects_json")),
        "rrule_kind": str(row.get("rrule_kind") or RRULE_WEEKLY),
        "weekdays": _parse_weekdays(row.get("weekdays_json")),
        "local_start_hhmm": str(row.get("local_start_hhmm") or "18:00"),
        "duration_sec": int(row.get("duration_sec") or 0),
        "tz_offset_minutes": int(row.get("tz_offset_minutes") or 0),
        "priority": int(row.get("priority") or 0),
        "enabled": bool(int(row.get("enabled") or 0)),
        "last_materialized_key": str(row.get("last_materialized_key") or ""),
        "created_at": int(row.get("created_at") or 0),
        "updated_at": int(row.get("updated_at") or 0),
        "created_by": int(row["created_by"]) if row.get("created_by") is not None else None,
    }


def list_schedules(*, conn=None, now: Optional[float] = None) -> List[Dict[str, Any]]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schedule_schema_ready(conn):
            return []
        rows = conn.execute(
            """
            SELECT id, name, preset_id, effects_json, rrule_kind, weekdays_json,
                   local_start_hhmm, duration_sec, tz_offset_minutes, priority,
                   enabled, last_materialized_key, created_at, updated_at, created_by
            FROM server_event_schedules
            ORDER BY priority DESC, id ASC;
            """
        ).fetchall()
        ts = float(now if now is not None else time.time())
        out: List[Dict[str, Any]] = []
        for r in rows:
            entry = _serialize_schedule_row(_row_dict(r))
            window = compute_schedule_window(entry, now=ts)
            if window:
                start, end, mat_key = window
                entry["next_window"] = {
                    "starts_at": int(start),
                    "ends_at": int(end),
                    "materialize_key": mat_key,
                    "already_materialized": str(entry.get("last_materialized_key") or "")
                    == mat_key,
                    "in_progress": float(start) <= ts < float(end),
                    "seconds_until_start": max(0, int(start - ts)),
                }
            else:
                entry["next_window"] = None
            out.append(entry)
        return out
    finally:
        if owns:
            conn.close()


def get_schedule(schedule_id: int, *, conn=None) -> Optional[Dict[str, Any]]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schedule_schema_ready(conn):
            return None
        row = conn.execute(
            """
            SELECT id, name, preset_id, effects_json, rrule_kind, weekdays_json,
                   local_start_hhmm, duration_sec, tz_offset_minutes, priority,
                   enabled, last_materialized_key, created_at, updated_at, created_by
            FROM server_event_schedules WHERE id = ?;
            """,
            (int(schedule_id),),
        ).fetchone()
        if not row:
            return None
        return _serialize_schedule_row(_row_dict(row))
    finally:
        if owns:
            conn.close()


def set_schedule_enabled(
    schedule_id: int, enabled: bool, *, conn=None
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schedule_schema_ready(conn):
            return None, "schema_unavailable"
        existing = get_schedule(int(schedule_id), conn=conn)
        if not existing:
            return None, "not_found"
        now = int(time.time())
        conn.execute(
            """
            UPDATE server_event_schedules
            SET enabled = ?, updated_at = ?
            WHERE id = ?;
            """,
            (1 if enabled else 0, now, int(schedule_id)),
        )
        conn.commit()
        return get_schedule(int(schedule_id), conn=conn), None
    finally:
        if owns:
            conn.close()


def compute_schedule_window(
    rule: Mapping[str, Any],
    *,
    now: Optional[float] = None,
) -> Optional[Tuple[int, int, str]]:
    """
    Next/current materializable window for a rule.

    Returns (starts_at, ends_at, materialize_key) or None.
    Prefers an in-progress window; else the next upcoming start within lookahead.
    """
    ts = float(now if now is not None else time.time())
    offset = int(rule.get("tz_offset_minutes") or 0)
    hour, minute = _parse_hhmm(str(rule.get("local_start_hhmm") or "18:00"))
    kind = str(rule.get("rrule_kind") or RRULE_WEEKLY)
    duration_sec = int(rule.get("duration_sec") or 0)
    preset = get_preset(str(rule.get("preset_id") or ""))
    weekdays = list(rule.get("weekdays") or [])
    if not weekdays and kind == RRULE_WEEKLY:
        weekdays = [4]  # Friday default

    local_now = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(minutes=offset)

    def _window_for_local_day(day_local: datetime) -> Tuple[int, int, str]:
        start_local = day_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        start_utc = int((start_local - timedelta(minutes=offset)).timestamp())
        if duration_sec > 0:
            end_utc = start_utc + duration_sec
        elif preset:
            _s, end_utc = resolve_preset_window(
                preset.get("duration"),
                now=float(start_utc),
                starts_at=start_utc,
                tz_offset_minutes=offset,
            )
        else:
            end_utc = start_utc + 24 * 3600
        key = f"{int(rule.get('id') or 0)}:{start_utc}"
        return start_utc, int(end_utc), key

    candidates: List[Tuple[int, int, str]] = []
    if kind == RRULE_DAILY:
        for delta in range(-1, 8):
            day = (local_now + timedelta(days=delta)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            candidates.append(_window_for_local_day(day))
    elif kind == RRULE_ONCE:
        # Single fire: use next matching weekday from weekdays, or tomorrow if empty.
        targets = weekdays or [local_now.weekday()]
        for delta in range(0, 14):
            day = (local_now + timedelta(days=delta)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if day.weekday() in targets:
                candidates.append(_window_for_local_day(day))
                break
    else:  # weekly
        for delta in range(-7, 14):
            day = (local_now + timedelta(days=delta)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if day.weekday() in weekdays:
                candidates.append(_window_for_local_day(day))

    if not candidates:
        return None

    # Prefer currently active window, else soonest start within lookahead.
    active = [
        c for c in candidates if float(c[0]) - SCHEDULE_LOOKAHEAD_SEC <= ts < float(c[1])
    ]
    if active:
        active.sort(key=lambda c: c[0])
        return active[0]
    upcoming = [c for c in candidates if float(c[0]) >= ts]
    if not upcoming:
        return None
    upcoming.sort(key=lambda c: c[0])
    start, end, key = upcoming[0]
    if float(start) - SCHEDULE_LOOKAHEAD_SEC > ts:
        return None
    return start, end, key


def materialize_schedule(
    schedule_id: int,
    *,
    conn=None,
    now: Optional[float] = None,
    force: bool = False,
    force_world_boss: bool = False,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    INSERT a server_events row for the rule's current/next window.

    Never updates/deletes existing events. Idempotent via last_materialized_key.
    """
    owns = conn is None
    if owns:
        conn = db()
    try:
        if not schedule_schema_ready(conn) or not schema_ready(conn):
            return None, "schema_unavailable"
        rule = get_schedule(int(schedule_id), conn=conn)
        if not rule:
            return None, "not_found"
        if not rule.get("enabled") and not force:
            return None, "disabled"

        window = compute_schedule_window(rule, now=now)
        if not window:
            return None, "no_window"
        start, end, mat_key = window
        if not force and str(rule.get("last_materialized_key") or "") == mat_key:
            return {
                "schedule_id": int(schedule_id),
                "skipped": True,
                "reason": "already_materialized",
                "materialize_key": mat_key,
                "event": None,
                "actions": [],
            }, None

        preset = get_preset(str(rule.get("preset_id") or ""))
        effects = list(rule.get("effects") or [])
        actions: List[Dict[str, Any]] = []
        title = str(rule.get("name") or get_locale_dict("en").get("server_event_scheduled_fallback") or "scheduled_event")
        slug_prefix = "scheduled"
        if preset:
            if not effects:
                effects = list(preset.get("effects") or [])
            actions = list(preset.get("actions") or [])
            title = _preset_fallback_title(preset)
            slug_prefix = str(preset.get("slug_prefix") or preset["id"] or slug_prefix)

        if not effects and not actions:
            return None, "empty_rule"

        entry = None
        if effects:
            slug = _unique_slug(slug_prefix, conn=conn)
            entry, err = create_event(
                slug=slug,
                title=title,
                starts_at=int(start),
                ends_at=int(end),
                effects=effects,
                enabled=True,
                created_by=rule.get("created_by"),
                conn=conn,
            )
            if err or not entry:
                return None, err or "create_failed"

        action_results: List[Dict[str, Any]] = []
        ts = float(now if now is not None else time.time())
        # WB spawn only when the window has started (not during pure lookahead).
        if actions and ts >= float(start):
            action_results = _dispatch_preset_actions(
                actions, conn=conn, force_world_boss=force_world_boss
            )

        now_i = int(time.time())
        conn.execute(
            """
            UPDATE server_event_schedules
            SET last_materialized_key = ?, updated_at = ?
            WHERE id = ?;
            """,
            (mat_key, now_i, int(schedule_id)),
        )
        conn.commit()
        clear_factor_cache()
        return (
            {
                "schedule_id": int(schedule_id),
                "skipped": False,
                "materialize_key": mat_key,
                "starts_at": int(start),
                "ends_at": int(end),
                "event": entry,
                "actions": action_results,
            },
            None,
        )
    finally:
        if owns:
            conn.close()


def tick_schedules(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Materialize all enabled rules due within lookahead. INSERT-only."""
    if not schedule_schema_ready(conn):
        return {"ok": False, "error": "schema_unavailable", "materialized": [], "skipped": 0}
    ts = float(now if now is not None else time.time())
    materialized: List[Dict[str, Any]] = []
    skipped = 0
    errors: List[Dict[str, Any]] = []
    for rule in list_schedules(conn=conn):
        if not rule.get("enabled"):
            continue
        result, err = materialize_schedule(int(rule["id"]), conn=conn, now=ts)
        # No window inside the scheduler lookahead is the normal idle state, not
        # an operational failure. Treat it like an ordinary skipped rule so the
        # maintenance logs only report actionable LiveOps errors.
        if err == "no_window":
            skipped += 1
            continue
        if err:
            errors.append({"schedule_id": rule["id"], "error": err})
            continue
        if not result:
            continue
        if result.get("skipped"):
            skipped += 1
        else:
            materialized.append(result)
    return {
        "ok": True,
        "materialized": materialized,
        "skipped": skipped,
        "errors": errors,
    }


def maybe_tick_schedules(*, conn, now: Optional[float] = None) -> Dict[str, Any]:
    """Cron entry — throttled schedule materialization."""
    from .runtime_state import get_runtime_value, set_runtime_value

    ts = float(now if now is not None else time.time())
    try:
        raw = get_runtime_value(SCHEDULE_RUNTIME_KEY, conn=conn)
        last = float(raw) if raw not in (None, "") else 0.0
    except (TypeError, ValueError):
        last = 0.0
    if last > 0 and (ts - last) < SCHEDULE_TICK_THROTTLE_SEC:
        return {"ok": True, "throttled": True, "materialized": [], "skipped": 0}
    try:
        out = tick_schedules(conn=conn, now=ts)
        set_runtime_value(SCHEDULE_RUNTIME_KEY, str(ts), conn=conn)
        out["throttled"] = False
        return out
    except Exception:
        return {"ok": False, "error": "tick_failed", "materialized": [], "skipped": 0}
