from pathlib import Path

fleet_path = Path("game/fleet.py")
fleet = fleet_path.read_text(encoding="utf-8")
start = fleet.index("def preview_mass_expedition_slot_split(")
end = fleet.index("def mass_expedition_from_ships(", start)
block = fleet[start:end]
needle = """                speed_percent=100,
                conn=conn,
            )
            if not ok_send:
"""
replacement = """                speed_percent=100,
                conn=conn,
                persist_resources=False,
            )
            if not ok_send:
"""
if needle not in block:
    raise SystemExit("mass expo preview validate_fleet_send anchor missing")
if block.count(needle) != 1:
    raise SystemExit(f"mass expo preview anchor count={block.count(needle)}")
block = block.replace(needle, replacement, 1)
fleet = fleet[:start] + block + fleet[end:]
fleet_path.write_text(fleet, encoding="utf-8")

app_path = Path("app.py")
app = app_path.read_text(encoding="utf-8")

live_old = """_FLEET_MUTATION_LIVE_SOURCES = frozenset(
    {
        "api_fleet_send",
        "api_fleet_bulk_launch_presets",
        "api_fleet_recall",
    }
)
"""
live_new = """_FLEET_MUTATION_LIVE_SOURCES = frozenset(
    {
        "api_fleet_send",
        "api_fleet_bulk_launch_presets",
        "api_fleet_recall",
        "api_fleet_mass_expedition",
    }
)
"""
if live_old not in app:
    raise SystemExit("fleet mutation live sources anchor missing")
app = app.replace(live_old, live_new, 1)

diet_start = app.index("def _uses_action_state_diet(")
diet_end = app.index("def _hud_only_game_state(", diet_start)
diet = app[diet_start:diet_end]
diet_needle = '        "api_fleet_recall",\n'
if diet_needle not in diet:
    raise SystemExit("action state diet fleet recall anchor missing")
if '"api_fleet_mass_expedition"' not in diet:
    diet = diet.replace(
        diet_needle,
        diet_needle + '        "api_fleet_mass_expedition",\n',
        1,
    )
app = app[:diet_start] + diet + app[diet_end:]
app_path.write_text(app, encoding="utf-8")

doc_path = Path("docs/FLEET_SYSTEM.md")
doc = doc_path.read_text(encoding="utf-8")
anchor = "| `/api/fleet/mass-expedition/preview` | POST | Split preview (`usable_slots`, `reserved_slots`) |"
if anchor not in doc:
    raise SystemExit("fleet docs mass expo preview row missing")
replacement_doc = anchor + "\n\n**GC-PERF-MASS-EXPO-002:** Mass-Expedition-Preview ist strikt read-only. Ressourcen werden nur in-memory projiziert (`persist_resources=False`), damit parallele Previews keinen Planet-Row-Lock halten. Der Mass-Expedition-Mutations-Response nutzt denselben schlanken Poll-/Action-State-Pfad wie normales Fleet-Send."
if "GC-PERF-MASS-EXPO-002" not in doc:
    doc = doc.replace(anchor, replacement_doc, 1)
doc_path.write_text(doc, encoding="utf-8")
