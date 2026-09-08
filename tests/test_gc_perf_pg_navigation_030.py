"""GC-PERF-PG-NAV-030 — PostgreSQL HTTP navigation sentinel.

Runs core authenticated PJAX pages against PostgreSQL and records the existing
request-perf response headers. The second pass is the measurement pass: first
visits may legitimately persist Codex/Initiation unlocks or bootstrap data.

Wall-clock numbers are diagnostic only because CI hardware is not production.
Structural budgets are authoritative here:
- repeated PJAX navigation performs no DB writes;
- repeated PJAX navigation uses at most one request DB checkout.
"""

from __future__ import annotations

import importlib
import json
import uuid

import pytest

from tests.pg_fixtures import close_pg_pool, requires_postgres


ROUTES = (
    "/overview",
    "/buildings",
    "/research",
    "/shipyard",
    "/defense",
    "/fleet",
    "/galaxy",
    "/empire",
    "/combat-simulator",
    "/inventory",
    "/vote-center",
    "/galactic-politics",
)

PERF_HEADERS = {
    "server_ms": "X-GC-Nav-Server-Ms",
    "sql_count": "X-GC-Nav-Sql-Count",
    "writes": "X-GC-Nav-Sql-Write-Count",
    "db_connections": "X-GC-Nav-Db-Connections",
    "db_query_ms": "X-GC-Nav-Db-Query-Ms",
}


def _metric(resp, key: str) -> float:
    raw = resp.headers.get(PERF_HEADERS[key])
    assert raw is not None, (key, dict(resp.headers))
    return float(raw)


@requires_postgres
def test_pg_core_pjax_navigation_structural_budget(pg_parity_db, monkeypatch):
    monkeypatch.setenv("GC_NAV_PERF_DEBUG", "1")
    monkeypatch.setenv("GC_REQUEST_PERF_SAMPLE", "1.0")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    monkeypatch.setenv("GC_PG_POOL_TIMEOUT", "3")

    from game.bootstrap import bootstrap_application
    from game.models import create_user

    bootstrap_application(skip_migration_check=True)

    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True

    uname = f"pgnav_{uuid.uuid4().hex[:8]}"
    ok, reason, user = create_user(uname, "PgNav!Pass99xx")
    assert ok and user, reason
    user_id = int(user["id"])

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    headers = {
        "X-PJAX": "true",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html",
    }

    # Warm every durable route visit / one-time bootstrap first.
    for route in ROUTES:
        resp = client.get(route, headers=headers)
        assert resp.status_code == 200, (route, resp.status_code, resp.get_data(as_text=True)[:500])

    samples = []
    for route in ROUTES:
        resp = client.get(route, headers=headers)
        assert resp.status_code == 200, (route, resp.status_code, resp.get_data(as_text=True)[:500])

        sample = {"route": route}
        for key in PERF_HEADERS:
            sample[key] = _metric(resp, key)
        samples.append(sample)
        print("[PG NAV PERF] " + json.dumps(sample, sort_keys=True), flush=True)

        assert sample["writes"] == 0, sample
        assert sample["db_connections"] <= 1, sample

    # Keep the aggregate visible in CI logs for follow-up SQL-budget slicing.
    summary = {
        "routes": len(samples),
        "max_server_ms": max(s["server_ms"] for s in samples),
        "max_sql_count": max(s["sql_count"] for s in samples),
        "max_db_query_ms": max(s["db_query_ms"] for s in samples),
        "max_db_connections": max(s["db_connections"] for s in samples),
        "total_writes": sum(s["writes"] for s in samples),
    }
    print("[PG NAV SUMMARY] " + json.dumps(summary, sort_keys=True), flush=True)

    close_pg_pool()
