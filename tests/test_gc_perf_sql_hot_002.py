"""GC-PERF-SQL-HOT-002 — surface frequent SQL signatures on slow requests."""

from __future__ import annotations

import time

from flask import Flask, g


def test_request_perf_aggregates_fast_repeated_sql_without_literals():
    from game.live_state import RequestPerfState, record_request_perf_sql_timing

    app = Flask(__name__)
    with app.test_request_context("/api/game-state"):
        g.gc_request_perf = RequestPerfState(sampled=True, intel_enabled=True)
        for value in (101, 202, 303):
            record_request_perf_sql_timing(
                f"SELECT status FROM player_directives WHERE player_id = {value} LIMIT 1",
                2.0,
            )
        stats = g.gc_request_perf.sql_signature_stats
        assert len(stats) == 1
        signature, row = next(iter(stats.items()))
        assert "101" not in signature
        assert "202" not in signature
        assert "303" not in signature
        assert int(row["count"]) == 3
        assert float(row["total_ms"]) == 6.0


def test_postgres_cursor_native_timing_covers_cursor_execute_once():
    from game.db_pg import PgConnection, PgCursor
    from game.live_state import (
        RequestPerfState,
        attach_request_perf_sql_trace,
    )

    class RawConn:
        pass

    class RawCursor:
        description = None
        rowcount = 1

        def execute(self, _sql, _params=None):
            time.sleep(0.001)
            return self

    app = Flask(__name__)
    with app.test_request_context("/api/game-state"):
        g.gc_request_perf = RequestPerfState(sampled=True, intel_enabled=True)
        conn = PgConnection(RawConn())
        assert "execute" not in conn.__dict__
        attach_request_perf_sql_trace(conn)
        assert getattr(conn, "_gc_perf_cursor_timing", False) is True
        # Native PG instrumentation lives in PgCursor; conn.execute is not monkey-wrapped.
        assert "execute" not in conn.__dict__

        cur = PgCursor(RawCursor(), connection=conn)
        cur.execute("SELECT id FROM planets WHERE id = ?", (7,))
        state = g.gc_request_perf
        assert state.sql_count == 1
        assert len(state.sql_signature_stats) == 1
        row = next(iter(state.sql_signature_stats.values()))
        assert int(row["count"]) == 1


def test_spike_retains_top_frequency_sql_signatures():
    from game.perf_intel import PerfIntelStore, RequestSample

    store = PerfIntelStore(spike_max=8)
    store.record(
        RequestSample(
            ts=time.time(),
            method="GET",
            route="api_game_state",
            path="/api/game-state",
            status=200,
            total_ms=1200.0,
            error=False,
            slow_class="very_slow",
            sql_count=44,
            sql_signatures=[
                {
                    "signature": "SELECT * FROM player_directives WHERE player_id = ?",
                    "count": 31,
                    "total_ms": 90.0,
                    "max_ms": 5.0,
                },
                {
                    "signature": "SELECT * FROM planets WHERE id = ?",
                    "count": 4,
                    "total_ms": 12.0,
                    "max_ms": 4.0,
                },
            ],
        )
    )
    spike = store.recent_spikes(1)[0]
    assert spike["sql_signatures"][0]["count"] == 31
    assert "player_directives" in spike["sql_signatures"][0]["signature"]


def test_admin_spike_ui_renders_sql_frequency_signatures():
    src = open("static/admin.js", encoding="utf-8").read()
    assert "s.sql_signatures" in src
    assert "q.count" in src
    assert "q.signature" in src
