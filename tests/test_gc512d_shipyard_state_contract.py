"""
GC-512D + GC-PERF-JS-002 — shipyard state-first envelope + page module split.

Run: python -m pytest tests/test_gc512d_shipyard_state_contract.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_shipyard_build_uses_apply_action_state_when_state_present():
    """GC-512D — build success path is state-first (applyActionState when res.state)."""
    src = _read("static/js/pages/shipyard.js")
    build = src.split('GC.fetchGameAction("/api/shipyard/build"')[1].split(
        'showNotify(reasonText("generic")'
    )[0]
    assert "if (res.state)" in build
    assert 'applyActionState(res, "shipyard_build")' in build
    assert "applyShipyardState(page, res.data)" in build
    # No redundant full refresh when state already applied
    assert 'refreshGameState("shipyard_build")' not in build


def test_shipyard_cancel_uses_apply_action_state_when_state_present():
    src = _read("static/js/pages/shipyard.js")
    cancel = src.split('GC.fetchGameAction("/api/shipyard/queue/cancel"')[1].split(
        'GC.fetchGameAction("/api/shipyard/queue/move"'
    )[0]
    assert 'applyActionState(resCancel, "shipyard_cancel")' in cancel
    assert "if (resCancel.state)" in cancel
    assert "applyShipyardState(page, resCancel.data)" in cancel


def test_state_ajax_docs_shipyard_ok_state_envelope():
    doc = _read("docs/STATE_AJAX.md")
    assert "POST /api/shipyard/build" in doc
    assert "`{ ok, state }`" in doc or "{ ok, state }" in doc
    assert "GC-512D" in doc
    assert "applyActionState" in doc
    # Old exception claiming shipyard is data-only must be gone
    assert "Ausnahme (GC-512D):** Shipyard → `{ ok, data }`" not in doc


def test_gc_perf_js_002_shipyard_page_module_extracted():
    """GC-PERF-JS-002 — binder lives in pages/shipyard.js; main.js is thin delegate only."""
    page_mod = ROOT / "static" / "js" / "pages" / "shipyard.js"
    assert page_mod.is_file()
    page_src = page_mod.read_text(encoding="utf-8")
    assert "function bindShipyardOnce" in page_src
    assert "function initShipyard" in page_src
    assert 'GC.pages.shipyard' in page_src
    assert 'GC.fetchGameAction("/api/shipyard/build"' in page_src

    main = _read("static/main.js")
    # Full binder deleted from main.js (Regel 19)
    assert "function bindShipyardOnce" not in main
    assert 'e.target.closest("[data-shipyard-build]")' not in main
    # Thin delegate remains
    assert "function initShipyard()" in main
    assert "GC.pages.shipyard?.init" in main or "GC.pages.shipyard.init" in main
    assert "GC.applyShipyardState = applyShipyardState" in main
    assert "GC.applyActionState = applyActionState" in main

    base = _read("templates/base.html")
    assert "js/pages/shipyard.js" in base
