#!/usr/bin/env python3
"""GC-900B-1: Backfill and fix Buildings EN locale keys."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EN_PATH = ROOT / "locales" / "en.json"

BUILDING_EN: dict[str, str] = {
    "building_academy": "Genesis Academy",
    "building_barracks": "Orbital Barracks",
    "building_command_center": "Command Center",
    "building_crystal_mine": "Crytite Extractor",
    "building_crystal_storage": "Crytite Silo",
    "building_defense_factory": "Defense Factory",
    "building_metal_mine": "Ferronite Mine",
    "building_metal_storage": "Ferronite Depot",
    "building_nanofactory": "Nanofactory",
    "building_radar_array": "Deep-Space Radar Array",
    "building_research_lab": "Research Lab",
    "building_shield_generator": "Planetary Shield Generator",
    "building_solar_plant": "Solar Collector Field",
    "buildings_btn_active": "Active",
    "buildings_techtree_link": "View tech tree",
    "build_queue_title": "Build queue",
    "build_queue_remaining": "Remaining",
    "build_queue_time": "Build time",
    "build_queue_target": "Target",
    "build_queue_level_short": "L",
    "build_queue_hint": "{count} orders · Next completion: {eta}",
    "hud_storage_almost_full": "Storage almost full",
    "hud_storage_full": "Storage full",
    "label_buildings": "Buildings",
    "label_level": "Level",
    "msg_build_not_enough_resources_short": "Not enough Ferronite or Crytite.",
    "buildings_technical_yard_reference": "Orbital Shipyard L%(level)s: capacity %(capacity)s",
}


def main() -> None:
    data = json.loads(EN_PATH.read_text(encoding="utf-8"))
    changed = 0
    for key, val in BUILDING_EN.items():
        if data.get(key) != val:
            data[key] = val
            changed += 1
    EN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"GC-900B-1: updated {changed} EN keys")


if __name__ == "__main__":
    main()
