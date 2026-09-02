#!/usr/bin/env python3
from pathlib import Path

path = Path("tests/test_mine_evolution.py")
text = path.read_text(encoding="utf-8")
old = '''        buildings = get_planet_buildings(pid)\n        buildings["metal_mine"] = 180\n        save_planet_buildings(pid, buildings)\n'''
new = '''        buildings = get_planet_buildings(pid)\n        # This panel test is about the pre-Ascension L180 state, not the\n        # low-Nexus cap. Give the fixture enough normal Nexus progression\n        # to make L180 legal while still remaining below the L200 boundary.\n        buildings["planet_core_nexus"] = 150\n        buildings["metal_mine"] = 180\n        save_planet_buildings(pid, buildings)\n'''
if old not in text:
    raise SystemExit("mine panel fixture target not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Aligned mine panel fixture with canonical Nexus progression")
