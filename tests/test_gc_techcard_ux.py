"""GC-TECHCARD-UX-001 — Aussage statt Prozent contracts."""

from __future__ import annotations

from pathlib import Path

from game.technical_data import (
    build_building_technical_summary,
    build_impact_summary,
    build_production_display,
    build_research_technical_summary,
    build_storage_display,
    impact_from_duration_seconds,
    impact_from_rate,
    resolve_building_impact,
    resolve_research_impact,
)

ROOT = Path(__file__).resolve().parents[1]


def test_techcard_doc_exists():
    text = (ROOT / "docs/TECHCARD_UX.md").read_text(encoding="utf-8")
    assert "Four questions" in text or "four questions" in text.lower() or "Four questions" in text
    assert "impact" in text
    assert "Command Center" in text or "command_center" in text.lower()


def test_impact_summary_shape():
    impact = build_impact_summary(
        blurb_key="desc_metal_mine",
        current_value=100,
        current_unit="/h",
        next_from=100,
        next_to=110,
        next_delta=10,
        affects=[{"label_key": "building_metal_mine"}],
    )
    assert impact["blurb_key"] == "desc_metal_mine"
    assert impact["current"]["value"] == 100
    assert impact["next"]["from"] == 100
    assert impact["next"]["to"] == 110
    assert impact["next"]["delta"] == 10
    assert impact["next"]["delta_pct"] == 10.0
    assert impact["affects"][0]["label_key"] == "building_metal_mine"


def test_mine_summary_has_concrete_impact():
    buildings = {"metal_mine": 5, "solar_plant": 5}
    research = {}
    display = build_production_display(
        building_type="metal_mine",
        buildings=buildings,
        level=6,
        ratio=1.0,
        research_levels=research,
    )
    next_row = {
        "display": display,
        "cost_metal": 100,
        "cost_crystal": 50,
        "time_seconds": 60,
    }
    summary = build_building_technical_summary(
        building_type="metal_mine",
        buildings=buildings,
        research_levels=research,
        ratio=1.0,
        current=5,
        max_level=50,
        current_row=None,
        next_row=next_row,
    )
    assert summary.get("impact")
    impact = summary["impact"]
    assert impact["next"]["from"] == display["current_per_hour"]
    assert impact["next"]["to"] == display["next_per_hour"]
    assert impact["next"]["unit"] == "/h"
    assert impact["next"]["delta"] == display["delta_per_hour"]


def test_storage_summary_has_capacity_impact():
    display = build_storage_display(current=1000, next_val=1500, resource="metal", capacity_at_level=1500, step_delta=500)
    impact = resolve_building_impact(
        building_type="metal_storage",
        buildings={"metal_storage": 3},
        research_levels={},
        current=3,
        display=display,
    )
    assert impact
    assert impact["example"]["kind"] == "capacity"
    assert impact["next"]["from"] == 1000
    assert impact["next"]["to"] == 1500
    assert impact["next"]["delta"] == 500


def test_command_center_impact_is_nanofactory_upgrade_only():
    buildings = {"nanofactory": 2, "command_center": 3, "metal_mine": 10}
    impact = resolve_building_impact(
        building_type="command_center",
        buildings=buildings,
        research_levels={},
        current=3,
        display={"layout": "effect_percent"},
    )
    assert impact
    assert impact["example"]["scope"] == "nanofactory_upgrade_only"
    assert impact["example"]["kind"] == "duration"
    assert any(a["label_key"] == "building_nanofactory" for a in impact["affects"])
    assert not any("metal_mine" in a["label_key"] for a in impact["affects"])


def test_nano_impact_uses_duration_example():
    impact = resolve_building_impact(
        building_type="nanofactory",
        buildings={"nanofactory": 1, "metal_mine": 4},
        research_levels={},
        current=1,
        display={"layout": "nanofactory_build_time", "nano_time_preview": {}},
    )
    assert impact
    assert impact["example"]["kind"] == "duration"
    assert "seconds_current" in impact["example"]


def test_buildtime_tech_research_impact_is_duration(monkeypatch):
    def _seconds(self, building_type, target_level):
        tech = int(self.research.get("buildtime_tech", 0) or 0)
        return max(1, 10_000 - tech * 100)

    monkeypatch.setattr(
        "game.effects.effect_resolver.EffectResolver.get_build_time_seconds",
        _seconds,
    )
    impact = resolve_research_impact(
        tech_key="buildtime_tech",
        current=2,
        buildings={"metal_mine": 5},
        research_levels={"buildtime_tech": 2},
        effect={"effect_kind": "bonus_percent", "effect_current": 3, "effect_next": 5},
    )
    assert impact
    assert impact["example"]["kind"] == "duration"
    assert impact["next"]["to"] < impact["next"]["from"]
    assert impact["example"]["saved_seconds"] > 0


def test_navigation_tech_impact_is_slots():
    impact = resolve_research_impact(
        tech_key="navigation_tech",
        current=1,
        buildings={},
        research_levels={},
        effect={"effect_kind": "level", "effect_current": 1, "effect_next": 2},
    )
    assert impact
    assert impact["example"]["kind"] == "slots"
    assert impact["next"]["to"] >= impact["next"]["from"]


def test_interstellar_impact_is_unlock():
    impact = resolve_research_impact(
        tech_key="interstellar_expansion",
        current=1,
        buildings={},
        research_levels={},
        effect={"effect_kind": "level", "effect_current": 1, "effect_next": 2},
    )
    assert impact
    assert impact["example"]["kind"] == "unlock"
    assert impact["example"]["unlocks"]


def test_research_summary_attaches_impact():
    summary = build_research_technical_summary(
        tech_key="navigation_tech",
        current=0,
        next_row={"time_seconds": 100, "cost_metal": 10, "cost_crystal": 10, "display": {}},
        buildings={},
        research_levels={},
    )
    assert summary.get("impact")
    assert summary["impact"]["example"]["kind"] == "slots"


def test_main_js_renders_impact_summary():
    src = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "function renderTechnicalImpactSummary" in src
    assert "summary.impact" in src
    assert "gc-tech-impact" in src
    assert "NANOFACTORY_SPEED_COEFF" not in src
    # No duplicate modal description inside impact block.
    impact_fn = src.split("function renderTechnicalImpactSummary")[1].split(
        "function renderTechnicalSummaryDetail"
    )[0]
    assert "gc-tech-impact-blurb" not in impact_fn
    assert 'rawCurLabelKey !== "techcard_current"' in impact_fn


def test_duration_helper_saved_seconds():
    impact = impact_from_duration_seconds(
        blurb_key="desc_nanofactory",
        current_seconds=480,
        next_seconds=464,
        affects=[{"label_key": "building_metal_mine"}],
    )
    assert impact["example"]["saved_seconds"] == 16
    assert impact["next"]["delta"] == -16


def test_rate_helper():
    impact = impact_from_rate(
        blurb_key="desc_metal_mine",
        current_rate=1000,
        next_rate=1100,
        unit="/h",
    )
    assert impact["next"]["delta"] == 100
    assert impact["next"]["delta_pct"] == 10.0
