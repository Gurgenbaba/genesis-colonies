"""Canonical duration formatting contracts."""

from __future__ import annotations

from game.time_format import format_duration_human
from game.timekeeper import format_balance_label


def test_format_duration_human_adaptive_units():
    assert format_duration_human(0) == "0s"
    assert format_duration_human(45) == "45s"
    assert format_duration_human(125) == "2min 5s"
    assert format_duration_human(7380) == "2h 3min"
    assert format_duration_human(90061) == "1d 1h 1min"
    # 7–29d uses weeks (never months)
    assert format_duration_human(10 * 86400) == "1w 3d"
    assert format_duration_human(29 * 86400) == "4w 1d"
    # Season-scale (~60d): plain days — no mo+w nonsense
    assert format_duration_human(5_182_530) == "59d 23h 35min"
    assert format_duration_human(5_182_530, max_parts=2) == "59d 23h"
    assert "mo" not in format_duration_human(5_182_530)
    assert "w" not in format_duration_human(5_182_530)
    # ≥90d: months + days (no weeks)
    assert format_duration_human(100 * 86400) == "3mo 10d"
    assert "w" not in format_duration_human(100 * 86400)
    assert format_duration_human(400 * 86400) == "1y 1mo 5d"


def test_timekeeper_label_uses_canonical_formatter():
    assert format_balance_label(0) == "0min"
    assert format_balance_label(45) == "45s"
    assert format_balance_label(7 * 3600 + 35 * 60) == "7h 35min"
