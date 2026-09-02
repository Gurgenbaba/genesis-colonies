"""PG production regression: building cancel must not open a second owner lookup connection."""

from __future__ import annotations

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cancel_build_uses_mutation_connection_for_owner_lookup():
    src = (ROOT / "game/buildings.py").read_text(encoding="utf-8")
    block = src.split("def cancel_build_job_for_planet(", 1)[1].split("# =============================================================================", 1)[0]
    assert "SELECT player_id FROM planets WHERE id = ? LIMIT 1;" in block
    assert "owner_row = conn.execute(" in block
    assert "get_planet_owner_id(planet_id)" not in block
    assert "lock_planet_for_update(conn, planet_id)" in block
    assert "refund_build_job(" in block
    assert "recalculate_build_queue_finish_times(" in block


def test_queue_contract_still_requires_finish_refund_delete_reschedule_order():
    src = (ROOT / "game/buildings.py").read_text(encoding="utf-8")
    block = src.split("def cancel_build_job_for_planet(", 1)[1].split("# =============================================================================", 1)[0]
    positions = [
        block.index("finish_due_work("),
        block.index("refund_build_job("),
        block.index("delete_build_job("),
        block.index("recalculate_build_queue_finish_times("),
        block.index("commit(conn)"),
    ]
    assert positions == sorted(positions)


def test_cancel_build_executes_on_exactly_one_connection(monkeypatch):
    import game.buildings as buildings
    import game.queue_engine as queue_engine
    import game.queue_refund as queue_refund

    job = {
        "id": 42,
        "building_type": "metal_mine",
        "start_time": time.time() + 100,
        "finish_time": time.time() + 200,
        "cost_metal": 1000,
        "cost_crystal": 500,
    }

    class FakeResult:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class FakeCursor:
        def __init__(self):
            self.last_sql = ""

        def execute(self, sql, params=()):
            self.last_sql = str(sql)
            return self

        def fetchone(self):
            if "FROM build_queue" in self.last_sql:
                return dict(job)
            raise AssertionError(f"unexpected cursor fetch for SQL: {self.last_sql}")

    class FakeConn:
        def __init__(self):
            self.closed = False
            self.owner_queries = 0

        def execute(self, sql, params=()):
            text = str(sql)
            if "SELECT player_id FROM planets" in text:
                self.owner_queries += 1
                assert tuple(params) == (5,)
                return FakeResult({"player_id": 7})
            raise AssertionError(f"unexpected direct SQL: {text}")

        def cursor(self):
            return FakeCursor()

        def close(self):
            self.closed = True

    fake_conn = FakeConn()
    db_calls = []
    observed = []

    def fake_db():
        db_calls.append(fake_conn)
        return fake_conn

    monkeypatch.setattr(buildings, "db", fake_db)
    monkeypatch.setattr(buildings, "begin_write_transaction", lambda conn: observed.append(("begin", conn)))
    monkeypatch.setattr(buildings, "lock_planet_for_update", lambda conn, pid: observed.append(("lock", conn, pid)))
    monkeypatch.setattr(buildings, "rollback", lambda conn: observed.append(("rollback", conn)))
    monkeypatch.setattr(buildings, "commit", lambda conn: observed.append(("commit", conn)))
    monkeypatch.setattr(
        buildings,
        "get_planet_owner_id",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("second owner lookup must not run")),
    )
    monkeypatch.setattr(
        queue_engine,
        "finish_due_work",
        lambda **kwargs: (
            observed.append(("finish", kwargs["conn"])),
            {"finished": {"buildings": 0, "research": 0}},
        )[1],
    )

    def fake_refund(conn, planet_id, **kwargs):
        observed.append(("refund", conn, planet_id, kwargs["job_id"]))
        return {
            "refund_ratio": 1.0,
            "refund_metal": 1000,
            "refund_crystal": 500,
        }

    monkeypatch.setattr(queue_refund, "refund_build_job", fake_refund)
    monkeypatch.setattr(
        buildings,
        "delete_build_job",
        lambda job_id, *, conn=None: observed.append(("delete", conn, job_id)),
    )
    monkeypatch.setattr(
        buildings,
        "recalculate_build_queue_finish_times",
        lambda planet_id, owner_id, *, conn=None, now=None: observed.append(
            ("reschedule", conn, planet_id, owner_id)
        ),
    )
    monkeypatch.setattr(buildings, "invalidate_player_score_cache", lambda *a, **k: None)

    ok, reason, payload = buildings.cancel_build_job_for_planet(5, 42, user_id=7)

    assert ok is True
    assert reason == "ok"
    assert payload["cancelled"] is True
    assert payload["refund_ratio"] == 1.0
    assert db_calls == [fake_conn]
    assert fake_conn.owner_queries == 1
    assert fake_conn.closed is True

    same_conn_events = [event for event in observed if event[0] in {"begin", "lock", "finish", "refund", "delete", "reschedule", "commit"}]
    assert same_conn_events
    assert all(fake_conn in event for event in same_conn_events)
    assert [event[0] for event in same_conn_events] == [
        "begin",
        "lock",
        "finish",
        "refund",
        "delete",
        "reschedule",
        "commit",
    ]
