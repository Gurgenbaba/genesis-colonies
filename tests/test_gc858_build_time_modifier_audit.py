"""
GC-858 — Build-time modifier audit (no balance changes).

Run: python -m pytest tests/test_gc858_build_time_modifier_audit.py tests/test_gc850a_build_time_wiring.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from game.buildings import (
    NANOFACTORY_BUILD_BONUS_PER_LEVEL,
    nanofactory_build_bonus_pct,
)
from game.economy_balance import power_build_seconds
from game.effects import EffectResolver
from game.technical_data import build_production_milestones

ROOT = Path(__file__).resolve().parents[1]
SPEED_ONE = {"production_speed": 1.0, "build_speed": 1.0, "research_speed": 1.0}

NEUTRAL = ({}, {}, 1.0)
MIDGAME = ({"nanofactory": 5, "research_lab": 10}, {"buildtime_tech": 5}, 1.0)
FERDI_LIKE = (
    {"nanofactory": 22, "research_lab": 30, "command_center": 10},
    {"buildtime_tech": 17},
    10.0,
)


def _er(buildings: dict, research: dict, build_speed: float) -> EffectResolver:
    return EffectResolver(
        dict(buildings),
        dict(research),
        settings={"build_speed": build_speed, "production_speed": 1.0, "research_speed": 1.0},
    )


class TestGc858ModifierSources:
    def test_buildtime_tech_multiplies_speed(self):
        base = EffectResolver({}, {}, settings=SPEED_ONE)
        mod = EffectResolver({}, {"buildtime_tech": 10}, settings=SPEED_ONE)
        assert mod.get_build_time_seconds("metal_mine", 15) < base.get_build_time_seconds("metal_mine", 15)

    def test_nanofactory_applies_via_duration_multiplier(self):
        no_nano = EffectResolver({}, {}, settings=SPEED_ONE)
        with_nano = EffectResolver({"nanofactory": 8}, {}, settings=SPEED_ONE)
        assert with_nano.get_build_time_seconds("metal_mine", 15) < no_nano.get_build_time_seconds("metal_mine", 15)

    def test_command_center_only_affects_nanofactory_builds(self):
        b = {"nanofactory": 5, "command_center": 10}
        nano_upgrade = _er(b, {}, 1.0).get_build_time_seconds("nanofactory", 6)
        mine = _er(b, {}, 1.0).get_build_time_seconds("metal_mine", 20)
        no_cc = _er({"nanofactory": 5}, {}, 1.0).get_build_time_seconds("nanofactory", 6)
        assert nano_upgrade < no_cc
        assert _er({"nanofactory": 5, "command_center": 10}, {}, 1.0).get_build_time_seconds(
            "metal_mine", 20
        ) == mine

    def test_one_second_floor_is_enforced(self):
        er = _er(*FERDI_LIKE)
        for btype, lvl in (("metal_mine", 30), ("research_lab", 30), ("orbital_shipyard", 30)):
            assert er.get_build_time_seconds(btype, lvl) == 1


class TestGc858ExampleProfiles:
    @pytest.mark.parametrize(
        "profile,buildings,research,build_speed,expectations",
        [
            (
                "neutral",
                *NEUTRAL,
                [("metal_mine", 30, 11246)],
            ),
            (
                "midgame",
                *MIDGAME,
                [("metal_mine", 30, 1623)],
            ),
            (
                "ferdi_like",
                *FERDI_LIKE,
                [
                    ("metal_mine", 20, 1),
                    ("metal_mine", 30, 1),
                    ("metal_mine", 50, 1),
                    ("research_lab", 30, 1),
                    ("orbital_shipyard", 30, 1),
                ],
            ),
        ],
    )
    def test_profile_final_seconds(self, profile, buildings, research, build_speed, expectations):
        er = _er(buildings, research, build_speed)
        for btype, lvl, expected in expectations:
            assert er.get_build_time_seconds(btype, lvl) == expected, f"{profile} {btype} L{lvl}"


class TestGc858DisplayVsRuntime:
    def test_nanofactory_ui_flat_pct_differs_from_runtime(self):
        nano_level = 22
        ui_pct = nanofactory_build_bonus_pct(nano_level)
        assert ui_pct == NANOFACTORY_BUILD_BONUS_PER_LEVEL * nano_level
        er = _er({"nanofactory": nano_level}, {}, 1.0)
        runtime_pct = er.get_build_time_reduction_pct("metal_mine")
        assert ui_pct == 660
        assert runtime_pct == 100
        assert ui_pct != runtime_pct

    def test_production_milestone_is_not_build_time(self):
        buildings = {"metal_mine": 40, "crystal_mine": 30}
        research = {"mining_tech": 10, "drone_tech": 8}
        milestones = build_production_milestones(
            building_type="metal_mine",
            buildings=buildings,
            research_levels=research,
            ratio=1.0,
            current=40,
        )
        assert milestones
        big = max(int(m["display"].strip("+").strip().split()[0]) for m in milestones)
        er = _er({**buildings, "nanofactory": 22}, {"buildtime_tech": 17}, 10.0)
        assert big > 100
        assert er.get_build_time_seconds("metal_mine", 41) == 1

    def test_ferdi_like_card_modal_queue_still_match(self, monkeypatch):
        def _factory(_user_id, *, buildings=None, research=None, conn=None, force_refresh=False, **kwargs):
            return EffectResolver(
                dict(buildings or {}),
                dict(research or {}),
                settings={"build_speed": 10.0, "production_speed": 1.0, "research_speed": 1.0},
            )

        monkeypatch.setattr("game.buildings.get_effect_resolver", _factory)
        from game.buildings import _make_panel_row, _technical_level_row, get_build_time

        buildings = {"metal_mine": 29, "nanofactory": 22, "research_lab": 30, "command_center": 10}
        research = {"buildtime_tech": 17}
        planet = {"player_id": 1, "metal": 10_000_000, "crystal": 10_000_000}
        target = 30

        panel = _make_panel_row(
            planet, buildings, research, "metal_mine", queue_count=0, ratio=1.0, queue_free_slots=5
        )
        modal = _technical_level_row(
            "metal_mine", buildings, research, target, user_id=1, conn=None, ratio=1.0, is_current=False
        )
        enqueue = get_build_time("metal_mine", target, user_id=1, buildings=buildings, research_levels=research)
        assert panel["time_seconds"] == modal["time_seconds"] == enqueue == 1


class TestGc858AuditDoc:
    def test_audit_doc_exists_and_classifies(self):
        text = (ROOT / "docs/GC-858_BUILD_TIME_MODIFIER_AUDIT.md").read_text(encoding="utf-8")
        assert "UI GAP" in text
        assert "max(int(seconds), 1)" in text
        assert "ferdi_like" in text.lower() or "Ferdi" in text
        assert "BALANCE DECISION REQUIRED" in text

    def test_effects_doc_mentions_build_time_floor(self):
        text = (ROOT / "docs/EFFECTS.md").read_text(encoding="utf-8")
        assert "get_build_time_seconds" in text
        assert "1 second" in text.lower() or "1-second" in text.lower()
