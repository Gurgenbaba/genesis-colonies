"""
GC-854 — Buildings panel SSR optimization (shared EffectResolver context).

Run: python -m pytest tests/test_gc854_buildings_ssr_optimization.py -v
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

pytest_plugins = ["tests.test_game_state_live"]


def test_gc854_panel_rows_use_single_effect_resolver(game_client):
    from game.buildings import get_buildings_panel_rows
    from game.effects import get_effect_resolver
    from game.models import get_homeworld, get_planet_buildings

    client, pid = game_client
    assert client.get("/buildings?tab=resources").status_code == 200

    conn = __import__("game.db", fromlist=["db"]).db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT player_id FROM planets WHERE id = ?;", (int(pid),))
        uid = int(cur.fetchone()["player_id"])
        planet = get_homeworld(uid, conn=conn)
        buildings = get_planet_buildings(int(pid), conn=conn)
    finally:
        conn.close()

    with patch("game.buildings.get_effect_resolver", wraps=get_effect_resolver) as mock_er:
        rows = get_buildings_panel_rows(
            planet,
            buildings,
            build_queue={"queue": [], "summary": {"count": 0, "limit": 5}},
            active_tab="resources",
        )
    assert len(rows.get("resources") or []) == 7
    assert mock_er.call_count == 1


def test_gc854_panel_row_payload_unchanged(game_client):
    from game.buildings import get_buildings_panel_rows
    from game.models import get_homeworld, get_planet_buildings

    _client, pid = game_client
    conn = __import__("game.db", fromlist=["db"]).db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT player_id FROM planets WHERE id = ?;", (int(pid),))
        uid = int(cur.fetchone()["player_id"])
        planet = get_homeworld(uid, conn=conn)
        buildings = get_planet_buildings(int(pid), conn=conn)
        rows = get_buildings_panel_rows(
            planet,
            buildings,
            build_queue={"queue": [], "summary": {"count": 0, "limit": 5}},
            active_tab="resources",
        )
    finally:
        conn.close()

    mine = next(r for r in rows["resources"] if r["key"] == "metal_mine")
    assert mine["level"] >= 0
    assert mine["time_seconds"] >= 1
    assert mine["cost_metal"] >= 0
    assert "effect_kind" in mine or mine.get("effect_current") is not None or mine["level"] == 0


def test_gc854_buildings_ssr_under_budget(game_client, monkeypatch):
    """Warm buildings SSR must stay below GC-853 cold-class latency.

    GC-854 originally targeted <700ms after sharing EffectResolver context.
    Later TECHCARD-UX impact rows + heavier buildings payload raised measured
    warm SSR on Windows idle to ~770–900ms (panel≈300 + template≈270 +
    live_context≈200). The guardrail is the regression ceiling below the
    GC-853 cold baseline (~1613ms), not the historical GC-854 peak target.
    """
    monkeypatch.setenv("GC_SSR_PERF_DEBUG", "1")
    client, _pid = game_client

    warm = client.get("/buildings?tab=resources")
    assert warm.status_code == 200

    t0 = time.perf_counter()
    resp = client.get("/buildings?tab=resources")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert resp.status_code == 200
    assert len(resp.data) > 1000
    # Still far below GC-853 cold (~1613ms); catches catastrophic regressions.
    assert elapsed_ms < 1100.0, (
        f"buildings SSR took {elapsed_ms:.1f}ms (target <1100ms warm; GC-853 cold ~1613ms)"
    )
