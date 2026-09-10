from pathlib import Path

# The building card describes the local lab's prestige capacity. It must not
# resolve the account-wide effective queue (which also probes Galactic Directives)
# while BuildingsPanelContext is already resolving the same external mechanics.
# /research remains the canonical surface for effective account capacity.

p = Path("game/research_lab_ascension.py")
s = p.read_text(encoding="utf-8")
old = '''    tribute_m, tribute_c = tribute_cost_for_rank(next_rank)\n    return {\n        "research_lab_ascension": True,\n'''
new = '''    tribute_m, tribute_c = tribute_cost_for_rank(next_rank)\n    local_prestige_capacity = min(\n        PRESTIGE_SLOT_CAP,\n        base_slots_for_lab_level(int(level or 0)) + int(rank),\n    )\n    return {\n        "research_lab_ascension": True,\n        "research_queue_capacity": int(local_prestige_capacity),\n        "research_queue_prestige_capacity": int(local_prestige_capacity),\n'''
if s.count(old) != 1:
    raise SystemExit(f"research_lab_ascension panel anchor count={s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

p = Path("game/buildings.py")
s = p.read_text(encoding="utf-8")
old = '''    if pid is not None and building_type == "research_lab":\n        from .research_lab_ascension import panel_fields as research_lab_ascension_panel_fields\n        from .research_lab_ascension import research_queue_capacity\n\n        row.update(\n            research_lab_ascension_panel_fields(\n                int(planet.get("player_id") or 0),\n                pid,\n                level,\n                conn=evo_conn,\n            )\n        )\n        capacity = research_queue_capacity(\n            int(planet.get("player_id") or 0),\n            conn=evo_conn,\n        )\n        row["research_queue_capacity"] = int(capacity.get("limit") or 0)\n        row["research_queue_prestige_capacity"] = int(capacity.get("prestige_limit") or 0)\n'''
new = '''    if pid is not None and building_type == "research_lab":\n        from .research_lab_ascension import panel_fields as research_lab_ascension_panel_fields\n\n        # The card is planet-local. panel_fields provides this lab's prestige\n        # capacity without re-resolving account-wide Directive bonuses.\n        row.update(\n            research_lab_ascension_panel_fields(\n                int(planet.get("player_id") or 0),\n                pid,\n                level,\n                conn=evo_conn,\n            )\n        )\n'''
if s.count(old) != 1:
    raise SystemExit(f"buildings research panel anchor count={s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

print("research lab building-card capacity no longer performs duplicate account directive probe")
