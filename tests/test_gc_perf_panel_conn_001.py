"""GC-PERF-PANEL-CONN-001: buildings panel reuses request conn; no orphan db() opens."""

from __future__ import annotations

import time
from unittest.mock import patch

from game.buildings import get_buildings_panel_rows
from game.db import db
from game.models import get_homeworld, get_planet_buildings, get_research_levels

pytest_plugins = ["tests.test_game_state_live"]


def _stable_row_snapshot(rows_by_tab: dict) -> dict:
    out = {}
    for tab, rows in sorted(rows_by_tab.items()):
        out[tab] = [
            {
                "key": r.get("key"),
                "level": r.get("level"),
                "target_level": r.get("target_level"),
                "cost_metal": r.get("cost_metal"),
                "cost_crystal": r.get("cost_crystal"),
                "time_seconds": r.get("time_seconds"),
                "effect_kind": r.get("effect_kind"),
                "effect_current": r.get("effect_current"),
                "effect_next": r.get("effect_next"),
                "effect_delta": r.get("effect_delta"),
                "requirements_met": r.get("requirements_met"),
                "can_afford": r.get("can_afford"),
                "max_queueable": r.get("max_queueable"),
                "upgrade_roi_hours": r.get("upgrade_roi_hours"),
            }
            for r in rows
        ]
    return out


def test_buildings_panel_rows_reuses_passed_conn(game_client):
    """With conn=, get_buildings_panel_rows must not open a new db()."""
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        assert planet is not None
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)

        def _guard_db(*_a, **_k):
            raise AssertionError("orphan db() open inside get_buildings_panel_rows")

        with patch("game.db.db", side_effect=_guard_db), patch(
            "game.models.db", side_effect=_guard_db
        ), patch("game.buildings.db", side_effect=_guard_db), patch(
            "game.galactic_directives.state.db", side_effect=_guard_db
        ):
            rows = get_buildings_panel_rows(
                planet,
                buildings,
                active_tab="resources",
                conn=conn,
                research_levels=levels,
            )
        assert "resources" in rows
        assert len(rows["resources"]) >= 1
    finally:
        conn.close()


def test_buildings_panel_rows_payload_identical_with_or_without_conn(game_client):
    _client, uid = game_client
    conn = db()
    try:
        planet = get_homeworld(int(uid), conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        levels = get_research_levels(int(uid), conn=conn)

        a = get_buildings_panel_rows(
            planet, buildings, active_tab="resources", research_levels=levels
        )
        b = get_buildings_panel_rows(
            planet,
            buildings,
            active_tab="resources",
            conn=conn,
            research_levels=levels,
        )
        assert _stable_row_snapshot(a) == _stable_row_snapshot(b)
    finally:
        conn.close()


def test_api_game_state_buildings_panel_passes_conn_contract():
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    buildings_block = src.split('perf_span("panel.buildings_rows")', 1)[1].split(
        "if panel_delta_keys", 1
    )[0]
    delta_block = src.split('perf_span("panel.buildings_delta")', 1)[1].split(
        "active_planet_id", 1
    )[0]
    assert "conn=conn" in buildings_block
    assert "conn=conn" in delta_block
    assert "get_buildings_panel_rows(" in buildings_block


def test_db_connection_open_count_increments(monkeypatch):
    from game import live_state

    class _State:
        db_connection_open_count = 0

    state = _State()
    monkeypatch.setattr(live_state, "_request_perf_state", lambda: state)
    live_state.record_request_perf_db_connection_open()
    live_state.record_request_perf_db_connection_open()
    assert state.db_connection_open_count == 2


def test_buildings_panel_local_perf_smoke(game_client):
    """Soft local smoke: panel_page=buildings should stay well under prod CRITICAL."""
    client, _uid = game_client
    t0 = time.perf_counter()
    r = client.get(
        "/api/game-state?include_panel=1&panel_page=buildings&panel_tab=resources"
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert r.status_code == 200
    body = r.get_json() or {}
    assert body.get("ok") is True
    assert "resources" in (body.get("buildings_panel") or {})
    # Soft ceiling for CI/local SSD — not a hard prod budget.
    assert elapsed_ms < 2500.0, f"buildings panel game-state too slow: {elapsed_ms:.1f}ms"
