"""GC-821F — long-term mine ROI anchors and bulk-upgrade prep."""

from __future__ import annotations

import pytest

from game.economy_balance import (
    MINE_BULK_UPGRADE_INCREMENTS,
    MINE_UPGRADE_ROI_TARGET_HOURS,
    ROI_BENCHMARK_LEVELS,
    cumulative_upgrade_cost_range,
    max_affordable_mine_upgrade_level,
    mine_bulk_upgrade_preview,
    mine_roi_anchor_hours,
    mine_roi_cost_multiplier,
    mine_upgrade_roi_hours,
    power_upgrade_cost,
)


class TestGc821fRoiAnchors:
    @pytest.mark.parametrize("level", ROI_BENCHMARK_LEVELS)
    def test_metal_mine_roi_at_anchors(self, level):
        roi = mine_upgrade_roi_hours("metal_mine", level)
        target = MINE_UPGRADE_ROI_TARGET_HOURS[level]
        assert target * 0.65 <= roi <= target * 1.35

    def test_anchor_interpolation_midpoint(self):
        assert 50 <= mine_roi_anchor_hours(20) <= 50
        mid = mine_roi_anchor_hours(30)
        assert 50 < mid < 100

    def test_roi_multiplier_increases_with_level(self):
        """Endgame anchors need stronger cost scaling than early game (821F curve)."""
        levels = ROI_BENCHMARK_LEVELS
        for low, high in zip(levels, levels[1:]):
            assert mine_roi_cost_multiplier(low) < mine_roi_cost_multiplier(high), (
                f"cost multiplier must rise L{low}→L{high} to hit longer ROI anchors"
            )


class TestGc821fBulkUpgradePrep:
    def test_increments_defined(self):
        assert MINE_BULK_UPGRADE_INCREMENTS == (1, 5, 10)

    def test_cumulative_cost_range(self):
        m, c = cumulative_upgrade_cost_range("metal_mine", 10, 12)
        m1, _ = power_upgrade_cost("metal_mine", 11)
        m2, _ = power_upgrade_cost("metal_mine", 12)
        assert m == m1 + m2

    def test_bulk_preview_options(self):
        preview = mine_bulk_upgrade_preview(
            "metal_mine",
            10,
            120,
            metal_available=10**12,
            crystal_available=10**12,
        )
        assert preview["from_level"] == 10
        assert preview["affordable_max_level"] >= 11
        steps = {o["step"] for o in preview["options"]}
        assert 1 in steps
        assert 5 in steps
        assert 10 in steps
        assert "max" in steps

    def test_max_affordable_respects_resources(self):
        m11, c11 = power_upgrade_cost("metal_mine", 11)
        lvl = max_affordable_mine_upgrade_level(
            "metal_mine",
            10,
            50,
            metal_available=m11,
            crystal_available=c11,
        )
        assert lvl == 11
        lvl2 = max_affordable_mine_upgrade_level(
            "metal_mine",
            10,
            50,
            metal_available=m11 - 1,
            crystal_available=c11,
        )
        assert lvl2 == 10
