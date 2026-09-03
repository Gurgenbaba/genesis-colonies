"""One-shot GC-MINE-ASC-NEXUS-001 patch helper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    src = path.read_text(encoding="utf-8")
    if new in src:
        print(f"{label}: already applied")
        return
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one marker, got {count}")
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print(f"{label}: applied")


def main() -> int:
    resolver = ROOT / "game" / "effects" / "effect_resolver.py"
    buildings = ROOT / "game" / "buildings.py"
    formulas = ROOT / "game" / "mine_evolution" / "formulas.py"
    service = ROOT / "game" / "mine_evolution" / "service.py"
    effects_test = ROOT / "tests" / "test_effects.py"
    mine_test = ROOT / "tests" / "test_mine_evolution.py"

    replace_once(
        resolver,
        '''    def get_max_building_level(self, building_type: str) -> int:\n        # EPIC-29: production mines are uncapped (soft sentinel); solar keeps nexus formula.\n        if building_type in ("metal_mine", "crystal_mine", "fuel_cell_plant"):\n            from ..mine_evolution import UNCAPPED_BUILDING_LEVEL\n\n            return int(UNCAPPED_BUILDING_LEVEL)\n\n        base_max = self.MAX_BUILDING_LEVEL\n        b = self.buildings\n        core = _bld(b, "planet_core_nexus")\n        geo = _bld(b, "geothermal_nexus")\n\n        if building_type == "solar_plant":\n            return base_max + core + geo * 2\n        if building_type in ("metal_storage", "crystal_storage", "fuel_storage"):\n            return base_max + geo * 2\n        return base_max''',
        '''    def get_max_building_level(self, building_type: str) -> int:\n        # GC-MINE-ASC-NEXUS-001: Nexus levels are the pre-Ascension hard cap.\n        # Ascension is deliberately applied by the Buildings queue owner because\n        # the rank is per (planet_id, building_type), not a global resolver cap.\n        base_max = self.MAX_BUILDING_LEVEL\n        b = self.buildings\n        core = _bld(b, "planet_core_nexus")\n        geo = _bld(b, "geothermal_nexus")\n        nexus_production_cap = base_max + core + geo * 2\n\n        if building_type in (\n            "metal_mine",\n            "crystal_mine",\n            "fuel_cell_plant",\n            "solar_plant",\n        ):\n            return nexus_production_cap\n        if building_type in ("metal_storage", "crystal_storage", "fuel_storage"):\n            return base_max + geo * 2\n        return base_max''',
        "resolver nexus mine cap",
    )

    replace_once(
        buildings,
        '''    panel_ctx = BuildingsPanelContext.for_planet(planet, buildings, research_levels, ratio, conn=conn)\n    max_level = panel_ctx.max_level(btype)\n    from .technical_data import (''',
        '''    panel_ctx = BuildingsPanelContext.for_planet(planet, buildings, research_levels, ratio, conn=conn)\n    base_max_level = panel_ctx.max_level(btype)\n    max_level = _effective_building_queue_cap(\n        btype,\n        base_max_level,\n        planet_id=planet_id,\n        conn=conn,\n    )\n    from .technical_data import (''',
        "technical data ascension cap",
    )

    replace_once(
        buildings,
        '''    gate = int(required_level_for_evolution(rank + 1) or 0)\n    if gate <= 0:\n        return max_level\n    return min(max_level, gate)''',
        '''    gate = int(required_level_for_evolution(rank + 1) or 0)\n    if gate <= 0:\n        return max_level\n    # Before Rank I, Nexus progression is the real cap (up to L200). Once\n    # this mine ascends, its own rank extends only this mine to the next\n    # milestone (I→225, II→250, ...), independent of the other mines.\n    if rank <= 0:\n        return min(max_level, gate)\n    return gate''',
        "rank extends nexus cap",
    )

    replace_once(
        buildings,
        '''    if building_type == "geothermal_nexus":\n        # EPIC-29: mines uncapped — nexus still raises solar + storage caps.''',
        '''    if building_type == "geothermal_nexus":\n        # Nexus raises the pre-Ascension mine/solar cap and the storage cap.''',
        "geothermal card comment",
    )
    replace_once(
        buildings,
        '''    if building_type == "planet_core_nexus":\n        # EPIC-29: core raises solar (and formerly mine) cap — mines are uncapped.''',
        '''    if building_type == "planet_core_nexus":\n        # Core raises the pre-Ascension production cap (mines + solar).''',
        "core card comment",
    )

    replace_once(
        formulas,
        '''# Soft sentinel for EffectResolver / enqueue (not a gameplay wall).\nUNCAPPED_BUILDING_LEVEL = 10_000''',
        '''# Legacy/admin safety sentinel only. Normal player mine caps are Nexus-based\n# through L200, then extended per mine by completed Ascension ranks.\nUNCAPPED_BUILDING_LEVEL = 10_000''',
        "legacy sentinel comment",
    )

    replace_once(
        service,
        '''    from ..options import vacation_blocks_outbound\n\n    ok_vacation, vac_reason = vacation_blocks_outbound(int(user_id), conn=db())\n    if not ok_vacation:\n        return False, vac_reason, {}\n\n    conn = db()\n    try:\n        begin_write_transaction(conn)''',
        '''    from ..options import vacation_blocks_outbound\n\n    # GC-MINE-ASC-NEXUS-001: reuse the mutation connection for the vacation\n    # probe instead of leaking an orphan checkout immediately before the TX.\n    conn = db()\n    try:\n        ok_vacation, vac_reason = vacation_blocks_outbound(int(user_id), conn=conn)\n        if not ok_vacation:\n            return False, vac_reason, {}\n\n        begin_write_transaction(conn)''',
        "ascension single connection",
    )

    replace_once(
        effects_test,
        '''        assert e1 > e0\n        # EPIC-29: mines uncapped; geo still raises solar/storage caps.\n        from game.mine_evolution import UNCAPPED_BUILDING_LEVEL\n\n        assert get_max_level_for_building("metal_mine", b2) == UNCAPPED_BUILDING_LEVEL\n        assert get_max_level_for_building("solar_plant", b2) == 50 + 4\n        assert get_max_level_for_building("metal_storage", b2) == 54\n\n    def test_geothermal_and_core_stack_max_levels(self):\n        b = {\n            "planet_core_nexus": 3,\n            "geothermal_nexus": 2,\n        }\n        from game.mine_evolution import UNCAPPED_BUILDING_LEVEL\n\n        assert EffectResolver(b, {}).get_max_building_level("solar_plant") == 57\n        assert EffectResolver(b, {}).get_max_building_level("fuel_cell_plant") == UNCAPPED_BUILDING_LEVEL\n        assert EffectResolver(b, {}).get_max_building_level("metal_storage") == 54''',
        '''        assert e1 > e0\n        # Geothermal raises the pre-Ascension producer cap (+2 per level).\n        assert get_max_level_for_building("metal_mine", b2) == 50 + 4\n        assert get_max_level_for_building("solar_plant", b2) == 50 + 4\n        assert get_max_level_for_building("metal_storage", b2) == 54\n\n    def test_geothermal_and_core_stack_max_levels(self):\n        b = {\n            "planet_core_nexus": 3,\n            "geothermal_nexus": 2,\n        }\n\n        assert EffectResolver(b, {}).get_max_building_level("solar_plant") == 57\n        assert EffectResolver(b, {}).get_max_building_level("fuel_cell_plant") == 57\n        assert EffectResolver(b, {}).get_max_building_level("metal_storage") == 54''',
        "effects nexus assertions",
    )

    replace_once(
        mine_test,
        '''class TestMineEvolutionCaps:\n    def test_mines_uncapped_solar_still_capped(self):\n        from game.effects.effect_resolver import EffectResolver\n\n        buildings = {\n            "metal_mine": 10,\n            "crystal_mine": 10,\n            "fuel_cell_plant": 10,\n            "solar_plant": 10,\n            "planet_core_nexus": 5,\n            "geothermal_nexus": 3,\n        }\n        er = EffectResolver(buildings, {})\n        assert er.get_max_building_level("metal_mine") == UNCAPPED_BUILDING_LEVEL\n        assert er.get_max_building_level("crystal_mine") == UNCAPPED_BUILDING_LEVEL\n        assert er.get_max_building_level("fuel_cell_plant") == UNCAPPED_BUILDING_LEVEL\n        assert er.get_max_building_level("solar_plant") == 50 + 5 + 2 * 3\n        assert er.get_max_building_level("metal_storage") == 50 + 2 * 3\n        assert er.get_max_building_level("research_lab") == 50''',
        '''class TestMineEvolutionCaps:\n    def test_mines_and_solar_share_nexus_cap_before_ascension(self):\n        from game.effects.effect_resolver import EffectResolver\n\n        buildings = {\n            "metal_mine": 10,\n            "crystal_mine": 10,\n            "fuel_cell_plant": 10,\n            "solar_plant": 10,\n            "planet_core_nexus": 5,\n            "geothermal_nexus": 3,\n        }\n        er = EffectResolver(buildings, {})\n        producer_cap = 50 + 5 + 2 * 3\n        assert er.get_max_building_level("metal_mine") == producer_cap\n        assert er.get_max_building_level("crystal_mine") == producer_cap\n        assert er.get_max_building_level("fuel_cell_plant") == producer_cap\n        assert er.get_max_building_level("solar_plant") == producer_cap\n        assert er.get_max_building_level("metal_storage") == 50 + 2 * 3\n        assert er.get_max_building_level("research_lab") == 50\n\n    def test_max_nexuses_unlock_level_200_before_rank_one(self):\n        from game.effects.effect_resolver import EffectResolver\n\n        buildings = {"planet_core_nexus": 50, "geothermal_nexus": 50}\n        er = EffectResolver(buildings, {})\n        for key in ("metal_mine", "crystal_mine", "fuel_cell_plant", "solar_plant"):\n            assert er.get_max_building_level(key) == 200''',
        "mine evolution nexus caps",
    )

    replace_once(
        mine_test,
        '''    def test_queue_cap_helper_preserves_legacy_overlevel_catchup(self):\n        import game.buildings as bmod\n\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", UNCAPPED_BUILDING_LEVEL, planet_id=1, evolution_rank=0\n        ) == 200\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", UNCAPPED_BUILDING_LEVEL, planet_id=1, evolution_rank=2\n        ) == 250\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", UNCAPPED_BUILDING_LEVEL, planet_id=1, evolution_rank=4\n        ) == 300''',
        '''    def test_queue_cap_helper_combines_nexus_phase_and_per_mine_rank(self):\n        import game.buildings as bmod\n\n        # Rank 0 follows the actual Nexus cap until the L200 Ascension gate.\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", 137, planet_id=1, evolution_rank=0\n        ) == 137\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", 200, planet_id=1, evolution_rank=0\n        ) == 200\n        # Completed ranks extend this mine beyond the Nexus ceiling.\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", 200, planet_id=1, evolution_rank=1\n        ) == 225\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", 200, planet_id=1, evolution_rank=2\n        ) == 250\n        assert bmod._effective_building_queue_cap(\n            "metal_mine", 200, planet_id=1, evolution_rank=4\n        ) == 300''',
        "queue cap helper contract",
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
