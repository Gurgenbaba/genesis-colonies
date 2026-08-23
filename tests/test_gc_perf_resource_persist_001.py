"""GC-PERF-RESOURCE-PERSIST-001 — diet resource projection stays write-free inside throttle window."""

from __future__ import annotations

import re
import time

from game.db import db
from game.logic import read_player_live_state_for_poll
from game.planet_evolution.repository import get_context_planet

pytest_plugins = ["tests.test_game_state_live"]

ROOT_WRITE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)


def _trace_writes(conn) -> list[str]:
    writes: list[str] = []

    def trace(stmt: str) -> None:
        if ROOT_WRITE.match(stmt):
            writes.append(stmt.strip())

    conn.set_trace_callback(trace)
    return writes


def test_diet_resource_projection_does_not_persist_inside_throttle_window(
    game_client, monkeypatch
):
    _client, uid = game_client
    monkeypatch.setenv("GC_RESOURCE_PERSIST_SEC", "600")
    monkeypatch.setenv("GC_GAME_WORKER_PRIMARY", "1")

    conn = db()
    try:
        planet = get_context_planet(int(uid), conn=conn)
        assert planet is not None
        now = time.time()
        conn.execute(
            "UPDATE planets SET last_update = ? WHERE id = ?",
            (now, int(planet["id"])),
        )
        conn.commit()

        writes = _trace_writes(conn)
        try:
            player_view, _buildings, _ratio, _energy_total, _energy_used, _caps = (
                read_player_live_state_for_poll(int(uid), conn=conn)
            )
        finally:
            conn.set_trace_callback(None)

        assert int(player_view["id"]) == int(uid)
        assert writes == [], f"diet resource projection wrote inside throttle window: {writes}"
    finally:
        conn.close()


def test_diet_resource_poll_persists_after_throttle_window(game_client, monkeypatch):
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
            read_player_live_state_for_poll(int(uid), conn=conn)
        finally:
            conn.set_trace_callback(None)

        assert any(
            re.match(r"^\s*UPDATE\s+planets\b", stmt, re.IGNORECASE) for stmt in writes
        ), f"resource persist did not update planet after throttle window: {writes}"
    finally:
        conn.close()
