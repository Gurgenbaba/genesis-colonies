"""GC-ENDGAME-ECO-HOTFIX-001 — safe rollout tests for the high-level mine tail."""

from __future__ import annotations

from decimal import Decimal

import pytest

import game.production_formula as pf


@pytest.fixture(autouse=True)
def _restore_rollout_state(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_PIVOT_LEVEL", 650)
    monkeypatch.setattr(pf, "ENDGAME_PRODUCTION_TAIL_POWER", 2)
    monkeypatch.setattr(pf, "ENDGAME_SHADOW_MIN_LEVEL", 600)
    pf._ENDGAME_SHADOW_SEEN.clear()
    yield
    pf._ENDGAME_SHADOW_SEEN.clear()


def _legacy_float(resource: str, level: int) -> float:
    base = float(pf.LEVEL_GROWTH[resource]["multiplier"])
    return base * level * (pf.LEVEL_GROWTH_RATE**level)


def test_legacy_mode_preserves_existing_high_level_curve_byte_for_byte():
    for level in (120, 200, 600, 650, 675):
        assert pf.mine_output("metal", level) == _legacy_float("metal", level)
        assert pf.mine_output("crystal", level) == _legacy_float("crystal", level)


def test_shadow_mode_is_gameplay_identical_to_legacy(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "shadow")
    for level in (600, 650, 675, 800):
        assert pf.mine_output("metal", level) == _legacy_float("metal", level)
        exact = pf.mine_output_decimal("metal", level)
        assert exact == pf.legacy_mine_output_decimal("metal", level)


def test_candidate_tail_is_exactly_continuous_at_pivot():
    pivot = pf.ENDGAME_PRODUCTION_PIVOT_LEVEL
    assert pf.endgame_tail_mine_output_decimal("metal", pivot) == pf.legacy_mine_output_decimal(
        "metal", pivot
    )
    assert pf.endgame_tail_mine_output_decimal("crystal", pivot) == pf.legacy_mine_output_decimal(
        "crystal", pivot
    )


def test_candidate_tail_is_monotone_but_tames_exponential_growth():
    at_650 = pf.endgame_tail_mine_output_decimal("metal", 650)
    at_675 = pf.endgame_tail_mine_output_decimal("metal", 675)
    at_1000 = pf.endgame_tail_mine_output_decimal("metal", 1000)

    assert at_675 > at_650
    assert at_1000 > at_675
    assert at_675 < pf.legacy_mine_output_decimal("metal", 675)
    assert at_1000 < pf.legacy_mine_output_decimal("metal", 1000)

    # The current 25-level jump around L650 is >6x.  The tested q=2 tail is
    # deliberately still meaningful progress, but below a 4x jump.
    assert Decimal("1") < at_675 / at_650 < Decimal("4")


def test_active_mode_switches_only_levels_above_pivot(monkeypatch):
    pivot = pf.ENDGAME_PRODUCTION_PIVOT_LEVEL
    legacy_pivot = pf.mine_output_decimal("metal", pivot)
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")

    assert pf.mine_output_decimal("metal", pivot) == legacy_pivot
    assert pf.mine_output_decimal("metal", pivot + 1) == pf.endgame_tail_mine_output_decimal(
        "metal", pivot + 1
    )
    assert pf.mine_output_decimal("metal", pivot + 1) < pf.legacy_mine_output_decimal(
        "metal", pivot + 1
    )


def test_active_tail_stays_finite_at_very_high_levels(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    value = pf.mine_output_decimal("metal", 50_000)
    assert value.is_finite()
    assert value > pf.mine_output_decimal("metal", 10_000)


def test_shadow_logs_full_modifier_breakdown_once(caplog, monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "shadow")
    monkeypatch.setattr(pf, "ENDGAME_SHADOW_MIN_LEVEL", 600)
    caplog.set_level("INFO", logger=pf.__name__)

    ctx = pf.ProductionContext(
        resource_type="metal",
        level=650,
        slot=4,
        energy_ratio=0.9,
        production_speed=1.0,
        research={"mining_tech": 40, "drone_tech": 30},
        player=123,
        planet=456,
        building_modifier=1.2,
        directive_modifier=1.5,
        event_modifier=2.0,
    )

    first = pf.calculate_resource_output_decimal("metal", ctx)
    second = pf.calculate_resource_output_decimal("metal", ctx)
    assert first == second

    rows = [r.getMessage() for r in caplog.records if "endgame_economy_shadow" in r.getMessage()]
    assert len(rows) == 1
    row = rows[0]
    assert "player=123" in row
    assert "planet=456" in row
    assert "level=650" in row
    assert "mining=40" in row
    assert "drone=30" in row
    assert "event=2" in row


def test_invalid_rollout_mode_fails_closed_to_legacy(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "definitely-not-valid")
    assert pf.endgame_economy_mode() == "legacy"
    assert pf.mine_output("metal", 675) == _legacy_float("metal", 675)
