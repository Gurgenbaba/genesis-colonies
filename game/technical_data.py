"""
GC-823 — unified technical-data display payloads (server authority).

All values for production transparency, bonuses, ROI, and formula steps are computed here.
Frontend renders ``display`` blocks only — no game-mechanics math in JS.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .economy_balance import power_upgrade_cost, upgrade_roi_hours
from .production_formula import (
    FERDI_GROWTH_RATE,
    LEVEL_GROWTH,
    LEVEL_GROWTH_RATE,
    STANDARD_PRODUCTION_PER_HOUR,
    ProductionContext,
    ProductionModifiers,
    calculate_resource_output,
    level_growth,
    mine_output,
    normalize_resource_type,
    production_context_from_resolver,
    research_modifier_for,
    standard_output,
    _lvl,
)

BUILDING_PRODUCTION_MAP: Dict[str, str] = {
    "metal_mine": "metal",
    "crystal_mine": "crystal",
    "fuel_cell_plant": "fuel_cells",
}

MINE_BUILDINGS = frozenset(BUILDING_PRODUCTION_MAP.keys())

# GC-823B — technical modal level schedule (early L0–L5, midgame current + next levels).
TECHNICAL_MILESTONE_LEVELS: Tuple[int, ...] = (10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120)
TECHNICAL_EARLY_GAME_MAX_LEVEL = 5
TECHNICAL_PREVIEW_AHEAD = 5

STORAGE_BUILDING_RESOURCES: Dict[str, str] = {
    "metal_storage": "metal",
    "crystal_storage": "crystal",
    "fuel_storage": "fuel_cells",
}


def technical_preview_levels(current: int, max_level: Optional[int] = None) -> List[int]:
    """
    Levels shown in the technical-data table.
    Early game: L0..L5. Midgame+: current and the next five upgrade levels (no milestone gaps).
    """
    cur = max(0, int(current))
    cap = int(max_level) if max_level is not None else None

    if cur <= TECHNICAL_EARLY_GAME_MAX_LEVEL:
        hi = TECHNICAL_EARLY_GAME_MAX_LEVEL
        if cap is not None:
            hi = min(hi, cap)
        levels = list(range(0, hi + 1))
    else:
        end = cur + TECHNICAL_PREVIEW_AHEAD
        if cap is not None:
            end = min(end, cap)
        levels = list(range(cur, end + 1))

    seen: set[int] = set()
    out: List[int] = []
    for lvl in levels:
        if lvl not in seen:
            seen.add(lvl)
            out.append(lvl)
    return sorted(out)


def technical_row_role(level: int, current: int, *, max_level: Optional[int] = None) -> str:
    """Row badge: current | next | preview."""
    lvl = int(level)
    cur = int(current)
    if lvl == cur:
        return "current"
    if lvl == cur + 1 and (max_level is None or cur < int(max_level)):
        return "next"
    return "preview"


def canonical_storage_capacity_for_building(
    building_type: str,
    level: int,
    *,
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
    panel_ctx=None,
) -> int:
    """Same cap path as buildings panel / game-state (EffectResolver + planet scope when available)."""
    btype = str(building_type)
    resource = STORAGE_BUILDING_RESOURCES.get(btype)
    if not resource:
        return 0
    lv = max(0, int(level))
    if panel_ctx is not None:
        caps = panel_ctx.resolver_at_target(btype, lv).get_storage_capacity()
    else:
        from .effects import EffectResolver

        bumped = dict(buildings)
        bumped[btype] = lv
        caps = EffectResolver(bumped, dict(research_levels or {})).get_storage_capacity()
    return int(caps.get(resource, 0) or 0)


def _mine_energy_draw_at(
    buildings: Mapping[str, int],
    building_type: str,
    level: int,
    research_levels: Mapping[str, int],
) -> int:
    from .effects import EffectResolver

    if int(level) <= 0:
        return 0
    bumped = dict(buildings)
    bumped[building_type] = int(level)
    resolver = EffectResolver(bumped, dict(research_levels or {}))
    return int(resolver.building_energy_draw(building_type, level=int(level)))


def _pct_display(factor: float) -> str:
    pct = int(round((float(factor) - 1.0) * 100))
    if pct > 0:
        return f"+{pct} %"
    if pct < 0:
        return f"{pct} %"
    return "0 %"


def _energy_display(ratio: float) -> str:
    return f"{int(round(max(0.0, min(1.0, float(ratio))) * 100))} %"


def _building_output_at(
    buildings: Mapping[str, int],
    building_type: str,
    level: int,
    ratio: float,
    research_levels: Mapping[str, int],
) -> int:
    from .logic import get_building_production_per_hour

    bumped = dict(buildings)
    bumped[building_type] = max(0, int(level))
    prod = get_building_production_per_hour(bumped, ratio, research=dict(research_levels or {}))
    return int(prod.get(building_type, 0) or 0)


def _production_delta_at(
    buildings: Mapping[str, int],
    building_type: str,
    level: int,
    ratio: float,
    research_levels: Mapping[str, int],
) -> int:
    lvl = max(0, int(level))
    if lvl < 1:
        return 0
    cur = _building_output_at(buildings, building_type, lvl, ratio, research_levels)
    prev = _building_output_at(buildings, building_type, lvl - 1, ratio, research_levels) if lvl > 1 else 0
    return max(0, cur - prev)


def _upgrade_roi_hours(
    building_type: str,
    level: int,
    *,
    metal_cost: int,
    crystal_cost: int,
    delta_per_hour: int,
    fuel_cells_cost: int = 0,
) -> Optional[float]:
    if str(building_type) not in MINE_BUILDINGS:
        return None
    roi = upgrade_roi_hours(
        metal_cost=int(metal_cost or 0),
        crystal_cost=int(crystal_cost or 0),
        fuel_cells_cost=int(fuel_cells_cost or 0),
        delta_per_hour=float(delta_per_hour or 0),
    )
    if not math.isfinite(roi):
        return None
    return round(roi, 1)


def _active_production_bonuses(
    resource_type: str,
    context: ProductionContext,
) -> List[Dict[str, Any]]:
    key = normalize_resource_type(resource_type)
    mods = ProductionModifiers(context)
    rows: List[Dict[str, Any]] = []

    slot_f = mods.slot_modifier()
    if abs(slot_f - 1.0) > 0.0005:
        rows.append({"label_key": "technical_bonus_slot", "display": _pct_display(slot_f)})

    if key == "fuel_cells":
        temp_f = mods.temperature_modifier()
        if abs(temp_f - 1.0) > 0.0005:
            rows.append({"label_key": "technical_bonus_temperature", "display": _pct_display(temp_f)})

    research = context.research or {}
    mining = _lvl(research, "mining_tech")
    drone = _lvl(research, "drone_tech")
    if key == "metal" and mining > 0:
        rows.append(
            {
                "label_key": "technical_bonus_mining",
                "display": f"+{int(round(mining * 3))} %",
            }
        )
    if key in ("metal", "crystal") and drone > 0:
        rows.append(
            {
                "label_key": "technical_bonus_drone",
                "display": f"+{int(round(drone * 2))} %",
            }
        )

    energy_f = mods.energy_modifier()
    rows.append({"label_key": "technical_bonus_energy", "display": _energy_display(energy_f)})

    overlay = max(0.0, float(context.directive_modifier or 1.0))
    research_part = research_modifier_for(key, research)
    empire_f = overlay
    if abs(empire_f - 1.0) > 0.0005:
        rows.append({"label_key": "technical_bonus_empire", "display": _pct_display(empire_f)})

    for label_key, factor in (
        ("technical_bonus_event", mods.event_modifier()),
        ("technical_bonus_planet", mods.planet_modifier()),
        ("technical_bonus_building", mods.building_modifier()),
    ):
        if abs(factor - 1.0) > 0.0005:
            rows.append({"label_key": label_key, "display": _pct_display(factor)})

    return rows


def _formula_steps(resource_type: str, context: ProductionContext) -> List[Dict[str, Any]]:
    key = normalize_resource_type(resource_type)
    lvl = max(0, int(context.level or 0))
    mods = ProductionModifiers(context)
    speed = max(0.0, float(context.production_speed or 1.0))
    mod_shared = mods.combined_without_energy()
    cfg = LEVEL_GROWTH[key]

    standard_part = int(standard_output(key) * speed * mod_shared)
    mine_part = 0
    if lvl > 0:
        mine_part = int(mine_output(key, lvl) * speed * mods.combined())

    steps: List[Dict[str, Any]] = [
        {
            "label_key": "technical_formula_standard",
            "detail": f"{STANDARD_PRODUCTION_PER_HOUR[key]:g} /h × modifiers (excl. energy)",
            "value_per_hour": standard_part,
        }
    ]
    if lvl > 0:
        steps.append(
            {
                "label_key": "technical_formula_base",
                "detail": f"{cfg['multiplier']:g} × level × {LEVEL_GROWTH_RATE}^level",
                "value_per_hour": int(mine_output(key, lvl) * speed),
            }
        )
        if abs(mods.energy_modifier() - 1.0) > 0.0005 or abs(mod_shared - 1.0) > 0.0005:
            steps.append(
                {
                    "label_key": "technical_formula_mine_after_mods",
                    "detail": "mine × modifiers (incl. energy)",
                    "value_per_hour": mine_part,
                }
            )

    total = int(calculate_resource_output(key, context))
    steps.append({"label_key": "technical_formula_total", "value_per_hour": total, "is_total": True})
    return steps


def _production_context_for_building(
    buildings: Mapping[str, int],
    building_type: str,
    level: int,
    ratio: float,
    research_levels: Mapping[str, int],
) -> ProductionContext:
    from .effects import EffectResolver

    bumped = dict(buildings)
    bumped[building_type] = max(0, int(level))
    resolver = EffectResolver(bumped, dict(research_levels or {}))
    resource = BUILDING_PRODUCTION_MAP[building_type]
    return production_context_from_resolver(
        resolver, resource, level=int(level), energy_ratio=float(ratio)
    )


def build_production_display(
    *,
    building_type: str,
    buildings: Mapping[str, int],
    level: int,
    ratio: float,
    research_levels: Mapping[str, int],
    metal_cost: int = 0,
    crystal_cost: int = 0,
    fuel_cells_cost: int = 0,
) -> Dict[str, Any]:
    resource = BUILDING_PRODUCTION_MAP[building_type]
    lvl = max(0, int(level))
    prev_lvl = max(0, lvl - 1)
    current = _building_output_at(buildings, building_type, prev_lvl, ratio, research_levels) if lvl > 0 else 0
    next_val = _building_output_at(buildings, building_type, lvl, ratio, research_levels) if lvl > 0 else 0
    delta = max(0, next_val - current)

    ctx = _production_context_for_building(buildings, building_type, lvl, ratio, research_levels)
    roi = _upgrade_roi_hours(
        building_type,
        lvl,
        metal_cost=metal_cost,
        crystal_cost=crystal_cost,
        delta_per_hour=delta,
        fuel_cells_cost=fuel_cells_cost,
    )

    return {
        "layout": "production",
        "table_layout": "production",
        "resource": resource,
        "unit": "/h",
        "current_per_hour": int(current),
        "next_per_hour": int(next_val),
        "value_at_level": int(next_val) if lvl > 0 else 0,
        "delta_per_hour": int(delta),
        "step_delta": int(delta),
        "delta_per_day": int(delta) * 24,
        "upgrade_roi_hours": roi,
        "active_bonuses": _active_production_bonuses(resource, ctx),
        "formula": {"steps": _formula_steps(resource, ctx)},
    }


def build_effect_percent_display(
    *,
    effect_kind: str,
    current: int,
    next_val: int,
    unit: str = "%",
    display_mode: str = "effect",
    label_key: str = "",
) -> Dict[str, Any]:
    cur = int(current or 0)
    nxt = int(next_val or 0)
    if effect_kind == "bonus_percent":
        delta = max(0, nxt - cur)
    else:
        delta = max(0, cur - nxt)
    return {
        "layout": "effect_percent",
        "table_layout": "effect_percent",
        "effect_kind": effect_kind,
        "display_mode": display_mode,
        "label_key": label_key,
        "unit": unit,
        "current": cur,
        "next": nxt,
        "value_at_level": cur,
        "delta": delta,
        "step_delta": delta,
    }


def _impact_delta_pct(current: float, nxt: float) -> Optional[float]:
    cur = float(current or 0)
    if cur <= 0:
        return None
    return round(100.0 * (float(nxt) - cur) / cur, 1)


def build_impact_summary(
    *,
    blurb_key: str = "",
    current_label_key: str = "techcard_current",
    current_value: Any = None,
    current_unit: str = "",
    next_label_key: str = "techcard_next_level",
    next_from: Any = None,
    next_to: Any = None,
    next_delta: Any = None,
    next_delta_pct: Optional[float] = None,
    next_unit: str = "",
    affects: Optional[List[Dict[str, str]]] = None,
    example: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """GC-TECHCARD-UX-001 — canonical 4-question impact block (server authority)."""
    unit = str(next_unit or current_unit or "")
    cur_val = current_value
    from_v = next_from if next_from is not None else cur_val
    to_v = next_to
    delta_v = next_delta
    if delta_v is None and from_v is not None and to_v is not None:
        try:
            delta_v = int(to_v) - int(from_v)
        except (TypeError, ValueError):
            delta_v = None
    pct = next_delta_pct
    if pct is None and from_v is not None and to_v is not None:
        try:
            pct = _impact_delta_pct(float(from_v), float(to_v))
        except (TypeError, ValueError):
            pct = None
    impact: Dict[str, Any] = {
        "blurb_key": str(blurb_key or ""),
        "current": {
            "label_key": str(current_label_key or "techcard_current"),
            "value": cur_val,
            "unit": unit,
        },
        "next": {
            "label_key": str(next_label_key or "techcard_next_level"),
            "from": from_v,
            "to": to_v,
            "delta": delta_v,
            "delta_pct": pct,
            "unit": unit,
        },
        "affects": list(affects or []),
    }
    if example:
        impact["example"] = dict(example)
    return impact


def impact_from_rate(
    *,
    blurb_key: str,
    current_rate: int,
    next_rate: int,
    unit: str = "/h",
    affects: Optional[List[Dict[str, str]]] = None,
    kind: str = "rate",
) -> Dict[str, Any]:
    cur = max(0, int(current_rate or 0))
    nxt = max(0, int(next_rate or 0))
    delta = nxt - cur
    return build_impact_summary(
        blurb_key=blurb_key,
        current_value=cur,
        current_unit=unit,
        next_from=cur,
        next_to=nxt,
        next_delta=delta,
        next_unit=unit,
        affects=affects,
        example={"kind": kind, "current": cur, "next": nxt, "delta": delta, "unit": unit},
    )


def impact_from_capacity(
    *,
    blurb_key: str,
    current_cap: int,
    next_cap: int,
    affects: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    return impact_from_rate(
        blurb_key=blurb_key,
        current_rate=current_cap,
        next_rate=next_cap,
        unit="",
        affects=affects,
        kind="capacity",
    )


def impact_from_duration_seconds(
    *,
    blurb_key: str,
    current_seconds: int,
    next_seconds: int,
    affects: Optional[List[Dict[str, str]]] = None,
    extra_example: Optional[Dict[str, Any]] = None,
    current_label_key: str = "techcard_current",
) -> Dict[str, Any]:
    cur = max(0, int(current_seconds or 0))
    nxt = max(0, int(next_seconds or 0))
    saved = max(0, cur - nxt)
    pct = _impact_delta_pct(cur, nxt)  # negative when faster
    example: Dict[str, Any] = {
        "kind": "duration",
        "seconds_current": cur,
        "seconds_next": nxt,
        "saved_seconds": saved,
        "delta_pct": pct,
    }
    if extra_example:
        example.update(extra_example)
    return build_impact_summary(
        blurb_key=blurb_key,
        current_label_key=current_label_key,
        current_value=cur,
        current_unit="s",
        next_from=cur,
        next_to=nxt,
        next_delta=-saved,
        next_delta_pct=pct,
        next_unit="s",
        affects=affects,
        example=example,
    )


_PRODUCTION_AFFECTS: Dict[str, List[Dict[str, str]]] = {
    "metal_mine": [
        {"label_key": "building_metal_mine"},
        {"label_key": "nav_overview"},
    ],
    "crystal_mine": [
        {"label_key": "building_crystal_mine"},
        {"label_key": "nav_overview"},
    ],
    "fuel_cell_plant": [
        {"label_key": "building_fuel_cell_plant"},
        {"label_key": "nav_overview"},
    ],
}

_STORAGE_AFFECTS: Dict[str, List[Dict[str, str]]] = {
    "metal_storage": [{"label_key": "building_metal_storage"}, {"label_key": "nav_overview"}],
    "crystal_storage": [{"label_key": "building_crystal_storage"}, {"label_key": "nav_overview"}],
    "fuel_storage": [{"label_key": "building_fuel_storage"}, {"label_key": "nav_overview"}],
}


def _pick_longest_build_reference(
    resolver,
    buildings: Mapping[str, int],
) -> Tuple[str, int]:
    """Choose the planet's longest next upgrade (excludes nanofactory self-upgrade)."""
    from .buildings import BUILDING_ORDER

    best_building = "metal_mine"
    best_target = max(1, int(buildings.get("metal_mine", 0) or 0) + 1)
    best_seconds = -1
    for btype in BUILDING_ORDER:
        if btype == "nanofactory":
            continue
        cur_lvl = int(buildings.get(btype, 0) or 0)
        try:
            max_lvl = int(resolver.get_max_building_level(btype))
        except Exception:
            max_lvl = cur_lvl + 1
        if cur_lvl >= max_lvl:
            continue
        target = cur_lvl + 1
        try:
            secs = int(resolver.get_build_time_seconds(btype, target))
        except Exception:
            continue
        if secs > best_seconds:
            best_seconds = secs
            best_building = btype
            best_target = target
    return best_building, int(best_target)


def build_nanofactory_time_preview(
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
    *,
    nano_level: Optional[int] = None,
    settings: Optional[Mapping[str, Any]] = None,
    player_id: Optional[int] = None,
    planet_id: Optional[int] = None,
    planet_position: Optional[int] = None,
    galaxy_id: Optional[int] = None,
    conn=None,
    base_resolver=None,
) -> Dict[str, Any]:
    """GC-NANO-001 — server-only nano speed + reference build-time preview (no frontend math)."""
    from .effects import EffectResolver

    bld = {str(k): int(v or 0) for k, v in dict(buildings or {}).items()}
    research = {str(k): int(v or 0) for k, v in dict(research_levels or {}).items()}
    cur_nano = int(nano_level) if nano_level is not None else int(bld.get("nanofactory", 0) or 0)
    cur_nano = max(0, cur_nano)
    next_nano = cur_nano + 1

    def _clone(nano_lvl: int):
        clone_bld = dict(bld)
        clone_bld["nanofactory"] = int(nano_lvl)
        if base_resolver is not None:
            return EffectResolver(
                clone_bld,
                research,
                settings=getattr(base_resolver, "_settings", None),
                player_id=getattr(base_resolver, "player_id", None),
                planet_id=getattr(base_resolver, "planet_id", None),
                planet_position=getattr(base_resolver, "planet_position", None),
                galaxy_id=getattr(base_resolver, "galaxy_id", None),
                conn=getattr(base_resolver, "_conn", None),
                skip_inventory_boosters=bool(
                    getattr(base_resolver, "_skip_inventory_boosters", False)
                ),
            )
        return EffectResolver(
            clone_bld,
            research,
            settings=dict(settings) if settings is not None else None,
            player_id=player_id,
            planet_id=planet_id,
            planet_position=planet_position,
            galaxy_id=galaxy_id,
            conn=conn,
        )

    r0 = _clone(0)
    r_cur = _clone(cur_nano)
    r_next = _clone(next_nano)

    # Example = longest next upgrade under current nano (most tangible savings).
    ref_building, ref_target = _pick_longest_build_reference(r_cur, bld)
    ref_label_key = f"building_{ref_building}"

    seconds_l0 = int(r0.get_build_time_seconds(ref_building, ref_target))
    seconds_cur = int(r_cur.get_build_time_seconds(ref_building, ref_target))
    seconds_next = int(r_next.get_build_time_seconds(ref_building, ref_target))

    speed_cur = float(EffectResolver.nanofactory_build_speed(cur_nano))
    speed_next = float(EffectResolver.nanofactory_build_speed(next_nano))
    saved_vs_l0 = max(0, seconds_l0 - seconds_cur)
    saved_marginal = max(0, seconds_cur - seconds_next)
    marginal_pct = 0.0
    if seconds_cur > 0:
        marginal_pct = round(100.0 * float(saved_marginal) / float(seconds_cur), 2)

    r_cur.get_modifiers()
    source_labels: List[str] = []
    for src in getattr(r_cur, "_sources", []) or []:
        if src.get("status") != "active":
            continue
        label = str(src.get("key") or src.get("label") or src.get("source") or "").strip()
        if label:
            source_labels.append(label)

    build_speed = 1.0
    try:
        build_speed = float(r_cur.build_speed_setting())
    except Exception:
        build_speed = 1.0

    return {
        "nano_level": cur_nano,
        "nano_level_next": next_nano,
        "speed_current": round(speed_cur, 2),
        "speed_next": round(speed_next, 2),
        "speed_bonus_pct_current": int(EffectResolver.nanofactory_build_speed_bonus_pct(cur_nano)),
        "speed_bonus_pct_next": int(EffectResolver.nanofactory_build_speed_bonus_pct(next_nano)),
        "reference_building": ref_building,
        "reference_building_label_key": ref_label_key,
        "reference_target_level": int(ref_target),
        "seconds_nano_0": seconds_l0,
        "seconds_current": seconds_cur,
        "seconds_next": seconds_next,
        "saved_vs_l0_seconds": int(saved_vs_l0),
        "saved_marginal_seconds": int(saved_marginal),
        "marginal_duration_reduction_pct": marginal_pct,
        "modifiers": {
            "nanofactory_level": cur_nano,
            "buildtime_tech_level": int(research.get("buildtime_tech", 0) or 0),
            "universe_build_speed": build_speed,
            "sources": source_labels,
        },
    }


def build_nanofactory_time_display(preview: Mapping[str, Any]) -> Dict[str, Any]:
    """Display block for nanofactory technical modal / summary."""
    p = dict(preview or {})
    return {
        "layout": "nanofactory_build_time",
        "table_layout": "effect_percent",
        "effect_kind": "bonus_percent",
        "unit": "%",
        "current": int(p.get("speed_bonus_pct_current") or 0),
        "next": int(p.get("speed_bonus_pct_next") or 0),
        "value_at_level": int(p.get("speed_bonus_pct_current") or 0),
        "delta": max(
            0,
            int(p.get("speed_bonus_pct_next") or 0) - int(p.get("speed_bonus_pct_current") or 0),
        ),
        "step_delta": max(
            0,
            int(p.get("speed_bonus_pct_next") or 0) - int(p.get("speed_bonus_pct_current") or 0),
        ),
        "nano_time_preview": p,
    }


def build_consumption_percent_display(
    *,
    consumption_at_level: int,
    consumption_prev: int,
    label_key: str = "technical_energy_consumption",
) -> Dict[str, Any]:
    cur = int(consumption_at_level)
    prev = int(consumption_prev)
    step = cur - prev
    return {
        "layout": "effect_percent",
        "table_layout": "effect_percent",
        "effect_kind": "consumption_percent",
        "display_mode": "consumption",
        "label_key": label_key,
        "unit": "%",
        "current": cur,
        "next": cur,
        "value_at_level": cur,
        "delta": abs(step),
        "step_delta": step,
    }


def build_storage_display(
    *,
    current: int,
    next_val: int,
    resource: str,
    at_max_level: bool = False,
    capacity_at_level: int | None = None,
    step_delta: int | None = None,
) -> Dict[str, Any]:
    cap_at = int(capacity_at_level if capacity_at_level is not None else next_val)
    cur = int(current or 0)
    nxt = int(next_val or 0)
    step = int(step_delta) if step_delta is not None else max(0, nxt - cur)
    return {
        "layout": "storage",
        "table_layout": "storage",
        "resource": resource,
        "current": cur,
        "next": nxt,
        "capacity_at_level": cap_at,
        "value_at_level": cap_at,
        "delta": step,
        "step_delta": step,
        "at_max_level": bool(at_max_level),
    }


def build_energy_display(*, current: int, next_val: int, level: int = 0) -> Dict[str, Any]:
    cur = int(current or 0)
    nxt = int(next_val or 0)
    step = max(0, nxt - cur)
    return {
        "layout": "energy",
        "table_layout": "energy",
        "current": cur,
        "next": nxt,
        "value_at_level": nxt if int(level) > 0 else cur,
        "delta": step,
        "step_delta": step,
    }


def build_yard_display(
    *,
    level: int,
    batch_capacity: int,
    reduction_current: int,
    reduction_next: int,
) -> Dict[str, Any]:
    lvl = max(0, int(level))
    red_at = int(reduction_next) if lvl > 0 else 0
    return {
        "layout": "yard",
        "table_layout": "yard",
        "batch_capacity": int(batch_capacity),
        "capacity_at_level": int(batch_capacity),
        "build_time_reduction_current": int(reduction_current),
        "build_time_reduction_next": int(reduction_next),
        "reduction_at_level": red_at,
        "build_time_reduction_delta": max(0, int(reduction_next) - int(reduction_current)),
        "level": lvl,
    }


def enrich_building_technical_row(
    row: Dict[str, Any],
    building_type: str,
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
    ratio: float,
    level: int,
    *,
    panel_ctx=None,
) -> None:
    """Attach unified ``display`` block to a building technical-data level row."""
    lvl = max(0, int(level))
    prev = max(0, lvl - 1)
    btype = str(building_type)
    metal_cost = int(row.get("cost_metal") or 0)
    crystal_cost = int(row.get("cost_crystal") or 0)

    if btype in MINE_BUILDINGS:
        display = build_production_display(
            building_type=btype,
            buildings=buildings,
            level=lvl,
            ratio=ratio,
            research_levels=research_levels,
            metal_cost=metal_cost,
            crystal_cost=crystal_cost,
        )
        row["production_delta_per_hour"] = display["delta_per_hour"]
        row["upgrade_roi_hours"] = display.get("upgrade_roi_hours")
        energy_at = _mine_energy_draw_at(buildings, btype, lvl, research_levels)
        energy_prev = _mine_energy_draw_at(buildings, btype, prev, research_levels)
        display["energy_at_level"] = -energy_at if lvl > 0 else 0
        display["energy_step_delta"] = -(energy_at - energy_prev) if lvl > 0 else 0
        if row.get("upgrade_roi_hours") is not None:
            display["upgrade_roi_hours"] = row["upgrade_roi_hours"]
        row["display"] = display
        return

    kind = str(row.get("effect_kind") or "level")

    if kind == "production":
        resource = str(row.get("effect_resource") or "")
        display = build_production_display(
            building_type=btype,
            buildings=buildings,
            level=lvl,
            ratio=ratio,
            research_levels=research_levels,
            metal_cost=metal_cost,
            crystal_cost=crystal_cost,
        )
        row["display"] = display
        return

    if kind in ("bonus_percent", "reduction_percent"):
        from .buildings import command_center_nanofactory_build_bonus_pct
        from .effects import EffectResolver

        bumped = dict(buildings)
        bumped[btype] = lvl
        r_prev = EffectResolver({**buildings, btype: prev}, dict(research_levels or {}))
        r_cur = EffectResolver(bumped, dict(research_levels or {}))

        if btype == "nanofactory":
            # Row at level L: preview as if nano is at L-1 → L (matches effect_current/next pattern).
            base = getattr(panel_ctx, "resolver", None) if panel_ctx is not None else None
            preview = build_nanofactory_time_preview(
                buildings,
                research_levels,
                nano_level=prev,
                base_resolver=base,
            )
            row["effect_current"] = int(preview["speed_bonus_pct_current"])
            row["effect_next"] = int(preview["speed_bonus_pct_next"])
            row["effect_delta"] = max(0, row["effect_next"] - row["effect_current"])
            row["nano_time_preview"] = preview
            row["display"] = build_nanofactory_time_display(preview)
            return

        if btype == "research_lab":
            cur_pct = int(round((r_prev.research_lab_bonus() - 1.0) * 100))
            nxt_pct = int(round((r_cur.research_lab_bonus() - 1.0) * 100))
        elif btype == "academy":
            cur_pct = max(0, prev) * 5
            nxt_pct = max(0, lvl) * 5
        elif btype == "command_center":
            cur_pct = command_center_nanofactory_build_bonus_pct(prev)
            nxt_pct = command_center_nanofactory_build_bonus_pct(lvl)
        elif btype == "terraformer":
            cur_pct = 5 * prev
            nxt_pct = 5 * lvl
        else:
            cur_pct = int(row.get("effect_value") or 0)
            nxt_pct = cur_pct

        row["effect_current"] = cur_pct
        row["effect_next"] = nxt_pct
        row["effect_delta"] = max(0, nxt_pct - cur_pct) if kind == "bonus_percent" else max(0, cur_pct - nxt_pct)
        row["display"] = build_effect_percent_display(
            effect_kind=kind,
            current=cur_pct,
            next_val=nxt_pct,
        )
        return

    if kind == "storage":
        resource = str(row.get("effect_resource") or "metal")
        cap_at = canonical_storage_capacity_for_building(
            btype,
            lvl,
            buildings=buildings,
            research_levels=research_levels,
            panel_ctx=panel_ctx,
        )
        cap_prev = (
            canonical_storage_capacity_for_building(
                btype,
                lvl - 1,
                buildings=buildings,
                research_levels=research_levels,
                panel_ctx=panel_ctx,
            )
            if lvl > 0
            else 0
        )
        step = cap_at - cap_prev if lvl > 0 else 0
        row["effect_value"] = cap_at
        row["display"] = build_storage_display(
            current=cap_prev if lvl > 0 else cap_at,
            next_val=cap_at,
            resource=resource,
            at_max_level=(lvl > 0 and cap_at == cap_prev),
            capacity_at_level=cap_at,
            step_delta=step,
        )
        return

    if kind == "energy":
        from .effects import EffectResolver

        def _energy_at(lv: int) -> int:
            b = dict(buildings)
            b[btype] = lv
            et, _ = EffectResolver(b, dict(research_levels or {})).compute_energy()
            return int(et)

        row["display"] = build_energy_display(
            current=_energy_at(prev),
            next_val=_energy_at(lvl),
            level=lvl,
        )
        return

    if kind == "yard_production":
        from .shipyard import BUILD_TIME_LEVEL_FACTOR

        lvl_i = max(1, lvl)
        prev_i = max(1, prev) if prev > 0 else 1
        red_cur = int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (prev_i - 1)) * 100)) if prev_i > 1 else 0
        red_nxt = int(round((1 - BUILD_TIME_LEVEL_FACTOR ** (lvl_i - 1)) * 100)) if lvl_i > 1 else 0
        display = build_yard_display(
            level=lvl_i,
            batch_capacity=int(row.get("yard_batch_capacity") or row.get("effect_value") or 0),
            reduction_current=red_cur,
            reduction_next=red_nxt,
        )
        from .shipyard import orbital_production_batch_capacity

        cap_cur = int(display.get("capacity_at_level") or display.get("batch_capacity") or 0)
        cap_prev = orbital_production_batch_capacity(max(1, prev)) if prev > 0 else 0
        display["capacity_step_delta"] = max(0, cap_cur - cap_prev) if lvl > 0 else 0
        time_s = int(row.get("time_seconds") or 0)
        if lvl >= 1 and time_s > 0:
            display["upgrade_roi_hours"] = round(time_s / 3600.0, 1)
        row["display"] = display
        return

    row["display"] = {"layout": "plain", "effect_kind": kind, "value": row.get("effect_value")}


def enrich_research_technical_row(row: Dict[str, Any], tech_key: str, level: int) -> None:
    """Attach unified ``display`` for research technical-data rows."""
    lvl = max(0, int(level))
    prev = max(0, lvl - 1)
    key = str(tech_key)

    if key == "energy_tech":
        from .effects import EffectResolver

        red = int(EffectResolver.mine_energy_reduction_pct(lvl))
        red_prev = int(EffectResolver.mine_energy_reduction_pct(prev))
        row["display"] = build_consumption_percent_display(
            consumption_at_level=100 - red,
            consumption_prev=100 - red_prev,
        )
        row["effect_current"] = 100 - red
        row["effect_next"] = 100 - red
        row["effect_delta"] = abs((100 - red) - (100 - red_prev))
        return

    effect = row.get("effect_kind") or "level"
    if effect in ("bonus_percent", "reduction_percent"):
        cur_val = int(row.get("effect_current") if row.get("effect_current") is not None else 0)
        nxt_val = int(row.get("effect_next") if row.get("effect_next") is not None else cur_val)
        step = int(row.get("effect_delta") if row.get("effect_delta") is not None else 0)
        if lvl == 0:
            value_at = 0
            step = 0
        else:
            value_at = nxt_val
        row["effect_current"] = cur_val
        row["effect_next"] = nxt_val
        row["effect_delta"] = step
        row["display"] = build_effect_percent_display(
            effect_kind=str(effect),
            current=cur_val if lvl > 0 else 0,
            next_val=nxt_val if lvl > 0 else 0,
            label_key=str(row.get("effect_metric_key") or ""),
        )
        row["display"]["value_at_level"] = value_at
        row["display"]["step_delta"] = step
        return

    row["display"] = {
        "layout": "plain",
        "table_layout": "standard",
        "effect_kind": effect,
        "value": row.get("effect_value"),
        "metric_key": row.get("effect_metric_key") or "",
    }


def resolve_building_impact(
    *,
    building_type: str,
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
    current: int,
    display: Mapping[str, Any],
    panel_ctx=None,
) -> Optional[Dict[str, Any]]:
    """Build TECHCARD impact for a building summary (GC-TECHCARD-UX-001)."""
    from .effects import EffectResolver

    btype = str(building_type)
    cur = max(0, int(current))
    blurb = f"desc_{btype}"
    layout = str(display.get("layout") or "")

    if btype in MINE_BUILDINGS or layout == "production":
        cur_rate = int(display.get("current_per_hour") or 0)
        nxt_rate = int(display.get("next_per_hour") or 0)
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=cur_rate,
            next_rate=nxt_rate,
            unit="/h",
            affects=_PRODUCTION_AFFECTS.get(btype, [{"label_key": f"building_{btype}"}, {"label_key": "nav_overview"}]),
        )

    if btype in STORAGE_BUILDING_RESOURCES or layout == "storage":
        cur_cap = int(display.get("current") or 0)
        nxt_cap = int(display.get("next") or display.get("capacity_at_level") or 0)
        return impact_from_capacity(
            blurb_key=blurb,
            current_cap=cur_cap,
            next_cap=nxt_cap,
            affects=_STORAGE_AFFECTS.get(btype, [{"label_key": f"building_{btype}"}]),
        )

    if layout == "energy" or btype == "solar_plant":
        cur_e = int(display.get("current") or 0)
        nxt_e = int(display.get("next") or 0)
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=cur_e,
            next_rate=nxt_e,
            unit="",
            affects=[{"label_key": "building_solar_plant"}, {"label_key": "energy"}],
            kind="energy",
        )

    if layout == "yard" or btype in ("orbital_shipyard", "defense_factory"):
        cur_cap = int(display.get("batch_capacity_current") or 0)
        nxt_cap = int(display.get("batch_capacity") or display.get("capacity_at_level") or 0)
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=cur_cap,
            next_rate=nxt_cap,
            unit="",
            affects=[{"label_key": f"building_{btype}"}, {"label_key": "nav_shipyard" if btype == "orbital_shipyard" else "nav_defense"}],
            kind="capacity",
        )

    if btype == "nanofactory" or layout == "nanofactory_build_time":
        preview = display.get("nano_time_preview") or {}
        if not preview:
            base = getattr(panel_ctx, "resolver", None) if panel_ctx is not None else None
            preview = build_nanofactory_time_preview(
                buildings, research_levels, nano_level=cur, base_resolver=base
            )
        ref_key = str(
            preview.get("reference_building_label_key")
            or f"building_{preview.get('reference_building') or 'metal_mine'}"
        )
        return impact_from_duration_seconds(
            blurb_key=blurb,
            current_seconds=int(preview.get("seconds_current") or 0),
            next_seconds=int(preview.get("seconds_next") or 0),
            current_label_key=ref_key,
            affects=[
                {"label_key": ref_key},
                {"label_key": "nav_buildings"},
                {"label_key": "nav_overview"},
            ],
            extra_example={
                "speed_current": preview.get("speed_current"),
                "speed_next": preview.get("speed_next"),
                "saved_vs_l0_seconds": preview.get("saved_vs_l0_seconds"),
                "seconds_nano_0": preview.get("seconds_nano_0"),
                "marginal_duration_reduction_pct": preview.get("marginal_duration_reduction_pct"),
                "reference_building": preview.get("reference_building"),
                "reference_building_label_key": ref_key,
                "reference_target_level": preview.get("reference_target_level"),
            },
        )

    if btype == "command_center":
        # CC only accelerates nanofactory upgrades — never other buildings.
        base = getattr(panel_ctx, "resolver", None) if panel_ctx is not None else None

        def _nano_upgrade_seconds(cc_level: int) -> int:
            bld = dict(buildings or {})
            bld["command_center"] = max(0, int(cc_level))
            nano_lvl = int(bld.get("nanofactory", 0) or 0)
            target = nano_lvl + 1
            if base is not None:
                er = EffectResolver(
                    bld,
                    dict(research_levels or {}),
                    settings=getattr(base, "_settings", None),
                    player_id=getattr(base, "player_id", None),
                    planet_id=getattr(base, "planet_id", None),
                    planet_position=getattr(base, "planet_position", None),
                    galaxy_id=getattr(base, "galaxy_id", None),
                    conn=getattr(base, "_conn", None),
                )
            else:
                er = EffectResolver(bld, dict(research_levels or {}))
            return int(er.get_build_time_seconds("nanofactory", target))

        t_cur = _nano_upgrade_seconds(cur)
        t_nxt = _nano_upgrade_seconds(cur + 1)
        return impact_from_duration_seconds(
            blurb_key=blurb,
            current_seconds=t_cur,
            next_seconds=t_nxt,
            affects=[{"label_key": "building_nanofactory"}],
            extra_example={"scope": "nanofactory_upgrade_only"},
        )

    if btype in ("research_lab", "academy"):
        base = getattr(panel_ctx, "resolver", None) if panel_ctx is not None else None
        research = dict(research_levels or {})

        def _research_seconds(bld_levels: Mapping[str, int]) -> int:
            if base is not None:
                er = EffectResolver(
                    dict(bld_levels),
                    research,
                    settings=getattr(base, "_settings", None),
                    player_id=getattr(base, "player_id", None),
                    planet_id=getattr(base, "planet_id", None),
                    planet_position=getattr(base, "planet_position", None),
                    galaxy_id=getattr(base, "galaxy_id", None),
                    conn=getattr(base, "_conn", None),
                )
            else:
                er = EffectResolver(dict(bld_levels), research)
            # Reference: next level of energy_tech (always defined).
            tech_lvl = int(research.get("energy_tech", 0) or 0) + 1
            return int(er.get_research_time_seconds("energy_tech", tech_lvl))

        bld_cur = dict(buildings or {})
        bld_nxt = dict(bld_cur)
        bld_nxt[btype] = cur + 1
        return impact_from_duration_seconds(
            blurb_key=blurb,
            current_seconds=_research_seconds(bld_cur),
            next_seconds=_research_seconds(bld_nxt),
            affects=[{"label_key": "nav_research"}, {"label_key": f"building_{btype}"}],
            extra_example={"reference_tech": "energy_tech"},
        )

    if btype == "terraformer":
        # Storage capacity bonus: metal storage as concrete example.
        bld_cur = dict(buildings or {})
        bld_nxt = dict(bld_cur)
        bld_nxt["terraformer"] = cur + 1
        cap_cur = canonical_storage_capacity_for_building(
            "metal_storage",
            int(bld_cur.get("metal_storage", 0) or 0),
            buildings=bld_cur,
            research_levels=research_levels,
            panel_ctx=panel_ctx,
        )
        cap_nxt = canonical_storage_capacity_for_building(
            "metal_storage",
            int(bld_nxt.get("metal_storage", 0) or 0),
            buildings=bld_nxt,
            research_levels=research_levels,
            panel_ctx=panel_ctx,
        )
        return impact_from_capacity(
            blurb_key=blurb,
            current_cap=cap_cur,
            next_cap=cap_nxt,
            affects=[{"label_key": "building_metal_storage"}, {"label_key": "building_terraformer"}],
        )

    if btype in ("geothermal_nexus", "planet_core_nexus"):
        base = getattr(panel_ctx, "resolver", None) if panel_ctx is not None else None

        def _max_mine(bld: Mapping[str, int]) -> int:
            if base is not None:
                er = EffectResolver(
                    dict(bld),
                    dict(research_levels or {}),
                    settings=getattr(base, "_settings", None),
                    player_id=getattr(base, "player_id", None),
                    planet_id=getattr(base, "planet_id", None),
                    planet_position=getattr(base, "planet_position", None),
                    galaxy_id=getattr(base, "galaxy_id", None),
                    conn=getattr(base, "_conn", None),
                )
            else:
                er = EffectResolver(dict(bld), dict(research_levels or {}))
            return int(er.get_max_building_level("metal_mine"))

        bld_cur = dict(buildings or {})
        bld_nxt = dict(bld_cur)
        bld_nxt[btype] = cur + 1
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=_max_mine(bld_cur),
            next_rate=_max_mine(bld_nxt),
            unit="",
            affects=[{"label_key": "building_metal_mine"}, {"label_key": f"building_{btype}"}],
            kind="capacity",
        )

    return None


def build_building_technical_summary(
    *,
    building_type: str,
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
    ratio: float,
    current: int,
    max_level: int,
    current_row: Optional[Dict[str, Any]],
    next_row: Optional[Dict[str, Any]],
    panel_ctx=None,
) -> Dict[str, Any]:
    """Top-of-modal summary for the next building upgrade (or max level)."""
    cur = max(0, int(current))
    cap = max(0, int(max_level))
    if cur >= cap or not next_row:
        return {"at_max_level": True, "layout": "max_level", "level": cur}

    btype = str(building_type)
    if btype in STORAGE_BUILDING_RESOURCES and panel_ctx is not None:
        resource = STORAGE_BUILDING_RESOURCES[btype]
        cap_from = canonical_storage_capacity_for_building(
            btype,
            cur,
            buildings=buildings,
            research_levels=research_levels,
            panel_ctx=panel_ctx,
        )
        cap_to = canonical_storage_capacity_for_building(
            btype,
            cur + 1,
            buildings=buildings,
            research_levels=research_levels,
            panel_ctx=panel_ctx,
        )
        display = build_storage_display(
            current=cap_from,
            next_val=cap_to,
            resource=resource,
            capacity_at_level=cap_to,
            step_delta=max(0, cap_to - cap_from),
        )
        out = {
            "at_max_level": False,
            "layout": "storage",
            "from_level": cur,
            "to_level": cur + 1,
            "display": display,
            "cost_metal": int(next_row.get("cost_metal") or 0),
            "cost_crystal": int(next_row.get("cost_crystal") or 0),
            "time_seconds": int(next_row.get("time_seconds") or 0),
            "upgrade_roi_hours": display.get("upgrade_roi_hours"),
            "active_bonuses": [],
            "formula": None,
        }
        impact = resolve_building_impact(
            building_type=btype,
            buildings=buildings,
            research_levels=research_levels,
            current=cur,
            display=display,
            panel_ctx=panel_ctx,
        )
        if impact:
            out["impact"] = impact
        return out

    display = dict(next_row.get("display") or {})
    layout = str(display.get("layout") or "")
    if layout == "yard" and current_row:
        cur_d = current_row.get("display") or {}
        display["batch_capacity_current"] = cur_d.get("capacity_at_level")
        display["build_time_reduction_current"] = cur_d.get("reduction_at_level")
        display["batch_capacity"] = display.get("capacity_at_level")
        display["build_time_reduction_next"] = display.get("reduction_at_level")

    out = {
        "at_max_level": False,
        "layout": layout or "plain",
        "from_level": cur,
        "to_level": cur + 1,
        "display": display,
        "cost_metal": int(next_row.get("cost_metal") or 0),
        "cost_crystal": int(next_row.get("cost_crystal") or 0),
        "time_seconds": int(next_row.get("time_seconds") or 0),
        "upgrade_roi_hours": display.get("upgrade_roi_hours"),
        "active_bonuses": display.get("active_bonuses") or [],
        "formula": display.get("formula"),
    }
    impact = resolve_building_impact(
        building_type=btype,
        buildings=buildings,
        research_levels=research_levels,
        current=cur,
        display=display,
        panel_ctx=panel_ctx,
    )
    if impact:
        out["impact"] = impact
    return out


def resolve_research_impact(
    *,
    tech_key: str,
    current: int,
    buildings: Optional[Mapping[str, int]],
    research_levels: Optional[Mapping[str, int]],
    effect: Mapping[str, Any],
) -> Optional[Dict[str, Any]]:
    """TECHCARD impact for research summaries — concrete gameplay units."""
    from .effects import EffectResolver
    from .research import fleet_slots_for_navigation_level

    key = str(tech_key)
    cur = max(0, int(current))
    nxt = cur + 1
    blurb = f"desc_{key}"
    bld = dict(buildings or {})
    research = dict(research_levels or {})

    if key in ("mining_tech", "drone_tech"):
        mine_lvl = max(1, int(bld.get("metal_mine", 0) or 0))
        r_cur = EffectResolver(bld, {**research, key: cur})
        r_nxt = EffectResolver(bld, {**research, key: nxt})
        # Use production_per_hour metal via resolver helper if available.
        prod_cur = int(r_cur.get_building_production_per_hour(1.0).get("metal", 0) or 0)
        prod_nxt = int(r_nxt.get_building_production_per_hour(1.0).get("metal", 0) or 0)
        if prod_cur <= 0 and mine_lvl <= 0:
            # Fallback: show percent as rate of 100 for readability only when no mine.
            return impact_from_rate(
                blurb_key=blurb,
                current_rate=int(effect.get("effect_current") or 0),
                next_rate=int(effect.get("effect_next") or 0),
                unit="%",
                affects=[{"label_key": "building_metal_mine"}],
            )
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=prod_cur,
            next_rate=prod_nxt,
            unit="/h",
            affects=[{"label_key": "building_metal_mine"}, {"label_key": "nav_overview"}],
        )

    if key == "storage_tech":
        store_lvl = int(bld.get("metal_storage", 0) or 0)
        cap_cur = canonical_storage_capacity_for_building(
            "metal_storage", store_lvl, buildings=bld, research_levels={**research, key: cur}
        )
        cap_nxt = canonical_storage_capacity_for_building(
            "metal_storage", store_lvl, buildings=bld, research_levels={**research, key: nxt}
        )
        return impact_from_capacity(
            blurb_key=blurb,
            current_cap=cap_cur,
            next_cap=cap_nxt,
            affects=[{"label_key": "building_metal_storage"}],
        )

    if key == "buildtime_tech":
        r_cur = EffectResolver(bld, {**research, key: cur})
        r_nxt = EffectResolver(bld, {**research, key: nxt})
        target = max(1, int(bld.get("metal_mine", 0) or 0) + 1)
        return impact_from_duration_seconds(
            blurb_key=blurb,
            current_seconds=int(r_cur.get_build_time_seconds("metal_mine", target)),
            next_seconds=int(r_nxt.get_build_time_seconds("metal_mine", target)),
            affects=[{"label_key": "building_metal_mine"}, {"label_key": "nav_overview"}],
            extra_example={"reference_building": "metal_mine"},
        )

    if key == "energy_tech":
        # Concrete mine energy draw at metal_mine level.
        mine_lvl = max(1, int(bld.get("metal_mine", 0) or 1))
        r_cur = EffectResolver({**bld, "metal_mine": mine_lvl}, {**research, key: cur})
        r_nxt = EffectResolver({**bld, "metal_mine": mine_lvl}, {**research, key: nxt})
        draw_cur = int(r_cur.building_energy_draw("metal_mine", level=mine_lvl))
        draw_nxt = int(r_nxt.building_energy_draw("metal_mine", level=mine_lvl))
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=draw_cur,
            next_rate=draw_nxt,
            unit="",
            affects=[{"label_key": "building_metal_mine"}, {"label_key": "energy"}],
            kind="energy",
        )

    if key == "navigation_tech":
        slots_cur = int(fleet_slots_for_navigation_level(cur))
        slots_nxt = int(fleet_slots_for_navigation_level(nxt))
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=slots_cur,
            next_rate=slots_nxt,
            unit="",
            affects=[{"label_key": "nav_fleet"}, {"label_key": "research_navigation_tech"}],
            kind="slots",
        )

    if key in ("engine_tech", "fuel_efficiency"):
        # Speed / fuel factor as × multiplier (server), still more concrete than bare +.
        if key == "engine_tech":
            f_cur = 1.0 + 0.02 * cur
            f_nxt = 1.0 + 0.02 * nxt
            return build_impact_summary(
                blurb_key=blurb,
                current_value=round(f_cur, 2),
                current_unit="×",
                next_from=round(f_cur, 2),
                next_to=round(f_nxt, 2),
                next_delta=round(f_nxt - f_cur, 2),
                next_unit="×",
                affects=[{"label_key": "nav_fleet"}],
                example={"kind": "rate", "unit": "×", "current": round(f_cur, 2), "next": round(f_nxt, 2)},
            )
        # fuel: remaining factor
        f_cur = float(EffectResolver.fuel_efficiency_factor_for_level(cur))
        f_nxt = float(EffectResolver.fuel_efficiency_factor_for_level(nxt))
        # Show relative fuel use % of base (lower is better).
        use_cur = int(round(f_cur * 100))
        use_nxt = int(round(f_nxt * 100))
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=use_cur,
            next_rate=use_nxt,
            unit="%",
            affects=[{"label_key": "nav_fleet"}],
            kind="rate",
        )

    if key in ("weapon_tech", "armor_tech", "shield_tech"):
        # Reference combat stat: base 1000 scaled by +5%/level.
        base = 1000
        bonus_cur = 1.0 + 0.05 * cur
        bonus_nxt = 1.0 + 0.05 * nxt
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=int(round(base * bonus_cur)),
            next_rate=int(round(base * bonus_nxt)),
            unit="",
            affects=[{"label_key": "nav_fleet"}, {"label_key": f"research_{key}"}],
            kind="capacity",
        )

    if key == "interstellar_expansion":
        from .planet_evolution.expansion_protocol import interstellar_expansion_reach_label

        return build_impact_summary(
            blurb_key=blurb,
            current_label_key="techcard_current",
            current_value=cur,
            current_unit="",
            next_from=cur,
            next_to=nxt,
            next_delta=1,
            affects=[
                {"label_key": "research_interstellar_expansion"},
                {"label_key": "nav_galaxy"},
            ],
            example={
                "kind": "unlock",
                "reach_current_key": interstellar_expansion_reach_label(cur),
                "reach_next_key": interstellar_expansion_reach_label(nxt),
                "unlocks": [
                    {"label_key": interstellar_expansion_reach_label(nxt)},
                    {"label_key": "nav_galaxy"},
                ],
            },
        )

    # Generic numeric effect fallback (still structured).
    if effect.get("effect_kind") in ("bonus_percent", "reduction_percent", "level"):
        return impact_from_rate(
            blurb_key=blurb,
            current_rate=int(effect.get("effect_current") or 0),
            next_rate=int(effect.get("effect_next") or 0),
            unit="%" if "percent" in str(effect.get("effect_kind")) else "",
            affects=[{"label_key": f"research_{key}"}],
        )
    return None


def build_research_technical_summary(
    *,
    tech_key: str,
    current: int,
    next_row: Optional[Dict[str, Any]],
    buildings: Optional[Mapping[str, int]] = None,
    research_levels: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """Top-of-modal summary for the next research level."""
    cur = max(0, int(current))
    key = str(tech_key)
    if not next_row:
        return {"at_max_level": True, "layout": "max_level", "level": cur}

    from .research import get_research_effect_preview

    nxt = cur + 1
    effect = get_research_effect_preview(key, cur, nxt)
    time_s = int(next_row.get("time_seconds") or 0)
    roi_hours = round(time_s / 3600.0, 1) if time_s > 0 else None

    if key == "energy_tech":
        from .effects import EffectResolver

        c_cons = 100 - int(EffectResolver.mine_energy_reduction_pct(cur))
        n_cons = 100 - int(EffectResolver.mine_energy_reduction_pct(nxt))
        display = {
            "layout": "effect_percent",
            "table_layout": "effect_percent",
            "display_mode": "consumption",
            "effect_kind": "consumption_percent",
            "label_key": "technical_energy_consumption",
            "unit": "%",
            "current": c_cons,
            "next": n_cons,
            "value_at_level": c_cons,
            "delta": abs(n_cons - c_cons),
            "step_delta": n_cons - c_cons,
        }
    elif effect.get("effect_kind") in ("bonus_percent", "reduction_percent"):
        display = build_effect_percent_display(
            effect_kind=str(effect.get("effect_kind")),
            current=int(effect.get("effect_current") or 0),
            next_val=int(effect.get("effect_next") or 0),
            label_key=str(effect.get("effect_metric_key") or ""),
        )
    else:
        display = dict(next_row.get("display") or {})

    bonuses: List[Dict[str, Any]] = []
    if buildings is not None and research_levels is not None:
        bonuses = _active_research_bonuses_for_planet(buildings, research_levels)

    out = {
        "at_max_level": False,
        "layout": str(display.get("layout") or "plain"),
        "from_level": cur,
        "to_level": nxt,
        "display": display,
        "cost_metal": int(next_row.get("cost_metal") or 0),
        "cost_crystal": int(next_row.get("cost_crystal") or 0),
        "time_seconds": time_s,
        "upgrade_roi_hours": roi_hours,
        "active_bonuses": bonuses,
    }
    impact = resolve_research_impact(
        tech_key=key,
        current=cur,
        buildings=buildings,
        research_levels=research_levels,
        effect=effect,
    )
    if impact:
        out["impact"] = impact
    return out


def _active_research_bonuses(tech_key: str, current_level: int) -> List[Dict[str, Any]]:
    """Legacy stub — use _active_research_bonuses_for_planet with planet context."""
    _ = tech_key
    _ = current_level
    return []


def _active_research_bonuses_for_planet(
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
) -> List[Dict[str, Any]]:
    from .effects import EffectResolver
    from .buildings import nanofactory_build_bonus_pct

    rows: List[Dict[str, Any]] = []
    resolver = EffectResolver(dict(buildings or {}), dict(research_levels or {}))
    lab = int(buildings.get("research_lab", 0) or 0)
    if lab > 0:
        pct = int(round((resolver.research_lab_bonus() - 1.0) * 100))
        if pct > 0:
            rows.append({"label_key": "building_research_lab", "display": f"+{pct} %"})
    nf = int(buildings.get("nanofactory", 0) or 0)
    if nf > 0:
        pct = int(nanofactory_build_bonus_pct(nf))
        if pct > 0:
            rows.append({"label_key": "building_nanofactory", "display": f"+{pct} %"})
    bt = int(research_levels.get("buildtime_tech", 0) or 0)
    if bt > 0:
        pct = int(EffectResolver.buildtime_speed_bonus_pct(bt))
        if pct > 0:
            rows.append({"label_key": "buildtime_tech", "display": f"+{pct} %"})
    return rows


def resolve_technical_table_layout(levels: List[Dict[str, Any]]) -> str:
    """Pick the dominant table layout from preview rows (not only index 0)."""
    for row in levels or []:
        display = row.get("display") or {}
        layout = str(display.get("table_layout") or display.get("layout") or "").strip()
        if layout and layout not in ("plain", "standard"):
            return layout
    return "standard"


def build_production_milestones(
    *,
    building_type: str,
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
    ratio: float,
    current: int,
    max_level: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Upcoming production milestones vs current output (mines only)."""
    btype = str(building_type)
    if btype not in MINE_BUILDINGS:
        return []
    cur = max(0, int(current))
    if cur <= 0:
        return []
    cur_out = _building_output_at(buildings, btype, cur, ratio, research_levels)
    if cur_out <= 0:
        return []
    out: List[Dict[str, Any]] = []
    for milestone in TECHNICAL_MILESTONE_LEVELS:
        if milestone <= cur:
            continue
        if max_level is not None and milestone > int(max_level):
            break
        at_m = _building_output_at(buildings, btype, milestone, ratio, research_levels)
        if at_m <= cur_out:
            continue
        pct = int(round((at_m - cur_out) / float(cur_out) * 100))
        if pct <= 0:
            continue
        out.append(
            {
                "level": milestone,
                "kind": "production_gain",
                "label_key": "technical_milestone_production",
                "display": f"+{pct} %",
                "detail_key": "technical_milestone_production_detail",
            }
        )
    return out[:6]


def build_research_effect_milestones(
    *,
    tech_key: str,
    current: int,
    levels: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Upcoming research milestones with effect preview."""
    from .research import get_research_effect_preview

    cur = max(0, int(current))
    key = str(tech_key)
    out: List[Dict[str, Any]] = []
    for row in levels or []:
        lvl = int(row.get("level") or 0)
        if lvl <= cur + 1:
            continue
        role = str(row.get("row_role") or "")
        if role not in ("milestone", "preview"):
            continue
        effect = get_research_effect_preview(key, max(0, lvl - 1), lvl)
        kind = str(effect.get("effect_kind") or "")
        if kind == "bonus_percent":
            val = int(effect.get("effect_next") or 0)
            display = f"+{val} %"
        elif kind == "reduction_percent":
            val = int(effect.get("effect_next") or 0)
            display = f"-{val} %"
        elif kind == "level":
            val = int(effect.get("effect_next") or 0)
            display = str(val)
        else:
            continue
        out.append(
            {
                "level": lvl,
                "kind": "research_effect",
                "label_key": str(effect.get("effect_metric_key") or key),
                "display": display,
            }
        )
    return out[:6]


def _format_bonus_pct_display(bonus_pct: int) -> str:
    pct = int(bonus_pct)
    if pct > 0:
        return f"+{pct} %"
    if pct < 0:
        return f"{pct} %"
    return "+0 %"


def build_effective_stat(
    key: str,
    base: int | float,
    *,
    multiplier: float | None = None,
    additive_frac: float | None = None,
    sources: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    GC-EFFSTAT — canonical effective-stat display payload.

    Primary value is ``effective`` (gameplay). ``bonus_pct`` is the single net
    total percentage vs catalog base. Frontend formats only — no game math.
    """
    base_i = max(0, int(round(float(base or 0))))
    if multiplier is not None:
        mult = max(0.0, float(multiplier))
        effective = int(round(base_i * mult)) if base_i else 0
    elif additive_frac is not None:
        frac = float(additive_frac)
        effective = int(round(base_i * (1.0 + frac))) if base_i else 0
        effective = max(0, effective)
    else:
        effective = base_i

    if base_i > 0:
        bonus_pct = int(round((float(effective) / float(base_i) - 1.0) * 100.0))
    else:
        bonus_pct = 0

    return {
        "key": str(key),
        "base": base_i,
        "effective": int(effective),
        "bonus_pct": int(bonus_pct),
        "bonus_display": _format_bonus_pct_display(bonus_pct),
        "sources": list(sources or []),
    }


def _resolver_source_contributions(
    resolver: Any,
    mod_key: str,
    *,
    kind: str,
) -> List[Dict[str, Any]]:
    """Derive per-source % contributions from EffectResolver source log."""
    prev = 0.0 if kind == "additive_frac" else 1.0
    rows: List[Dict[str, Any]] = []
    for entry in list(getattr(resolver, "_sources", None) or []):
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("status") or "") != "active":
            continue
        if str(entry.get("key") or "") != mod_key:
            continue
        try:
            val = float(entry.get("value"))
        except (TypeError, ValueError):
            continue
        label = str(entry.get("source") or mod_key).strip() or mod_key
        if kind == "additive_frac":
            delta = val - prev
            pct = int(round(delta * 100.0))
        else:
            if prev <= 0:
                prev = val
                continue
            pct = int(round((val / prev - 1.0) * 100.0))
        prev = val
        if pct == 0:
            continue
        rows.append({"label_key": label, "display": _format_bonus_pct_display(pct)})
    return rows


def _active_combat_bonuses(
    research_levels: Mapping[str, int],
    *,
    resolver: Any | None = None,
) -> List[Dict[str, Any]]:
    """Combat bonus lines: prefer full-stack resolver contributions, else research."""
    if resolver is not None:
        rows: List[Dict[str, Any]] = []
        for mod_key in ("weapon_bonus", "shield_bonus", "armor_bonus"):
            rows.extend(
                _resolver_source_contributions(resolver, mod_key, kind="additive_frac")
            )
        if rows:
            return rows

    from .effects import EffectResolver

    rows = []
    for key in ("weapon_tech", "shield_tech", "armor_tech"):
        lvl = int(research_levels.get(key, 0) or 0)
        if lvl > 0:
            pct = int(EffectResolver.combat_bonus_pct(lvl))
            if pct > 0:
                rows.append({"label_key": key, "display": f"+{pct} %"})
    return rows


def _active_mobility_bonuses(resolver: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for mod_key in ("fleet_speed_multiplier", "cargo_multiplier", "fuel_efficiency_factor"):
        rows.extend(_resolver_source_contributions(resolver, mod_key, kind="mult"))
    return rows


def resolve_unit_effect_context(
    *,
    buildings: Mapping[str, int] | None = None,
    research_levels: Mapping[str, int] | None = None,
    player_id: int | None = None,
    conn=None,
    planet: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Shared EffectResolver snapshot for unit/fleet display (GC-EFFSTAT).

    Prefer full player stack when ``player_id`` + ``conn`` are available so
    alliance / class / directives / boosters match gameplay.
    """
    from .effects import EffectResolver, get_effect_resolver

    bld = dict(buildings or {})
    res = dict(research_levels or {})
    if player_id is not None and conn is not None:
        resolver = get_effect_resolver(
            int(player_id),
            buildings=bld,
            research=res,
            conn=conn,
            planet=dict(planet) if planet is not None else None,
        )
    else:
        resolver = EffectResolver(bld, res)

    combat = resolver.get_combat_modifiers()
    mods = resolver.get_modifiers()
    return {
        "resolver": resolver,
        "weapon_bonus": float(combat.get("weapon_bonus", 0.0) or 0.0),
        "shield_bonus": float(combat.get("shield_bonus", 0.0) or 0.0),
        "armor_bonus": float(combat.get("armor_bonus", 0.0) or 0.0),
        "fleet_speed_multiplier": float(mods.get("fleet_speed_multiplier", 1.0) or 1.0),
        "cargo_multiplier": float(mods.get("cargo_multiplier", 1.0) or 1.0),
        "fuel_efficiency_factor": float(mods.get("fuel_efficiency_factor", 1.0) or 1.0),
    }


def build_combat_effective_stats(
    *,
    base_attack: int,
    base_shield: int,
    base_hull: int,
    effect_ctx: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    resolver = effect_ctx.get("resolver")
    return {
        "attack": build_effective_stat(
            "attack",
            base_attack,
            additive_frac=float(effect_ctx.get("weapon_bonus") or 0.0),
            sources=_resolver_source_contributions(resolver, "weapon_bonus", kind="additive_frac")
            if resolver is not None
            else None,
        ),
        "shield": build_effective_stat(
            "shield",
            base_shield,
            additive_frac=float(effect_ctx.get("shield_bonus") or 0.0),
            sources=_resolver_source_contributions(resolver, "shield_bonus", kind="additive_frac")
            if resolver is not None
            else None,
        ),
        "hull": build_effective_stat(
            "hull",
            base_hull,
            additive_frac=float(effect_ctx.get("armor_bonus") or 0.0),
            sources=_resolver_source_contributions(resolver, "armor_bonus", kind="additive_frac")
            if resolver is not None
            else None,
        ),
    }


def build_mobility_effective_stats(
    *,
    base_speed: int,
    base_cargo: int,
    base_fuel: int,
    effect_ctx: Mapping[str, Any],
) -> Dict[str, Dict[str, Any]]:
    resolver = effect_ctx.get("resolver")
    return {
        "speed": build_effective_stat(
            "speed",
            base_speed,
            multiplier=float(effect_ctx.get("fleet_speed_multiplier") or 1.0),
            sources=_resolver_source_contributions(
                resolver, "fleet_speed_multiplier", kind="mult"
            )
            if resolver is not None
            else None,
        ),
        "cargo": build_effective_stat(
            "cargo",
            base_cargo,
            multiplier=float(effect_ctx.get("cargo_multiplier") or 1.0),
            sources=_resolver_source_contributions(resolver, "cargo_multiplier", kind="mult")
            if resolver is not None
            else None,
        ),
        "fuel": build_effective_stat(
            "fuel",
            base_fuel,
            multiplier=float(effect_ctx.get("fuel_efficiency_factor") or 1.0),
            sources=_resolver_source_contributions(
                resolver, "fuel_efficiency_factor", kind="mult"
            )
            if resolver is not None
            else None,
        ),
    }


def apply_combat_stats_to_catalog_entry(
    entry: Dict[str, Any],
    *,
    effect_ctx: Mapping[str, Any],
    attack_key: str = "attack",
    shield_key: str = "shield",
    hull_key: str = "hull",
) -> Dict[str, Any]:
    """Attach EffectiveStat payloads and overwrite catalog ints with effective values."""
    combat = build_combat_effective_stats(
        base_attack=int(entry.get(attack_key) or 0),
        base_shield=int(entry.get(shield_key) or 0),
        base_hull=int(entry.get(hull_key) or 0),
        effect_ctx=effect_ctx,
    )
    entry["attack_stat"] = combat["attack"]
    entry["shield_stat"] = combat["shield"]
    entry["hull_stat"] = combat["hull"]
    entry[attack_key] = int(combat["attack"]["effective"])
    entry[shield_key] = int(combat["shield"]["effective"])
    entry[hull_key] = int(combat["hull"]["effective"])
    return entry


def build_unit_technical_block(
    *,
    base_attack: int,
    base_shield: int,
    base_hull: int,
    base_build_seconds: int,
    production: Mapping[str, Any],
    buildings: Mapping[str, int],
    research_levels: Mapping[str, int],
    next_yard_unit_seconds: int,
    player_id: int | None = None,
    conn=None,
    planet: Mapping[str, Any] | None = None,
    base_speed: int | None = None,
    base_cargo: int | None = None,
    base_fuel: int | None = None,
    effect_ctx: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """GC-828 / GC-EFFSTAT — unit detail: build preview, effective combat/mobility, bonuses."""
    ctx = dict(effect_ctx) if effect_ctx is not None else resolve_unit_effect_context(
        buildings=buildings,
        research_levels=research_levels,
        player_id=player_id,
        conn=conn,
        planet=planet,
    )
    resolver = ctx.get("resolver")
    combat_stats = build_combat_effective_stats(
        base_attack=base_attack,
        base_shield=base_shield,
        base_hull=base_hull,
        effect_ctx=ctx,
    )

    cur_cycle = max(1, int(production.get("cycle_seconds") or base_build_seconds or 1))
    next_cycle = max(1, int(next_yard_unit_seconds or cur_cycle))
    cycle_delta = cur_cycle - next_cycle

    active = _active_combat_bonuses(research_levels, resolver=resolver)
    mobility = None
    if base_speed is not None or base_cargo is not None or base_fuel is not None:
        mobility = build_mobility_effective_stats(
            base_speed=int(base_speed or 0),
            base_cargo=int(base_cargo or 0),
            base_fuel=int(base_fuel or 0),
            effect_ctx=ctx,
        )
        for row in _active_mobility_bonuses(resolver):
            if row not in active:
                active.append(row)

    out: Dict[str, Any] = {
        "build_preview": {
            "current_seconds": cur_cycle,
            "next_seconds": next_cycle,
            "delta_seconds": cycle_delta,
            "at_max_yard": next_cycle >= cur_cycle and cycle_delta <= 0,
        },
        "combat": {
            "attack": int(combat_stats["attack"]["effective"]),
            "shield": int(combat_stats["shield"]["effective"]),
            "hull": int(combat_stats["hull"]["effective"]),
            "build_seconds": cur_cycle,
            "base_attack": int(base_attack),
            "base_shield": int(base_shield),
            "base_hull": int(base_hull),
            "attack_stat": combat_stats["attack"],
            "shield_stat": combat_stats["shield"],
            "hull_stat": combat_stats["hull"],
        },
        "active_bonuses": active,
        "yard_batch_capacity": int(production.get("yard_batch_capacity") or 0),
        "build_time_reduction_percent": int(production.get("build_time_reduction_percent") or 0),
    }
    if mobility is not None:
        out["mobility"] = mobility
    return out
