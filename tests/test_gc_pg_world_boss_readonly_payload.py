"""Regression gates for the PostgreSQL World Boss GET/read payload hot path."""

from __future__ import annotations

import inspect
from pathlib import Path

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


def test_production_world_boss_get_callers_are_read_only():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    page = src.split("def world_boss_view():", 1)[1].split(
        '@app.route("/api/world-boss")', 1
    )[0]
    api = src.split("def api_world_boss():", 1)[1].split(
        '@app.route("/api/world-boss/attack"', 1
    )[0]

    for block in (page, api):
        assert "flush_auto=True" not in block
        assert "begin_write_transaction" not in block
        assert "commit(conn)" not in block
        assert "rollback(conn)" not in block
        assert "build_world_boss_payload" in block


def test_fleet_worker_remains_server_owned_auto_attack_mutation_owner():
    src = (ROOT / "game" / "fleet_worker.py").read_text(encoding="utf-8")
    assert "tick_world_boss_auto_attacks_short_tx" in src
    assert "include_auto_attack=False" in src
    assert '_run_stage("world_boss", _world_boss, manage_tx=False)' in src


def test_world_boss_payload_source_documents_read_vs_mutation_boundary():
    src = inspect.getsource(wb.build_world_boss_payload)
    assert "if flush_auto and player_id is not None" in src
    assert "Read payloads stay mutation-free by default" in src



class _OneRow:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _AutoGateConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):  # noqa: ANN001
        self.calls.append((str(sql), tuple(params or ())))
        return _OneRow(
            {
                "auto_attack_enabled": 1,
                "auto_attack_ships_json": "{}",
                "auto_attack_planet_id": 41,
                "waves": 3,
                "last_attack_at": 0.0,
            }
        )


def test_auto_fire_gate_drops_repeated_contribution_event_join(monkeypatch):
    conn = _AutoGateConn()
    event = {
        "id": 77,
        "status": wb.STATUS_ACTIVE,
        "ends_at": 10_000.0,
        "current_hp": 999,
    }
    seen = {}

    monkeypatch.setattr(wb, "world_boss_schema_ready", lambda conn: True)
    monkeypatch.setattr(wb, "_auto_attack_columns_ready", lambda conn: True)
    monkeypatch.setattr(wb, "get_event_by_id", lambda event_id, *, conn: dict(event))

    def _can(player_id, event_id, **kwargs):
        seen["can_event"] = kwargs.get("_event_snapshot")
        seen["can_contribution"] = kwargs.get("_contribution_snapshot")
        return True, "", {"event": dict(event), "waves": 3}

    def _execute(player_id, event_id, ships, **kwargs):
        seen["exec_event"] = kwargs.get("_event_snapshot")
        seen["exec_contribution"] = kwargs.get("_contribution_snapshot")
        return {
            "ok": True,
            "attack": {"damage": 5},
            "boss": {"hp": 994},
            "player": {"waves": 4},
            "damage": 5,
        }

    monkeypatch.setattr(wb, "can_player_attack_boss", _can)
    monkeypatch.setattr(wb, "execute_instant_attack", _execute)

    out = wb.maybe_fire_ready_auto_attack(
        9,
        77,
        conn=conn,
        now=100.0,
        ships={"falcon_interceptor": 1},
        planet_id=41,
        lean_response=True,
    )

    assert out["fired"] is True
    assert len(conn.calls) == 1
    gate_sql = " ".join(conn.calls[0][0].split()).upper()
    assert "FROM WORLD_BOSS_CONTRIBUTIONS" in gate_sql
    assert "JOIN WORLD_BOSS_EVENTS" not in gate_sql
    assert "LAST_ATTACK_AT" in gate_sql
    assert seen["can_event"]["id"] == 77
    assert seen["exec_event"]["id"] == 77
    assert seen["can_contribution"]["waves"] == 3
    assert seen["exec_contribution"]["waves"] == 3


def test_can_player_attack_boss_accepts_sql_free_gate_snapshots():
    class _NoSqlConn:
        def execute(self, sql, params=None):  # noqa: ANN001
            raise AssertionError(f"unexpected SQL: {sql} {params}")

    event = {
        "id": 77,
        "status": wb.STATUS_ACTIVE,
        "ends_at": 10_000.0,
        "current_hp": 999,
    }
    contribution = {"waves": 3, "last_attack_at": 0.0}

    ok, reason, meta = wb.can_player_attack_boss(
        9,
        77,
        conn=_NoSqlConn(),
        now=100.0,
        check_inflight=False,
        _event_snapshot=event,
        _contribution_snapshot=contribution,
    )

    assert ok is True
    assert reason == ""
    assert meta["waves"] == 3
    assert meta["event"]["id"] == 77


def test_execute_instant_attack_revalidates_forwarded_gate_snapshots(monkeypatch):
    event = {
        "id": 77,
        "status": wb.STATUS_ACTIVE,
        "ends_at": 10_000.0,
        "current_hp": 999,
    }
    contribution = {"waves": 3, "last_attack_at": 95.0}
    seen = {}

    def _can(player_id, event_id, **kwargs):
        seen["event"] = kwargs.get("_event_snapshot")
        seen["contribution"] = kwargs.get("_contribution_snapshot")
        return False, "world_boss_cooldown", {"cooldown_until": 395.0}

    monkeypatch.setattr(wb, "can_player_attack_boss", _can)

    out = wb.execute_instant_attack(
        9,
        77,
        {"falcon_interceptor": 1},
        planet_id=41,
        conn=object(),
        now=100.0,
        _event_snapshot=event,
        _contribution_snapshot=contribution,
    )

    assert out["ok"] is False
    assert out["error"] == "world_boss_cooldown"
    assert seen["event"] is event
    assert seen["contribution"] is contribution
