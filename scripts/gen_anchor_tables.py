"""Generate community anchor tables from live game code (speed x1)."""
from __future__ import annotations

from game.production_formula import LEVEL_GROWTH
from game.economy_balance import (
    BUILDING_UPGRADE_CURVES,
    power_upgrade_cost,
    power_build_seconds,
    mine_upgrade_roi_hours,
    research_time_anchor_hours,
    research_cost_anchor_total,
    research_upgrade_cost,
    research_base_time_seconds,
    reference_production_per_hour,
    STORAGE_BASE_CAPACITY,
    STORAGE_LEVEL_GROWTH,
    EXCHANGE_DAILY_LIMIT_MIN,
    EXCHANGE_DAILY_LIMIT_PCT_DEFAULT,
    MINE_UPGRADE_ROI_TARGET_HOURS,
    RESEARCH_TIME_ANCHOR_HOURS,
    RESEARCH_COST_ANCHOR_TOTAL,
    NEUTRAL_BALANCE_SLOT,
)
from game.research import RESEARCH_TECHS
from game.effects import EffectResolver
from game.buildings import MAX_BUILDING_LEVEL

ANCHORS = [10, 20, 30, 40, 60, 80, 100, 120]
SPEED = {"production_speed": 1.0, "build_speed": 1.0, "research_speed": 1.0}
SLOT = NEUTRAL_BALANCE_SLOT


def fmt_num(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} Mio"
    if n >= 10_000:
        return f"{n / 1_000:,.0f}k".replace(",", ".")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{int(round(n)):,}".replace(",", ".")


def fmt_time_sec(sec: float) -> str:
    sec = float(sec)
    if sec < 60:
        return f"{sec:.0f} s"
    if sec < 3600:
        return f"{sec / 60:.0f} Min"
    h = sec / 3600
    if h < 24:
        return f"{h:.1f} h"
    if h < 168:
        return f"{h / 24:.1f} Tage"
    if h < 720:
        return f"{h / 168:.1f} Wochen"
    if h < 8760:
        return f"{h / 720:.1f} Monate"
    return f"{h / 8760:.1f} Jahre"


def prod_ph(res: str, lvl: int) -> float:
    return reference_production_per_hour(res, lvl, slot=SLOT, production_speed=1.0)


def main() -> None:
    lines: list[str] = []
    lines.append("# Genesis Colonies — Ankerkurven (Code-Stand, Universum-Speed ×1)")
    lines.append("")
    lines.append(
        "**Referenz:** Galaxieslot 9 · Energie 100% · Forschung 0 · "
        "`production_speed=1` · `build_speed=1` · `research_speed=1`"
    )
    lines.append("")

    lines.append("## 1) Produktionsformel (GC-820)")
    lines.append("")
    lines.append("```")
    lines.append(
        "Produktion/h = Basis × production_speed × Level^Exponent × Slot × Temperatur × Forschung × Energie × …"
    )
    lines.append("```")
    lines.append("")
    lines.append("| Ressource | Basis | Exponent | Gebäude |")
    lines.append("|-----------|-------|----------|---------|")
    labels = {"metal": "Ferronit", "crystal": "Crytite", "fuel_cells": "Brennzellen"}
    for res, cfg in LEVEL_GROWTH.items():
        lines.append(f"| {labels.get(res, res)} | {cfg['base']} | {cfg['exponent']} | {cfg['building']} |")
    lines.append("")

    lines.append("### Produktion/h (Slot 9, Speed ×1)")
    lines.append("")
    lines.append("| Mine-Stufe | Ferronit/h | Crytite/h | Brennzellen/h |")
    lines.append("|------------|------------|-----------|---------------|")
    for lvl in ANCHORS:
        lines.append(
            f"| {lvl} | {fmt_num(prod_ph('metal', lvl))} | {fmt_num(prod_ph('crystal', lvl))} | "
            f"{fmt_num(prod_ph('fuel_cells', lvl))} |"
        )
    lines.append("")

    lines.append("### Produktionsgewinn pro Upgrade (+1 Stufe, Delta/h)")
    lines.append("")
    lines.append("| Ziel-Stufe | Ferronit +/h | Crytite +/h | Brennzellen +/h |")
    lines.append("|------------|--------------|-------------|-----------------|")
    for lvl in ANCHORS:
        dm = prod_ph("metal", lvl) - (prod_ph("metal", lvl - 1) if lvl > 1 else 0)
        dc = prod_ph("crystal", lvl) - (prod_ph("crystal", lvl - 1) if lvl > 1 else 0)
        df = prod_ph("fuel_cells", lvl) - (prod_ph("fuel_cells", lvl - 1) if lvl > 1 else 0)
        lines.append(f"| {lvl} | {fmt_num(dm)} | {fmt_num(dc)} | {fmt_num(df)} |")
    lines.append("")

    lines.append("## 2) Forschung — Ankerkurven (GC-825, vor Speed-Boni)")
    lines.append("")
    lines.append("### Basis-Dauer (Energieeffizienz-Tier = 1,0)")
    lines.append("")
    lines.append("| Forschungsstufe | Anker (h) | Dauer Speed ×1 |")
    lines.append("|-----------------|-----------|----------------|")
    for lvl in ANCHORS:
        h = research_time_anchor_hours(lvl)
        sec = research_base_time_seconds(lvl, time_tier=1.0)
        lines.append(f"| {lvl} | {h:g} | {fmt_time_sec(sec)} |")
    lines.append("")

    lines.append("### Basis-Kosten (Energieeffizienz-Tier = 1,0)")
    lines.append("")
    lines.append("| Forschungsstufe | Gesamt (Anker) | Ferronit | Crytite |")
    lines.append("|-----------------|----------------|----------|---------|")
    for lvl in ANCHORS:
        total = research_cost_anchor_total(lvl)
        m, c = research_upgrade_cost(1000, 500, lvl)
        lines.append(f"| {lvl} | {fmt_num(total)} | {fmt_num(m)} | {fmt_num(c)} |")
    lines.append("")

    lines.append("### Alle Technologien — Stufe 30 (Speed ×1, Labor L1, ohne Tech-Boni auf Zeit)")
    lines.append("")
    lines.append("| Technologie | Ferronit | Crytite | Dauer | Tier Zeit | Tier Kosten |")
    lines.append("|-------------|----------|---------|-------|-----------|-------------|")
    bld = {"research_lab": 1, "metal_mine": 3, "crystal_mine": 2}
    for key in sorted(RESEARCH_TECHS.keys()):
        cfg = RESEARCH_TECHS[key]
        m, c = research_upgrade_cost(int(cfg["base_cost_m"]), int(cfg["base_cost_c"]), 30)
        er = EffectResolver(bld, {key: 29}, settings=SPEED, player_id=1)
        t = er.get_research_time_seconds(key, 30)
        bt = float(cfg.get("base_time", 840))
        bc = int(cfg.get("base_cost_m", 0)) + int(cfg.get("base_cost_c", 0))
        lines.append(
            f"| {key} | {fmt_num(m)} | {fmt_num(c)} | {fmt_time_sec(t)} | "
            f"{bt/840:.2f} | {bc/1500:.2f} |"
        )
    lines.append("")

    lines.append("## 3) Minen-Upgrades — Kosten & Ziel-Amortisation (live)")
    lines.append("")
    lines.append(
        "Amortisation = Payback in **Produktionsstunden** der jeweiligen Ressource (Slot 9, Speed ×1)."
    )
    lines.append("")
    for btype, label in [
        ("metal_mine", "Ferronit-Mine"),
        ("crystal_mine", "Crytite-Mine"),
        ("fuel_cell_plant", "Brennzellen-Anlage"),
    ]:
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |")
        lines.append("|------------|----------|---------|--------|--------------|")
        for lvl in ANCHORS:
            m, c = power_upgrade_cost(btype, lvl)
            roi = mine_upgrade_roi_hours(btype, lvl, slot=SLOT, production_speed=1.0)
            lines.append(
                f"| {lvl} | {fmt_num(m)} | {fmt_num(c)} | {fmt_num(m + c)} | {roi:.0f} h |"
            )
        lines.append("")

    lines.append("### Minen ROI-Anker (explizite Zielwerte GC-821F)")
    lines.append("")
    lines.append("| Stufe | Ziel-Amortisation |")
    lines.append("|-------|-------------------|")
    for lvl, h in sorted(MINE_UPGRADE_ROI_TARGET_HOURS.items()):
        lines.append(f"| {lvl} | {h:.0f} h |")
    lines.append("")

    lines.append("## 4) Alle Gebäude — Upgrade-Kosten gesamt (F+C, live)")
    lines.append("")
    bnames = list(BUILDING_UPGRADE_CURVES.keys())
    lines.append("| Stufe | " + " | ".join(bnames) + " |")
    lines.append("|" + "---|" * (len(bnames) + 1))
    for lvl in [10, 20, 30, 40, 50]:
        row = f"| {lvl} |"
        for b in bnames:
            m, c = power_upgrade_cost(b, lvl)
            row += f" {fmt_num(m + c)} |"
        lines.append(row)
    lines.append("")
    lines.append(f"*Normaler Max-Level: {MAX_BUILDING_LEVEL}*")
    lines.append("")

    lines.append("## 5) Gebäude-Bauzeit — Live (GC-821 / GC-850A, vor Speed-Boni)")
    lines.append("")
    lines.append("Formel: `power_build_seconds` = `TIME_K × Level^Exponent` · ÷ `build_speed` / Tech-Boni im Resolver")
    lines.append("")
    lines.append("| Stufe | Ferronit | Crytite | Solar | Brennzellen | Labor | Werft | Command |")
    lines.append("|-------|----------|---------|-------|-------------|-------|-------|---------|")
    pick = [
        "metal_mine",
        "crystal_mine",
        "solar_plant",
        "fuel_cell_plant",
        "research_lab",
        "orbital_shipyard",
        "command_center",
    ]
    for lvl in ANCHORS:
        row = f"| {lvl} |"
        for b in pick:
            row += f" {fmt_time_sec(power_build_seconds(b, lvl))} |"
        lines.append(row)
    lines.append("")

    lines.append("## 6) Speicher & Tausch")
    lines.append("")
    lines.append(
        f"Speicher Basis L1: **{STORAGE_BASE_CAPACITY:,}** · Wachstum **×{STORAGE_LEVEL_GROWTH}**/Stufe".replace(",", ".")
    )
    lines.append("")
    lines.append("| Lager-Stufe | Kapazität |")
    lines.append("|-------------|-----------|")
    for lvl in [1, 5, 10, 20, 30, 40, 50]:
        cap = STORAGE_BASE_CAPACITY * (STORAGE_LEVEL_GROWTH ** max(0, lvl - 1))
        lines.append(f"| {lvl} | {fmt_num(cap)} |")
    lines.append("")
    lines.append(
        f"Tausch Tageslimit: min. **{EXCHANGE_DAILY_LIMIT_MIN:,}** oder **{EXCHANGE_DAILY_LIMIT_PCT_DEFAULT}%** "
        "Imperiums-Tagesproduktion".replace(",", ".")
    )
    lines.append("")

    lines.append("## 7) Code-Anker (Rohwerte)")
    lines.append("")
    lines.append(
        "**Forschung Zeit:** "
        + ", ".join(f"L{k}={v}h" for k, v in RESEARCH_TIME_ANCHOR_HOURS.items())
    )
    lines.append("")
    lines.append(
        "**Forschung Kosten:** "
        + ", ".join(f"L{k}={fmt_num(v)}" for k, v in RESEARCH_COST_ANCHOR_TOTAL.items())
    )
    lines.append("")
    lines.append(
        "**Minen ROI:** "
        + ", ".join(f"L{k}={v}h" for k, v in MINE_UPGRADE_ROI_TARGET_HOURS.items())
    )

    out = "\n".join(lines)
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
