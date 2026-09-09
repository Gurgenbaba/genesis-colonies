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



class _RowsResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)


class _QueueProbeConn:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        self.calls.append((normalized, tuple(params)))
        if "FROM build_queue" in normalized:
            return _RowsResult(
                [
                    {"id": 11, "building_type": "metal_mine", "finish_time": 200.5},
                    {"id": 12, "building_type": "solar_plant", "finish_time": 350.0},
                ]
            )
        if "FROM research_queue" in normalized:
            return _RowsResult(
                [
                    {"id": 21, "tech_key": "energy_tech", "finish_at": 500.25},
                ]
            )
        raise AssertionError(f"unexpected SQL: {normalized}")


def test_diet_queue_probe_reads_only_fingerprint_columns():
    conn = _QueueProbeConn()

    build = live_state._build_queue_probe_slice(7, conn=conn)
    research = live_state._research_queue_probe_slice(9, conn=conn)

    assert build == [
        {"id": 11, "building_type": "metal_mine", "finish_time": 200.5},
        {"id": 12, "building_type": "solar_plant", "finish_time": 350.0},
    ]
    assert research == [
        {
            "id": 21,
            "key": "energy_tech",
            "tech_key": "energy_tech",
            "finish_at": 500.25,
        },
    ]

    build_sql = conn.calls[0][0]
    research_sql = conn.calls[1][0]
    assert "SELECT id, building_type, finish_time FROM build_queue" in build_sql
    assert "SELECT *" not in build_sql
    assert "SELECT id, tech_key, finish_at FROM research_queue" in research_sql
    assert "SELECT *" not in research_sql


def test_probe_no_longer_builds_full_build_or_research_status():
    source = inspect.getsource(live_state.probe_poll_version)

    assert "get_build_queue_status_for_planet" not in source
    assert "get_research_status" not in source
    assert "_build_queue_probe_slice" in source
    assert "_research_queue_probe_slice" in source


def test_minimal_queue_probe_shapes_hash_like_full_queue_shapes():
    minimal_build = [
        {"id": 11, "building_type": "metal_mine", "finish_time": 200.5},
    ]
    full_build = {
        "queue": [
            {
                "id": 11,
                "building_type": "metal_mine",
                "label_key": "building_metal_mine",
                "target_level": 42,
                "remaining": 99,
                "remaining_seconds": 99,
                "total": 120,
                "finish_time": 200.5,
            }
        ],
        "summary": {"count": 1, "limit": 5},
    }
    minimal_research = [
        {
            "id": 21,
            "key": "energy_tech",
            "tech_key": "energy_tech",
            "finish_at": 500.25,
        },
    ]
    full_research = [
        {
            "id": 21,
            "tech_key": "energy_tech",
            "key": "energy_tech",
            "label": "Energy",
            "remaining": 300,
            "finish_at": 500.25,
            "target_level": 8,
        }
    ]

    assert live_state._queue_fp_for_poll(minimal_build) == live_state._queue_fp_for_poll(full_build)
    assert live_state._queue_fp_for_poll(minimal_research) == live_state._queue_fp_for_poll(full_research)
