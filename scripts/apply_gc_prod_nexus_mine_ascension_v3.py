#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"target not found in {path}: {old[:160]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Nexus owns the normal mine cap up to L200. Ascension owns progression after L200.
replace_once(
    "game/effects/effect_resolver.py",
    '''    def get_max_building_level(self, building_type: str) -> int:\n        # EPIC-29: production mines are uncapped (soft sentinel); solar keeps nexus formula.\n        if building_type in ("metal_mine", "crystal_mine", "fuel_cell_plant"):\n            from ..mine_evolution import UNCAPPED_BUILDING_LEVEL\n\n            return int(UNCAPPED_BUILDING_LEVEL)\n\n        base_max = self.MAX_BUILDING_LEVEL\n        b = self.buildings\n        core = _bld(b, "planet_core_nexus")\n        geo = _bld(b, "geothermal_nexus")\n\n        if building_type == "solar_plant":\n            return base_max + core + geo * 2\n''',
    '''    def get_max_building_level(self, building_type: str) -> int:\n        base_max = self.MAX_BUILDING_LEVEL\n        b = self.buildings\n        core = _bld(b, "planet_core_nexus")\n        geo = _bld(b, "geothermal_nexus")\n\n        if building_type in ("metal_mine", "crystal_mine", "fuel_cell_plant"):\n            from ..mine_evolution import FIRST_EVOLUTION_LEVEL\n\n            # Canonical progression: Nexuses unlock normal mine levels, but never\n            # beyond L200. Mine Ascension takes over after that boundary.\n            return min(base_max + core + geo * 2, int(FIRST_EVOLUTION_LEVEL))\n\n        if building_type == "solar_plant":\n            return base_max + core + geo * 2\n''',
)

replace_once(
    "game/buildings.py",
    '''    gate = int(required_level_for_evolution(rank + 1) or 0)\n    if gate <= 0:\n        return max_level\n    return min(max_level, gate)\n''',
    '''    gate = int(required_level_for_evolution(rank + 1) or 0)\n    if gate <= 0:\n        return max_level\n    # Before the first Ascension, the Nexus-derived normal cap is authoritative\n    # (and tops out at L200). Once Rank I exists, Ascension owns the endgame\n    # gate: I -> 225, II -> 250, ... independent of further Nexus growth.\n    if rank <= 0:\n        return min(max_level, gate)\n    return gate\n''',
)

replace_once(
    "static/main.js",
    '''  function mapActionError(reason, payload) {\n    if (reason === "not_enough_resources" && payload) {\n''',
    '''  function mapActionError(reason, payload) {\n    if (reason === "ascension_required") {\n      const progress = t("buildings_mine_evo_progress", "Nächste Ascension");\n      const action = t("buildings_mine_evo_action", "Ascension einleiten");\n      return `${progress}: ${action}`;\n    }\n    if (reason === "not_enough_resources" && payload) {\n''',
)

replace_once(
    "docs/MINE_EVOLUTION.md",
    '''| Soft-uncapped resolver + **enqueue gate at the next Ascension milestone** | Permanent hard max on mines |\n''',
    '''| Nexus-limited normal progression to **L200**, then Ascension gates every +25 levels | Permanent hard max on mines |\n''',
)
replace_once(
    "docs/MINE_EVOLUTION.md",
    '''| `metal_mine`, `crystal_mine`, `fuel_cell_plant` | Resolver remains soft-uncapped (`UNCAPPED_BUILDING_LEVEL`), but **new build jobs stop at `required_level(rank+1)` until that Ascension is completed** |\n''',
    '''| `metal_mine`, `crystal_mine`, `fuel_cell_plant` | Nexuses unlock normal levels up to **L200**. At L200 Ascension I is required; each completed Ascension unlocks the next **25 mine levels** (225, 250, 275, ...). |\n''',
)
replace_once(
    "docs/MINE_EVOLUTION.md",
    '''Nexus no longer raises the **mine** hardcap. The resolver stays uncapped, while the build queue uses the next Ascension milestone as a progression gate. Existing overlevel/catch-up levels are never reduced.\n''',
    '''**Canonical contract:** Nexuses are the normal building-limit system and can unlock mines only up to L200. Ascension begins exactly there and takes over further mine progression in 25-level steps. Existing overlevel/catch-up levels are never reduced.\n''',
)
replace_once(
    "docs/BUILDINGS_SYSTEM.md",
    '''| `metal_mine`, `crystal_mine`, `fuel_cell_plant` | Resolver soft-uncapped; **Build-Enqueue nur bis zum nächsten Ascension-Milestone `required_level(rank+1)`** |\n''',
    '''| `metal_mine`, `crystal_mine`, `fuel_cell_plant` | Nexus-Limit bis **L200**; danach Mine-Ascension in +25-Level-Gates (225, 250, 275, ...) |\n''',
)
replace_once(
    "docs/EFFECTS.md",
    '''EPIC-29: production mines uncapped ([MINE_EVOLUTION.md](MINE_EVOLUTION.md)); nexus still raises solar/storage caps''',
    '''production mines are Nexus-limited up to L200, then Mine Ascension owns further +25-level gates ([MINE_EVOLUTION.md](MINE_EVOLUTION.md)); nexus still raises solar/storage caps''',
)

# Stellar Forge runtime already increases ships per production cycle; align docs.
forge = Path("docs/STELLAR_FORGE.md")
forge_text = forge.read_text(encoding="utf-8")
if '''4. Grants **capability unlocks per rank**, not raw build-speed multipliers that would blow out ship-count inflation further.\n\nNo second shipyard engine. Stellar Forge reads/writes its own rank state and layers modifiers onto the existing shipyard math in `game/shipyard.py` — it does not reimplement batch capacity, build time, or the build queue.\n''' in forge_text:
    forge_text = forge_text.replace(
        '''4. Grants **capability unlocks per rank**, not raw build-speed multipliers that would blow out ship-count inflation further.\n\nNo second shipyard engine. Stellar Forge reads/writes its own rank state and layers modifiers onto the existing shipyard math in `game/shipyard.py` — it does not reimplement batch capacity, build time, or the build queue.\n''',
        '''4. Increases **ships built per production cycle** through the existing shipyard batch-capacity math, while also granting capability unlocks.\n\nNo second shipyard engine. Stellar Forge reads/writes its own rank state and layers modifiers onto the existing shipyard math in `game/shipyard.py` — it does not reimplement batch capacity, build time, or the build queue. `orbital_production_batch_capacity(..., forge_rank)` is authoritative for the throughput increase.\n''',
        1,
    )
if '''| Ranks I–III, capability unlocks only (extra queue slot, Ascension HUD, Nanite-Assisted order option) | Specialization (Vanguard/Logistics/Odyssey forge), Redline Overdrive, Capital Hulls |\n''' in forge_text:
    forge_text = forge_text.replace(
        '''| Ranks I–III, capability unlocks only (extra queue slot, Ascension HUD, Nanite-Assisted order option) | Specialization (Vanguard/Logistics/Odyssey forge), Redline Overdrive, Capital Hulls |\n''',
        '''| Ranks I–III: higher ships-per-cycle batch capacity plus capability unlocks (extra queue slot, Ascension HUD, Nanite-Assisted order option) | Specialization (Vanguard/Logistics/Odyssey forge), Redline Overdrive, Capital Hulls |\n''',
        1,
    )
forge.write_text(forge_text, encoding="utf-8")

print("Applied canonical Nexus -> L200 -> Ascension contract")
