"""
Server Events — timed global LiveOps bonuses (production, expedition hold).

Owner for admin CRUD + active factor reads. Gameplay hooks:
- production_formula.production_context_from_resolver → event_modifier
- fleet.expedition_stay_seconds → hold duration mult
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import db, table_exists

KIND_PRODUCTION_MULT = "production_mult"
KIND_EXPEDITION_HOLD_MULT = "expedition_hold_mult"

EFFECT_KINDS = frozenset({KIND_PRODUCTION_MULT, KIND_EXPEDITION_HOLD_MULT})

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")

# Short process cache so resource ticks / fleet previews do not re-query every call.
_FACTOR_CACHE: Tuple[float, Dict[str, float]] = (0.0, {})
_FACTOR_CACHE_TTL = 3.0


def schema_ready(conn) -> bool:
    return bool(table_exists(conn, "server_events"))


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
        kind = str(item.get("kind") or "").strip()
        if kind not in EFFECT_KINDS:
            continue
        try:
            mult = float(item.get("mult"))
        except (TypeError, ValueError):
            continue
        if mult <= 0:
            continue
        out.append({"kind": kind, "mult": mult})
    return out


def validate_effects(raw: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Validate admin payload; reject unknown kinds or bad mults."""
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
                "title": e["title"],
                "starts_at": e["starts_at"],
                "ends_at": e["ends_at"],
                "effects": e["effects"],
            }
            for e in active
        ],
        "production_mult": float(factors.get(KIND_PRODUCTION_MULT, 1.0)),
        "expedition_hold_mult": float(factors.get(KIND_EXPEDITION_HOLD_MULT, 1.0)),
    }


def effect_summary_short(effects: Any) -> List[str]:
    """Compact labels for banners/calendar (+100% Prod, −25% Hold)."""
    out: List[str] = []
    if not isinstance(effects, list):
        return out
    for eff in effects:
        if not isinstance(eff, Mapping):
            continue
        kind = str(eff.get("kind") or "").strip()
        try:
            mult = float(eff.get("mult") or 1.0)
        except (TypeError, ValueError):
            continue
        if kind == KIND_PRODUCTION_MULT and mult > 0:
            pct = int(round((mult - 1.0) * 100))
            if pct != 0:
                out.append(f"+{pct}% Prod" if pct > 0 else f"{pct}% Prod")
        elif kind == KIND_EXPEDITION_HOLD_MULT and mult > 0:
            pct = int(round((1.0 - mult) * 100))
            if pct != 0:
                out.append(f"−{pct}% Hold" if pct > 0 else f"+{abs(pct)}% Hold")
    return out


def active_events_banner(*, now: Optional[float] = None, conn=None) -> List[Dict[str, Any]]:
    """UI teaser rows for Overview / Login Rewards (active server events only)."""
    ts = float(now if now is not None else time.time())
    out: List[Dict[str, Any]] = []
    for ev in list_active_events(now=ts, conn=conn):
        ends = int(ev.get("ends_at") or 0)
        out.append(
            {
                "kind": "server_event",
                "id": int(ev.get("id") or 0),
                "slug": str(ev.get("slug") or ""),
                "title": str(ev.get("title") or ""),
                "title_key": "",
                "effects_summary": effect_summary_short(ev.get("effects")),
                "ends_at": ends,
                "remaining_sec": max(0, ends - int(ts)) if ends else 0,
                "href": "login_rewards_view",
            }
        )
    return out


def _combine_factors(events: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    prod = 1.0
    hold = 1.0
    for ev in events:
        for eff in ev.get("effects") or []:
            kind = str(eff.get("kind") or "")
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
    return {
        KIND_PRODUCTION_MULT: prod,
        KIND_EXPEDITION_HOLD_MULT: hold,
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
        titles.append(str(ev.get("title") or ev.get("slug") or ""))
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
    ]
