"""
Alliance Hub catalog — buildings, technologies, costs, progression (EPIC-09).

Owner: game/alliance.py consumes these definitions; no duplicate math elsewhere.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from typing import Any, Dict, List, Mapping, Optional, Tuple

ALLIANCE_ROLES = frozenset({"leader", "officer", "member"})
OFFICER_ROLES = frozenset({"leader", "officer"})

BASE_MEMBER_LIMIT = 5
HQ_MEMBERS_PER_LEVEL = 2

DONATION_XP_DIVISOR = 10_000
DONATION_XP_MAX_PER_DONATION = 25
DONATION_XP_DAILY_CAP = 150
PROJECT_XP_DIVISOR = 5_000

ALLIANCE_XP_LEVEL_BASE = 1_000

ALLIANCE_BUILDINGS: Dict[str, Dict[str, Any]] = {
    "alliance_headquarters": {
        "label_key": "alliance_building_hq",
        "desc_key": "alliance_building_hq_desc",
        "max_level": 10,
        "base_cost": {"metal": 40_000, "crystal": 20_000, "fuel_cells": 5_000},
        "cost_factor": 1.75,
        "duration_sec": 3_600,
        "duration_factor": 1.35,
    },
    "research_archive": {
        "label_key": "alliance_building_research_archive",
        "desc_key": "alliance_building_research_archive_desc",
        "max_level": 5,
        "base_cost": {"metal": 30_000, "crystal": 30_000, "fuel_cells": 8_000},
        "cost_factor": 1.8,
        "duration_sec": 4_800,
        "duration_factor": 1.4,
        "requires": {"alliance_level": 1},
    },
    "expedition_office": {
        "label_key": "alliance_building_expedition_office",
        "desc_key": "alliance_building_expedition_office_desc",
        "max_level": 5,
        "base_cost": {"metal": 35_000, "crystal": 25_000, "fuel_cells": 10_000},
        "cost_factor": 1.8,
        "duration_sec": 5_400,
        "duration_factor": 1.4,
        "requires": {"building": {"research_archive": 1}, "alliance_level": 2},
        "expedition_success_bonus_pct_per_level": 0.6,
        "expedition_success_bonus_max_pct": 3.0,
    },
    "logistics_depot": {
        "label_key": "alliance_building_logistics_depot",
        "desc_key": "alliance_building_logistics_depot_desc",
        "max_level": 5,
        "base_cost": {"metal": 45_000, "crystal": 35_000, "fuel_cells": 12_000},
        "cost_factor": 1.85,
        "duration_sec": 6_000,
        "duration_factor": 1.45,
        "requires": {"building": {"research_archive": 1}, "alliance_level": 2},
        "pool_cap_bonus_pct_per_level": 8,
    },
    "diplomacy_center": {
        "label_key": "alliance_building_diplomacy_center",
        "desc_key": "alliance_building_diplomacy_center_desc",
        "max_level": 3,
        "base_cost": {"metal": 50_000, "crystal": 40_000, "fuel_cells": 15_000},
        "cost_factor": 2.0,
        "duration_sec": 7_200,
        "duration_factor": 1.5,
        "requires": {"building": {"alliance_headquarters": 2}, "alliance_level": 3},
    },
}

ALLIANCE_TECHNOLOGIES: Dict[str, Dict[str, Any]] = {
    "research_network": {
        "label_key": "alliance_tech_research_network",
        "desc_key": "alliance_tech_research_network_desc",
        "max_level": 6,
        "bonus_pct_per_level": 0.5,
        "bonus_max_pct": 3.0,
        "effect_key": "research_time_speed",
        "base_cost": {"metal": 25_000, "crystal": 35_000, "fuel_cells": 6_000},
        "cost_factor": 1.9,
        "duration_sec": 5_400,
        "duration_factor": 1.45,
        "requires": {"building": {"research_archive": 1}},
    },
    "expedition_coordination": {
        "label_key": "alliance_tech_expedition_coordination",
        "desc_key": "alliance_tech_expedition_coordination_desc",
        "max_level": 5,
        "bonus_pct_per_level": 1.0,
        "bonus_max_pct": 5.0,
        "success_bonus_pct_per_level": 0.8,
        "success_bonus_max_pct": 4.0,
        "effect_key": "expedition_loot_mult",
        "base_cost": {"metal": 30_000, "crystal": 30_000, "fuel_cells": 10_000},
        "cost_factor": 1.95,
        "duration_sec": 6_600,
        "duration_factor": 1.5,
        "requires": {"building": {"expedition_office": 1}},
    },
    "industrial_logistics": {
        "label_key": "alliance_tech_industrial_logistics",
        "desc_key": "alliance_tech_industrial_logistics_desc",
        "max_level": 5,
        "bonus_pct_per_level": 0.4,
        "bonus_max_pct": 2.0,
        "effect_key": "production_factor",
        "base_cost": {"metal": 40_000, "crystal": 25_000, "fuel_cells": 8_000},
        "cost_factor": 1.9,
        "duration_sec": 6_000,
        "duration_factor": 1.45,
        "requires": {"building": {"research_archive": 1}, "alliance_level": 2},
    },
    "defensive_protocols": {
        "label_key": "alliance_tech_defensive_protocols",
        "desc_key": "alliance_tech_defensive_protocols_desc",
        "max_level": 6,
        "bonus_pct_per_level": 0.5,
        "bonus_max_pct": 3.0,
        "effect_key": "defense_armor_shield",
        "base_cost": {"metal": 35_000, "crystal": 40_000, "fuel_cells": 10_000},
        "cost_factor": 2.0,
        "duration_sec": 7_200,
        "duration_factor": 1.5,
        "requires": {"building": {"research_archive": 1}, "alliance_level": 2},
    },
    "trade_coordination": {
        "label_key": "alliance_tech_trade_coordination",
        "desc_key": "alliance_tech_trade_coordination_desc",
        "max_level": 5,
        "bonus_pct_per_level": 2.0,
        "bonus_max_pct": 10.0,
        "effect_key": "pool_cap_and_project_speed",
        "base_cost": {"metal": 45_000, "crystal": 45_000, "fuel_cells": 12_000},
        "cost_factor": 2.05,
        "duration_sec": 7_800,
        "duration_factor": 1.55,
        "requires": {"building": {"logistics_depot": 1}, "alliance_level": 3},
    },
}

DIPLOMACY_RELATIONS = frozenset({"neutral", "nap", "alliance", "war"})
DIPLOMACY_REQUEST_TYPES = frozenset({"nap", "alliance", "war", "peace"})

AFFECTS_BY_EFFECT_KEY: Dict[str, List[str]] = {
    "research_time_speed": ["alliance_affects_research"],
    "expedition_loot_mult": ["alliance_affects_expedition"],
    "production_factor": [
        "alliance_affects_metal",
        "alliance_affects_crystal",
        "alliance_affects_fuel_cells",
    ],
    "defense_armor_shield": ["alliance_affects_defense"],
    "pool_cap_and_project_speed": ["alliance_affects_pool", "alliance_affects_projects"],
}

AFFECTS_BY_BUILDING_KEY: Dict[str, List[str]] = {
    "alliance_headquarters": ["alliance_affects_members"],
    "research_archive": ["alliance_affects_tech_projects"],
    "expedition_office": ["alliance_affects_expedition_tech"],
    "logistics_depot": ["alliance_affects_pool"],
    "diplomacy_center": ["alliance_affects_diplomacy"],
}


def alliance_xp_for_level(level: int) -> int:
    """Total XP required to reach ``level`` (level 1 = 0)."""
    lvl = max(1, int(level))
    if lvl <= 1:
        return 0
    return ALLIANCE_XP_LEVEL_BASE * (lvl - 1) * lvl // 2


def alliance_level_from_xp(xp: int) -> int:
    total = max(0, int(xp))
    level = 1
    while alliance_xp_for_level(level + 1) <= total:
        level += 1
        if level > 99:
            break
    return level


def _scale_cost(base: Mapping[str, int], factor: float, target_level: int) -> Dict[str, int]:
    exponent = max(0, int(target_level) - 1)
    factor_d = Decimal(str(factor))
    max_digits = max(
        len(str(abs(int(base.get(key) or 0))))
        for key in ("metal", "crystal", "fuel_cells")
    )
    with localcontext() as ctx:
        ctx.prec = max(64, max_digits + exponent * 16 + 64)
        mult = factor_d ** exponent
        return {
            key: max(
                1,
                int(
                    (Decimal(int(base[key])) * mult).to_integral_value(
                        rounding=ROUND_HALF_EVEN
                    )
                ),
            )
            for key in ("metal", "crystal", "fuel_cells")
        }


def _project_duration(cfg: Mapping[str, Any], target_level: int) -> int:
    base = int(cfg.get("duration_sec") or 3600)
    factor = float(cfg.get("duration_factor") or 1.4)
    mult = factor ** max(0, int(target_level) - 1)
    return max(300, int(base * mult))


def building_level(buildings: Mapping[str, int], key: str) -> int:
    return max(0, int(buildings.get(key, 0) or 0))


def tech_level(techs: Mapping[str, int], key: str) -> int:
    return max(0, int(techs.get(key, 0) or 0))


def member_limit_from_buildings(buildings: Mapping[str, int]) -> int:
    hq = building_level(buildings, "alliance_headquarters")
    return BASE_MEMBER_LIMIT + HQ_MEMBERS_PER_LEVEL * hq


def _requirements_met(
    req: Optional[Mapping[str, Any]],
    *,
    alliance_level: int,
    buildings: Mapping[str, int],
    techs: Mapping[str, int],
) -> bool:
    if not req:
        return True
    need_level = int(req.get("alliance_level") or 0)
    if alliance_level < need_level:
        return False
    for b_key, need in (req.get("building") or {}).items():
        if building_level(buildings, str(b_key)) < int(need):
            return False
    for t_key, need in (req.get("tech") or {}).items():
        if tech_level(techs, str(t_key)) < int(need):
            return False
    return True


def project_cost_and_duration(
    kind: str,
    key: str,
    target_level: int,
    *,
    trade_coord_level: int = 0,
) -> Tuple[Dict[str, int], int]:
    cfg = (
        ALLIANCE_BUILDINGS.get(key)
        if kind == "building"
        else ALLIANCE_TECHNOLOGIES.get(key)
    )
    if not cfg:
        raise ValueError("invalid_project")
    lvl = max(1, int(target_level))
    cost = _scale_cost(cfg["base_cost"], float(cfg.get("cost_factor") or 1.8), lvl)
    duration = _project_duration(cfg, lvl)
    speed_pct = trade_coord_bonus_pct(trade_coord_level)
    duration = max(300, int(duration * (1.0 - speed_pct / 100.0)))
    return cost, duration


def available_projects(
    *,
    alliance_level: int,
    buildings: Mapping[str, int],
    techs: Mapping[str, int],
    trade_coord_level: int = 0,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for b_key, cfg in ALLIANCE_BUILDINGS.items():
        cur = building_level(buildings, b_key)
        nxt = cur + 1
        max_lvl = int(cfg.get("max_level") or 1)
        if nxt > max_lvl:
            continue
        if not _requirements_met(cfg.get("requires"), alliance_level=alliance_level, buildings=buildings, techs=techs):
            continue
        cost, duration = project_cost_and_duration("building", b_key, nxt, trade_coord_level=trade_coord_level)
        out.append(
            {
                "kind": "building",
                "key": b_key,
                "current_level": cur,
                "target_level": nxt,
                "cost": cost,
                "duration_sec": duration,
                "label_key": cfg.get("label_key"),
            }
        )
    for t_key, cfg in ALLIANCE_TECHNOLOGIES.items():
        cur = tech_level(techs, t_key)
        nxt = cur + 1
        max_lvl = int(cfg.get("max_level") or 1)
        if nxt > max_lvl:
            continue
        if not _requirements_met(cfg.get("requires"), alliance_level=alliance_level, buildings=buildings, techs=techs):
            continue
        cost, duration = project_cost_and_duration("tech", t_key, nxt, trade_coord_level=trade_coord_level)
        out.append(
            {
                "kind": "tech",
                "key": t_key,
                "current_level": cur,
                "target_level": nxt,
                "cost": cost,
                "duration_sec": duration,
                "label_key": cfg.get("label_key"),
            }
        )
    out.sort(key=lambda p: sum(int(p["cost"].get(k) or 0) for k in ("metal", "crystal", "fuel_cells")))
    return out


def pool_cap_from_projects(available: List[Dict[str, Any]], *, cap_bonus_pct: float = 0.0) -> Dict[str, int]:
    """Cap = sum of the two cheapest available project costs (+ optional % bonus)."""
    if not available:
        return {"metal": 100_000, "crystal": 100_000, "fuel_cells": 25_000}
    cheapest = available[:2]
    cap = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    for proj in cheapest:
        for res, amt in (proj.get("cost") or {}).items():
            if res in cap:
                cap[res] += int(amt)
    bonus = Decimal("1") + max(Decimal("0"), Decimal(str(cap_bonus_pct)))
    max_digits = max((len(str(abs(int(v)))) for v in cap.values()), default=1)
    with localcontext() as ctx:
        ctx.prec = max(64, max_digits + 64)
        return {
            key: max(
                1,
                int(
                    (Decimal(int(value)) * bonus).to_integral_value(
                        rounding=ROUND_HALF_EVEN
                    )
                ),
            )
            for key, value in cap.items()
        }


def compute_bonus_chips(techs: Mapping[str, int]) -> List[Dict[str, Any]]:
    chips: List[Dict[str, Any]] = []
    for t_key, cfg in ALLIANCE_TECHNOLOGIES.items():
        lvl = tech_level(techs, t_key)
        if lvl <= 0:
            continue
        per = float(cfg.get("bonus_pct_per_level") or 0)
        max_pct = float(cfg.get("bonus_max_pct") or 0)
        pct = min(max_pct, per * lvl)
        if pct <= 0:
            continue
        chips.append({"tech_key": t_key, "label_key": cfg.get("label_key"), "bonus_pct": round(pct, 1)})
    return chips


def _tech_bonus_pct(cfg: Mapping[str, Any], level: int) -> float:
    per = float(cfg.get("bonus_pct_per_level") or 0)
    max_pct = float(cfg.get("bonus_max_pct") or 0)
    return round(min(max_pct, per * max(0, int(level))), 1)


def _secondary_bonus_pct(cfg: Mapping[str, Any], level: int, *, per_key: str, max_key: str) -> float:
    per = float(cfg.get(per_key) or 0)
    if per <= 0:
        return 0.0
    max_pct = float(cfg.get(max_key) or 0)
    raw = per * max(0, int(level))
    return round(min(max_pct, raw) if max_pct > 0 else raw, 1)


def trade_coord_bonus_pct(trade_coord_level: int) -> float:
    """Pool-cap % and project-duration reduction % from Handelskoordination."""
    lvl = max(0, int(trade_coord_level))
    if lvl <= 0:
        return 0.0
    cfg = ALLIANCE_TECHNOLOGIES.get("trade_coordination") or {}
    return _tech_bonus_pct(cfg, lvl)


def project_effect_preview(
    kind: str,
    key: str,
    *,
    current_level: int,
    target_level: int,
    buildings: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """UI preview lines for alliance project cards (current vs next level)."""
    buildings = dict(buildings or {})
    cfg = ALLIANCE_BUILDINGS.get(key) if kind == "building" else ALLIANCE_TECHNOLOGIES.get(key)
    if not cfg:
        return {"desc_key": "", "effect_key": "", "current_value": None, "next_value": None}

    cur = max(0, int(current_level))
    nxt = max(1, int(target_level))
    desc_key = str(cfg.get("desc_key") or "")
    effect_key = str(cfg.get("effect_key") or key)
    current_value: Any = None
    next_value: Any = None

    if kind == "building":
        effect_key = key
        if key == "alliance_headquarters":
            current_value = member_limit_from_buildings({**buildings, key: cur})
            next_value = member_limit_from_buildings({**buildings, key: nxt})
        elif key == "logistics_depot":
            per = int(cfg.get("pool_cap_bonus_pct_per_level") or 0)
            current_value = per * cur
            next_value = per * nxt
        elif key == "diplomacy_center":
            current_value = cur >= 1
            next_value = True
        elif key == "research_archive":
            current_value = cur
            next_value = nxt
        elif key == "expedition_office":
            current_value = _secondary_bonus_pct(
                cfg,
                cur,
                per_key="expedition_success_bonus_pct_per_level",
                max_key="expedition_success_bonus_max_pct",
            )
            next_value = _secondary_bonus_pct(
                cfg,
                nxt,
                per_key="expedition_success_bonus_pct_per_level",
                max_key="expedition_success_bonus_max_pct",
            )
        else:
            current_value = cur
            next_value = nxt
    else:
        current_value = _tech_bonus_pct(cfg, cur)
        next_value = _tech_bonus_pct(cfg, nxt)

    success_current_value: Optional[float] = None
    success_next_value: Optional[float] = None
    if kind == "tech" and key == "expedition_coordination":
        success_current_value = _secondary_bonus_pct(
            cfg,
            cur,
            per_key="success_bonus_pct_per_level",
            max_key="success_bonus_max_pct",
        )
        success_next_value = _secondary_bonus_pct(
            cfg,
            nxt,
            per_key="success_bonus_pct_per_level",
            max_key="success_bonus_max_pct",
        )

    affects_keys: List[str] = []
    if kind == "building":
        affects_keys = list(AFFECTS_BY_BUILDING_KEY.get(key) or [])
    else:
        affects_keys = list(AFFECTS_BY_EFFECT_KEY.get(effect_key) or [])

    out: Dict[str, Any] = {
        "desc_key": desc_key,
        "effect_key": effect_key,
        "current_value": current_value,
        "next_value": next_value,
        "affects_keys": affects_keys,
    }
    if success_current_value is not None:
        out["success_current_value"] = success_current_value
        out["success_next_value"] = success_next_value
    return out


def describe_missing_requirements(
    req: Optional[Mapping[str, Any]],
    *,
    alliance_level: int,
    buildings: Mapping[str, int],
    techs: Mapping[str, int],
) -> List[Dict[str, Any]]:
    """Human-facing unlock blockers for locked alliance projects."""
    if not req:
        return []
    missing: List[Dict[str, Any]] = []
    need_level = int(req.get("alliance_level") or 0)
    if alliance_level < need_level:
        missing.append(
            {
                "type": "alliance_level",
                "key": str(need_level),
                "need": need_level,
                "have": alliance_level,
                "label_key": "alliance_req_alliance_level",
            }
        )
    for b_key, need in (req.get("building") or {}).items():
        have = building_level(buildings, str(b_key))
        if have < int(need):
            missing.append(
                {
                    "type": "building",
                    "key": str(b_key),
                    "need": int(need),
                    "have": have,
                    "label_key": ALLIANCE_BUILDINGS.get(str(b_key), {}).get("label_key") or f"alliance_building_{b_key}",
                }
            )
    for t_key, need in (req.get("tech") or {}).items():
        have = tech_level(techs, str(t_key))
        if have < int(need):
            missing.append(
                {
                    "type": "tech",
                    "key": str(t_key),
                    "need": int(need),
                    "have": have,
                    "label_key": ALLIANCE_TECHNOLOGIES.get(str(t_key), {}).get("label_key") or f"alliance_tech_{t_key}",
                }
            )
    return missing


def locked_next_projects(
    *,
    alliance_level: int,
    buildings: Mapping[str, int],
    techs: Mapping[str, int],
    trade_coord_level: int = 0,
) -> List[Dict[str, Any]]:
    """Next building/tech upgrades blocked by requirements (for unlock hints)."""
    locked: List[Dict[str, Any]] = []
    avail_keys = {
        (p["kind"], p["key"])
        for p in available_projects(
            alliance_level=alliance_level,
            buildings=buildings,
            techs=techs,
            trade_coord_level=trade_coord_level,
        )
    }

    def _append(kind: str, key: str, cfg: Mapping[str, Any], cur: int, nxt: int) -> None:
        if (kind, key) in avail_keys:
            return
        if nxt > int(cfg.get("max_level") or 1):
            return
        if _requirements_met(
            cfg.get("requires"),
            alliance_level=alliance_level,
            buildings=buildings,
            techs=techs,
        ):
            return
        cost, duration = project_cost_and_duration(kind, key, nxt, trade_coord_level=trade_coord_level)
        row = {
            "kind": kind,
            "key": key,
            "current_level": cur,
            "target_level": nxt,
            "cost": cost,
            "duration_sec": duration,
            "label_key": cfg.get("label_key"),
            "missing_requirements": describe_missing_requirements(
                cfg.get("requires"),
                alliance_level=alliance_level,
                buildings=buildings,
                techs=techs,
            ),
        }
        row["effect"] = project_effect_preview(
            kind,
            key,
            current_level=cur,
            target_level=nxt,
            buildings=buildings,
        )
        locked.append(row)

    for b_key, cfg in ALLIANCE_BUILDINGS.items():
        cur = building_level(buildings, b_key)
        _append("building", b_key, cfg, cur, cur + 1)
    for t_key, cfg in ALLIANCE_TECHNOLOGIES.items():
        cur = tech_level(techs, t_key)
        _append("tech", t_key, cfg, cur, cur + 1)

    locked.sort(key=lambda p: (0 if p["kind"] == "building" else 1, p["key"]))
    return locked


def enrich_available_projects(
    projects: List[Dict[str, Any]],
    *,
    buildings: Mapping[str, int],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for proj in projects:
        row = dict(proj)
        row["effect"] = project_effect_preview(
            str(row.get("kind") or ""),
            str(row.get("key") or ""),
            current_level=int(row.get("current_level") or 0),
            target_level=int(row.get("target_level") or 1),
            buildings=buildings,
        )
        out.append(row)
    return out
