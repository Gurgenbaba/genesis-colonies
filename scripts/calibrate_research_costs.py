"""Derive research cost afford-hour anchors (GC-RESEARCH-COST-REBALANCE)."""
from __future__ import annotations

from game.economy_balance import (
    RESEARCH_COST_AFFORD_HOURS,
    research_cost_afford_hours,
    research_cost_anchor_total,
    reference_production_per_hour,
)
from game.research import get_research_cost

ANCHORS = sorted(RESEARCH_COST_AFFORD_HOURS)


def main() -> None:
    print("RESEARCH_COST_AFFORD_HOURS (source of truth)")
    for lvl in ANCHORS:
        print(f"  L{lvl:3d}: {RESEARCH_COST_AFFORD_HOURS[lvl]:g} h")
    print()
    print("Computed energy_tech totals (tier 1.0):")
    for lvl in [1, 10, 19, 20, 30, 40, 50, 100]:
        m, c = get_research_cost("energy_tech", lvl)
        income = reference_production_per_hour("metal", lvl) + reference_production_per_hour(
            "crystal", lvl
        )
        print(
            f"  L{lvl:3d}: {m+c:14,}  "
            f"(income {income:,.0f}/h × {research_cost_afford_hours(lvl):.1f}h)"
        )
    print()
    m, c = get_research_cost("storage_tech", 19)
    print(f"storage_tech L19: {m:,} Fe + {c:,} Cr = {m+c:,}")


if __name__ == "__main__":
    main()
