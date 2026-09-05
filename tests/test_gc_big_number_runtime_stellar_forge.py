"""Unbounded runtime arithmetic contracts for Stellar Forge operational progress."""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, localcontext
from pathlib import Path

import pytest

from game.shipyard import orbital_production_batch_capacity
from game.stellar_forge import formulas
from game.stellar_forge import service

ROOT = Path(__file__).resolve().parents[1]
HUGE = 10**400


def test_operational_targets_preserve_legacy_values_and_scale_past_float_range():
    for protocol, base in formulas.OPERATIONAL_TARGETS_BASE.items():
        for rank in (1, 2, 3, 10, 25):
            legacy = int(round(base * (1.0 + 0.5 * (rank - 1))))
            assert formulas.operational_target(protocol, rank) == legacy

        huge_target = formulas.operational_target(protocol, HUGE)
        numerator = int(base) * (HUGE + 1)
        quotient, remainder = divmod(numerator, 2)
        if remainder and quotient % 2:
            quotient += 1
        assert huge_target == quotient


def test_record_operational_progress_accumulates_10_pow_400_exactly(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    monkeypatch.setattr(service, "schema_ready", lambda _conn: True)
    monkeypatch.setattr(
        service,
        "get_raw_state",
        lambda _planet_id, conn=None: {
            "campaign_active": True,
            "operational_progress": {"titan": HUGE},
        },
    )

    def fake_upsert(_conn, _planet_id, **fields):
        captured.update(fields)

    monkeypatch.setattr(service, "_upsert_state", fake_upsert)

    service.record_operational_progress(
        7,
        "titan",
        HUGE * 2,
        conn=object(),
        now=123.0,
    )

    progress = captured["operational_progress"]["titan"]
    assert isinstance(progress, int)
    assert progress == HUGE * 3


def test_operational_progress_normalizer_accepts_legacy_integral_float():
    assert service._operational_progress_int(123.0) == 123
    assert service._operational_progress_int("456") == 456
    assert service._operational_progress_int(float("inf")) == 0


def test_stellar_forge_operational_sources_have_no_unbounded_float_roundtrip():
    service_src = (ROOT / "game" / "stellar_forge" / "service.py").read_text(encoding="utf-8")
    formulas_src = (ROOT / "game" / "stellar_forge" / "formulas.py").read_text(encoding="utf-8")

    for forbidden in (
        "amt = float(amount or 0)",
        "float(progress.get(protocol, 0) or 0) + amt",
        'float(state["operational_progress"].get(p, 0) or 0)',
        "float(op_progress.get(p, 0) or 0)",
    ):
        assert forbidden not in service_src

    assert "amt = _operational_progress_int(amount)" in service_src
    assert "_operational_progress_int(progress.get(protocol, 0)) + amt" in service_src
    assert "numerator = base * (n + 1)" in formulas_src
    assert "base * (1.0 + 0.5 * (n - 1))" not in formulas_src



def test_tribute_cost_preserves_normal_values_and_scales_10_pow_400_exactly():
    normal = formulas.tribute_cost_for_rank(
        1,
        {"metal": 1000, "crystal": 500, "fuel_cells": 100},
    )
    assert normal == {
        "metal": int(round(1000 * 24 * 0.55)),
        "crystal": int(round(500 * 24 * 0.30)),
        "fuel_cells": int(round(100 * 24 * 0.15)),
    }

    rank = HUGE
    production = {
        "metal": HUGE * 7 + 1,
        "crystal": HUGE * 5 + 3,
        "fuel_cells": HUGE * 2 + 9,
    }
    cost = formulas.tribute_cost_for_rank(rank, production)
    hours = formulas.tribute_hours(rank)

    for resource, (weight_num, weight_den) in formulas.TRIBUTE_WEIGHT_RATIOS.items():
        product = production[resource] * hours * weight_num
        quotient, remainder = divmod(product, weight_den)
        doubled = remainder * 2
        if doubled > weight_den or (doubled == weight_den and quotient % 2):
            quotient += 1
        assert cost[resource] == quotient


def test_forge_capacity_scaling_preserves_normal_ranks_and_handles_10_pow_400():
    level = 50
    base = 1 + level * 5 + level**2.3

    for rank in (0, 1, 10, 25):
        legacy = max(1, int(base * (1.0 + rank * 1.5)))
        assert orbital_production_batch_capacity(level, forge_rank=rank) == legacy

    with localcontext() as ctx:
        ctx.prec = len(str(HUGE)) + 96
        expected = int(
            (
                Decimal(str(base))
                * Decimal(2 + 3 * HUGE)
                / Decimal(2)
            ).to_integral_value(rounding=ROUND_FLOOR)
        )

    assert orbital_production_batch_capacity(level, forge_rank=HUGE) == expected
    assert formulas.forge_capacity_multiplier(HUGE) == str(1 + (3 * HUGE) // 2)
    assert formulas.forge_capacity_multiplier(HUGE + 1).endswith(".5")


def test_manufacturing_role_presence_accepts_huge_integer_mass():
    required = ["combat", "cargo", "scout"]
    by_role = {
        "combat": HUGE,
        "cargo": HUGE * 2,
        "scout": HUGE * 3,
    }
    target = formulas.hull_mass_target(1)
    assert formulas.manufacturing_trial_complete(
        max(target, sum(by_role.values())),
        1,
        by_role,
        required,
    )


def test_stellar_forge_tribute_and_capacity_sources_have_no_unbounded_float_roundtrip():
    service_src = (ROOT / "game" / "stellar_forge" / "service.py").read_text(encoding="utf-8")
    formulas_src = (ROOT / "game" / "stellar_forge" / "formulas.py").read_text(encoding="utf-8")
    shipyard_src = (ROOT / "game" / "shipyard.py").read_text(encoding="utf-8")

    for forbidden in (
        'float(production_per_hour.get("metal_mine", 0) or 0)',
        'float(production_per_hour.get("crystal_mine", 0) or 0)',
        'float(production_per_hour.get("fuel_cell_plant", 0) or 0)',
        'float(prod.get("metal_mine", 0) or 0)',
        'float(prod.get("crystal_mine", 0) or 0)',
        'float(prod.get("fuel_cell_plant", 0) or 0)',
    ):
        assert forbidden not in service_src

    assert "rate = max(0, int(production_per_hour.get(resource, 0) or 0))" in formulas_src
    assert "float(production_per_hour.get(resource, 0) or 0)" not in formulas_src
    assert "all(int(by_role.get(r, 0) or 0) > 0 for r in roles)" in formulas_src

    assert "forge_capacity_scaled_floor(base, forge_rank)" in shipyard_src
    assert "base * forge_capacity_multiplier(forge_rank)" not in shipyard_src
