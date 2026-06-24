"""
GC-850A — EffectResolver build time uses economy_balance.power_build_seconds (GC-821).
"""

from __future__ import annotations

import pytest

from game.buildings import BUILDING_ORDER
from game.economy_balance import power_build_seconds
from game.effects import EffectResolver

ANCHOR_LEVELS = (10, 20, 30, 40, 60, 80, 100, 120)
SPEED_ONE = {"production_speed": 1.0, "build_speed": 1.0, "research_speed": 1.0}


def _resolver_at_speed_one() -> EffectResolver:
    return EffectResolver({}, {}, settings=SPEED_ONE)


class TestGc850aBuildTimeWiring:
    def test_resolver_matches_power_build_seconds_at_speed_one(self):
        er = _resolver_at_speed_one()
        for btype in BUILDING_ORDER:
            for lvl in (1, 10, 30, 50):
                design = power_build_seconds(btype, lvl)
                live = er.get_build_time_seconds(btype, lvl)
                assert live == design, f"{btype} L{lvl}: resolver={live} design={design}"

    def test_anchor_levels_match_gc_anchor_tables(self):
        er = _resolver_at_speed_one()
        pick = (
            "metal_mine",
            "crystal_mine",
            "solar_plant",
            "fuel_cell_plant",
            "research_lab",
            "orbital_shipyard",
            "command_center",
        )
        for btype in pick:
            for lvl in ANCHOR_LEVELS:
                assert er.get_build_time_seconds(btype, lvl) == power_build_seconds(btype, lvl)

    def test_build_speed_setting_scales_inversely(self):
        er_fast = EffectResolver({}, {}, settings={"build_speed": 2.0})
        er_slow = EffectResolver({}, {}, settings={"build_speed": 1.0})
        lvl = 20
        t_fast = er_fast.get_build_time_seconds("metal_mine", lvl)
        t_slow = er_slow.get_build_time_seconds("metal_mine", lvl)
        base = power_build_seconds("metal_mine", lvl)
        assert t_fast == max(1, int(base / 2.0))
        assert t_slow == base
        assert t_fast < t_slow

    def test_buildtime_tech_reduces_duration(self):
        base_er = _resolver_at_speed_one()
        mod_er = EffectResolver({}, {"buildtime_tech": 10}, settings=SPEED_ONE)
        base = base_er.get_build_time_seconds("research_lab", 15)
        mod = mod_er.get_build_time_seconds("research_lab", 15)
        assert mod < base


class TestGc850aDisplayContract:
    """Card = queue enqueue = technical modal (same get_build_time / resolver path)."""

    @pytest.fixture(autouse=True)
    def _speed_one_resolver(self, monkeypatch):
        def _factory(_user_id, *, buildings=None, research=None, conn=None, force_refresh=False, **kwargs):
            return EffectResolver(
                dict(buildings or {}),
                dict(research or {}),
                settings=SPEED_ONE,
            )

        monkeypatch.setattr("game.buildings.get_effect_resolver", _factory)

    @staticmethod
    def _planet():
        return {"player_id": 1, "metal": 10_000_000, "crystal": 10_000_000}

    def _assert_triple_match(self, btype: str, buildings: dict, target_level: int):
        from game.buildings import _make_panel_row, _technical_level_row, get_build_time

        planet = self._planet()
        research: dict = {}
        ratio = 1.0
        level = target_level - 1
        buildings = dict(buildings)
        buildings[btype] = level

        panel = _make_panel_row(
            planet, buildings, research, btype, queue_count=0, ratio=ratio, queue_free_slots=5
        )
        modal_row = _technical_level_row(
            btype,
            buildings,
            research,
            target_level,
            user_id=1,
            conn=None,
            ratio=ratio,
            is_current=False,
        )
        enqueue = get_build_time(
            btype, target_level, user_id=1, buildings=buildings, research_levels=research
        )

        assert panel["time_seconds"] == enqueue == modal_row["time_seconds"]

    def test_mine_l20_l30(self):
        for lvl in (20, 30):
            self._assert_triple_match("metal_mine", {"metal_mine": lvl - 1}, lvl)
            self._assert_triple_match("crystal_mine", {"crystal_mine": lvl - 1}, lvl)

    def test_lab_and_shipyard_l20_plus(self):
        for lvl in (20, 25, 30):
            self._assert_triple_match(
                "research_lab",
                {"metal_mine": 3, "crystal_mine": 2, "research_lab": lvl - 1},
                lvl,
            )
            self._assert_triple_match(
                "orbital_shipyard",
                {"command_center": 2, "orbital_shipyard": lvl - 1},
                lvl,
            )
