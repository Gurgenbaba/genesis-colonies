"""GC-PERF-TK-PG-022 — real PostgreSQL Timekeeper HTTP profiling sentinel.

Runs only when GC_TEST_POSTGRES_URL is available. Uses the existing request-perf
owner to report SQL statements, pool checkouts and DB time for the exact browser
flow: Timekeeper apply, and after a real Building completion the canonical
Buildings include_panel reconcile.
"""

from __future__ import annotations

import importlib
import time
import uuid
from typing import Any, Callable

import pytest

pytest_plugins = ["tests.pg_fixtures"]

from tests.pg_fixtures import requires_postgres


def _seed_build_timekeeper(*, finish_in: int, credit_seconds: int):
    from game.db import begin_write_transaction, commit, db
    from game.models import (
        add_build_job,
        create_user,
        ensure_player_and_homeworld,
        get_homeworld,
    )
    from game.timekeeper import credit

    username = f"tk_pg_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(username, "test-pass-123")
    assert ok, err
    uid = int(user["id"])

    conn = db()
    try:
        ensure_player_and_homeworld(uid, player_name="TkPg", conn=conn)
        planet = get_homeworld(player_id=uid, conn=conn)
        assert planet is not None
        pid = int(planet["id"])

        now = time.time()
        add_build_job(
            pid,
            "metal_mine",
            now - 10,
            now + int(finish_in),
            conn=conn,
        )
        begin_write_transaction(conn)
        credit(uid, int(credit_seconds), "pg_http_sentinel", conn=conn)
        commit(conn)
        return uid, pid
    finally:
        conn.close()


def _client_for(uid: int):
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = int(uid)
    return client


def _profile_request(monkeypatch, request_fn: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    """Capture the existing request perf state; do not invent a second profiler."""
    from game import live_state

    captured: dict[str, Any] = {}
    original = live_state._emit_request_perf_log

    def _capture(state, *args, **kwargs):
        captured.update(
            {
                "sampled": bool(state.sampled),
                "sql_count": int(state.sql_count),
                "sql_write_count": int(state.sql_write_count),
                "db_connections": int(state.db_connection_open_count),
                "db_query_ms": round(float(state.db_query_ms), 1),
                "phases": dict(state.phases),
                "meta": dict(state.meta),
                "sql_signatures": sorted(
                    (
                        {
                            "signature": str(signature),
                            "count": int(values.get("count", 0.0)),
                            "total_ms": round(float(values.get("total_ms", 0.0)), 1),
                            "max_ms": round(float(values.get("max_ms", 0.0)), 1),
                        }
                        for signature, values in state.sql_signature_stats.items()
                    ),
                    key=lambda row: (-int(row["count"]), -float(row["total_ms"])),
                )[:12],
            }
        )
        return original(state, *args, **kwargs)

    monkeypatch.setattr(live_state, "_emit_request_perf_log", _capture)
    started = time.perf_counter()
    response = request_fn()
    captured["wall_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    assert captured, "request perf state was not emitted"
    assert captured.get("sampled") is True
    return response, captured


def _print_profile(label: str, perf: dict[str, Any]) -> None:
    phases = perf.get("phases") or {}
    print(
        "[TK-PG-022] "
        f"{label} wall_ms={perf.get('wall_ms')} "
        f"sql={perf.get('sql_count')} writes={perf.get('sql_write_count')} "
        f"opens={perf.get('db_connections')} db_ms={perf.get('db_query_ms')} "
        f"live_context_ms={round(float(phases.get('live_context_ms') or 0), 1)} "
        f"payload_ms={round(float(phases.get('payload_ms') or 0), 1)} "
        f"panel_ms={round(float(phases.get('panel_total_ms') or phases.get('payload_panel_ms') or 0), 1)}",
        flush=True,
    )
    for row in perf.get("sql_signatures") or []:
        print(
            "[TK-PG-022-SQL] "
            f"{label} count={row['count']} total_ms={row['total_ms']} "
            f"max_ms={row['max_ms']} sig={row['signature']}",
            flush=True,
        )


@pytest.fixture(autouse=True)
def _force_perf_sample(monkeypatch):
    monkeypatch.setenv("GC_PERF_INTEL", "1")
    monkeypatch.setenv("GC_PERF_INTEL_SAMPLE", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_DEBUG", "0")


@requires_postgres
def test_pg_timekeeper_partial_build_http_profile(pg_parity_db, monkeypatch):
    uid, pid = _seed_build_timekeeper(finish_in=7200, credit_seconds=900)
    client = _client_for(uid)

    response, perf = _profile_request(
        monkeypatch,
        lambda: client.post(
            "/api/timekeeper/apply",
            json={"domain": "build", "planet_id": pid, "mode": "max"},
        ),
    )
    body = response.get_json() or {}
    assert response.status_code == 200, body
    assert body.get("ok") is True
    assert int(body.get("seconds_applied") or 0) > 0
    assert body.get("jobs_finished") is False

    _print_profile("partial_apply", perf)

    # Structural guardrails, deliberately loose enough for runner variance.
    # The purpose is to catch a return to hundreds/thousands of serial PG calls.
    assert int(perf["db_connections"]) <= 4, perf
    assert int(perf["sql_count"]) < 300, perf


@requires_postgres
def test_pg_timekeeper_finish_plus_buildings_reconcile_profile(pg_parity_db, monkeypatch):
    uid, pid = _seed_build_timekeeper(finish_in=90, credit_seconds=3600)
    client = _client_for(uid)

    apply_response, apply_perf = _profile_request(
        monkeypatch,
        lambda: client.post(
            "/api/timekeeper/apply",
            json={"domain": "build", "planet_id": pid, "mode": "max"},
        ),
    )
    apply_body = apply_response.get_json() or {}
    assert apply_response.status_code == 200, apply_body
    assert apply_body.get("ok") is True
    assert apply_body.get("jobs_finished") is True
    _print_profile("finish_apply", apply_perf)

    reconcile_response, reconcile_perf = _profile_request(
        monkeypatch,
        lambda: client.get(
            "/api/game-state?include_panel=1&panel_page=buildings&panel_tab=resources"
        ),
    )
    reconcile_body = reconcile_response.get_json() or {}
    assert reconcile_response.status_code == 200, reconcile_body
    assert reconcile_body.get("ok") is True
    assert reconcile_body.get("buildings_panel") is not None
    _print_profile("finish_reconcile", reconcile_perf)

    assert int(apply_perf["db_connections"]) <= 4, apply_perf
    assert int(apply_perf["sql_count"]) < 350, apply_perf
    assert int(reconcile_perf["db_connections"]) <= 4, reconcile_perf
    # Full Buildings reconcile is allowed to be larger, but never return to the
    # old multi-thousand-query PG regression.
    assert int(reconcile_perf["sql_count"]) < 700, reconcile_perf
