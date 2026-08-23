"""GC-PERF-TK-005 — Timekeeper apply must not reload the same queue before shifting it."""

from __future__ import annotations

from unittest.mock import patch

from game import timekeeper


def test_apply_domain_shift_reuses_preloaded_queue_rows():
    rows = [
        {
            "id": 7,
            "start_time": 100.0,
            "finish_time": 200.0,
        }
    ]
    effect = {"kind": "time_boost", "target": "build", "seconds_shifted": 30}

    with patch("game.timekeeper._load_domain_rows") as load_rows, patch(
        "game.inventory_use.apply_active_head_queue_time_boost",
        return_value=effect,
    ) as apply_boost:
        result = timekeeper._apply_domain_shift(
            "build",
            1,
            2,
            30,
            conn=object(),
            now=150.0,
            rows=rows,
            finish_col_override="finish_time",
        )

    assert result == effect
    load_rows.assert_not_called()
    apply_boost.assert_called_once()
    kwargs = apply_boost.call_args.kwargs
    assert kwargs["rows"] is rows
    assert kwargs["finish_col"] == "finish_time"


def test_apply_timekeeper_loads_queue_only_before_and_after_shift():
    rows_before = [{"id": 11, "start_time": 100.0, "finish_time": 200.0}]
    rows_after = [{"id": 11, "start_time": 70.0, "finish_time": 170.0}]

    with patch("game.timekeeper.schema_ready", return_value=True), patch(
        "game.timekeeper.get_balance", return_value=120
    ), patch("game.timekeeper._finish_before_apply"), patch(
        "game.timekeeper._load_domain_rows",
        side_effect=[(rows_before, "finish_time"), (rows_after, "finish_time")],
    ) as load_rows, patch(
        "game.timekeeper._apply_domain_shift",
        return_value={"seconds_shifted": 30},
    ) as apply_shift, patch(
        "game.timekeeper.debit", return_value=90
    ), patch(
        "game.timekeeper.serialize_for_client",
        return_value={"ready": True, "balance_sec": 90, "label": "1min"},
    ):
        ok, reason, payload = timekeeper.apply_timekeeper(
            1,
            "build",
            planet_id=2,
            seconds=30,
            mode="partial",
            conn=object(),
        )

    assert ok is True
    assert reason == "ok"
    assert payload["seconds_applied"] == 30
    assert load_rows.call_count == 2
    apply_shift.assert_called_once()
    kwargs = apply_shift.call_args.kwargs
    assert kwargs["rows"] is rows_before
    assert kwargs["finish_col_override"] == "finish_time"
