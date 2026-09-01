"""GC-PG-HIGHSPEED-001B — diet game-state poll zero resource-persist writes."""

from __future__ import annotations

import re
import time
from pathlib import Path

from game.db import db
from game.logic import read_player_live_state_for_poll
from game.planet_evolution.repository import get_context_planet

pytest_plugins = ["tests.test_game_state_live"]

ROOT = Path(__file__).resolve().parents[1]
ROOT_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


def _trace_writes(conn) -> list[str]:
    writes: list[str] = []

    def trace(stmt: str) -> None:
        if ROOT_WRITE.match(stmt):
            writes.append(stmt.strip())

    conn.set_trace_callback(trace)
    return writes


def test_001b_poll_path_disables_periodic_resource_persist():
    source = (ROOT / "game" / "logic.py").read_text(encoding="utf-8")
    block = source.split("def read_player_live_state_for_poll(")[1].split(
        "\ndef refresh_player_live_state(", 1
    )[0]
    assert "GC-PG-HIGHSPEED-001B" in block
    assert "get_resource_persist_interval_sec()" not in block
    assert "is_game_worker_primary()" not in block


def test_idle_diet_poll_no_planet_persist_after_throttle_window(game_client, monkeypatch):
    """001B: stale last_update alone must not trigger UPDATE planets on diet poll."""
    _client, uid = game_client
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")

    conn = db()
    try:
        planet = get_context_planet(int(uid), conn=conn)
        assert planet is not None
        conn.execute(
            "UPDATE planets SET last_update = ? WHERE id = ?",
            (time.time() - 601.0, int(planet["id"])),
        )
        conn.commit()

        writes = _trace_writes(conn)
        try:
            player_view, *_rest = read_player_live_state_for_poll(int(uid), conn=conn)
        finally:
            conn.set_trace_callback(None)

        assert int(player_view["id"]) == int(uid)
        planet_updates = [
            s for s in writes if re.match(r"^\s*UPDATE\s+planets\b", s, re.IGNORECASE)
        ]
        assert planet_updates == [], f"idle diet poll persisted planets: {planet_updates}"
    finally:
        conn.close()
