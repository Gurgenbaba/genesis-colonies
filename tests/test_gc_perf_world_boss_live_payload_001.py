"""GC-PERF-WB-LIVE-001 — live HP polls must not rebuild the full boss page."""

from __future__ import annotations

import inspect
from pathlib import Path

from game import world_boss as wb

ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), tuple(params or ())))
        return _Result(
            {
                "player_id": 7,
                "alliance_id": None,
                "damage": 123,
                "waves": 2,
                "alliance_xp": 4,
                "last_attack_at": 990.0,
                "auto_attack_enabled": 1,
                "player_rank": 3,
                "total_players": 12,
            }
        )


def _event(event_id=44):
    return {
        "id": event_id,
        "status": wb.STATUS_ACTIVE,
        "current_hp": 900,
        "max_hp": 1000,
        "starts_at": 1.0,
        "ends_at": 9999.0,
    }


def test_live_payload_reads_one_personal_snapshot_per_visible_event(monkeypatch):
    monkeypatch.setattr(wb, "world_boss_schema_ready", lambda conn: True)
    monkeypatch.setattr(wb, "list_active_events", lambda **kwargs: [_event()])

    import game.db as db_module

    monkeypatch.setattr(db_module, "column_exists", lambda *args, **kwargs: True)
    conn = _Conn()
    payload = wb.build_world_boss_live_payload(7, conn=conn, event_ids=[44], now=1000.0)

    assert len(conn.calls) == 1
    assert payload["event"]["current_hp"] == 900
    assert payload["player"]["contribution"]["damage"] == 123
    assert payload["player"]["rank"] == 3
    assert payload["player"]["total_players"] == 12
    assert payload["player"]["attack_meta"]["cooldown_until"] == 1290.0
    assert payload["flushed_attacks"] == []


def test_live_payload_excludes_full_page_builders():
    src = inspect.getsource(wb.build_world_boss_live_payload)
    for forbidden in (
        "build_world_boss_recognition",
        "build_player_reward_outlook",
        "build_overview_companions",
        "list_alliance_contributions",
        "formation_preview_from_hangar",
        "list_contributions",
    ):
        assert forbidden not in src


def test_browser_live_poll_requests_compact_payload():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert 'const params = new URLSearchParams({ live: "1" });' in src
    assert 'params.set("event_ids", ids.join(","))' in src
    assert "fetch(wbLivePollUrl()," in src


def test_api_keeps_full_payload_for_non_live_requests():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    block = src.split("def api_world_boss():", 1)[1].split(
        '@app.route("/api/world-boss/attack"', 1
    )[0]
    assert "if live_poll:" in block
    assert "build_world_boss_live_payload" in block
    assert "build_world_boss_payload" in block
    assert "event_ids=visible_event_ids" in block
