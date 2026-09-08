"""GC-PERF-WB-TX-028 — World Boss worker releases write TX between auto players."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from game import world_boss as wb

ROOT = Path(__file__).resolve().parents[1]


class _Conn:
    pass


def _patch_short_tx_dependencies(monkeypatch, rows, fire):
    import game.db as dbmod
    import game.tx_context as txmod

    monkeypatch.setattr(wb, "world_boss_schema_ready", lambda conn: True)
    monkeypatch.setattr(wb, "_auto_attack_columns_ready", lambda conn: True)
    monkeypatch.setattr(wb, "_world_boss_auto_attack_candidates", lambda *, conn: list(rows))
    monkeypatch.setattr(wb, "maybe_fire_ready_auto_attack", fire)
    monkeypatch.setattr(txmod, "tx_context", lambda **kwargs: nullcontext())
    return dbmod


def test_short_tx_commits_each_auto_candidate_independently(monkeypatch):
    events = []

    def fire(player_id, event_id, *, conn, now, lean_response):
        del conn, now, lean_response
        events.append(f"fire:{event_id}:{player_id}")
        return {"ok": True, "fired": True, "stopped": False}

    dbmod = _patch_short_tx_dependencies(
        monkeypatch,
        [
            {"event_id": 11, "player_id": 101},
            {"event_id": 11, "player_id": 202},
        ],
        fire,
    )
    monkeypatch.setattr(dbmod, "begin_write_transaction", lambda conn: events.append("begin"))
    monkeypatch.setattr(dbmod, "commit", lambda conn: events.append("commit"))
    monkeypatch.setattr(dbmod, "rollback", lambda conn: events.append("rollback"))

    out = wb.tick_world_boss_auto_attacks_short_tx(conn=_Conn(), now=123.0)

    assert events == [
        "begin",
        "fire:11:101",
        "commit",
        "begin",
        "fire:11:202",
        "commit",
    ]
    assert out["fired"] == 2
    assert out["write_commits"] == 2
    assert out["errors"] == []


def test_short_tx_rolls_back_one_player_and_continues(monkeypatch):
    events = []

    def fire(player_id, event_id, *, conn, now, lean_response):
        del conn, now, lean_response
        events.append(f"fire:{event_id}:{player_id}")
        if player_id == 101:
            raise RuntimeError("candidate failed")
        return {"ok": True, "fired": True, "stopped": False}

    dbmod = _patch_short_tx_dependencies(
        monkeypatch,
        [
            {"event_id": 11, "player_id": 101},
            {"event_id": 11, "player_id": 202},
        ],
        fire,
    )
    monkeypatch.setattr(dbmod, "begin_write_transaction", lambda conn: events.append("begin"))
    monkeypatch.setattr(dbmod, "commit", lambda conn: events.append("commit"))
    monkeypatch.setattr(dbmod, "rollback", lambda conn: events.append("rollback"))

    out = wb.tick_world_boss_auto_attacks_short_tx(conn=_Conn(), now=123.0)

    assert events == [
        "begin",
        "fire:11:101",
        "rollback",
        "begin",
        "fire:11:202",
        "commit",
    ]
    assert out["fired"] == 1
    assert out["write_commits"] == 1
    assert len(out["errors"]) == 1


def test_worker_schedule_commits_before_short_auto_attacks():
    src = (ROOT / "game" / "fleet_worker.py").read_text(encoding="utf-8")
    block = src.split("def _world_boss() -> None:", 1)[1].split(
        "def _asteroids() -> None:",
        1,
    )[0]

    assert "include_auto_attack=False" in block
    assert "tick_world_boss_auto_attacks_short_tx" in block
    assert block.index("commit(conn)") < block.index(
        "tick_world_boss_auto_attacks_short_tx(conn=conn)"
    )
    assert '_run_stage("world_boss", _world_boss, manage_tx=False)' in src


def test_idle_skip_uses_short_tx_auto_owner():
    src = (ROOT / "game" / "fleet_worker.py").read_text(encoding="utf-8")
    block = src.split("if not force and not should_run_global_fleet_tick", 1)[1].split(
        "from .fleet import fleet_schema_ready",
        1,
    )[0]

    assert "tick_world_boss_auto_attacks_short_tx" in block
    assert "tick_world_boss_auto_attacks(conn=conn)" not in block
    assert "begin_write_transaction(conn)" not in block
