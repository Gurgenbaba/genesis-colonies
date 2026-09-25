#!/usr/bin/env python3
"""Long-horizon economy magnitude audit.

Read-only balance tooling.  It combines the canonical mine/Ascension simulator
with live owners for energy, storage, Trader limits and research pricing/time.

This is deliberately *not* a gameplay simulator: the record-mine topologies are
optimistic upper bounds.  The purpose is to reveal where a 6/12-month economy
first becomes numerically or mechanically awkward.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from typing import Any, Dict, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game import production_formula as pf
from game.economy_balance import (
    storage_production_buffer_capacity,
    storage_reference_hours_at_depot_level,
)
from game.effects import EffectResolver
from game.mine_evolution.nodebuster import (
    ascension_points_for_depth,
    effective_shortage_ratio_bps,
    energy_draw_bps,
)
from game.models import DEFAULT_GAME_SETTINGS
from game.research import get_research_payment_cost
from game.time_floors import building_progress_floor_seconds
from scripts.sim_ascension_breakthroughs import (
    SCENARIOS,
    run_topology_horizons,
    uni1_endgame_curve,
    upgrade_value_cost,
)


AUDIT_SLOTS = (1, 8, 15)
RESEARCH_TARGETS = (60, 100, 120, 150, 200)


def _scenario(key: str):
    return next(row for row in SCENARIOS if row.key == key)


def _resource_output_per_hour(resource: str, level: int, scenario) -> Decimal:
    mine = pf.mine_output_decimal(
        resource,
        int(level),
        tail_power_bonus_hundredths=int(scenario.tail_bonus_hundredths),
    )
    standard = pf.standard_output_decimal(resource)
    return (standard + mine) * Decimal(scenario.production_multiplier)


def _ratio_bps(supply: int, demand: int) -> int:
    if demand <= 0 or supply >= demand:
        return 10_000
    return max(0, min(10_000, (int(supply) * 10_000) // max(1, int(demand))))


def _energy_snapshot(level: int, slot: int) -> Dict[str, Any]:
    cap_resolver = EffectResolver(
        {"planet_core_nexus": 50, "geothermal_nexus": 50},
        {},
        settings=DEFAULT_GAME_SETTINGS,
        planet_position=int(slot),
    )
    solar_cap = int(cap_resolver.get_max_building_level("solar_plant"))

    buildings = {
        "metal_mine": int(level),
        "crystal_mine": int(level),
        "fuel_cell_plant": int(level),
        "solar_plant": solar_cap,
        "geothermal_nexus": 50,
    }
    research = {"energy_tech": 50}
    resolver = EffectResolver(
        buildings,
        research,
        settings=DEFAULT_GAME_SETTINGS,
        planet_position=int(slot),
    )
    supply, demand = resolver.compute_energy()
    base_bps = _ratio_bps(supply, demand)

    optimized_bps = int(energy_draw_bps({"optimized_energy": 10}))
    optimized_demand = 0
    for key in ("metal_mine", "crystal_mine", "fuel_cell_plant"):
        draw = int(resolver.building_energy_draw(key))
        optimized_demand += max(1, (draw * optimized_bps) // 10_000) if draw > 0 else 0
    optimized_grid_bps = _ratio_bps(supply, optimized_demand)
    optimized_balanced_bps = int(
        effective_shortage_ratio_bps(
            optimized_grid_bps,
            {"load_balancing": 10},
        )
    )

    return {
        "slot": int(slot),
        "solar_cap": solar_cap,
        "supply": int(supply),
        "demand": int(demand),
        "grid_pct": base_bps / 100.0,
        "optimized_grid_pct": optimized_grid_bps / 100.0,
        "optimized_balanced_pct": optimized_balanced_bps / 100.0,
    }


def _late_research_time_hours(target_level: int) -> float:
    resolver = EffectResolver(
        {"research_lab": 100, "academy": 50},
        {"buildtime_tech": 120},
        settings=DEFAULT_GAME_SETTINGS,
    )
    # The strongest current research-network state adds +10% speed at Ascension V.
    resolver._research_lab_ascension_rank_cache = 5
    seconds = resolver.get_research_time_seconds("energy_tech", int(target_level))
    return float(seconds) / 3600.0


def _research_rows(
    *,
    empire_combined_per_hour: Decimal,
    world_count: int,
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    income = max(Decimal(1), Decimal(empire_combined_per_hour))
    for target in RESEARCH_TARGETS:
        metal, crystal = get_research_payment_cost(
            "energy_tech",
            int(target),
            cost_context={
                "empire_combined_per_hour": int(income),
                "maturity_index": 1.0,
                "world_count": int(world_count),
            },
        )
        total = Decimal(int(metal) + int(crystal))
        rows.append(
            {
                "target_level": int(target),
                "payment_total": int(total),
                "afford_hours": float(total / income),
                "late_infra_time_hours": _late_research_time_hours(int(target)),
            }
        )
    return rows


def build_audit() -> Dict[str, Any]:
    stress = _scenario("singularity_stack")
    with uni1_endgame_curve():
        topology = run_topology_horizons(stress)

        cap_resolver = EffectResolver(
            {"planet_core_nexus": 50, "geothermal_nexus": 50},
            {},
            settings=DEFAULT_GAME_SETTINGS,
        )
        storage_cap_level = int(cap_resolver.get_max_building_level("metal_storage"))
        storage_hours = int(storage_reference_hours_at_depot_level(storage_cap_level))
        trader_hard_cap = min(
            int(DEFAULT_GAME_SETTINGS.get("exchange_daily_limit", 50_000_000_000)),
            int(DEFAULT_GAME_SETTINGS.get("exchange_daily_limit_max", 50_000_000_000)),
        )

        anchors = []
        anchor_specs = (
            ("1w_6m", "one_world", "182.5d", 1),
            ("1w_12m", "one_world", "365d", 1),
            ("11w_6m", "eleven_world_pool", "182.5d", 11),
            ("11w_12m", "eleven_world_pool", "365d", 11),
            ("zero_12m", "zero_cost_queue", "365d", 1),
        )
        for key, topology_key, horizon, worlds in anchor_specs:
            level = int(topology[topology_key][horizon])
            metal_ph = _resource_output_per_hour("metal", level, stress)
            crystal_ph = _resource_output_per_hour("crystal", level, stress)
            empire_combined = (metal_ph + crystal_ph) * Decimal(int(worlds))
            next_cost = upgrade_value_cost(level + 1, stress)
            queue_floor = int(building_progress_floor_seconds("metal_mine", level + 1))
            daily_metal = metal_ph * Decimal(24) * Decimal(int(worlds))
            storage_floor = int(storage_production_buffer_capacity(metal_ph, storage_cap_level))

            anchors.append(
                {
                    "key": key,
                    "worlds": int(worlds),
                    "level": level,
                    "metal_per_hour": int(metal_ph),
                    "crystal_per_hour": int(crystal_ph),
                    "empire_combined_per_hour": int(empire_combined),
                    "next_upgrade_total": int(next_cost),
                    "next_upgrade_resource_hours": float(
                        next_cost / max(Decimal(1), metal_ph * Decimal(int(worlds)))
                    ),
                    "next_queue_floor_seconds": queue_floor,
                    "ascension_ap_if_reset": int(ascension_points_for_depth(level)),
                    "storage_level_cap": storage_cap_level,
                    "storage_buffer_hours": storage_hours,
                    "metal_storage_v2_floor": storage_floor,
                    "trader_hard_cap": trader_hard_cap,
                    "trader_cap_vs_empire_metal_day_pct": float(
                        Decimal(trader_hard_cap) * Decimal(100)
                        / max(Decimal(1), daily_metal)
                    ),
                    "energy": [_energy_snapshot(level, slot) for slot in AUDIT_SLOTS],
                    "research": _research_rows(
                        empire_combined_per_hour=empire_combined,
                        world_count=int(worlds),
                    ),
                }
            )

    return {
        "scenario": stress.key,
        "topology": topology,
        "anchors": anchors,
    }


def _human_number(value: int) -> str:
    n = Decimal(int(value))
    suffixes = (
        (Decimal("1e18"), "Qi"),
        (Decimal("1e15"), "Qa"),
        (Decimal("1e12"), "T"),
        (Decimal("1e9"), "B"),
        (Decimal("1e6"), "M"),
    )
    for threshold, suffix in suffixes:
        if abs(n) >= threshold:
            return f"{n / threshold:.2f}{suffix}"
    return f"{int(n):,}"


def main() -> None:
    audit = build_audit()
    print("Long-horizon economy magnitude audit")
    print(f"Scenario: {audit['scenario']}")
    print()
    print(
        "Anchor | Lvl | Metal/h | Next cost | Queue floor | AP | "
        "Storage buffer | Trader cap/day"
    )
    print("--- | ---: | ---: | ---: | ---: | ---: | ---: | ---:")
    for row in audit["anchors"]:
        print(
            f"{row['key']} | L{row['level']} | {_human_number(row['metal_per_hour'])} | "
            f"{_human_number(row['next_upgrade_total'])} | "
            f"{row['next_queue_floor_seconds']}s | {row['ascension_ap_if_reset']} | "
            f"{row['storage_buffer_hours']}h | "
            f"{row['trader_cap_vs_empire_metal_day_pct']:.4f}%"
        )

    print()
    print("Live energy at current caps: Solar cap + Geo50 + Energy Tech50")
    print("Anchor | Slot | Grid | +Optimized Energy X | +Load Balancing X")
    print("--- | ---: | ---: | ---: | ---:")
    for row in audit["anchors"]:
        for energy in row["energy"]:
            print(
                f"{row['key']} | {energy['slot']} | {energy['grid_pct']:.1f}% | "
                f"{energy['optimized_grid_pct']:.1f}% | "
                f"{energy['optimized_balanced_pct']:.1f}%"
            )

    print()
    print(
        "Research payment/time: mature empire income at anchor; "
        "Lab100 + Academy50 + Buildtime120 + Research Network Asc V"
    )
    print("Anchor | Tech target | Afford | Queue time")
    print("--- | ---: | ---: | ---:")
    for row in audit["anchors"]:
        if row["key"] == "zero_12m":
            continue
        for research in row["research"]:
            print(
                f"{row['key']} | L{research['target_level']} | "
                f"{research['afford_hours']:.1f}h | "
                f"{research['late_infra_time_hours']:.1f}h"
            )


if __name__ == "__main__":
    main()
