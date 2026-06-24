"""
GC-822 — Live economy QA & player migration audit.

Read-only analysis of live DB state after GC-820/GC-821.
Does NOT change production formulas or mutate player data unless explicitly called.

Owner: docs/GC-822_LIVE_ECONOMY_QA.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .buildings import BASE_COST, BUILDING_ORDER, COST_FACTOR, get_upgrade_cost
from .economy_balance import (
    BENCHMARK_LEVELS,
    cumulative_upgrade_cost_sum,
    legacy_exponential_cost_sum,
)
from .effects import EffectResolver
from .exchange import resolve_exchange_daily_limit
from .models import (
    get_build_queue_rows,
    get_planet_buildings,
    get_planets_by_player,
    get_research_levels,
)


# Risk flags surfaced in audit reports.
FLAG_STORAGE_OVERFLOW = "storage_overflow"
FLAG_STORAGE_NEAR_FULL = "storage_near_full"
FLAG_ENERGY_STARVED = "energy_starved"
FLAG_EXCHANGE_LIMIT_FLOOR = "exchange_limit_floor"
FLAG_ACTIVE_BUILD_QUEUE = "active_build_queue"
FLAG_HIGH_MINE_LEGACY_COST = "high_mine_legacy_cost_burden"
FLAG_RANKING_BUILDING_DRIFT = "ranking_building_drift"
FLAG_LOW_TRADER_HEADROOM = "low_trader_headroom"


@dataclass
class ColonyAudit:
    planet_id: int
    position: Optional[int]
    metal: int
    crystal: int
    fuel_cells: int
    metal_cap: int
    crystal_cap: int
    fuel_cap: int
    metal_fill_pct: float
    crystal_fill_pct: float
    fuel_fill_pct: float
    production_per_hour: Dict[str, int]
    energy_ratio: float
    max_mine_level: int
    flags: List[str] = field(default_factory=list)


@dataclass
class PlayerEconomyAudit:
    player_id: int
    username: str
    colony_count: int
    empire_production_per_hour: Dict[str, int]
    empire_production_per_day: int
    exchange_daily_limit: int
    exchange_limit_source: str
    score_total: int
    score_buildings: int
    score_buildings_legacy: int
    active_build_jobs: int
    flags: List[str] = field(default_factory=list)
    colonies: List[ColonyAudit] = field(default_factory=list)


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        return int(float(val or 0))
    except (TypeError, ValueError):
        return default


def _fill_pct(balance: int, cap: int) -> float:
    if cap <= 0:
        return 0.0
    return round(100.0 * max(0, balance) / cap, 1)


def _legacy_building_investment(planets_buildings: List[Dict[str, int]]) -> int:
    total = 0
    for b in planets_buildings:
        for key in BUILDING_ORDER:
            lvl = _safe_int(b.get(key))
            if lvl <= 0:
                continue
            base = BASE_COST.get(key, (0, 0))
            fac = float(COST_FACTOR.get(key, 1.5))
            total += legacy_exponential_cost_sum(
                key, lvl, base_m=int(base[0]), base_c=int(base[1]), factor=fac
            )
    return total


def _gc821_building_investment(planets_buildings: List[Dict[str, int]]) -> int:
    total = 0
    for b in planets_buildings:
        for key in BUILDING_ORDER:
            lvl = _safe_int(b.get(key))
            if lvl <= 0:
                continue
            total += cumulative_upgrade_cost_sum(key, lvl)
    return total


def audit_colony(
    planet: Dict[str, Any],
    *,
    player_id: int,
    research: Dict[str, int],
    conn,
) -> ColonyAudit:
    from .galaxy import get_planet_coordinates

    planet_id = _safe_int(planet.get("id"))
    buildings = get_planet_buildings(planet_id, conn=conn)
    coords = get_planet_coordinates(planet)
    position = _safe_int(coords.get("position")) or None
    if position is not None and not (1 <= position <= 15):
        position = None

    resolver = EffectResolver(
        buildings,
        research,
        player_id=int(player_id),
        planet_id=planet_id,
        planet_position=position,
        conn=conn,
    )
    energy_total, energy_used = resolver.compute_energy()
    ratio = resolver.energy_ratio(energy_total, energy_used)
    caps = resolver.get_storage_capacity()
    prod = resolver.get_building_production_per_hour(ratio)

    metal = _safe_int(planet.get("metal"))
    crystal = _safe_int(planet.get("crystal"))
    fuel = _safe_int(planet.get("fuel_cells"))
    metal_cap = _safe_int(caps.get("metal"))
    crystal_cap = _safe_int(caps.get("crystal"))
    fuel_cap = _safe_int(caps.get("fuel_cells"))

    flags: List[str] = []
    if metal > metal_cap and metal_cap > 0:
        flags.append(FLAG_STORAGE_OVERFLOW)
    if crystal > crystal_cap and crystal_cap > 0:
        flags.append(FLAG_STORAGE_OVERFLOW)
    if fuel > fuel_cap and fuel_cap > 0:
        flags.append(FLAG_STORAGE_OVERFLOW)
    for pct, cap in (
        (_fill_pct(metal, metal_cap), metal_cap),
        (_fill_pct(crystal, crystal_cap), crystal_cap),
        (_fill_pct(fuel, fuel_cap), fuel_cap),
    ):
        if cap > 0 and pct >= 90.0:
            flags.append(FLAG_STORAGE_NEAR_FULL)
    if ratio < 0.85:
        flags.append(FLAG_ENERGY_STARVED)

    mine_levels = [
        _safe_int(buildings.get("metal_mine")),
        _safe_int(buildings.get("crystal_mine")),
    ]
    max_mine = max(mine_levels) if mine_levels else 0
    if max_mine >= 60:
        flags.append(FLAG_HIGH_MINE_LEGACY_COST)

    return ColonyAudit(
        planet_id=planet_id,
        position=position,
        metal=metal,
        crystal=crystal,
        fuel_cells=fuel,
        metal_cap=metal_cap,
        crystal_cap=crystal_cap,
        fuel_cap=fuel_cap,
        metal_fill_pct=_fill_pct(metal, metal_cap),
        crystal_fill_pct=_fill_pct(crystal, crystal_cap),
        fuel_fill_pct=_fill_pct(fuel, fuel_cap),
        production_per_hour={
            "metal": _safe_int(prod.get("metal_mine")),
            "crystal": _safe_int(prod.get("crystal_mine")),
            "fuel_cells": _safe_int(prod.get("fuel_cell_plant")),
        },
        energy_ratio=round(float(ratio), 3),
        max_mine_level=max_mine,
        flags=flags,
    )


def audit_player(player_id: int, *, conn, username: Optional[str] = None) -> PlayerEconomyAudit:
    from .empire_page import get_empire_production_aggregate
    from .ranking import compute_player_scores

    uid = int(player_id)
    if username is None:
        row = conn.execute("SELECT username FROM users WHERE id = ? LIMIT 1;", (uid,)).fetchone()
        username = str(row["username"]) if row else f"player_{uid}"

    planets = get_planets_by_player(uid, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    buildings_list = [get_planet_buildings(int(p["id"]), conn=conn) for p in planets]

    colonies = [audit_colony(p, player_id=uid, research=research, conn=conn) for p in planets]
    empire = get_empire_production_aggregate(uid, conn=conn)
    limit_block = resolve_exchange_daily_limit(uid, conn=conn)

    scores = compute_player_scores(uid, conn=conn)
    legacy_invest = _legacy_building_investment(buildings_list)
    gc821_invest = _gc821_building_investment(buildings_list)
    legacy_building_score = int((legacy_invest ** 1.0)) if legacy_invest > 0 else 0
    current_building_score = int(scores.get("building_score", 0))

    build_jobs = 0
    for p in planets:
        build_jobs += len(get_build_queue_rows(int(p["id"]), conn=conn))

    flags: List[str] = []
    for col in colonies:
        for f in col.flags:
            if f not in flags:
                flags.append(f)
    if build_jobs > 0:
        flags.append(FLAG_ACTIVE_BUILD_QUEUE)
    if limit_block.get("daily_limit_source") == "min":
        flags.append(FLAG_EXCHANGE_LIMIT_FLOOR)
    day_total = _safe_int(empire.get("total_per_day"))
    daily_limit = _safe_int(limit_block.get("daily_limit"))
    if day_total > 0 and daily_limit > 0 and daily_limit < day_total * 0.15:
        flags.append(FLAG_LOW_TRADER_HEADROOM)
    drift_pct = 0.0
    if legacy_building_score > 0:
        drift_pct = abs(current_building_score - legacy_building_score) / legacy_building_score * 100.0
    if drift_pct >= 15.0:
        flags.append(FLAG_RANKING_BUILDING_DRIFT)

    return PlayerEconomyAudit(
        player_id=uid,
        username=username,
        colony_count=len(planets),
        empire_production_per_hour={
            "metal": _safe_int(empire.get("metal_per_hour")),
            "crystal": _safe_int(empire.get("crystal_per_hour")),
            "fuel_cells": _safe_int(empire.get("fuel_cells_per_hour")),
        },
        empire_production_per_day=day_total,
        exchange_daily_limit=daily_limit,
        exchange_limit_source=str(limit_block.get("daily_limit_source") or ""),
        score_total=_safe_int(scores.get("total_score")),
        score_buildings=current_building_score,
        score_buildings_legacy=legacy_building_score,
        active_build_jobs=build_jobs,
        flags=flags,
        colonies=colonies,
    )


def audit_universe(
    *,
    conn,
    limit: int = 50,
    min_max_mine_level: int = 0,
) -> Dict[str, Any]:
    """Scan active players; prioritize high mine levels for live QA."""
    rows = conn.execute(
        """
        SELECT u.id AS user_id, u.username,
               MAX(
                   CASE
                       WHEN COALESCE(pb.metal_mine, 0) >= COALESCE(pb.crystal_mine, 0)
                       THEN COALESCE(pb.metal_mine, 0)
                       ELSE COALESCE(pb.crystal_mine, 0)
                   END
               ) AS max_mine
        FROM users u
        JOIN players p ON p.user_id = u.id
        JOIN planets pl ON pl.player_id = p.id
        LEFT JOIN planet_buildings pb ON pb.planet_id = pl.id
        GROUP BY u.id
        HAVING max_mine >= ?
        ORDER BY max_mine DESC, u.id ASC
        LIMIT ?;
        """,
        (int(min_max_mine_level), int(limit)),
    ).fetchall()

    players: List[Dict[str, Any]] = []
    flag_counts: Dict[str, int] = {}

    for row in rows:
        audit = audit_player(int(row["user_id"]), conn=conn, username=str(row["username"]))
        for f in audit.flags:
            flag_counts[f] = flag_counts.get(f, 0) + 1
        players.append(
            {
                "player_id": audit.player_id,
                "username": audit.username,
                "max_mine_level": max((c.max_mine_level for c in audit.colonies), default=0),
                "empire_production_per_day": audit.empire_production_per_day,
                "exchange_daily_limit": audit.exchange_daily_limit,
                "score_total": audit.score_total,
                "score_buildings": audit.score_buildings,
                "score_buildings_legacy": audit.score_buildings_legacy,
                "active_build_jobs": audit.active_build_jobs,
                "flags": audit.flags,
            }
        )

    return {
        "player_count": len(players),
        "flag_counts": flag_counts,
        "players": players,
    }


def synthetic_profile_audit(
    buildings: Dict[str, int],
    *,
    research: Optional[Dict[str, int]] = None,
    planet_position: int = 9,
    balances: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Offline QA profile without DB — for tests and balance tables."""
    research = dict(research or {})
    balances = balances or {"metal": 0, "crystal": 0, "fuel_cells": 0}
    resolver = EffectResolver(buildings, research, planet_position=planet_position)
    energy_total, energy_used = resolver.compute_energy()
    ratio = resolver.energy_ratio(energy_total, energy_used)
    prod = resolver.get_building_production_per_hour(ratio)
    caps = resolver.get_storage_capacity()

    metal_lvl = _safe_int(buildings.get("metal_mine"))
    next_metal_cost = get_upgrade_cost("metal_mine", metal_lvl) if metal_lvl >= 0 else (0, 0)
    metal_ph = _safe_int(prod.get("metal_mine"))
    upgrade_hours = (
        float(next_metal_cost[0]) / metal_ph if metal_ph > 0 and next_metal_cost[0] > 0 else None
    )

    return {
        "production_per_hour": {
            "metal": metal_ph,
            "crystal": _safe_int(prod.get("crystal_mine")),
            "fuel_cells": _safe_int(prod.get("fuel_cell_plant")),
        },
        "storage_caps": caps,
        "balances": balances,
        "energy_ratio": round(float(ratio), 3),
        "next_metal_upgrade_cost": next_metal_cost,
        "next_metal_upgrade_hours": upgrade_hours,
        "benchmark_levels": list(BENCHMARK_LEVELS),
    }


def migration_recommendations(audit: PlayerEconomyAudit) -> List[str]:
    """Non-destructive guidance for support/admin — no auto-compensation."""
    recs: List[str] = []
    if FLAG_STORAGE_OVERFLOW in audit.flags:
        recs.append(
            "Overflow-Salden bleiben erhalten; Produktion cappt nur Zuwachs — kein Trim nötig."
        )
    if FLAG_STORAGE_NEAR_FULL in audit.flags:
        recs.append(
            "Lager nahe voll: Spieler auf Storage-Upgrade oder Trader hinweisen (GC-821 höhere Basis-Caps)."
        )
    if FLAG_ENERGY_STARVED in audit.flags:
        recs.append("Energieunterversorgung: Solar/Verbrauch prüfen — Produktion ist absichtlich gedrosselt.")
    if FLAG_EXCHANGE_LIMIT_FLOOR in audit.flags:
        recs.append(
            "Trader-Limit durch exchange_daily_limit_min — bei Reibung Admin-Pct/Min anpassen, nicht Produktion."
        )
    if FLAG_RANKING_BUILDING_DRIFT in audit.flags:
        recs.append(
            "Gebäude-Score weicht von Legacy ab: erwartet nach GC-821 Power-Kosten — kein Rollback."
        )
    if FLAG_HIGH_MINE_LEGACY_COST in audit.flags:
        recs.append(
            "Endgame-Minen: GC-821 senkt künftige Upgrade-Kosten vs. alter Exponentialkurve — Bestand fairer."
        )
    if not recs:
        recs.append("Keine Migration/Compensation nötig — Spielstand kompatibel.")
    return recs


def player_audit_to_dict(audit: PlayerEconomyAudit) -> Dict[str, Any]:
    return {
        "player_id": audit.player_id,
        "username": audit.username,
        "colony_count": audit.colony_count,
        "empire_production_per_hour": audit.empire_production_per_hour,
        "empire_production_per_day": audit.empire_production_per_day,
        "exchange_daily_limit": audit.exchange_daily_limit,
        "exchange_limit_source": audit.exchange_limit_source,
        "score_total": audit.score_total,
        "score_buildings": audit.score_buildings,
        "score_buildings_legacy": audit.score_buildings_legacy,
        "active_build_jobs": audit.active_build_jobs,
        "flags": audit.flags,
        "recommendations": migration_recommendations(audit),
        "colonies": [
            {
                "planet_id": c.planet_id,
                "position": c.position,
                "metal_fill_pct": c.metal_fill_pct,
                "crystal_fill_pct": c.crystal_fill_pct,
                "fuel_fill_pct": c.fuel_fill_pct,
                "production_per_hour": c.production_per_hour,
                "energy_ratio": c.energy_ratio,
                "max_mine_level": c.max_mine_level,
                "flags": c.flags,
            }
            for c in audit.colonies
        ],
    }
