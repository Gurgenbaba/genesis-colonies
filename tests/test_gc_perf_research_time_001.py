"""GC-PERF-RESEARCH-TIME-001: shared levels/conn/resolver for research catalog times."""

from __future__ import annotations

import time
from unittest.mock import patch

from game.db import db
from game.models import get_homeworld, get_planet_buildings, get_research_levels
from game.research import (
    RESEARCH_TECHS,
    get_research_status,
    get_research_time,
)

pytest_plugins = ["tests.test_game_state_live"]


def _tech_time_snapshot(status: dict) -> dict:
    return {
        t["key"]: {
            "time_seconds": t.get("time_seconds"),
            "cost_metal": t.get("cost_metal"),
            "cost_crystal": t.get("cost_crystal"),
            "target_level": t.get("target_level"),
            "max_queueable": t.get("max_queueable"),
        }
        for t in (status.get("techs") or [])
    }


def test_get_research_time_prefers_shared_resolver(game_client):
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)
        from game.effects import get_effect_resolver

        resolver = get_effect_resolver(
            int(uid), buildings=buildings, research=levels, conn=conn
        )
        expected = int(resolver.get_research_time_seconds("energy_tech", 1))

        def _guard_levels(*_a, **_k):
            raise AssertionError("get_research_levels must not run when resolver= is set")

        with patch("game.research.get_research_levels", side_effect=_guard_levels):
            got = get_research_time(
                "energy_tech",
                1,
                int(uid),
                buildings=buildings,
                levels=levels,
                conn=conn,
                resolver=resolver,
            )
        assert got == expected
    finally:
        conn.close()


def test_research_status_catalog_does_not_refetch_levels_per_tech(game_client):
    """Full catalog must not call get_research_levels once per tech."""
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)
        tech_count = len(RESEARCH_TECHS)
        assert tech_count >= 8

        calls = {"n": 0}
        real = get_research_levels

        def _counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        with patch("game.research.get_research_levels", side_effect=_counting):
            status = get_research_status(
                int(uid),
                buildings=buildings,
                skip_finish=True,
                include_techs=True,
                conn=conn,
                levels=levels,
            )
        assert len(status.get("techs") or []) == tech_count
        # Shared levels= → no catalog refetch; allow tiny finish/retry noise only if any.
        assert calls["n"] == 0, f"unexpected get_research_levels calls: {calls['n']}"
    finally:
        conn.close()


def test_research_status_payload_identical_with_shared_conn(game_client):
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)

        a = get_research_status(
            int(uid),
            buildings=buildings,
            skip_finish=True,
            include_techs=True,
            levels=levels,
        )
        b = get_research_status(
            int(uid),
            buildings=buildings,
            skip_finish=True,
            include_techs=True,
            conn=conn,
            levels=levels,
        )
        assert _tech_time_snapshot(a) == _tech_time_snapshot(b)
    finally:
        conn.close()


def test_api_game_state_research_hud_passes_levels_conn_contract():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    assert "get_research_status(" in src
    # HUD path must keep shared levels + request conn (GC-PERF-HUD-READS / RESEARCH-TIME).
    block = src.split('_live_perf_span("hud.research")', 1)[1].split(
        "_live_perf_span(", 1
    )[0]
    assert "levels=" in block
    assert "conn=conn" in block


def test_research_panel_local_perf_smoke(game_client):
    """Soft local smoke: research include_panel should stay well under prod CRITICAL."""
    client, _uid = game_client
    t0 = time.perf_counter()
    r = client.get("/api/game-state?include_panel=1&panel_page=research")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("ok") is True
    research = body.get("research") or {}
    assert len(research.get("techs") or []) >= 1
    assert elapsed_ms < 2500.0, f"research panel game-state too slow: {elapsed_ms:.1f}ms"
