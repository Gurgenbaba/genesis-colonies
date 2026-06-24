"""
GC-856 — SSR instrumentation on overview/shipyard/defense routes.

Run: python -m pytest tests/test_gc856_ssr_route_instrumentation.py -v
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_ssr_perf_trace():
    from game.live_state import finish_ssr_perf

    finish_ssr_perf()
    yield
    finish_ssr_perf()


@pytest.mark.parametrize(
    "path,route_token",
    [
        ("/overview", "route=/overview"),
        ("/shipyard", "route=/shipyard"),
        ("/defense", "route=/defense"),
    ],
)
def test_gc856_route_with_debug_emits_ssr_log(game_client, monkeypatch, caplog, path, route_token):
    monkeypatch.setenv("GC_SSR_PERF_DEBUG", "1")
    caplog.set_level(logging.INFO)
    client, _pid = game_client

    resp = client.get(path)
    assert resp.status_code == 200
    hits = [rec for rec in caplog.records if "[GC SSR PERF]" in rec.message]
    assert len(hits) == 1
    msg = hits[0].message
    assert route_token in msg
    for key in ("total=", "live_context=", "template=", "bytes="):
        assert key in msg


def test_gc856_app_routes_call_start_ssr_perf():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    for route in ("/overview", "/shipyard", "/defense"):
        assert f'start_ssr_perf("{route}")' in src
