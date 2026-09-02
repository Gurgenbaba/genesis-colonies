"""GC-PJAX-RESILIENCE-001 — transient 502, late preload, Messages init guards."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gateway_backoff_is_shared_and_read_only():
    src = _read("static/js/core/gc.js")
    block = src.split("function installGatewayBackoff()", 1)[1].split(
        "function installLatePjaxPreloadGuard()", 1
    )[0]

    for path in (
        "/api/game-state",
        "/api/world-boss",
        "/api/notifications/summary",
        "/api/chat/messages",
    ):
        assert f'"{path}": true' in block

    assert 'meta.method === "GET"' in block
    assert "response.status !== 502" in block
    assert "backoffUntil" in block
    assert "maxRetries = 2" in block
    assert "await sleep(sharedDelay, meta.signal)" in block
    assert "global.fetch = gcFetch" in block


def test_late_pjax_preloads_are_suppressed_without_touching_ssr_links():
    src = _read("static/js/core/gc.js")
    block = src.split("function installLatePjaxPreloadGuard()", 1)[1].split(
        "function installMessagesInitGuard()", 1
    )[0]

    assert "head.appendChild = function appendChildWithGcPreloadGuard" in block
    assert 'node.dataset.gcLcpPreload === "1"' in block
    assert 'node.dataset.gcFramePreload === "1"' in block
    assert 'node.dataset.gcPjaxPreloadSuppressed = "1"' in block
    assert "return nativeAppendChild(node)" in block

    # Existing SSR preload remains in base.html and is parsed before core/gc.js.
    base = _read("templates/base.html")
    assert 'id="gc-planet-landscape-preload"' in base


def test_messages_module_init_is_guarded_per_live_root():
    src = _read("static/js/core/gc.js")
    block = src.split("function installMessagesInitGuard()", 1)[1]

    assert 'getElementById("messages-page")' in block
    assert "root === lastRoot" in block
    assert "lastRoot = root" in block
    assert 'bindGuardedProperty(modules, "messages")' in block
    assert 'bindGuardedProperty(GC, "initMessagesPage")' in block
    assert "Object.defineProperty" in block


def test_core_guard_loads_between_main_and_messages_module():
    base = _read("templates/base.html")
    main_pos = base.index("filename='main.js'")
    core_pos = base.index("filename='js/core/gc.js'")
    messages_pos = base.index("filename='js/messages.js'")
    assert main_pos < core_pos < messages_pos
