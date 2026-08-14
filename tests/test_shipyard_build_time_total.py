"""GC-CARGO-FIX-001 sibling — total batch build time on shipyard cards ('Gesamt' row).

Run: python -m pytest tests/test_shipyard_build_time_total.py -q
"""

from __future__ import annotations

import re

import pytest

from app import T, app
from game.shipyard import production_job_duration_seconds


def _render_footer(build_seconds: int, qty: int, batch_capacity) -> str:
    with app.test_request_context("/"):
        app.jinja_env.globals["T"] = T
        tpl = app.jinja_env.from_string(
            '{% from "partials/progression_cards.html" import render_unit_build_time_footer %}'
            "{{ render_unit_build_time_footer(build_seconds, qty=qty, batch_capacity=batch_capacity) }}"
        )
        return tpl.render(build_seconds=build_seconds, qty=qty, batch_capacity=batch_capacity)


def _extract_total_seconds(html: str) -> int | None:
    """Parse the 'Gesamt' row's mm:ss/h:mm:ss value back to seconds, or None if absent."""
    if "data-unit-build-time-total" not in html:
        return None
    chunk = html.split("data-unit-build-time-total")[1]
    m = re.search(r'gc-card-lr-value gc-mono">\s*([\d:]+)\s*<', chunk)
    assert m, f"could not find duration value in: {chunk[:200]}"
    parts = [int(p) for p in m.group(1).split(":")]
    seconds = 0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


class TestShipyardBuildTimeTotal:
    @pytest.mark.parametrize(
        "build_seconds,qty,batch_capacity",
        [
            (30, 1, 5),  # qty<=1 -> no total row regardless of capacity
            (30, 5, 5),  # qty<=capacity -> single batch, total == per-unit (still shown, qty>1)
            (30, 11, 5),  # qty>capacity -> multiple batches
            (120, 1000, 37),  # large/irregular capacity, must still ceil-divide correctly
        ],
    )
    def test_total_matches_production_job_duration_seconds(self, build_seconds, qty, batch_capacity):
        html = _render_footer(build_seconds, qty, batch_capacity)
        expected_total = production_job_duration_seconds(
            unit_seconds=build_seconds, amount=qty, batch_capacity=batch_capacity
        )
        if qty <= 1:
            assert _extract_total_seconds(html) is None
            return
        actual_total = _extract_total_seconds(html)
        assert actual_total == expected_total, (
            f"qty={qty} cap={batch_capacity} sec={build_seconds}: "
            f"template total={actual_total}s, production_job_duration_seconds={expected_total}s"
        )

    def test_qty_le_1_never_renders_total_row(self):
        html = _render_footer(30, 1, 5)
        assert "data-unit-build-time-total" not in html

    def test_no_batch_capacity_never_renders_total_row(self):
        """Locked shipyard cards (no qty input) call the macro with batch_capacity=none."""
        html = _render_footer(30, 5, None)
        assert "data-unit-build-time-total" not in html
        # Per-unit row must still render normally without the stash attributes.
        assert "data-unit-build-time" in html
        assert "data-unit-build-seconds" not in html

    def test_per_unit_row_unaffected(self):
        html = _render_footer(30, 11, 5)
        assert "0:30" in html  # per-unit duration line still present
        assert "Bauzeit" in html

    def test_stash_attributes_present_when_batch_capacity_given(self):
        html = _render_footer(45, 3, 7)
        assert 'data-unit-build-seconds="45"' in html
        assert 'data-unit-batch-capacity="7"' in html

    def test_single_root_wrapper_prevents_stale_row_stacking(self):
        """Regression: both rows MUST share one root element.

        JS live updates replace the row via `timeRow.outerHTML = html` on every
        keystroke. If the macro ever emits two sibling top-level <div>s again
        (the original bug), only the first gets replaced on each update and the
        old 'Gesamt' row from the previous keystroke is orphaned as a sibling —
        rows pile up indefinitely instead of being replaced (see screenshot bug:
        six stacked 'GESAMT' rows for one quantity typed digit by digit).
        """
        html = _render_footer(30, 11, 5).strip()
        assert html.startswith("<div data-unit-build-time")
        assert html.endswith("</div>")

        # Div nesting depth must return to 0 exactly once, at the very end —
        # i.e. a single root element wraps everything else. If a second
        # top-level <div> existed (the original bug), depth would hit 0 again
        # partway through the string, before the final closing tag.
        depth = 0
        zero_crossings_before_end = 0
        tags = re.findall(r"<(/?)div\b", html)
        for i, is_close in enumerate(tags):
            depth += -1 if is_close else 1
            if depth == 0 and i < len(tags) - 1:
                zero_crossings_before_end += 1
        assert depth == 0
        assert zero_crossings_before_end == 0

        # Only one element carries the wrapper marker (not one per row).
        assert re.findall(r"\bdata-unit-build-time(?!-total)\b", html) == ["data-unit-build-time"]
        assert html.count("data-unit-build-time-total") == 1
