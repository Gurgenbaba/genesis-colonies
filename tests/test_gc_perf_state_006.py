"""GC-PERF-STATE-006 — diet score/rank reads reuse the request DB connection."""

from __future__ import annotations

import inspect

import game.live_state as live_state
import game.models as models
import game.ranking as ranking


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((str(sql), tuple(params)))
        return self

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._cursor = _FakeCursor(row)

    def cursor(self):
        return self._cursor


def test_score_cache_miss_reuses_caller_connection(monkeypatch):
    ranking.invalidate_all_score_cache()
    conn = _FakeConn(
        {
            "player_id": 77,
            "score_total": 123,
            "score_buildings": 100,
            "score_research": 23,
        }
    )

    def fail_db():
        raise AssertionError("get_player_score_cached opened a nested DB connection")

    monkeypatch.setattr(ranking, "db", fail_db)
    result = ranking.get_player_score_cached(77, read_only=True, conn=conn)

    assert result["total"] == 123
    assert result["buildings"] == 100
    assert result["research"] == 23
    assert len(conn._cursor.executed) == 1
    assert "player_scores" in conn._cursor.executed[0][0]


def test_models_rank_wrapper_forwards_caller_connection(monkeypatch):
    sentinel = object()
    seen = {}

    def fake_rank(player_id, conn=None):
        seen["player_id"] = player_id
        seen["conn"] = conn
        return 4, 99

    monkeypatch.setattr(ranking, "get_player_rank", fake_rank)
    assert models.get_player_rank(17, conn=sentinel) == (4, 99)
    assert seen == {"player_id": 17, "conn": sentinel}


def test_probe_passes_request_connection_to_score_and_rank():
    source = inspect.getsource(live_state.probe_poll_version)
    assert "get_player_score_cached(uid, read_only=True, conn=conn)" in source
    assert "get_player_rank(uid, conn=conn)" in source
