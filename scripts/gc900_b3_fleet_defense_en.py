#!/usr/bin/env python3
"""GC-900B-3: Fleet, shipyard and defense EN locale canon fixes."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EN_PATH = ROOT / "locales" / "en.json"

FLEET_DEFENSE_EN: dict[str, str] = {
    "shipyard": "Orbital Shipyard",
    "fleet_shipyard_title": "Orbital Shipyard",
    "nav_shipyard": "Orbital Shipyard",
    "shipyard_btn_queue_full": "Orbital shipyard queue full",
    "defense_panel_planetary_title": "Planetary Defense",
    "defense_hint": "Build stationary turrets and shields to protect your colony. Unlocks via the Defense Factory and Orbital Shipyard.",
    "defense_buildable_subtitle": "Unlocked — production via orbital shipyard capacity",
    "defense_build_time_per_cycle": "Cycle: %(seconds)s s · Orbital yard ×%(capacity)s",
}


def main() -> None:
    data = json.loads(EN_PATH.read_text(encoding="utf-8"))
    changed = 0
    for key, val in FLEET_DEFENSE_EN.items():
        if data.get(key) != val:
            data[key] = val
            changed += 1
    EN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"GC-900B-3: updated {changed} EN keys")


if __name__ == "__main__":
    main()
