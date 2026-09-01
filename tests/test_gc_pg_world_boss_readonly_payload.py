"""Regression gates for the PostgreSQL World Boss GET/read payload hot path."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from game import world_boss as wb

ROOT = Path(__file__).resolve().parents[1]


class _Rows:
    def fetchall(self):
        return []


class _Conn:
    def execute(self, sql, params=None):  # noqa: ANN001
        del sql, params
        return _Rows()


def test_default_world_boss_payload_never_flushes_auto_attack(monkeypatch):
    """Opening/refreshing World Boss must not become a gameplay mutation."""
    assert inspect.signature(wb.build_world_boss_payload).parameters["flush_auto"].default is False

    monkeypatch.setattr(wb, "world_boss_schema_ready", lambda conn: True)
    monkeypatch.setattr(wb, "build_schedule_info", lambda **kwargs: {"spawn_ready": False})
    monkeypatch.setattr(wb, "list_active_events", lambda **kwargs: [])
    monkeypatch.setattr(wb, "list_definitions", lambda **kwargs: [])

    import game.world_boss_companions as companions

    monkeypatch.setattr(
        companions,
        "build_overview_companions",
        lambda player_id, *, conn, now: {"ready": True, "slots": [], "owned_count": 0},
    )

    def _forbidden_flush(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("read payload attempted World Boss auto-attack mutation")

    monkeypatch.setattr(wb, "flush_ready_auto_attacks_for_player", _forbidden_flush)

    payload = wb.build_world_boss_payload(7, conn=_Conn(), now=12345.0)
    assert payload["ok"] is True
    assert payload["flushed_attacks"] == []


def test_explicit_auto_flush_remains_opt_in(monkeypatch):
    """Narrow internal callers can still request the legacy mutation explicitly."""
    monkeypatch.setattr(wb, "world_boss_schema_ready", lambda conn: True)
    monkeypatch.setattr(wb, "build_schedule_info", lambda **kwargs: {"spawn_ready": False})
    monkeypatch.setattr(wb, "list_active_events", lambda **kwargs: [])
    monkeypatch.setattr(wb, "list_definitions", lambda **kwargs: [])

    import game.world_boss_companions as companions

    monkeypatch.setattr(
        companions,
        "build_overview_companions",
        lambda player_id, *, conn, now: {"ready": True, "slots": [], "owned_count": 0},
    )
    called: list[int] = []

    def _flush(player_id, *, conn, now):  # noqa: ANN001
        del conn, now
        called.append(int(player_id))
        return {"ok": True, "attacks": []}

    monkeypatch.setattr(wb, "flush_ready_auto_attacks_for_player", _flush)
    wb.build_world_boss_payload(9, conn=_Conn(), now=12345.0, flush_auto=True)
    assert called == [9]


def test_fleet_worker_remains_server_owned_auto_attack_mutation_owner():
    src = (ROOT / "game" / "fleet_worker.py").read_text(encoding="utf-8")
    assert "from .world_boss import tick_world_boss_auto_attacks" in src
    assert "tick_world_boss_auto_attacks(conn=conn)" in src
    assert "commit(conn)" in src


def test_world_boss_payload_source_documents_read_vs_mutation_boundary():
    src = inspect.getsource(wb.build_world_boss_payload)
    assert "if flush_auto and player_id is not None" in src
    assert "Read payloads stay mutation-free by default" in src
