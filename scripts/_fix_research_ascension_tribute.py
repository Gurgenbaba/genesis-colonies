from pathlib import Path

path = Path("game/research_lab_ascension.py")
text = path.read_text(encoding="utf-8")
old = '''    gate = required_level_for_rank(r)\n    from .mine_evolution.formulas import evolution_tribute_cost\n\n    raw = evolution_tribute_cost("research_lab", gate)\n    total = max(0, int(raw.get("metal", 0) or 0)) + max(0, int(raw.get("crystal", 0) or 0))\n'''
new = '''    gate = required_level_for_rank(r)\n    from .buildings import get_upgrade_cost\n\n    # Same endgame Ascension anchor as the mine system: 25% of the canonical\n    # upgrade spend across the 40 levels ending at the rank milestone.\n    total_upgrade_spend = 0\n    for target_level in range(max(1, gate - 39), gate + 1):\n        metal_cost, crystal_cost = get_upgrade_cost("research_lab", target_level - 1)\n        total_upgrade_spend += int(metal_cost) + int(crystal_cost)\n    total = total_upgrade_spend // 4\n'''
if text.count(old) != 1:
    raise SystemExit(f"tribute replacement expected 1 match, got {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("research ascension tribute helper fixed")
