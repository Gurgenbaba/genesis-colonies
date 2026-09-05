"""Unbounded runtime arithmetic contracts for Stellar Forge operational progress."""

from __future__ import annotations

from pathlib import Path

import pytest

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
