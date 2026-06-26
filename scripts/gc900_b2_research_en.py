#!/usr/bin/env python3
"""GC-900B-2: Backfill and fix Research EN locale keys."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EN_PATH = ROOT / "locales" / "en.json"

RESEARCH_EN: dict[str, str] = {
    "btn_research": "Start Research",
    "label_research": "Research",
    "overview_label_score_research": "Research",
    "overview_panel_research_hint": "Active projects and core technologies at a glance.",
    "overview_research_none": "No research active right now.",
    "research_active_header": "Active Research",
    "research_no_active": "No active research.",
    "research_panel_tech_hint": "All core technologies for this colony.",
    "research_msg_error": "An error occurred while starting research.",
    "research_msg_started": "Started research level %(level)s. Remaining: %(seconds)s seconds.",
    "research_msg_started_fmt": "Started research level {level}. Remaining: {seconds} seconds.",
    "desc_tech_construction_optimization": "Reduces building and research times through standard modules and automation.",
    "tech_construction_optimization_desc": "Reduces building and research times through standard modules and automation.",
    "tech_energy_efficiency_desc": "Optimizes systems and reduces mine energy use by 5% per level. The effect scales with every additional research level.",
    "tech_metal_refining": "Ferronite Refinement",
    "tech_weapon_tech": "Weapon Development",
    "tech_armor_tech": "Armor Technology",
    "tech_shield_tech": "Shield Technology",
}


def main() -> None:
    data = json.loads(EN_PATH.read_text(encoding="utf-8"))
    changed = 0
    for key, val in RESEARCH_EN.items():
        if data.get(key) != val:
            data[key] = val
            changed += 1
    EN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"GC-900B-2: updated {changed} EN keys")


if __name__ == "__main__":
    main()
