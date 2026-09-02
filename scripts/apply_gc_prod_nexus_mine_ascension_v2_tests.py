#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"test target not found in {path}: {old[:160]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


Path("tests/test_gc_prod_nexus_mine_ascension_contract.py").write_text(
    '''"""Canonical production contract: Nexus -> L200 -> Mine Ascension."""\n\nfrom pathlib import Path\n\nfrom game.buildings import _effective_building_queue_cap\nfrom game.effects.effect_resolver import EffectResolver\nfrom game.mine_evolution import UNCAPPED_BUILDING_LEVEL, required_level_for_evolution\n\n\ndef test_nexus_limits_normal_mine_progression_and_caps_at_200():\n    low = EffectResolver({"planet_core_nexus": 20, "geothermal_nexus": 10}, {})\n    assert low.get_max_building_level("metal_mine") == 90\n\n    maxed = EffectResolver({"planet_core_nexus": 100, "geothermal_nexus": 100}, {})\n    assert maxed.get_max_building_level("metal_mine") == 200\n    assert maxed.get_max_building_level("crystal_mine") == 200\n    assert maxed.get_max_building_level("fuel_cell_plant") == 200\n\n\ndef test_rank_zero_cannot_bypass_current_nexus_cap():\n    assert _effective_building_queue_cap(\n        "metal_mine", 90, planet_id=1, evolution_rank=0\n    ) == 90\n    assert _effective_building_queue_cap(\n        "metal_mine", 200, planet_id=1, evolution_rank=0\n    ) == 200\n\n\ndef test_ascension_takes_over_after_level_200_in_25_level_steps():\n    assert required_level_for_evolution(1) == 200\n    assert required_level_for_evolution(2) == 225\n    assert required_level_for_evolution(8) == 375\n    assert required_level_for_evolution(9) == 400\n\n    assert _effective_building_queue_cap(\n        "metal_mine", 200, planet_id=1, evolution_rank=1\n    ) == 225\n    assert _effective_building_queue_cap(\n        "metal_mine", 200, planet_id=1, evolution_rank=7\n    ) == 375\n    assert _effective_building_queue_cap(\n        "metal_mine", 200, planet_id=1, evolution_rank=8\n    ) == 400\n\n\ndef test_mando_level_385_needs_rank_viii_then_can_build_to_400():\n    before = _effective_building_queue_cap(\n        "metal_mine", 200, planet_id=1, evolution_rank=7\n    )\n    after = _effective_building_queue_cap(\n        "metal_mine", 200, planet_id=1, evolution_rank=8\n    )\n    assert before == 375\n    assert 385 > before\n    assert after == 400\n    assert 386 <= after\n\n\ndef test_legacy_uncapped_sentinel_still_cannot_skip_ascension_gates():\n    assert _effective_building_queue_cap(\n        "metal_mine", UNCAPPED_BUILDING_LEVEL, planet_id=1, evolution_rank=0\n    ) == 200\n    assert _effective_building_queue_cap(\n        "metal_mine", UNCAPPED_BUILDING_LEVEL, planet_id=1, evolution_rank=2\n    ) == 250\n\n\ndef test_ascension_error_has_localized_user_feedback():\n    src = Path("static/main.js").read_text(encoding="utf-8")\n    block = src.split("function mapActionError(reason, payload)", 1)[1].split("\\n  function ", 1)[0]\n    assert 'reason === "ascension_required"' in block\n    assert 't("buildings_mine_evo_progress"' in block\n    assert 't("buildings_mine_evo_action"' in block\n\n\ndef test_shipyard_ascension_increases_ships_per_cycle():\n    from game.shipyard import orbital_production_batch_capacity\n\n    base = orbital_production_batch_capacity(50, forge_rank=0)\n    rank1 = orbital_production_batch_capacity(50, forge_rank=1)\n    rank5 = orbital_production_batch_capacity(50, forge_rank=5)\n    assert rank1 > base\n    assert rank5 > rank1\n\n\ndef test_docs_lock_both_ascension_contracts():\n    mine_doc = Path("docs/MINE_EVOLUTION.md").read_text(encoding="utf-8")\n    forge_doc = Path("docs/STELLAR_FORGE.md").read_text(encoding="utf-8")\n    assert "Nexuses are the normal building-limit system" in mine_doc\n    assert "ships built per production cycle" in forge_doc\n    assert "orbital_production_batch_capacity(..., forge_rank)" in forge_doc\n''',
    encoding="utf-8",
)

# Update existing Nexus matrix from the obsolete 'mines uncapped' contract.
Path("tests/test_nexus_building_caps.py").write_text(
    '''"""GC-832 — Nexus building level-cap matrix.\n\nNexuses own normal mine progression up to L200. Mine Ascension owns levels above 200.\n"""\n\nfrom __future__ import annotations\n\nimport pytest\n\nfrom game.effects.effect_resolver import EffectResolver\n\nBASE = EffectResolver.MAX_BUILDING_LEVEL\n\n\n@pytest.mark.parametrize(\n    ("building", "core", "geo", "expected"),\n    [\n        ("metal_mine", 0, 0, BASE),\n        ("crystal_mine", 0, 0, BASE),\n        ("fuel_cell_plant", 0, 0, BASE),\n        ("metal_mine", 3, 2, BASE + 3 + 4),\n        ("fuel_cell_plant", 3, 2, BASE + 3 + 4),\n        ("solar_plant", 0, 0, BASE),\n        ("metal_storage", 0, 0, BASE),\n        ("solar_plant", 30, 20, BASE + 30 + 40),\n        ("metal_mine", 30, 20, BASE + 30 + 40),\n        ("metal_storage", 30, 20, BASE + 40),\n        ("crystal_storage", 5, 10, BASE + 20),\n        ("fuel_storage", 0, 15, BASE + 30),\n        ("research_lab", 50, 50, BASE),\n        ("geothermal_nexus", 50, 50, BASE),\n        ("metal_mine", 100, 100, 200),\n        ("fuel_cell_plant", 100, 100, 200),\n    ],\n)\ndef test_nexus_cap_matrix(building: str, core: int, geo: int, expected: int):\n    b = {"planet_core_nexus": core, "geothermal_nexus": geo}\n    assert EffectResolver(b, {}).get_max_building_level(building) == expected\n\n\ndef test_storage_ignores_planet_core_but_mines_do_not():\n    b = {"planet_core_nexus": 25, "geothermal_nexus": 0}\n    er = EffectResolver(b, {})\n    assert er.get_max_building_level("metal_storage") == BASE\n    assert er.get_max_building_level("metal_mine") == BASE + 25\n    assert er.get_max_building_level("solar_plant") == BASE + 25\n\n\ndef test_fuel_cell_matches_production_mine_nexus_cap():\n    b = {"planet_core_nexus": 10, "geothermal_nexus": 5}\n    er = EffectResolver(b, {})\n    assert er.get_max_building_level("metal_mine") == BASE + 20\n    assert er.get_max_building_level("fuel_cell_plant") == BASE + 20\n''',
    encoding="utf-8",
)

replace_once(
    "tests/test_mine_evolution.py",
    '''    def test_mines_uncapped_solar_still_capped(self):\n''',
    '''    def test_mines_nexus_limited_until_first_ascension(self):\n''',
)
replace_once(
    "tests/test_mine_evolution.py",
    '''        assert er.get_max_building_level("metal_mine") == UNCAPPED_BUILDING_LEVEL\n        assert er.get_max_building_level("crystal_mine") == UNCAPPED_BUILDING_LEVEL\n        assert er.get_max_building_level("fuel_cell_plant") == UNCAPPED_BUILDING_LEVEL\n        assert er.get_max_building_level("solar_plant") == 50 + 5 + 2 * 3\n''',
    '''        expected_prod_cap = 50 + 5 + 2 * 3\n        assert er.get_max_building_level("metal_mine") == expected_prod_cap\n        assert er.get_max_building_level("crystal_mine") == expected_prod_cap\n        assert er.get_max_building_level("fuel_cell_plant") == expected_prod_cap\n        assert er.get_max_building_level("solar_plant") == expected_prod_cap\n''',
)
replace_once(
    "tests/test_mine_evolution.py",
    '''    uname = f"mevo_{uuid.uuid4().hex[:8]}"\n''',
    '''    uname = f"Nova{uuid.uuid4().hex[:8]}"\n''',
)

replace_once(
    "tests/test_effects.py",
    '''        # EPIC-29: mines uncapped; geo still raises solar/storage caps.\n        from game.mine_evolution import UNCAPPED_BUILDING_LEVEL\n\n        assert get_max_level_for_building("metal_mine", b2) == UNCAPPED_BUILDING_LEVEL\n        assert get_max_level_for_building("solar_plant", b2) == 50 + 4\n''',
    '''        assert get_max_level_for_building("metal_mine", b2) == 50 + 4\n        assert get_max_level_for_building("solar_plant", b2) == 50 + 4\n''',
)
replace_once(
    "tests/test_effects.py",
    '''        from game.mine_evolution import UNCAPPED_BUILDING_LEVEL\n\n        assert EffectResolver(b, {}).get_max_building_level("solar_plant") == 57\n        assert EffectResolver(b, {}).get_max_building_level("fuel_cell_plant") == UNCAPPED_BUILDING_LEVEL\n''',
    '''        assert EffectResolver(b, {}).get_max_building_level("solar_plant") == 57\n        assert EffectResolver(b, {}).get_max_building_level("fuel_cell_plant") == 57\n''',
)

print("Applied canonical Nexus/Ascension regressions")
