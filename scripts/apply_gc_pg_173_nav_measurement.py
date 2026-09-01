from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "game" / "live_state.py"
MAIN = ROOT / "static" / "main.js"
TEST = ROOT / "tests" / "test_gc_perf_002_nav_latency.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Server: expose existing numeric request telemetry to same-origin PJAX only
# when GC_NAV_PERF_DEBUG is explicitly enabled. No query text, no new DB work.
# ---------------------------------------------------------------------------
text = LIVE.read_text(encoding="utf-8")
old = '''        if state.sampled and not is_production_request_perf_header():\n            response.headers["X-GC-Request-Perf-Total-Ms"] = str(\n                round((time.perf_counter() - state.started_at) * 1000.0, 1)\n            )\n'''
new = '''        request_total_ms = round((time.perf_counter() - state.started_at) * 1000.0, 1)\n        if state.sampled and not is_production_request_perf_header():\n            response.headers["X-GC-Request-Perf-Total-Ms"] = str(request_total_ms)\n\n        # GC-PERF-173: staging/Sentinel PJAX correlation. These headers expose\n        # only already-collected numeric counters/timings and create zero DB work.\n        try:\n            from game.config import is_nav_perf_debug_enabled\n\n            if is_nav_perf_debug_enabled() and state.meta.get("pjax"):\n                response.headers["X-GC-Nav-Server-Ms"] = str(request_total_ms)\n                response.headers["X-GC-Nav-Sql-Count"] = str(int(state.sql_count))\n                response.headers["X-GC-Nav-Sql-Write-Count"] = str(int(state.sql_write_count))\n                response.headers["X-GC-Nav-Db-Connections"] = str(\n                    int(state.db_connection_open_count)\n                )\n                response.headers["X-GC-Nav-Db-Query-Ms"] = str(\n                    round(\n                        float(\n                            state.db_query_ms\n                            or state.phases.get("db_query_ms")\n                            or 0.0\n                        ),\n                        1,\n                    )\n                )\n        except Exception:\n            logger.debug("nav perf response headers failed", exc_info=True)\n'''
text = replace_once(text, old, new, "server nav headers")
LIVE.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Browser: correlate server telemetry with the already-existing nav phases and
# retain a bounded machine-readable buffer for Playwright/Sentinel.
# ---------------------------------------------------------------------------
text = MAIN.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''  let _navPerfSession = null;\n  let _navPerfFetchWrapped = false;\n''',
    '''  let _navPerfSession = null;\n  let _navPerfFetchWrapped = false;\n  const NAV_PERF_SAMPLE_LIMIT = 100;\n  const _navPerfSamples = [];\n  window.GC_NAV_PERF_SAMPLES = _navPerfSamples;\n\n  function getNavPerfSamples() {\n    return _navPerfSamples.map((sample) => ({ ...sample }));\n  }\n\n  window.GC_GET_NAV_PERF_SAMPLES = getNavPerfSamples;\n''',
    "nav sample buffer",
)
text = replace_once(
    text,
    '''        return nativeFetch(input, init).then((res) => {\n          entry.duration_ms = Math.round(performance.now() - entry.t0);\n          entry.status = res.status;\n          return res;\n        }).catch((err) => {\n''',
    '''        return nativeFetch(input, init).then((res) => {\n          entry.duration_ms = Math.round(performance.now() - entry.t0);\n          entry.status = res.status;\n          const headerNumber = (name) => {\n            const raw = res?.headers?.get?.(name);\n            if (raw === null || raw === undefined || raw === "") return null;\n            const value = Number(raw);\n            return Number.isFinite(value) ? value : null;\n          };\n          const serverMs = headerNumber("X-GC-Nav-Server-Ms");\n          if (serverMs !== null) {\n            entry.server = {\n              server_ms: serverMs,\n              sql_count: headerNumber("X-GC-Nav-Sql-Count"),\n              sql_write_count: headerNumber("X-GC-Nav-Sql-Write-Count"),\n              db_connections: headerNumber("X-GC-Nav-Db-Connections"),\n              db_query_ms: headerNumber("X-GC-Nav-Db-Query-Ms"),\n            };\n          }\n          return res;\n        }).catch((err) => {\n''',
    "nav fetch server capture",
)
text = replace_once(
    text,
    '''    const payload = {\n      from: s.from,\n      to: s.to,\n      cached: Boolean(s.cached),\n''',
    '''    const serverRequest = s.concurrent.find((entry) => entry && entry.server) || null;\n    const server = serverRequest?.server || null;\n    const payload = {\n      from: s.from,\n      to: s.to,\n      cached: Boolean(s.cached),\n''',
    "nav primary server sample",
)
text = replace_once(
    text,
    '''      total_navigation_ms: round(performance.now() - s.clickAt),\n      concurrent_requests: s.concurrent,\n    };\n    if (extra && typeof extra === "object") Object.assign(payload, extra);\n    console.info("[GC NAV PERF]", payload);\n    _navPerfSession = null;\n''',
    '''      total_navigation_ms: round(performance.now() - s.clickAt),\n      server_ms: server?.server_ms ?? null,\n      sql_count: server?.sql_count ?? null,\n      sql_write_count: server?.sql_write_count ?? null,\n      db_connections: server?.db_connections ?? null,\n      db_query_ms: server?.db_query_ms ?? null,\n      concurrent_requests: s.concurrent,\n    };\n    if (extra && typeof extra === "object") Object.assign(payload, extra);\n    _navPerfSamples.push(payload);\n    if (_navPerfSamples.length > NAV_PERF_SAMPLE_LIMIT) {\n      _navPerfSamples.splice(0, _navPerfSamples.length - NAV_PERF_SAMPLE_LIMIT);\n    }\n    console.info("[GC NAV PERF]", payload);\n    _navPerfSession = null;\n''',
    "nav sample persistence",
)
MAIN.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Regression: behavioral server headers + static browser measurement contract.
# ---------------------------------------------------------------------------
text = TEST.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    assert 'console.info("[GC NAV PERF]"' in src\n    assert "concurrent_requests" in src\n''',
    '''    assert 'console.info("[GC NAV PERF]"' in src\n    assert "concurrent_requests" in src\n    assert "NAV_PERF_SAMPLE_LIMIT = 100" in src\n    assert "window.GC_NAV_PERF_SAMPLES" in src\n    assert "window.GC_GET_NAV_PERF_SAMPLES" in src\n    assert '_navPerfSamples.push(payload)' in src\n    for header in (\n        "X-GC-Nav-Server-Ms",\n        "X-GC-Nav-Sql-Count",\n        "X-GC-Nav-Sql-Write-Count",\n        "X-GC-Nav-Db-Connections",\n        "X-GC-Nav-Db-Query-Ms",\n    ):\n        assert header in src\n''',
    "browser nav contract",
)
text += '''\n\ndef test_buildings_pjax_nav_measurement_headers(game_client, monkeypatch):\n    monkeypatch.setenv("GC_NAV_PERF_DEBUG", "1")\n    client, _pid = game_client\n    resp = client.get(\n        "/buildings",\n        headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},\n    )\n    assert resp.status_code == 200\n    expected = (\n        "X-GC-Nav-Server-Ms",\n        "X-GC-Nav-Sql-Count",\n        "X-GC-Nav-Sql-Write-Count",\n        "X-GC-Nav-Db-Connections",\n        "X-GC-Nav-Db-Query-Ms",\n    )\n    for header in expected:\n        assert header in resp.headers\n        assert float(resp.headers[header]) >= 0\n\n\ndef test_nav_measurement_headers_are_opt_in(game_client, monkeypatch):\n    monkeypatch.delenv("GC_NAV_PERF_DEBUG", raising=False)\n    client, _pid = game_client\n    resp = client.get(\n        "/buildings",\n        headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},\n    )\n    assert resp.status_code == 200\n    assert "X-GC-Nav-Server-Ms" not in resp.headers\n'''
TEST.write_text(text, encoding="utf-8")

print("GC-PERF-173 navigation measurement contract applied")
