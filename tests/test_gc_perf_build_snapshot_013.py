"""GC-PERF-BUILD-PG-013 — Build recalc reuses the mutation snapshot."""

from pathlib import Path
from unittest.mock import patch

from game.buildings import recalculate_build_queue_finish_times


class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((str(sql), tuple(params)))
        return self


class _Conn:
    def __init__(self):
        self.cur = _Cursor()

    def cursor(self):
        return self.cur


class _Hotpath:
    def build_time_seconds(self, _building_type, target_level):
        return 20 + int(target_level)


def test_recalc_with_preloaded_snapshot_performs_no_state_getters():
    conn = _Conn()
    rows = [
        {
            "id": 1,
            "building_type": "metal_mine",
            "start_time": 90.0,
            "finish_time": 150.0,
        },
        {
            "id": 2,
            "building_type": "metal_mine",
            "start_time": 170.0,
            "finish_time": 250.0,
        },
    ]
    buildings = {"metal_mine": 10}
    research = {}

    with patch(
        "game.buildings.get_build_queue_rows",
        side_effect=AssertionError("queue reread"),
    ), patch(
        "game.buildings.get_planet_buildings",
        side_effect=AssertionError("buildings reread"),
    ), patch(
        "game.buildings.get_research_levels",
        side_effect=AssertionError("research reread"),
    ), patch(
        "game.buildings.BuildingsPanelContext.for_queue_recalc",
        side_effect=AssertionError("resolver rebuild"),
    ):
        out = recalculate_build_queue_finish_times(
            7,
            3,
            conn=conn,
            now=100.0,
            rows=rows,
            buildings=buildings,
            research_levels=research,
            hotpath=_Hotpath(),
        )

    assert len(out) == 2
    # Active head keeps its existing window.
    assert out[0]["start_time"] == 90.0
    assert out[0]["finish_time"] == 150.0
    # Follower is chained from the head and returned with the DB-written values.
    assert out[1]["start_time"] == 150.0
    assert out[1]["finish_time"] == 182.0
    updates = [call for call in conn.cur.calls if "UPDATE build_queue" in call[0]]
    assert len(updates) == 1
    assert updates[0][1] == (150.0, 182.0, 2)


def test_enqueue_reuses_recalc_snapshot_in_source_contract():
    src = (Path(__file__).resolve().parents[1] / "game" / "buildings.py").read_text(
        encoding="utf-8"
    )
    block = src.split("def queue_build_for_planet(", 1)[1].split(
        "\ndef cancel_build_job_for_planet(", 1
    )[0]
    before, after = block.split("rows_db = recalculate_build_queue_finish_times(", 1)

    assert before.count("get_planet_buildings(") == 1
    assert before.count("get_research_levels(") == 1
    assert before.count("get_build_queue_rows(") == 1
    # After recalc, the enqueue loop must consume the returned in-memory snapshot.
    assert "get_planet_buildings(" not in after
    assert "get_research_levels(" not in after
    assert "get_build_queue_rows(" not in after
    assert "rows=rows_db" in block
    assert "buildings=buildings" in block
    assert "research_levels=research_levels" in block
    assert "hotpath=hotpath" in block
