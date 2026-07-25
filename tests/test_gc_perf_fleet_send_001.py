"""
GC-PERF-FLEET-SEND — Instant fleet dispatch contracts.

Run: python -m pytest tests/test_gc_perf_fleet_send_001.py -v
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from game.db import db
from game.fleet import get_planet_ships
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
from tests.test_fleet import (
    _fund_planet,
    _planet_coords,
    _policy_safe_username,
    _second_colony,
    _seed_ships,
)

pytest_plugins = ("tests.test_fleet",)

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_fleet_send_success_path_no_await_refresh_fleet_state():
    """Live payload + slim state patch UI; deferred coalesce only (not critical-path await)."""
    src = _read("static/main.js")
    send_ok = src.split('const sendForm = e.target.closest ? e.target.closest("#fleet-send-form")')[1][:5000]
    assert 'applyActionState(res, "fleet_send_success")' in send_ok
    assert "mergeFleetMovementIntoHud(payload.fleet" in send_ok
    assert "await refreshFleetState(page)" not in send_ok
    sync = src.split("function syncFleetUiAfterMutation(reason)")[1].split("function resetQueueRenderSignaturesForImmediatePatch")[0]
    assert 'r === "fleet_send_success"' in sync
    assert "immediate: false" in sync


def test_app_fleet_send_uses_slim_mutation_state():
    src = _read("app.py")
    assert "def _fleet_mutation_game_state(finish_source: str)" in src
    assert '"api_fleet_send"' in src
    assert '"api_fleet_recall"' in src
    send_fn = src.split("def api_fleet_send():")[1].split("def api_fleet_recall():")[0]
    assert "_fleet_mutation_game_state(" in send_fn
    assert "include_panel=True" not in send_fn
    recall_fn = src.split("def api_fleet_recall():")[1].split("def api_fleet_presets_list():")[0]
    assert "_fleet_mutation_game_state(" in recall_fn
    assert "include_panel=True" not in recall_fn
    skip = src.split("_FLEET_TICK_SKIP_ENDPOINTS = frozenset(")[1].split(")")[0]
    assert '"api_fleet_send"' in skip
    assert '"api_fleet_recall"' in skip
    diet = src.split("def _uses_action_state_diet(finish_source: str)")[1].split("def _is_buildings_queue_action_source")[0]
    assert '"api_fleet_send"' in diet
    assert '"api_fleet_recall"' in diet
    poll = src.split("def _use_poll_live_path(finish_source: str)")[1].split("def login():")[0]
    assert "_FLEET_MUTATION_LIVE_SOURCES" in poll


def test_api_fleet_send_returns_slim_state_without_buildings_panel(fleet_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uname = _policy_safe_username("pfleet")
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Admiral", conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony2 = _second_colony(uid, conn=conn)
    g, s, p = _planet_coords(colony2, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"mule_courier": 5}, conn=conn)
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    resp = client.post(
        "/api/fleet/send",
        json={
            "origin_planet_id": pid,
            "target_galaxy": g,
            "target_system": s,
            "target_position": p,
            "mission_type": "transport",
            "ships": {"mule_courier": 2},
            "resources": {"metal": 500, "crystal": 0},
            "speed_percent": 100,
        },
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True
    live = body.get("data") or {}
    assert live.get("fleet")
    assert live["fleet"].get("status") == "outbound"
    assert live.get("updated_ships") is not None
    assert live.get("active_slots") is not None

    state = body.get("state") or {}
    assert state.get("ok") is True
    assert "buildings_panel" not in state
    for heavy in (
        "exchange",
        "scrapyard",
        "shipyard",
        "defense",
        "global_queue_hud",
        "planet_teaser",
        "auction_house",
    ):
        assert heavy not in state
    assert state.get("resources") or state.get("player")

    action_bytes = len(json.dumps(state, separators=(",", ":")))
    assert action_bytes < 80_000

    verify = db()
    try:
        assert get_planet_ships(pid, conn=verify).get("mule_courier") == 3
        row = verify.execute(
            "SELECT status FROM fleet_movements WHERE player_id = ? ORDER BY id DESC LIMIT 1;",
            (uid,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "outbound"
    finally:
        verify.close()
