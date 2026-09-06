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
    assert "if (!logistics && !sendPanel) return false;" in src
    assert "if (logistics && (!logisticsPanel || !syncLogisticsPresentation" in src


def test_fleet_template_renders_only_requested_heavy_mode():
    src = _read("templates/fleet.html")
    assert "{% if fleet_mode == 'send' %}" in src
    assert "{% if fleet_mode in ('collect', 'distribute') %}" in src
    assert 'data-fleet-mode-panel="send"' in src
    assert 'data-fleet-mode-panel="logistics"' in src
    assert 'id="logistics-page-state"' in src
    assert 'data-fleet-mode-tab="collect"' in src
    assert 'data-fleet-mode-tab="distribute"' in src
    assert 'data-fleet-mode-panel="send"{% if fleet_mode != \'send\' %}' not in src
