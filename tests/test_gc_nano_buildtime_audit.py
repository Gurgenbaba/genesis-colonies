"""GC-NANO-BUILDTIME-AUDIT-001 — diminishing-returns nano + server preview contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from game.effects import EffectResolver
from game.technical_data import build_nanofactory_time_preview

ROOT = Path(__file__).resolve().parents[1]
SPEED_ONE = {"build_speed": 1.0, "production_speed": 1.0, "research_speed": 1.0}


def _er(buildings=None, research=None, build_speed=1.0):
    settings = dict(SPEED_ONE)
    settings["build_speed"] = float(build_speed)
    return EffectResolver(dict(buildings or {}), dict(research or {}), settings=settings)


class TestNanoDiminishingRuntime:
    def test_l0_to_l1_on_480_base(self, monkeypatch):
        monkeypatch.setattr(
            "game.economy_balance.power_build_seconds",
            lambda _btype, _level: 480,
        )
        t0 = _er().get_build_time_seconds("metal_mine", 5)
        t1 = _er({"nanofactory": 1}).get_build_time_seconds("metal_mine", 5)
        assert t0 == 480
        assert t1 == max(int(480 / EffectResolver.nanofactory_build_speed(1)), 1)
        assert t1 == 309  # int(480 / 1.55)
        assert t0 - t1 == 171

    def test_buildtime_tech_l2_is_about_three_percent(self, monkeypatch):
        monkeypatch.setattr(
            "game.economy_balance.power_build_seconds",
            lambda _btype, _level: 480,
        )
        base = _er().get_build_time_seconds("metal_mine", 5)
        with_bt = _er({}, {"buildtime_tech": 2}).get_build_time_seconds("metal_mine", 5)
        saved = base - with_bt
        assert base == 480
        assert 14 <= saved <= 16  # ~3.0–3.3% — not nano L0→L1 (~171 s)
        nano = _er({"nanofactory": 1}).get_build_time_seconds("metal_mine", 5)
        assert base - nano > 100

    def test_marginal_high_level_is_small_fraction(self, monkeypatch):
        monkeypatch.setattr(
            "game.economy_balance.power_build_seconds",
            lambda _btype, _level: 10_000,
        )
        # Pick nano where current effective display can sit near 480s after stack.
        nano = 12
        t_cur = _er({"nanofactory": nano}).get_build_time_seconds("metal_mine", 8)
        t_next = _er({"nanofactory": nano + 1}).get_build_time_seconds("metal_mine", 8)
        assert t_next < t_cur
        speed_cur = EffectResolver.nanofactory_build_speed(nano)
        speed_next = EffectResolver.nanofactory_build_speed(nano + 1)
        expected_ratio = speed_cur / speed_next
        assert t_next == pytest.approx(int(t_cur * expected_ratio) or t_next, abs=1)
        # Marginal save as % of current is much smaller than L0→L1 (~35%).
        pct = 100.0 * (t_cur - t_next) / t_cur
        assert pct < 10.0

    def test_command_center_does_not_affect_other_buildings(self):
        """CC only accelerates nanofactory upgrades — not metal_mine / normal buildings."""
        base = {"nanofactory": 25, "metal_mine": 10}
        t_no_cc = _er(base).get_build_time_seconds("metal_mine", 11)
        t_cc = _er({**base, "command_center": 20}).get_build_time_seconds("metal_mine", 11)
        assert t_no_cc == t_cc
        assert _er(base).get_build_time_duration_multiplier("metal_mine") == _er(
            {**base, "command_center": 20}
        ).get_build_time_duration_multiplier("metal_mine")

    def test_nano_25_to_26_marginal_about_three_percent(self, monkeypatch):
        """Player report: ~16s on an 8:00 display ≈ marginal Nano 25→26 (~2.7%), not −25%."""
        monkeypatch.setattr(
            "game.economy_balance.power_build_seconds",
            lambda _btype, _level: 480
            * EffectResolver.nanofactory_build_speed(25),  # so nano25 display ≈ 480s
        )
        t25 = _er({"nanofactory": 25}).get_build_time_seconds("metal_mine", 11)
        t26 = _er({"nanofactory": 26}).get_build_time_seconds("metal_mine", 11)
        assert t25 == 480
        saved = t25 - t26
        pct = 100.0 * saved / t25
        assert 12 <= saved <= 16
        assert 2.5 <= pct <= 3.5
        # CC must not change this comparison.
        assert t25 == _er({"nanofactory": 25, "command_center": 15}).get_build_time_seconds(
            "metal_mine", 11
        )

    def test_command_center_only_speeds_nanofactory_upgrade(self):
        t0 = _er({"nanofactory": 5, "command_center": 0}).get_build_time_seconds("nanofactory", 6)
        t_cc = _er({"nanofactory": 5, "command_center": 5}).get_build_time_seconds("nanofactory", 6)
        assert t_cc < t0
        # Existing nano level still applies to its own upgrade (current runtime rule).
        t_no_nano = _er({"nanofactory": 0, "command_center": 5}).get_build_time_seconds(
            "nanofactory", 6
        )
        assert t_cc < t_no_nano


class TestNanoPreviewPayload:
    def test_preview_matches_resolver_seconds(self, monkeypatch):
        monkeypatch.setattr(
            "game.economy_balance.power_build_seconds",
            lambda _btype, _level: 480,
        )
        buildings = {"metal_mine": 4, "nanofactory": 0}
        preview = build_nanofactory_time_preview(
            buildings,
            {},
            nano_level=0,
            settings=SPEED_ONE,
        )
        assert preview["reference_building"] == "metal_mine"
        assert preview["reference_target_level"] == 5
        assert preview["speed_current"] == 1.0
        assert preview["speed_next"] == 1.55
        assert preview["seconds_nano_0"] == 480
        assert preview["seconds_current"] == 480
        assert preview["seconds_next"] == 309
        assert preview["saved_vs_l0_seconds"] == 0
        assert preview["saved_marginal_seconds"] == 171
        assert preview["modifiers"]["buildtime_tech_level"] == 0

    def test_preview_separates_buildtime_tech(self, monkeypatch):
        monkeypatch.setattr(
            "game.economy_balance.power_build_seconds",
            lambda _btype, _level: 480,
        )
        preview = build_nanofactory_time_preview(
            {"metal_mine": 4, "nanofactory": 0},
            {"buildtime_tech": 2},
            nano_level=0,
            settings=SPEED_ONE,
        )
        assert preview["modifiers"]["buildtime_tech_level"] == 2
        assert preview["seconds_current"] < 480
        assert preview["saved_marginal_seconds"] < 171  # nano still applies on reduced base


class TestNanoDocsAndNoFrontendMath:
    def test_effects_and_buildings_docs_canonical_formula(self):
        effects = (ROOT / "docs/EFFECTS.md").read_text(encoding="utf-8")
        buildings = (ROOT / "docs/BUILDINGS_SYSTEM.md").read_text(encoding="utf-8")
        assert "0.55" in effects and "0.8" in effects
        assert "0.55" in buildings and "0.8" in buildings
        assert "duration `× 0.70^level`" not in effects
        assert "× 0.70^level" not in buildings
        assert "flat `level × 30 %`" not in effects
        assert "flat `level × 30 %`" not in buildings

    def test_gc858_superseded_for_nano_formula(self):
        text = (ROOT / "docs/GC-858_BUILD_TIME_MODIFIER_AUDIT.md").read_text(encoding="utf-8")
        assert "GC-NANO-BUILDTIME-AUDIT-001" in text
        assert "1 + 0.55" in text or "0.55 ×" in text

    def test_main_js_has_no_nano_coeff_duplicate(self):
        src = (ROOT / "static/main.js").read_text(encoding="utf-8")
        assert "NANOFACTORY_SPEED_COEFF" not in src
        assert "0.55 * " not in src
        assert "level ** 0.8" not in src
        assert "nano_time_preview" in src
        assert "nanofactory_build_time" in src
