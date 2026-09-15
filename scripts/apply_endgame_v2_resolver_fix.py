#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
resolver_path = ROOT / "game" / "effects" / "effect_resolver.py"
src = resolver_path.read_text(encoding="utf-8")

replacements = [
    (
        '''        # --- Research: mining_tech (+3% Ferronit per level — GC-820) ---\n        lm = _lvl(r, "mining_tech")\n        if lm > 0:\n            from ..production_formula import MINING_TECH_PER_LEVEL\n\n            metal_prod_factor *= 1.0 + MINING_TECH_PER_LEVEL * lm\n            sources.append(self._source_entry("metal_prod_factor", "mining_tech", metal_prod_factor, lm))\n''',
        '''        # --- Research: mining_tech (+3% Ferronit per effective level — GC-820/V2) ---\n        lm = _lvl(r, "mining_tech")\n        if lm > 0:\n            from ..production_formula import MINING_TECH_PER_LEVEL, research_effective_level\n\n            lm_effective = research_effective_level(lm)\n            metal_prod_factor *= 1.0 + MINING_TECH_PER_LEVEL * lm_effective\n            sources.append(self._source_entry("metal_prod_factor", "mining_tech", metal_prod_factor, lm))\n''',
    ),
    (
        '''        # --- Research: crystal_tech (+3% Crytite per level) ---\n        lc = _lvl(r, "crystal_tech")\n        if lc > 0:\n            from ..production_formula import CRYSTAL_TECH_PER_LEVEL\n\n            crystal_prod_factor *= 1.0 + CRYSTAL_TECH_PER_LEVEL * lc\n            sources.append(self._source_entry("crystal_prod_factor", "crystal_tech", crystal_prod_factor, lc))\n''',
        '''        # --- Research: crystal_tech (+3% Crytite per effective level — V2) ---\n        lc = _lvl(r, "crystal_tech")\n        if lc > 0:\n            from ..production_formula import CRYSTAL_TECH_PER_LEVEL, research_effective_level\n\n            lc_effective = research_effective_level(lc)\n            crystal_prod_factor *= 1.0 + CRYSTAL_TECH_PER_LEVEL * lc_effective\n            sources.append(self._source_entry("crystal_prod_factor", "crystal_tech", crystal_prod_factor, lc))\n''',
    ),
    (
        '''        # --- Research: drone_tech (+2% Ferronit + Crytite per level — GC-820) ---\n        ld = _lvl(r, "drone_tech")\n        if ld > 0:\n            from ..production_formula import DRONE_TECH_PER_LEVEL\n\n            drone_bonus = 1.0 + DRONE_TECH_PER_LEVEL * ld\n            metal_prod_factor *= drone_bonus\n            crystal_prod_factor *= drone_bonus\n            sources.append(self._source_entry("prod_factor", "drone_tech", drone_bonus, ld))\n''',
        '''        # --- Research: drone_tech (+2% Ferronit + Crytite per effective level — GC-820/V2) ---\n        ld = _lvl(r, "drone_tech")\n        if ld > 0:\n            from ..production_formula import DRONE_TECH_PER_LEVEL, research_effective_level\n\n            ld_effective = research_effective_level(ld)\n            drone_bonus = 1.0 + DRONE_TECH_PER_LEVEL * ld_effective\n            metal_prod_factor *= drone_bonus\n            crystal_prod_factor *= drone_bonus\n            sources.append(self._source_entry("prod_factor", "drone_tech", drone_bonus, ld))\n''',
    ),
]

for old, new in replacements:
    if old not in src:
        raise SystemExit(f"expected resolver block not found:\n{old}")
    src = src.replace(old, new, 1)

resolver_path.write_text(src, encoding="utf-8")

test_path = ROOT / "tests" / "test_endgame_economy_v2_resolver_cutover.py"
test_path.write_text(
    '''import pytest\n\nfrom game.effects.effect_resolver import EffectResolver\nfrom game import production_formula as pf\n\n\ndef _resolver(research):\n    return EffectResolver(\n        {\n            "metal_mine": 200,\n            "crystal_mine": 200,\n            "fuel_cell_plant": 200,\n            "solar_plant": 200,\n        },\n        research,\n        settings={"production_speed": 1.0, "build_speed": 1.0, "research_speed": 1.0},\n    )\n\n\ndef test_active_research_tail_is_applied_inside_effect_resolver(monkeypatch):\n    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")\n    research = {"mining_tech": 240, "crystal_tech": 240, "drone_tech": 240}\n    resolver = _resolver(research)\n    mods = resolver.get_modifiers()\n\n    expected_metal = pf.research_modifier_for("metal", research)\n    expected_crystal = pf.research_modifier_for("crystal", research)\n\n    assert mods["metal_prod_factor"] == pytest.approx(expected_metal, rel=1e-12)\n    assert mods["crystal_prod_factor"] == pytest.approx(expected_crystal, rel=1e-12)\n    assert resolver.prod_overlay_factor("metal") == pytest.approx(1.0, rel=1e-12)\n    assert resolver.prod_overlay_factor("crystal") == pytest.approx(1.0, rel=1e-12)\n\n\ndef test_active_resolver_output_uses_diminished_research_not_legacy_linear(monkeypatch):\n    research = {"mining_tech": 240, "crystal_tech": 240, "drone_tech": 240}\n\n    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")\n    active = _resolver(research).production_per_hour_exact(1.0)[0]\n\n    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")\n    legacy = _resolver(research).production_per_hour_exact(1.0)[0]\n\n    assert active > 0\n    assert active < legacy\n\n\ndef test_levels_through_120_remain_resolver_equivalent(monkeypatch):\n    research = {"mining_tech": 120, "crystal_tech": 120, "drone_tech": 120}\n\n    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")\n    legacy = _resolver(research).production_per_hour_exact(1.0)\n\n    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")\n    active = _resolver(research).production_per_hour_exact(1.0)\n\n    assert active == legacy\n''',
    encoding="utf-8",
)

print("patched EffectResolver research tail and added end-to-end regression")
