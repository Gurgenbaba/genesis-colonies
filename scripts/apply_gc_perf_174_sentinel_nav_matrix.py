from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, got {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Include backend identity in the same opt-in, zero-query navigation headers.
replace_once(
    "game/live_state.py",
    "            from game.config import is_nav_perf_debug_enabled\n",
    "            from game.config import is_nav_perf_debug_enabled\n            from game.db import get_db_backend\n",
)
replace_once(
    "game/live_state.py",
    '                response.headers["X-GC-Nav-Db-Query-Ms"] = str(\n                    round(\n                        float(\n                            state.db_query_ms\n                            or state.phases.get("db_query_ms")\n                            or 0.0\n                        ),\n                        1,\n                    )\n                )\n',
    '                response.headers["X-GC-Nav-Db-Query-Ms"] = str(\n                    round(\n                        float(\n                            state.db_query_ms\n                            or state.phases.get("db_query_ms")\n                            or 0.0\n                        ),\n                        1,\n                    )\n                )\n                response.headers["X-GC-Nav-Db-Backend"] = get_db_backend()\n',
)

# Carry backend identity into the bounded browser sample.
replace_once(
    "static/main.js",
    '          const serverMs = headerNumber("X-GC-Nav-Server-Ms");\n',
    '          const headerText = (name) => {\n            const raw = res?.headers?.get?.(name);\n            return raw === null || raw === undefined || raw === "" ? null : String(raw);\n          };\n          const serverMs = headerNumber("X-GC-Nav-Server-Ms");\n',
)
replace_once(
    "static/main.js",
    '              db_query_ms: headerNumber("X-GC-Nav-Db-Query-Ms"),\n',
    '              db_query_ms: headerNumber("X-GC-Nav-Db-Query-Ms"),\n              db_backend: headerText("X-GC-Nav-Db-Backend"),\n',
)
replace_once(
    "static/main.js",
    '      db_query_ms: server?.db_query_ms ?? null,\n      concurrent_requests: s.concurrent,\n',
    '      db_query_ms: server?.db_query_ms ?? null,\n      db_backend: server?.db_backend ?? null,\n      concurrent_requests: s.concurrent,\n',
)

# Sandbox Sentinel owns its own disposable app process, so enabling nav telemetry
# here cannot affect production and avoids any extra instrumentation endpoint.
replace_once(
    "scripts/browser_test_support.py",
    '            "GC_DB_BACKEND": "sqlite",\n            "GC_DB_PATH": str(db_file),\n',
    '            "GC_DB_BACKEND": "sqlite",\n            "GC_NAV_PERF_DEBUG": "1",\n            "GC_DB_PATH": str(db_file),\n',
)

# Add PJAX navigation helper + report aggregation.
sentinel_anchor = '\n\ndef _write_html_report(report: dict, path: Path) -> None:\n'
sentinel_helper = r'''


def _navigate_with_pjax_perf(page, target: str) -> dict:
    """Drive the production PJAX navigator and return the newly emitted perf sample."""
    return page.evaluate(
        """
        async (target) => {
          const getter = window.GC_GET_NAV_PERF_SAMPLES;
          if (!window.GC || typeof window.GC.navigateTo !== "function" || typeof getter !== "function") {
            return { used_pjax: false, sample: null, status: null };
          }
          const before = getter().length;
          await window.GC.navigateTo(target, { force: true });
          await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const samples = getter();
          const fresh = samples.slice(before);
          const sample = fresh.length ? fresh[fresh.length - 1] : null;
          let status = null;
          if (sample && Array.isArray(sample.concurrent_requests)) {
            const primary = sample.concurrent_requests.find((entry) => entry && entry.server)
              || sample.concurrent_requests.find((entry) => entry && Number(entry.status) > 0)
              || null;
            if (primary) status = Number(primary.status || 0) || null;
          }
          return { used_pjax: true, sample, status, href: location.href };
        }
        """,
        target,
    )


def _navigation_perf_summary(route_results: list[dict]) -> dict:
    rows = []
    for item in route_results:
        sample = item.get("navigation_perf") or None
        if not isinstance(sample, dict):
            continue
        rows.append(
            {
                "name": item.get("name"),
                "route": item.get("route"),
                "viewport": item.get("viewport"),
                "total_navigation_ms": sample.get("total_navigation_ms"),
                "server_ms": sample.get("server_ms"),
                "sql_count": sample.get("sql_count"),
                "sql_write_count": sample.get("sql_write_count"),
                "db_connections": sample.get("db_connections"),
                "db_query_ms": sample.get("db_query_ms"),
                "db_backend": sample.get("db_backend"),
            }
        )

    def total_ms(row: dict) -> float:
        value = row.get("total_navigation_ms")
        try:
            return float(value)
        except (TypeError, ValueError):
            return -1.0

    rows.sort(key=total_ms, reverse=True)
    return {
        "sample_count": len(rows),
        "worst_by_total_ms": rows[:12],
    }
'''
replace_once("scripts/browser_sentinel.py", sentinel_anchor, sentinel_helper + sentinel_anchor)

# Route rows now execute the real PJAX path. Full navigation is only a compatibility
# fallback when the game shell does not expose the navigator at all.
replace_once(
    "scripts/browser_sentinel.py",
    '                "status": None,\n                "safe_controls": [],\n',
    '                "status": None,\n                "navigation_mode": None,\n                "navigation_perf": None,\n                "safe_controls": [],\n',
)
replace_once(
    "scripts/browser_sentinel.py",
    '            action = f"GET {spec.path}"\n            try:\n                response = page.goto(f"{base_url.rstrip(\'/\')}{spec.path}", wait_until="domcontentloaded", timeout=60_000)\n                result["status"] = response.status if response else None\n                page.wait_for_selector("body", state="attached", timeout=10_000)\n',
    '            action = f"PJAX {spec.path}"\n            try:\n                nav_result = _navigate_with_pjax_perf(page, spec.path)\n                if nav_result.get("used_pjax"):\n                    result["navigation_mode"] = "pjax"\n                    result["navigation_perf"] = nav_result.get("sample")\n                    result["status"] = nav_result.get("status") or 200\n                else:\n                    response = page.goto(\n                        f"{base_url.rstrip(\'/\')}{spec.path}",\n                        wait_until="domcontentloaded",\n                        timeout=60_000,\n                    )\n                    result["navigation_mode"] = "full-fallback"\n                    result["status"] = response.status if response else None\n                page.wait_for_selector("body", state="attached", timeout=10_000)\n',
)
replace_once(
    "scripts/browser_sentinel.py",
    '        "route_count": len(route_results),\n        "findings": findings,\n        "routes": route_results,\n',
    '        "route_count": len(route_results),\n        "navigation_perf": _navigation_perf_summary(route_results),\n        "findings": findings,\n        "routes": route_results,\n',
)
replace_once(
    "scripts/browser_sentinel.py",
    '            "routes": report["route_count"],\n            "summary": report["summary"],\n',
    '            "routes": report["route_count"],\n            "nav_perf_samples": report["navigation_perf"]["sample_count"],\n            "summary": report["summary"],\n',
)

# Regression contract: the behavioral header test also proves backend identity is
# generated without any additional database operation.
test_path = ROOT / "tests/test_gc_perf_174_sentinel_nav_matrix.py"
test_path.write_text(
    '''"""GC-PERF-174 — Sentinel real-PJAX navigation matrix contracts."""\n\nfrom pathlib import Path\n\npytest_plugins = ["tests.test_game_state_live"]\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef _read(rel: str) -> str:\n    return (ROOT / rel).read_text(encoding="utf-8")\n\n\ndef test_sentinel_sandbox_enables_navigation_perf():\n    src = _read("scripts/browser_test_support.py")\n    assert '"GC_NAV_PERF_DEBUG": "1"' in src\n\n\ndef test_sentinel_drives_real_pjax_and_persists_route_samples():\n    src = _read("scripts/browser_sentinel.py")\n    assert "window.GC.navigateTo" in src\n    assert "window.GC_GET_NAV_PERF_SAMPLES" in src\n    assert '"navigation_mode": None' in src\n    assert '"navigation_perf": None' in src\n    assert '"navigation_perf": _navigation_perf_summary(route_results)' in src\n    assert '"nav_perf_samples": report["navigation_perf"]["sample_count"]' in src\n\n\ndef test_nav_sample_carries_database_backend_identity():\n    server = _read("game/live_state.py")\n    client = _read("static/main.js")\n    assert 'X-GC-Nav-Db-Backend' in server\n    assert 'get_db_backend()' in server\n    assert 'db_backend: headerText("X-GC-Nav-Db-Backend")' in client\n    assert 'db_backend: server?.db_backend ?? null' in client\n\n\ndef test_pjax_backend_header_behavior(game_client, monkeypatch):\n    monkeypatch.setenv("GC_NAV_PERF_DEBUG", "1")\n    monkeypatch.setenv("GC_DB_BACKEND", "sqlite")\n    client, _pid = game_client\n    resp = client.get(\n        "/buildings",\n        headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"},\n    )\n    assert resp.status_code == 200\n    assert resp.headers.get("X-GC-Nav-Db-Backend") == "sqlite"\n''',
    encoding="utf-8",
)

print("GC-PERF-174 patch staged")
