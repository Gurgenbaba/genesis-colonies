"""GC-BST — Buildings colony stage layout (display-only)."""

from __future__ import annotations

from game.buildings import BUILDING_ORDER, BUILDING_STAGE_LAYOUT, _make_panel_row


def test_building_stage_layout_covers_all_buildings():
    missing = [k for k in BUILDING_ORDER if k not in BUILDING_STAGE_LAYOUT]
    assert missing == [], f"missing stage slots: {missing}"


def test_building_stage_layout_pct_in_range():
    for key, slot in BUILDING_STAGE_LAYOUT.items():
        assert 0.0 <= float(slot["left_pct"]) <= 100.0, key
        assert 0.0 <= float(slot["top_pct"]) <= 100.0, key
        assert float(slot["scale"]) > 0, key


def test_panel_row_includes_stage_fields():
    planet = {"player_id": 1, "metal": 1e12, "crystal": 1e12}
    buildings = {k: 1 for k in BUILDING_ORDER}
    research = {}
    row = _make_panel_row(planet, buildings, research, "metal_mine")
    assert row["key"] == "metal_mine"
    assert "stage_left_pct" in row
    assert "stage_top_pct" in row
    assert row["stage_left_pct"] == BUILDING_STAGE_LAYOUT["metal_mine"]["left_pct"]
