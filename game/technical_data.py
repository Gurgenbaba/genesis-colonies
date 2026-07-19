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

    ref_building = "metal_mine"
    ref_target = max(1, int(bld.get(ref_building, 0) or 0) + 1)

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
        return {
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

    display = dict(next_row.get("display") or {})
    layout = str(display.get("layout") or "")
    if layout == "yard" and current_row:
        cur_d = current_row.get("display") or {}
        display["batch_capacity_current"] = cur_d.get("capacity_at_level")
        display["build_time_reduction_current"] = cur_d.get("reduction_at_level")
        display["batch_capacity"] = display.get("capacity_at_level")
        display["build_time_reduction_next"] = display.get("reduction_at_level")

    return {
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

    return {
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


def _stat_with_combat_bonus(base: int, bonus_frac: float) -> int:
    return int(round(max(0, int(base)) * (1.0 + max(0.0, float(bonus_frac)))))


def _active_combat_bonuses(research_levels: Mapping[str, int]) -> List[Dict[str, Any]]:
    from .effects import EffectResolver

    rows: List[Dict[str, Any]] = []
    for key in ("weapon_tech", "shield_tech", "armor_tech"):
        lvl = int(research_levels.get(key, 0) or 0)
        if lvl > 0:
            pct = int(EffectResolver.combat_bonus_pct(lvl))
            if pct > 0:
                rows.append({"label_key": key, "display": f"+{pct} %"})
    return rows


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
) -> Dict[str, Any]:
    """GC-828 — unified unit detail sections (build time preview, combat, bonuses)."""
    from .effects import EffectResolver

    resolver = EffectResolver(dict(buildings or {}), dict(research_levels or {}))
    combat = resolver.get_combat_modifiers()

    cur_cycle = max(1, int(production.get("cycle_seconds") or base_build_seconds or 1))
    next_cycle = max(1, int(next_yard_unit_seconds or cur_cycle))
    cycle_delta = cur_cycle - next_cycle

    cur_attack = _stat_with_combat_bonus(base_attack, combat["weapon_bonus"])
    cur_shield = _stat_with_combat_bonus(base_shield, combat["shield_bonus"])
    cur_hull = _stat_with_combat_bonus(base_hull, combat["armor_bonus"])

    return {
        "build_preview": {
            "current_seconds": cur_cycle,
            "next_seconds": next_cycle,
            "delta_seconds": cycle_delta,
            "at_max_yard": next_cycle >= cur_cycle and cycle_delta <= 0,
        },
        "combat": {
            "attack": cur_attack,
            "shield": cur_shield,
            "hull": cur_hull,
            "build_seconds": cur_cycle,
            "base_attack": int(base_attack),
            "base_shield": int(base_shield),
            "base_hull": int(base_hull),
        },
        "active_bonuses": _active_combat_bonuses(research_levels),
        "yard_batch_capacity": int(production.get("yard_batch_capacity") or 0),
        "build_time_reduction_percent": int(production.get("build_time_reduction_percent") or 0),
    }
