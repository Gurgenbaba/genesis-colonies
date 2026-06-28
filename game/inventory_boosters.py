"""
GC-968A — Active inventory boosters (single owner for timed pct effects).

Activated via inventory_use; consumed by EffectResolver, expedition loot, container rolls.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from game.db import table_exists
from game.inventory_catalog import item_catalog_entry

BOOSTER_SCHEMA_TABLES = ("player_active_boosters",)

# use_kind → effect_key stored in player_active_boosters
USE_KIND_EFFECT_KEYS: Dict[str, str] = {
    "research_pct_boost": "research_time_speed",
    "energy_pct_boost": "solar_output_factor",
    "fleet_speed_pct_boost": "fleet_speed_multiplier",
    "expedition_loot_pct_boost": "expedition_loot_mult",
    "container_luck_boost": "container_luck_mult",
    "production_pct_boost": "metal_prod_factor",
}

EFFECT_RESOLVER_BOOSTER_KEYS = frozenset(
    {
        "research_time_speed",
        "solar_output_factor",
        "fleet_speed_multiplier",
        "metal_prod_factor",
        "crystal_prod_factor",
        "fuel_prod_factor",
    }
)

PRODUCTION_EFFECT_KEYS = frozenset({"metal_prod_factor", "crystal_prod_factor", "fuel_prod_factor"})

HUD_RESOURCE_PROD_KEYS: Dict[str, str] = {
    "metal": "metal_mine",
    "crystal": "crystal_mine",
    "fuel_cells": "fuel_cell_plant",
}

# GC-968B audit — booster reward classification for docs/tests.
BOOSTER_AUDIT: Dict[str, str] = {
    # Timed pct — EffectResolver / domain owner
    "booster_research_pct_2_24h": "active_real_effect",
    "booster_energy_surge_24h": "active_real_effect",
    "booster_production_25": "active_real_effect",
    "booster_production_50": "active_real_effect",
    "booster_production_100": "active_real_effect",
    "booster_energy_50": "active_real_effect",
    "booster_fleet_speed_25_24h": "active_real_effect",
    "booster_expedition_loot_25_24h": "active_real_effect",
    "booster_container_luck_24h": "active_real_effect",
    # Time shift — queue engine (instant on use, no fake pct label)
    "booster_build_5m": "active_real_effect",
    "booster_build_15m": "active_real_effect",
    "booster_build_1h": "active_real_effect",
    "booster_build_6h": "active_real_effect",
    "booster_build_24h": "active_real_effect",
    "booster_research_5m": "active_real_effect",
    "booster_research_15m": "active_real_effect",
    "booster_research_30m": "active_real_effect",
    "booster_research_1h": "active_real_effect",
    "booster_research_6h": "active_real_effect",
    "booster_research_24h": "active_real_effect",
    "booster_shipyard_15m": "active_real_effect",
    "booster_shipyard_1h": "active_real_effect",
    # Locked utilities — no formula wiring yet
    "utility_repair_drone": "locked_planned",
    "utility_fleet_instant_recall": "locked_planned",
    "utility_alien_scanner": "locked_planned",
    "utility_pirate_scanner": "locked_planned",
    "utility_anomaly_scanner": "locked_planned",
    "utility_fleet_queue_plus_1": "locked_planned",
}

EFFECT_HUD_META: Dict[str, Dict[str, str]] = {
    "research_time_speed": {
        "domain": "research",
        "label_key": "boost_hud_research",
        "summary_key": "boost_hud_pct_summary",
        "applies_to": "new_jobs_only",
    },
    "solar_output_factor": {
        "domain": "energy",
        "label_key": "boost_hud_energy",
        "summary_key": "boost_hud_pct_summary",
        "applies_to": "ongoing",
    },
    "metal_prod_factor": {
        "domain": "production",
        "label_key": "boost_hud_production",
        "summary_key": "boost_hud_pct_summary",
        "applies_to": "ongoing",
    },
    "production": {
        "domain": "production",
        "label_key": "boost_hud_production",
        "summary_key": "boost_hud_pct_summary",
        "applies_to": "ongoing",
    },
    "fleet_speed_multiplier": {
        "domain": "fleet",
        "label_key": "boost_hud_fleet",
        "summary_key": "boost_hud_pct_summary",
        "applies_to": "ongoing",
    },
    "expedition_loot_mult": {
        "domain": "expedition",
        "label_key": "boost_hud_expedition",
        "summary_key": "boost_hud_pct_summary",
        "applies_to": "ongoing",
    },
    "container_luck_mult": {
        "domain": "containers",
        "label_key": "boost_hud_containers",
        "summary_key": "boost_hud_pct_summary",
        "applies_to": "ongoing",
    },
}


def boosters_schema_ready(conn) -> bool:
    return all(table_exists(conn, name) for name in BOOSTER_SCHEMA_TABLES)


def _purge_expired(user_id: int, *, conn, now: Optional[float] = None) -> None:
    if not boosters_schema_ready(conn):
        return
    ts = float(now if now is not None else time.time())
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM player_active_boosters WHERE user_id = ? AND expires_at <= ?;",
        (int(user_id), ts),
    )


def _boost_specs_from_item(item_key: str) -> List[Dict[str, Any]]:
    spec = item_catalog_entry(str(item_key))
    use_kind = str(spec.get("use_kind") or "")
    effect = dict(spec.get("use_effect") or {})
    pct = float(effect.get("pct") or 0)
    hours = float(effect.get("hours") or 24)
    if use_kind == "container_luck_boost" and pct <= 0:
        pct = 25.0
    multiplier = 1.0 + (pct / 100.0) if pct > 0 else 1.25
    duration_seconds = int(max(1, hours * 3600))
    base = {
        "multiplier": float(multiplier),
        "duration_seconds": duration_seconds,
        "use_kind": use_kind,
    }
    if use_kind == "production_pct_boost":
        return [
            {**base, "effect_key": "metal_prod_factor"},
            {**base, "effect_key": "crystal_prod_factor"},
            {**base, "effect_key": "fuel_prod_factor"},
        ]
    effect_key = USE_KIND_EFFECT_KEYS.get(use_kind)
    if not effect_key:
        return []
    return [{**base, "effect_key": effect_key}]


def _boost_spec_from_item(item_key: str) -> Optional[Dict[str, Any]]:
    specs = _boost_specs_from_item(item_key)
    return specs[0] if specs else None


def item_has_implemented_use_effect(item_key: str) -> bool:
    """True when inventory use applies a real gameplay effect (GC-968A audit)."""
    from game.inventory_catalog import (
        BOOSTER_TIME_SECONDS,
        is_research_datacore_item,
        resolve_item_use_kind,
    )

    key = str(item_key or "").strip()
    if not key:
        return False
    if key in BOOSTER_TIME_SECONDS:
        return True
    kind = resolve_item_use_kind(key)
    if kind in (
        "time_boost",
        "resource",
        "planet_xp",
        "research_datacore",
        "research_instant",
        "blueprint",
    ):
        return True
    if kind in USE_KIND_EFFECT_KEYS:
        return _boost_spec_from_item(key) is not None
    if kind == "production_pct_boost":
        return bool(_boost_specs_from_item(key))
    return False


def activate_inventory_booster(
    user_id: int,
    item_key: str,
    *,
    conn,
    now: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    if not boosters_schema_ready(conn):
        return None
    specs = _boost_specs_from_item(item_key)
    if not specs:
        return None

    ts = float(now if now is not None else time.time())
    uid = int(user_id)
    _purge_expired(uid, conn=conn, now=ts)

    activated: List[Dict[str, Any]] = []
    cur = conn.cursor()
    for boost in specs:
        effect_key = str(boost["effect_key"])
        multiplier = float(boost["multiplier"])
        duration = int(boost["duration_seconds"])
        new_expires = ts + duration

        cur.execute(
            """
            SELECT multiplier, expires_at FROM player_active_boosters
            WHERE user_id = ? AND effect_key = ? LIMIT 1;
            """,
            (uid, effect_key),
        )
        row = cur.fetchone()
        if row:
            existing_mult = float(row["multiplier"] or 1.0)
            existing_expires = float(row["expires_at"] or 0)
            multiplier = max(existing_mult, multiplier)
            new_expires = max(existing_expires, new_expires)
            cur.execute(
                """
                UPDATE player_active_boosters
                SET multiplier = ?, expires_at = ?, source_item_key = ?, activated_at = ?
                WHERE user_id = ? AND effect_key = ?;
                """,
                (multiplier, new_expires, str(item_key), ts, uid, effect_key),
            )
        else:
            cur.execute(
                """
                INSERT INTO player_active_boosters (
                    user_id, effect_key, multiplier, expires_at, source_item_key, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (uid, effect_key, multiplier, new_expires, str(item_key), ts),
            )
        activated.append(
            {
                "effect_key": effect_key,
                "multiplier": multiplier,
                "expires_at": new_expires,
            }
        )

    primary = activated[0]
    return {
        "kind": "active_boost",
        "effect_key": str(primary["effect_key"]),
        "multiplier": float(primary["multiplier"]),
        "expires_at": float(primary["expires_at"]),
        "duration_seconds": int(specs[0]["duration_seconds"]),
        "source_item_key": str(item_key),
        "activated_effects": activated,
    }


def list_active_boosters(user_id: int, *, conn, now: Optional[float] = None) -> List[Dict[str, Any]]:
    if not boosters_schema_ready(conn):
        return []
    ts = float(now if now is not None else time.time())
    _purge_expired(int(user_id), conn=conn, now=ts)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT effect_key, multiplier, expires_at, source_item_key, activated_at
        FROM player_active_boosters
        WHERE user_id = ? AND expires_at > ?
        ORDER BY effect_key ASC;
        """,
        (int(user_id), ts),
    )
    return [
        {
            "effect_key": str(row["effect_key"]),
            "multiplier": float(row["multiplier"] or 1.0),
            "expires_at": float(row["expires_at"] or 0),
            "source_item_key": str(row["source_item_key"] or ""),
            "activated_at": float(row["activated_at"] or 0),
        }
        for row in cur.fetchall()
    ]


def get_active_booster_multipliers(user_id: int, *, conn, now: Optional[float] = None) -> Dict[str, float]:
    rows = list_active_boosters(user_id, conn=conn, now=now)
    out: Dict[str, float] = {}
    for row in rows:
        key = str(row.get("effect_key") or "")
        if not key:
            continue
        out[key] = max(float(out.get(key, 1.0)), float(row.get("multiplier") or 1.0))
    return out


def get_expedition_booster_flags(user_id: int, *, conn, now: Optional[float] = None) -> Dict[str, float]:
    mults = get_active_booster_multipliers(user_id, conn=conn, now=now)
    loot_mult = float(mults.get("expedition_loot_mult") or 1.0)
    if loot_mult <= 1.0:
        return {}
    return {"expedition_loot_mult": loot_mult}


def get_container_luck_multiplier(user_id: int, *, conn, now: Optional[float] = None) -> float:
    mults = get_active_booster_multipliers(user_id, conn=conn, now=now)
    return max(1.0, float(mults.get("container_luck_mult") or 1.0))


def _pct_from_multiplier(multiplier: float) -> int:
    return max(0, int(round((float(multiplier) - 1.0) * 100)))


def _hud_row_from_effect(
    *,
    effect_key: str,
    multiplier: float,
    expires_at: float,
    source_item_key: str,
    now: float,
    locale: Optional[str],
) -> Dict[str, Any]:
    from game.i18n import tr

    meta = EFFECT_HUD_META.get(effect_key) or {}
    pct = _pct_from_multiplier(multiplier)
    remaining = max(0, int(expires_at - now))
    label_key = str(meta.get("label_key") or "boost_hud_generic")
    summary_key = str(meta.get("summary_key") or "boost_hud_pct_summary")
    applies_to = str(meta.get("applies_to") or "ongoing")
    label = tr(label_key, label_key, locale=locale)
    effect_summary = tr(summary_key, f"+{pct}%", locale=locale, pct=pct)
    note = ""
    if applies_to == "new_jobs_only":
        note = tr(
            "boost_hud_research_new_jobs_note",
            "Applies to newly started research during the active period.",
            locale=locale,
        )
    return {
        "key": str(effect_key),
        "effect_key": str(effect_key),
        "label_key": label_key,
        "label": label,
        "effect_summary_key": summary_key,
        "effect_summary": effect_summary,
        "effect_summary_params": {"pct": pct},
        "expires_at": float(expires_at),
        "remaining_seconds": remaining,
        "affected_domain": str(meta.get("domain") or "general"),
        "applies_to": applies_to,
        "note": note,
        "source_item_key": str(source_item_key or ""),
    }


def build_active_effects_for_hud(
    user_id: int,
    *,
    conn,
    locale: Optional[str] = None,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """HUD-ready active timed boosters — labels resolved server-side (GC-968B)."""
    rows = list_active_boosters(user_id, conn=conn, now=now)
    ts = float(now if now is not None else time.time())
    prod_rows = [r for r in rows if str(r.get("effect_key") or "") in PRODUCTION_EFFECT_KEYS]
    other_rows = [r for r in rows if str(r.get("effect_key") or "") not in PRODUCTION_EFFECT_KEYS]

    out: List[Dict[str, Any]] = []
    if prod_rows:
        mult = max(float(r.get("multiplier") or 1.0) for r in prod_rows)
        expires = max(float(r.get("expires_at") or 0) for r in prod_rows)
        source = str(prod_rows[0].get("source_item_key") or "")
        if mult > 1.0 and expires > ts:
            out.append(
                _hud_row_from_effect(
                    effect_key="production",
                    multiplier=mult,
                    expires_at=expires,
                    source_item_key=source,
                    now=ts,
                    locale=locale,
                )
            )

    for row in other_rows:
        mult = float(row.get("multiplier") or 1.0)
        if mult <= 1.0:
            continue
        out.append(
            _hud_row_from_effect(
                effect_key=str(row.get("effect_key") or ""),
                multiplier=mult,
                expires_at=float(row.get("expires_at") or 0),
                source_item_key=str(row.get("source_item_key") or ""),
                now=ts,
                locale=locale,
            )
        )
    out.sort(key=lambda r: (str(r.get("affected_domain") or ""), str(r.get("key") or "")))
    return enrich_active_effects_with_resource_impacts(
        user_id,
        conn=conn,
        locale=locale,
        effects=out,
    )


def _format_hourly_delta_summary(amount: int, *, locale: Optional[str]) -> str:
    from game.i18n import fmt_int, tr

    return tr(
        "boost_hud_hourly_delta",
        "(+{amount}/h)",
        locale=locale,
        amount=fmt_int(max(0, int(amount))),
    )


def _format_energy_delta_summary(amount: int, *, locale: Optional[str]) -> str:
    from game.i18n import fmt_int, tr

    return tr(
        "boost_hud_energy_delta",
        "(+{amount})",
        locale=locale,
        amount=fmt_int(max(0, int(amount))),
    )


def _active_planet_production_snapshot(
    user_id: int,
    *,
    conn,
    skip_inventory_boosters: bool = False,
) -> Tuple[Dict[str, int], int, int]:
    from game.effects.effect_resolver import EffectResolver

    resolver = EffectResolver.for_player(
        int(user_id),
        conn=conn,
        skip_inventory_boosters=skip_inventory_boosters,
    )
    total, used = resolver.compute_energy()
    ratio = EffectResolver.energy_ratio(total, used)
    prod = resolver.get_building_production_per_hour(ratio)
    return prod, int(total), int(used)


def enrich_active_effects_with_resource_impacts(
    user_id: int,
    *,
    conn,
    locale: Optional[str],
    effects: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach server-resolved hourly/total deltas for HUD resource chips (GC-969)."""
    if not effects:
        return effects

    domains = {str(e.get("affected_domain") or "") for e in effects}
    if "production" not in domains and "energy" not in domains:
        return effects

    try:
        prod_boost, total_boost, _used_boost = _active_planet_production_snapshot(
            user_id, conn=conn, skip_inventory_boosters=False
        )
        prod_base, total_base, _used_base = _active_planet_production_snapshot(
            user_id, conn=conn, skip_inventory_boosters=True
        )
    except Exception:
        return effects

    prod_deltas = {
        res_key: max(
            0,
            int(prod_boost.get(build_key, 0) or 0) - int(prod_base.get(build_key, 0) or 0),
        )
        for res_key, build_key in HUD_RESOURCE_PROD_KEYS.items()
    }
    energy_delta = max(0, int(total_boost) - int(total_base))

    enriched: List[Dict[str, Any]] = []
    for effect in effects:
        row = dict(effect)
        domain = str(row.get("affected_domain") or "")
        impacts: Dict[str, Dict[str, Any]] = {}

        if domain == "production":
            for res_key, delta in prod_deltas.items():
                if delta <= 0:
                    continue
                impacts[res_key] = {
                    "delta_per_hour": int(delta),
                    "impact_summary": _format_hourly_delta_summary(delta, locale=locale),
                }
        elif domain == "energy" and energy_delta > 0:
            impacts["energy"] = {
                "delta_total": int(energy_delta),
                "impact_summary": _format_energy_delta_summary(energy_delta, locale=locale),
            }

        if impacts:
            row["resource_impacts"] = impacts
        enriched.append(row)
    return enriched


def build_inventory_boosters_state(
    user_id: int,
    *,
    conn,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    rows = list_active_boosters(user_id, conn=conn)
    active_effects = build_active_effects_for_hud(user_id, conn=conn, locale=locale)
    return {
        "ready": boosters_schema_ready(conn),
        "active": rows,
        "active_effects": active_effects,
    }
