from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Keep same-origin failures strict by default, but classify two known lifecycle
# aborts and Werkzeug's local WS framing limitation below the release gate.
anchor = '''def _install_third_party_guard(context, base_url: str) -> None:\n'''
helper = '''def _runtime_event_severity(*, kind: str, problem: str, url: str = "", base_url: str = "") -> str:\n    text = str(problem or "")\n    if kind == "request_failed" and "net::ERR_ABORTED" in text:\n        path = urlsplit(str(url or "")).path\n        if path in {"/api/chat/bootstrap", "/api/messages"}:\n            return "LOW"\n    if (\n        kind == "console_error"\n        and str(base_url or "").startswith("http://127.0.0.1:")\n        and "WebSocket connection to '" in text\n        and "/ws/galaxy/" in text\n        and "Invalid frame header" in text\n    ):\n        return "LOW"\n    return "HIGH"\n\n\n'''
replace_once("scripts/browser_sentinel.py", anchor, helper + anchor)

replace_once(
    "scripts/browser_sentinel.py",
    '''    def on_console(message) -> None:\n        if message.type == "error":\n            add("console_error", "HIGH", problem=message.text)\n''',
    '''    def on_console(message) -> None:\n        if message.type == "error":\n            problem = message.text\n            add(\n                "console_error",\n                _runtime_event_severity(\n                    kind="console_error",\n                    problem=problem,\n                    base_url=base_url,\n                ),\n                problem=problem,\n            )\n''',
)

replace_once(
    "scripts/browser_sentinel.py",
    '''        failure = getattr(request, "failure", None)\n        add(\n            "request_failed",\n            "HIGH",\n            problem=f"Request failed: {request.url}",\n            details={"url": request.url, "resource_type": request.resource_type, "failure": failure},\n        )\n''',
    '''        failure = getattr(request, "failure", None)\n        problem = f"Request failed: {request.url} ({failure or 'unknown'})"\n        add(\n            "request_failed",\n            _runtime_event_severity(\n                kind="request_failed",\n                problem=problem,\n                url=request.url,\n                base_url=base_url,\n            ),\n            problem=problem,\n            details={"url": request.url, "resource_type": request.resource_type, "failure": failure},\n        )\n''',
)

# Pin the classifier with behavioral unit tests. Unknown same-origin aborts and
# non-local websocket errors remain HIGH.
test = ROOT / "tests/test_gc_perf_174_sentinel_nav_matrix.py"
text = test.read_text(encoding="utf-8")
text += '''\n\ndef test_sentinel_lifecycle_noise_classifier_is_narrow():\n    from scripts.browser_sentinel import _runtime_event_severity\n\n    assert _runtime_event_severity(\n        kind="request_failed",\n        problem="Request failed: http://127.0.0.1:5000/api/chat/bootstrap (net::ERR_ABORTED)",\n        url="http://127.0.0.1:5000/api/chat/bootstrap",\n        base_url="http://127.0.0.1:5000",\n    ) == "LOW"\n    assert _runtime_event_severity(\n        kind="request_failed",\n        problem="Request failed: http://127.0.0.1:5000/api/messages?limit=50 (net::ERR_ABORTED)",\n        url="http://127.0.0.1:5000/api/messages?limit=50",\n        base_url="http://127.0.0.1:5000",\n    ) == "LOW"\n    assert _runtime_event_severity(\n        kind="request_failed",\n        problem="Request failed: http://127.0.0.1:5000/api/game-state (net::ERR_ABORTED)",\n        url="http://127.0.0.1:5000/api/game-state",\n        base_url="http://127.0.0.1:5000",\n    ) == "HIGH"\n\n\ndef test_sentinel_local_werkzeug_galaxy_ws_noise_is_not_live_suppression():\n    from scripts.browser_sentinel import _runtime_event_severity\n\n    problem = "WebSocket connection to 'ws://127.0.0.1:5000/ws/galaxy/5/404' failed: Invalid frame header"\n    assert _runtime_event_severity(\n        kind="console_error", problem=problem, base_url="http://127.0.0.1:5000"\n    ) == "LOW"\n    assert _runtime_event_severity(\n        kind="console_error", problem=problem, base_url="https://genesis-colonies.com"\n    ) == "HIGH"\n'''
test.write_text(text, encoding="utf-8")

print("GC-PERF-174C lifecycle-noise patch staged")
