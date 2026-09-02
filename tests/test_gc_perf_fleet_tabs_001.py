"""GC-PERF-FLEET-TABS-001 — fleet mode tabs use the already-rendered DOM."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_fleet_fast_tabs_core_contract():
    src = _read("static/js/core/gc.js")
    assert "function installFleetFastTabs()" in src
    assert 'closest("[data-fleet-mode-tab]")' in src
    assert 'data-fleet-mode-panel="send"' in src
    assert 'data-fleet-mode-panel="logistics"' in src
    assert "global.history.replaceState" in src
    assert "event.preventDefault()" in src
    assert "event.stopImmediatePropagation()" in src
    assert "GC.modules && GC.modules.logistics" in src
    assert "syncLogisticsPresentation" in src


def test_fleet_template_keeps_local_mode_payload_available():
    src = _read("templates/fleet.html")
    assert 'data-fleet-mode-panel="send"' in src
    assert 'data-fleet-mode-panel="logistics"' in src
    assert 'id="logistics-page-state"' in src
    assert 'data-fleet-mode-tab="collect"' in src
    assert 'data-fleet-mode-tab="distribute"' in src
