"""GC-PERF-PG-DUE-PROBE-001 — one data round trip for queue due detection."""

from __future__ import annotations


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((str(sql), tuple(params or ())))
        return _Result(self.row)


def test_due_queue_domains_collapse_to_one_data_statement(monkeypatch):
    from game import queue_poll as qp

    monkeypatch.setattr(
        qp,
        "_optional_due_queue_readiness",
        lambda _conn: (True, True, True, True),
    )
    conn = _Conn(row=None)

    assert qp.player_has_due_queue_work(7, conn=conn, now=1000.0) is False
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    normalized = " ".join(sql.split())
    assert normalized.startswith("SELECT 1 WHERE EXISTS")
    for table in (
        "build_queue",
        "research_queue",
        "planet_research_queue",
        "planet_ascension_queue",
        "shipyard_queue",
        "defense_queue",
        "troop_queue",
    ):
        assert table in sql
    # Every due domain must use the same cutoff supplied by the caller.
    assert 7 in params
    assert any(isinstance(value, float) and value >= 1000.0 for value in params)


def test_due_queue_probe_returns_true_from_single_statement(monkeypatch):
    from game import queue_poll as qp

    monkeypatch.setattr(
        qp,
        "_optional_due_queue_readiness",
        lambda _conn: (False, False, False, False),
    )
    conn = _Conn(row={"due": 1})

    assert qp.player_has_due_queue_work(8, conn=conn, now=1000.0) is True
    assert len(conn.calls) == 1
    sql, _params = conn.calls[0]
    assert "build_queue" in sql
    assert "research_queue" in sql
    assert "shipyard_queue" not in sql


def test_planet_scope_keeps_account_research_and_scopes_planet_queues(monkeypatch):
    from game import queue_poll as qp

    monkeypatch.setattr(
        qp,
        "_optional_due_queue_readiness",
        lambda _conn: (True, True, True, True),
    )
    conn = _Conn(row=None)

    qp.player_has_due_queue_work(9, planet_id=42, conn=conn, now=1000.0)
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "bq.planet_id = ?" in sql
    assert "research_queue WHERE user_id = ?" in sql
    assert "tq.planet_id = ?" in sql
    assert 42 in params
    assert 9 in params


def test_worker_primary_no_due_never_runs_pending_probe(monkeypatch):
    from game import config
    from game import queue_poll as qp

    monkeypatch.setattr(config, "is_game_worker_primary", lambda: True)
    monkeypatch.setattr(qp, "player_has_due_queue_work", lambda *_a, **_k: False)

    def _pending_must_not_run(*_a, **_k):
        raise AssertionError("pending queue probe ran under worker-primary ownership")

    monkeypatch.setattr(qp, "player_has_pending_queue_work", _pending_must_not_run)
    allowed, reason = qp.should_poll_attempt_queue_finish(10, conn=object(), now=1000.0)
    assert allowed is False
    assert reason == "no_queue_due"


def test_worker_primary_due_with_fresh_heartbeat_never_runs_pending_probe(monkeypatch):
    from game import config
    from game import queue_poll as qp
    from game import runtime_state

    monkeypatch.setattr(config, "is_game_worker_primary", lambda: True)
    monkeypatch.setattr(qp, "player_has_due_queue_work", lambda *_a, **_k: True)
    monkeypatch.setattr(runtime_state, "is_queue_tick_heartbeat_fresh", lambda **_k: True)

    def _pending_must_not_run(*_a, **_k):
        raise AssertionError("pending queue probe ran under worker-primary ownership")

    monkeypatch.setattr(qp, "player_has_pending_queue_work", _pending_must_not_run)
    allowed, reason = qp.should_poll_attempt_queue_finish(11, conn=object(), now=1000.0)
    assert allowed is False
    assert reason == "queue_tick_fresh_defer"
